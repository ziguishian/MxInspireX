import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.parametrize('api', ['responses', 'chat_completions'])
@pytest.mark.parametrize('resume', [False, True])
@pytest.mark.parametrize('failure_kind', ['format', 'timeout', 'streaming'])
def test_image_failure_stops_image_tool_and_preserves_reason(api, resume, failure_kind):
    root = Path(__file__).resolve().parents[1]
    code, message = {
        'format': ('image_output_format', '图像服务返回了 SVG'),
        'timeout': ('image_response_timeout', '等待图像响应超时，生成结果待确认'),
        'streaming': ('image_streaming_unsupported', '图像服务拒绝了流式响应模式，这不表示原图不支持编辑'),
    }[failure_kind]
    failure = {'tool':'generate_image','status':'failed','message':message,'errorCode':code,'stopTool':True,'retryable':False}
    payload = {'api':api,'model':'fixture','apiKey':'fixture','baseUrl':'http://fixture.invalid/v1',
               'toolGateway':{'baseUrl':'http://fixture.invalid','projectId':'fixture','taskId':'fixture'},
               'context':{'brief':'生成笔记本封面效果图','constraints':{'executionFlow':'direct','agentCollaboration':False}},
               'recovery':{'blockedTools':{'generate_image':failure},'toolOutputs':[{'name':'generate_image','args':{'prompt':'笔记本封面效果图'},'output':failure}]} if resume else {}}
    result = subprocess.run([shutil.which('node'),'--import',(root/'tests/fixtures/image_format_failure_transport.mjs').resolve().as_uri(),str(root/'app/openai_agent_worker.mjs')],
                            input=json.dumps(payload),text=True, encoding='utf-8',capture_output=True,timeout=30,
                            env={**os.environ,'FIXTURE_FORMAT_RESUME':'1' if resume else '0','FIXTURE_IMAGE_FAILURE':failure_kind})
    assert result.returncode == 0, result.stderr + result.stdout[-6000:]
    events = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
    assert any(e['type']=='result' for e in events)
    checkpoint = [e['recovery'] for e in events if e['type']=='checkpoint'][-1]
    assert checkpoint['blockedTools']['generate_image']['errorCode'] == code
    assert len(checkpoint['toolOutputs']) == 1


def test_validation_failure_cannot_consume_remaining_turns_without_corrected_tool_call():
    root = Path(__file__).resolve().parents[1]
    failure = {
        'tool':'generation_reference_check', 'status':'image_parameters_invalid',
        'instruction':'3840x1200 超过当前模型最大 3:1，请修正尺寸。',
    }
    payload = {
        'api':'responses', 'model':'fixture', 'apiKey':'fixture',
        'baseUrl':'http://fixture.invalid/v1',
        'toolGateway':{'baseUrl':'http://fixture.invalid','projectId':'fixture','taskId':'fixture'},
        'context':{'brief':'生成三比一背景','constraints':{'executionFlow':'direct','agentCollaboration':False}},
        # Both allowed correction rounds were already consumed. The persisted
        # signature must stop resume before another model request.
        'recovery':{
            'stageTurns':{'design':2},
            'recoveryAttempts':{'design':{'total':2,'signatures':{
                'validation:generation_reference_check:image_parameters_invalid:':{
                    'attempts':2,'lastTurn':1,'kind':'validation','tool':'generation_reference_check',
                    'code':'image_parameters_invalid','fieldPath':'',
                },
            }}},
            'toolOutputs':[{'name':'generation_reference_check','args':{},'stageTurn':1,'output':failure}],
        },
    }
    result = subprocess.run(
        [shutil.which('node'),'--import',(root/'tests/fixtures/image_format_failure_transport.mjs').resolve().as_uri(),str(root/'app/openai_agent_worker.mjs')],
        input=json.dumps(payload), text=True, encoding='utf-8', capture_output=True, timeout=30,
        env={**os.environ,'FIXTURE_FORMAT_RESUME':'1'},
    )
    assert result.returncode != 0
    events = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
    error = next(event for event in reversed(events) if event['type'] == 'error')
    assert error['kind'] == 'tool'
    assert '3840x1200' in error['message']
    assert error['recovery']['usage']['requests'] == 0
    assert not any(event['type'] == 'usage' for event in events)


def test_persisted_stage_recovery_cap_stops_before_another_model_request():
    root = Path(__file__).resolve().parents[1]
    failure = {
        'tool':'generation_reference_check', 'status':'image_parameters_invalid',
        'instruction':'请修正尺寸。',
    }
    payload = {
        'api':'responses', 'model':'fixture', 'apiKey':'fixture',
        'baseUrl':'http://fixture.invalid/v1',
        'toolGateway':{'baseUrl':'http://fixture.invalid','projectId':'fixture','taskId':'fixture'},
        'context':{'brief':'生成背景','constraints':{'executionFlow':'direct','agentCollaboration':False}},
        'recovery':{
            'stageTurns':{'design':7},
            'recoveryAttempts':{'design':{'total':6,'signatures':{}}},
            'toolOutputs':[{'name':'generation_reference_check','args':{},'stageTurn':7,'output':failure}],
        },
    }
    result = subprocess.run(
        [shutil.which('node'),'--import',(root/'tests/fixtures/image_format_failure_transport.mjs').resolve().as_uri(),str(root/'app/openai_agent_worker.mjs')],
        input=json.dumps(payload), text=True, encoding='utf-8', capture_output=True, timeout=30,
        env={**os.environ,'FIXTURE_FORMAT_RESUME':'1'},
    )
    assert result.returncode != 0
    events = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
    error = next(event for event in reversed(events) if event['type'] == 'error')
    assert error['kind'] == 'tool' and error['recovery']['recoveryAttempts']['design']['total'] == 6
    assert not any(event['type'] == 'usage' for event in events)
