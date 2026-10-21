import json
from types import SimpleNamespace

import pytest

from app.assets import AssetStore
from app.canvas import CanvasStore
from app.design_tools import DesignToolRegistry, DesignToolError
from app.model_catalog import ModelCatalog
from app.model_config import ModelSettings
from app.skills import SkillService, SkillError
from app.svg_policy import derive_policy, ensure_task_policy, task_policy
from app.task_runtime import TaskRuntime
from test_conversation_context import workspace, add_turn
from test_skill_sdk import run_worker

SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100"><rect width="200" height="100" fill="green"/></svg>'


@pytest.mark.parametrize('message,allowed', [
    ('做一套 logo 样机', False), ('做笔记本封面效果', False), ('画一个矩形', False),
    ('生成 IP 三视图', False), ('你好', False), ('SVG 的优劣势是什么？', False),
    ('输出 SVG', False), ('做一份可打印的矢量文件', False), ('需要可打印的制作文件', False),
    ('导出印刷制作文件', False), ('Draw an SVG logo', False), ('export print-ready files', False),
    ('不要用 SVG 做样机', False), ('不需要矢量，只做效果图', False),
    ('Please do not use SVG', False), ('#skill:svg-maker 做效果图', False),
])
def test_explicit_scope(message, allowed):
    assert derive_policy('explicit', message)['allowed'] is False


def enqueue(store, brief, **inputs):
    runtime = TaskRuntime(store)
    runtime._start_worker = lambda *args: False
    task = runtime.enqueue(project_id='one', agent_key='design', workflow_step='design', brief=brief, input_data=inputs, run_async=True)
    return task['id']


def test_settings_default_snapshot_forgery_and_workspace_isolation(workspace, tmp_path):
    catalog = ModelCatalog(workspace)
    assert catalog.settings().svgDrawing == 'off'
    denied = enqueue(workspace, '做样机', svgPolicy={'mode':'auto','allowed':True}, svgDrawing='auto')
    assert not ensure_task_policy(workspace, denied)['allowed']
    catalog.save_settings(ModelSettings(svgDrawing='auto'))
    assert ModelCatalog(workspace).settings().svgDrawing == 'off'
    assert not ensure_task_policy(workspace, denied)['allowed']
    allowed = enqueue(workspace, '做样机')
    assert not ensure_task_policy(workspace, allowed)['allowed']
    catalog.save_settings(ModelSettings(svgDrawing='off'))
    assert not ensure_task_policy(workspace, allowed)['allowed']
    assert not ensure_task_policy(workspace, enqueue(workspace, '请输出 SVG'))['allowed']
    from app.storage import ProjectStore
    assert ModelCatalog(ProjectStore(str(tmp_path/'other'))).settings().svgDrawing == 'off'


def test_only_validated_continuation_inherits_user_request(workspace):
    original = enqueue(workspace, '输出 SVG')
    with workspace._connect() as db:
        db.execute("UPDATE tasks SET status='succeeded',output_json=? WHERE id=?", (json.dumps({'structured_data':{'clarification':{'questions':[{'id':'size','question':'尺寸？'}]}}}), original))
    continued = enqueue(workspace, '宽度 100mm', clarificationTaskId=original, clarificationAnswers=[{'questionId':'size','value':'100mm','skipped':False}])
    assert not ensure_task_policy(workspace, continued)['allowed']
    revoked = enqueue(workspace, '不要 SVG 了，只出效果图', clarificationTaskId=original)
    assert not ensure_task_policy(workspace, revoked)['allowed']
    assert not ensure_task_policy(workspace, enqueue(workspace, '做效果图', planAccepted=True))['allowed']


