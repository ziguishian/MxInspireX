from __future__ import annotations

import json
import http.client
import base64
import mimetypes
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4
from typing import Any

from ..credentials import LocalCredentialStore
from ..model_config import DEFAULT_VIDEO_MODEL
from ..image_output import prepare_image_output


class ProviderError(RuntimeError):
    def __init__(self, message, *, status_code=None, stop_tool=False, error_code=None, response_received=False):
        super().__init__(message)
        self.status_code = status_code
        self.stop_tool = stop_tool
        self.error_code = error_code
        self.response_received = response_received


def _image_connection_lost():
    # A partial body is not a rejection and may already have incurred a charge.
    # Never expose partial image bytes, credentials or a retryable status here.
    return ProviderError('图像响应连接中断，生成结果待确认，可能已计费；已保留原请求，停止自动重发。',
                         stop_tool=True, error_code='image_result_unconfirmed')


def _http_error_detail(error: urllib.error.HTTPError) -> str:
    """Extract a gateway's useful error message without leaking headers/secrets."""
    try:
        raw = error.read().decode("utf-8", errors="replace")
    except Exception:
        raw = ""
    if not raw:
        return str(error.reason or "请求失败")
    try:
        body = json.loads(raw)
    except ValueError:
        return raw[:600]
    if isinstance(body, dict):
        error_body = body.get("error")
        if isinstance(error_body, dict) and error_body.get("message"):
            return str(error_body["message"])[:600]
        if body.get("message"):
            return str(body["message"])[:600]
        if body.get("detail"):
            return str(body["detail"])[:600]
    return raw[:600]


