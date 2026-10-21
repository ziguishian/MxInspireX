"""EvoLink asynchronous image/video transport and temporary reference upload."""
from __future__ import annotations

import base64
from contextlib import contextmanager
import http.client
import hashlib
import json
import mimetypes
import time
import threading
import urllib.error
import urllib.request
from pathlib import Path
from datetime import datetime
from urllib.parse import quote, urlsplit

from .http import ProviderError, OpenAICompatibleImageProvider, SeedreamVideoProvider, _http_error_detail
from .openrouter_video import _NoRedirect
from .image_request import image_request_started
from ..image_output import prepare_image_output
from ..video_inputs import video_options


class EvoLinkTransport:
    poll_interval = 3
    poll_timeout = 900
    user_agent = 'MxinspireX/0.2.0'
    _upload_cache = {}
    _upload_cache_lock = threading.Lock()

    @contextmanager
    def _image_phase(self, phase):
        started = time.monotonic()
        try:
            yield
        finally:
            self.last_timings[phase] = self.last_timings.get(phase, 0) + round((time.monotonic() - started) * 1000)

    def _json(self, path, payload=None, *, upload=False):
        key = self.credentials.get(self.provider_key)
        if not key:
            raise ProviderError('未找到 EvoLink 的本地 API Key')
        root = 'https://files-api.evolink.ai/api/v1' if upload else (getattr(self, 'base_url', None) or self.endpoint).rstrip('/')
        request = urllib.request.Request(root + path,
            data=json.dumps(payload, ensure_ascii=False).encode('utf-8') if payload is not None else None,
            headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json',
                     'Accept': 'application/json', 'User-Agent': self.user_agent})
        try:
            # Never forward credentials through redirects to a CDN/another host.
            with urllib.request.build_opener(_NoRedirect).open(request, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read())
            if not isinstance(body, dict):
                raise ValueError('invalid task response')
            return body
        except urllib.error.HTTPError as error:
            raise ProviderError(f'EvoLink 请求失败（HTTP {error.code}）：{_http_error_detail(error).replace(key, "[REDACTED]")}', status_code=error.code) from error
        except (OSError, http.client.HTTPException, ValueError) as error:
            raise ProviderError('EvoLink 连接中断或响应无效，请检查任务状态后继续。', stop_tool=True,
                                error_code='provider_result_unconfirmed') from error

    def _upload(self, source):
        path = Path(source)
        if not path.is_file():
            raise ProviderError('参考图片文件不存在', status_code=400)
        mime = mimetypes.guess_type(path.name)[0] or ''
        if mime not in {'image/png', 'image/jpeg', 'image/webp'} or path.stat().st_size > 20 * 1024 * 1024:
            raise ProviderError('EvoLink 参考图须为 PNG、JPEG 或 WebP，且不超过 20 MB', status_code=400)
        content = path.read_bytes()
        credential = self.credentials.get(self.provider_key) or ''
        identity = (str(path.resolve()), hashlib.sha256(content).hexdigest(),
                    hashlib.sha256(credential.encode()).hexdigest())
        # Process-local only, isolated by file and credential. Reserve the full
        # polling window before expiry; missing/invalid expiry is never cached.
        with self._upload_cache_lock:
            cached = self._upload_cache.get(identity)
            if cached and cached[1] > time.time() + self.poll_timeout + 60:
                self.last_upload_cache_hits = getattr(self, 'last_upload_cache_hits', 0) + 1
                return cached[0]
        try:
            body = self._json('/files/upload/base64', {'base64_data': f'data:{mime};base64,' + base64.b64encode(content).decode('ascii')}, upload=True)
        except ProviderError as error:
            # Upload precedes generation dispatch. Keep the failed phase clear
            # and stop here instead of retrying or dropping the reference.
            raise ProviderError(f'参考图上传失败，尚未提交生成请求：{error}', status_code=error.status_code,
                                stop_tool=True, error_code='reference_upload_failed') from error
        url = (body.get('data') or {}).get('file_url')
        if body.get('success') is not True or not isinstance(url, str) or urlsplit(url).scheme != 'https':
            raise ProviderError('EvoLink 参考图上传未返回有效地址，尚未提交生成请求',
                                stop_tool=True, error_code='reference_upload_failed')
        try:
            expiry = datetime.fromisoformat(body['data']['expires_at'].replace('Z', '+00:00'))
            expires_at = min(expiry.timestamp(), time.time() + 72 * 3600) if expiry.tzinfo else 0
        except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
            expires_at = 0
        if expires_at > time.time() + self.poll_timeout + 60:
            with self._upload_cache_lock:
                for key, entry in list(self._upload_cache.items()):
                    if entry[1] <= time.time() + self.poll_timeout + 60:
                        self._upload_cache.pop(key, None)
                if len(self._upload_cache) >= 128:
                    self._upload_cache.pop(next(iter(self._upload_cache)))
                self._upload_cache[identity] = (url, expires_at)
        return url

    def _query_task(self, task_id):
        for attempt in range(3):
            try:
                body = self._json('/tasks/' + quote(task_id, safe=''))
            except ProviderError as error:
                if attempt < 2 and (error.status_code is None or error.status_code in {408,429,500,502,503,504}):
                    time.sleep(attempt + 1)
                    continue
                raise
            if body.get('id') != task_id:
                raise ProviderError('EvoLink 返回了不匹配的任务编号', stop_tool=True)
            return body

    def _remember(self, body):
        from ..evolink_billing import normalize_usage
        usage = normalize_usage(body.get('usage'), completed=body.get('status') == 'completed')
        self.last_response = {**body, 'usage': usage}
        if getattr(self, 'on_task', None):
            self.on_task(body)
        # Task duration is processing time, not billable video length.
        self.last_response.pop('duration', None)
        if body.get('video_duration') is not None:
            self.last_response['duration'] = body['video_duration']

    def _download(self, body):
        urls = body.get('results') or [item.get('url') for item in body.get('result_data', []) if isinstance(item, dict)]
        url = urls[0] if isinstance(urls, list) and urls else None
        parsed = urlsplit(url) if isinstance(url, str) else None
        if not parsed or parsed.scheme not in {'https', 'http'} or not parsed.hostname or parsed.username or parsed.password:
            raise ProviderError('EvoLink 任务已完成，但没有有效的媒体下载地址', stop_tool=True)
        # Result URLs are signed and public. No API Key leaves the API origin.
        for attempt in range(3):
            try:
                request = urllib.request.Request(url, headers={'User-Agent': self.user_agent})
                with urllib.request.urlopen(request, timeout=min(self.timeout_seconds, 60)) as response:
                    content = response.read()
                if not content:
                    raise ValueError('empty media')
                return content
            except (OSError, http.client.HTTPException, ValueError) as error:
                # Only retry the public GET, never the paid generation POST.
                transient = not isinstance(error, urllib.error.HTTPError) or error.code in {408, 429, 500, 502, 503, 504}
                if attempt < 2 and transient:
                    time.sleep(attempt + 1)
                    continue
                raise ProviderError(f'EvoLink 结果下载失败，任务 {body.get("id", "")} 已生成，请在产物记录中取回原结果。', stop_tool=True, error_code='provider_result_unconfirmed') from error


