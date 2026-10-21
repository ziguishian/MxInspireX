"""Bounded local media operations. Inputs are project asset IDs, never shell code."""
import io
import os
import subprocess
import tempfile
from pathlib import Path
from uuid import uuid4


def source(registry, project_id, asset_id, kinds):
    asset=registry.asset_store.get_asset(project_id=project_id,asset_id=asset_id)
    if not asset or asset['mime'].split('/')[0] not in kinds: raise ValueError('输入资产类型不符或不属于当前项目')
    if not Path(asset['absolutePath']).is_file(): raise ValueError('输入资产文件不存在')
    return asset


def save(registry, project_id, task_id, kind, content, extension, operation, asset_ids, canvas_node_id, state):
    if kind=='image' and canvas_node_id:
        target=next((node for node in registry.canvas_store.load(project_id)['nodes'] if node['id']==canvas_node_id),{})
        if target.get('data',{}).get('assetId') or (target.get('data',{}).get('asset') or {}).get('id'):
            canvas_node_id=None
    asset=registry.asset_store.add_bytes(project_id=project_id,kind=kind,filename=f'{operation}-{uuid4().hex}.{extension}',content=content,
        metadata={'taskId':task_id,'source':'design-agent-tool','executionReceipt':state.get('fingerprint'),'canvasNodeId':canvas_node_id,'operation':operation,'sourceAssetIds':asset_ids})
    node=registry.canvas_store.ensure_asset_node(project_id,asset,task_id=task_id,target_node_id=canvas_node_id,execution_receipt=state.get('fingerprint'))
    return {'status':'succeeded','node':node,'assetId':asset['id'],'asset':asset,'outputKind':kind}


