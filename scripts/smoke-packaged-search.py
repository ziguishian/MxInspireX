"""Exercise the frozen search API with local fixtures and an isolated workspace."""
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

requests = []
source = {'url': 'https://93.184.216.34/fixture', 'title': '本地测试引用'}


class Upstream(BaseHTTPRequestHandler):
    def log_message(self, *_): pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        requests.append(body)
        slow = 'slow-fixture' in json.dumps(body)
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.end_headers()
        try:
            if slow:
                for _ in range(40):
                    self.wfile.write(b': heartbeat\n\n'); self.wfile.flush(); time.sleep(.05)
                return
            assert 'plugins' not in body
            assert body['tools'][0]['type'] in ('web_search', 'openrouter:web_search')
            if body['tools'][0]['type'] == 'openrouter:web_search':
                assert not body.get('include')
                assert body['tools'][0]['parameters']['engine'] == 'native'
            call = {'id': 'search-1', 'type': 'web_search_call', 'status': 'completed', 'action': {'type': 'search', 'query': 'fixture'}}
            message = {'id': 'message-1', 'type': 'message', 'role': 'assistant', 'status': 'completed', 'content': [
                {'type': 'output_text', 'text': '可核验的测试结果', 'annotations': [{'type': 'url_citation', **source, 'start_index':0, 'end_index':9}]}]}
            response = {'id':'response-1', 'model':body['model'], 'object':'response', 'created_at':1, 'status':'completed', 'output':[call,message],
                        'usage': {'input_tokens':1,'output_tokens':1,'total_tokens':2,'cost':0,'server_tool_use_details':{'web_search_requests':1}}}
            events = [{'type':'response.created','response':{**response,'status':'in_progress','output':[]}},
                      {'type':'response.output_item.done','output_index':0,'item':call},
                      {'type':'response.output_item.done','output_index':1,'item':message},
                      {'type':'response.completed','response':response}]
            for event in events:
                self.wfile.write(('data: ' + json.dumps(event) + '\n\n').encode()); self.wfile.flush()
            self.wfile.write(b'data: [DONE]\n\n'); self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError): pass


release = Path(sys.argv[1]).resolve()
executable = release/'macos-arm64/MxinspireX.app/Contents/Resources/app/services/api/sidecar/aics-api/aics-api'
assert executable.is_file()
workspace = Path(tempfile.mkdtemp(prefix='langju-search-package-'))
upstream = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
threading.Thread(target=upstream.serve_forever, daemon=True).start()
with socket.socket() as sock:
    sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
base = f'http://127.0.0.1:{port}'
upstream_base = f'http://127.0.0.1:{upstream.server_port}/v1'
log = (workspace/'api.log').open('wb')
env = {**os.environ, 'AICS_WORKSPACE_ROOT': str(workspace), 'AICS_TEST_MODE': '1',
       'AICS_API_HOST': '127.0.0.1', 'AICS_API_PORT': str(port),
       'AICS_PROVIDER_KEY_OPENROUTER': 'fixture-only', 'AICS_PROVIDER_KEY_OPENAI_COMPATIBLE': 'fixture-only',
       'AICS_NODE':str(release/'macos-arm64/MxinspireX.app/Contents/MacOS/MxinspireX'), 'AICS_NODE_RUN_AS_NODE':'1',
       'NO_PROXY': '127.0.0.1,localhost', 'no_proxy': '127.0.0.1,localhost'}
process = subprocess.Popen([str(executable), '--host', '127.0.0.1', '--port', str(port)], env=env, stdout=log, stderr=log)
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def request(path, payload=None, task=None, method=None):
    headers = {'Content-Type': 'application/json'}
    if task: headers['x-aics-task-id'] = task
    req = urllib.request.Request(base+path, data=json.dumps(payload).encode() if payload is not None else None, headers=headers, method=method)
    try:
        with opener.open(req, timeout=8) as response: return response.status, json.load(response)
    except urllib.error.HTTPError as error: return error.code, json.load(error)


try:
    for _ in range(80):
        if process.poll() is not None: raise RuntimeError((workspace/'api.log').read_text()[-2000:])
        try:
            if request('/health')[0] == 200: break
        except OSError: pass
        time.sleep(.1)
    else: raise AssertionError('Frozen API did not start')
    status, project = request('/api/projects', {'name': '打包后搜索验证', 'brief': '仅本地模拟'})
    assert status in (200,201), project
    project_id = project['id']
    for key in ('openrouter', 'openai-compatible'):
        with sqlite3.connect(workspace/'catalog.sqlite') as db:
            db.execute('INSERT INTO model_catalogs VALUES (?,?,?,?)', (key, upstream_base, json.dumps({'models': ['gpt-5.6-terra']}), '2026-09-12'))
            for suffix in ('normal', 'slow'):
                task = f'{key}-{suffix}'
                payload = {'allowExternalNetwork': True, 'textProvider': {'key': key, 'baseUrl': upstream_base, 'model': 'gpt-5.6-terra'}}
                db.execute("INSERT INTO tasks (id,project_id,agent_key,workflow_step,status,input_json,created_at,updated_at) VALUES (?,?,'design','design','queued',?,'2026-09-12','2026-09-12')", (task,project_id,json.dumps(payload)))
        _, settings = request('/api/model-settings')
        settings['search']={'provider':key,'baseUrl':upstream_base,'model':'gpt-5.6-terra','api':'responses'}
        status, saved = request('/api/model-settings', settings, method='PUT')
        assert status == 200, saved
        status, data = request(f'/api/projects/{project_id}/agent-tools/web_search', {'query':'fixture'}, key+'-normal')
        assert status == 200 and data['sources'] == [source], (status,data)
        started = time.monotonic()
        status, data = request(f'/api/projects/{project_id}/agent-tools/web_search', {'query':'slow-fixture','_search_context':{'timeoutSeconds':1}}, key+'-slow')
        assert status == 422 and data['stopTool'] and time.monotonic()-started < 3, (status,data)
        count = len(requests)
        status, data = request(f'/api/projects/{project_id}/agent-tools/web_search', {'query':'rewritten-query'}, key+'-slow')
        assert status == 422 and len(requests) == count
    report = {'passed': True, 'localFixtureOnly': True, 'upstreamRequests': len(requests), 'workspace': str(workspace),
              'checks': ['frozen Agents SDK worker via Electron Node', 'OpenRouter hosted tool', 'compatible native webSearchTool', 'heartbeat hard deadline', 'closed request is not replayed']}
    print(json.dumps(report))
finally:
    process.terminate()
    try: process.wait(timeout=8)
    except subprocess.TimeoutExpired: process.kill(); process.wait()
    log.close(); upstream.shutdown(); upstream.server_close()
