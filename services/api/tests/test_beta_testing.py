import io
import json
import zipfile
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.beta_testing import BetaTesting, FeedbackInput, UsageInput, redact
from app.canvas import CanvasStore
from app.main import app
from app.models import new_project
from app.storage import ProjectStore
from app.task_runtime import TaskRuntime


@pytest.fixture
def env(tmp_path):
    store = ProjectStore(str(tmp_path))
    project = store.create_project(new_project(name='测试项目', slug='beta', brief='测试', budget_minor=None, currency='CNY', root_path=str(tmp_path / 'beta')))
    tasks = TaskRuntime(store)
    with patch.object(tasks, '_start_worker'):
        task = tasks.enqueue(project_id=project['id'], agent_key='design', workflow_step='design', brief='请设计礼盒', input_data={'textProvider': {'key':'openrouter', 'model':'example', 'apiKey':'NEVER_EXPORT'}}, run_async=True)
    canvas = CanvasStore(store)
    service = BetaTesting(store, canvas)
    return service, project['id'], task['id']


def add_output(service, project, task):
    return service.canvas.create_node(project, kind='text', title='方案', data={'text':'礼盒方案'}, task_id=task)


def test_ratings_validate_scope_and_require_visible_output(env):
    service, project, task = env
    with pytest.raises(HTTPException) as missing:
        service.save_feedback('another-project', task, FeedbackInput(action='rated', rating=4))
    assert missing.value.status_code == 404
    with pytest.raises(HTTPException) as pending:
        service.save_feedback(project, task, FeedbackInput(action='rated', rating=4))
    assert pending.value.status_code == 409
    for invalid in [0, 6, 1.5, True, '5']:
        with pytest.raises(ValidationError):
            FeedbackInput(action='rated', rating=invalid)
    add_output(service, project, task)
    assert service.save_feedback(project, task, FeedbackInput(action='rated', rating=4))['rating'] == 4


def test_feedback_persists_and_updates_one_record_instead_of_duplicating(env):
    service, project, task = env
    add_output(service, project, task)
    shown = service.save_feedback(project, task, FeedbackInput(action='shown'))
    assert service.save_feedback(project, task, FeedbackInput(action='shown'))['shownAt'] == shown['shownAt']
    assert service.save_feedback(project, task, FeedbackInput(action='dismissed'))['dismissedAt']
    service.save_feedback(project, task, FeedbackInput(action='rated', rating=2, actor='员工甲'))
    service.save_feedback(project, task, FeedbackInput(action='rated', rating=5, actor='员工甲'))
    restored = BetaTesting(service.store, service.canvas).feedback(project)
    assert len(restored) == 1
    assert restored[0]['rating'] == 5
    assert restored[0]['dismissedAt'] is None


def test_export_redacts_credentials_omits_inputs_and_contains_feedback_csv(env):
    service, project, task = env
    add_output(service, project, task)
    service.save_feedback(project, task, FeedbackInput(action='rated', rating=3, actor='=DANGEROUS_FORMULA()'))
    service.usage(UsageInput(event='artifact_view', projectId=project, taskId=task))
    logs = service.store.workspace_root / 'logs'
    logs.mkdir()
    (logs / 'api.log').write_text('Authorization: Bearer sk-secret123456789\nurl=https://example.test/image?token=PRIVATE\ndata:image/png;base64,SECRET_MEDIA\n')
    (service.store.workspace_root / 'private-material.txt').write_text('DO_NOT_EXPORT')
    with zipfile.ZipFile(io.BytesIO(service.export())) as archive:
        contents = '\n'.join(archive.read(name).decode('utf-8') for name in archive.namelist())
        for secret in ['NEVER_EXPORT', 'sk-secret123456789', 'PRIVATE', 'SECRET_MEDIA', 'DO_NOT_EXPORT']:
            assert secret not in contents
        summary = json.loads(archive.read('summary.json'))
        assert summary['ratingDistribution']['3'] == 1
        assert summary['averageRating'] == 3
        assert "'=DANGEROUS_FORMULA()" in archive.read('feedback.csv').decode('utf-8-sig')
        assert 'catalog.sqlite' not in archive.namelist()
        feedback = json.loads(archive.read('feedback.jsonl'))
        assert json.loads(feedback['output_ids'])
        assert feedback['task_status'] == 'queued'
        assert json.loads(archive.read('tasks.jsonl'))['prompt'] == '请设计礼盒'


def test_common_secrets_and_home_paths_are_redacted():
    assert redact({'api_key':'secret-value', 'model':'test'}) == {'api_key':'[REDACTED]', 'model':'test'}
    assert 'abc123' not in redact('api_key="abc123" password=abc123')
    assert 'private' not in redact('https://user:private@example.test/path?sig=private')


def test_testing_endpoints_export_valid_zip_and_reject_invalid_events(tmp_path, monkeypatch):
    monkeypatch.setenv('AICS_WORKSPACE_ROOT', str(tmp_path))
    with TestClient(app) as client:
        assert client.post('/api/testing/events', json={'event':'page_view', 'page':'schedules'}).status_code == 200
        assert client.post('/api/testing/events', json={'event':'arbitrary', 'data':'hidden'}).status_code == 422
        response = client.get('/api/testing/export')
        assert response.status_code == 200
        assert response.headers['content-type'] == 'application/zip'
        assert zipfile.is_zipfile(io.BytesIO(response.content))
