from __future__ import annotations

import json
import logging
import os
import time
from typing import Any
from uuid import uuid4

from .model_config import DEFAULT_VIDEO_MODEL
from .model_router import MediaModelRouter, RouteTrace
from .image_output import prepare_image_output, reject_svg_output
from .image_production import explicit_image_disclaimer_requested, normalize_production_notes, prepare_production_image_request
from .image_routing import build_image_route, dispatch_image_route
from .html_assets import prepare_html_assets, referenced_image_ids
from .video_inputs import video_inputs

from .canvas import CanvasStore
from .providers.http import ProviderError, OpenAICompatibleSpeechProvider
from .agent_extensions import AgentExtensions


class DesignToolError(RuntimeError):
    """A user-actionable failure from a design Agent tool."""
    def __init__(self, message, *, stop_tool=False, response_received=False, error_code=None):
        super().__init__(message)
        self.stop_tool = stop_tool
        self.response_received = response_received
        self.error_code = error_code


def image_reference_ids(source_asset_id=None, source_asset_ids=None):
    from .asset_identity import asset_id
    source_asset_id = asset_id(source_asset_id)
    if isinstance(source_asset_ids, list):
        source_asset_ids = [asset_id(value) for value in source_asset_ids]
    if source_asset_ids is not None and (not isinstance(source_asset_ids, list) or any(not isinstance(value, str) or not value for value in source_asset_ids)):
        raise DesignToolError('source_asset_ids 必须为图像资产 ID 列表')
    return list(dict.fromkeys(([source_asset_id] if source_asset_id else []) + (source_asset_ids or [])))


