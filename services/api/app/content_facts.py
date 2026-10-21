"""Flag unsupported technical numbers separately from file/browser validity.

Source matching is not independent verification of real-world accuracy. The
reviewer still checks context, corrections and other factual claims.
"""
import re
from html.parser import HTMLParser
from .conversation_context import _object


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.skip = 0
        self.stack = []
        self.parts = []
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        hidden = tag in {'script', 'style'} or 'hidden' in attrs or attrs.get('aria-hidden') == 'true' or bool(re.search(r'display\s*:\s*none|visibility\s*:\s*hidden', attrs.get('style') or '', re.I))
        if tag not in {'br', 'hr', 'img', 'input', 'meta', 'link', 'source', 'wbr'}:
            self.stack.append((tag, hidden))
            if hidden: self.skip += 1
    def handle_endtag(self, tag):
        index = next((i for i in range(len(self.stack) - 1, -1, -1) if self.stack[i][0] == tag), None)
        if index is not None:
            self.skip -= sum(1 for _, hidden in self.stack[index:] if hidden)
            del self.stack[index:]
    def handle_data(self, data):
        if not self.skip: self.parts.append(data)


NUMBER = re.compile(r'(?<![a-zA-Z0-9_.])(\d+(?:\.\d+)?)\s*(guest\s+cabins?|knots?|km/h|kW|kg|kn|m\b|米|节|吨|马力|客舱)', re.I)
UNITS = {'m': '米', 'kn': '节', 'knot': '节', 'knots': '节', 'guest cabin': '客舱', 'guest cabins': '客舱'}


def numbers(text):
    return {f'{float(match[1]):g}{UNITS.get(match[2].lower(), match[2].lower())}': match[0] for match in NUMBER.finditer(text)}


def fact_sources(store, project_id, task_id):
    sources = []
    with store._connect() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='tasks'").fetchone(): return sources
        current = db.execute('SELECT created_at,COALESCE(turn_order,rowid) AS position FROM tasks WHERE id=? AND project_id=?', (task_id, project_id)).fetchone()
        if not current: return sources
        rows = db.execute("""SELECT id,input_json FROM tasks WHERE project_id=? AND agent_key='design'
            AND superseded_by IS NULL AND (created_at<? OR (created_at=? AND COALESCE(turn_order,rowid)<=?)) ORDER BY created_at,COALESCE(turn_order,rowid)""",
            (project_id, current['created_at'], current['created_at'], current['position'])).fetchall()
        documents = set()
        for row in rows:
            data = _object(row['input_json'])
            if data.get('taskSurface', 'conversation') == 'canvas_node' and row['id'] != task_id:
                continue
            sources.append({'source': f"用户消息 {row['id']}", 'values': numbers(str(data.get('userMessage') or ''))})
            for ref in data.get('referencedFiles') or []:
                if isinstance(ref, dict) and ref.get('documentId'): documents.add((ref.get('scope', 'project'), ref['documentId']))
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for scope, document_id in documents:
            chunks, docs = ('global_knowledge_chunks', 'global_knowledge_documents') if scope == 'global' else ('knowledge_chunks', 'knowledge_documents')
            if chunks not in tables or docs not in tables: continue
            query = f'SELECT c.text FROM {chunks} c JOIN {docs} d ON d.id=c.document_id WHERE d.id=?'
            params = (document_id,)
            if scope != 'global': query += ' AND d.project_id=?'; params += (project_id,)
            text = '\n'.join(row['text'] for row in db.execute(query, params))
            sources.append({'source': f'引用资料 {document_id}', 'values': numbers(text)})
    # Research bodies are evidence; search summaries and past model answers
    # cannot independently verify a technical claim.
    from .project_context import ProjectContextResolver
    for evidence in ProjectContextResolver(store).evidence(project_id, task_id):
        if evidence['evidenceType'] == 'web_body':
            sources.append({'source': evidence['id'], 'values': numbers(evidence['text'])})
    return sources


def check_content_facts(content, kind, sources):
    text = str(content or '')
    if kind == 'html':
        parser = VisibleText(); parser.feed(text); text = ' '.join(parser.parts)
    claims = numbers(text)
    if not claims: return {'status': 'not_applicable', 'claims': [], 'note': '未检测到本规则覆盖的技术参数，不代表已核实所有事实'}
    # A visible disclaimer must identify the parameters as illustrative. A
    # hidden script/style comment cannot qualify the content for this status.
    illustrative = bool(re.search(r'(?:参数|规格|数据).{0,30}(?:概念示意|示例数据|仅供示意|待确认|未经核实)|(?:概念示意|示例数据).{0,30}(?:参数|规格|数据)|(?:illustrative|placeholder).{0,25}(?:specifications|parameters|data)', text, re.I))
    findings = []
    for key, value in claims.items():
        source = next((item['source'] for item in reversed(sources) if key in item['values']), None)
        findings.append({'value': value, 'source': source, 'status': 'source_matched' if source else 'illustrative' if illustrative else 'needs_confirmation'})
    state = 'needs_confirmation' if any(item['status'] == 'needs_confirmation' for item in findings) else 'illustrative' if any(item['status'] == 'illustrative' for item in findings) else 'source_matched'
    return {'status': state, 'claims': findings[:40], 'note': '有来源匹配仍需核对语境和用户后续更正'}
