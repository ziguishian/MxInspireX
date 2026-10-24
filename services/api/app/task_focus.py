"""Select relevant context without sending the whole canvas to the model."""
import re


def whole_canvas_requested(text):
    # A prohibition such as “不要遍历整个画布” must never enable an overview.
    clauses = re.split(r'[，。；!！?？\n]|\bbut\b', str(text))
    return any(not re.search(r'不(?:要|能|必|用|需要|想|应该|允许)|无需|避免|禁止|别|尽量不|\b(?:not|never|avoid|without|don.t)\b', clause, re.I)
               and re.search(r'(?:全部|整个|整张|所有).{0,8}(?:画布|节点|产物|素材)|(?:画布|节点).{0,8}(?:全部|整体)|\b(?:entire|whole) canvas\b|\ball nodes\b', clause, re.I)
               and re.search(r'检查|查看|浏览|遍历|读取|整理|修改|调整|重排|布局|导出|处理|清理|列出|优化|统一|展示|\b(?:inspect|read|review|scan|export|update|organize)\b',clause,re.I)
               for clause in clauses)


def node_view(node, *, text_offset=0, text_limit=3000):
    from .node_context import fingerprint
    data = node.get('data') or {}
    selected = {key: data[key] for key in ('kind','title','adopted','adoptedAt','editor','referenceRole','assetId','styleFramework','imageAssetIds','mediaAssetIds','videoAssetIds','audioAssetIds','previewSize','htmlPreviewSize','generating','status','error','draft') if key in data}
    if data.get('asset'):
        selected['asset'] = {key: data['asset'][key] for key in ('id','kind','mime') if key in data['asset']}
        selected.setdefault('assetId', data['asset'].get('id'))
    selected['params'] = {key: value for key, value in (data.get('params') or {}).items() if key in {'size','aspectRatio','background','quality','output_format','model','duration'}}
    longest = 0
    if data.get('kind') == 'cad' and data.get('cad'):
        cad = data['cad']
        selected['cadRevision'] = data.get('cadRevision')
        selected['cad'] = {k:cad[k] for k in ('parameters','parameter_definitions','checks','assumptions','reference_asset_ids') if k in cad}
        source = cad.get('source','')
        selected['cad']['source'] = source[text_offset:text_offset+text_limit]
        longest = len(source)
    for key in ('text','html','summary','prompt'):
        if isinstance(data.get(key), str):
            from .web_framework import strip_web_framework
            content = strip_web_framework(data[key]) if key == 'html' else data[key]
            longest = max(longest, len(content))
            selected[key] = content[text_offset:text_offset+text_limit]
    if data.get('job'):
        selected['job'] = {key: data['job'][key] for key in ('id','jobId','status') if key in data['job']}
    return {'id': node['id'], 'version':fingerprint(node), 'position': node.get('position'), 'data': selected,
            'nextTextOffset': text_offset+text_limit if longest > text_offset+text_limit else None}


