"""Rule-first policy routing, separate from Agent identity and media execution."""
from __future__ import annotations

import json
import inspect
import os
import random
import re
import time
from typing import Literal
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field

from .billing import billing_scope
from .model_config import (
    DEFAULT_DRAFT_IMAGE_MODEL,
    DEFAULT_IMAGE_MODEL,
    DEFAULT_TEXT_FALLBACK_MODEL,
    FALLBACK_IMAGE_MODEL,
    ModelTier,
)
from .design_runtime import DesignRuntimeError
from .task_policy import delivery_requirements, execution_flow, is_simple_conversation


class ExecutionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_type: str
    complexity: int = Field(ge=1, le=10)
    model_tier: ModelTier
    reasoning_effort: Literal["none", "low", "medium", "high", "xhigh"]
    quality_level: Literal["draft", "standard", "production"]
    tools_required: list[str]
    parallelism: int | None = Field(default=None, exclude=True, description='兼容旧记录；实际调度依据交付依赖，不使用数量上限')
    max_turns: int = Field(ge=1, le=60)
    route_reason: str


class ModelRouter:
    def __init__(self, catalog, providers):
        self.catalog, self.providers = catalog, providers

    def policy(self, tier=ModelTier.STANDARD, *, task_type="design", complexity=4, quality="standard", reason="常规设计任务", tools=None):
        config = self.catalog.settings().tiers[tier]
        return ExecutionPolicy(task_type=task_type, complexity=complexity, model_tier=tier,
                               reasoning_effort=config.reasoningEffort, quality_level=quality,
                               tools_required=tools or [], max_turns=config.maxTurns, route_reason=reason)

    def endpoint(self, tier, current, fallback=False):
        config = self.catalog.settings().tiers[tier]
        selected = config.fallback if fallback else config.primary
        if selected is None:
            return None
        key = current["key"] if selected.provider == "inherit" else selected.provider
        base = selected.baseUrl or (current.get("baseUrl", "") if key == current["key"] else "")
        adapter = self.providers.text(key, base_url=base or None, model=selected.model)
        # Test doubles and third-party adapters are not required to expose a
        # concrete base_url attribute.  An explicit endpoint remains the
        # source of truth unless the adapter supplies a normalized string.
        adapter_base = getattr(adapter, "base_url", None)
        if isinstance(adapter_base, str) and adapter_base.strip():
            base = adapter_base
        model = self.catalog.resolve_id(key, base, selected.model)
        if not model:
            raise ValueError(f"{tier} 的模型 {selected.model} 不在该服务的本地目录中，请在设置同步目录或修改等级映射")
        return {"key": key, "baseUrl": base, "model": model, "api": selected.api}

    def automatic_endpoint(self, tier, current, constraints=None):
        """Resolve Luna first and use GPT-6 Sol only for a pre-submit hard mismatch.

        Empty modality metadata is not proof of incompatibility. This method
        never reacts to output quality or a submitted provider failure.
        """
        constraints = constraints or {}
        primary_error = None
        try:
            primary = self.endpoint(tier, current)
        except ValueError as error:
            primary, primary_error = None, error
        visual_input = any(
            str(item.get('mime') or '').startswith('image/') or item.get('assetId')
            for item in constraints.get('attachments', []) if isinstance(item, dict)
        ) or any(constraints.get(key) for key in ('referencedAssets', 'referencedNodes', 'referencedCanvasNodes'))
        if primary:
            record = self.catalog.record(primary['key'], primary['baseUrl'], primary['model'])
            modalities = [str(value).lower() for value in (record.get('inputModalities') or [])]
            if not visual_input or not modalities or 'image' in modalities:
                return primary, None
        elif primary_error:
            # A missing Luna entry is a configuration/catalog problem, not
            # proof that Luna lacks a requested capability.
            raise primary_error
        key = current['key']
        base = current.get('baseUrl', '')
        adapter = self.providers.text(key, base_url=base or None, model=DEFAULT_TEXT_FALLBACK_MODEL)
        adapter_base = getattr(adapter, 'base_url', None)
        if isinstance(adapter_base, str) and adapter_base.strip():
            base = adapter_base
        resolved = self.catalog.resolve_id(key, base, DEFAULT_TEXT_FALLBACK_MODEL)
        if not resolved:
            raise ValueError(f"默认模型不支持本轮图片输入，且兼容模型 {DEFAULT_TEXT_FALLBACK_MODEL} 不在本地目录中")
        record = self.catalog.record(key, base, resolved)
        modalities = [str(value).lower() for value in (record.get('inputModalities') or [])]
        if visual_input and modalities and 'image' not in modalities:
            raise ValueError(f"模型 {resolved} 也不支持本轮图片输入")
        return {"key": key, "baseUrl": base, "model": resolved, "api": "auto"}, 'vision'

    def route(self, brief, current, constraints=None):
        constraints = constraints or {}
        routing = constraints.get("modelRouting")
        mode = routing.get("mode", "auto") if isinstance(routing, dict) else "auto"
        contextual_inputs = any(constraints.get(key) for key in (
            "attachments", "referencedAssets", "referencedFiles", "referencedNodes", "referencedCanvasNodes",
        )) or bool((constraints.get("canvasParams") or {}).get("nodeId"))
        simple = constraints.get("simpleConversation", is_simple_conversation(brief, constraints))
        task = {"task_type": "conversation", "complexity": 1} if simple else {}
        if mode == "manual":
            return self.policy(reason="用户手动选择模型", **task)
        if mode in {"fast", "standard", "quality"}:
            tier = ModelTier.FAST if mode == 'fast' else ModelTier.STANDARD
            if mode == "fast" and contextual_inputs:
                tier = ModelTier.STANDARD
            return self.policy(tier,
                               quality="production" if mode == "quality" else "standard", reason="用户选择执行质量", **task)
        text = brief.lower()
        if simple:
            return self.policy(ModelTier.FAST, task_type="conversation", complexity=1, reason="简短交流或轻量文字处理，直接答复")
        from .task_policy import is_schedule_management, is_skill_management
        if is_skill_management(brief, constraints):
            return self.policy(task_type='skill', reason='管理可复用的专业 Skill，不执行其中的设计流程', tools=['skill_list', 'skill_read', 'skill_create', 'skill_update', 'skill_delete', 'skill_load', 'skill_unload'])
        if is_schedule_management(brief, constraints):
            return self.policy(task_type='schedule', reason='组织定时计划，到期后执行产物生成', tools=['schedule_list','schedule_create','schedule_update'])
        if contextual_inputs:
            return self.policy(ModelTier.STANDARD, task_type="design", reason="任务包含图片、文件或画布引用，使用支持多模态理解的设计模型")
        # Media quality and workflow length do not imply expensive text reasoning.
        strong_reasoning = bool(re.search(r"严谨证明|数学证明|形式化验证|多约束优化|结构计算|复杂.*(?:cad|算法|代码|编程)|complex.*(?:cad|algorithm|code)|formal.verification|强推理|深度推理", text))
        if strong_reasoning:
            return self.policy(ModelTier.STANDARD, task_type='design', complexity=8,
                               reason='自动模式保持 Luna；如需更高推理模型可手动选择')
        required = delivery_requirements(brief, constraints)
        if required:
            kind = required[0]
            return self.policy(ModelTier.STANDARD, task_type=f"media:{kind}", reason="多模态设计模型组织媒体任务，媒体质量由独立路由选择", tools=[f"generate_{kind}"])
        if constraints.get('continuation') or re.search(r'设计|礼盒|包装|三视图|刀版|效果图|design|packaging', text):
            return self.policy(reason="结合当前项目目标与未完成交付继续设计", task_type="design")
        if re.search(r"^(?:请|帮我|把|将|给)?[^。\n]{0,16}(?:打标|分类|提取|抽取|翻译)|(?:添加|标注).{0,8}标签|^(?:translate|classify|label|tag|extract)\b|转(?:成|为).*json", text):
            if re.search(r"图片|图像|照片|海报|截图|image|photo|poster|screenshot", text):
                return self.policy(ModelTier.STANDARD, task_type="transform", complexity=3, reason="需要读取视觉内容，使用多模态设计模型")
            return self.policy(ModelTier.FAST, task_type="transform", complexity=2, reason="可机械验证的标注、提取或格式转换")
        if re.search(r"总结|需求|方案|设计|文案|你好|介绍|建议|summar|design|hello|copywriting", text):
            return self.policy(reason="常规沟通、需求总结或设计方向，使用默认多模态设计模型")
        return self.policy(ModelTier.STANDARD, reason='自动模式使用默认 Luna')

    def classify(self, brief, current, constraints):
        # Kept as a compatibility entry point for older callers. Routing is
        # now deterministic and must never spend a separate Luna request.
        return self.policy(ModelTier.STANDARD, reason="本地规则分类使用默认 Luna")