def image_edit(registry, *, project_id, task_id, asset_id, operation, params=None, canvas_node_id=None, **kwargs):
    from PIL import Image
    asset=source(registry,project_id,asset_id,{'image'});params=params or {};state=kwargs.get('_execution_state',{})
    with Image.open(asset['absolutePath']) as original:
        image=original.convert('RGBA')
    if operation=='inpaint':
        defaults=(registry._task_input(project_id,task_id).get('mediaProvider') or {}).get('image') or {}
        provider=params.get('provider') or defaults.get('key')
        same_provider=not params.get('provider') or provider==defaults.get('key')
        model=params.get('model') or (defaults.get('model') if same_provider and defaults.get('manual') is not False else None)
        base=params.get('baseUrl') or (defaults.get('baseUrl') if same_provider else None)
        mask=source(registry,project_id,params.get('maskAssetId'),{'image'})
        with Image.open(mask['absolutePath']) as mask_image:
            if mask_image.size!=image.size or 'A' not in mask_image.getbands(): raise ValueError('遮罩需与原图同尺寸并包含 Alpha 通道')
        return registry.generate_image(project_id=project_id,task_id=task_id,prompt=params.get('prompt',''),source_asset_id=asset_id,
            provider=provider,model=model,canvas_node_id=canvas_node_id,source_asset_ids=kwargs.get('source_asset_ids'),
            params={'maskAssetId':mask['id'],**({'baseUrl':base} if base else {})},reference_analysis=kwargs.get('reference_analysis'),_execution_state=state,
            _reference_snapshot=kwargs.get('_reference_snapshot'),_delivery_binding=kwargs.get('_delivery_binding'))
    if operation=='crop':
        x,y,width,height=[int(params.get(k,0)) for k in ('x','y','width','height')]
        if x<0 or y<0 or width<=0 or height<=0 or x+width>image.width or y+height>image.height: raise ValueError('裁剪区域超出图片范围')
        image=image.crop((x,y,x+width,y+height))
    elif operation in {'resize','extend'}:
        width,height=int(params.get('width',0)),int(params.get('height',0))
        if not 1<=width<=8192 or not 1<=height<=8192: raise ValueError('图像尺寸须为 1–8192 像素')
        if operation=='resize': image=image.resize((width,height),Image.Resampling.LANCZOS)
        else:
            if width<image.width or height<image.height: raise ValueError('扩展画布不能小于原图')
            padded=Image.new('RGBA',(width,height),(0,0,0,0));padded.alpha_composite(image,((width-image.width)//2,(height-image.height)//2));image=padded
    elif operation!='convert': raise ValueError('图像操作支持 crop、resize、extend、convert、inpaint')
    fmt=str(params.get('format','png')).lower()
    if fmt not in {'png','jpeg','webp'}: raise ValueError('输出格式支持 PNG、JPEG、WebP')
    if fmt=='jpeg':
        flat=Image.new('RGB',image.size,'white');flat.paste(image,mask=image.getchannel('A'));image=flat
    result=io.BytesIO();image.save(result,format=fmt.upper())
    return save(registry,project_id,task_id,'image',result.getvalue(),fmt,operation,[asset_id],canvas_node_id,state)


def ffmpeg():
    configured = os.environ.get('AICS_FFMPEG','').strip()
    if configured:
        if not Path(configured).is_file(): raise ValueError('本地媒体组件文件缺失，请在设置中重新安装。')
        return configured
    if os.environ.get('AICS_LITE_RUNTIME') == '1':
        raise ValueError('本地媒体处理组件尚未安装。请打开“设置 → 能力组件”按需安装后重试。')
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def run_media(args, cwd):
    result=subprocess.run([ffmpeg(),'-nostdin','-hide_banner','-loglevel','error','-y',*args],cwd=cwd,capture_output=True,timeout=180)
    if result.returncode: raise ValueError('媒体处理失败：'+result.stderr.decode(errors='replace')[-1000:])


def media_edit(registry, *, project_id, task_id, operation, asset_ids, params=None, canvas_node_id=None, **kwargs):
    if not isinstance(asset_ids,list) or not 1<=len(asset_ids)<=12: raise ValueError('请选择 1–12 个音视频资产')
    assets=[source(registry,project_id,id,{'video','audio'}) for id in asset_ids];params=params or {}
    kind=assets[0]['mime'].split('/')[0]
    if operation=='concat' and any(a['mime'].split('/')[0]!=kind for a in assets): raise ValueError('拼接素材需要同为音频或视频')
    duration=float(params.get('duration',600));start=float(params.get('start',0))
    if not 0<duration<=600 or not 0<=start<=86400: raise ValueError('每次处理最长 600 秒，起点不得为负数')
    with tempfile.TemporaryDirectory(prefix='aics-media-') as temporary:
        root=Path(temporary);extension='mp4' if kind=='video' else 'wav';output=root/f'output.{extension}'
        inputs=['-i',assets[0]['absolutePath']]
        video_codec=['-c:v','libx264','-pix_fmt','yuv420p'] if kind=='video' else []
        audio_codec=['-c:a','aac'] if kind=='video' else ['-c:a','pcm_s16le']
        if operation=='trim': args=['-ss',str(start),*inputs,'-t',str(duration),*video_codec,*audio_codec]
        elif operation=='voiceover':
            if kind!='video' or len(assets)!=2 or not assets[1]['mime'].startswith('audio/'): raise ValueError('配音合成需要视频和音频各一个，音轨将替换为指定配音')
            args=[*inputs,'-i',assets[1]['absolutePath'],'-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','aac','-shortest','-t',str(duration)]
        elif operation=='subtitles':
            if kind!='video': raise ValueError('字幕需选择视频')
            cues=params.get('cues',[])
            if not isinstance(cues,list) or not 1<=len(cues)<=500: raise ValueError('请提供 1–500 条字幕')
            def timestamp(seconds):
                ms=int(float(seconds)*1000)
                if not 0<=ms<=600000: raise ValueError('字幕时间超出范围')
                return f'{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02},{ms%1000:03}'
            lines=[]
            for index,cue in enumerate(cues):
                if float(cue['end'])<=float(cue['start']): raise ValueError('字幕结束时间必须晚于开始时间')
                lines.append(f"{index+1}\n{timestamp(cue['start'])} --> {timestamp(cue['end'])}\n{str(cue['text'])[:500]}\n")
            (root/'subtitles.srt').write_text('\n'.join(lines),encoding='utf-8')
            # Portable subtitle track; no platform font or libass dependency.
            args=[*inputs,'-i','subtitles.srt','-map','0:v:0','-map','0:a?','-map','1:0','-c:v','copy','-c:a','copy','-c:s','mov_text','-t',str(duration)]
        elif operation=='concat':
            # Normalize every segment before concat to preserve timing/audio
            # across different resolutions and audio-less video clips.
            names=[]
            for index,asset in enumerate(assets):
                name=f'part{index}.{extension}';names.append(name)
                if kind=='video':
                    inspect=subprocess.run([ffmpeg(),'-hide_banner','-i',asset['absolutePath']],capture_output=True,timeout=15)
                    has_audio=b'Audio:' in inspect.stderr
                    command=['-i',asset['absolutePath']]
                    if not has_audio: command+=['-f','lavfi','-i','anullsrc=r=48000:cl=stereo']
                    command+=['-map','0:v:0','-map','0:a:0' if has_audio else '1:a:0','-vf','scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,fps=24',*video_codec,'-c:a','aac','-ar','48000','-ac','2','-shortest','-t',str(duration),name]
                else: command=['-i',asset['absolutePath'],'-ar','48000','-ac','2','-t',str(duration),name]
                run_media(command,root)
            (root/'parts.txt').write_text('\n'.join(f"file '{name}'" for name in names))
            args=['-f','concat','-safe','1','-i','parts.txt','-c','copy','-t',str(duration)]
        else: raise ValueError('媒体操作支持 trim、concat、voiceover、subtitles')
        run_media([*args,str(output)],root)
        content=output.read_bytes()
    return save(registry,project_id,task_id,kind,content,extension,operation,asset_ids,canvas_node_id,kwargs.get('_execution_state',{}))
