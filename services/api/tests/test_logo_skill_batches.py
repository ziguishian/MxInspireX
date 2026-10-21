"""Exercise the Skill's cumulative batch workflow with real local tools."""
import copy
import io
import json

from PIL import Image

from app.bundled_skills import install_bundled_skills
from app.skills import SkillService
from test_design_execution import env, finish


def test_logo_batches_keep_brand_references_finish_each_batch_and_reuse_outputs(env):
    store, project, _, tools, enqueue, call = env
    service = SkillService(store)
    skill = next(s for s in install_bundled_skills(service) if s['name'] == 'logo-mockup-suite')
    stream = io.BytesIO()
    Image.new('RGB', (24, 24), '#184778').save(stream, format='PNG')
    logo = tools.asset_store.add_bytes(project_id=project, kind='image', filename='designer-logo.png', content=stream.getvalue())
    first = enqueue(f'@asset:{logo["id"]} 用已有 Logo 做多场景图片延展，分批交付。行业：咖啡；标准色 #184778。',
                    referencedAssets=[{'id': logo['id'], 'projectId': project}])
    service.bind(project, first, skill['id'], active=True, operation_id='load-logo-batches')
    assert call(first, 'design_state', decisions=[
        {'field': 'industry', 'value': '咖啡', 'status': 'confirmed', 'quote': '行业：咖啡'},
        {'field': 'primary_color', 'value': '#184778', 'status': 'confirmed', 'quote': '标准色 #184778'},
    ])['status'] == 'recorded'
    batches = [
        ['辅助纹样', '咖啡杯', '杯套', '外带袋', '封口贴', '外带场景'],
        ['菜单', '门头', '服务卡', '品牌头像', '主页封面', '上新宣传图'],
        ['礼盒', '贺卡', '包装纸', '礼品袋', '活动胸牌', '活动展架'],
    ]
    value = {'goal': '咖啡品牌的当前批次及累计图片交付', 'preserve': [f'原 Logo asset:{logo["id"]}', '行业：咖啡；标准色 #184778'],
             'deliverables': [], 'coverage': [], 'deferred': [], 'openQuestions': [], 'research': '采用用户品牌资料'}
    original_nodes = {}
    for batch_index, titles in enumerate(batches):
        current = first if batch_index == 0 else enqueue('继续')
        if batch_index:
            context = tools._task_input(project, current)
            assert context['planAccepted'] and context['planBaseline']['scopeId'] == first
            assert context['designState']['decisions']['industry']['value'] == '咖啡'
            assert context['designState']['decisions']['primary_color']['value'] == '#184778'
            assert context['referencedAssets'] == [{'id': logo['id'], 'projectId': project}]
            assert service.bindings(current)[0]['contentHash'] == skill['contentHash']
        new_items = [{'id': f'B{batch_index+1}-{index+1:02}', 'title': title, 'kind': 'image',
                      'representation': 'raster', 'acceptance': '沿用原 Logo、准确字标与标准色',
                      'dependsOn': [], 'blockingFields': []} for index, title in enumerate(titles)]
        value['deliverables'].extend(new_items)
        value['deferred'] = [f'下一批建议 B{i+1}：' + '、'.join(names) for i, names in enumerate(batches) if i > batch_index]
        saved = call(current, 'design_plan', plan=copy.deepcopy(value))
        assert saved['status'] == 'ready', saved
        assert saved['plan']['scopeId'] == first
        before = call(current, 'delivery_verify')
        assert {d['id'] for d in before['deliverables'] if d['status'] == 'pending'} == {d['id'] for d in new_items}
        for item in new_items:
            result = call(current, 'generate_image', prompt=f"{item['id']} {item['title']}，沿用原 Logo，咖啡行业，标准色 #184778",
                          provider='local-placeholder', source_asset_id=logo['id'], output_mode='create', deliverable_ids=[item['id']])
            original_nodes[item['id']] = result['node']['id']
        report = call(current, 'delivery_verify')
        assert report['passed'] and not report['issues']
        assert len(report['deliverables']) == (batch_index + 1) * 6
        assert all(d['nodeIds'] == [original_nodes[d['id']]] for d in report['deliverables'])
        replay = call(current, 'generate_image', prompt='再次尝试已经完成的第一项', provider='local-placeholder',
                      source_asset_id=logo['id'], output_mode='create', deliverable_ids=['B1-01'])
        assert replay['reused'] and replay['node']['id'] == original_nodes['B1-01']
        assert len(tools.asset_store.list_assets(project)) == 1 + (batch_index + 1) * 6
        finish(store, current, {'designPlan': saved['plan'], 'delivery': report,
                               'answer': f'本批完成 6 项，累计 {(batch_index + 1) * 6}/18 项。' + ('回复继续进入下一批。' if batch_index < 2 else '整套完成。')})
    assert len(original_nodes) == 18
    with store._connect() as db:
        inputs = json.loads(db.execute('SELECT input_json FROM tasks WHERE id=?', (current,)).fetchone()[0])
    assert inputs['designPlan']['deferred'] == []
