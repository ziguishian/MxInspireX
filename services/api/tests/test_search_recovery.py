import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.providers.web_search import OpenAIWebSearchProvider, WebSearchError
from app.research import ResearchImportError
from test_agent_capabilities import task_for_tools


def native_transport(monkeypatch, tmp_path, mode='success'):
    fixture = Path(__file__).parent / 'fixtures/native_search_transport.mjs'
    requests = tmp_path / 'requests.jsonl'
    monkeypatch.setenv('NODE_OPTIONS', '--import ' + str(fixture.resolve()))
    monkeypatch.setenv('NATIVE_SEARCH_FIXTURE', mode)
    monkeypatch.setenv('SEARCH_REQUEST_FILE', str(requests))
    return requests


def provider_for(provider='openrouter', **kwargs):
    return OpenAIWebSearchProvider('https://fixture.test/v1', provider, 'openai/gpt-6-luna', SimpleNamespace(get=lambda _: 'fixture-secret'), **kwargs)


@pytest.mark.parametrize('provider', ['openrouter', 'openai-compatible'])
@pytest.mark.parametrize('mode', ['success', 'annotations', 'server_usage'])
def test_sdk_hosted_search_with_action_sources_or_annotations(monkeypatch, tmp_path, provider, mode):
    requests = native_transport(monkeypatch, tmp_path, mode)
    adapter = provider_for(provider)
    result = adapter.search('查询')
    assert result['sources'] == [{'url':'https://93.184.216.34/source','title':'原始资料'}]
    assert result['runtime'] == 'openai-agents-sdk'
    assert result['searchCalls'] == (2 if mode == 'server_usage' else 1)
    assert adapter.last_response['usage']['cost'] == .004
    body = json.loads(requests.read_text())
    assert body['tools'][0]['type'] == ('openrouter:web_search' if provider == 'openrouter' else 'web_search')
    assert body['model'] == 'openai/gpt-6-luna'
    assert 'plugins' not in body


@pytest.mark.parametrize('mode', ['no_search', 'no_sources', 'incomplete', 'truncated'])
def test_sdk_rejects_missing_evidence_and_incomplete_results(monkeypatch, tmp_path, mode):
    native_transport(monkeypatch, tmp_path, mode)
    adapter = provider_for()
    with pytest.raises(WebSearchError) as error: adapter.search('查询')
    assert error.value.stop_tool and not error.value.rejected
    if mode != 'truncated': assert adapter.last_response['usage']


def test_sdk_search_cancellation_and_deadline(monkeypatch, tmp_path):
    native_transport(monkeypatch, tmp_path, 'hang')
    start = time.monotonic()
    with pytest.raises(WebSearchError, match='总时限') as error: provider_for(timeout=.2).search('查询')
    assert error.value.stop_tool
    assert time.monotonic() - start < 2
    start = time.monotonic()
    with pytest.raises(WebSearchError, match='已停止'):
        provider_for(timeout=10).search('查询',should_cancel=lambda:time.monotonic()-start > .15)
    assert time.monotonic() - start < 2


def test_search_api_does_not_fallback_to_chat_or_plugin(monkeypatch, tmp_path):
    requests = native_transport(monkeypatch, tmp_path)
    with pytest.raises(WebSearchError, match='Responses'): provider_for(api='chat_completions').search('查询')
    assert not requests.exists()


def test_rejected_search_persists_stop_without_charge(monkeypatch, tmp_path):
    requests = native_transport(monkeypatch,tmp_path,'http400')
    monkeypatch.setenv('AICS_WORKSPACE_ROOT',str(tmp_path/'workspace'))
    monkeypatch.setenv('AICS_PROVIDER_KEY_OPENAI_COMPATIBLE','fixture-secret')
    with TestClient(app) as client:
        catalog = app.state.model_catalog
        catalog.save('openai-compatible','https://relay.test/v1',{'models':['gpt-6-luna','gpt-5.6-terra']})
        settings=catalog.settings();settings.search.provider='openai-compatible';settings.search.baseUrl='https://relay.test/v1';catalog.save_settings(settings)
        project, headers = task_for_tools(client)
        before = client.get('/api/credits').json()
        first = client.post(f'/api/projects/{project}/agent-tools/web_search',headers=headers,json={'query':'查询'})
        second = client.post(f'/api/projects/{project}/agent-tools/web_search',headers=headers,json={'query':'换词查询'})
        assert first.status_code == second.status_code == 422
        assert '不支持或拒绝 SDK' in first.json()['detail']
        assert 'fixture-secret' not in first.text
        assert first.json()['stopTool']
        assert len(requests.read_text().splitlines()) == 1
        assert client.get('/api/credits').json() == before


