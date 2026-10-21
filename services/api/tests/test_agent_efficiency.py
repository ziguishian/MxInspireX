import json

import pytest

from app.agent_sessions import AgentSessionStore
from app.conversation_memory import ConversationMemoryService
from test_conversation_memory import workspace, turn, picture, update, fact


def test_first_turn_empty_selection_is_local_idempotent_and_can_still_save_facts(workspace):
    turn(workspace, 'current', '生成一个陶瓷杯，主色蓝色')
    service = ConversationMemoryService(workspace)
    state = service.prepare_empty_selection('one', 'current')
    assert state['analyzed'] and state['analysisMode'] == 'empty_catalog'
    assert state['selected'] == [] and state['referenceSnapshots'] == []
    assert service.prepare_empty_selection('one', 'current') == state
    service.validate_generation('one', 'current', {'prompt': '陶瓷杯'})
    saved = update(service, 'current', [fact('蓝色', '主色蓝色')], ['brand.color'])
    assert saved['state']['selected'][0]['content'] == '蓝色'
    with workspace._connect() as db:
        assert json.loads(db.execute('SELECT input_json FROM tasks WHERE id=?', ('current',)).fetchone()[0])['userMessage'] == '生成一个陶瓷杯，主色蓝色'


@pytest.mark.parametrize('condition', ['history', 'reference', 'file', 'plan', 'recovery'])
def test_empty_selection_never_bypasses_existing_context(workspace, condition):
    extra = {}
    if condition == 'history':
        turn(workspace, 'previous', '品牌是蓝色')
    elif condition == 'reference':
        asset = picture(workspace, source='input-reference')
        extra['referencedAssets'] = [{'id': asset['id']}]
    elif condition == 'file':
        extra['referencedFiles'] = [{'documentId': 'brief'}]
    elif condition == 'plan':
        extra['planBaseline'] = {'ready': True}
    turn(workspace, 'current', '生成陶瓷杯', **extra)
    service = ConversationMemoryService(workspace)
    if condition == 'recovery':
        saved = update(service, 'current', selected=[])
        assert service.prepare_empty_selection('one', 'current') == saved['state']
    else:
        assert not service.prepare_empty_selection('one', 'current')['analyzed']


def test_session_images_are_deduplicated_losslessly_with_transaction_guards(workspace):
    turn(workspace, 'current', '使用这张参考')
    sessions = AgentSessionStore(workspace)
    call = lambda action, **kw: sessions.dispatch('one', 'current', {'action': action, **kw})
    start = call('acquire')
    image = 'data:image/png;base64,' + 'YWJj' * 25000
    item = {'type': 'message', 'role': 'user', 'content': [
        {'type': 'input_image', 'image': image},
        {'type': 'input_text', 'text': '保留蓝色'},
        {'_aics_session_blob': 'literal-not-a-reference'},
    ]}
    tx = {'type': 'append_items', 'items': [item, item]}
    args = dict(transaction=tx, operationId='append', revision=start['revision'])
    committed = call('mutate', **args)
    assert call('mutate', **args)['replayed']
    assert call('get')['items'] == [item, item]
    assert call('archive')['items'] == [item, item]
    with workspace._connect() as db:
        assert db.execute('SELECT count(*) FROM sdk_session_blobs').fetchone()[0] == 1
        assert len(db.execute('SELECT items FROM sdk_sessions').fetchone()[0]) < 1000
    with pytest.raises(ValueError, match='内容发生变化'):
        call('mutate', **{**args, 'transaction': {'type': 'append_items', 'items': [item]}})
    with pytest.raises(ValueError, match='版本发生变化'):
        call('mutate', **{**args, 'operationId': 'stale'})
    # Replacement archives use the same blob, and archive reads rehydrate it.
    call('mutate', transaction={'type': 'replace', 'items': [{'type': 'compaction', 'encrypted_content': 'opaque'}]},
         operationId='compact', revision=committed['revision'])
    assert call('archive')['items'] == [item, item]
    assert call('get')['items'][0]['encrypted_content'] == 'opaque'
    with pytest.raises(ValueError, match='不属于'):
        sessions.dispatch('two', 'current', {'action': 'get'})


def test_legacy_session_migrates_once_and_reads_do_not_need_write_lock(workspace):
    turn(workspace, 'current', '继续')
    sessions = AgentSessionStore(workspace)
    item = {'type': 'message', 'role': 'user', 'content': [{'type': 'input_image', 'image': 'data:image/png;base64,YQ=='}]}
    old = json.dumps([item])
    with workspace._connect() as db:
        db.execute('INSERT INTO sdk_sessions(id,project_id,items,revision) VALUES(?,?,?,7)', ('project:one', 'one', old))
        db.execute('INSERT INTO sdk_session_raw VALUES(?,?)', ('project:one', old))
        db.execute('INSERT INTO sdk_session_archive VALUES(?,?,?)', ('project:one', 6, old))
    call = lambda **kw: sessions.dispatch('one', 'current', {'action': 'get', **kw})
    assert call()['items'] == [item]
    with workspace._connect() as db:
        assert db.execute('SELECT storage_version,revision FROM sdk_sessions').fetchone()[:] == (1, 7)
        assert db.execute('SELECT count(*) FROM sdk_session_blobs').fetchone()[0] == 1
        assert 'data:image' not in db.execute('SELECT items FROM sdk_session_archive').fetchone()[0]
        db.execute('BEGIN IMMEDIATE')
        # The HTTP route creates a fresh adapter per call; initialization must
        # also stay read-only once the schema exists.
        assert AgentSessionStore(workspace).dispatch('one', 'current', {'action': 'get'})['items'] == [item]
        assert call(limit=0)['items'] == []
    assert AgentSessionStore(workspace).dispatch('one', 'current', {'action': 'archive'})['items'] == [item]


def test_session_failed_suffix_rolls_back_blob_and_history(workspace):
    turn(workspace, 'current', '继续')
    sessions = AgentSessionStore(workspace)
    sessions.dispatch('one', 'current', {'action': 'acquire'})
    with pytest.raises(ValueError, match='尾部'):
        sessions.dispatch('one', 'current', {'action': 'mutate', 'operationId': 'bad', 'revision': 0,
            'transaction': {'type': 'replace_suffix', 'expectedSuffix': [{'role': 'user', 'content': 'missing'}],
                            'replacement': [{'role': 'user', 'content': 'data:image/png;base64,Yg=='}]}})
    with workspace._connect() as db:
        assert db.execute('SELECT count(*) FROM sdk_session_blobs').fetchone()[0] == 0
    assert sessions.dispatch('one', 'current', {'action': 'get'})['revision'] == 0