class EvoLinkImageProvider(EvoLinkTransport, OpenAICompatibleImageProvider):
    def retrieve(self, *, job_id):
        body = self._query_task(job_id)
        self._remember(body)
        result = {'jobId': job_id, 'status': body.get('status'), 'raw': self.last_response}
        if body.get('status') == 'completed':
            result['content'] = self._download(body)
        return result

    def generate(self, *, prompt, negative_prompt=None, model=None, **params):
        self.last_timings = {}
        self.last_upload_cache_hits = 0
        from ..evolink import image_parameters
        model = model or self.model
        try:
            prompt, params = prepare_image_output(prompt, params)
            params = image_parameters(params, model)
        except ValueError as error:
            raise ProviderError(str(error), status_code=400) from error
        # The workspace's image call returns one asset; don't pay for dropped outputs.
        if params.get('n', 1) != 1:
            raise ProviderError('请使用批量图像任务生成多张图片，单次图像调用仅支持 n=1', status_code=400)
        sources = list(dict.fromkeys(([params['source_asset_path']] if params.get('source_asset_path') else []) + list(params.get('source_asset_paths') or [])))
        mask = params.get('mask_asset_path')
        if mask and (not sources or 'gpt-image' not in model.lower()):
            raise ProviderError('蒙版编辑需要原图和支持蒙版的 GPT Image 模型', status_code=400)
        reference_limit = 16 if 'gpt-image' in model.lower() else 3 if 'qwen-image' in model.lower() else 10 if 'seedream-5.0-pro' in model.lower() else 14
        if len(sources) > reference_limit:
            raise ProviderError('参考图数量超过 EvoLink 模型限制', status_code=400)
        gpt = 'gpt-image' in model.lower()
        if params.get('background') == 'transparent' and not gpt:
            raise ProviderError('当前 EvoLink 模型未声明透明输出，请选择 GPT Image', status_code=400)
        fields = {'size', 'quality', 'n'} | ({'resolution', 'background', 'output_format'} if gpt else {'output_format'} if 'seedream-5.0-pro' in model.lower() else set())
        payload = {'model': model, 'prompt': prompt, **{k: v for k, v in params.items() if k in fields and v is not None}}
        with self._image_phase('referenceUploadMs'):
            if sources:
                payload['image_urls'] = [self._upload(path) for path in sources]
            if mask:
                payload['mask_url'] = self._upload(mask)
        image_request_started()
        try:
            with self._image_phase('providerSubmitMs'):
                body = self._json('/images/generations', payload)
        except ProviderError as error:
            if error.status_code is None or error.status_code >= 500:
                error.stop_tool = True
            raise
        task_id = body.get('id')
        if not isinstance(task_id, str) or not task_id:
            raise ProviderError('EvoLink 未返回任务编号，生成结果待确认，请勿重复提交', stop_tool=True)
        self._remember(body)  # Keep the accepted task ID even if polling/download fails.
        with self._image_phase('providerWaitMs'):
            body = self._wait_image(task_id, body)
        with self._image_phase('resultDownloadMs'):
            return self._download(body)

    def _wait_image(self, task_id, body):
        deadline = time.monotonic() + self.poll_timeout
        while body.get('status') not in {'completed', 'failed', 'cancelled'}:
            if time.monotonic() >= deadline:
                raise ProviderError(f'EvoLink 任务 {task_id} 仍在生成，请在服务商控制台查询；已停止自动重发。', stop_tool=True, error_code='provider_result_unconfirmed')
            observed_status = body.get('status')
            observed_started = time.monotonic()
            time.sleep(self.poll_interval)
            try:
                body = self._query_task(task_id)
                self._remember(body)
            except ProviderError as error:
                # A failed status read is never evidence that submission failed.
                raise ProviderError(f'EvoLink 任务 {task_id} 状态查询失败；请保留任务编号查询，勿重复生成。', stop_tool=True, error_code='image_result_unconfirmed') from error
            finally:
                phase = {'pending':'observedQueueMs','queued':'observedQueueMs','processing':'observedProcessingMs','running':'observedProcessingMs'}.get(observed_status)
                if phase:
                    self.last_timings[phase] = self.last_timings.get(phase, 0) + round((time.monotonic() - observed_started) * 1000)
        self._remember(body)
        if body.get('status') != 'completed':
            detail = str((body.get('error') or {}).get('message') or '任务失败或取消')
            key = self.credentials.get(self.provider_key) or ''
            raise ProviderError(f'EvoLink 任务 {task_id}：{detail.replace(key, "[REDACTED]") if key else detail}', stop_tool=True)
        return body