class MediaModelRouter:
    def __init__(self, catalog):
        self.catalog = catalog

    def route(self, kind, *, provider, base_url, model=None, quality=None, prompt="", params=None):
        if kind == 'image':
            return self.image_plan(
                provider=provider, base_url=base_url, model=model, quality=quality,
                params=params or {}, has_references=bool((params or {}).get('_hasReferences')),
            )['primaryModel']
        quality = quality or 'standard'
        slots = self.catalog.settings().media[kind]
        level = "final" if quality in {"production", "final"} else quality
        if kind == 'video' and not model:
            level = self.video_quality(prompt, params or {}, level)
        if kind == "3d" and level == "standard":
            level = "final"
        if kind == 'image' and level == 'final' and not model and not slots.get('final'):
            raise ValueError('请在设置中配置 final 图像模型；当前请求保持最高质量，不自动改用较低档模型')
        desired = model or slots.get(level) or slots.get("standard") or ""
        resolved = self.catalog.resolve_id(provider, base_url, desired)
        if not resolved and not model and kind == 'video' and provider == 'evolink':
            # EvoLink publishes separate mode IDs for the same Seedance family.
            # Resolve only a locally known variant, never change model/tier or
            # silently override an explicit manual selection.
            leaf = desired.rsplit('/', 1)[-1]
            if re.fullmatch(r'seedance-[\d.]+(?:-mini)?', leaf):
                mode = 'image-to-video' if (params or {}).get('_hasReferences') else 'text-to-video'
                resolved = self.catalog.resolve_id(provider, base_url, f'{leaf}-{mode}')
        if not resolved:
            raise ValueError(f"{kind} 模型 {desired or '未设置'} 不在本地目录中，请在设置中同步模型并选择可用模型")
        return resolved

    @staticmethod
    def automatic_image_model_allowed(model: str) -> bool:
        """Exclude the costly multimodal LLM, including namespaced snapshots."""
        leaf = str(model or '').strip().lower().replace('_', '-').split('/')[-1]
        leaf = re.sub(r'-\d{4}-\d{2}-\d{2}$', '', leaf)
        return not bool(re.fullmatch(r'gpt-5[.-]4-image-2', leaf))

    def image_plan(self, *, provider, base_url, model=None, quality=None, params=None, has_references=False):
        """Return an ordered, locally available image route without dispatching."""
        level = 'final' if quality in {'production', 'final'} else quality or 'draft'
        if level not in {'draft', 'standard', 'final'}:
            level = 'draft'
        slots = self.catalog.settings().media['image']
        if model:
            resolved = self.catalog.resolve_id(provider, base_url, model)
            if not resolved:
                raise ValueError(f"image 模型 {model} 不在本地目录中，请在设置中同步模型并选择可用模型")
            return {'mode': 'manual', 'tier': level, 'primaryModel': resolved, 'candidateModels': [resolved],
                    'allCandidateModels': [resolved], 'unavailableModels': []}

        configured = str(slots.get(level) or slots.get('standard') or '').strip()
        builtins = ([DEFAULT_DRAFT_IMAGE_MODEL, DEFAULT_IMAGE_MODEL, FALLBACK_IMAGE_MODEL]
                    if level == 'draft' else [DEFAULT_IMAGE_MODEL, DEFAULT_DRAFT_IMAGE_MODEL, FALLBACK_IMAGE_MODEL])
        resolution = str((params or {}).get('resolution') or (params or {}).get('image_size') or '').upper()
        explicit_resolution = str((params or {}).get('_resolutionSource') or '') in {'user', 'parameter'}
        if level == 'draft':
            seedream = (['bytedance-seed/seedream-4.5', 'bytedance-seed/seedream-5-0-pro']
                        if resolution == '1K' and explicit_resolution else
                        ['bytedance-seed/seedream-5-0-lite', 'bytedance-seed/seedream-4.5', 'bytedance-seed/seedream-5-0-pro'])
        elif resolution == '4K':
            seedream = ['bytedance-seed/seedream-4.5', 'bytedance-seed/seedream-5-0-lite']
        else:
            seedream = ['bytedance-seed/seedream-5-0-pro', 'bytedance-seed/seedream-4.5', 'bytedance-seed/seedream-5-0-lite']
        desired = list(dict.fromkeys([configured, *builtins, *seedream]))
        desired = [item for item in desired if item and self.automatic_image_model_allowed(item)]
        resolved = []
        unavailable = []
        planned = []
        for candidate in desired:
            selected = self.catalog.resolve_id(provider, base_url, candidate)
            record = self.catalog.record(provider, base_url, selected) if selected and hasattr(self.catalog, 'record') else {}
            kinds = set(record.get('kinds') or ([record.get('kind')] if record.get('kind') else []))
            image_capable = not record or 'image' in kinds
            if selected and image_capable and self.automatic_image_model_allowed(selected) and selected not in resolved:
                resolved.append(selected)
                planned.append(selected)
            elif not selected or not image_capable:
                unavailable.append(candidate)
                planned.append(candidate)
        if not resolved:
            raise ValueError('没有可用且兼容的自动图像模型；请同步本地模型目录或手动选择模型')
        return {'mode': 'auto', 'tier': level, 'primaryModel': planned[0], 'candidateModels': resolved,
                'allCandidateModels': planned, 'unavailableModels': unavailable}

    @staticmethod
    def video_quality(prompt, params, quality):
        text = str(prompt).lower()
        try: duration = float(params.get('duration') or params.get('seconds') or 0)
        except (TypeError, ValueError): duration = 0
        complex_scene = bool(re.search(r'多镜头|多场景|复杂|多人|对白|口型|对口型|分镜|长镜头|叙事|角色一致|电影级|正式交付|multi.?shot|dialogue|lip.?sync|cinematic', text))
        if quality == 'final' or complex_scene or duration > 6 or params.get('audio') or params.get('generate_audio'):
            return 'final'
        # Keep 2.5 as the default. Mini is for a clearly simple draft/preview.
        simple = bool(re.search(r'简单|单镜头|静态|轻微|固定镜头|simple|single.?shot|static', text))
        draft = quality == 'draft' or bool(re.search(r'草稿|预览|测试|快速试|draft|preview', text))
        return 'draft' if simple and draft else 'standard'