class DesignToolRegistry:
    """Business tools exposed to the OpenAI Agents SDK.

    The registry is deliberately independent of the model provider. A model
    can decide *which* tool to call, while this layer owns project storage,
    asset lineage, knowledge retrieval and canvas persistence.
    """

    from .conversation_memory import TOOLS as MEMORY_TOOLS
    from .skills import SKILL_TOOLS
    TOOL_NAMES = SKILL_TOOLS + MEMORY_TOOLS + ("generation_reference_check",) + AgentExtensions.NAMES + (
        "search",
        "web_search",
        "list_models",
        "knowledge_search",
        "document_read",
        "document_part_inspect",
        "document_part_promote",
        "asset_search",
        "asset_inspect",
        "reference_search",
        "reference_inspect",
        "request_reference_selection",
        "conversation_read",
        "context_read",
        "generate_image",
        "generate_text",
        "generate_video",
        "generate_audio",
        "generate_3d",
        "generate_cad",
        "canvas_create_text",
        "canvas_create_html",
        "canvas_read",
        "report_progress",
        "delivery_verify",
        "budget_check",
        "repair_control",
        "canvas_create_node",
        "canvas_create_media",
        "canvas_update_node",
        "canvas_link_nodes",
        "request_clarification",
        "design_plan",
        "design_state",
    )

    def __init__(
        self,
        store,
        *,
        knowledge_store=None,
        research_store=None,
        asset_store=None,
        provider_registry=None,
        video_service=None,
        canvas_store: CanvasStore | None = None,
    ) -> None:
        self.store = store
        self.knowledge_store = knowledge_store
        self.research_store = research_store
        self.asset_store = asset_store
        self.provider_registry = provider_registry
        self.video_service = video_service
        self.canvas_store = canvas_store or CanvasStore(store)
        from .execution_store import ExecutionStore
        self.executions = ExecutionStore(store)
        from .skills import SkillService
        self.skills = SkillService(store)
        self.trace = None

    def execute(self, *, project_id: str, task_id: str | None, name: str, arguments: dict[str, Any] | None = None, preview_call_id: str | None = None, operation_id: str | None = None, agent_role: str = 'design') -> dict[str, Any]:
        from .conversation_memory import ConversationMemoryService, MemoryError
        if task_id and (name.startswith('generate_') or name in {'generation_reference_check', 'image_edit', 'canvas_create_text', 'canvas_create_html', 'canvas_create_node', 'canvas_create_media', 'canvas_update_node'}):
            context = self._task_input(project_id, task_id)
            if (context.get('designBatch') or {}).get('status') == 'needs_plan':
                from .design_batches import instruction
                return {'tool': name, 'status': 'planning_required', 'instruction': instruction(context), 'batch': context['designBatch']}
        if name == 'request_reference_selection' and agent_role != 'design':
            raise DesignToolError('由主设计 Agent 发起参考选择，研究角色只搜索和查看')
        if name in self.MEMORY_TOOLS:
            try:
                return ConversationMemoryService(self.store).execute(name,project_id,task_id,dict(arguments or {}),role=agent_role,operation_id=operation_id)
            except MemoryError as error:
                return ConversationMemoryService(self.store).failure(name,project_id,task_id,error,role=agent_role)
        if name == 'generation_reference_check':
            try:
                if task_id and self._task_input(project_id, task_id).get('referenceWorkflow', {}).get('status') == 'required':
                    from .reference_workflow import ReferenceWorkflow
                    result = ReferenceWorkflow(self.store, self.asset_store).preflight(self, project_id, task_id)
                    if result:
                        return {'tool': name, 'status': 'reference_selection_required', 'referenceSelection': result.structured_data['referenceSelection'], 'instruction': '等待用户选择或跳过参考，结束本轮。'}
                from .image_request_resolution import preflight_images
                return {**preflight_images(self, project_id, task_id, arguments or {}),
                        'referenceWorkflow': self._task_input(project_id, task_id).get('referenceWorkflow', {})}
            except (MemoryError, ValueError, DesignToolError) as error:
                from .image_request_resolution import error_result
                return error_result(name, error)
        if name in self.SKILL_TOOLS:
            # Skill operations commit their own receipt in the same transaction
            # as the catalogue/binding. Load/unload must not use args-only dedupe.
            return self.skills.execute(name, project_id, task_id, dict(arguments or {}), role=agent_role,
                                       operation_id=f'agent:{task_id}:{operation_id}' if operation_id else None)
        with self.executions.running_scope():
            return self._execute_claimed(project_id=project_id, task_id=task_id, name=name, arguments=arguments, preview_call_id=preview_call_id)

    def _execute_claimed(self, *, project_id, task_id, name, arguments=None, preview_call_id=None):
        self._validate_svg(task_id, name, arguments or {})
        from .svg_policy import validate_asset_references
        try:
            validate_asset_references(self, project_id, task_id, name, arguments or {})
        except ValueError as error:
            raise DesignToolError(str(error)) from error
        return self._execute_permitted(project_id=project_id, task_id=task_id, name=name, arguments=arguments, preview_call_id=preview_call_id)

    def _validate_svg(self, task_id, name, arguments):
        from .svg_policy import ensure_task_policy, configured_mode, derive_policy, validate_tool, contains_svg
        if name not in {'canvas_create_svg', 'generate_image', 'image_edit'} and (name not in {'canvas_create_html', 'canvas_create_text', 'canvas_update_node', 'canvas_create_node'} or not contains_svg(arguments)):
            return
        svg_policy = ensure_task_policy(self.store, task_id) if task_id else derive_policy(configured_mode(self.store), '')
        try:
            validate_tool(svg_policy, name, arguments)
        except ValueError as error:
            raise DesignToolError(str(error)) from error

    def _execute_permitted(self, *, project_id, task_id, name, arguments=None, preview_call_id=None):
        if task_id:
            from .task_policy import is_skill_management
            task_input = self._task_input(project_id, task_id)
            if task_input.get('missingDeliveryOnly') and name == 'design_plan':
                return {'tool': name, 'status': 'plan_reused', 'plan': task_input.get('designPlan'), 'batch': task_input.get('designBatch'), 'instruction': '本轮仅补齐已确认缺项，复用原计划，不改变设计要求或已保存产物。'}
            if is_skill_management(task_input.get('userMessage', ''), task_input) and (name.startswith('generate_') or name.startswith('canvas_') and name not in {'canvas_read','canvas_versions'} or name in AgentExtensions.MUTATIONS or name in {'web_search','web_read'}):
                raise DesignToolError('本轮只管理 Skill，请通过 Skill 工具保存专业流程，不生成设计产物或联网执行流程')
            if name in {'generate_image', 'generate_video', 'generate_3d', 'canvas_create_html', 'canvas_create_svg', 'image_edit'} or name == 'canvas_create_node' and (arguments or {}).get('kind') in {'image','html','video','3d'}:
                from .reference_workflow import ReferenceWorkflow
                if task_input.get('referenceWorkflow', {}).get('status') == 'required':
                    result = ReferenceWorkflow(self.store, self.asset_store).preflight(self, project_id, task_id)
                    if result:
                        return {'tool': name, 'status': 'reference_selection_required', 'referenceSelection': result.structured_data['referenceSelection'], 'instruction': '等待用户选择图片或明确跳过。现在结束本轮，不生成、补全或验收。'}
            creates = name.startswith('generate_') or name in {'image_edit','canvas_create_text','canvas_create_html','canvas_create_media','canvas_create_node','canvas_update_node'}
            if creates and task_input.get('memoryProtocol') and not (task_input.get('conversationMemory') or {}).get('analyzed') and not task_input.get('deliveryRepairOnly'):
                return {'tool':name,'status':'memory_required','instruction':'开始制作前，请用 conversation_memory_update 分析本轮需求并选用相关信息；从零设计可保存空选择。'}
        from .image_request_resolution import IMAGE_TOOLS, normalize_image_request, error_result
        original_arguments = arguments or {}
        preflight_started = time.monotonic()
        if name in IMAGE_TOOLS:
            if task_id:
                previous = self.executions.completed_result(task_id, name, original_arguments)
                if previous is not None:
                    if previous.get('stopTool') and previous.get('status') == 'failed':
                        raise DesignToolError(previous['message'], stop_tool=True, error_code=previous.get('errorCode'))
                    from .svg_policy import contains_svg, ERROR as SVG_ERROR
                    if contains_svg(previous): raise DesignToolError(SVG_ERROR)
                    return self._tool_result(previous, task_id, name)
            try:
                arguments = normalize_image_request(self, project_id, task_id, name, original_arguments)
            except (ValueError, DesignToolError) as error:
                return error_result(name, error)
        binding = {}
        context = {}
        if task_id and (name.startswith('generate_') or name in {'canvas_create_text', 'canvas_create_html', 'canvas_create_svg', 'canvas_create_media', 'canvas_create_node', 'canvas_update_node', 'image_edit', 'export_deliverable'}):
            context = self._task_input(project_id, task_id)
            plan = context.get('designPlan') or {}
            if not context.get('deliveryReviewOnly') and not context.get('deliveryRepairOnly') and ((context.get('designPlanning') or {}).get('required') or plan) and not plan.get('ready'):
                return {'tool': name, 'status': 'planning_required', 'instruction': '先调用 design_plan 明确本轮目标、交付清单和验收条件；存在关键未决问题时使用 request_clarification。计划就绪后再生成，不把一张概念图当作整套设计。', 'guide': context.get('designPlanning')}
            from .deliverable_tracking import assign_delivery
            ready_ids = set()
            if any(item.get('dependsOn') for item in plan.get('deliverables', [])):
                from .delivery import DeliveryService
                dependency_report = DeliveryService(self.store, self.asset_store, self.canvas_store).inspect_task(project_id, task_id)
                ready_ids = {item['id'] for item in dependency_report['deliverables'] if item['status'] in {'ready', 'passed', 'needs_review'}}
            binding, blocked = assign_delivery(context, name, arguments or {}, self.canvas_store.load(project_id)['nodes'], ready_ids)
            if blocked: return {'tool': name, **blocked}
            missing_scope = context.get('missingDeliveryOnly')
            if missing_scope and (not binding or not set(binding['itemIds']).issubset(missing_scope['itemIds'])):
                return {'tool': name, 'status': 'batch_scope_required', 'instruction': '仅可制作本轮尚未生成的交付项；已保存产物保持不变。'}
            batch = context.get('designBatch') or {}
            revision_image = (batch.get('intent') == 'revise' and name == 'generate_image'
                              and (arguments or {}).get('output_mode') == 'create'
                              and bool(image_reference_ids((arguments or {}).get('source_asset_id'),(arguments or {}).get('source_asset_ids'))))
            if batch.get('intent') == 'revise' and binding and not (arguments or {}).get('canvas_node_id') and not (arguments or {}).get('node_id') and not revision_image:
                return {'tool': name, 'status': 'batch_scope_required', 'instruction': '本轮修改上一批图像时，请将原图资产作为 source_asset_id，使用 output_mode=create 生成新节点并保留原图。', 'batch': batch}
            if binding and name.startswith(('generate_', 'canvas_create_')) and not (arguments or {}).get('canvas_node_id') and (arguments or {}).get('output_mode') != 'edit' and not revision_image:
                from .delivery import DeliveryService
                report = DeliveryService(self.store, self.asset_store, self.canvas_store).inspect_task(project_id, task_id)
                board = {n['id']: n for n in self.canvas_store.load(project_id)['nodes']}
                for item in report.get('cumulativeArtifacts', report['artifacts']):
                    saved = board[item['nodeId']]
                    old = saved.get('data', {}).get('deliveryBinding', {})
                    if item['ready'] and old.get('scopeId') == binding['scopeId'] and set(binding['itemIds']).issubset(old.get('itemIds', [])):
                        prior_asset = self.asset_store.get_asset(project_id=project_id, asset_id=item['assetId']) if self.asset_store and item.get('assetId') else None
                        if prior_asset and prior_asset.get('mime') == 'image/svg+xml':
                            return {'tool': name, 'status': 'representation_required', 'instruction': '旧交付项是 SVG，已禁用复用。需要更新为真实图像时，请把可用原图作为 source_asset_id，使用 generate_image 新建节点；不要把旧 SVG 计为本轮已完成。'}
                        return {'tool': name, 'status': 'succeeded', 'reused': True, 'node': saved, 'assetId': item.get('assetId'), 'outputKind': item['kind'], 'instruction': '该交付项已有产物，已复用。需要修改图像时将它作为 source_asset_id，并用 output_mode=create 生成新节点。'}
            batch = context.get('designBatch') or {}
            if batch and binding and not set(binding['itemIds']).issubset(batch['itemIds']):
                return {'tool': name, 'status': 'batch_scope_required', 'instruction': '这次调用不属于本批执行项。按 design_plan 返回的 batch.itemIds 制作本批；累计清单中的旧资产保留复用。', 'batch': batch}
        if task_id and self.provider_registry and getattr(self.provider_registry, 'catalog', None):
            from .budget import BudgetService
            BudgetService(self.store,self.provider_registry.catalog).guard_repair_tool(task_id,name,arguments or {})
        # Read tools remain fresh. Mutations commit their receipt before the
        # worker can lose its HTTP connection or be restarted.
        fingerprint = None
        resources = []
        if task_id and (name in AgentExtensions.MUTATIONS or name.startswith("generate_") or name.startswith("canvas_") and name not in {'canvas_read','canvas_versions'}):
            try:
                target = (arguments or {}).get('canvas_node_id') or (arguments or {}).get('node_id')
                if name not in IMAGE_TOOLS: target = target or (context.get('canvasParams') or {}).get('canvasNodeId')
                resources = ([f'node:{target}'] if target else []) + [f"delivery:{binding.get('scopeId')}:{item}" for item in binding.get('itemIds', [])]
                contract = context.get('deliveryContract') or []
                if name == 'generate_video' and not resources and len(contract) == 1 and contract[0].get('kind') == 'video' and contract[0].get('count', 1) == 1:
                    resources = ['delivery:single-video']
                fingerprint, previous = self.executions.claim(task_id, name, original_arguments, resources=resources)
            except RuntimeError as error:
                raise DesignToolError(str(error)) from error
            if previous is not None:
                if previous.get('stopTool') and previous.get('status') == 'failed':
                    raise DesignToolError(previous['message'], stop_tool=True, error_code=previous.get('errorCode'))
                # Replaying a legacy SVG generator result must not publish it
                # again after the product-wide prohibition.
                from .svg_policy import contains_svg, ERROR as SVG_ERROR
                if contains_svg(previous):
                    raise DesignToolError(SVG_ERROR)
                return self._tool_result(previous, task_id, name)
        execution_state = {"fingerprint": fingerprint, "resources": resources}
        from .node_context import active_task
        version_token = active_task.set(task_id)
        try:
            # Receipts use original arguments; dispatch re-resolves and validates
            # sources without changing the historical idempotency identity.
            if name in IMAGE_TOOLS:
                from .image_request_resolution import prepare_image_request, check_preflight
                try:
                    arguments = prepare_image_request(self, project_id, task_id, name, original_arguments, binding)
                    check_preflight(self, project_id, task_id, name, original_arguments, arguments)
                except (ValueError, DesignToolError) as error:
                    if fingerprint: self.executions.reject(task_id, fingerprint)
                    return error_result(name, error)
            else:
                arguments = self._focused_arguments(project_id, task_id, name, arguments or {}, delivery_binding=binding)
            if name == 'canvas_create_html' and task_id and preview_call_id:
                from .html_generation import HtmlGenerationPreviews
                arguments = HtmlGenerationPreviews(self.store, self.canvas_store).bind(project_id, task_id, preview_call_id, arguments)
            if name in IMAGE_TOOLS:
                from .task_timing import record_timing
                record_timing(self.store, task_id, 'imagePreflightMs', preflight_started)
            result = self._execute(project_id=project_id, task_id=task_id, name=name, arguments={**(arguments or {}), "_execution_state": execution_state, '_delivery_binding': binding})
            if binding and result.get('node'):
                result['node'] = self.canvas_store.update_node(project_id, result['node']['id'], {'data': {'deliveryBinding': binding}})
        except Exception as error:
            from .image_parameters import ImageParameterError
            from .image_reference_design import ReferenceDesignError
            if isinstance(error,(ImageParameterError,ReferenceDesignError)) and not execution_state.get('submitted'):
                if fingerprint: self.executions.reject(task_id,fingerprint)
                return {'tool':name,'status':error.code,'instruction':str(error)}
            logging.getLogger(__name__).exception('Design tool failed: project=%s task=%s tool=%s', project_id, task_id, name)
            # Validation before dispatch and explicit upstream rejections are
            # safe to correct. Timeouts/connection loss remain unconfirmed.
            rejected = getattr(error, "status_code", None) in {400, 401, 402, 403, 404, 405, 413, 415, 422, 429}
            access_rejected = name in IMAGE_TOOLS and isinstance(error, ProviderError) and error.status_code in {401, 402, 403}
            if access_rejected:
                # Credentials, balance and access cannot be fixed by rewriting
                # a prompt. Persist a task-wide stop, including after restart.
                error.stop_tool = True
                error.error_code = 'image_provider_access'
            if fingerprint and (getattr(error, 'response_received', False) or access_rejected):
                # The provider has returned and may already have charged. Keep
                # a terminal failure receipt, never an unknown/running request
                # or a retryable rejection that could submit another charge.
                self.executions.complete(task_id, fingerprint, {
                    'tool': name, 'status': 'failed', 'message': str(error),
                    'errorCode': error.error_code, 'stopTool': True, 'retryable': False,
                    'responseReceived': bool(getattr(error, 'response_received', False) or execution_state.get('submitted')),
                })
            elif fingerprint and (not execution_state.get("submitted") or rejected):
                self.executions.reject(task_id, fingerprint)
            raise
        finally:
            active_task.reset(version_token)
        result = self._tool_result(result, task_id, name)
        if fingerprint:
            self.executions.complete(task_id, fingerprint, result)
        if task_id and result.get('node') and self._task_input(project_id,task_id).get('memoryProtocol'):
            from .conversation_memory import ConversationMemoryService
            memory=ConversationMemoryService(self.store)
            memory.record_output(project_id,task_id,result)
            result['memoryContext']=memory.runtime(project_id,task_id,images=True)
        if task_id and result.get('node') and name != 'canvas_read' and self._task_input(project_id, task_id).get('designPlan'):
            self.delivery_verify(project_id=project_id, task_id=task_id)
            latest = self._task_input(project_id, task_id)
            result['batchContext'] = {'batch': latest.get('designBatch'), 'progress': latest.get('deliveryProgress', [])}
        return result

    def _focused_arguments(self, project_id, task_id, name, arguments, delivery_binding=None):
        """Enforce reference scope and require a semantic create/edit choice."""
        from .image_request_resolution import IMAGE_TOOLS, normalize_image_request
        if name in IMAGE_TOOLS:
            return normalize_image_request(self, project_id, task_id, name, arguments, delivery_binding)

        if not task_id: return arguments
        scoped = {'asset_inspect','canvas_versions','canvas_restore_node','canvas_update_node','canvas_link_nodes','canvas_create_media','export_deliverable','image_edit','media_edit','transcribe_audio'}
        generators = {'generate_image','generate_video','generate_audio','generate_text','generate_3d','generate_cad','canvas_create_text','canvas_create_html','canvas_create_svg'}
        if name not in scoped | generators: return arguments
        from .task_focus import TaskFocus
        context = self._task_input(project_id,task_id)
        service = TaskFocus(self.store,self.canvas_store)
        focus = service.resolve(project_id,task_id,context)
        args = dict(arguments)
        canvas = context.get('canvasParams') or {}
        canvas_generators = {f"generate_{canvas.get('kind')}", f"canvas_create_{canvas.get('kind')}"}
        if canvas.get('canvasNodeId') and name in canvas_generators:
            # The node composer owns the output target and reference snapshot.
            # An Agent must not omit inputs or overwrite an upstream reference.
            args['canvas_node_id'] = canvas['canvasNodeId']
            if name == 'generate_video':
                ids = image_reference_ids(canvas.get('source_asset_id'), canvas.get('source_asset_ids'))
                if name == 'generate_image' and context.get('referenceWorkflow', {}).get('status') == 'selected':
                    ids = list(dict.fromkeys([*ids, *context['referenceWorkflow'].get('assetIds', [])]))
                if ids or 'source_asset_ids' in canvas:
                    args['source_asset_id'], args['source_asset_ids'] = ids[0] if ids else None, ids
                if name == 'generate_video' and (ids or 'source_asset_ids' in canvas or 'last_frame_asset_id' in canvas):
                    args['last_frame_asset_id'] = canvas.get('last_frame_asset_id') or (ids[1] if len(ids) == 2 else None)
                    args['params'] = {k: v for k, v in (args.get('params') or {}).items() if k not in {'last_frame_asset_id', 'end_frame_asset_id'}}
        if name == 'generate_video':
            try:
                first, last, options = video_inputs(args.get('source_asset_id'), args.get('source_asset_ids'), args.get('last_frame_asset_id'), args.get('params'))
            except ValueError as error:
                raise DesignToolError(str(error)) from error
            args.update(source_asset_id=first, last_frame_asset_id=last, params=options)
        if name == 'generate_cad':
            ids = image_reference_ids(canvas.get('source_asset_id'), canvas.get('source_asset_ids'))
            if ids: args['reference_asset_ids'] = list(dict.fromkeys([*(args.get('reference_asset_ids') or []), *ids]))
        if name in generators | {'image_edit','media_edit'}:
            target = args.get('canvas_node_id')
            choice = args.get('output_mode')
            if choice not in {None,'edit','create'}: raise DesignToolError('output_mode 必须为 edit 或 create')
            if target and not choice:
                node = next((n for n in self.canvas_store.load(project_id)['nodes'] if n['id']==target),{})
                blank_input = target==(context.get('canvasParams') or {}).get('canvasNodeId') and not any(node.get('data',{}).get(k) for k in ('assetId','asset','text','html'))
                choice = 'create' if blank_input else 'edit'
                args['output_mode']=choice
            if name == 'canvas_create_html' and not target and not choice and focus['hasReferences'] and not focus.get('missingNodeIds'):
                # Image/file references can be embedded in a new page, but cannot
                # be overwritten by HTML. Existing HTML targets stay explicit.
                focused_nodes = focus.get('nodes') or []
                if not focus['nodeIds'] or focused_nodes and all(n.get('data', {}).get('kind') == 'image' for n in focused_nodes):
                    choice = args['output_mode'] = 'create'
            if focus['mode']!='none' and not target and not choice:
                raise DesignToolError('请先根据用户语义区分修改对象与参考资料：图像调整将原图作为来源并设置 output_mode=create；其他内容的原位修改才明确 canvas_node_id。')
            if choice=='create' and target and target!=(context.get('canvasParams') or {}).get('canvasNodeId'):
                raise DesignToolError('新建产物不能同时覆盖已有节点；请移除 canvas_node_id 或明确选择 edit')
            # No keyword-based target guessing: the model must identify the node.
            if choice=='edit' and not target and focus['nodeIds']:
                raise DesignToolError('请明确要修改的 canvas_node_id；引用也可能只是风格参考，不能自动选择目标')
        node_ids = [args[k] for k in ('canvas_node_id','node_id','source_node_id','target_node_id') if args.get(k)] + list(args.get('node_ids') or [])
        asset_ids = [args[k] for k in ('source_asset_id','last_frame_asset_id','asset_id') if args.get(k)] + list(args.get('asset_ids') or []) + image_reference_ids(None, args.get('source_asset_ids')) + list(args.get('reference_asset_ids') or [])
        if name == 'canvas_create_html':
            asset_ids += referenced_image_ids(args.get('html'))
        if name == 'canvas_update_node':
            asset_ids += referenced_image_ids((args.get('patch') or {}).get('data', {}).get('html'))
        if name=='export_deliverable':
            asset_ids += [id for slide in args.get('slides') or [] for id in slide.get('imageAssetIds') or []]
        if name=='image_edit' and (args.get('params') or {}).get('maskAssetId'):
            asset_ids.append(args['params']['maskAssetId'])
        service.validate_ids(project_id,task_id,context,node_ids=node_ids,asset_ids=asset_ids)
        if name=='export_deliverable' and not args.get('node_ids') and not args.get('slides') and focus['mode']!='none' and not focus['allowOverview']:
            if len(focus['nodeIds'])!=1: raise DesignToolError('请明确要导出的 node_ids，不能默认导出整张画布')
            args['node_ids']=focus['nodeIds']
        return args

    @staticmethod
    def _tool_result(result, task_id, name):
        # UI calls may need the full board. Agent mutation receipts need only
        # their changed node/edge, never every unrelated node's content.
        if task_id and name != 'canvas_read' and isinstance(result,dict):
            def compact(value):
                if isinstance(value, dict): return {key: compact(item) for key, item in value.items() if key != 'htmlAssets'}
                if isinstance(value, list): return [compact(item) for item in value]
                return value
            return compact({key:value for key,value in result.items() if key!='canvas'})
        return result

    def _execute(self, *, project_id: str, task_id: str | None, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.store.get_project(project_id) is None:
            raise DesignToolError("项目不存在")
        args = arguments if isinstance(arguments, dict) else {}
        context = self._task_input(project_id, task_id) if task_id else {}
        if context.get('deliveryRepairOnly') and (name in AgentExtensions.MUTATIONS or name.startswith('generate_') or name.startswith('canvas_') and name not in {'canvas_read','canvas_versions'}):
            target = args.get('canvas_node_id') or args.get('node_id')
            if name not in {'canvas_create_html','canvas_create_text','canvas_update_node','generate_cad'} or target not in context.get('deliveryRepairNodes', []):
                raise DesignToolError('定向修复仅能修改本轮原节点，不能新建产物或提交收费生成')
        if name in AgentExtensions.NAMES:
            return AgentExtensions(self).execute(name,project_id,task_id,**args)
        method = {
            "search": self.search,
            "web_search": self.web_search,
            "list_models": self.list_models,
            "knowledge_search": self.knowledge_search,
            "document_read": self.document_read,
            "document_part_inspect": self.document_part_inspect,
            "document_part_promote": self.document_part_promote,
            "asset_search": self.asset_search,
            "asset_inspect": self.asset_inspect,
            "reference_search": self.reference_search,
            "reference_inspect": self.reference_inspect,
            "request_reference_selection": self.request_reference_selection,
            "conversation_read": self.conversation_read,
            "context_read": self.context_read,
            "generate_image": self.generate_image,
            "generate_text": self.generate_text,
            "generate_video": self.generate_video,
            "generate_audio": self.generate_audio,
            "generate_3d": self.generate_3d,
            "generate_cad": self.generate_cad,
            "canvas_create_text": self.canvas_create_text,
            "canvas_create_html": self.canvas_create_html,
            "canvas_read": self.canvas_read,
            "report_progress": self.report_progress,
            "delivery_verify": self.delivery_verify,
            "budget_check": self.budget_check,
            "repair_control": self.repair_control,
            "canvas_create_node": self.canvas_create_node,
            "canvas_create_media": self.canvas_create_media,
            "canvas_update_node": self.canvas_update_node,
            "canvas_link_nodes": self.canvas_link_nodes,
            "request_clarification": self.request_clarification,
            "design_plan": self.design_plan,
            "design_state": self.design_state,
        }.get(str(name))
        if method is None:
            raise DesignToolError(f"不支持的设计工具：{name}")
        if name not in {"generate_image", "generate_video", "generate_audio", "generate_3d"}:
            return method(project_id=project_id, task_id=task_id, **args)
        args = dict(args)
        kind = name.removeprefix("generate_")
        if kind == 'image':
            # Image adapters notify only after references, credentials, request
            # encoding and the metered provider's budget check have succeeded.
            return method(project_id=project_id, task_id=task_id, **args)
        pending_data = {"generating": True, "draft": False, "error": "", "status": "生成中", "params": args.get("params") or {}}
        if args.get('_delivery_binding'): pending_data['deliveryBinding'] = args['_delivery_binding']
        if args.get("canvas_node_id"):
            pending = self.canvas_store.update_node(project_id, args["canvas_node_id"], {"data": pending_data})
        else:
            pending = self.canvas_store.create_node(project_id, kind=kind, title={"image": "生成图像", "video": "生成视频", "audio": "生成音频", "3d": "生成模型"}[kind], data=pending_data, task_id=task_id)
            args["canvas_node_id"] = pending["id"]
        try:
            result = method(project_id=project_id, task_id=task_id, **args)
            if not result.get("assetId"):
                self.canvas_store.update_node(project_id, pending["id"], {"data": {"generating": False, "status": "任务已提交", "job": result.get("job")}})
            return result
        except Exception as error:
            self.canvas_store.update_node(project_id, pending["id"], {"data": {"generating": False, "error": str(error), "status": "生成失败"}})
            raise

    def reference_search(self, **kwargs):
        from .reference_workflow import reference_search
        return reference_search(self, **kwargs)

    def reference_inspect(self, *, project_id, task_id, reference_id, **_):
        from .reference_library import ReferenceLibraryStore
        context = self._task_input(project_id, task_id)
        if reference_id not in context.get('referenceCandidates', []):
            raise DesignToolError('请先搜索并选择本轮相关的参考图片')
        return ReferenceLibraryStore(self.store).inspect(reference_id)

    def request_reference_selection(self, *, project_id, task_id, items=None, intro=None, **_):
        from .reference_workflow import ReferenceWorkflow
        context = self._task_input(project_id, task_id)
        if any(item.get('id') not in context.get('referenceCandidates', []) for item in items or []):
            raise DesignToolError('只能展示本轮实际检索到的参考图片')
        context['referenceWorkflow'] = {**context.get('referenceWorkflow', {}), 'status': 'required'}
        with self.store._connect() as db:
            db.execute('UPDATE tasks SET input_json=? WHERE id=?', (json.dumps(context, ensure_ascii=False), task_id))
        card = ReferenceWorkflow(self.store, self.asset_store).present(project_id, task_id, items or [], **({'intro': intro} if intro else {}))
        if card is None:
            return {'tool': 'request_reference_selection', 'awaitingUser': False, 'status': 'ready',
                    'referenceWorkflow': self._task_input(project_id, task_id)['referenceWorkflow'],
                    'instruction': '可选参考为空，按已确认需求继续设计；不展示空卡片。'}
        return {'tool': 'request_reference_selection', 'referenceSelection': card, 'awaitingUser': True}

    def design_plan(self, *, project_id, task_id=None, plan=None, change_reason=None, reuse_current=False, expected_revision=None, expected_scope_id=None, **_):
        context = self._task_input(project_id, task_id)
        if plan is None:
            from .design_batches import refresh, instruction
            context = refresh(self.store, project_id, task_id) if task_id else context
            if reuse_current and (context.get('designPlan') or {}).get('ready') and (context.get('designBatch') or {}).get('status') != 'needs_plan':
                from .design_planning import reused_plan_receipt
                return reused_plan_receipt(context)
            return {'tool': 'design_plan', 'status': 'ready' if (context.get('designPlan') or {}).get('ready') and (context.get('designBatch') or {}).get('status') != 'needs_plan' else 'needs_plan', 'guide': context.get('designPlanning'), 'plan': context.get('designPlan'), 'baseline': context.get('planBaseline'), 'state': context.get('designState'), 'continuation': context.get('continuation'), 'batch': context.get('designBatch'), 'progress': context.get('deliveryProgress', []), 'instruction': instruction(context)}
        from .design_planning import save_design_plan
        try:
            return save_design_plan(self.store, project_id, task_id, plan, reuse_ready=not str(change_reason or '').strip(), expected_revision=expected_revision, expected_scope_id=expected_scope_id)
        except ValueError as error:
            return {'tool': 'design_plan', 'status': 'invalid', 'instruction': str(error)[:1000]}

    def design_state(self, *, project_id, task_id, decisions=None, brief=None, **_):
        from .design_state import read_state, record_decisions
        try:
            state = record_decisions(self.store, project_id, task_id, decisions or [], brief=brief) if decisions or brief is not None else read_state(self.store, project_id, task_id)
            return {'tool': 'design_state', 'state': state, 'status': 'recorded'}
        except ValueError as error:
            return {'tool': 'design_state', 'status': 'invalid', 'instruction': str(error)}

    def _record_document_usage(self, project_id, task_id, document_id, result, *, read_locators=None,
                               inspected_part_id=None, promoted_part_id=None, promoted_asset_id=None):
        if not task_id:
            return
        with self.store._connect() as db:
            row = db.execute("SELECT input_json FROM tasks WHERE id=? AND project_id=?", (task_id, project_id)).fetchone()
            if not row:
                return
            context = json.loads(row[0] or "{}")
            snapshots = context.get("documentReferenceSnapshots")
            if not isinstance(snapshots, list):
                snapshots = []
            document = result.get("document") if isinstance(result, dict) else None
            current = next((item for item in snapshots if item.get("documentId") == document_id), None)
            if current is None:
                current = {"documentId": document_id, "readLocators": [], "inspectedPartIds": [],
                           "promotedPartIds": [], "promotedAssetIds": []}
                snapshots.append(current)
            if isinstance(document, dict):
                current.update({"checksum": document.get("checksum"), "parserVersion": document.get("parserVersion"),
                                "scope": document.get("scope"), "status": document.get("status")})
            for key, values in (("readLocators", read_locators or []),
                                ("inspectedPartIds", [inspected_part_id] if inspected_part_id else []),
                                ("promotedPartIds", [promoted_part_id] if promoted_part_id else []),
                                ("promotedAssetIds", [promoted_asset_id] if promoted_asset_id else [])):
                existing = current.get(key) if isinstance(current.get(key), list) else []
                current[key] = list(dict.fromkeys([*existing, *[value for value in values if value]]))[-100:]
            context["documentReferenceSnapshots"] = snapshots[-20:]
            db.execute("UPDATE tasks SET input_json=? WHERE id=? AND project_id=?", (json.dumps(context, ensure_ascii=False), task_id, project_id))

    def _task_input(self, project_id, task_id):
        with self.store._connect() as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='tasks'").fetchone():
                return {}
            row = db.execute("SELECT input_json FROM tasks WHERE id=? AND project_id=?", (task_id, project_id)).fetchone()
        return json.loads(row[0]) if row else {}

    def list_models(self, *, project_id, task_id=None, kind=None, offset=0, **_):
        context = self._task_input(project_id, task_id)
        current = context.get("textProvider") or {}
        catalog = getattr(self.provider_registry, "catalog", None)
        if not catalog:
            raise DesignToolError("尚未保存本地模型目录，请先在设置同步")
        records = catalog.get(current.get("key", ""), current.get("baseUrl", "")).get("modelCatalog", [])
        records = [item for item in records if not kind or kind in item["kinds"]]
        offset = max(0, int(offset))
        return {"models": [{"id": item["id"], "name": item["name"], "kinds": item["kinds"]} for item in records[offset:offset+100]], "total": len(records), "nextOffset": offset+100 if len(records) > offset+100 else None}

    def web_search(self, *, project_id, task_id=None, query, limit=8, _search_context=None, _model_context=None, **_):
        from .providers.web_search import OpenAIWebSearchProvider
        context = self._task_input(project_id, task_id)
        if not context.get("allowExternalNetwork"):
            raise DesignToolError("此任务未开启联网研究")
        if not str(query).strip():
            raise DesignToolError("搜索内容不能为空")
        catalog = self.provider_registry.catalog
        current = context.get("textProvider") or {}
        runtime = _model_context if isinstance(_model_context, dict) else _search_context if isinstance(_search_context, dict) else {}
        if runtime.get('model'):
            from .model_config import EndpointModel
            active = EndpointModel(provider=runtime.get('provider', 'inherit'), baseUrl=runtime.get('baseUrl', ''), model=runtime['model'])
            if active.provider != 'inherit':
                current = {'key': active.provider, 'baseUrl': active.baseUrl, 'model': active.model}
        config = catalog.settings().search
        key = current.get("key") if config.provider == "inherit" else config.provider
        base = config.baseUrl or (current.get("baseUrl") if key == current.get("key") else None)
        desired = (config.model
                   or (runtime.get('model') or current.get("model") if config.provider == 'inherit'
                       else catalog.settings().tiers["STANDARD"].primary.model)
                   or catalog.settings().tiers["STANDARD"].primary.model)
        adapter = self.provider_registry.text(key, base_url=base, model=desired)
        base = adapter.base_url
        model = catalog.resolve_id(key, base, desired)
        if not model:
            raise DesignToolError("联网搜索模型不在本地目录中，请在模型路由设置中选择")
        timeout = min(60., max(1., float(runtime.get('timeoutSeconds', 60))))
        search = OpenAIWebSearchProvider(base, key, model, self.provider_registry.credentials, api=config.api, timeout=timeout,
                                       max_output_tokens=min(2048, catalog.settings().maxOutputTokens))
        fingerprint = None
        if task_id:
            try:
                fingerprint, previous = self.executions.claim(task_id, 'web_search', {
                    'query': str(query).strip()[:12000], 'limit': min(20, max(1, int(limit))),
                    'provider': key, 'baseUrl': base, 'model': model, 'api': config.api,
                })
            except RuntimeError as error:
                raise DesignToolError(str(error), stop_tool=True) from error
            if previous is not None:
                if previous.get('stopTool'): raise DesignToolError(previous['message'], stop_tool=True)
                return previous
        from .budget import BudgetService
        budget=BudgetService(self.store,catalog)
        reservation, result, rejected, dispatched = None, None, False, False
        call_started = time.monotonic()
        trace_error = None
        def progress(message):
            if self.trace and task_id: self.trace(task_id, 'progress', message)
        def cancelled():
            if not task_id: return False
            with self.store._connect() as db:
                row = db.execute('SELECT status FROM tasks WHERE id=?', (task_id,)).fetchone()
            return not row or row['status'] in {'cancelled', 'failed', 'succeeded'}
        try:
            reservation=budget.reserve(task_id,provider=key,base_url=base,model=model,kind='search',usage={'input_tokens':len(str(query).encode())+2000,'output_tokens':search.max_output_tokens},units={'requests':1,'searchCalls':1})
            dispatched = True
            result = {'tool': 'web_search', **search.search(str(query).strip()[:12000], limit=min(20, max(1, int(limit))), progress=progress, should_cancel=cancelled)}
            if fingerprint: self.executions.complete(task_id, fingerprint, result)
            return result
        except ProviderError as error:
            trace_error = error
            rejected = getattr(error, 'rejected', False)
            stop = getattr(error, 'stop_tool', False) or not dispatched
            if fingerprint:
                if stop:
                    self.executions.complete(task_id, fingerprint, {'status':'unavailable','sources':[], 'message':str(error), 'stopTool':True, 'retryable':False,
                        'instruction':'本轮不要重复搜索或改写查询重试；使用已保存来源，缺失事实明确标记未核验。'})
                else: self.executions.reject(task_id, fingerprint)
            raise DesignToolError(str(error), stop_tool=stop) from error
        finally:
            if task_id:
                RouteTrace(self.store).append(task_id, {
                    'call_kind': 'web_search',
                    'tier': runtime.get('tier') or 'STANDARD',
                    'provider': key,
                    'model': model,
                    'api': config.api,
                    'route_source': runtime.get('routeSource') or ('active_agent' if config.provider == 'inherit' else 'explicit_search'),
                    'started_at': time.time() - (time.monotonic() - call_started),
                    'latency_ms': round((time.monotonic() - call_started) * 1000),
                    'status': 'succeeded' if result is not None else 'failed',
                    'error_type': 'provider' if trace_error is not None else None,
                    'error_message': str(trace_error)[:600] if trace_error is not None else None,
                    'submitted': dispatched,
                    'billing_certainty': 'settled' if result is not None else 'not_submitted' if not dispatched or rejected else 'unknown',
                })
            if rejected or not dispatched:
                if reservation: budget.settle(task_id, reservation['reservationId'], 0)
            elif self.provider_registry.billing:
                raw = getattr(search, "last_response", {})
                ledger=self.provider_registry.billing.record(provider=key, base_url=base, model=model, kind="search",
                    usage=raw.get("usage") or {}, units={"requests": 1, "searchCalls": getattr(search, "search_calls", None)},
                    completed=result is not None)
                if reservation: budget.settle(task_id,reservation['reservationId'],ledger.get('points'))

    def search(self, *, project_id: str, task_id: str | None = None, query: str, limit: int = 8, **_: Any) -> dict[str, Any]:
        clean_query = str(query or "").strip()
        if not clean_query:
            raise DesignToolError("search.query 不能为空")
        clean_limit = max(1, min(int(limit or 8), 20))
        results: list[dict[str, Any]] = []
        if self.knowledge_store is not None:
            try:
                results.extend(self.knowledge_store.vector_search_for_project(project_id=project_id, query=clean_query, limit=clean_limit))
            except Exception:
                results.extend(self.knowledge_store.search(project_id=project_id, query=clean_query, limit=clean_limit))
        if self.research_store is not None:
            needle = clean_query.casefold()
            for source in self.research_store.list_sources(project_id):
                haystack = f"{source.get('title') or ''} {source.get('uri') or ''}".casefold()
                if needle in haystack:
                    results.append({
                        "sourceId": source.get("id"),
                        "title": source.get("title"),
                        "uri": source.get("uri"),
                        "rightsStatus": source.get("rightsStatus"),
                        "sourceType": source.get("sourceType"),
                    })
        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for result in results:
            key = str(result.get("chunkId") or result.get("sourceId") or result.get("uri") or json.dumps(result, ensure_ascii=False, sort_keys=True))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(result)
        return {"tool": "search", "query": clean_query, "results": deduped[:clean_limit], "count": min(len(deduped), clean_limit)}

    def conversation_read(self, *, project_id: str, task_id: str | None = None, query: str = "", turn_id: str | None = None, offset: int = 0, limit: int = 5, text_offset: int = 0, **_: Any) -> dict[str, Any]:
        from .conversation_context import ConversationContext
        from .task_focus import TaskFocus
        try:
            result=ConversationContext(self.store).read(project_id, task_id, query=query, turn_id=turn_id, offset=offset, limit=limit, text_offset=text_offset)
            focus=TaskFocus(self.store,self.canvas_store)
            nodes,assets=[],[]
            for turn in result['results']:
                for item in [*(turn.get('artifacts') or []),*(turn.get('references') or [])]:
                    if item.get('projectId',project_id)!=project_id: continue
                    node=item.get('nodeId') or (item.get('id') if item.get('referenceType')=='node' else None)
                    asset=item.get('assetId') or (item.get('id') if item.get('referenceType')=='asset' else None)
                    if node: nodes.append(node)
                    if asset: assets.append(asset)
            focus.remember_candidates(project_id,task_id,'node',nodes,limit=None)
            focus.remember_candidates(project_id,task_id,'asset',assets,limit=None)
            return {"tool": "conversation_read", **result}
        except ValueError as error:
            raise DesignToolError(str(error)) from error

    def context_read(self, *, project_id, task_id, kind='evidence', ids=None, query='', offset=0, **_):
        from .project_context import ProjectContextResolver
        if kind == 'history':
            return self.conversation_read(project_id=project_id, task_id=task_id, query=query, turn_id=(ids or [None])[0], text_offset=offset)
        if kind == 'artifacts':
            return self.canvas_read(project_id=project_id, task_id=task_id, node_ids=ids, query=query, text_offset=offset)
        if kind != 'evidence':
            raise DesignToolError('context_read.kind 必须为 evidence/history/artifacts')
        return {'tool': 'context_read', 'results': ProjectContextResolver(self.store).evidence(project_id, task_id, query, ids, offset), 'notice': '正文与搜索摘要分别标记，不能将模型推断当成事实来源。'}

    def knowledge_search(self, *, project_id: str, task_id: str | None = None, query: str, limit: int = 8, mode: str = "hybrid", **_: Any) -> dict[str, Any]:
        clean_query = str(query or "").strip()
        if not clean_query:
            raise DesignToolError("knowledge_search.query 不能为空")
        clean_limit = max(1, min(int(limit or 8), 20))
        if self.knowledge_store is None:
            return {"tool": "knowledge_search", "query": clean_query, "results": [], "count": 0}
        if str(mode).lower() in {"lexical", "keyword"}:
            results = self.knowledge_store.search(project_id=project_id, query=clean_query, limit=clean_limit)
        else:
            results = self.knowledge_store.vector_search_for_project(project_id=project_id, query=clean_query, limit=clean_limit)
            if not results:
                results = self.knowledge_store.search(project_id=project_id, query=clean_query, limit=clean_limit)
        return {"tool": "knowledge_search", "query": clean_query, "mode": mode, "results": results, "count": len(results)}

    def document_read(self, *, project_id: str, task_id: str | None = None, document_id: str,
                      cursor: int = 0, locator: str | None = None, limit: int = 30, **_: Any) -> dict[str, Any]:
        if self.knowledge_store is None:
            raise DesignToolError("知识文档服务不可用")
        try:
            result = self.knowledge_store.agent_read(project_id=project_id, task_id=task_id, document_id=document_id,
                                                     cursor=cursor, locator=locator, limit=limit)
        except ValueError as error:
            raise DesignToolError(str(error)) from error
        self._record_document_usage(project_id, task_id, document_id, result, read_locators=[block.get("locator") for block in result.get("blocks", [])])
        return {"tool": "document_read", **result}

    def document_part_inspect(self, *, project_id: str, task_id: str | None = None,
                              document_id: str, part_id: str, **_: Any) -> dict[str, Any]:
        if self.knowledge_store is None:
            raise DesignToolError("知识文档服务不可用")
        try:
            result = self.knowledge_store.agent_inspect(project_id=project_id, task_id=task_id, document_id=document_id, part_id=part_id)
        except ValueError as error:
            raise DesignToolError(str(error)) from error
        self._record_document_usage(project_id, task_id, document_id, result, inspected_part_id=part_id)
        return result

    def document_part_promote(self, *, project_id: str, task_id: str | None = None,
                              document_id: str, part_id: str, title: str | None = None, **_: Any) -> dict[str, Any]:
        if self.knowledge_store is None or self.asset_store is None:
            raise DesignToolError("文档或资产服务不可用")
        try:
            result = self.knowledge_store.agent_promote(project_id=project_id, task_id=task_id, document_id=document_id,
                                                        part_id=part_id, asset_store=self.asset_store, title=title)
        except ValueError as error:
            raise DesignToolError(str(error)) from error
        self._record_document_usage(project_id, task_id, document_id, result, promoted_part_id=part_id, promoted_asset_id=result.get("assetId"))
        return result

    def asset_search(self, *, project_id: str, task_id: str | None = None, kind: str | None = None, query: str | None = None, limit: int = 20, **_: Any) -> dict[str, Any]:
        if self.asset_store is None:
            return {"tool": "asset_search", "results": [], "count": 0}
        clean_kind = str(kind or "").strip().lower()
        needle = str(query or "").strip().casefold()
        clean_limit = max(1, min(int(limit or 20), 50))
        focused_ids = None
        scope_service = None
        if task_id:
            from .task_focus import TaskFocus
            scope_service = TaskFocus(self.store, self.canvas_store)
            context = self._task_input(project_id,task_id)
            focus = scope_service.resolve(project_id, task_id, context)
            if (focus['hasReferences'] or not needle and focus['mode']!='none') and not focus['allowOverview']:
                focused_ids = scope_service.known_ids(project_id,task_id,context,focus)[1]
            if not needle and focus['mode']=='none' and not focus['allowOverview']:
                return {'tool':'asset_search','results':[],'count':0,'notice':'请先根据对话确定素材；缺少线索时提供具体查询词，不能默认遍历素材库。'}
            if not focus['allowOverview']: clean_limit=min(clean_limit,6)
        results = []
        for asset in self.asset_store.list_assets(project_id):
            if focused_ids is not None and asset['id'] not in focused_ids:
                continue
            if clean_kind and str(asset.get("kind") or "").lower() != clean_kind:
                continue
            metadata = asset.get("metadata") if isinstance(asset.get("metadata"), dict) else {}
            haystack = " ".join([
                str(asset.get("id") or ""),
                str(asset.get("pathRelative") or ""),
                str(metadata.get("prompt") or ""),
                str(metadata.get("caption") or ""),
                str(metadata.get("source") or ""),
            ]).casefold()
            if needle and needle not in haystack:
                continue
            results.append(asset)
            if len(results) >= clean_limit:
                break
        if scope_service and focused_ids is None and not focus['allowOverview']:
            selected = scope_service.remember_candidates(project_id,task_id,'asset',[asset['id'] for asset in results])
            results=[asset for asset in results if asset['id'] in selected]
        return {"tool": "asset_search", "kind": clean_kind or None, "query": query or "", "results": results, "count": len(results)}

    def _image_configurations(self, *, project_id, task_id, provider=None, model=None, params=None, quality=None, has_references=False, reference_count=0, prompt=''):
        """Shared, read-only parameter preparation for preflight and dispatch."""
        from .image_quality import decide_image_policy
        if self.provider_registry is None:
            raise ValueError('图像 Provider 尚未初始化')
        test_mode=os.environ.get('AICS_TEST_MODE')=='1'
        provider_key=str(provider or ('local-placeholder' if test_mode else 'openai-image')).strip()
        task_input=self._task_input(project_id,task_id) if task_id else {}
        canvas_params=task_input.get('canvasParams') if isinstance(task_input.get('canvasParams'),dict) else {}
        supplied_params=params if isinstance(params,dict) else {}
        # Canvas controls are user-owned. Other task tool parameters are model
        # suggestions and may be repaired locally when they violate a selected
        # Provider's mechanical size limits.
        trusted_dimensions = not bool(task_id) or any(
            key in canvas_params and canvas_params.get(key) == supplied_params.get(key)
            for key in ('size','width','height','resolution','image_size')
        )
        decision=decide_image_policy(quality,user_message=task_input.get('userMessage','') if task_id else None,prompt=prompt,
                                     params=params,memory=task_input.get('conversationMemory'),has_references=has_references,
                                     trust_requested=not bool(task_id),trust_dimensions=trusted_dimensions)
        options=dict(params or {})
        base_url=str(options.pop('baseUrl','') or '')
        requested_model=str(model or ('placeholder-v0' if provider_key=='local-placeholder' else '')).strip() or None
        plan,candidates=build_image_route(
            self.provider_registry,provider=provider_key,base_url=base_url,requested_model=requested_model,
            decision=decision,params=options,has_references=has_references,reference_count=reference_count,
        )
        return provider_key,base_url,plan,candidates

    def _image_configuration(self, **kwargs):
        """Compatibility view used by preflight callers that need the primary candidate."""
        provider_key,_,plan,candidates=self._image_configurations(**kwargs)
        candidate=candidates[0]
        return provider_key,candidate.model,candidate.adapter,candidate.options,candidate.quality

    def generate_image(
        self,
        *,
        project_id: str,
        task_id: str | None = None,
        prompt: str,
        provider: str | None = None,
        model: str | None = None,
        source_asset_id: str | None = None,
        source_asset_ids: list[str] | None = None,
        negative_prompt: str | None = None,
        production_notes: list[str] | None = None,
        background: str | None = None,
        quality: str | None = None,
        canvas_node_id: str | None = None,
        params: dict[str, Any] | None = None,
        reference_analysis: dict[str, Any] | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        if self.asset_store is None or self.provider_registry is None:
            raise DesignToolError("图像工具尚未初始化")
        clean_prompt = str(prompt or "").strip()
        if not clean_prompt:
            raise DesignToolError("generate_image.prompt 不能为空")
        clean_notes = normalize_production_notes(production_notes)
        task_input = self._task_input(project_id,task_id) if task_id else {}
        user_message = task_input.get('userMessage') if task_id else clean_prompt
        clean_prompt, clean_negative_prompt = prepare_production_image_request(
            clean_prompt, negative_prompt,
            allow_disclaimer=explicit_image_disclaimer_requested(user_message),
        )
        options = dict(params) if isinstance(params, dict) else {}
        if options.get("style"):
            clean_prompt += f"\n视觉风格：{options['style']}"
        target_node = next((node for node in self.canvas_store.load(project_id)['nodes'] if node['id']==canvas_node_id),{}) if canvas_node_id else {}
        target_asset_id = target_node.get('data',{}).get('assetId') or (target_node.get('data',{}).get('asset') or {}).get('id')
        if target_asset_id:
            if task_input.get('taskSurface') == 'canvas_node':
                from .image_request_resolution import ImageRequestError
                raise ImageRequestError('已有内容的节点不能作为输出目标或引用自身资产。请新建空白节点并连线后生成。',
                                        code='self_reference_not_allowed', field='canvas_node_id',
                                        asset_ids=[target_asset_id], node_ids=[canvas_node_id])
            # Enforce the non-destructive image invariant at the generator
            # boundary as well, including task-less/internal callers.
            source_asset_ids=list(dict.fromkeys([target_asset_id,*image_reference_ids(source_asset_id,source_asset_ids)]))
            source_asset_id=target_asset_id
            canvas_node_id=None
        source_ids = image_reference_ids(source_asset_id, source_asset_ids)
        source_asset_id = source_ids[0] if source_ids else None
        from .conversation_memory import ConversationMemoryService
        for key in ('source_asset_path','source_asset_paths','mask_asset_path'):
            options.pop(key,None)
        if options.get('maskAssetId'):
            mask=self.asset_store.get_asset(project_id=project_id,asset_id=options['maskAssetId'])
            if not mask or mask.get('kind')!='image':raise DesignToolError('遮罩必须属于当前项目')
            options['mask_asset_path']=mask['absolutePath']
        source_paths = []
        source_assets = {}
        for asset_id in source_ids:
            source = self.asset_store.get_asset(project_id=project_id, asset_id=asset_id)
            if source is None or source.get("kind") != "image":
                raise DesignToolError("参考素材必须指向当前项目中存在的图像资产")
            source_paths.append(source['absolutePath'])
            source_assets[asset_id] = source
        reference_snapshot = _.get('_reference_snapshot') or ConversationMemoryService(self.store).validate_generation(project_id,task_id if task_input.get('memoryProtocol') else None,{'source_asset_ids':source_ids})
        if task_input.get('referenceWorkflow', {}).get('status') == 'selected':
            direction = task_input['referenceWorkflow']
            reference_snapshot = {**reference_snapshot, 'visualDirection': {key: direction.get(key) for key in ('selectionId', 'notes')} | {'choices': [c for c in direction.get('choices', []) if c.get('assetId') in source_ids]}}
        from .image_reference_design import prepare_reference_design, drawing_reference_ids
        clean_prompt, reference_snapshot, provider_input_ids = prepare_reference_design(
            clean_prompt, source_ids, reference_analysis, reference_snapshot, required=bool(task_input.get('memoryProtocol')),
            masked_edit=bool(options.get('maskAssetId')),
            layout_source_ids=drawing_reference_ids(self.asset_store, project_id, source_ids))
        source_paths = [path for identity,path in zip(source_ids,source_paths) if identity in provider_input_ids]
        source_transparent = any(source_assets[identity].get('metadata',{}).get('imageOutput',{}).get('hasTransparency') is True for identity in provider_input_ids)
        if source_paths:
            options['source_asset_path'], options['source_asset_paths'] = source_paths[0], source_paths
        clean_prompt, options = prepare_image_output(clean_prompt, options, background=background, source_transparent=source_transparent)
        provider_key,base_url,route_plan,route_candidates=self._image_configurations(project_id=project_id,task_id=task_id,
            provider=provider,model=model,params=options,quality=quality,has_references=bool(provider_input_ids),
            reference_count=len(provider_input_ids),prompt=clean_prompt)
        pending = None
        original = next((n for n in self.canvas_store.load(project_id)['nodes'] if n['id']==canvas_node_id), None)
        automatic = canvas_node_id is None
        execution_state = _.get('_execution_state', {})
        route_started = time.monotonic()
        submitted_models = set()
        def started(candidate):
            nonlocal pending, canvas_node_id
            active_params={key:value for key,value in candidate.options.items() if key not in {"source_asset_path","source_asset_paths","mask_asset_path","baseUrl"}}
            pending_data={'generating':True,'draft':False,'error':'',
                          'status':('首选不可用，正在尝试 '+candidate.model if pending is not None else '生成中'),
                          'params':active_params,'model':candidate.model}
            if _.get('_delivery_binding'):pending_data['deliveryBinding']=_['_delivery_binding']
            if canvas_node_id:
                pending=self.canvas_store.update_node(project_id,canvas_node_id,{'data':pending_data})
            else:
                pending=self.canvas_store.create_node(project_id,kind='image',title='生成图像',data=pending_data,task_id=task_id,
                    execution_receipt=execution_state.get('fingerprint'))
                canvas_node_id=pending['id']
            execution_state['submitted']=True
            if provider_key == 'evolink' and task_id:
                from .image_recovery import ImageRecovery
                recovery = ImageRecovery(self)
                adapter = getattr(candidate.adapter, '_adapter', candidate.adapter)
                metadata = {'source':'design-agent-tool','prompt':clean_prompt,'productionNotes':clean_notes,
                    'canvasNodeId':canvas_node_id,'sourceAssetIds':source_ids,'referenceSnapshot':reference_snapshot,
                    'deliveryBinding':_.get('_delivery_binding')}
                adapter.on_task = lambda body: recovery.remember(project_id, task_id, execution_state.get('fingerprint'),
                    body, candidate.model, base_url, metadata)
        trace = RouteTrace(self.store) if task_id else None
        def route_status(item):
            if trace:
                status = item.get('status')
                if status == 'submitted':
                    submitted_models.add(item.get('model'))
                submitted = item.get('model') in submitted_models
                adapter = next((candidate.adapter for candidate in route_candidates if candidate.model == item.get('model')), None)
                provider_timing = getattr(adapter, 'last_timings', None)
                trace.append(task_id,{'phase':'image_route','fingerprint':execution_state.get('fingerprint'),
                    **({'timingMs':dict(provider_timing)} if isinstance(provider_timing, dict) else {}),
                    **({'referenceUploadCacheHits':adapter.last_upload_cache_hits} if isinstance(getattr(adapter, 'last_upload_cache_hits', None), int) else {}),
                    'call_kind':'image_generation','route_source':'manual' if route_plan['mode']=='manual' else 'automatic',
                    'provider':provider_key,'mode':route_plan['mode'],'tier':route_plan['tier'],
                    'started_at':time.time()-(time.monotonic()-route_started),
                    'latency_ms':round((time.monotonic()-route_started)*1000),
                    'submitted':submitted,
                    'billing_certainty':('settled' if status=='succeeded' else 'unknown' if status=='unknown'
                                         else 'not_submitted' if status=='safe_rejected' else 'pending' if submitted else 'not_submitted'),
                    **item})
        try:
            def validate(content,candidate):
                if not content:
                    raise DesignToolError("图像 Provider 没有返回可保存的内容",stop_tool=True,response_received=True,error_code='image_response_invalid')
                try:
                    return reject_svg_output(content,transparent_requested=candidate.options.get("background")=="transparent")
                except ValueError as error:
                    raise DesignToolError(str(error),stop_tool=True,response_received=True,error_code='image_output_format') from error
            content,candidate,image_route,image_output=dispatch_image_route(
                route_plan,route_candidates,prompt=clean_prompt,negative_prompt=clean_negative_prompt or None,
                on_submitted=started,on_status=route_status,validate_content=validate,
            )
            save_started = time.monotonic()
            selected_model,image_provider,options,quality_info=candidate.model,candidate.adapter,candidate.options,candidate.quality
            saved_params={key:value for key,value in options.items() if key not in {"source_asset_path","source_asset_paths","mask_asset_path","baseUrl"}}
            extension = str(options.get("output_format") or "png").lstrip(".")
            raw_images = getattr(image_provider, "last_response", {}).get("data", [])
            if raw_images and isinstance(raw_images, list) and isinstance(raw_images[0], dict):
                mime = raw_images[0].get("media_type")
                extension = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}.get(mime, extension)
            if image_output.get("verified"):
                extension = {"jpeg": "jpg"}.get(image_output["format"], image_output["format"])
            asset = self.asset_store.add_bytes(
                project_id=project_id,
                kind="image",
                filename=f"agent-image-{uuid4().hex}.{extension}",
                content=bytes(content),
                metadata={
                    "source": "design-agent-tool",
                    "taskId": task_id,
                    "executionReceipt": _.get("_execution_state", {}).get("fingerprint"),
                    "canvasNodeId": canvas_node_id,
                    "provider": provider_key,
                    "model": selected_model,
                    "prompt": clean_prompt,
                    "negativePrompt": clean_negative_prompt,
                    "productionNotes": clean_notes,
                    "sourceAssetId": source_asset_id,
                    "sourceAssetIds": source_ids,
                    "providerInputAssetIds": provider_input_ids,
                    "referenceSnapshot": reference_snapshot,
                    "designSpec": _.get('_design_spec'),
                    "imageQuality": quality_info,
                    "imageRoute": image_route,
                    "params": saved_params,
                    "imageOutput": image_output,
                    "contractVersion": "langju-agent-v1",
                },
            )
            node = self.canvas_store.ensure_asset_node(project_id, asset, task_id=task_id, target_node_id=canvas_node_id, data={"params": saved_params, "provider": provider_key, "model": selected_model, "imageQuality":quality_info, "imageRoute":image_route, "referenceSnapshot":reference_snapshot, "designSpec":_.get('_design_spec'), "productionNotes":clean_notes},execution_receipt=execution_state.get('fingerprint'))
            from .task_timing import record_timing
            record_timing(self.store, task_id, 'assetSaveMs', save_started)
            return {
                "tool": "generate_image",
                "node": node,
                "status": "succeeded",
                "provider": provider_key,
                "model": selected_model,
                "imageRoute": image_route,
                "asset": asset,
                "assetId": asset["id"],
                "outputKind": "image",
                "imageOutput": image_output,
                "warnings": [image_output["warning"]] if image_output.get("warning") else [],
                "productionNotes": clean_notes,
            }
        except Exception as error:
            if pending:
                rejected=getattr(error,'status_code',None) in {400,401,402,403,404,405,413,415,422,429}
                if rejected and automatic:
                    self.canvas_store.apply_changes(project_id,{'removeNodeIds':[pending['id']]},agent_edit=True)
                elif rejected and original:
                    prior=original.get('data',{})
                    self.canvas_store.update_node(project_id,pending['id'],{'data':{k:prior.get(k,default) for k,default in {'generating':False,'draft':False,'error':'','status':'','params':{}}.items()}})
                else:
                    # A complete rejected/invalid response is a known failure;
                    # only a missing final response has an unknown outcome.
                    state = '生成失败' if getattr(error, 'response_received', False) else '生成结果待确认'
                    self.canvas_store.update_node(project_id,pending['id'],{'data':{'generating':False,'error':str(error),'status':state}})
            raise

    def generate_video(
        self,
        *,
        project_id: str,
        task_id: str | None = None,
        prompt: str,
        provider: str = "seedream",
        model: str | None = None,
        source_asset_id: str | None = None,
        source_asset_ids: list[str] | None = None,
        last_frame_asset_id: str | None = None,
        endpoint: str | None = None,
        canvas_node_id: str | None = None,
        params: dict[str, Any] | None = None,
        quality: str = "standard",
        **_: Any,
    ) -> dict[str, Any]:
        if self.provider_registry is None:
            raise DesignToolError("视频工具尚未初始化")
        clean_prompt = str(prompt or "").strip()
        if not clean_prompt:
            raise DesignToolError("generate_video.prompt 不能为空")
        try:
            source_asset_id, last_frame_asset_id, options = video_inputs(source_asset_id, source_asset_ids, last_frame_asset_id, params)
        except ValueError as error:
            raise DesignToolError(str(error)) from error
        if getattr(self.provider_registry, "catalog", None) and provider in {"openrouter", "openai-compatible", "evolink"}:
            model = MediaModelRouter(self.provider_registry.catalog).route("video", provider=provider, base_url=endpoint or "", model=model, quality=quality, prompt=clean_prompt, params={**options, '_hasReferences': bool(source_asset_id)})
        # Style and camera are creative directions, not portable API fields.
        # Keep them effective even when an adapter filters provider parameters.
        for field, label in (("style", "视觉风格"), ("camera", "镜头运动"), ("camera_motion", "镜头运动")):
            if options.get(field):
                clean_prompt += f"\n{label}：{options[field]}"
        model = model or DEFAULT_VIDEO_MODEL
        source_paths = []
        for asset_id in (source_asset_id, last_frame_asset_id):
            if not asset_id:
                source_paths.append(None)
                continue
            if self.asset_store is None:
                raise DesignToolError("视频工具缺少资产存储")
            source = self.asset_store.get_asset(project_id=project_id, asset_id=asset_id)
            if source is None or source.get('kind') != 'image':
                raise DesignToolError("视频参考素材必须是当前项目中存在的图像资产")
            path = source.get('absolutePath')
            if not path or not os.path.isfile(path):
                raise DesignToolError('视频参考图片文件不存在')
            source_paths.append(path)
        frame_metadata = {'sourceAssetId': source_asset_id, 'sourceAssetIds': [id for id in (source_asset_id, last_frame_asset_id) if id], 'lastFrameAssetId': last_frame_asset_id}
        try:
            video_provider = self.provider_registry.video(str(provider), endpoint=endpoint, model=str(model))
            if last_frame_asset_id and not getattr(video_provider, 'supports_last_frame', False):
                raise DesignToolError('当前视频服务不支持首尾帧，请使用 OpenRouter 视频服务')
            _.get("_execution_state", {})["submitted"] = True
            frame_options = {'last_frame_asset': source_paths[1]} if last_frame_asset_id else {}
            job = video_provider.generate(prompt=clean_prompt, source_asset=source_paths[0], model=str(model), **frame_options, **{key: value for key, value in options.items() if key not in {"style", "camera", "camera_motion"}})
        except (ProviderError, ValueError) as error:
            raise error
        if not isinstance(job, dict):
            raise DesignToolError("视频 Provider 返回了无效任务对象")
        video_content = job.pop("content", None)
        extension = str(job.pop("extension", "mp4")).lstrip(".")
        output_asset = None
        if isinstance(video_content, (bytes, bytearray)) and video_content and self.asset_store is not None:
            output_asset = self.asset_store.add_bytes(
                project_id=project_id,
                kind="video",
                filename=f"agent-video-{uuid4().hex}.{extension}",
                content=bytes(video_content),
                metadata={
                    "source": "design-agent-tool",
                    "taskId": task_id,
                    "executionReceipt": _.get("_execution_state", {}).get("fingerprint"),
                    "canvasNodeId": canvas_node_id,
                    "provider": provider,
                    "model": model,
                    "prompt": clean_prompt,
                    **frame_metadata,
                    "params": options,
                },
            )
        record = None
        if self.video_service is not None:
            record = self.video_service.create(
                project_id,
                provider=str(provider),
                model=str(model),
                status=str(job.get("status") or "submitted"),
                job_id=str(job.get("jobId")) if job.get("jobId") else None,
                prompt=clean_prompt,
                source_asset_id=source_asset_id,
                metadata={"source": "design-agent-tool", "taskId": task_id, "canvasNodeId": canvas_node_id, "executionReceipt": _.get("_execution_state", {}).get("fingerprint"), "executionResources": _.get("_execution_state", {}).get("resources", []), "endpoint": endpoint, "params": options, **job, **frame_metadata},
                output_asset_id=output_asset.get("id") if output_asset else None,
            )
        node = self.canvas_store.ensure_asset_node(project_id, output_asset, task_id=task_id, target_node_id=canvas_node_id, data={"params": options, "provider": provider, "model": model}) if output_asset else None
        return {
            "tool": "generate_video",
            "node": node,
            "status": str(job.get("status") or "submitted"),
            "provider": provider,
            "model": model,
            "job": record or job,
            "asset": output_asset,
            "assetId": output_asset.get("id") if output_asset else None,
        }

    def canvas_create_text(
        self,
        *,
        project_id: str,
        task_id: str | None = None,
        text: str,
        title: str = "设计说明",
        canvas_node_id: str | None = None,
        x: float | None = None,
        y: float | None = None,
        application_items: list | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        self._validate_svg(task_id, 'canvas_create_text', {'text': text})
        from .application_inventory import prepare_inventory, render_inventory
        inventory = prepare_inventory(application_items, text, self._task_input(project_id, task_id), _.get('_delivery_binding'))
        extra = {}
        if inventory:
            text = render_inventory(inventory, {})
            extra['applicationInventory'] = {**inventory, 'taskId': task_id, 'renderedText': text}
        if canvas_node_id:
            node = self.canvas_store.update_node(project_id, canvas_node_id, {"data": {"text": str(text), "title": title, "generating": False, "draft": False, "error": "", **extra}, "meta": {"createdBy": "design-agent", "taskId": task_id, "executionReceipt": _.get("_execution_state", {}).get("fingerprint")}})
            return {"tool": "canvas_create_text", "node": node, "canvas": self.canvas_store.load(project_id)}
        node = self.canvas_store.create_node(
            project_id,
            kind="text",
            title=title,
            summary=str(text or ""),
            position=None if task_id else {key: value for key, value in {"x": x, "y": y}.items() if value is not None},
            data={"text": str(text or ""), **extra},
            task_id=task_id,
            execution_receipt=_.get("_execution_state", {}).get("fingerprint"),
        )
        return {"tool": "canvas_create_text", "node": node, "canvas": self.canvas_store.load(project_id)}

    def canvas_read(self, *, project_id, task_id=None, node_ids=None, asset_ids=None, scope='focus', query='', offset=0, limit=6, text_offset=0, **_):
        from .delivery import DeliveryService
        from .task_focus import TaskFocus
        delivery = DeliveryService(self.store, self.asset_store, self.canvas_store)
        result = TaskFocus(self.store,self.canvas_store).read(project_id,task_id,self._task_input(project_id,task_id),
            node_ids=node_ids,asset_ids=asset_ids,scope=scope,query=query,offset=offset,limit=limit,text_offset=text_offset)
        # Check fingerprints against full local content, not paginated text.
        originals = {n['id']:n for n in self.canvas_store.load(project_id)['nodes']} if result['scope'] not in {'discover','candidates'} else {}
        for node in result['canvas']['nodes']:
            check = delivery.check(project_id, originals[node['id']]) if node['id'] in originals else None
            if check:
                node["data"]["previewValidation"] = {k: v for k, v in check.items() if k != "frames"}
        from .node_context import observe
        observe(self.store,project_id,task_id,[originals[n['id']] for n in result['canvas']['nodes'] if n['id'] in originals])
        return result

    def report_progress(self, *, project_id, summary, **_):
        text = str(summary or '').strip()
        if not text or len(text)>400: raise DesignToolError('执行说明需为 1–400 字的简短摘要')
        return {'summary':text,'status':'recorded'}

    def delivery_verify(self, *, project_id, task_id=None, refs=None, **_):
        from .delivery import DeliveryService
        from .deliverable_tracking import record_progress
        report = DeliveryService(self.store, self.asset_store, self.canvas_store).inspect_task(project_id, task_id, refs)
        if task_id:
            from .application_inventory import finalize_inventories
            if finalize_inventories(self.canvas_store, project_id, task_id, report):
                # Recompute fingerprints after updating inventory; repeated verification is read-only.
                report = DeliveryService(self.store, self.asset_store, self.canvas_store).inspect_task(project_id, task_id, refs)
        if task_id: record_progress(self.store, project_id, task_id, report)
        return report

    def repair_control(self, *, project_id, task_id, action, node_ids=None, **_):
        from .budget import BudgetService
        delivery = self.delivery_verify(project_id=project_id,task_id=task_id) if action == 'begin' else {}
        return BudgetService(self.store,self.provider_registry.catalog).repair_control(task_id,action,[a['nodeId'] for a in delivery.get('artifacts',[]) if a.get('nodeId') and (node_ids is None or a['nodeId'] in node_ids)])

    def budget_check(self, *, project_id, task_id, provider, base_url, model, input_tokens, output_tokens, input_images=0, require_price=False, **_):
        from .budget import BudgetService
        return BudgetService(self.store,self.provider_registry.catalog).reserve(task_id,provider=provider,base_url=base_url,model=model,kind='text',
            usage={'input_tokens':max(0,int(input_tokens)),'output_tokens':max(0,int(output_tokens))},units={'requests':1,'inputImages':input_images},require_price=require_price)

    def asset_inspect(self, *, project_id, task_id=None, asset_id, **_):
        import base64
        from pathlib import Path
        asset = self.asset_store.get_asset(project_id=project_id, asset_id=asset_id) if self.asset_store else None
        if not asset:
            raise DesignToolError("资产不属于当前项目或不存在")
        result = {"assetId": asset_id, "mime": asset.get("mime"), "metadata": asset.get("metadata", {})}
        path = Path(asset["absolutePath"])
        if asset.get("mime") in {"image/png", "image/jpeg", "image/webp", "image/gif"}:
            from .vision_preview import make_vision_preview
            preview = make_vision_preview(path.read_bytes())
            if preview:
                content = preview.pop('content')
                result["image"] = f"data:{preview['mime']};base64," + base64.b64encode(content).decode()
                result["visionPreview"] = {**preview, "normalized": True}
            else:
                result["notice"] = "图像过大或格式不可解析；原资产未变更，可在画布中查看。"
        elif asset.get('metadata', {}).get('cadRole') == 'model':
            from .cad import cad_manifest
            from .delivery import DeliveryService
            result['cad'] = cad_manifest(self.asset_store, project_id, asset_id)
            node = next((n for n in self.canvas_store.load(project_id)['nodes'] if n.get('data', {}).get('assetId') == asset_id), None)
            check = DeliveryService(self.store,self.asset_store,self.canvas_store).check(project_id,node) if node else None
            result['images'] = (check or {}).get('frames', [])
            if not result['images']:
                thumbnail = self.asset_store.get_asset(project_id=project_id,asset_id=result['cad']['files']['thumbnail'])
                result['image'] = 'data:image/png;base64,' + base64.b64encode(Path(thumbnail['absolutePath']).read_bytes()).decode()
            result['notice'] = '实际 GLB 三视图与几何检查' if result['images'] else '实体网格缩略图；GLB 预览检查尚未完成'
        elif asset.get('mime') == 'image/svg+xml':
            result['svg'] = path.read_text(encoding='utf-8')[:16000]
            result['notice'] = '静态 SVG 源码检查，可检查文字与图形结构；未提供栅格截图，不代表已核验实际印刷或工程精度。'
        elif asset.get("mime", "").startswith("video/"):
            from .delivery import DeliveryService
            delivery = DeliveryService(self.store, self.asset_store, self.canvas_store)
            node = next((n for n in self.canvas_store.load(project_id)["nodes"] if n.get("data", {}).get("assetId") == asset_id), None)
            check = delivery.check(project_id, node) if node else None
            result["images"] = (check or {}).get("frames", [])
            result["notice"] = "视频抽帧与播放检查，不代表逐帧人工验收" if result["images"] else "视频尚未完成浏览器抽帧验收"
        else:
            result["notice"] = "此资产仅返回元数据，未作图像内容检查"
        return result

    def canvas_create_html(self, *, project_id, task_id=None, html, title="网页", canvas_node_id=None, x=None, y=None, **_):
        self._validate_svg(task_id, 'canvas_create_html', {'html': html})
        html = str(html).strip()
        if not html or len(html.encode()) > 1024 * 1024:
            raise DesignToolError("HTML 内容须为 1 字节至 1 MB")
        from .html_syntax import validate_html_styles
        validate_html_styles(html)
        data = {"kind": "html", "html": html, "title": title, "draft": False, "generating": False, "error": "", "status": "已生成"}
        data.update(prepare_html_assets(html, self.asset_store, project_id))
        if canvas_node_id:
            node = self.canvas_store.update_node(project_id, canvas_node_id, {"data": data, "meta": {"createdBy": "design-agent", "taskId": task_id, "executionReceipt": _.get("_execution_state", {}).get("fingerprint")}})
        else:
            node = self.canvas_store.create_node(project_id, kind="html", title=title, data=data, task_id=task_id,
                execution_receipt=_.get("_execution_state", {}).get("fingerprint"),
                position=None if task_id else {key: value for key, value in {"x": x, "y": y}.items() if value is not None})
        return {"tool": "canvas_create_html", "node": node, "outputKind": "html", "status": "succeeded"}

    def generate_text(self, *, project_id, task_id=None, prompt, model=None, title="生成文本", canvas_node_id=None, **_):
        current = self._task_input(project_id, task_id).get("textProvider") or {}
        runtime = _.get('_model_context') if isinstance(_.get('_model_context'), dict) else {}
        catalog = getattr(self.provider_registry, "catalog", None)
        preferred = catalog.settings().preferredTextProvider if catalog else None
        key = runtime.get("provider") or runtime.get("key") or current.get("key") or (preferred.key if preferred else "")
        base = runtime.get("baseUrl") or current.get("baseUrl") or (preferred.baseUrl if preferred and preferred.key == key else "")
        # In automatic routing the Agent tool argument is descriptive only.
        # Reuse the endpoint already selected for the main turn so this helper
        # cannot jump from Terra to a UI placeholder or another provider.
        selected = runtime.get("model") or model or current.get("model")
        if not selected or not self.provider_registry:
            raise DesignToolError("请先配置文本模型")
        if catalog:
            resolved = catalog.resolve_id(key, base or "", selected)
            record = catalog.record(key, base or "", resolved or selected)
            if not resolved or "text" not in record.get("kinds", []):
                raise DesignToolError("所选模型不在本地文本模型目录中")
            selected = resolved
        provider = self.provider_registry.text(key, base_url=base, model=selected)
        call_started = time.monotonic()
        submitted = False
        failure = None
        result = None
        try:
            _.get("_execution_state", {})["submitted"] = True
            submitted = True
            text = provider.complete(system="按用户要求完成文本或代码交付，只输出交付正文。不要假称运行过代码。", prompt=str(prompt))
            result = self.canvas_create_text(project_id=project_id, task_id=task_id, text=text, title=title, canvas_node_id=canvas_node_id, **_)
            return {**result, "tool": "generate_text", "model": selected, "outputKind": "text", "status": "succeeded"}
        except Exception as error:
            failure = error
            raise
        finally:
            if task_id:
                RouteTrace(self.store).append(task_id, {
                    'call_kind': 'generate_text',
                    'tier': runtime.get('tier') or 'STANDARD',
                    'provider': key,
                    'model': selected,
                    'api': runtime.get('api') or 'auto',
                    'route_source': runtime.get('routeSource') or 'active_agent',
                    'started_at': time.time() - (time.monotonic() - call_started),
                    'latency_ms': round((time.monotonic() - call_started) * 1000),
                    'status': 'succeeded' if result is not None else 'failed',
                    'error_type': type(failure).__name__ if failure is not None else None,
                    'error_message': str(failure)[:600] if failure is not None else None,
                    'submitted': submitted,
                    'billing_certainty': 'settled' if result is not None else 'unknown' if submitted else 'not_submitted',
                })

    def generate_cad(self, *, project_id, task_id=None, source=None, parameter_definitions=None, parameters=None,
                     title='CAD 模型', canvas_node_id=None, base_revision=None, reference_asset_ids=None,
                     assumptions=None, expected_dimensions=None, **kwargs):
        from .cad import cad_service
        service = cad_service(self.store)
        request = dict(source=source, parameter_definitions=parameter_definitions, parameters=parameters or {},
                       title=title, canvas_node_id=canvas_node_id, base_revision=base_revision,
                       reference_asset_ids=reference_asset_ids or [], assumptions=assumptions or [], expected_dimensions=expected_dimensions or {})
        build = service.submit(project_id,request,task_id=task_id,receipt=kwargs.get('_execution_state',{}).get('fingerprint'),binding=kwargs.get('_delivery_binding'))
        build = service.wait(project_id,build['id'])
        if build['status'] != 'succeeded':
            return {'status':build['status'],'buildId':build['id'],'error':build['error'],
                    'instruction':'构建未交付，未替换已有模型。按 error 的真实步骤和原因说明失败；语法或参数错误不能描述成几何校验失败。最多修复一次，修复时同时处理整段程序的所有报错并核对尺寸。'}
        return {'buildId':build['id'], **build['result']}

    def generate_3d(self, *, project_id, task_id=None, prompt, model=None, source_asset_id=None,
                    canvas_node_id=None, quality="standard", params=None, **_):
        from .model_config import EndpointModel
        from .agent_contracts import utc_now
        config = (self._task_input(project_id, task_id).get("mediaProvider") or {}).get("threeD") or {}
        endpoint = str(config.get("endpoint") or "")
        hint = config.get("key")
        key = self.provider_registry.detect_3d_provider(endpoint, hint)
        if not endpoint or key not in {"meshy", "tripo", "rodin", "hunyuan3d"}:
            raise DesignToolError("请先设置已支持的 Meshy、Tripo、Rodin 或 Hunyuan3D 服务地址及 Key")
        EndpointModel(baseUrl=endpoint)
        slots = self.provider_registry.catalog.settings().media["3d"]
        selected = model or config.get("model") or slots.get("draft" if quality == "draft" else "final") or key
        source = self.asset_store.get_asset(project_id=project_id, asset_id=source_asset_id) if source_asset_id else None
        if source_asset_id and (not source or source.get("kind") != "image"):
            raise DesignToolError("3D 参考图像必须属于当前项目")
        options = {k: v for k, v in (params or {}).items() if k in {"texture", "topology", "target_polycount", "enable_pbr", "negative_prompt"}}
        generation_id = str(uuid4())
        with self.store._connect() as db:
            db.execute("INSERT INTO generations (id, project_id, provider, model, prompt_text, negative_prompt, params_json, parent_asset_id, status, created_at) VALUES (?, ?, ?, ?, ?, '', ?, ?, 'running', ?)",
                       (generation_id, project_id, key, selected, prompt, json.dumps(options), source_asset_id, utc_now()))
        try:
            _.get("_execution_state", {})["submitted"] = True
            job = self.provider_registry.three_d(key, endpoint=endpoint).generate(prompt=prompt, model=selected, source_asset=source.get("absolutePath") if source else None, output_format="glb", **options)
            content = job.pop("content", None)
            asset = self.asset_store.add_bytes(project_id=project_id, kind="3d", filename=f"agent-{generation_id}.{job.pop('extension', 'glb')}", content=content,
                metadata={"source": "design-agent-tool", "taskId": task_id, "model": selected, "sourceAssetId": source_asset_id}) if content else None
            job.update(endpoint=endpoint, sourceAsset=source_asset_id, canvasNodeId=canvas_node_id)
            with self.store._connect() as db:
                db.execute("UPDATE generations SET asset_id=?, status=?, evaluation_json=? WHERE id=?", (asset["id"] if asset else None, job.get("status", "submitted"), json.dumps({"job": job}), generation_id))
            node = self.canvas_store.ensure_asset_node(project_id, asset, task_id=task_id, target_node_id=canvas_node_id) if asset else None
            return {"tool": "generate_3d", "generationId": generation_id, "status": job.get("status", "submitted"), "job": job, "assetId": asset["id"] if asset else None, "asset": asset, "node": node}
        except (ProviderError, ValueError) as error:
            with self.store._connect() as db:
                db.execute("UPDATE generations SET status='failed', evaluation_json=? WHERE id=?", (json.dumps({"error": str(error)}), generation_id))
            raise DesignToolError(str(error)) from error

    def generate_audio(self, *, project_id: str, task_id: str | None = None, prompt: str,
                       provider: str = "openai-compatible", model: str = "", params: dict | None = None,
                       canvas_node_id: str | None = None, **_: Any) -> dict[str, Any]:
        if not self.provider_registry or not self.asset_store or not model:
            raise DesignToolError("请先选择支持语音生成的音频模型")
        options = dict(params or {})
        base = str(options.get("baseUrl") or ("https://openrouter.ai/api/v1" if provider == "openrouter" else "https://api.openai.com/v1"))
        record = self.provider_registry.catalog.record(provider, base, model) if getattr(self.provider_registry, "catalog", None) else {}
        if record and "audio" not in record.get("kinds", []):
            raise DesignToolError("所选模型不支持音频输出")
        api = record.get("audioApi", "auto")
        if provider == 'evolink':
            from .providers.evolink import EvoLinkAudioProvider
            from .evolink import EVOLINK_BASE_URL
            adapter = EvoLinkAudioProvider(base_url=EVOLINK_BASE_URL, provider_key=provider, model=model, credentials=self.provider_registry.credentials)
            from .image_recovery import ImageRecovery
            adapter.on_task = lambda body: ImageRecovery(self).remember(project_id,task_id,_.get('_execution_state',{}).get('fingerprint'),
                body,model,EVOLINK_BASE_URL,{'kind':'audio','source':'design-agent-tool','prompt':prompt,'canvasNodeId':canvas_node_id,'deliveryBinding':_.get('_delivery_binding')})
        else:
            adapter = OpenAICompatibleSpeechProvider(base, provider, model, self.provider_registry.credentials, api=api)
        adapter = self.provider_registry._meter("audio", adapter)
        _.get("_execution_state", {})["submitted"] = True
        try:
            content = adapter.generate(text=prompt, voice=str(options.get("voice") or ('longanhuan_v3.1' if provider == 'evolink' else 'alloy')), speed=float(options.get("speed") or 1))
        except ProviderError as error:
            if canvas_node_id and getattr(error, 'error_code', None) in {'image_result_unconfirmed','provider_result_unconfirmed'}:
                self.canvas_store.update_node(project_id,canvas_node_id,{'data':{'status':'生成结果待确认','generating':False}})
            raise
        if not content:
            raise DesignToolError("音频接口返回了空内容")
        asset = self.asset_store.add_bytes(project_id=project_id, kind="audio", filename=f"agent-audio-{uuid4().hex}.mp3", content=content,
                                          metadata={"source": "design-agent-tool", "taskId": task_id, "prompt": prompt, "model": model, "canvasNodeId": canvas_node_id, "executionReceipt": _.get("_execution_state", {}).get("fingerprint")})
        node = self.canvas_store.ensure_asset_node(project_id, asset, task_id=task_id, target_node_id=canvas_node_id, data={"params": options, "model": model})
        return {"tool": "generate_audio", "status": "succeeded", "asset": asset, "assetId": asset["id"], "node": node}

    def canvas_create_node(
        self, *, project_id: str, task_id: str | None = None, kind: str = "text",
        title: str = "设计节点", x: float | None = None, y: float | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        data = {'draft': True}
        if kind == 'drawing':
            from .drawing import empty_drawing
            kind = 'image'
            data.update(editor='drawing', referenceRole='layout', drawing=empty_drawing(), previewSize={'width':720,'height':540}, params={'aspectRatio':'4:3'})
        node = self.canvas_store.create_node(
            project_id, kind=str(kind or "text"), title=title,
            position=None if task_id else {key: value for key, value in {"x": x, "y": y}.items() if value is not None},
            data=data, task_id=task_id,
            execution_receipt=_.get("_execution_state", {}).get("fingerprint"),
        )
        return {"tool": "canvas_create_node", "node": node, "canvas": self.canvas_store.load(project_id)}

    def canvas_create_media(
        self,
        *,
        project_id: str,
        task_id: str | None = None,
        asset_id: str,
        kind: str = "image",
        title: str = "设计资产",
        summary: str = "",
        x: float | None = None,
        y: float | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        if self.asset_store is None:
            raise DesignToolError("画布工具缺少资产存储")
        asset = self.asset_store.get_asset(project_id=project_id, asset_id=str(asset_id))
        if asset is None:
            raise DesignToolError("asset_id 不属于当前项目或资产不存在")
        if task_id and (asset.get('mime') == 'image/svg+xml' or str(asset.get('pathRelative', '')).lower().endswith('.svg')):
            from .svg_policy import ERROR
            raise DesignToolError(ERROR)
        node = self.canvas_store.ensure_asset_node(
            project_id, asset,
            title=title,
            summary=summary or str((asset.get("metadata") or {}).get("prompt") or ""),
            position=None if task_id else {key: value for key, value in {"x": x, "y": y}.items() if value is not None},
            task_id=task_id,
            execution_receipt=_.get("_execution_state", {}).get("fingerprint"),
        )
        return {"tool": "canvas_create_media", "node": node, "asset": asset, "canvas": self.canvas_store.load(project_id)}

    def canvas_update_node(
        self,
        *,
        project_id: str,
        task_id: str | None = None,
        node_id: str,
        patch: dict[str, Any],
        **_: Any,
    ) -> dict[str, Any]:
        if not isinstance(patch, dict):
            raise DesignToolError("canvas_update_node.patch 必须是对象")
        self._validate_svg(task_id, 'canvas_update_node', patch)
        if task_id and isinstance(patch.get('data'), dict) and patch['data'].get('assetId') and self.asset_store:
            asset = self.asset_store.get_asset(project_id=project_id, asset_id=patch['data']['assetId'])
            if asset and (asset.get('mime') == 'image/svg+xml' or str(asset.get('pathRelative', '')).lower().endswith('.svg')):
                from .svg_policy import ERROR
                raise DesignToolError(ERROR)
        if isinstance(patch.get('data'), dict) and 'html' in patch['data']:
            patch = {**patch, 'data': {**patch['data'], **prepare_html_assets(patch['data']['html'], self.asset_store, project_id)}}
        node = self.canvas_store.update_node(project_id, str(node_id), {**patch, **({"meta": {"createdBy": "design-agent", "taskId": task_id, "executionReceipt": _.get("_execution_state", {}).get("fingerprint")}} if task_id else {})})
        return {"tool": "canvas_update_node", "node": node, "canvas": self.canvas_store.load(project_id)}

    def canvas_link_nodes(
        self,
        *,
        project_id: str,
        task_id: str | None = None,
        source_node_id: str,
        target_node_id: str,
        label: str | None = None,
        source_handle: str | None = None,
        target_handle: str | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        edge = self.canvas_store.link_nodes(
            project_id,
            source_node_id=str(source_node_id),
            target_node_id=str(target_node_id),
            label=label,
            source_handle=source_handle,
            target_handle=target_handle,
            task_id=task_id,
            execution_receipt=_.get("_execution_state", {}).get("fingerprint"),
        )
        return {"tool": "canvas_link_nodes", "edge": edge, "canvas": self.canvas_store.load(project_id)}

    def request_clarification(
        self, *, project_id: str, task_id: str | None = None,
        questions: list[dict[str, Any]] | None = None, intro: str = "开始设计前，请补充以下信息。", **_: Any,
    ) -> dict[str, Any]:
        """Return a model-decided, structured intake card without generating assets."""
        normalized: list[dict[str, Any]] = []
        for item in questions or []:
            if not isinstance(item, dict) or not str(item.get("question") or "").strip():
                continue
            options = [str(option).strip() for option in item.get("options", []) if str(option).strip()][:8]
            normalized.append({"id": str(item.get("id") or uuid4().hex[:8]), "question": str(item["question"]).strip(), "options": options, "multi": bool(item.get("multi"))})
        from .design_state import read_state, unanswered_questions
        normalized, answered = unanswered_questions(read_state(self.store, project_id, task_id), normalized) if task_id else (normalized, [])
        return {"tool": "request_clarification", "intro": str(intro or "开始设计前，请补充以下信息。"), "questions": normalized[:6], "awaitingUser": bool(normalized), 'answered': answered, 'instruction': '沿用已回答内容。缺少官方规范时把待确认项放在节点制作说明中，图像保持干净，先推进不依赖它的视觉设计。' if answered else ''}