class EvoLinkAudioProvider(EvoLinkImageProvider):
    def generate(self, *, text, voice=None, speed=1):
        if self.model != 'qwen-audio-3.1-tts-flash':
            raise ProviderError('当前 EvoLink 语音接口支持 Qwen Audio 3.1 TTS Flash，请重新选择模型', status_code=400)
        if not text.strip() or len(text) > 5000 or not 0.5 <= speed <= 2:
            raise ProviderError('语音文本须为 1–5000 字，语速范围为 0.5–2', status_code=400)
        self.last_timings = {}
        body = self._json('/audios/generations', {'model':self.model,'prompt':text,
            'voice':voice or 'longanhuan_v3.1','speech_rate':speed,'response_format':'mp3'})
        if not isinstance(body.get('id'), str) or not body['id']:
            raise ProviderError('EvoLink 未返回音频任务编号，结果待确认，请勿重复提交', stop_tool=True)
        self._remember(body)
        return self._download(self._wait_image(body['id'], body))


class EvoLinkVideoProvider(EvoLinkTransport, SeedreamVideoProvider):
    supports_last_frame = True

    def generate(self, *, prompt, source_asset=None, last_frame_asset=None, model=None, **params):
        params = video_options(params)
        model = model or self.model
        if last_frame_asset and not source_asset:
            raise ProviderError('指定尾帧时必须同时指定首帧图片', status_code=400)
        if source_asset and 'text-to-video' in model:
            raise ProviderError('当前模型仅支持文生视频，请选择对应的 image-to-video 模型', status_code=400)
        if not source_asset and ('image-to-video' in model or 'reference-to-video' in model):
            raise ProviderError('当前视频模型需要参考图片', status_code=400)
        if last_frame_asset and 'reference-to-video' in model:
            raise ProviderError('参考视频模型不保证尾帧，请选择 image-to-video 模型使用首尾帧', status_code=400)
        if params.get('n', 1) != 1:
            raise ProviderError('单次视频任务仅支持 n=1，请分别创建多个任务', status_code=400)
        options = {k: v for k, v in params.items() if k in {'duration', 'quality', 'aspect_ratio', 'generate_audio', 'seed'}}
        if params.get('resolution'):
            options['quality'] = str(params['resolution']).lower()
        if params.get('aspectRatio'):
            options['aspect_ratio'] = params['aspectRatio']
        if options.get('aspect_ratio') == 'auto':
            options.pop('aspect_ratio')
        if 'sora' in model.lower():
            if last_frame_asset:
                raise ProviderError('EvoLink Sora 仅支持一张首帧图，不支持尾帧', status_code=400)
            if options.get('duration', 4) not in {4, 8, 12}:
                raise ProviderError('EvoLink Sora 时长须为 4、8 或 12 秒', status_code=400)
            if options.get('quality') not in {None, '720p'}:
                raise ProviderError('当前 EvoLink Sora 接口仅支持 720p', status_code=400)
            if options.get('generate_audio') is False or options.get('seed') is not None:
                raise ProviderError('当前 EvoLink Sora 接口不支持关闭音频或设置随机种子', status_code=400)
            for field in ('quality', 'generate_audio', 'seed'):
                options.pop(field, None)
        h3 = 'minimax-h3' in model.lower()
        if h3:
            if options.get('quality') not in {None, '2k'}:
                raise ProviderError('EvoLink MiniMax H3 仅支持 2k，请明确选择此分辨率', status_code=400)
            if not 4 <= options.get('duration', 5) <= 15:
                raise ProviderError('EvoLink MiniMax H3 时长须为 4–15 秒', status_code=400)
            if 'generate_audio' in options or 'seed' in options:
                raise ProviderError('EvoLink MiniMax H3 接口不支持音频开关或随机种子参数', status_code=400)
            if 'image-to-video' in model and options.get('aspect_ratio') not in {None, 'adaptive'}:
                raise ProviderError('MiniMax H3 图生视频沿用首帧比例，请将视频比例设为自动', status_code=400)
            if 'image-to-video' in model:
                options.pop('aspect_ratio', None)
        frames = [self._upload(path) for path in (source_asset, last_frame_asset) if path]
        if frames:
            if h3 and 'image-to-video' in model:
                options.update(zip(('image_start', 'image_end'), frames))
            else:
                options['image_urls'] = frames
        try:
            body = self._json('/videos/generations', {'model': model, 'prompt': prompt, **options})
        except ProviderError as error:
            if error.status_code is None or error.status_code >= 500:
                error.stop_tool = True
            raise
        if not body.get('id'):
            raise ProviderError('EvoLink 视频请求未返回任务编号，请勿重复提交', stop_tool=True)
        self._remember(body)
        return {'jobId': body['id'], 'status': body.get('status', 'pending'), 'model': model, 'raw': self.last_response}

    def retrieve(self, *, job_id, **_):
        body = self._json('/tasks/' + quote(str(job_id), safe=''))
        if body.get('id') != job_id:
            raise ProviderError('EvoLink 返回了不匹配的任务编号', stop_tool=True)
        self._remember(body)
        result = {'jobId': job_id, 'status': body.get('status', 'pending'), 'raw': self.last_response}
        if body.get('error'):
            key = self.credentials.get(self.provider_key) or ''
            detail = str(body['error'].get('message') or '视频生成失败')
            result['error'] = detail.replace(key, '[REDACTED]') if key else detail
        if body.get('status') == 'completed':
            result.update(content=self._download(body), extension='mp4')
        return result
