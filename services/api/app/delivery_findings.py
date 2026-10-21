"""Report generation and file availability; adapt legacy review records."""

LABELS = {'problem': '生成异常', 'unverified': '执行待处理',
          'production_confirmation': '制作参数待确认', 'generation_unconfirmed': '生成结果待确认'}
ACTIONS = {
    'problem': '查看对应产物，说明需要修改的部分后继续。',
    'unverified': '查看已有产物与依据，补充资料或明确要求检查具体内容。',
    'production_confirmation': '制作前补充并确认尺寸、材质、工艺等参数。',
    'generation_unconfirmed': '先核对图像服务的原请求、结果和计费记录；核对前不要重新提交生成。',
}
CODE_ACTIONS = {
    'file_missing': '恢复原文件或重新导入对应资产，再检查已有产物。',
    'file_empty': '检查原文件并恢复或重新导入完整文件。',
    'asset_missing': '恢复或重新导入该节点引用的资产。',
    'content_empty': '在对应节点补充内容，或在对话中说明需要完成的内容。',
    'format_mismatch': '核对要求的文件格式，并在对话中指定需要转换或修改的产物。',
    'dimension_mismatch': '核对要求与实际像素尺寸，在对话中指定此产物和目标尺寸。',
    'transparency_missing': '打开原图检查透明通道，在对话中指定此产物需要透明背景。',
    'image_invalid': '检查原图片能否打开；恢复完整文件或检查图像服务返回格式。',
    'cad_invalid': '查看已保存模型的几何检查结果，说明需要修正的实体问题。',
    'cad_check_unavailable': '检查已保存的 CAD 文件和本地预览环境，再检查已有文件。',
}


def finding(kind, code, message, *, node_id=None, plan_item_id=None, next_action=None, repair=None, source_task_id=None, artifact_fingerprint=None):
    return {'kind': kind, 'code': code, 'message': str(message)[:1000],
            'nextAction': next_action or (CODE_ACTIONS.get(code) if kind == 'problem' else None) or ACTIONS[kind],
            **({'nodeId': node_id} if node_id else {}), **({'planItemId': plan_item_id} if plan_item_id else {}),
            **({'repair': repair} if kind == 'problem' and isinstance(repair, dict) and repair.get('change') else {}),
            **({'sourceTaskId': source_task_id} if source_task_id else {}),
            **({'artifactFingerprint': artifact_fingerprint} if artifact_fingerprint else {})}


def unique_findings(items):
    result, seen = [], set()
    for item in items:
        if not isinstance(item, dict) or item.get('kind') not in LABELS or not item.get('message'):
            continue
        key = (item['kind'], item.get('nodeId'), item.get('planItemId'), item['message'])
        if key not in seen:
            seen.add(key)
            result.append({**item, 'nextAction': item.get('nextAction') or ACTIONS[item['kind']]})
    return result


# Only operational failures affect completion. Design quality is judged by users.
OPERATIONAL_CODES = {
    'file_missing', 'file_empty', 'asset_missing', 'content_empty', 'image_invalid',
    'cad_invalid', 'cad_check_unavailable', 'video_generation_failed',
    'generation_failed', 'generation_unconfirmed', 'image_output_format',
    'image_response_invalid', 'image_response_timeout', 'image_result_unconfirmed',
    'media_timeout', 'media_transport', 'media_decode', 'preview_failed',
    'count_mismatch', 'artifact_missing', 'plan_incomplete', 'execution_interrupted',
}


def collect_findings(data):
    report = data.get('delivery') or {}
    return unique_findings([item for item in report.get('findings') or []
                           if item.get('code') in OPERATIONAL_CODES or item.get('kind') == 'generation_unconfirmed'])


def settled_answer(answer):
    pending = {'视频请求已受理，正在等待生成结果。', '产物仍在生成或加载中，保存完成后更新结果。'}
    lines = [line for line in str(answer or '').splitlines() if line.strip() not in pending]
    completion = '作品已生成并保存到右侧画布。'
    if any(line.strip().endswith('作品已保存到右侧画布。') for line in lines):
        lines = [line for line in lines if line.strip() != completion]
    return '\n'.join(lines).strip()


def annotate_delivery(data):
    # Project legacy records without changing their persisted billing/history.
    had_review = bool(data.pop('review', None))
    data.pop('unverifiedNodeIds', None)
    findings = collect_findings(data)
    data['deliveryFindings'] = findings
    report = data.get('delivery')
    if report is not None:
        for key in ('reviewCache', 'reviewScopeHash', 'reviewEvidenceVersion', 'contentChecks'):
            report.pop(key, None)
        report['findings'] = findings
        report['issues'] = list(dict.fromkeys(item['message'] for item in findings))
        pending = bool(report.get('pendingMedia') or report.get('pendingPreview'))
        batch = report.get('designBatch')
        items = [item for item in report.get('deliverables') or []
                 if not batch or item['id'] in batch.get('itemIds', [])]
        incomplete = bool(batch and batch.get('status') == 'needs_plan') or any(item.get('status') in {'pending', 'blocked', 'generating'} for item in items)
        unavailable = any(not item.get('ready') for item in report.get('artifacts') or [])
        report['passed'] = not (findings or pending or incomplete or unavailable)
        data['deliveryStatus'] = 'pending' if pending else 'needs_review' if findings or incomplete or unavailable or data.get('executionError') else 'passed'
        for item in report.get('deliverables') or []:
            item['findings'] = [f for f in findings if f.get('planItemId') == item['id'] or
                                not f.get('planItemId') and f.get('nodeId') in item.get('nodeIds', [])]
            if item.get('status') in {'ready', 'passed', 'needs_review'}:
                item['status'] = 'needs_review' if item['findings'] else 'passed'
        if had_review:
            saved = any(item.get('ready') for item in report.get('artifacts') or [])
            data['answer'] = ('作品已保存到右侧画布。' if saved else '本轮尚未保存作品。') + ('\n' + '；'.join(report['issues']) if findings else '')
        if data['deliveryStatus'] == 'passed' and report.get('artifacts') and 'answer' in data:
            data['answer'] = settled_answer(data['answer'])
    if data.get('clarification') or data.get('referenceSelection'):
        data.pop('deliveryStatus', None)
    return findings


def findings_summary(findings):
    return '；'.join(f'{label} {sum(f["kind"] == kind for f in findings)} 项'
                     for kind, label in LABELS.items() if any(f['kind'] == kind for f in findings))
