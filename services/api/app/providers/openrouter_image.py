"""Dedicated OpenRouter Image API with explicit raster output and references."""
import base64
import http.client
import json
import mimetypes
import urllib.request
import urllib.error
from dataclasses import dataclass
from pathlib import Path

from .http import OpenAICompatibleImageProvider, ProviderError, _http_error_detail
from ..image_output import prepare_image_output


@dataclass
class OpenRouterImageProvider(OpenAICompatibleImageProvider):
    # High-quality edits may take several minutes before the first byte.
    # This is a socket inactivity timeout, not a retry or a task deadline.
    timeout_seconds: float = 900
    supports_streaming: bool = False

    @staticmethod
    def _unconfirmed(message, code='image_result_unconfirmed'):
        return ProviderError(
            message + '；生成结果待确认，可能已计费。已停止自动重试，请先核对原请求。',
            stop_tool=True, error_code=code,
        )

    def _read_stream(self, response, key):
        """Only a completed image is an asset; previews never count as delivery."""
        data = []

        def event():
            payload = '\n'.join(data)
            data.clear()
            if not payload or payload == '[DONE]':
                return None
            value = json.loads(payload)
            if value.get('type') == 'error':
                detail = value.get('error') or {}
                detail = detail.get('message', '图像生成中断') if isinstance(detail, dict) else str(detail)
                raise ProviderError(
                    'OpenRouter 图像服务返回错误：' + str(detail).replace(key, '[REDACTED]')[:600],
                    stop_tool=True, error_code='image_generation_failed', response_received=True,
                )
            if value.get('type') == 'image_generation.completed':
                return {**{k: value[k] for k in ('id', 'model', 'created', 'usage') if k in value},
                        'data': [{k: value[k] for k in ('b64_json', 'media_type') if k in value}]}
            return None

        for raw in response:
            line = raw.decode('utf-8').rstrip('\r\n')
            if not line:
                result = event()
                if result is not None:
                    return result
            elif line.startswith('data:'):
                if line[5:].strip() == '[DONE]':
                    break
                data.append(line[5:].lstrip(' '))
        result = event()
        if result is not None:
            return result
        raise self._unconfirmed('图像响应中断，未收到最终图片')

    def generate(self, *, prompt, negative_prompt=None, model=None, **params):
        self.last_response = {}
        try:
            prompt, params = prepare_image_output(prompt, params)
            from ..image_parameters import prepare_image_parameters
            params = prepare_image_parameters(params, model=model or self.model, openrouter=True,
                                              supported_parameters=self.supported_parameters)
        except ValueError as error:
            raise ProviderError(str(error), status_code=400) from error
        key = self.credentials.get(self.provider_key)
        if not key:
            raise ProviderError(f"未找到 {self.provider_key} 的本地 API Key")
        if params.get('mask_path') or params.get('mask_asset_path'):
            raise ProviderError('当前 OpenRouter 图像接口未配置蒙版协议，请使用参考图编辑')
        fields = {'resolution', 'aspect_ratio', 'size', 'quality', 'output_format', 'background', 'output_compression', 'seed', 'provider'}
        payload = {k: v for k,v in params.items() if k in fields and v not in ('', None)}
        if params.get('aspectRatio'):
            payload['aspect_ratio'] = params['aspectRatio']
        # A canvas generation tool produces one asset; multiple images use
        # separate explicit tool calls so every charged result is saved.
        sources = list(dict.fromkeys(([params['source_asset_path']] if params.get('source_asset_path') else []) + list(params.get('source_asset_paths') or [])))
        # The catalog's streaming flag covers text-to-image generation only.
        # OpenRouter rejects stream=true for image-to-image requests, even for
        # models that support streaming. Preserve the references and request
        # the final JSON response directly; never retry by dropping the images.
        payload.update(model=model or self.model, prompt=prompt + (f'\nAvoid: {negative_prompt}' if negative_prompt else ''), n=1,
                       stream=self.supports_streaming and not sources)
        for source_path in sources:
            source = Path(source_path)
            mime = mimetypes.guess_type(source.name)[0] or 'image/png'
            data_url = f'data:{mime};base64,' + base64.b64encode(source.read_bytes()).decode()
            payload.setdefault('input_references', []).append({'type':'image_url','image_url':{'url':data_url}})
        request = urllib.request.Request(self.base_url.rstrip('/')+'/images', data=json.dumps(payload, ensure_ascii=False).encode(), headers={'Authorization':f'Bearer {key}', 'Content-Type':'application/json'}, method='POST')
        from .image_request import image_request_started
        image_request_started()
        received = False
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                headers = getattr(response, 'headers', {})
                if 'text/event-stream' in str(headers.get('Content-Type', '')).lower():
                    body = self._read_stream(response, key)
                    received = True
                else:
                    raw = response.read()
                    received = True
                    body = json.loads(raw)
            self.last_response = body
            content = base64.b64decode(body['data'][0]['b64_json'], validate=True)
            if not content:
                raise ValueError('empty image')
            return content
        except urllib.error.HTTPError as error:
            detail = _http_error_detail(error).replace(key, '[REDACTED]')
            if error.code in {400, 422} and 'streaming is not supported' in detail.lower():
                raise ProviderError(
                    '图像服务拒绝了流式响应模式，这不表示原图不支持编辑。已停止本轮自动重试；'
                    '保留原图和修改要求，不要改写提示词、移除参考图或改为纯文字重生成来重试。'
                    '请检查图像接口配置。',
                    status_code=error.code, stop_tool=True, error_code='image_streaming_unsupported',
                ) from error
            raise ProviderError(f'OpenRouter 图像接口 HTTP {error.code}: {detail}', status_code=error.code) from error
        except TimeoutError as error:
            raise self._unconfirmed('等待图像响应超时', 'image_response_timeout') from error
        except (urllib.error.URLError, OSError, http.client.HTTPException) as error:
            if isinstance(getattr(error, 'reason', None), TimeoutError):
                raise self._unconfirmed('等待图像响应超时', 'image_response_timeout') from error
            raise self._unconfirmed('图像请求连接中断，未取得完整响应') from error
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as error:
            if not received:
                raise self._unconfirmed('图像响应内容异常，未收到最终图片') from error
            raise ProviderError('图像响应内容异常，未返回可保存的图片。请求可能已计费，已停止自动重试。',
                                stop_tool=True, error_code='image_response_invalid', response_received=True) from error
