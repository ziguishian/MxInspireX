"""Real HTTP/SSE shutdown and restart, with an isolated, non-network Agent."""
import json
import os
from pathlib import Path
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.request

import pytest


SERVER = r'''
import os, time, sys, signal, threading
from types import SimpleNamespace
import uvicorn
from app import main
from app.agent_contracts import AgentResult
from app.design_runtime import DesignRuntimeError
from app.server import StudioServer
OriginalRuntime = main.TaskRuntime
class IsolatedRuntime(OriginalRuntime):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        def simulate(**options):
            options['trace']('agent_started', '隔离任务已开始')
            if os.environ['RECOVERY_TEST_MODE'] == 'wait':
                while not options['should_cancel'](): time.sleep(.02)
                raise DesignRuntimeError('服务重启', kind='interrupted')
            return AgentResult(status='succeeded', structured_data={'answer': '恢复完成'})
        self.design_runtime = SimpleNamespace(run=simulate)
main.TaskRuntime = IsolatedRuntime
# Windows Popen.send_signal(SIGTERM) uses TerminateProcess and cannot exercise
# graceful handlers. Deliver a Python signal after the server has started.
if os.name == 'nt':
    def control():
        if sys.stdin.readline().strip() == 'shutdown': signal.raise_signal(signal.SIGTERM)
    threading.Thread(target=control, daemon=True).start()
server_class = StudioServer if os.environ['RECOVERY_SERVER_KIND'] == 'studio' else uvicorn.Server
server_class(uvicorn.Config(main.app, host='127.0.0.1', port=int(os.environ['RECOVERY_TEST_PORT']), log_level='warning')).run()
'''


def eventually(check, timeout=12):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = check()
            if value: return value
        except (OSError, ValueError):
            pass
        time.sleep(.05)
    raise AssertionError('Timed out waiting for the isolated API')


@pytest.mark.parametrize('server_kind', ['studio', 'stock'])
def test_signal_closes_active_sse_and_restart_recovers_same_task(tmp_path, server_kind):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    base = f'http://127.0.0.1:{port}'
    env = {**os.environ, 'AICS_WORKSPACE_ROOT': str(tmp_path / 'workspace'), 'AICS_TEST_MODE': '1',
           'RECOVERY_TEST_PORT': str(port), 'RECOVERY_SERVER_KIND': server_kind}
    processes = []
    stream_opened, stream_closed = threading.Event(), threading.Event()
    def request(path, data=None):
        req = urllib.request.Request(base + path, data=json.dumps(data).encode() if data is not None else None,
                                     headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=2) as response:
            return json.load(response)
    def start(mode):
        process = subprocess.Popen([sys.executable, '-c', SERVER], cwd=Path(__file__).resolve().parents[1],
            env={**env, 'RECOVERY_TEST_MODE': mode}, stdin=subprocess.PIPE, text=True, encoding='utf-8', stdout=subprocess.DEVNULL, stderr=log)
        processes.append(process)
        eventually(lambda: request('/health'))
        return process
    with (tmp_path / 'server.log').open('w') as log:
        try:
            first = start('wait')
            project = request('/api/projects', {'name': '重启验收'})
            route = f"/api/projects/{project['id']}/tasks"
            initial = request(route, {'brief': '你好', 'async': True})
            task_url = route + '/' + initial['id']
            eventually(lambda: request(task_url)['status'] == 'running')
            def consume_stream():
                try:
                    with urllib.request.urlopen(base + task_url + '/events', timeout=8) as response:
                        if response.readline(): stream_opened.set()
                        response.read()
                except OSError:
                    pass
                finally:
                    stream_closed.set()
            thread = threading.Thread(target=consume_stream, daemon=True)
            thread.start()
            assert stream_opened.wait(3)
            if os.name == 'nt':
                first.stdin.write('shutdown\n')
                first.stdin.flush()
            else:
                first.send_signal(signal.SIGTERM)
            first.wait(timeout=8)
            assert stream_closed.wait(1)
            with sqlite3.connect(tmp_path / 'workspace' / 'catalog.sqlite') as db:
                state = db.execute('SELECT status,error_json FROM tasks WHERE id=?', (initial['id'],)).fetchone()
            assert state == ('queued', None)
            start('complete')
            eventually(lambda: request(task_url)['status'] == 'succeeded')
            assert len(request(route)) == 1
            assert request(task_url)['id'] == initial['id']
        finally:
            for process in processes:
                if process.poll() is None:
                    process.terminate()
                    try: process.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=2)