class TaskFocus:
    def __init__(self, store, canvas):
        self.store, self.canvas = store, canvas
        with store._connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS task_focus_reads (project_id TEXT, task_id TEXT, kind TEXT, entity_id TEXT, PRIMARY KEY(project_id,task_id,kind,entity_id))')

    def remember_candidates(self, project_id, task_id, kind, ids, limit=12):
        if not task_id: return list(ids)
        with self.store._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            rows = db.execute('SELECT kind,entity_id FROM task_focus_reads WHERE project_id=? AND task_id=?',(project_id,task_id)).fetchall()
            seen = {(r['kind'],r['entity_id']) for r in rows}
            selected = []
            for value in ids:
                if (kind,value) not in seen and limit is not None and len(seen)>=limit: continue
                db.execute('INSERT OR IGNORE INTO task_focus_reads VALUES (?,?,?,?)',(project_id,task_id,kind,value))
                seen.add((kind,value)); selected.append(value)
            return selected

    def _history(self, project_id, task_id, context):
        if not task_id or not context.get('userMessage') or context.get('taskSurface') == 'canvas_node':
            return []
        from .conversation_context import ConversationContext
        return ConversationContext(self.store).build(project_id,task_id,context.get('userMessage','')).get('recentOutcomes', [])

    def known_ids(self, project_id, task_id, context, focus=None):
        """References, conversation targets and current outputs are legitimate reads."""
        focus = focus or self.resolve(project_id,task_id,context)
        nodes, assets = set(focus['nodeIds']), {a['assetId'] for a in focus['assetReferences'] if a['projectId']==project_id}
        target = (context.get('canvasParams') or {}).get('canvasNodeId')
        if context.get('taskSurface') == 'canvas_node' and target:
            nodes.add(target)
        nodes.update(context.get('deliveryRepairNodes') or [])
        for ref in (context.get('conversationMemory') or {}).get('selected',[]):
            if ref.get('assetId'): assets.add(ref['assetId'])
        assets.update(ref['assetId'] for ref in context.get('memoryInputAssets',[]) if ref.get('assetId'))
        assets.update(ref['assetId'] for ref in context.get('memoryContextAssets',[]) if ref.get('assetId'))
        with self.store._connect() as db:
            for row in db.execute('SELECT kind,entity_id FROM task_focus_reads WHERE project_id=? AND task_id=?',(project_id,task_id)):
                (nodes if row['kind']=='node' else assets).add(row['entity_id'])
        for turn in self._history(project_id,task_id,context):
            for item in [*(turn.get('artifacts') or []), *(turn.get('references') or [])]:
                if item.get('projectId',project_id)!=project_id: continue
                if item.get('nodeId'): nodes.add(item['nodeId'])
                if item.get('referenceType')=='node' and item.get('id'): nodes.add(item['id'])
                if item.get('assetId'): assets.add(item['assetId'])
                if item.get('referenceType')=='asset' and item.get('id'): assets.add(item['id'])
        for node in self.canvas.load(project_id)['nodes']:
            if task_id and node.get('meta',{}).get('taskId')==task_id: nodes.add(node['id'])
            if node['id'] in nodes:
                asset_id = node.get('data',{}).get('assetId') or (node.get('data',{}).get('asset') or {}).get('id')
                if asset_id: assets.add(asset_id)
                assets.update(node.get('data', {}).get('imageAssetIds') or [])
                assets.update(node.get('data', {}).get('mediaAssetIds') or [])
        # Uploaded/global reference images receive local, editable asset IDs.
        if context.get('referencedFiles') or context.get('referencedAssets') or assets:
            from .assets import AssetStore
            files = {ref.get('pathRelative') for ref in context.get('referencedFiles',[]) if ref.get('pathRelative')}
            documents = {ref.get('documentId') for ref in context.get('referencedFiles',[]) if ref.get('documentId')}
            origins = {(ref.get('projectId',project_id),ref.get('id') or ref.get('assetId')) for ref in context.get('referencedAssets',[])}
            for asset in AssetStore(self.store).list_assets(project_id):
                meta = asset.get('metadata') or {}
                origin=meta.get('referenceOrigin') or {}
                if meta.get('referenceFile') in files or meta.get('referenceDocumentId') in documents or meta.get('sourceDocumentId') in documents or (origin.get('projectId'),origin.get('assetId')) in origins or (task_id and meta.get('taskId')==task_id): assets.add(asset['id'])
        return nodes, assets

    def validate_ids(self, project_id, task_id, context, *, node_ids=(), asset_ids=()):
        if not task_id or whole_canvas_requested(context.get('userMessage','')): return
        focus = self.resolve(project_id,task_id,context)
        if focus['mode']=='none': return  # A targeted lookup is allowed when context is insufficient.
        known_nodes, known_assets = self.known_ids(project_id,task_id,context,focus)
        if set(node_ids)-known_nodes or set(asset_ids)-known_assets:
            raise ValueError('目标不在本轮引用、对话相关内容或本轮产物中。请先根据用户引用与上下文确定目标，不要读取或修改无关画布内容。')

    def resolve(self, project_id, task_id, context, conversation=None):
        params = context.get('canvasParams') or {}
        node_ids = []
        assets = []
        def add_node(value):
            if isinstance(value,str) and value and value not in node_ids: node_ids.append(value)
        def add_asset(value, owner=project_id):
            if isinstance(value,str) and value and {'assetId':value,'projectId':owner} not in assets:
                assets.append({'assetId':value,'projectId':owner})
        for ref in context.get('referencedNodes') or []:
            if isinstance(ref,dict) and ref.get('projectId',project_id)==project_id: add_node(ref.get('id') or ref.get('nodeId'))
        if context.get('taskSurface') != 'canvas_node':
            add_node(params.get('canvasNodeId'))
        for node_id in params.get('reference_node_ids') or []: add_node(node_id)
        for ref in context.get('referencedAssets') or []:
            if not isinstance(ref,dict): continue
            owner = ref.get('projectId') or project_id
            add_asset(ref.get('id') or ref.get('assetId'),owner)
            if owner==project_id: add_node(ref.get('nodeId'))
        add_asset(params.get('source_asset_id'))
        add_asset(params.get('last_frame_asset_id'))
        for asset_id in [*(params.get('source_asset_ids') or []), *(params.get('reference_asset_ids') or [])]: add_asset(asset_id)
        # Accept exact mention tokens, not substring matches such as n1 / n10.
        for kind, value in re.findall(r'@(node|asset):([A-Za-z0-9_-]+)', str(context.get('userMessage',''))):
            if kind=='node': add_node(value)
            elif not any(ref['assetId']==value for ref in assets): add_asset(value)
        explicit = bool(node_ids or assets or context.get('referencedFiles') or context.get('referencedNodes') or context.get('referencedAssets') or re.search(r'@knowledge:[A-Za-z0-9_-]+',str(context.get('userMessage',''))))
        mode = 'references' if explicit else 'none'
        context_status = None
        memory_refs=[r for r in (context.get('conversationMemory') or {}).get('selected',[]) if r.get('assetId')]
        if not explicit and memory_refs:
            for ref in memory_refs: add_asset(ref['assetId'])
            mode='memory'
        if not explicit and not memory_refs:
            history = (conversation or {}).get('recentOutcomes',[]) if conversation is not None else self._history(project_id,task_id,context)
            for turn in reversed(history):
                records = turn.get('artifacts') or turn.get('references') or []
                if not records: continue
                for artifact in records[-8:]:
                    if artifact.get('projectId',project_id)!=project_id: continue
                    add_node(artifact.get('nodeId'));add_asset(artifact.get('assetId'))
                    if artifact.get('referenceType')=='node': add_node(artifact.get('id'))
                    if artifact.get('referenceType')=='asset': add_asset(artifact.get('id'))
                mode = 'context'
                context_status = turn.get('status')
                break
        nodes = self.canvas.load(project_id)['nodes'] if node_ids or assets else []
        by_id = {node['id']: node for node in nodes}
        # A known node identifies the precise placement of a reused asset.
        for ref in list(assets):
            if ref['projectId']!=project_id: continue
            if any(((by_id.get(id,{}).get('data') or {}).get('assetId') or ((by_id.get(id,{}).get('data') or {}).get('asset') or {}).get('id'))==ref['assetId'] for id in node_ids): continue
            for node in nodes:
                if (node.get('data',{}).get('assetId') or (node.get('data',{}).get('asset') or {}).get('id'))==ref['assetId']: add_node(node['id'])
        missing = [id for id in node_ids if id not in by_id]
        resolved = [by_id[id] for id in node_ids if id in by_id]
        for node in resolved:
            add_asset(node.get('data',{}).get('assetId') or (node.get('data',{}).get('asset') or {}).get('id'))
        return {'mode':mode,'hasReferences':explicit,'nodeIds':[n['id'] for n in resolved],
                'contextTaskStatus':context_status,
                'selectionRequired':mode=='context' and len(resolved)>1,
                'nodes':[({'id':n['id'],'position':n.get('position'),'data':{k:n.get('data',{}).get(k) for k in ('kind','title','assetId')}} if mode=='context' and len(resolved)>1 else node_view(n)) for n in resolved[:8]],'assetReferences':assets,
                'missingNodeIds':missing,'moreReferencedNodes':max(0,len(resolved)-8),
                'fileCount':len(context.get('referencedFiles') or []),
                'allowOverview':whole_canvas_requested(context.get('userMessage','')),
                'guidance':'先理解用户语义，区分待修改对象与风格/内容参考。上下文候选不代表全部都要修改；选择具体 ID 后精读。图像修改把原图资产作为参考，使用 output_mode=create 在新节点生成并保留原图；其他内容的原位修改才填 canvas_node_id。引用缺失时说明问题，不改选无关节点。'}

    def read(self, project_id, task_id, context, *, node_ids=None, asset_ids=None, scope='focus', query='', offset=0, limit=6, text_offset=0):
        if scope not in {'focus','outputs','discover'}: raise ValueError('画布读取范围无效')
        node_ids,asset_ids = node_ids or [],asset_ids or []
        if not isinstance(node_ids,list) or not isinstance(asset_ids,list) or len(node_ids)>20 or len(asset_ids)>20:
            raise ValueError('每次按 ID 最多读取 20 个目标')
        board = self.canvas.load(project_id)
        explicit_ids = bool(node_ids or asset_ids)
        if explicit_ids:
            self.validate_ids(project_id,task_id,context,node_ids=node_ids,asset_ids=asset_ids)
        if scope=='outputs':
            nodes = [n for n in board['nodes'] if task_id and n.get('meta',{}).get('taskId')==task_id
                     and (not explicit_ids or n['id'] in node_ids or n.get('data',{}).get('assetId') in asset_ids)]
        elif explicit_ids:
            nodes = [n for n in board['nodes'] if n['id'] in node_ids or n.get('data',{}).get('assetId') in asset_ids]
        else:
            focus = self.resolve(project_id,task_id,context)
            if scope=='discover' and focus['hasReferences'] and not focus['allowOverview']:
                raise ValueError('本轮已有明确引用，请按引用或上下文中的节点 ID 读取；无需遍历整张画布')
            if scope=='focus' and (focus['mode']!='none' or focus['hasReferences']):
                node_ids = focus['nodeIds']
                nodes = [n for n in board['nodes'] if n['id'] in node_ids]
                if focus['selectionRequired']: scope='candidates'
            else:
                scope = 'discover'
                needle = str(query).strip().casefold()
                if not needle and not focus['allowOverview']:
                    return {'tool':'canvas_read','scope':'discover','canvas':{'nodes':[],'edges':[]},'total':0,'nextOffset':None,
                            'needsTarget':True,'notice':'先根据当前对话或 conversation_read 确定目标；确实缺少线索时提供具体标题 query。禁止无关键词遍历画布。'}
                if offset and not focus['allowOverview']:
                    raise ValueError('请按标题缩小查找范围或澄清目标，不要逐页遍历画布')
                nodes = [n for n in board['nodes'] if not needle or needle in str(n.get('data',{}).get('title','')).casefold() or needle==n['id'].casefold()]
        start,limit = max(0,int(offset)),max(1,min(8,int(limit)))
        page = nodes[start:start+limit]
        if scope=='discover' and not whole_canvas_requested(context.get('userMessage','')):
            selected_ids = self.remember_candidates(project_id,task_id,'node',[n['id'] for n in page])
            page = [n for n in page if n['id'] in selected_ids]
        if scope in {'discover','candidates'}:
            selected = [{'id':n['id'],'position':n.get('position'),'data':{key:n.get('data',{}).get(key) for key in ('kind','title','assetId')}} for n in page]
        else:
            selected = [node_view(n,text_offset=max(0,int(text_offset)),text_limit=12000) for n in page]
        ids = {n['id'] for n in page}
        edges = [e for e in board.get('edges',[]) if e.get('source') in ids and e.get('target') in ids]
        return {'tool':'canvas_read','scope':scope,'canvas':{'nodes':selected,'edges':edges},
                'total':len(nodes),'nextOffset':start+limit if start+limit<len(nodes) and (scope!='discover' or whole_canvas_requested(context.get('userMessage',''))) else None,
                'missingNodeIds':[id for id in node_ids if not any(n['id']==id for n in nodes)],
                'notice':'仅返回相关节点；目录只含标题和 ID，确认目标后按 ID 精读。没有目标时优先 conversation_read，仍不明确再澄清。'}