@dataclass
class OpenAICompatibleSpeechProvider:
    base_url: str
    provider_key: str
    model: str
    credentials: LocalCredentialStore
    api: str = "auto"

    def generate(self, *, text: str, voice: str = "alloy", speed: float = 1) -> bytes:
        key = self.credentials.get(self.provider_key)
        if not key:
            raise ProviderError(f"未找到 {self.provider_key} 的本地 API Key")
        if not text.strip() or len(text) > 4096:
            raise ProviderError("语音文本须为 1–4096 个字符")
        if self.api == "chat_completions" or re.search(r"gpt-(?:audio|4o.*audio)", self.model, re.I):
            streaming = self.provider_key == "openrouter"
            payload = {"model": self.model, "modalities": ["text", "audio"], "audio": {"voice": voice, "format": "mp3"},
                       "messages": [{"role": "user", "content": "请逐字朗读以下文本：\n" + text}], "stream": streaming}
            if streaming:
                payload["stream_options"] = {"include_usage": True}
            request = urllib.request.Request(self.base_url.rstrip("/") + "/chat/completions", data=json.dumps(payload, ensure_ascii=False).encode(),
                                             headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, method="POST")
            try:
                with urllib.request.urlopen(request, timeout=180) as response:
                    if streaming:
                        chunks = []
                        for line in response:
                            if not line.startswith(b"data:"):
                                continue
                            data = line[5:].strip()
                            if data == b"[DONE]":
                                break
                            event = json.loads(data)
                            if event.get("error"):
                                raise ProviderError("音频流返回错误：" + str(event["error"])[:300])
                            if event.get("usage"):
                                self.last_response = {"usage": event["usage"]}
                            for choice in event.get("choices", []):
                                audio = choice.get("delta", {}).get("audio", {}).get("data")
                                if audio:
                                    chunks.append(base64.b64decode(audio, validate=True))
                        if not chunks:
                            raise ProviderError("音频流未返回音频内容")
                        return b"".join(chunks)
                    body = json.loads(response.read())
                    self.last_response = body
                return base64.b64decode(body["choices"][0]["message"]["audio"]["data"], validate=True)
            except urllib.error.HTTPError as error:
                raise ProviderError(f"语音模型调用失败（HTTP {error.code}）：{_http_error_detail(error).replace(key, '[REDACTED]')}") from error
            except (urllib.error.URLError, TimeoutError, ValueError, KeyError, IndexError, TypeError) as error:
                raise ProviderError("语音模型未返回可播放的音频") from error
        payload = {"model": self.model, "input": text, "voice": voice, "speed": speed, "response_format": "mp3"}
        request = urllib.request.Request(self.base_url.rstrip("/") + "/audio/speech", data=json.dumps(payload).encode(), headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                if "json" in str(response.headers.get("Content-Type", "")):
                    raise ProviderError("音频接口未返回可播放的音频内容")
                return response.read()
        except urllib.error.HTTPError as error:
            raise ProviderError(f"音频生成失败 HTTP {error.code}: {_http_error_detail(error)}") from error
        except (urllib.error.URLError, TimeoutError) as error:
            raise ProviderError(f"音频接口连接失败：{error}") from error


@dataclass
class OpenAICompatibleTextProvider:
    base_url: str
    provider_key: str
    model: str
    credentials: LocalCredentialStore
    timeout_seconds: float = 90
    max_completion_tokens: int | None = None
    reasoning_effort: str | None = None
    requires_key: bool = True
    local: bool = False

    def complete(self, *, system: str, prompt: str, model: str | None = None, attachments: list[dict[str, Any]] | None = None, response_format: dict | None = None) -> str:
        api_key = self.credentials.get(self.provider_key) or (self.provider_key if not self.requires_key else None)
        if not api_key:
            raise ProviderError(f"未找到 {self.provider_key} 的本地 API Key")
        user_content: str | list[dict[str, Any]] = prompt
        if attachments:
            parts: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
            for attachment in attachments:
                filename = str(attachment.get("filename") or "附件")
                mention = str(attachment.get("mention") or "").strip()
                reference = f"{mention} " if mention else ""
                text = attachment.get("text")
                data = attachment.get("data")
                mime = str(attachment.get("mime") or "application/octet-stream")
                if isinstance(data, str) and mime.startswith("image/"):
                    parts.append({"type": "text", "text": f"\n[{reference}图片附件：{filename}]"})
                    parts.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}})
                elif isinstance(text, str) and text.strip():
                    parts.append({"type": "text", "text": f"\n[{reference}文件附件：{filename}]\n{text[:12000]}"})
                else:
                    parts.append({"type": "text", "text": f"\n[{reference}二进制附件：{filename}，类型 {mime}，大小 {attachment.get('byteSize', '未知')} bytes]"})
            user_content = parts
        payload_data = {"model": model or self.model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user_content}]}
        if self.max_completion_tokens is not None:
            payload_data["max_completion_tokens"] = self.max_completion_tokens
        if self.reasoning_effort is not None:
            payload_data["reasoning_effort"] = self.reasoning_effort
        if response_format:
            payload_data["response_format"] = response_format
        payload = json.dumps(payload_data, ensure_ascii=False).encode()
        request = urllib.request.Request(self.base_url.rstrip("/") + "/chat/completions", data=payload, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read())
                self.last_response = body
        except urllib.error.HTTPError as error:
            raise ProviderError(f"{self.provider_key} 请求失败: HTTP {error.code}: {_http_error_detail(error)}") from error
        except (urllib.error.URLError, TimeoutError) as error:
            raise ProviderError(f"{self.provider_key} 请求失败: {error}") from error
        try:
            return str(body["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as error:
            raise ProviderError("Provider 返回格式不符合 chat completion 契约") from error


    def complete_structured(self, *, system: str, prompt: str, schema: dict, name: str) -> str:
        return self.complete(system=system, prompt=prompt, response_format={"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}})


@dataclass
class OpenAICompatibleEmbeddingProvider:
    """Adapter for the OpenAI-compatible ``/embeddings`` contract."""

    base_url: str
    provider_key: str
    model: str
    credentials: LocalCredentialStore
    timeout_seconds: float = 90

    def embed(self, texts: list[str]) -> list[list[float]]:
        values = [str(text) for text in texts]
        if not values:
            return []
        api_key = self.credentials.get(self.provider_key)
        if not api_key:
            raise ProviderError(f"未找到 {self.provider_key} 的本地 API Key")
        payload = json.dumps({"model": self.model, "input": values}, ensure_ascii=False).encode()
        request = urllib.request.Request(
            self.base_url.rstrip("/") + "/embeddings",
            data=payload,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read())
                self.last_response = body
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as error:
            raise ProviderError(f"{self.provider_key} Embeddings 请求失败: {error}") from error
        try:
            items = body["data"]
            if not isinstance(items, list) or len(items) != len(values):
                raise ValueError("data 长度与 input 不一致")
            ordered = sorted(items, key=lambda item: int(item.get("index", 0)))
            vectors = [[float(value) for value in item["embedding"]] for item in ordered]
            if any(not vector for vector in vectors):
                raise ValueError("embedding 不能为空")
            return vectors
        except (KeyError, TypeError, ValueError, IndexError) as error:
            raise ProviderError("Provider 返回格式不符合 embeddings 契约") from error


@dataclass
class ClaudeTextProvider(OpenAICompatibleTextProvider):
    """Backward-compatible class name that still uses chat/completions."""

    pass


@dataclass
class GeminiTextProvider(OpenAICompatibleTextProvider):
    """Backward-compatible class name that still uses chat/completions."""

    pass


@dataclass
class OpenAICompatibleImageProvider:
    reports_image_request_start = True
    """Adapter for providers exposing the OpenAI images/generations contract."""

    # Keep UI-only metadata (style presets, material, renderPageNo, etc.) out
    # of the wire payload. OpenAI-compatible gateways reject unknown fields
    # with HTTP 400 instead of ignoring them.
    _SUPPORTED_FIELDS = {
        "background",
        "input_fidelity",
        "moderation",
        "n",
        "output_compression",
        "output_format",
        "quality",
        "size",
        "user",
    }

    base_url: str
    provider_key: str
    model: str
    credentials: LocalCredentialStore
    timeout_seconds: float = 180
    api: str = "images"
    supported_parameters: dict | None = None

    def generate(self, *, prompt: str, negative_prompt: str | None = None, model: str | None = None, **params: Any) -> bytes:
        # Text and image calls intentionally share one OpenAI-compatible
        # gateway credential. Keep the old openai-image alias as a fallback so
        # existing installations continue to work after upgrading.
        api_key = self.credentials.get(self.provider_key)
        if not api_key and self.provider_key == "openai-image":
            api_key = self.credentials.get("openai-compatible")
        if not api_key:
            raise ProviderError("未找到 OpenAI-compatible 的本地 API Key（文本与图像共用）")
        try:
            prompt, params = prepare_image_output(prompt, params)
            from ..image_parameters import prepare_image_parameters
            params = prepare_image_parameters(params, model=model or self.model, provider_api=self.api,
                                              supported_parameters=self.supported_parameters)
        except ValueError as error:
            raise ProviderError(str(error), status_code=400) from error
        if self.api in {"chat_completions", "gemini"}:
            if params.get("background") == "transparent":
                raise ProviderError("当前图像接口不支持 background=transparent；请选择使用 Images API 的 GPT Image 模型。", status_code=400)
            return self._generate_multimodal(prompt=prompt, model=model or self.model, api_key=api_key, params=params)
        payload_data: dict[str, Any] = {"model": model or self.model, "prompt": prompt}
        source_asset_paths = list(dict.fromkeys(([params['source_asset_path']] if params.get('source_asset_path') else []) + list(params.get('source_asset_paths') or [])))
        mask_asset_path = params.get("mask_asset_path")
        payload_data.update({key: value for key, value in params.items() if key in self._SUPPORTED_FIELDS and value is not None})
        if re.search(r"gpt-image-2(?:\.|-|$)", str(model or self.model), re.I):
            payload_data.pop("input_fidelity", None)
        if re.search(r"dall[-_ ]?e", str(model or self.model), re.I):
            payload_data["response_format"] = "b64_json"
        if mask_asset_path and not source_asset_paths:
            raise ProviderError("images/edits 的 mask 必须和上一版本图像一起提交")
        if source_asset_paths:
            payload, content_type = self._multipart_payload(payload_data, source_asset_paths, mask_asset_path)
            endpoint = self.base_url.rstrip("/") + "/images/edits"
        else:
            payload = json.dumps(payload_data, ensure_ascii=False).encode()
            content_type = "application/json"
            endpoint = self.base_url.rstrip("/") + "/images/generations"
        request = urllib.request.Request(endpoint, data=payload, headers={"Authorization": f"Bearer {api_key}", "Content-Type": content_type}, method="POST")
        from .image_request import image_request_started
        image_request_started()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read())
                self.last_response = body
        except urllib.error.HTTPError as error:
            detail = _http_error_detail(error).replace(api_key, '[REDACTED]')
            if error.code in {400, 422} and re.search(r'quality|input_fidelity', detail, re.I):
                detail = '图像质量参数被供应商拒绝，请检查模型与接口配置；请求未降档重试。' + detail
            raise ProviderError(f"{self.provider_key} 图像请求失败: HTTP {error.code}: {detail}", status_code=error.code) from error
        except (urllib.error.URLError, OSError, http.client.HTTPException) as error:
            raise _image_connection_lost() from error
        except ValueError as error:
            raise ProviderError('图像接口已返回完整响应，但内容不是有效 JSON；已停止自动重发。',
                                stop_tool=True, error_code='invalid_image_response', response_received=True) from error
        try:
            item = body["data"][0]
            if item.get("b64_json"):
                return base64.b64decode(item["b64_json"])
            image_url = item.get("url")
            if image_url:
                with urllib.request.urlopen(image_url, timeout=self.timeout_seconds) as image_response:
                    return image_response.read()
        except (urllib.error.URLError, OSError, http.client.HTTPException) as error:
            raise _image_connection_lost() from error
        except (KeyError, IndexError, TypeError, ValueError, urllib.error.URLError, urllib.error.HTTPError) as error:
            raise ProviderError("Provider 返回格式不符合 images/generations 契约") from error
        raise ProviderError("Provider 未返回图像数据")

    def _generate_multimodal(self, *, prompt, model, api_key, params):
        sources = list(dict.fromkeys(([params['source_asset_path']] if params.get('source_asset_path') else []) + list(params.get('source_asset_paths') or [])))
        if params.get("mask_asset_path"):
            raise ProviderError("当前多模态图像接口不支持蒙版，请选择支持 images/edits 的模型")
        images = [(base64.b64encode(Path(source).read_bytes()).decode('ascii'), mimetypes.guess_type(source)[0] or 'image/png') for source in sources]
        if self.api == "gemini":
            parts = [{"text": prompt}]
            parts.extend({"inlineData": {"mimeType": mime, "data": encoded}} for encoded, mime in images)
            config = {"responseModalities": ["TEXT", "IMAGE"]}
            image_config = {}
            if params.get("aspectRatio"):
                image_config["aspectRatio"] = params["aspectRatio"]
            if params.get("resolution"):
                image_config["imageSize"] = params["resolution"]
            if image_config:
                config["imageConfig"] = image_config
            payload = {"contents": [{"role": "user", "parts": parts}], "generationConfig": config}
            root = self.base_url.rstrip("/").removesuffix("/v1")
            if "openai-proxy.org" in urllib.parse.urlsplit(root).netloc and not root.endswith("/google"):
                root += "/google"
            endpoint = root.removesuffix("/v1beta") + "/v1beta/models/" + urllib.parse.quote(model.removeprefix("google/"), safe="") + ":generateContent"
        else:
            content = [{"type": "text", "text": prompt}]
            content.extend({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}} for encoded, mime in images)
            payload = {"model": model, "messages": [{"role": "user", "content": content}], "modalities": ["image", "text"], "stream": False}
            image_config = {field: params[key] for key, field in {"aspectRatio": "aspect_ratio", "resolution": "image_size"}.items() if params.get(key)}
            if image_config:
                payload["image_config"] = image_config
            endpoint = self.base_url.rstrip("/") + "/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        if self.api == "gemini":
            headers["x-goog-api-key"] = api_key
        request = urllib.request.Request(endpoint, data=json.dumps(payload, ensure_ascii=False).encode(), headers=headers, method="POST")
        from .image_request import image_request_started
        image_request_started()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read())
                self.last_response = body
            if self.api == "gemini":
                raw_usage = body.get("usageMetadata") or {}
                if raw_usage:
                    self.last_response["usage"] = {"input_tokens": raw_usage.get("promptTokenCount"), "output_tokens": raw_usage.get("candidatesTokenCount")}
                for candidate in body.get("candidates", []):
                    for part in candidate.get("content", {}).get("parts", []):
                        data = part.get("inlineData") or part.get("inline_data") or {}
                        if data.get("data") and str(data.get("mimeType", data.get("mime_type", ""))).startswith("image/"):
                            return base64.b64decode(data["data"], validate=True)
            else:
                message = (body.get("choices") or [{}])[0].get("message") or {}
                images = list(message.get("images") or [])
                if isinstance(message.get("content"), list):
                    images.extend(message["content"])
                for item in images:
                    value = item.get("image_url") or item.get("imageUrl") or {}
                    url = value.get("url") if isinstance(value, dict) else value
                    if not url:
                        continue
                    if url.startswith("data:image/") and ";base64," in url:
                        return base64.b64decode(url.split(";base64,", 1)[1], validate=True)
                    if urllib.parse.urlsplit(url).scheme in {"https", "http"}:
                        with urllib.request.urlopen(url, timeout=self.timeout_seconds) as response:
                            return response.read()
        except urllib.error.HTTPError as error:
            raise ProviderError(f"{self.provider_key} 图像接口 {self.api} 失败（HTTP {error.code}）：{_http_error_detail(error).replace(api_key, '[REDACTED]')}") from error
        except (urllib.error.URLError, OSError, http.client.HTTPException) as error:
            raise _image_connection_lost() from error
        except (ValueError, TypeError, KeyError) as error:
            raise ProviderError(f"{self.provider_key} 图像接口 {self.api} 返回无效图像或连接失败") from error
        raise ProviderError("模型没有返回图像；请确认该模型和中转站支持图像生成")

    @staticmethod
    def _multipart_payload(fields: dict[str, Any], source_asset_path: str | list[str], mask_asset_path: str | None = None) -> tuple[bytes, str]:
        boundary = f"----aics-{uuid4().hex}"
        chunks: list[bytes] = []
        for key, value in fields.items():
            if value is None:
                continue
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)
            chunks.extend([f"--{boundary}\r\n".encode(), f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode(), str(value).encode(), b"\r\n"])
        sources = source_asset_path if isinstance(source_asset_path, list) else [source_asset_path]
        image_field = 'image[]' if len(sources) > 1 else 'image'
        for field_name, path_value in [*((image_field, source) for source in sources), ('mask', mask_asset_path)]:
            if not path_value:
                continue
            path = Path(str(path_value))
            if not path.is_file():
                raise ProviderError(f"图像编辑输入资产不存在: {path}")
            mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            chunks.extend([f"--{boundary}\r\n".encode(), f'Content-Disposition: form-data; name="{field_name}"; filename="{path.name}"\r\n'.encode(), f"Content-Type: {mime}\r\n\r\n".encode(), path.read_bytes(), b"\r\n"])
        chunks.append(f"--{boundary}--\r\n".encode())
        return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


