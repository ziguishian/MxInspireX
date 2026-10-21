from pathlib import Path
from unittest.mock import Mock, patch

from app.model_catalog import ModelCatalog
from app.model_config import DEFAULT_FAST_TEXT_MODEL, DEFAULT_TEXT_FALLBACK_MODEL
from app.models import new_project
from app.providers.registry import ProviderRegistry
from app.storage import ProjectStore
from app.task_runtime import TaskRuntime


def test_greeting_runs_installed_sdk_once_without_retrieval_or_canvas_calls(tmp_path, monkeypatch):
    import sys
    monkeypatch.setenv('FIXTURE_PYTHON',sys.executable)
    monkeypatch.setenv('FIXTURE_WORKSPACE',str(tmp_path))
    monkeypatch.setenv('PYTHONPATH',str(Path(__file__).parents[1]))
    monkeypatch.delenv('AICS_TEST_MODE', raising=False)
    monkeypatch.setenv('NODE_OPTIONS', f'--import={(Path(__file__).resolve().parent / "fixtures/greeting_transport.mjs").as_uri()}')
    store = ProjectStore(str(tmp_path))
    project = store.create_project(new_project(name='简单对话', slug='hello', brief='', budget_minor=None, currency='CNY', root_path=str(tmp_path/'hello')))
    catalog = ModelCatalog(store)
    catalog.save('openrouter', 'https://fixture.invalid/v1', {'models':[DEFAULT_FAST_TEXT_MODEL, DEFAULT_TEXT_FALLBACK_MODEL], 'modelCatalog':[]})
    providers = ProviderRegistry()
    providers.catalog = catalog
    knowledge, research = Mock(), Mock()
    knowledge.vector_search_for_project.side_effect = AssertionError('Greeting must not retrieve documents')
    research.list_sources.side_effect = AssertionError('Greeting must not read research sources')
    runtime = TaskRuntime(store, provider_registry=providers, knowledge_store=knowledge, research_store=research)
    with patch.object(providers.credentials, 'get', return_value='fixture-secret'):
        result = runtime.enqueue(project_id=project['id'], agent_key='design', workflow_step='design', brief='你好', input_data={
            'textProvider':{'key':'openrouter','baseUrl':'https://fixture.invalid/v1','model':'gpt-6-astra'},
            'modelRouting':{'mode':'auto'}, 'allowExternalNetwork':True,
        })
    assert result['status']=='succeeded', result
    output = result['output']
    assert output['structured_data']['answer']=='你好！很高兴见到你。'
    assert output['provenance']['model']==DEFAULT_FAST_TEXT_MODEL
    assert output['provenance']['modelRequestCount']==1
    assert output['provenance']['stages']==['design']
    assert output['provenance']['toolOutputCount']==0
    assert output['provenance']['executionFlow']=='direct'
    assert output['usage']['total_tokens']==42
    assert not any(event['phase']=='retrieval' for event in result['trace'])
    assert any(event['phase']=='text' and '你好' in event['message'] for event in result['trace'])
    assert not (tmp_path/'hello/canvas').exists()