class RouteTrace:
    def __init__(self, store):
        self.store = store
        with store._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS model_route_trace (id TEXT PRIMARY KEY, task_id TEXT NOT NULL, data_json TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS model_call_trace (id TEXT PRIMARY KEY, task_id TEXT NOT NULL, data_json TEXT NOT NULL, created_at REAL NOT NULL)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_model_call_trace_task_time ON model_call_trace(task_id,created_at)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_model_route_trace_task ON model_route_trace(task_id)")

    def append(self, task_id, data, *, record_id=None):
        with self.store._connect() as db:
            db.execute("INSERT OR IGNORE INTO model_call_trace VALUES (?,?,?,?)", (record_id or str(uuid4()), task_id, json.dumps(data, ensure_ascii=False), time.time()))

    def list(self, task_id):
        with self.store._connect() as db:
            legacy = db.execute("SELECT data_json FROM model_route_trace WHERE task_id=? ORDER BY rowid", (task_id,)).fetchall()
            rows = db.execute("SELECT data_json FROM model_call_trace WHERE task_id=? ORDER BY created_at,rowid", (task_id,)).fetchall()
        return [json.loads(row[0]) for row in [*legacy, *rows]]


def evaluate_result(result, required_artifacts=None):
    if result.status != "succeeded":
        return "执行结果失败"
    if not result.structured_data:
        return "结构化结果为空"
    if result.structured_data.get("clarification") or result.structured_data.get("referenceSelection"):
        return None
    if result.structured_data.get('deliveryStatus') in {'pending', 'needs_review'}:
        # Content verification must not cause another paid generation or tier escalation.
        return None
    if not str(result.structured_data.get("answer", "")).strip() and set(result.structured_data) <= {"answer", "review", "delivery"}:
        return "没有返回有效答复"
    if result.structured_data.get("delivery", {}).get("issues"):
        return "；".join(result.structured_data["delivery"]["issues"])
    if result.provenance.get("toolFailureCount", 0) >= 2:
        return "工具连续失败，产物需重新检查"
    available = {ref.entity_type for ref in result.artifact_refs}
    available.update(result.provenance.get("artifactKinds", []))
    # Submitted videos are handed to the durable completion service, never
    # treated as finished artifacts or retried through another model tier.
    if result.provenance.get("pendingMedia"):
        available.add("video")
    missing = set(required_artifacts or []) - available
    return f"缺少必需产物：{', '.join(sorted(missing))}" if missing else None


class RoutedDesignRuntime:
    def __init__(self, runtime, catalog, providers, store):
        self.runtime, self.catalog, self.providers = runtime, catalog, providers
        self.router = ModelRouter(catalog, providers)
        self.traces = RouteTrace(store)

    def run(self, **kwargs):
        with billing_scope(project_id=kwargs["project_id"], task_id=kwargs["task_id"]):
            return self._run(**kwargs)

    def _run(self, **kwargs):
        if kwargs.get("should_cancel") and kwargs["should_cancel"]():
            raise DesignRuntimeError("任务已停止", kind="interrupted")
        current = kwargs["provider_ref"]
        constraints = kwargs.get("constraints", {})
        from .node_prompt import is_literal
        if is_literal(constraints):
            return self.runtime.run(**kwargs)
        simple = is_simple_conversation(kwargs["brief"], {**constraints, "attachments": kwargs.get("attachments") or constraints.get("attachments", [])})
        constraints = {**constraints, "attachments": kwargs.get("attachments") or constraints.get("attachments", []),
                       "requiredArtifacts": delivery_requirements(kwargs["brief"], constraints),
                       "executionFlow": execution_flow(kwargs["brief"], constraints), "simpleConversation": simple}
        if simple:
            constraints.update(executionFlow="direct", agentCollaboration=False, deliveryVerification=False)
        kwargs = {**kwargs, "constraints": constraints}
        canvas = constraints.get("canvasParams") or {}
        if canvas.get("kind") in {"text", "html"} and canvas.get("model"):
            current = {**current, "model": canvas["model"]}
            constraints = {**constraints, "modelRouting": {"mode": "manual"}}
            kwargs = {**kwargs, "constraints": constraints, "provider_ref": current}
        routing = constraints.get("modelRouting")
        mode = routing.get("mode", "auto") if isinstance(routing, dict) else "auto"
        try:
            policy = self.router.route(kwargs["brief"], current, constraints)
        except Exception:
            policy = self.router.policy(reason="路由异常，安全回退 STANDARD")
        tier, origin = policy.model_tier, policy.model_tier
        settings = self.catalog.settings()
        from .provider_health import ProviderHealth
        health = ProviderHealth(self.catalog.store)
        recovery = {}
        trace = kwargs.get("trace") or (lambda *args: None)
        def progress(phase, message, data=None):
            if data is None:
                return trace(phase, message)
            try:
                if 'data' in inspect.signature(trace).parameters:
                    return trace(phase, message, data)
            except (TypeError, ValueError):
                pass
            return trace(phase, message)
        last_error = None
        last_result = None
        stop_routing = False
        # Automatic mode never upgrades after a paid run. A deterministic
        # capability fallback is selected below before the first submission.
        for escalation in range(1):
            config = settings.tiers[tier]
            policy = policy.model_copy(update={"model_tier": tier, "reasoning_effort": config.reasoningEffort, "max_turns": config.maxTurns})
            if simple:
                policy = policy.model_copy(update={"reasoning_effort": "none"})
            targets = [False]
            capability_failure = False
            attempted = False
            for fallback in targets:
                target_capability_failure = False
                try:
                    capability_fallback = None
                    if mode == 'manual':
                        endpoint = current
                    else:
                        endpoint, capability_fallback = self.router.automatic_endpoint(tier, current, constraints)
                        if capability_fallback:
                            trace('route', f"Luna 在提交前确认不适合本轮输入，改用兼容模型 {endpoint['model']}")
                except ValueError as error:
                    last_error = error
                    trace("route_failed", f"模型配置不可用：{error}")
                    self.traces.append(kwargs["task_id"], {**policy.model_dump(mode="json"), "provider": current["key"], "status": "unavailable", "fallback": fallback, "error_type": "configuration", "error_message": str(error)[:600]})
                    continue
                attempted = True
                for retry in range(config.retries + 1):
                    if kwargs.get("should_cancel") and kwargs["should_cancel"]():
                        raise DesignRuntimeError("任务已停止", kind="interrupted")
                    started = time.monotonic()
                    route = {**policy.model_dump(mode="json"), "model": endpoint["model"], "provider": endpoint["key"],
                             "retry": retry, "fallback": fallback, "escalated_from": str(origin) if escalation else None,
                             "escalated_to": str(tier) if escalation else None,
                             "capability_fallback": capability_fallback,
                             "call_kind": "main_agent", "route_source": "manual" if mode == "manual" else "automatic",
                             "started_at": time.time(), "submitted": False, "billing_certainty": "not_submitted"}
                    if retry:
                        attempts_by_stage = recovery.setdefault("recoveryAttempts", {})
                        stage_recovery = attempts_by_stage.setdefault("design", {"total": 0, "signatures": {}})
                        status_code = getattr(last_error, "status_code", None)
                        signature = f"provider:main_agent:{status_code or 'network'}"
                        signature_state = stage_recovery.setdefault("signatures", {}).get(signature, {})
                        signature_attempt = int(signature_state.get("attempts") or 0) + 1
                        if signature_attempt > 2 or int(stage_recovery.get("total") or 0) >= 6:
                            break
                        stage_recovery["total"] = int(stage_recovery.get("total") or 0) + 1
                        stage_recovery["signatures"][signature] = {
                            "attempts": signature_attempt,
                            "kind": "provider",
                            "tool": "main_agent",
                            "code": str(status_code or "network"),
                        }
                        executions = getattr(self.runtime, "executions", None)
                        if executions:
                            executions.save(kwargs["task_id"], recovery)
                        requested_delay = getattr(last_error, 'retry_after', None)
                        try:
                            delay = min(5.0, max(0.0, float(requested_delay))) if requested_delay is not None else min(5.0, .5 * (2 ** (retry - 1)) + random.random() * .2)
                        except (TypeError, ValueError):
                            delay = min(5.0, .5 * (2 ** (retry - 1)) + random.random() * .2)
                        progress("retry", f"{endpoint['model']} · 临时服务故障，失败恢复 {retry}/{config.retries}", {
                            'kind':'provider','tool':'main_agent','code':str(status_code or 'network'),
                            'attempt':signature_attempt,'limit':2,
                            'stageTotal':stage_recovery['total'],'stageLimit':6,'stage':'design',
                        })
                        if os.environ.get('AICS_TEST_MODE') != '1' and delay:
                            time.sleep(delay)
                    trace("route", f"使用模型：{endpoint['model']} · {'备用服务' if fallback else policy.route_reason}")
                    evaluation = None
                    result = None
                    try:
                        route["submitted"] = True
                        route["billing_certainty"] = "pending"
                        result = self.runtime.run(**{**kwargs, "provider_ref": endpoint}, execution_policy=policy.model_dump(mode="json"), recovery=recovery)
                        last_result = result
                        if constraints.get("deliveryReviewOnly") and result.status == "failed":
                            route.update(status="failed", evaluation="产物未完整保存")
                            return result
                        required = constraints.get("requiredArtifacts") or ([policy.task_type.split(":", 1)[1]] if policy.task_type.startswith("media:") else [])
                        evaluation = evaluate_result(result, required)
                        if evaluation:
                            recovery = result.provenance.pop("recovery", recovery)
                            recovery = {**recovery, "stages": {key: value for key, value in recovery.get("stages", {}).items() if key == "research"}}
                            executions = getattr(self.runtime, "executions", None)
                            if executions:
                                executions.save(kwargs["task_id"], recovery)
                            raise DesignRuntimeError(evaluation, kind="capability", recovery=recovery)
                        result.provenance.pop("recovery", None)
                        result.provenance["executionPolicy"] = policy.model_dump(mode="json")
                        result.provenance.update({
                            "provider": endpoint["key"],
                            "baseUrl": endpoint["baseUrl"],
                            "model": endpoint["model"],
                            "api": endpoint.get("api", "auto"),
                            "tier": tier.value if isinstance(tier, ModelTier) else str(tier),
                            "routeSource": "manual" if mode == "manual" else "automatic",
                        })
                        route.update(status="succeeded", usage=result.provenance.get("usage", {}), evaluation="passed")
                        route["billing_certainty"] = "not_applicable" if getattr(self.providers, "is_local", lambda _key: False)(endpoint["key"]) else "settled"
                        health.record(endpoint,True)
                    except DesignRuntimeError as error:
                        if kwargs.get("should_cancel") and kwargs["should_cancel"]():
                            raise
                        last_error = error
                        recovery = getattr(error, "recovery", None) or recovery
                        kind = getattr(error, "kind", "provider")
                        detail = " ".join(str(error).split())[:600]
                        route.update(status="failed", error_type=kind, error_message=detail, status_code=error.status_code, evaluation=evaluation, usage=getattr(error, "usage", {}))
                        route["submitted"] = getattr(error, 'submitted', None)
                        route["billing_certainty"] = "not_applicable" if getattr(self.providers, "is_local", lambda _key: False)(endpoint["key"]) else getattr(error, 'billing_certainty', None) or ("unknown" if kind == "provider" else "not_applicable")
                        trace("route_failed", f"本地执行环境异常：{detail}" if kind == "runtime" else f"任务执行中断：{detail}" if kind in {'tool','execution_timeout'} else f"{endpoint['model']} 调用失败：{detail}")
                        if kind in {"configuration", "runtime", "tool", "execution_timeout"}:
                            raise
                        target_capability_failure = kind == "capability"
                        capability_failure = capability_failure or target_capability_failure
                        retryable = error.retryable
                        health.record(endpoint,False,retryable)
                    finally:
                        route["latency_ms"] = round((time.monotonic()-started)*1000)
                        self.traces.append(kwargs["task_id"], route)
                    if result is not None and evaluation is None:
                        return result
                    if target_capability_failure or not retryable:
                        break
                # A cheaper primary that produced an invalid result may still be
                # rescued by its explicitly configured same-tier model. Only
                # escalate to a more expensive tier after both have failed.
                if target_capability_failure:
                    continue
                # Provider/network failures must never fan out into another
                # endpoint after a request may have been submitted.  Even a
                # confirmed pre-submit rejection is retried only on the same
                # endpoint above; a configured fallback is reserved for
                # health/cost preselection or genuine capability failure.
                if isinstance(last_error, DesignRuntimeError):
                    stop_routing = True
                    break
            if stop_routing:
                break
            # Automatic mode has one preselected endpoint. Do not announce a
            # tier escalation which is forbidden and will never be executed.
            break
        if last_result is not None:
            last_result.status = "failed"
            last_result.warnings = list(dict.fromkeys([*last_result.warnings, str(last_error or "产物验收未通过")]))
            return last_result
        if isinstance(last_error, DesignRuntimeError):
            raise last_error
        raise DesignRuntimeError(str(last_error or "模型路由没有可用的执行端点"), kind="configuration")
