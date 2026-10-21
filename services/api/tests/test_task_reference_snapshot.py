import json

import pytest

from app.task_runtime import TaskRuntime


def task_row(input_json):
    return dict(id='task', agent_key='design', workflow_step='design', status='succeeded',
                input_json=input_json, output_json=None, error_json=None, trace_json='[]',
                created_at='2026-09-12', updated_at='2026-09-12')


def test_history_includes_only_safe_reference_metadata():
    data = {'userMessage': '@1 看这张图', 'textProvider': {'apiKey': 'private'},
            'referencedFiles': [{'documentId': 'doc', 'filename': 'ref.png', 'mime': 'image/png', 'index': 1,
                                 'projectId': 'project', 'pathRelative': 'private/path', 'imageBase64': 'large-private-data'}],
            'referencedAssets': [{'id': 'asset', 'projectId': 'source', 'filename': 'image.png', 'secret': 'private'}],
            'referencedNodes': [{'id': 'node', 'projectId': 'project', 'content': 'private'}]}
    response = TaskRuntime._task_dict(task_row(json.dumps(data)))
    assert response['userMessage'] == data['userMessage']
    assert response['references'] == {
        'referencedFiles': [{'documentId': 'doc', 'filename': 'ref.png', 'mime': 'image/png', 'index': 1, 'projectId': 'project'}],
        'referencedAssets': [{'id': 'asset', 'projectId': 'source', 'filename': 'image.png'}],
        'referencedNodes': [{'id': 'node', 'projectId': 'project'}],
    }
    assert 'private' not in json.dumps(response)


@pytest.mark.parametrize('value', ['{}', 'null', '[]', 'malformed', '{"referencedFiles":"bad","referencedAssets":null}'])
def test_old_or_malformed_tasks_remain_readable(value):
    assert TaskRuntime._task_dict(task_row(value))['references'] == {}
