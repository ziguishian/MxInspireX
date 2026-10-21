"""OpenRouter asynchronous video API. Credentials stay on the API origin."""
from __future__ import annotations

import base64
import json
import mimetypes
import urllib.request
import urllib.error
from pathlib import Path
from urllib.parse import quote, urlsplit

from .http import SeedreamVideoProvider, ProviderError, _http_error_detail
from ..video_inputs import video_options


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class OpenRouterVideoProvider(SeedreamVideoProvider):
    supports_last_frame = True

    def _request(self, path, payload=None, binary=False):
        key = self.credentials.get(self.provider_key)
        if not key:
            raise ProviderError(f"未找到 {self.provider_key} 的本地 API Key")
        request = urllib.request.Request(self.endpoint.rstrip('/') + path,
            data=json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        try:
            # Content may redirect to a signed CDN URL. Never forward the key.
            opener = urllib.request.build_opener(_NoRedirect)
            try:
                response = opener.open(request, timeout=self.timeout_seconds)
            except urllib.error.HTTPError as error:
                if binary and error.code in {301, 302, 303, 307, 308}:
                    location = error.headers.get('Location', '')
                    if urlsplit(location).scheme != 'https':
                        raise ProviderError('视频下载重定向地址无效') from error
                    response = urllib.request.urlopen(location, timeout=self.timeout_seconds)
                else:
                    raise
            with response:
                content = response.read()
                if binary:
                    if not content or 'json' in str(response.headers.get('Content-Type', '')):
                        raise ProviderError('视频下载接口未返回媒体内容')
                    return content
                body = json.loads(content)
                self.last_response = body
                return body
        except urllib.error.HTTPError as error:
            raise ProviderError(f"OpenRouter 视频接口 HTTP {error.code}: {_http_error_detail(error).replace(key, '[REDACTED]')}", status_code=error.code) from error
        except (urllib.error.URLError, TimeoutError, ValueError) as error:
            raise ProviderError(f"OpenRouter 视频接口失败：{error}") from error

    def generate(self, *, prompt, source_asset=None, last_frame_asset=None, model=None, **params):
        params = video_options(params)
        options = {k: v for k, v in params.items() if k in {'duration', 'resolution', 'aspect_ratio', 'size', 'generate_audio', 'seed', 'provider'}}
        if params.get('aspectRatio') and 'aspect_ratio' not in options:
            options['aspect_ratio'] = params['aspectRatio']
        if last_frame_asset and not source_asset:
            raise ProviderError('指定尾帧时必须同时指定首帧图片')
        frames = []
        for frame_type, asset_path in [('first_frame', source_asset), ('last_frame', last_frame_asset)]:
            if not asset_path:
                continue
            path = Path(asset_path)
            if not path.is_file():
                raise ProviderError('视频参考图片不存在')
            mime = mimetypes.guess_type(path.name)[0] or 'image/png'
            if not mime.startswith('image/'):
                raise ProviderError('视频参考资产必须是图片')
            data_url = f'data:{mime};base64,' + base64.b64encode(path.read_bytes()).decode()
            frames.append({'type': 'image_url', 'image_url': {'url': data_url}, 'frame_type': frame_type})
        if frames:
            options['frame_images'] = frames
        body = self._request('/videos', {'model': model or self.model, 'prompt': prompt, **options})
        if not body.get('id'):
            raise ProviderError('视频接口未返回任务编号')
        return {'jobId': body['id'], 'status': body.get('status', 'pending'), 'model': model or self.model, 'raw': body}

    def retrieve(self, *, job_id, **_):
        path = '/videos/' + quote(str(job_id), safe='')
        body = self._request(path)
        result = {'jobId': job_id, 'status': body.get('status', 'pending'), 'raw': body, 'error': body.get('error')}
        if body.get('status') == 'completed':
            result['content'] = self._request(path + '/content?index=0', binary=True)
            result['extension'] = 'mp4'
        return result
