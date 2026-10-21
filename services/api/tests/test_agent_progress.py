import json
import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from test_delivery_contract import workspace, task
from app.task_runtime import TaskRuntime


@pytest.mark.parametrize('api,mode', [('responses','complete'),('responses','tool'),('responses','interrupted'),('responses','truncated_tool'),('responses','failed'),('chat_completions','complete'),('chat_completions','tool'),('chat_completions','interrupted'),('chat_completions','no_terminal'),('chat_completions','truncated_tool')])
def test_sdk_public_text_finishes_each_response_or_reports_interruption(api, mode):
    root = Path(__file__).resolve().parents[1]
    payload = {'api':api,'model':'fixture','apiKey':'fixture','baseUrl':'http://fixture.invalid/v1',
               'context':{'projectId':'one','taskId':'current','brief':'修改引用的配色',
                          'constraints':{'agentCollaboration':False,'executionFlow':'direct'}}}
    result = subprocess.run([shutil.which('node'),'--import',str(root/'tests/fixtures/progress_transport.mjs'),str(root/'app/openai_agent_worker.mjs')],
                            input=json.dumps(payload),text=True,capture_output=True,timeout=30,
                            env={**os.environ,'PROGRESS_FIXTURE':mode})
    events = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
    public = [event for event in events if event['type']=='event']
    texts = [event['message'] for event in public if event.get('phase')=='text']
    # Fast local streams may coalesce the first two deltas before the UI's
    # 100 ms publish interval. Validate the public content contract rather
    # than depending on one exact partial-chunk length.
    assert texts and all(text.strip() for text in texts)
    assert 'PRIVATE_REASONING_SENTINEL' not in json.dumps(public)
    if mode in {'interrupted','no_terminal','truncated_tool','failed'}:
        assert result.returncode != 0
        assert any('中断' in event.get('message','') for event in public)
        assert any(event.get('phase')=='narration' and event['message']==texts[0] for event in public)
        assert not any(event['type']=='result' for event in events)
        error=next(event for event in events if event['type']=='error')
        assert error['kind']==('provider' if mode in {'failed','no_terminal'} else 'configuration')
        assert error['submitted'] is True and error['billingCertainty']=='unknown'
        assert not any(event.get('phase')=='tool' for event in public)
        if api=='responses':
            assert error['recovery']['responseCount']==1
            assert error['recovery']['usage']['requests']==1
            assert len([e for e in events if e['type']=='usage'])==1
    else:
        assert result.returncode == 0, result.stderr + result.stdout[-5000:]
        assert texts[-1] == '配色修改已完成，可以在右侧画布查看。'
        assert next(event['result']['structured_data']['answer'] for event in events if event['type']=='result') == texts[-1]
        if mode == 'tool':
            preamble = '我会基于引用图像修改配色，并保留原有构图。'
            assert any(event.get('phase')=='narration' and event['message']==preamble for event in public)
            assert any(event.get('phase')=='progress' and event['message']==preamble for event in public)
            assert not any(preamble in value and '配色修改已完成' in value for value in texts)


def test_trace_preserves_public_text_through_many_tools_and_reopening(workspace):
    store, project, *_ = workspace
    task(store, project)
    runtime = TaskRuntime(store)
    long_text = '我会保留原图构图，并调整配色。'*200
    runtime._append_trace('task','text',long_text)
    runtime._append_trace('task','narration','正在等待图像服务返回。')
    for index in range(110):
        runtime._append_trace('task','tool',f'工具完成：canvas_read · {index}')
    trace = TaskRuntime(store).get_task(project,'task')['trace']
    assert next(e['message'] for e in trace if e['phase']=='text') == long_text
    assert any(e['phase']=='narration' for e in trace)
    assert len([e for e in trace if e['phase']=='tool']) == 80
    runtime._append_trace('task','text','修改已完成。')
    trace = runtime.get_task(project,'task')['trace']
    assert [e['message'] for e in trace if e['phase']=='text'] == ['修改已完成。']


def test_concurrent_progress_updates_do_not_overwrite_each_other(workspace):
    store, project, *_ = workspace
    task(store, project)
    runtime = TaskRuntime(store)
    with ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(lambda n: runtime._append_trace('task','tool',f'event-{n}'),range(40)))
    trace = runtime.get_task(project,'task')['trace']
    assert {event['message'] for event in trace} == {f'event-{n}' for n in range(40)}


def test_cache_totals_and_native_failure_survive_refresh_and_local_compaction_traffic(workspace):
    store, project, *_ = workspace
    task(store,project)
    runtime=TaskRuntime(store)
    runtime._append_trace('task','context_compaction','失败后使用本地精简',{'mode':'native','status':'failed','attempted':True,'succeeded':False,'reason':'本任务不再重试'})
    runtime._append_trace('task','model_call','完成',{'totalModelCalls':80,'cacheReportedCalls':70,'cacheObservedInputTokens':8000,
        'totalCachedTokens':4000,'totalCacheWriteTokens':2000,'cacheWriteReportedCalls':70,'prompt':'must-not-save','apiKey':'secret'})
    for index in range(110):
        runtime._append_trace('task','context_compaction','本地精简',{'mode':'local','status':'succeeded','estimated':True,'beforeTokens':24000,'afterTokens':8000})
    trace=TaskRuntime(store).get_task(project,'task')['trace']
    assert any(e.get('data',{}).get('reason')=='本任务不再重试' for e in trace)
    assert next(e['data'] for e in trace if e['phase']=='model_call')['totalCacheWriteTokens'] == 2000
    assert 'must-not-save' not in json.dumps(trace) and 'secret' not in json.dumps(trace)
