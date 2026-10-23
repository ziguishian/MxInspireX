"""Short composer dictation, without creating a project or an Agent task."""
import json
import re
import urllib.request
import urllib.error
from uuid import uuid4
from fastapi import APIRouter, File, HTTPException, Request, UploadFile

router = APIRouter(tags=['voice'])


def configuration(state):
    preference = state.model_catalog.settings().preferredTextProvider
    key = preference.key
    if not key:
        raise HTTPException(422, '请先在「模型与连接」选择支持转写的服务商。')
    adapter = state.providers.text(key, base_url=preference.baseUrl or None)
    base = adapter.base_url
    records = state.model_catalog.get(key, base).get('modelCatalog', [])
    model = next((item['id'] for item in records if re.search(r'transcrib|whisper', item['id'], re.I)), None)
    if not model:
        raise HTTPException(422, '当前服务商未配置转写模型，请在「模型与连接」同步支持语音转写的模型后再试。')
    secret = state.providers.credentials.get(key)
    if not secret:
        raise HTTPException(422, '语音转写服务缺少 API Key，请先在「模型与连接」配置。')
    return key, base, model, secret


@router.get('/api/voice-input')
def voice_configuration(request: Request):
    key, _, model, _ = configuration(request.app.state)
    return {'provider': key, 'model': model}


@router.post('/api/voice-input')
def voice_input(request: Request, file: UploadFile = File(...)):
    state = request.app.state
    key, base, model, secret = configuration(state)
    mime = (file.content_type or '').split(';')[0]
    extensions = {'audio/webm': 'webm', 'audio/mp4': 'mp4', 'audio/ogg': 'ogg', 'audio/wav': 'wav'}
    if mime not in extensions:
        raise HTTPException(422, '不支持的录音格式')
    content = file.file.read(10 * 1024 * 1024 + 1)
    if not content or len(content) > 10 * 1024 * 1024:
        raise HTTPException(422, '录音为空或超过 10 MB，请缩短后重新录制')
    boundary = uuid4().hex
    payload = (f'--{boundary}\r\nContent-Disposition: form-data; name="model"\r\n\r\n{model}\r\n'
               f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="dictation.{extensions[mime]}"\r\nContent-Type: {mime}\r\n\r\n').encode() + content + f'\r\n--{boundary}--\r\n'.encode()
    outbound = urllib.request.Request(base.rstrip('/') + '/audio/transcriptions', data=payload,
        headers={'Authorization': f'Bearer {secret}', 'Content-Type': f'multipart/form-data; boundary={boundary}'}, method='POST')
    try:
        with urllib.request.urlopen(outbound, timeout=120) as response:
            result = json.loads(response.read())
    except urllib.error.HTTPError as error:
        if error.code >= 500:
            state.billing.record(provider=key, base_url=base, model=model, kind='audio', units={'requests': 1}, completed=False)
        raise HTTPException(502, f'语音转写服务返回错误（{error.code}），未自动重试。') from error
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as error:
        state.billing.record(provider=key, base_url=base, model=model, kind='audio', units={'requests': 1}, completed=False)
        raise HTTPException(502, '语音转写连接中断，费用待核对，未自动重试。') from error
    if not isinstance(result, dict):
        state.billing.record(provider=key, base_url=base, model=model, kind='audio', units={'requests': 1}, completed=False)
        raise HTTPException(502, '语音转写返回格式无效，未自动重试。')
    state.billing.record(provider=key, base_url=base, model=model, kind='audio', usage=result.get('usage') or {}, units={'requests': 1, 'seconds': result.get('duration')})
    text = str(result.get('text') or '').strip()
    if not text:
        raise HTTPException(422, '未识别到文字，请检查麦克风后重新录制。')
    return {'text': text}
