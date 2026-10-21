"""Resolve the inputs chosen by the Agent from saved project artifacts."""
import hashlib
import json
from pathlib import Path
from .asset_identity import selected_asset_id


def planned_inputs(context, item_ids):
    plan = context.get('designPlan') or {}
    refs = []
    for item in plan.get('deliverables', []):
        if item['id'] not in item_ids: continue
        refs.extend(item.get('inputs', []))
        # Preserve explicit dependencies in existing accepted plans; grouping
        # alone never adds an input or execution edge.
        if not item.get('inputs'):
            for group in plan.get('visualSeries', []):
                if item['id'] in group['memberIds'] and group.get('masterId') in item.get('dependsOn', []):
                    refs.append({'source':'deliverable','id':group['masterId'],'role':'layout','purpose':'复用已声明的前置版式'})
    # Also normalize plans saved by older workers. Besides asset:<id>, some
    # plans copied a selected semantic memory key such as "brand-logo".
    refs = [{**ref, 'id': selected_asset_id(ref['id'], context)} if ref['source'] == 'asset' else ref for ref in refs]
    return list({(ref['source'],ref['id'],ref.get('role','reference')):ref for ref in refs}.values())


def bind_generation_inputs(context, binding, args, nodes, assets, project_id, *, deferred_ids=()):
    refs = planned_inputs(context, binding.get('itemIds', []))
    if not refs: return args
    args = dict(args)
    snapshot = dict(args.get('_reference_snapshot') or {})
    input_records, resolved_assets = [], []
    scope = (context.get('designPlan') or {}).get('scopeId')
    for ref in sorted(refs, key=lambda r:r.get('role') != 'layout'):
        if ref['source'] == 'deliverable' and ref['id'] in deferred_ids:
            continue
        selected = []
        if ref['source'] == 'asset':
            asset_ids = [ref['id']]
        else:
            selected = [node for node in nodes if node.get('data',{}).get('deliveryBinding',{}).get('scopeId') == scope
                        and ref['id'] in node['data']['deliveryBinding'].get('itemIds',[])]
            if not selected or any(n['data'].get('generating') or n['data'].get('error') for n in selected):
                raise ValueError('所需前置产物尚未完成：' + ref['id'])
            asset_ids = []
            for node in selected:
                data = node['data']
                if data.get('kind') in {'text','html'}:
                    value = data.get('text') or data.get('html') or data.get('summary') or ''
                    if not value or len(value) > 20000:
                        raise ValueError('前置文本为空或过长，请先整理本项实际需要的内容：' + ref['id'])
                    # The Agent selects exact on-image copy in prompt. Do not
                    # append entire strategy documents, Markdown or HTML here.
                elif data.get('assetId'): asset_ids.append(data['assetId'])
                else: raise ValueError('前置产物没有可用内容：' + ref['id'])
        if ref.get('role') in {'layout', 'identity'} and (len(asset_ids) != 1 or len(selected) > 1):
            raise ValueError('排版或产品身份输入必须对应一张明确的图片：' + ref['id'])
        for id in asset_ids:
            asset = assets.get_asset(project_id=project_id, asset_id=id)
            if not asset or asset['kind'] != 'image' or asset['mime'] == 'image/svg+xml':
                raise ValueError('图像输入必须是可用图片；其他媒体请先提取本项需要的画面或文字：' + ref['id'])
            path = Path(asset['absolutePath'])
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != asset['sha256']:
                raise ValueError('所需输入文件缺失或已变化：' + ref['id'])
            resolved_assets.append({'assetId':id,'sha256':asset['sha256'],'role':'layout_master' if ref.get('role')=='layout' else 'input','purpose':ref['purpose']})
        input_records.append({**ref,'assetIds':asset_ids,'nodeIds':[n['id'] for n in selected]})
    from .design_tools import image_reference_ids
    sources = list(dict.fromkeys([*(r['assetId'] for r in resolved_assets), *image_reference_ids(args.get('source_asset_id'),args.get('source_asset_ids'))]))
    args.update(source_asset_id=sources[0] if sources else None, source_asset_ids=sources)
    original = {r['assetId']:r for r in snapshot.get('references',[])}
    for ref in resolved_assets:
        if ref['assetId'] not in original or ref['role']=='layout_master': original[ref['assetId']] = ref
    snapshot.update(references=[original[id] for id in sources],inputBindings=input_records)
    snapshot.pop('id',None)
    snapshot['id'] = hashlib.sha256(json.dumps(snapshot,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    args['_reference_snapshot'] = snapshot
    return args