@pytest.mark.parametrize('name,args', [
    ('canvas_create_svg', {'svg':SVG}),
    ('canvas_create_html', {'html':'<html>'+SVG+'</html>'}),
    ('canvas_create_html', {'html':'<img src="data:image/svg+xml;base64,PHN2Zy8+">'}),
    ('canvas_create_html', {'html':'<script>document.createElementNS("http://www.w3.org/2000/svg","svg")</script>'}),
    ('canvas_create_html', {'html':'<img src="data:image%2Fsvg%2Bxml,%3Csvg%2F%3E">'}),
    ('canvas_create_html', {'html':'&lt;svg&gt;&lt;/svg&gt;'}),
    ('canvas_create_text', {'text':SVG}),
    ('canvas_update_node', {'node_id':'missing','patch':{'data':{'html':SVG}}}),
    ('generate_image', {'prompt':'封面','params':{'output_format':'svg'}}),
    ('image_edit', {'asset_id':'missing','operation':'convert','params':{'format':'svg'}}),
])
def test_gateway_blocks_new_svg_before_writes(workspace, name, args):
    add_turn(workspace, 'denied', '做一套样机', status='running')
    tools = DesignToolRegistry(workspace, asset_store=AssetStore(workspace))
    with pytest.raises(DesignToolError, match='全局禁用'):
        tools.execute(project_id='one',task_id='denied',name=name,arguments=args)
    assert tools.canvas_store.load('one')['nodes'] == []
    assert tools.asset_store.list_assets('one') == []


def test_svg_generator_is_not_registered_or_implemented():
    assert 'canvas_create_svg' not in DesignToolRegistry.TOOL_NAMES
    assert not hasattr(DesignToolRegistry, 'canvas_create_svg')


@pytest.mark.parametrize('content', [SVG.encode(), SVG.encode('utf-16'), SVG.encode('utf-32'), ('<!--'+'x'*6000+'-->'+SVG).encode()])
def test_returned_svg_cannot_hide_in_encoding_or_long_preamble(content):
    from app.image_output import reject_svg_output
    with pytest.raises(ValueError, match='图像服务返回了 SVG'):
        reject_svg_output(content)


def test_existing_svg_stays_readable_but_cannot_be_reused_as_new_delivery(workspace):
    assets = AssetStore(workspace)
    asset = assets.add_bytes(project_id='one',kind='image',filename='old.svg',content=SVG.encode(),metadata={})
    add_turn(workspace, 'denied', '排版说明', status='running')
    tools = DesignToolRegistry(workspace,asset_store=assets)
    call = lambda name, **args: tools.execute(project_id='one',task_id='denied',name=name,arguments=args)
    assert assets.get_asset(project_id='one', asset_id=asset['id'])['id'] == asset['id']
    with pytest.raises(DesignToolError, match='全局禁用'):
        call('canvas_create_media',asset_id=asset['id'])
    old = tools.canvas_store.ensure_asset_node('one', asset)
    with pytest.raises((ValueError, DesignToolError), match='全局禁用'):
        call('export_deliverable',format='zip',node_ids=[old['id']])
    assert call('canvas_create_html',html='<html><body><h1>清晰中文</h1></body></html>')['status'] == 'succeeded'
    assert call('canvas_create_text',text='SVG 是一种矢量文件格式')['node']


def test_skill_dependency_cannot_override_policy_and_builtin_defaults_load(workspace):
    from app.bundled_skills import install_bundled_skills
    service = SkillService(workspace)
    with pytest.raises(SkillError, match='工具依赖不存在'):
        service.write({'name':'vector-only','description':'矢量','instructions':'请使用 SVG','required_tools':['canvas_create_svg']})
    hard = service.write({'name':'legacy-vector','description':'旧矢量技能','instructions':'旧 SVG 流程'})
    with workspace._connect() as db:
        row = db.execute('SELECT definition_json FROM skill_versions WHERE skill_id=?', (hard['id'],)).fetchone()
        definition = json.loads(row[0]); definition['requiredTools'] = ['canvas_create_svg']
        db.execute('UPDATE skill_versions SET definition_json=? WHERE skill_id=?', (json.dumps(definition), hard['id']))
    add_turn(workspace, 'denied', '做效果图', status='running')
    with pytest.raises(SkillError, match='缺少工具依赖'):
        service.bind('one','denied',hard['id'],active=True,operation_id='denied')
    assert not service.bindings('denied')
    install_bundled_skills(service)
    for name in ['notebook-print-design','scenic-wayfinding-design']:
        skill = service.list(query=name)['skills'][0]
        service.bind('one','denied',skill['id'],active=True,operation_id=name)
    assert len(service.bindings('denied')) == 2


