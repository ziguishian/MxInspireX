import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.design_runtime import DesignRuntime, DesignRuntimeError
from app.providers.registry import ProviderRegistry


def registry():
    return SimpleNamespace(credentials=SimpleNamespace(get=lambda _: 'fixture-key'), billing=None, list=lambda: [])


def run(runtime, **options):
    return runtime.run(project_id='project', task_id='review', agent_key='design', workflow_step='design',
                       brief='检查已有视频', constraints={'deliveryReviewOnly': True}, retrieved_context=[], research_sources=[],
                       attachments=[], prior_outputs=[], provider_ref={'key': 'openrouter', 'model': 'fixture', 'api': 'chat_completions'}, **options)


def test_review_starts_after_inherited_app_directory_is_deleted_and_recreated(tmp_path):
    """Reproduce the running sidecar surviving a release directory replacement."""
    worker = tmp_path / 'worker.mjs'
    worker.write_text("import fs from 'node:fs'; fs.readFileSync(0, 'utf8'); console.log(JSON.stringify({type:'result', result:{status:'succeeded',structured_data:{answer:process.cwd()},provenance:{modelRequestCount:0}}}));")
    script = '''
import os, shutil, sys
from pathlib import Path
from types import SimpleNamespace
from app.design_runtime import DesignRuntime
base=Path(sys.argv[1]); old=base/'replaced-app'; old.mkdir(); os.chdir(old)
shutil.rmtree(old); old.mkdir()
try: os.getcwd()
except FileNotFoundError: pass
else: raise AssertionError('fixture must leave an unlinked inherited cwd')
registry=SimpleNamespace(credentials=SimpleNamespace(get=lambda _: 'fixture-key'), billing=None, list=lambda: [])
runtime=DesignRuntime(registry,node_path=sys.argv[2],worker_path=base/'worker.mjs',runtime_root=base/'runs')
result=runtime.run(project_id='project',task_id='review',agent_key='design',workflow_step='design',brief='review',constraints={'deliveryReviewOnly':True},retrieved_context=[],research_sources=[],attachments=[],prior_outputs=[],provider_ref={'key':'openrouter','model':'fixture','api':'chat_completions'})
assert result.structured_data['answer']==str(base/'runs/review')
print('review completed from isolated cwd')
'''
    api = str(Path(__file__).resolve().parents[1])
    result = subprocess.run([sys.executable, '-c', script, str(tmp_path), shutil.which('node') or 'node'],
                            env={**os.environ, 'PYTHONPATH': api, 'AICS_NODE_RUN_AS_NODE': '0'}, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert 'review completed' in result.stdout


def test_missing_node_is_a_local_runtime_error_not_a_provider_failure(tmp_path):
    worker = tmp_path / 'worker.mjs'; worker.write_text('// fixture')
    runtime = DesignRuntime(registry(), node_path=str(tmp_path/'missing-node'), worker_path=worker, runtime_root=tmp_path/'runs')
    with pytest.raises(DesignRuntimeError, match='Node.js 启动程序不存在') as error:
        run(runtime)
    assert error.value.kind == 'runtime' and not error.value.retryable


def test_ollama_runtime_uses_local_placeholder_key_and_skips_billing(tmp_path):
    worker = tmp_path / 'worker.mjs'
    worker.write_text("""
import fs from 'node:fs';
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
console.log(JSON.stringify({type:'usage',sequence:1,role:'design',usage:{input_tokens:4,output_tokens:2}}));
console.log(JSON.stringify({type:'result',result:{status:'succeeded',structured_data:{provider:input.provider,model:input.model,baseUrl:input.baseUrl,apiKey:input.apiKey,api:input.api},provenance:{modelRequestCount:1}}}));
""")
    class NoCredentials:
        def get(self, _key): return None
    billing = SimpleNamespace(record=lambda **_kwargs: pytest.fail('local Ollama usage must not enter billing'))
    providers = ProviderRegistry(credentials=NoCredentials())
    providers.billing = billing
    runtime = DesignRuntime(providers, node_path=shutil.which('node'), worker_path=worker, runtime_root=tmp_path/'runs')
    result = runtime.run(project_id='project', task_id='ollama', agent_key='design', workflow_step='design', brief='hello', constraints={}, retrieved_context=[], research_sources=[], attachments=[], prior_outputs=[], provider_ref={'key':'ollama','model':'gpt-oss:20b','api':'chat_completions'})
    assert result.structured_data == {
        'provider': 'ollama', 'model': 'gpt-oss:20b',
        'baseUrl': 'http://127.0.0.1:11434/v1', 'apiKey': 'ollama', 'api': 'chat_completions',
    }


def test_missing_working_directory_is_not_reported_as_missing_node(tmp_path):
    worker = tmp_path / 'worker.mjs'; worker.write_text('// fixture')
    runtime = DesignRuntime(registry(), node_path=shutil.which('node') or 'node', worker_path=worker, runtime_root=tmp_path/'runs')
    def remove_before_launch(*args, **kwargs):
        shutil.rmtree(kwargs['cwd'])
        raise FileNotFoundError(2, 'No such file or directory', kwargs['cwd'])
    with patch('app.design_runtime.subprocess.Popen', side_effect=remove_before_launch):
        with pytest.raises(DesignRuntimeError, match='任务工作目录不存在') as error:
            run(runtime)
    assert 'Node.js 启动程序不存在' not in str(error.value)


def test_legacy_node_error_can_be_identified_without_enabling_provider_retries():
    error = DesignRuntimeError('找不到 Node.js：/old/App.app/Contents/MacOS/LangjuAgent')
    assert error.kind == 'runtime' and not error.retryable


def test_legacy_deadlines_do_not_kill_a_running_worker(tmp_path, monkeypatch):
    worker = tmp_path / 'worker.mjs'
    worker.write_text("""
import fs from 'node:fs';
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
if ('timeout' in input.executionPolicy) throw new Error('legacy deadline reached worker');
await new Promise(resolve => setTimeout(resolve, 150));
console.log(JSON.stringify({type:'result',result:{status:'succeeded',structured_data:{answer:'completed after old deadline'},provenance:{modelRequestCount:0}}}));
""")
    monkeypatch.setenv('AICS_AGENT_TIMEOUT_SECONDS', '0.01')
    runtime = DesignRuntime(registry(), node_path=shutil.which('node'), worker_path=worker, runtime_root=tmp_path/'runs', timeout_seconds=.01)
    result = run(runtime, execution_policy={'timeout':.01})
    assert result.structured_data['answer'] == 'completed after old deadline'


def test_unlimited_worker_still_stops_and_preserves_checkpoint(tmp_path):
    import time
    worker = tmp_path / 'worker.mjs'
    worker.write_text("""
import fs from 'node:fs'; fs.readFileSync(0, 'utf8');
console.log(JSON.stringify({type:'checkpoint',recovery:{stages:{design:'saved output'}}}));
console.log(JSON.stringify({type:'event',phase:'progress',message:'ready to stop'}));
setInterval(() => {}, 1000);
""")
    ready = []
    runtime = DesignRuntime(registry(), node_path=shutil.which('node'), worker_path=worker, runtime_root=tmp_path/'runs')
    start = time.monotonic()
    with pytest.raises(DesignRuntimeError, match='任务已停止') as error:
        run(runtime, trace=lambda *event: ready.append(event), should_cancel=lambda: bool(ready) or time.monotonic()-start > 3)
    assert ready
    assert error.value.kind == 'interrupted'
    assert error.value.recovery['stages']['design'] == 'saved output'
    assert time.monotonic()-start < 3


def test_protocol_rejects_three_malformed_jsonl_frames_with_redacted_diagnostics(tmp_path):
    worker = tmp_path / 'worker.mjs'
    worker.write_text("""
import fs from 'node:fs'; fs.readFileSync(0, 'utf8');
console.log('not-json');
console.log('[]');
console.log(JSON.stringify({type:'mystery',secret:'must-not-be-recorded'}));
""")
    runtime = DesignRuntime(registry(), node_path=shutil.which('node'), worker_path=worker, runtime_root=tmp_path/'runs')
    with pytest.raises(DesignRuntimeError, match='连续出现 3 个非法') as error:
        run(runtime)
    assert error.value.kind == 'runtime'
    diagnostics = error.value.recovery['protocolDiagnostics']
    assert len(diagnostics) == 3
    assert all(set(item) == {'reason', 'byteLength', 'sha256'} for item in diagnostics)
    assert 'must-not-be-recorded' not in json.dumps(diagnostics)


def test_protocol_rejects_duplicate_final_result(tmp_path):
    worker = tmp_path / 'worker.mjs'
    result = "{type:'result',result:{status:'succeeded',structured_data:{answer:'ok'},provenance:{modelRequestCount:0}}}"
    worker.write_text(f"import fs from 'node:fs'; fs.readFileSync(0, 'utf8'); const value={result}; console.log(JSON.stringify(value)); console.log(JSON.stringify(value));")
    runtime = DesignRuntime(registry(), node_path=shutil.which('node'), worker_path=worker, runtime_root=tmp_path/'runs')
    with pytest.raises(DesignRuntimeError, match='重复的最终结果') as error:
        run(runtime)
    assert error.value.kind == 'runtime'


def test_protocol_stall_notice_and_recoverable_timeout(tmp_path, monkeypatch):
    import time
    worker = tmp_path / 'worker.mjs'
    worker.write_text("import fs from 'node:fs'; fs.readFileSync(0, 'utf8'); setInterval(() => {}, 1000);")
    monkeypatch.setenv('AICS_AGENT_STALL_NOTICE_SECONDS', '0.1')
    monkeypatch.setenv('AICS_AGENT_PROTOCOL_TIMEOUT_SECONDS', '0.25')
    events = []
    runtime = DesignRuntime(registry(), node_path=shutil.which('node'), worker_path=worker, runtime_root=tmp_path/'runs')
    started = time.monotonic()
    with pytest.raises(DesignRuntimeError, match='没有返回有效协议事件') as error:
        run(runtime, trace=lambda *event: events.append(event))
    assert error.value.kind == 'execution_timeout'
    assert error.value.recovery['runtimeState']['status'] == 'execution_timeout'
    assert [event[0] for event in events].count('stalled') == 1
    assert time.monotonic() - started < 3
