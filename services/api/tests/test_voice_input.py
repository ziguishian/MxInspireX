from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock, patch
import pytest
from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers
from app.voice_input import voice_input, configuration


def state():
    return SimpleNamespace(model_catalog=SimpleNamespace(settings=lambda: SimpleNamespace(preferredTextProvider=SimpleNamespace(key='test', baseUrl='https://example.test/v1')), get=lambda *a: {'modelCatalog': [{'id': 'whisper-1'}]}), providers=SimpleNamespace(text=lambda *a, **k: SimpleNamespace(base_url='https://example.test/v1'), credentials=SimpleNamespace(get=lambda k: 'secret')), billing=SimpleNamespace(record=Mock()))


def recording():
    return UploadFile(BytesIO(b'recording'), filename='dictation', headers=Headers({'content-type': 'audio/webm;codecs=opus'}))


def test_dictation_single_call_returns_text_and_records_usage():
    current = state()
    with patch('app.voice_input.urllib.request.urlopen') as send:
        send.return_value.__enter__.return_value.read.return_value = b'{"text":"hello","duration":2}'
        assert voice_input(SimpleNamespace(app=SimpleNamespace(state=current)), recording()) == {'text': 'hello'}
        assert send.call_count == 1
        assert b'recording' in send.call_args.args[0].data
        current.billing.record.assert_called_once()


def test_interruption_does_not_retry():
    current = state()
    with patch('app.voice_input.urllib.request.urlopen', side_effect=TimeoutError) as send:
        with pytest.raises(HTTPException, match='未自动重试'):
            voice_input(SimpleNamespace(app=SimpleNamespace(state=current)), recording())
        assert send.call_count == 1
        assert current.billing.record.call_args.kwargs['completed'] is False


def test_no_model_blocks_before_upload():
    current = state()
    current.model_catalog.get = lambda *a: {'modelCatalog': []}
    with pytest.raises(HTTPException, match='未配置转写模型'):
        configuration(current)