def test_image_and_text_provider_cannot_return_svg_fallback(workspace):
    add_turn(workspace,'denied','做效果图',status='running')
    calls = []
    def generate(**kwargs):
        calls.append(kwargs)
        return SVG.encode()
    providers = SimpleNamespace(image=lambda *a,**kw:SimpleNamespace(generate=generate))
    tools = DesignToolRegistry(workspace,asset_store=AssetStore(workspace),provider_registry=providers)
    with pytest.raises(DesignToolError,match='图像服务返回了 SVG') as failed:
        tools.execute(project_id='one',task_id='denied',name='generate_image',arguments={'prompt':'封面效果图','provider':'local-placeholder'})
    assert failed.value.stop_tool and failed.value.response_received
    assert calls[0]['output_format'] == 'png'
    assert tools.asset_store.list_assets('one') == []
    restored = DesignToolRegistry(workspace,asset_store=AssetStore(workspace),provider_registry=providers)
    state = restored.executions.load('denied')
    assert state['blockedTools']['generate_image']['errorCode'] == 'image_output_format'
    with workspace._connect() as db:
        receipt = db.execute("SELECT status,output FROM tool_receipts WHERE task_id='denied' AND name='generate_image'").fetchone()
    assert receipt['status'] == 'completed' and json.loads(receipt['output'])['status'] == 'failed'
    for prompt in ['封面效果图', '改写提示词重试']:
        with pytest.raises(DesignToolError,match='图像服务返回了 SVG'):
            restored.execute(project_id='one',task_id='denied',name='generate_image',arguments={'prompt':prompt,'provider':'local-placeholder'})
    assert len(calls) == 1
    assert len(tools.canvas_store.load('one')['nodes']) == 1
    assert restored.execute(project_id='one',task_id='denied',name='canvas_create_text',arguments={'text':'保留制作说明'})['node']
    # Also covers generate_text's internal save method.
    with pytest.raises(DesignToolError,match='全局禁用'):
        tools.canvas_create_text(project_id='one',task_id='denied',text=SVG)


def test_png_metadata_containing_svg_does_not_reject_real_pixels(workspace):
    from io import BytesIO
    from PIL import Image, PngImagePlugin
    output = BytesIO()
    metadata = PngImagePlugin.PngInfo(); metadata.add_text('description', SVG)
    Image.new('RGB', (16,16), 'blue').save(output, format='PNG', pnginfo=metadata)
    content = output.getvalue()
    assert b'<svg' in content[:4096]
    add_turn(workspace,'png','做效果图',status='running')
    providers = SimpleNamespace(image=lambda *a,**kw:SimpleNamespace(generate=lambda **kw:content))
    tools = DesignToolRegistry(workspace,asset_store=AssetStore(workspace),provider_registry=providers)
    result = tools.execute(project_id='one',task_id='png',name='generate_image',arguments={'prompt':'封面效果图'})
    assert result['status'] == 'succeeded' and result['asset']['mime'] == 'image/png'


def test_plan_cannot_promise_unavailable_vector_but_can_record_blocker(workspace):
    from app.design_planning import save_design_plan
    add_turn(workspace,'denied','做封面效果',status='running')
    plan={'goal':'封面','research':'使用本地资料','deliverables':[{'id':'cover','title':'封面','kind':'image','representation':'vector','acceptance':'可编辑源稿'}]}
    with pytest.raises(ValueError,match='不能承诺'):
        save_design_plan(workspace,'one','denied',plan)
    plan['deliverables'][0]['blockingFields']=['svg_permission']
    assert save_design_plan(workspace,'one','denied',plan)['status'] == 'ready'


