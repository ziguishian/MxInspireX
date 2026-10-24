"""Real SDK runner with an entirely offline media/model transport."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.parametrize('api', ['responses', 'chat_completions'])
@pytest.mark.parametrize('mode', ['success', 'cancelled', 'unconfirmed', 'updates'])
def test_parallel_page_and_multi_output_finish_without_summary_call(api, mode):
    root = Path(__file__).resolve().parents[1]
    plan = {'ready': True, 'scopeId': 'scope', 'deliverables': [
        {'id': 'sound', 'kind': 'audio', 'title': '声音', 'supporting': True},
        {'id': 'page', 'kind': 'html', 'title': '页面', 'dependsOn': ['sound'],
         'inputs': [{'source': 'deliverable', 'id': 'sound', 'role': 'content', 'purpose': '试听'}]}]}
    payload = {'api': api, 'model': 'fixture', 'apiKey': 'fixture', 'baseUrl': 'http://web-fixture.invalid/v1',
        'executionStateVersion': 1, 'modelCapabilities': {'contextLength': 128000},
        'toolGateway': {'baseUrl': 'http://web-fixture.invalid', 'projectId': 'p', 'taskId': 't', 'supportsAsyncImageJobs': True},
        'context': {'projectId': 'p', 'taskId': 't', 'brief': '制作带试听的交互网页', 'constraints': {
            'executionPolicyVersion': 3, 'agentCollaboration': False, 'executionFlow': 'design',
            'designPlan': plan, 'requiredArtifacts': ['html'], 'deliveryVerification': True}}}
    if mode == 'updates':
        plan['deliverables'] = [{'id': id, 'kind': 'text', 'title': id} for id in ('a', 'b')]
        payload['context']['brief'] = '更新两张文字卡'
        payload['context']['constraints']['requiredArtifacts'] = ['text']
    result = subprocess.run([shutil.which('node'), '--import', (root/'tests/fixtures/web_pipeline_transport.mjs').as_uri(),
        str(root/'app/openai_agent_worker.mjs')], input=json.dumps(payload), text=True, encoding='utf-8',
        capture_output=True, timeout=30, env={**os.environ, 'WEB_PIPELINE_MODE': mode})
    events = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
    errors = [event for event in events if event['type'] == 'error']
    assert not errors, result.stderr + json.dumps([{key: event.get(key) for key in ('message','kind')} for event in errors], ensure_ascii=False)
    checkpoint = [event['recovery'] for event in events if event['type'] == 'checkpoint'][-1]
    assert checkpoint['performance']['sdkRequests'] == 2
    outputs = checkpoint['toolOutputs']
    assert len([item for item in outputs if item['name'] == 'generate_audio']) == (0 if mode == 'updates' else 1)
    if mode == 'updates':
        assert len([item for item in outputs if item['name'] == 'canvas_update_node']) == 2
        assert any(item['name'] == 'delivery_verify' and item['output']['passed'] for item in outputs)
    assert any(item['name'] == 'canvas_create_html' and item['output']['status'] == 'succeeded' for item in outputs) == (mode == 'success')
    if mode == 'success':
        pending = [event['recovery'] for event in events if event['type'] == 'checkpoint'
                   and event['recovery']['performance']['sdkRequests'] == 1
                   and any(item['output'].get('webMediaPending') for item in event['recovery']['toolOutputs'])][-1]
        payload['recovery'] = pending
        resumed = subprocess.run([shutil.which('node'), '--import', (root/'tests/fixtures/web_pipeline_transport.mjs').as_uri(),
            str(root/'app/openai_agent_worker.mjs')], input=json.dumps(payload), text=True, encoding='utf-8',
            capture_output=True, timeout=30, env={**os.environ, 'WEB_PIPELINE_MODE': mode, 'WEB_PIPELINE_RESUME': '1'})
        restored = [json.loads(line) for line in resumed.stdout.splitlines() if line.startswith('{')]
        assert not [event for event in restored if event['type'] == 'error'], resumed.stderr + str([event.get('message') for event in restored if event['type']=='error'])
        assert any(event['type'] == 'result' for event in restored)