def test_search_success_is_reused_and_explicit_model_wins(monkeypatch, tmp_path):
    requests = native_transport(monkeypatch,tmp_path)
    monkeypatch.setenv('AICS_WORKSPACE_ROOT',str(tmp_path/'workspace'))
    monkeypatch.setenv('AICS_PROVIDER_KEY_OPENAI_COMPATIBLE','fixture-secret')
    with TestClient(app) as client:
        catalog = app.state.model_catalog
        catalog.save('openai-compatible','https://relay.test/v1',{'models':['gpt-6-luna','gpt-5.6-terra']})
        settings=catalog.settings();settings.search.provider='openai-compatible';settings.search.baseUrl='https://relay.test/v1';catalog.save_settings(settings)
        project, headers = task_for_tools(client)
        args={'query':'查询'}
        first=client.post(f'/api/projects/{project}/agent-tools/web_search',headers=headers,json=args)
        second=client.post(f'/api/projects/{project}/agent-tools/web_search',headers=headers,json=args)
        assert first.status_code == second.status_code == 200,first.text
        assert len(requests.read_text().splitlines()) == 1
        settings=catalog.settings();settings.search.model='gpt-5.6-terra';catalog.save_settings(settings)
        third=client.post(f'/api/projects/{project}/agent-tools/web_search',headers=headers,json={'query':'另一查询'})
        assert third.status_code==200,third.text
        assert json.loads(requests.read_text().splitlines()[-1])['model']=='gpt-5.6-terra'


def test_web_read_reports_forbidden_source_instead_of_generic_server_error(tmp_path, monkeypatch):
    monkeypatch.setenv('AICS_WORKSPACE_ROOT', str(tmp_path))
    with TestClient(app) as client:
        project, headers = task_for_tools(client)
        with patch('app.research.ResearchStore._fetch', side_effect=ResearchImportError('研究来源抓取失败: HTTP Error 403: Forbidden')):
            result = client.post(f'/api/projects/{project}/agent-tools/web_read', headers=headers, json={'url': 'https://93.184.216.34/restricted'})
        assert result.status_code == 502
        assert '403' in result.json()['detail']
        assert '不要反复请求' in result.json()['detail']


@pytest.mark.parametrize('mode', ['permanent', 'transient', 'recovery', 'hang_headers', 'hang_body', 'bad_body'])
def test_sdk_stops_eight_queued_searches_and_restores_block_after_restart(mode):
    root = Path(__file__).resolve().parents[1]
    payload = {'api': 'chat_completions', 'model': 'fixture', 'apiKey': 'fixture', 'baseUrl': 'http://fixture.invalid/v1',
               'maxParallelTools': 4, 'context': {'projectId': 'project', 'taskId': 'task', 'brief': '调研最新标准',
               'constraints': {'allowExternalNetwork': True, 'agentCollaboration': False, 'executionFlow': 'direct'}}}
    if mode == 'recovery': payload['recovery'] = {'blockedTools': {'web_search': {'status': 'unavailable', 'sources': [], 'retryable': False}}}
    # Exercise an almost-spent search budget without imposing a task deadline.
    if mode.startswith('hang_'): payload['recovery']={'searchElapsedMs':118800}
    result = subprocess.run([shutil.which('node'), '--import', str(root/'tests/fixtures/search_failure_transport.mjs'), str(root/'app/openai_agent_worker.mjs')],
                            input=json.dumps(payload), text=True, capture_output=True, timeout=30,
                            env={**os.environ, 'SEARCH_FAILURE_FIXTURE': mode})
    assert result.returncode == 0, result.stderr + result.stdout[-5000:]
    events = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
    searches = [e for e in events if e.get('phase') == 'tool' and e.get('message') == '调用工具：web_search']
    assert len(searches) == (0 if mode == 'recovery' else 2 if mode == 'transient' else 1)
    assert any(e.get('type') == 'checkpoint' and e['recovery']['blockedTools'].get('web_search') for e in events)
    assert next(e['result']['structured_data']['answer'] for e in events if e['type'] == 'result') == '联网搜索不可用，无法核验最新标准。'
    completed=next(e['result'] for e in events if e['type']=='result')
    assert completed['provenance']['toolFailureCount']==0
    assert completed['provenance']['searchUnavailable']
    assert completed['warnings']
