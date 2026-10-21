"""Transcribe a project recording through an API-confirmed transcription model."""
import json
import re
import urllib.request
import urllib.error
import subprocess
from pathlib import Path
from uuid import uuid4
from .media_editing import source, ffmpeg
from .providers.http import ProviderError, _http_error_detail


def transcribe_audio(registry, *, project_id, task_id, asset_id, model=None, provider=None, **kwargs):
    current=registry._task_input(project_id,task_id).get('textProvider') or {}
    key=provider or current.get('key','openai-compatible')
    adapter=registry.provider_registry.text(key,base_url=current.get('baseUrl') if key==current.get('key') else None,model=model)
    base=adapter.base_url;catalog=registry.provider_registry.catalog
    records=catalog.get(key,base).get('modelCatalog',[])
    selected=model or next((m['id'] for m in records if re.search('transcrib|whisper',m['id'],re.I)),None)
    resolved=catalog.resolve_id(key,base,selected or '')
    if not resolved or not re.search('transcrib|whisper',resolved,re.I): raise ValueError('请在设置同步支持 /audio/transcriptions 的转写模型，或指定已确认的转写模型')
    asset=source(registry,project_id,asset_id,{'audio','video'})
    path=Path(asset['absolutePath'])
    if path.stat().st_size>25*1024*1024: raise ValueError('转写文件超过 25 MB，请先裁剪')
    probe=subprocess.run([ffmpeg(),'-hide_banner','-i',str(path)],capture_output=True,timeout=15)
    match=re.search(rb'Duration: (\d+):(\d+):([\d.]+)',probe.stderr)
    duration=int(match[1])*3600+int(match[2])*60+float(match[3]) if match else None
    secret=registry.provider_registry.credentials.get(key)
    if not secret: raise ProviderError('转写服务缺少 API Key',status_code=401)
    from .budget import BudgetService
    budget=BudgetService(registry.store,catalog)
    reservation=budget.reserve(task_id,provider=key,base_url=base,model=resolved,kind='audio',units={'requests':1,'seconds':duration})
    boundary=uuid4().hex
    data=(f'--{boundary}\r\nContent-Disposition: form-data; name="model"\r\n\r\n{resolved}\r\n--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="recording{path.suffix}"\r\nContent-Type: {asset["mime"]}\r\n\r\n').encode()+path.read_bytes()+f'\r\n--{boundary}--\r\n'.encode()
    request=urllib.request.Request(base.rstrip('/')+'/audio/transcriptions',data=data,headers={'Authorization':f'Bearer {secret}','Content-Type':f'multipart/form-data; boundary={boundary}'},method='POST')
    kwargs.get('_execution_state',{})['submitted']=True
    try:
        with urllib.request.urlopen(request,timeout=180) as response: result=json.loads(response.read())
    except urllib.error.HTTPError as error:
        if reservation and error.code in {400,401,403,404,413,422,429}: budget.settle(task_id,reservation['reservationId'],0)
        raise ProviderError(f'转写失败（{error.code}）：'+_http_error_detail(error).replace(secret,'[REDACTED]'),status_code=error.code) from error
    except (urllib.error.URLError,TimeoutError,ValueError) as error:
        raise ProviderError('转写连接中断或返回内容无效；请先核对原请求') from error
    text=str(result.get('text') or '').strip()
    if registry.provider_registry.billing:
        ledger=registry.provider_registry.billing.record(provider=key,base_url=base,model=resolved,kind='audio',usage=result.get('usage') or {},units={'requests':1,'seconds':result.get('duration') or duration},project_id=project_id,task_id=task_id)
        if reservation: budget.settle(task_id,reservation['reservationId'],ledger.get('points'))
    if not text: raise ValueError('转写未返回文字，不将空内容视为成功')
    output=registry.canvas_create_text(project_id=project_id,task_id=task_id,text=text,title='录音转写',**kwargs)
    return {**output,'status':'succeeded','text':text,'sourceAssetId':asset_id,'model':resolved,'segments':result.get('segments',[]),'notice':'转写是模型识别结果；没有时间戳时不自动猜测字幕时间'}
