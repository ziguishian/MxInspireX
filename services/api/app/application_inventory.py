"""Render application status from real artifacts without a model review."""
import re


def inventory_intro(text, items):
    """Tolerate models repeating the structured list in their text argument.

    Remove only recognized status headings and item bullets. Keep scope,
    production caveats and any unmatched material; raw text remains in metadata.
    """
    titles = {item['title'] for item in items}
    kept = []
    for line in str(text).splitlines():
        plain = re.sub(r'[*_`]', '', line).strip()
        if re.fullmatch(r'#{1,6}\s*(?:本轮已交付|本轮已生成|建议后续制作|按需选配)\s*[:：]?', plain):
            continue
        bullet = re.match(r'^(?:[-+•]|\d+[.)、])\s*(.+?)(?:[：:]|$)', plain)
        if bullet and bullet[1].strip() in titles:
            continue
        kept.append(line)
    return re.sub(r'\n{3,}', '\n\n', '\n'.join(kept)).strip()


def inventory_required(context, binding):
    ids = set((binding or {}).get('itemIds', []))
    return any(item['id'] in ids and item['kind'] == 'text'
               and re.search(r'应用.*清单|application inventory', item.get('title', ''), re.I)
               for item in (context.get('designPlan') or {}).get('deliverables', []))


def prepare_inventory(items, intro, context, binding):
    if items is None:
        if inventory_required(context, binding):
            raise ValueError('应用清单须提供 application_items（title、detail、priority=recommended/optional，可关联 deliverable_id）；text 仅写范围说明。完成状态由实际产物生成，不需要另调模型。')
        return None
    if not isinstance(items, list) or not 1 <= len(items) <= 80:
        raise ValueError('application_items 必须包含 1–80 个应用项')
    plan_ids = {item['id'] for item in (context.get('designPlan') or {}).get('deliverables', [])}
    normalized = []
    for item in items:
        if not isinstance(item, dict) or not str(item.get('title') or '').strip() or item.get('priority') not in {'recommended', 'optional'}:
            raise ValueError('每个应用项须有 title 和 priority=recommended/optional')
        if item.get('deliverable_id') and item['deliverable_id'] not in plan_ids:
            raise ValueError('应用项只能关联已存在的交付 ID，不能自行声明完成')
        value = {key: str(item.get(key) or '').strip() for key in ('title', 'detail', 'priority', 'deliverable_id')}
        value['detail'] = re.sub(r'^(?:本轮已交付|本轮已生成|已完成|建议后续制作|按需选配)\s*[：:]\s*', '', value['detail'])
        normalized.append(value)
    return {'version': 1, 'intro': inventory_intro(intro, normalized), 'sourceText': str(intro), 'items': normalized}


def render_inventory(inventory, report, node_id=None):
    # "ready" proves the file/content exists, not that it passed visual review.
    artifacts = [a for a in report.get('artifacts', []) if a.get('ready')]
    ready_nodes = {a['nodeId'] for a in artifacts}
    completed = {item['id'] for item in report.get('deliverables', [])
                 if item.get('nodeIds') and set(item['nodeIds']).issubset(ready_nodes)}
    sections = {key: [] for key in ('delivered', 'recommended', 'optional')}
    for item in inventory['items']:
        status = 'delivered' if item.get('deliverable_id') in completed else item['priority']
        sections[status].append(f"- {item['title']}" + (f"：{item['detail']}" if item['detail'] else ''))
    lines = [inventory['intro'], '', '## 本轮已交付', '',
             '以下产物已保存到画布。']
    represented = {item.get('deliverable_id') for item in inventory['items'] if item.get('deliverable_id') in completed}
    represented_nodes = {nid for item in report.get('deliverables', []) if item['id'] in represented for nid in item.get('nodeIds', [])}
    titles = {nid: item.get('title') for item in report.get('deliverables', []) for nid in item.get('nodeIds', [])}
    lines += [f"- 已生成：{titles.get(a['nodeId']) or a.get('title') or a['kind']}" for a in artifacts if a['nodeId'] not in represented_nodes]
    lines += sections['delivered']
    if not artifacts:
        lines.append('- 暂无其他已生成产物；本清单不代表应用物料已制作。')
    for status, title in [('recommended', '建议后续制作'), ('optional', '按需选配')]:
        lines += ['', f'## {title}', '', *(sections[status] or ['- 暂无。'])]
    return '\n'.join(lines)


def finalize_inventories(canvas, project_id, task_id, report):
    changed = False
    for node in canvas.load(project_id)['nodes']:
        data = node.get('data') or {}
        inventory = data.get('applicationInventory') or {}
        if inventory.get('version') != 1 or inventory.get('taskId') != task_id:
            continue
        # Respect subsequent manual edits, including text written by another task.
        if data.get('text') != inventory.get('renderedText'):
            continue
        text = render_inventory(inventory, report, node['id'])
        if text != data['text']:
            canvas.update_node(project_id, node['id'], {'data': {'text': text,
                'applicationInventory': {**inventory, 'renderedText': text}}})
            changed = True
    return changed