@dataclass
class Generic3DProvider:
    provider_key: str
    credentials: LocalCredentialStore
    endpoint: str | None = None

    def generate(self, *, prompt: str, source_asset: str | None = None, output_format: str = "glb", **params: Any) -> dict[str, Any]:
        """Declare a normalized 3D job without coupling the domain to a vendor."""
        if not self.endpoint:
            raise ProviderError(f"{self.provider_key} 尚未配置 endpoint")
        if not self.credentials.get(self.provider_key):
            raise ProviderError(f"未找到 {self.provider_key} 的本地 API Key")
        # A generic gateway may submit the task outside this process. Preserve
        # an optional gateway-provided id so the normalized refresh contract
        # can still be used without knowing the vendor's schema.
        job_id = params.get("jobId") or params.get("job_id")
        return {"provider": self.provider_key, "status": "submitted", "jobId": job_id, "prompt": prompt, "sourceAsset": source_asset, "outputFormat": output_format, "params": params}

    def retrieve(self, *, job_id: str, prompt: str = "", source_asset: str | None = None, output_format: str = "glb", **params: Any) -> dict[str, Any]:
        if not self.endpoint:
            raise ProviderError(f"{self.provider_key} 尚未配置 endpoint")
        api_key = self.credentials.get(self.provider_key)
        if not api_key:
            raise ProviderError(f"未找到 {self.provider_key} 的本地 API Key")
        endpoint = self.endpoint.rstrip("/")
        if not endpoint.endswith(("/jobs", "/tasks", "/generations")):
            endpoint += "/jobs"
        endpoint += f"/{urllib.parse.quote(str(job_id), safe='')}"
        request = urllib.request.Request(endpoint, headers={"Authorization": f"Bearer {api_key}", "x-api-key": api_key, "Content-Type": "application/json"}, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                body = json.loads(response.read())
                self.last_response = body
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as error:
            raise ProviderError(f"{self.provider_key} 3D 任务查询失败: {error}") from error
        return _normalize_3d_result(body=body, provider=self.provider_key, prompt=prompt, source_asset=source_asset, output_format=output_format, params=params, adapter="generic")


@dataclass
class Native3DProvider:
    """Native vendor adapter with one normalized output contract.

    The endpoint is deliberately user-configured because vendor regions and
    API versions differ. The adapter chooses a conservative provider path,
    sends the key only in the local process, and normalizes common task-id and
    status fields for the rest of the app.
    """

    provider_key: str
    credentials: LocalCredentialStore
    endpoint: str | None = None
    timeout_seconds: float = 180

    _paths = {"meshy": "/openapi/v2/text-to-3d", "tripo": "/v2/openapi/task", "rodin": "/api/v1/rodin", "hunyuan3d": "/v1/3d/generations"}

    def generate(self, *, prompt: str, source_asset: str | None = None, output_format: str = "glb", **params: Any) -> dict[str, Any]:
        if not self.endpoint:
            raise ProviderError(f"{self.provider_key} 尚未配置 endpoint")
        api_key = self.credentials.get(self.provider_key)
        if not api_key:
            raise ProviderError(f"未找到 {self.provider_key} 的本地 API Key")
        payload = {"prompt": prompt, "output_format": output_format, **params}
        if source_asset:
            payload["source_asset"] = source_asset
        endpoint = self.endpoint.rstrip("/")
        path = self._paths.get(self.provider_key, "")
        if path and not endpoint.endswith(path):
            endpoint += path
        request = urllib.request.Request(endpoint, data=json.dumps(payload, ensure_ascii=False).encode(), headers={"Authorization": f"Bearer {api_key}", "x-api-key": api_key, "Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read())
                self.last_response = body
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as error:
            raise ProviderError(f"{self.provider_key} 原生 3D 请求失败: {error}") from error
        return _normalize_3d_result(body=body, provider=self.provider_key, prompt=prompt, source_asset=source_asset, output_format=output_format, params=params, adapter="native")

    def retrieve(self, *, job_id: str, prompt: str = "", source_asset: str | None = None, output_format: str = "glb", **params: Any) -> dict[str, Any]:
        """Retrieve a native 3D task using the same normalized contract.

        Vendor endpoints differ, but the common task-resource shape is stable:
        the configured endpoint may be a host, a collection, or the submit
        path. We append the provider's known collection and task id only when
        the caller has not already supplied it.
        """
        if not self.endpoint:
            raise ProviderError(f"{self.provider_key} 尚未配置 endpoint")
        api_key = self.credentials.get(self.provider_key)
        if not api_key:
            raise ProviderError(f"未找到 {self.provider_key} 的本地 API Key")
        endpoint = self.endpoint.rstrip("/")
        path = self._paths.get(self.provider_key, "")
        if path and endpoint.endswith(path):
            endpoint += f"/{urllib.parse.quote(str(job_id), safe='')}"
        elif endpoint.endswith(("/jobs", "/tasks", "/generations")):
            endpoint += f"/{urllib.parse.quote(str(job_id), safe='')}"
        else:
            endpoint += path + f"/{urllib.parse.quote(str(job_id), safe='')}"
        request = urllib.request.Request(endpoint, headers={"Authorization": f"Bearer {api_key}", "x-api-key": api_key, "Content-Type": "application/json"}, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read())
                self.last_response = body
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as error:
            raise ProviderError(f"{self.provider_key} 原生 3D 任务查询失败: {error}") from error
        return _normalize_3d_result(body=body, provider=self.provider_key, prompt=prompt, source_asset=source_asset, output_format=output_format, params=params, adapter="native")


def _normalize_task_status(value: Any, *, has_content: bool = False) -> str:
    """Map common vendor status values to the app's small state machine."""
    if has_content:
        return "succeeded"
    normalized = str(value or "submitted").strip().lower()
    if normalized in {"done", "complete", "completed", "success", "succeeded", "finished", "ready"}:
        return "succeeded"
    if normalized in {"failed", "failure", "error", "canceled", "cancelled", "rejected"}:
        return "failed"
    if normalized in {"running", "processing", "in_progress", "in-progress", "generating"}:
        return "running"
    return "submitted"


def _normalize_3d_result(*, body: dict[str, Any], provider: str, prompt: str, source_asset: str | None, output_format: str, params: dict[str, Any], adapter: str) -> dict[str, Any]:
    data = body.get("data")
    item = data[0] if isinstance(data, list) and data else data if isinstance(data, dict) else body
    item = item if isinstance(item, dict) else {}
    job_id = item.get("jobId") or item.get("job_id") or item.get("taskId") or item.get("task_id") or body.get("jobId") or body.get("job_id") or body.get("taskId") or body.get("task_id") or body.get("id")
    content = None
    for encoded_key in ("b64_json", "model_base64", "modelBase64", "file_base64", "fileBase64"):
        if item.get(encoded_key):
            try:
                content = base64.b64decode(item[encoded_key])
            except (ValueError, TypeError):
                content = None
            break
    model_url = item.get("model_url") or item.get("modelUrl") or item.get("download_url") or item.get("downloadUrl") or item.get("url")
    if model_url and content is None:
        try:
            with urllib.request.urlopen(model_url, timeout=180) as model_response:
                content = model_response.read()
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
            content = None
    status = _normalize_task_status(item.get("status") or body.get("status"), has_content=bool(content))
    result = {"provider": provider, "adapter": adapter, "status": status, "jobId": job_id, "prompt": prompt, "sourceAsset": source_asset, "outputFormat": output_format, "params": params, "raw": body}
    if content:
        result["content"] = content
        result["extension"] = str(item.get("outputFormat") or item.get("output_format") or output_format).lstrip(".")
    return result


@dataclass
class SeedreamVideoProvider:
    """Seedream image/text-to-video adapter with a normalized job result."""

    provider_key: str
    credentials: LocalCredentialStore
    endpoint: str | None = None
    model: str = DEFAULT_VIDEO_MODEL
    local: bool = False
    timeout_seconds: float = 180

    def generate(self, *, prompt: str, source_asset: str | None = None, model: str | None = None, **params: Any) -> dict[str, Any]:
        selected_model = model or self.model
        if self.local:
            return {"provider": self.provider_key, "adapter": "local-placeholder", "status": "succeeded", "jobId": f"local-video-{abs(hash(prompt)) % 1000000:06d}", "model": selected_model, "prompt": prompt, "sourceAsset": source_asset, "params": params}
        if not self.endpoint:
            raise ProviderError("seedream 尚未配置 endpoint")
        api_key = self.credentials.get(self.provider_key)
        if not api_key:
            raise ProviderError("未找到 seedream 的本地 API Key")
        if "volcengineapi.com" in self.endpoint.lower() or params.get("req_key") or params.get("reqKey"):
            return self._generate_volcengine(prompt=prompt, source_asset=source_asset, api_key=api_key, endpoint=self.endpoint, params=params)
        payload = {"model": selected_model, "prompt": prompt, **params}
        if source_asset:
            payload["source_asset"] = source_asset
        endpoint = self.endpoint.rstrip("/")
        if not any(endpoint.endswith(suffix) for suffix in ("/videos/generations", "/video/generations", "/contents/generations/tasks", "/tasks")):
            endpoint += "/videos/generations"
        request = urllib.request.Request(endpoint, data=json.dumps(payload, ensure_ascii=False).encode(), headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read())
                self.last_response = body
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as error:
            raise ProviderError(f"seedream 视频请求失败: {error}") from error
        item = body.get("data", [{}])[0] if isinstance(body.get("data"), list) and body.get("data") else body
        content = None
        if isinstance(item, dict) and item.get("b64_json"):
            try:
                content = base64.b64decode(item["b64_json"])
            except (ValueError, TypeError):
                content = None
        video_url = (item.get("video_url") or item.get("videoUrl") or item.get("url")) if isinstance(item, dict) else None
        if video_url and content is None:
            try:
                with urllib.request.urlopen(video_url, timeout=self.timeout_seconds) as video_response:
                    content = video_response.read()
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
                content = None
        item_status = item.get("status") if isinstance(item, dict) else None
        item_job_id = (item.get("jobId") or item.get("job_id") or item.get("id")) if isinstance(item, dict) else None
        result = {"provider": self.provider_key, "adapter": "native", "status": body.get("status") or item_status or "submitted", "jobId": body.get("jobId") or body.get("id") or body.get("task_id") or item_job_id, "model": selected_model, "prompt": prompt, "sourceAsset": source_asset, "params": params, "raw": body}
        if content:
            result["content"] = content
            result["extension"] = "mp4"
        return result

    def _generate_volcengine(self, *, prompt: str, source_asset: str | None, api_key: str, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        """Submit a Jimeng/Seedream task through the Volcengine CV gateway.

        Volcengine publishes an Action/Version query contract rather than the
        OpenAI-style ``/videos/generations`` path. Authentication is kept at
        the local gateway boundary; callers can use a signed proxy or provide
        compatible Authorization headers through their deployment.
        """
        options = dict(params)
        req_key = str(options.pop("req_key", options.pop("reqKey", "jimeng_i2v_first_v30" if source_asset else "jimeng_t2v_v30")))
        action_defaults = {
            "jimeng_t2v_v30": "JimengT2VV30SubmitTask",
            "jimeng_i2v_first_v30": "JimengI2VFirstV30SubmitTask",
            "jimeng_i2v_first_tail_v30": "JimengI2VFirstTailV30SubmitTask",
        }
        action = str(options.pop("Action", options.pop("action", action_defaults.get(req_key, "JimengT2VV30SubmitTask"))))
        version = str(options.pop("Version", options.pop("version", "2024-06-06")))
        payload: dict[str, Any] = {"req_key": req_key, "prompt": prompt, **options}
        if source_asset:
            source_path = Path(source_asset)
            if source_path.is_file():
                payload["binary_data_base64"] = [base64.b64encode(source_path.read_bytes()).decode("ascii")]
            else:
                payload["image_urls"] = [source_asset]
        query = urllib.parse.urlencode({"Action": action, "Version": version})
        separator = "&" if "?" in endpoint else "?"
        request = urllib.request.Request(endpoint.rstrip("/") + separator + query, data=json.dumps(payload, ensure_ascii=False).encode(), headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read())
                self.last_response = body
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as error:
            raise ProviderError(f"seedream 视频请求失败: {error}") from error
        data = body.get("data") if isinstance(body.get("data"), dict) else {}
        video_url = data.get("video_url") or data.get("videoUrl")
        content = None
        if video_url:
            try:
                with urllib.request.urlopen(video_url, timeout=self.timeout_seconds) as video_response:
                    content = video_response.read()
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
                content = None
        result = {"provider": self.provider_key, "adapter": "volcengine-native", "status": data.get("status") or body.get("status") or "submitted", "jobId": data.get("task_id") or data.get("taskId") or body.get("task_id") or body.get("taskId"), "prompt": prompt, "sourceAsset": source_asset, "params": {"req_key": req_key, **options}, "raw": body}
        if content:
            result["content"] = content
            result["extension"] = "mp4"
        return result

    def retrieve(self, *, job_id: str, prompt: str = "", source_asset: str | None = None, model: str | None = None, **params: Any) -> dict[str, Any]:
        """Refresh an asynchronous video task using the provider's job id."""
        selected_model = model or self.model
        if self.local:
            return {"provider": self.provider_key, "adapter": "local-placeholder", "status": "succeeded", "jobId": job_id, "model": selected_model, "prompt": prompt, "sourceAsset": source_asset, "params": params}
        if not self.endpoint:
            raise ProviderError("seedream 尚未配置 endpoint")
        api_key = self.credentials.get(self.provider_key)
        if not api_key:
            raise ProviderError("未找到 seedream 的本地 API Key")
        if "volcengineapi.com" in self.endpoint.lower() or params.get("req_key") or params.get("reqKey"):
            return self._retrieve_volcengine(job_id=job_id, prompt=prompt, source_asset=source_asset, model=selected_model, api_key=api_key, endpoint=self.endpoint, params=params)
        endpoint = self.endpoint.rstrip("/")
        if not any(endpoint.endswith(suffix) for suffix in ("/videos/generations", "/video/generations", "/contents/generations/tasks", "/tasks")):
            endpoint += "/videos/generations"
        endpoint += f"/{urllib.parse.quote(str(job_id), safe='')}"
        request = urllib.request.Request(endpoint, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read())
                self.last_response = body
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as error:
            raise ProviderError(f"seedream 视频任务查询失败: {error}") from error
        return self._normalize_video_result(body=body, prompt=prompt, source_asset=source_asset, model=selected_model, params=params, adapter="native")

    def _retrieve_volcengine(self, *, job_id: str, prompt: str, source_asset: str | None, model: str, api_key: str, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        options = dict(params)
        req_key = str(options.pop("req_key", options.pop("reqKey", "jimeng_i2v_first_v30" if source_asset else "jimeng_t2v_v30")))
        submit_actions = {
            "jimeng_t2v_v30": "JimengT2VV30GetResult",
            "jimeng_i2v_first_v30": "JimengI2VFirstV30GetResult",
            "jimeng_i2v_first_tail_v30": "JimengI2VFirstTailV30GetResult",
        }
        action = str(options.pop("Action", options.pop("action", submit_actions.get(req_key, "JimengT2VV30GetResult"))))
        version = str(options.pop("Version", options.pop("version", "2024-06-06")))
        query = urllib.parse.urlencode({"Action": action, "Version": version})
        separator = "&" if "?" in endpoint else "?"
        payload = {"req_key": req_key, "task_id": str(job_id), **options}
        request = urllib.request.Request(endpoint.rstrip("/") + separator + query, data=json.dumps(payload, ensure_ascii=False).encode(), headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read())
                self.last_response = body
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as error:
            raise ProviderError(f"seedream 视频任务查询失败: {error}") from error
        return self._normalize_video_result(body=body, prompt=prompt, source_asset=source_asset, model=model, params=params, adapter="volcengine-native")

    def _normalize_video_result(self, *, body: dict[str, Any], prompt: str, source_asset: str | None, model: str, params: dict[str, Any] | None = None, adapter: str) -> dict[str, Any]:
        data = body.get("data")
        item = data[0] if isinstance(data, list) and data else data if isinstance(data, dict) else body
        item = item if isinstance(item, dict) else {}
        video_url = item.get("video_url") or item.get("videoUrl") or item.get("url")
        content = None
        if item.get("b64_json"):
            try:
                content = base64.b64decode(item["b64_json"])
            except (ValueError, TypeError):
                content = None
        if video_url and content is None:
            try:
                with urllib.request.urlopen(video_url, timeout=self.timeout_seconds) as video_response:
                    content = video_response.read()
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
                content = None
        result = {"provider": self.provider_key, "adapter": adapter, "status": item.get("status") or body.get("status") or "submitted", "jobId": item.get("jobId") or item.get("job_id") or item.get("taskId") or item.get("task_id") or body.get("jobId") or body.get("job_id") or body.get("task_id") or body.get("id"), "model": model, "prompt": prompt, "sourceAsset": source_asset, "params": dict(params or {}), "raw": body}
        if content:
            result["content"] = content
            result["extension"] = "mp4"
        return result
