from __future__ import annotations

import json
import hashlib
import os
import re
import queue
import shutil
import subprocess
import sys
import threading
import tempfile
import time
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4
from .model_config import DEFAULT_TEXT_MODEL

from .agent_contracts import AgentResult, ArtifactRef, Citation
from .providers.registry import ProviderRegistry


TraceCallback = Callable[..., None]


class DesignRuntimeError(RuntimeError):
    """Execution failure with safe continuation data for tier/provider retries."""
    def __init__(self, message, *, kind="provider", recovery=None, usage=None, status_code=None,
                 submitted: bool | None = None, billing_certainty: str | None = None,
                 retry_after: float | None = None):
        super().__init__(message)
        self.kind, self.recovery, self.usage = kind, recovery or {}, usage or {}
        self.status_code = status_code
        self.retry_after = retry_after
        self.submitted = submitted
        self.billing_certainty = billing_certainty or ('unknown' if submitted is not False else 'not_submitted')
        # Older workers expose the HTTP status only in their error text.
        if self.status_code is None:
            match = re.search(r"^(?:HTTP\s+)?([45]\d{2})\b", str(message), re.I)
            self.status_code = int(match[1]) if match else None
        if self.kind == "provider" and self.status_code and 400 <= self.status_code < 500 and self.status_code not in {408, 409, 429}:
            self.kind = "configuration"
        # Also recognize errors persisted by older desktop builds. Manual
        # continuation may recover after restart; provider retries cannot.
        if self.kind == "provider" and re.search(r"找不到 Node\.js|Agent 本地运行时|OpenAI Agents SDK worker 不存在", str(message)):
            self.kind = "runtime"
        if self.kind == "provider" and re.search(
            r"ENOBUFS|\.map is not a function|Cannot read properties|TypeError|signature|JSONL|protocol|RunState",
            str(message), re.I,
        ):
            self.kind = "runtime"

    @property
    def retryable(self):
        if re.search(r"spending.limit|monthly.limit|insufficient.quota|quota.exceeded|credit.balance|额度不足|余额不足|消费限额", str(self), re.I):
            return False
        if self.kind != "provider":
            return False
        if self.submitted is not False:
            return False
        if self.status_code is not None:
            return self.status_code in {408, 409, 429} or 500 <= self.status_code < 600
        return bool(re.search(r"timeout|timed out|超时|connection|连接|econnreset|econnrefused|fetch failed|socket", str(self), re.I))


def resolve_worker_path(worker_path: str | Path | None = None) -> Path:
    """Find the worker without depending on the process working directory.

    Desktop startup can explicitly select its adjacent standalone bundle. A
    directly launched frozen sidecar uses its own bundled data instead, which
    PyInstaller places below ``_MEIPASS`` rather than the source checkout.
    """
    override = worker_path or os.environ.get("AICS_AGENT_WORKER")
    if override:
        return Path(override).expanduser().resolve()

    module_worker = Path(__file__).resolve().with_name("openai_agent_worker.mjs")
    candidates = [module_worker]
    if getattr(sys, "frozen", False):
        executable_dir = Path(sys.executable).resolve().parent
        extraction_root = getattr(sys, "_MEIPASS", None)
        if extraction_root:
            candidates.append(Path(extraction_root) / "app" / "openai_agent_worker.mjs")
        candidates.extend([
            executable_dir / "_internal" / "app" / "openai_agent_worker.mjs",
            executable_dir / "app" / "openai_agent_worker.mjs",
        ])
        # The desktop bundle also keeps the worker at services/api/app.
        if executable_dir.name == "aics-api" and executable_dir.parent.name == "sidecar":
            candidates.append(executable_dir.parent.parent / "app" / "openai_agent_worker.mjs")
    return next((candidate for candidate in candidates if candidate.is_file()), module_worker)