@pytest.mark.parametrize('api',['responses','chat_completions'])
@pytest.mark.parametrize('setting,brief,allowed',[
    ('explicit','做 logo 样机',False), ('explicit','输出 SVG 文件',True),
    ('off','输出 SVG 文件',False), ('auto','画一个标志',True),
])
def test_real_sdk_tool_filter_and_batch_gate(workspace,api,setting,brief,allowed):
    ModelCatalog(workspace).save_settings(ModelSettings(svgDrawing=setting))
    add_turn(workspace,'policy',brief,status='running')
    result,events=run_worker(workspace,'policy','one','svg_legacy_snapshot',api)
    assert result.returncode == 0, result.stderr+result.stdout[-4500:]
    assert any(e['type']=='result' for e in events)
    nodes=CanvasStore(workspace).load('one')['nodes']
    assert len(nodes)==1
    assert 'MUST_NOT_SAVE' not in json.dumps(nodes)


def test_saved_true_permission_is_revoked_on_resume(workspace):
    add_turn(workspace, 'legacy', '输出 SVG', status='running', extra={'svgPolicy': {'mode':'auto','allowed':True}})
    assert ensure_task_policy(workspace, 'legacy') == {'mode':'off','allowed':False,'reason':'globally_disabled'}
    tools = DesignToolRegistry(workspace, asset_store=AssetStore(workspace))
    with pytest.raises(DesignToolError, match='全局禁用'):
        tools.execute(project_id='one',task_id='legacy',name='canvas_create_svg',arguments={'svg':SVG})


def test_old_svg_cannot_be_rebound_by_node_patch_or_automatic_delivery_reuse(workspace):
    assets = AssetStore(workspace)
    asset = assets.add_bytes(project_id='one',kind='image',filename='old.svg',content=SVG.encode())
    add_turn(workspace,'legacy','继续做封面',status='running',extra={'designPlan':{'ready':True,'scopeId':'legacy','deliverables':[{'id':'cover','title':'封面','kind':'image','representation':'raster','acceptance':'实际图像'}]}})
    tools = DesignToolRegistry(workspace,asset_store=assets)
    old = tools.canvas_store.ensure_asset_node('one',asset,task_id='legacy',data={'deliveryBinding':{'scopeId':'legacy','itemIds':['cover']}})
    with pytest.raises(DesignToolError,match='全局禁用'):
        tools.execute(project_id='one',task_id='legacy',name='canvas_update_node',arguments={'node_id':old['id'],'patch':{'data':{'assetId':asset['id']}}})
    result = tools.execute(project_id='one',task_id='legacy',name='generate_image',arguments={'prompt':'封面','deliverable_ids':['cover']})
    assert result['status'] == 'representation_required'
    assert not result.get('reused')
    assert len(assets.list_assets('one')) == 1


@pytest.mark.parametrize('name', ['canvas_create_media', 'export_deliverable', 'generate_image'])
def test_completed_legacy_receipts_do_not_republish_svg(workspace, name):
    add_turn(workspace,'legacy','继续',status='running')
    assets = AssetStore(workspace)
    asset = assets.add_bytes(project_id='one',kind='image',filename='old.svg',content=SVG.encode())
    tools = DesignToolRegistry(workspace,asset_store=assets)
    node = tools.canvas_store.ensure_asset_node('one',asset)
    args = {'asset_id':asset['id']} if name == 'canvas_create_media' else {'format':'zip','node_ids':[node['id']]} if name == 'export_deliverable' else {'prompt':'旧效果图'}
    fingerprint, _ = tools.executions.claim('legacy', name, args)
    tools.executions.complete('legacy', fingerprint, {'status':'succeeded','asset':asset,'node':node})
    with pytest.raises(DesignToolError,match='全局禁用'):
        tools.execute(project_id='one',task_id='legacy',name=name,arguments=args)
    assert len(assets.list_assets('one')) == 1
