"""Optional workspace prompt references, isolated from project knowledge."""
import json
from pathlib import Path
from .vector_index import LocalVectorIndex


class PromptTemplateStore:
    def __init__(self, workspace):
        self.root = Path(workspace) / 'prompt-templates'
        self.catalog = self.root / 'templates.json'

    def records(self):
        if not self.catalog.exists():
            return []
        records = json.loads(self.catalog.read_text(encoding='utf-8'))
        if not isinstance(records, list):
            raise ValueError('提示词模板目录格式无效')
        return records

    def upsert(self, record):
        for key in ('id', 'text', 'kind', 'source'):
            if not isinstance(record.get(key), str) or not record[key].strip():
                raise ValueError(f'模板缺少 {key}')
        if not isinstance(record.get('styles', []), list) or any(not isinstance(s, str) for s in record.get('styles', [])):
            raise ValueError('模板 styles 必须为字符串列表')
        clean = {key: record[key] for key in ('id', 'text', 'kind', 'source')}
        clean['styles'] = record.get('styles', [])
        records = [item for item in self.records() if item['id'] != clean['id']] + [clean]
        self.root.mkdir(parents=True, exist_ok=True)
        index = LocalVectorIndex(self.root / 'index')
        index.remove([clean['id']])
        index.add([{'chunk_id': clean['id'], 'project_id': 'prompt-templates', 'text': clean['text']}])
        temporary = self.catalog.with_suffix('.tmp')
        temporary.write_text(json.dumps(records, ensure_ascii=False), encoding='utf-8')
        temporary.replace(self.catalog)

    def search(self, query):
        records = self.records()
        if not records:
            return []
        by_id = {item['id']: item for item in records}
        hits = LocalVectorIndex(self.root / 'index').search(project_id='prompt-templates', query=query, limit=3)
        if not hits:
            raise ValueError('模板目录非空，但向量索引缺失或不可读取，请重新导入模板')
        return [by_id[hit['chunk_id']] for hit in hits if hit['chunk_id'] in by_id]


def retrieve_templates(workspace, query, constraints, trace):
    if constraints.get('taskSurface') == 'canvas_node' or constraints.get('simpleConversation'):
        return
    try:
        candidates = PromptTemplateStore(workspace).search(query)
    except Exception as error:
        trace('retrieval', '提示词模板检索失败，本轮继续使用用户需求：' + str(error)[:300])
        return
    if candidates:
        constraints['promptTemplates'] = {'candidates': candidates, 'trust': 'reference_only'}
        trace('retrieval', f'已检索 {len(candidates)} 条提示词参考，按适用性选择')