class DesignRuntime:
    """Bridge the Python task lifecycle to the OpenAI Agents SDK.

    The Python sidecar owns durable tasks, project data and cancellation. The
    Node worker owns the Agent loop, tool calls and model streaming. They
    communicate over a one-shot JSONL protocol so provider keys never enter
    the renderer or the persisted task input.
    """

    def __init__(
        self,
        provider_registry: ProviderRegistry,
        *,
        node_path: str | None = None,
        worker_path: str | Path | None = None,
        runtime_root: str | Path | None = None,
        timeout_seconds: float | None = None,
        tool_gateway_url: str | None = None,
    ) -> None:
        self.provider_registry = provider_registry
        self.executions = None
        self.node_path = node_path or os.environ.get("AICS_NODE") or shutil.which("node") or "node"
        self.worker_path = resolve_worker_path(worker_path)
        self.runtime_root = Path(runtime_root or os.environ.get("AICS_AGENT_RUNTIME_ROOT") or Path(tempfile.gettempdir()) / "langju-agent-runtime").expanduser().resolve()
        # Keep the legacy constructor argument compatible, but never impose a
        # wall-clock deadline on generation, review, or task continuation.
        self.tool_gateway_url = str(tool_gateway_url or os.environ.get("AICS_AGENT_TOOL_GATEWAY_URL") or "http://127.0.0.1:8765").rstrip("/")

    def run(
        self,
        *,
        project_id: str,
        task_id: str,
        agent_key: str,
        workflow_step: str,
        brief: str,
        constraints: dict[str, Any],
        retrieved_context: list[str],
        research_sources: list[dict[str, Any]],
        attachments: list[dict[str, Any]],
        prior_outputs: list[dict[str, Any]],
        provider_ref: dict[str, Any],
        trace: TraceCallback | None = None,
        should_cancel: Callable[[], bool] | None = None,
        execution_policy: dict | None = None,
        recovery: dict | None = None,
    ) -> AgentResult:
        execution_policy = {key: value for key, value in (execution_policy or {}).items() if key != 'timeout'}
        durable = self.executions.load(task_id) if self.executions else {}
        checkpoint = {**durable, **(recovery or {})}
        usage_count = 0
        attempt_id = str(uuid4())
        worker_failure = {}
        provider = str(provider_ref.get("key") or "openrouter").strip() or "openrouter"
        spec = next((item for item in self.provider_registry.list() if item["key"] == provider), None)
        from .node_prompt import is_literal
        direct_node = is_literal(constraints) and (constraints.get('canvasParams') or {}).get('kind') in {'image', 'upload', 'video', 'audio'}
        api_key = self.provider_registry.credentials.get(provider) or (provider if spec and spec.get("requiresKey") is False else None)
        if direct_node:
            api_key = api_key or 'local-node-dispatch-no-text-call'
        if not api_key:
            raise DesignRuntimeError(f"未找到 {provider} 的本地 API Key，请在 Provider 设置中保存凭据", kind="configuration")
        if not self.worker_path.is_file():
            raise DesignRuntimeError(f"OpenAI Agents SDK worker 不存在：{self.worker_path}。请重启应用后继续原任务。", kind="runtime")

        default_base_url = str(spec.get("defaultBaseUrl") or "") if spec else ""
        default_model = str(spec.get("defaultModel") or "") if spec else ""
        base_url = str(provider_ref.get("baseUrl") or default_base_url or "https://openrouter.ai/api/v1").strip().rstrip("/")
        model = str(provider_ref.get("model") or default_model or DEFAULT_TEXT_MODEL).strip()
        if checkpoint.get("finalResult"):
            return self._agent_result(checkpoint["finalResult"], provider=provider, model=model)
        catalog = getattr(self.provider_registry, "catalog", None)
        record = catalog.record(provider, base_url, model) if catalog else {}
        if not direct_node and any(a.get("data") and str(a.get("mime", "")).startswith("image/") for a in attachments) and record.get("inputModalities") and "image" not in record["inputModalities"]:
            raise DesignRuntimeError(f"模型 {model} 不支持图片输入，请选择支持视觉理解的模型", kind="configuration")
        from .model_capabilities import model_record
        protocol = provider_ref.get("api", "auto")
        if protocol == "auto":
            protocol = model_record({**record, "id": model})["textApi"]
        roles = {}
        if not is_literal(constraints) and catalog and not constraints.get('simpleConversation') and ((constraints.get('modelRouting') or {}).get('mode') != 'manual' or constraints.get('deliveryReviewOnly') and constraints.get('allowRoleModels')):
            for role, selected in catalog.settings().roles.items():
                if role != 'research' or not selected.model: continue
                if role=='research' and constraints.get('executionFlow') in {'direct','design','delivery','design_review','delivery_review'}: continue
                key = provider if selected.provider == 'inherit' else selected.provider
                adapter = self.provider_registry.text(key,base_url=selected.baseUrl or (base_url if key==provider else None),model=selected.model)
                resolved = catalog.resolve_id(key,adapter.base_url,selected.model)
                role_spec = next((item for item in self.provider_registry.list() if item["key"] == key), None)
                secret = self.provider_registry.credentials.get(key) or (key if role_spec and role_spec.get("requiresKey") is False else None)
                if not resolved or not secret: raise DesignRuntimeError(f'{role} 模型未同步或缺少凭据',kind='configuration')
                capabilities = catalog.record(key,adapter.base_url,resolved)
                roles[role] = {'provider':key,'baseUrl':adapter.base_url,'model':resolved,'apiKey':secret,
                               'capabilities': capabilities,
                               'api':selected.api if selected.api!='auto' else model_record({**capabilities,'id':resolved})['textApi']}
        run_dir = self.runtime_root / task_id
        run_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            'skills': None,
            "provider": provider,
            "model": model,
            "api": protocol,
            "modelCapabilities": record,
            "baseUrl": base_url,
            "apiKey": api_key,
            "roleModels": roles,
            "maxOutputTokens": catalog.settings().maxOutputTokens if catalog else 4096,
            "budgetEnabled": bool(catalog and catalog.settings().taskBudgetPoints is not None),
            "persistentSessions": bool(self.executions),
            "executionStateVersion": 1,
            "memorySettings": catalog.settings().memory.model_dump() if catalog else {},
            "toolGateway": {
                "baseUrl": self.tool_gateway_url,
                "projectId": project_id,
                "taskId": task_id,
                "supportsTaskUpdates": True,
                "supportsAsyncImageJobs": True,
            },
            "context": {
                "projectId": project_id,
                "taskId": task_id,
                "agentKey": agent_key,
                "workflowStep": workflow_step,
                "brief": brief,
                "constraints": constraints,
                "retrievedContext": retrieved_context,
                "researchSources": research_sources,
                "attachments": attachments,
                "priorOutputs": prior_outputs,
            },
            "runtimeDir": str(run_dir),
            "executionPolicy": execution_policy,
            "recovery": checkpoint,
        }
        if self.executions:
            from .task_policy import normalize_delivery_context
            constraints.update(normalize_delivery_context({**constraints, 'userMessage': brief}))
            from .svg_policy import ensure_task_policy
            constraints['svgPolicy'] = ensure_task_policy(self.executions.store, task_id)
            from .skills import SkillService
            from .conversation_memory import ConversationMemoryService
            memory_service = ConversationMemoryService(self.executions.store)
            memory_service.prepare_empty_selection(project_id, task_id)
            # ExecutionStore.load initializes toolOutputs=[] even on a new task.
            if not any(checkpoint.values()):
                memory_service.prepare_single_image_selection(project_id, task_id, attachments, constraints)
            if not is_literal(constraints):
                payload['memory'] = memory_service.runtime(project_id,task_id,images=True)
                payload['skills'] = SkillService(self.executions.store).runtime(task_id, simple=bool(constraints.get('simpleConversation')))
        process: subprocess.Popen[bytes] | None = None
        stderr_chunks: list[bytes] = []
        stderr_thread: threading.Thread | None = None
        stdout_chunks: queue.Queue[bytes] = queue.Queue()
        stdout_thread: threading.Thread | None = None
        stdout_closed = False
        result: dict[str, Any] | None = None
        worker_error: str | None = None
        result_count = 0
        checkpoint_count = 0
        malformed_consecutive = 0
        last_valid_frame_at = time.monotonic()
        stall_reported = False
        stall_seconds = max(0.05, float(os.environ.get('AICS_AGENT_STALL_NOTICE_SECONDS', '90')))
        protocol_timeout_seconds = max(stall_seconds, float(os.environ.get('AICS_AGENT_PROTOCOL_TIMEOUT_SECONDS', '600')))
        encoded = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        try:
            try:
                process = subprocess.Popen(
                    [self.node_path, str(self.worker_path)],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    # The sidecar's inherited cwd may refer to an unlinked app
                    # directory after an update. Never call getcwd() here.
                    cwd=str(run_dir),
                    env={**os.environ, **({"ELECTRON_RUN_AS_NODE": "1"} if os.environ.get("AICS_NODE_RUN_AS_NODE") == "1" else {})},
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
                )
            except OSError as error:
                missing = not run_dir.is_dir()
                reason = "任务工作目录不存在" if missing else "Node.js 启动程序不存在" if isinstance(error, FileNotFoundError) else "无法启动本地执行进程"
                location = str(run_dir) if missing else self.node_path
                raise DesignRuntimeError(f"Agent 本地运行时启动失败（{reason}）：{location}。请重启应用后继续原任务。", kind="runtime") from error
            assert process.stdin is not None
            assert process.stdout is not None
            assert process.stderr is not None
            # Windows select() accepts sockets, not subprocess pipes. A reader
            # thread keeps streaming and cancellation portable.
            def drain_stdout() -> None:
                assert process is not None and process.stdout is not None
                try:
                    while chunk := process.stdout.read1(65536):
                        stdout_chunks.put(chunk)
                finally:
                    stdout_chunks.put(b'')

            stdout_thread = threading.Thread(target=drain_stdout, name=f"agent-stdout-{task_id[:8]}", daemon=True)
            stdout_thread.start()

            def drain_stderr() -> None:
                assert process is not None and process.stderr is not None
                try:
                    data = process.stderr.read()
                    if data:
                        stderr_chunks.append(data)
                except OSError:
                    return

            stderr_thread = threading.Thread(target=drain_stderr, name=f"agent-stderr-{task_id[:8]}", daemon=True)
            stderr_thread.start()
            process.stdin.write(encoded)
            process.stdin.close()
            buffer = b""

            def invalid_frame(raw_line: bytes, reason: str) -> None:
                nonlocal checkpoint, malformed_consecutive
                malformed_consecutive += 1
                diagnostics = list(checkpoint.get('protocolDiagnostics') or [])
                diagnostics.append({
                    'reason': reason,
                    'byteLength': len(raw_line),
                    'sha256': hashlib.sha256(raw_line).hexdigest(),
                })
                checkpoint = {**checkpoint, 'protocolDiagnostics': diagnostics[-10:]}
                if self.executions:
                    self.executions.save(task_id, checkpoint)
                if trace:
                    trace('protocol', f'Agent 协议帧无效（连续 {malformed_consecutive}/3），已保存脱敏诊断。')
                if malformed_consecutive >= 3:
                    raise DesignRuntimeError('Agent stdout 连续出现 3 个非法 JSONL 帧，已终止运行并保存诊断。', kind='runtime', recovery=checkpoint)

            def handle_frame(raw_line: bytes) -> None:
                nonlocal checkpoint, checkpoint_count, last_valid_frame_at, malformed_consecutive
                nonlocal result, result_count, stall_reported, usage_count, worker_error, worker_failure
                if not raw_line.strip():
                    return
                try:
                    message = json.loads(raw_line.decode('utf-8'))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    invalid_frame(raw_line, 'invalid_json')
                    return
                if not isinstance(message, dict):
                    invalid_frame(raw_line, 'non_object')
                    return
                message_type = message.get('type')
                if message_type not in {'event', 'sdk_trace', 'context_manifest', 'checkpoint', 'usage', 'result', 'error'}:
                    invalid_frame(raw_line, 'unknown_type')
                    return
                if message_type == 'result' and not isinstance(message.get('result'), dict):
                    invalid_frame(raw_line, 'invalid_result')
                    return
                if message_type == 'context_manifest' and not isinstance(message.get('manifest'), dict):
                    invalid_frame(raw_line, 'invalid_manifest')
                    return
                if message_type == 'sdk_trace' and not isinstance(message.get('span'), dict):
                    invalid_frame(raw_line, 'invalid_sdk_trace')
                    return
                if message_type == 'checkpoint' and not isinstance(message.get('recovery'), dict):
                    invalid_frame(raw_line, 'invalid_checkpoint')
                    return
                if message_type == 'usage' and not isinstance(message.get('usage'), dict):
                    invalid_frame(raw_line, 'invalid_usage')
                    return
                if message_type == 'error' and message.get('recovery') is not None and not isinstance(message.get('recovery'), dict):
                    invalid_frame(raw_line, 'invalid_error_recovery')
                    return
                malformed_consecutive = 0
                last_valid_frame_at = time.monotonic()
                stall_reported = False
                if message_type == 'event':
                    phase = str(message.get('phase') or 'agent')
                    detail = str(message.get('message') or '').strip()
                    if trace and detail:
                        try:
                            trace(phase, detail, message.get('data'))
                        except TypeError:
                            trace(phase, detail)
                elif message_type == 'sdk_trace' and self.provider_registry.catalog:
                    from .model_router import RouteTrace
                    RouteTrace(self.provider_registry.catalog.store).append(task_id, {'phase': 'sdk', 'provider': provider, 'model': model, 'tier': execution_policy.get('model_tier'), **message.get('span', {})})
                elif message_type == 'context_manifest' and self.executions:
                    from .agent_sessions import AgentSessionStore
                    AgentSessionStore(self.executions.store).manifest(task_id, message['manifest'])
                    if trace and message['manifest'].get('sequence'):
                        data = {key: message['manifest'].get(key) for key in (
                            'sequence', 'stage', 'model', 'estimatedInputTokens',
                            'localBeforeTokens', 'localAfterTokens', 'localCompacted',
                        ) if message['manifest'].get(key) is not None}
                        try:
                            trace('context_manifest', '已更新本轮模型上下文', data)
                        except TypeError:
                            trace('context_manifest', '已更新本轮模型上下文')
                elif message_type == 'checkpoint':
                    checkpoint_count += 1
                    checkpoint = message['recovery']
                    if self.executions:
                        self.executions.save(task_id, checkpoint)
                elif message_type == 'usage':
                    usage_count += 1
                    actual = roles.get(message.get('role'), {'provider': provider, 'baseUrl': base_url, 'model': model})
                    if catalog:
                        from .model_router import RouteTrace
                        usage = message.get('usage') or {}
                        RouteTrace(catalog.store).append(task_id, {
                            'call_kind':'sdk_response', 'stage':message.get('stage'), 'provider':actual['provider'], 'model':actual['model'],
                            'latency_ms':message.get('latencyMs'), 'status':'completed', 'submitted':True,
                            'inputTokens':usage.get('input_tokens', usage.get('inputTokens', usage.get('prompt_tokens'))),
                            'outputTokens':usage.get('output_tokens', usage.get('outputTokens', usage.get('completion_tokens'))),
                        }, record_id=message.get('recordId') or f"sdk:{attempt_id}:{message.get('sequence', usage_count)}")
                    if trace:
                        from .token_usage import cache_trace
                        usage = message.get('usage') or {}
                        totals = message.get('usageTotals') or {}
                        data = {
                            'sequence': message.get('sequence'), 'agentRound': message.get('agentRound'), 'stage': message.get('stage'),
                            'latencyMs': message.get('latencyMs'),
                            'role': message.get('role'), 'model': roles.get(message.get('role'), {}).get('model', model),
                            'inputTokens': usage.get('input_tokens', usage.get('inputTokens', usage.get('prompt_tokens'))),
                            'outputTokens': usage.get('output_tokens', usage.get('outputTokens', usage.get('completion_tokens'))),
                            **cache_trace(usage),
                            **{target: totals[source] for source, target in {
                                'requests':'totalModelCalls', 'input_tokens':'totalInputTokens', 'cached_tokens':'totalCachedTokens',
                                'cache_write_tokens':'totalCacheWriteTokens', 'cache_reported_requests':'cacheReportedCalls',
                                'cache_observed_input_tokens':'cacheObservedInputTokens', 'cache_write_reported_requests':'cacheWriteReportedCalls',
                            }.items() if source in totals},
                        }
                        try:
                            trace('model_call', '模型完成一轮调用', data)
                        except TypeError:
                            trace('model_call', '模型完成一轮调用')
                    if self.provider_registry.billing and not self.provider_registry.is_local(actual['provider']):
                        ledger = self.provider_registry.billing.record(provider=actual['provider'], base_url=actual['baseUrl'], model=actual['model'], kind='text', provider_request_id=message.get('providerRequestId'), usage=message.get('usage'), units={'inputImages': (message.get('units') or {}).get('inputImages', 0)}, record_id=message.get('recordId') or f"{attempt_id}:{message.get('sequence', usage_count)}", project_id=project_id, task_id=task_id)
                        if self.executions and message.get('manifestId'):
                            from .agent_sessions import AgentSessionStore
                            AgentSessionStore(self.executions.store).record_cost(task_id, message['manifestId'], ledger.get('points'), ledger.get('id'))
                        if message.get('reservationId'):
                            from .budget import BudgetService
                            BudgetService(catalog.store, catalog).settle(task_id, message['reservationId'], ledger.get('points'))
                elif message_type == 'result':
                    result_count += 1
                    if result_count != 1:
                        raise DesignRuntimeError('Agent 协议返回了重复的最终结果，已停止以避免状态覆盖。', kind='runtime', recovery=checkpoint)
                    result = message['result']
                    if self.executions:
                        self.executions.save(task_id, {**checkpoint, 'finalResult': result})
                elif message_type == 'error':
                    worker_error = str(message.get('message') or 'OpenAI Agents SDK 执行失败')
                    worker_failure = message
                    checkpoint = message.get('recovery') or checkpoint

            while True:
                if should_cancel and should_cancel():
                    process.kill()
                    raise DesignRuntimeError("任务已停止", kind="interrupted", recovery=checkpoint)
                try:
                    chunks = [stdout_chunks.get(timeout=min(1.0, max(0.05, stall_seconds / 2)))]
                except queue.Empty:
                    chunks = []
                for chunk in chunks:
                    if not chunk:
                        stdout_closed = True
                        continue
                    buffer += chunk
                    while b"\n" in buffer:
                        raw_line, buffer = buffer.split(b"\n", 1)
                        handle_frame(raw_line)
                idle_seconds = time.monotonic() - last_valid_frame_at
                if idle_seconds >= protocol_timeout_seconds:
                    checkpoint = {**checkpoint, 'runtimeState': {'status': 'execution_timeout', 'lastValidFrameSecondsAgo': round(idle_seconds, 1)}}
                    if self.executions:
                        self.executions.save(task_id, checkpoint)
                    process.kill()
                    raise DesignRuntimeError('Agent 连续 10 分钟没有返回有效协议事件，已终止 worker 并保存检查点。', kind='execution_timeout', recovery=checkpoint)
                if idle_seconds >= stall_seconds and not stall_reported:
                    stall_reported = True
                    if trace:
                        trace('stalled', 'Agent 已 90 秒没有返回新进度；仍在等待，检查点和已完成产物均已保留。')
                if process.poll() is not None and stdout_closed:
                    if buffer.strip():
                        handle_frame(buffer)
                    break
            return_code = process.wait(timeout=5)
            if stderr_thread:
                stderr_thread.join(timeout=2)
            if return_code != 0 or result is None:
                detail = worker_error or b"".join(stderr_chunks).decode("utf-8", errors="replace").strip()
                raise DesignRuntimeError(self._redact(detail or "OpenAI Agents SDK 未返回结果", api_key), kind=worker_failure.get("kind", "provider"), recovery=checkpoint, usage=worker_failure.get("usage"), status_code=worker_failure.get("statusCode"),
                                         submitted=worker_failure.get('submitted'), billing_certainty=worker_failure.get('billingCertainty'), retry_after=worker_failure.get('retryAfter'))
            if not checkpoint_count and trace:
                trace('protocol', 'Agent 未返回 checkpoint 帧；最终结果已保存，但恢复诊断已记录。')
            if not usage_count and result.get('provenance', {}).get('modelRequestCount') != 0:
                if trace:
                    trace('protocol', 'Agent 未返回 usage 帧；已按最终结果中的 usage 记录待核对用量。')
                if self.provider_registry.billing and not self.provider_registry.is_local(provider):
                    self.provider_registry.billing.record(provider=provider, base_url=base_url, model=model, kind="text", usage=result.get("usage"), record_id=attempt_id, project_id=project_id, task_id=task_id)
            return self._agent_result(result, provider=provider, model=model)
        except BrokenPipeError as error:
            raise DesignRuntimeError("OpenAI Agents SDK worker 输入通道已关闭") from error
        finally:
            if process is not None and result is None and not usage_count and self.provider_registry.billing and not self.provider_registry.is_local(provider):
                self.provider_registry.billing.record(provider=provider, base_url=base_url, model=model, kind="text", usage={}, record_id=attempt_id, completed=False, project_id=project_id, task_id=task_id)
            if process and process.poll() is None:
                process.kill()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
            for thread in (stdout_thread, stderr_thread):
                if thread:
                    thread.join(timeout=2)

    @classmethod
    def _agent_result(cls, payload: dict[str, Any], *, provider: str, model: str) -> AgentResult:
        raw_status = str(payload.get("status") or "succeeded").lower()
        status = raw_status if raw_status in {"succeeded", "failed"} else "succeeded"
        structured = payload.get("structured_data")
        if not isinstance(structured, dict):
            structured = {"answer": str(structured or "")}
        artifact_refs = [
            cls._artifact_ref(item)
            for item in payload.get("artifact_refs", [])
            if isinstance(item, dict)
        ]
        citations = [
            cls._citation(item)
            for item in payload.get("citations", [])
            if isinstance(item, dict)
        ]
        provenance = payload.get("provenance")
        if not isinstance(provenance, dict):
            provenance = {}
        provenance = {
            **provenance,
            "runtime": "openai-agents-sdk",
            "provider": provider,
            "model": model,
        }
        if isinstance(payload.get("usage"), dict):
            provenance["usage"] = payload["usage"]
        if isinstance(payload.get("tool_outputs"), list):
            provenance["toolOutputCount"] = len(payload["tool_outputs"])
        return AgentResult(
            status=status,
            structured_data=structured,
            artifact_refs=artifact_refs,
            citations=citations,
            assumptions=cls._string_list(payload.get("assumptions")),
            warnings=cls._string_list(payload.get("warnings")),
            next_actions=cls._string_list(payload.get("next_actions")),
            provenance=provenance,
        )

    @staticmethod
    def _artifact_ref(value: dict[str, Any]) -> ArtifactRef:
        return ArtifactRef(
            entity_type=str(value.get("entity_type") or value.get("entityType") or "asset"),
            entity_id=str(value.get("entity_id") or value.get("entityId") or value.get("id") or ""),
            version=value.get("version"),
            label=str(value.get("label")) if value.get("label") is not None else None,
        )

    @staticmethod
    def _citation(value: dict[str, Any]) -> Citation:
        return Citation(
            source_id=str(value.get("source_id") or value.get("sourceId") or ""),
            quote=str(value.get("quote") or ""),
            locator=str(value.get("locator")) if value.get("locator") is not None else None,
        )

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    @staticmethod
    def _redact(value: str, secret: str) -> str:
        if not secret:
            return value[:800]
        return value.replace(secret, "[REDACTED]")[:800]
