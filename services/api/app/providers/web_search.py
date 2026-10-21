"""Bounded bridge to hosted search tools run by the OpenAI Agents SDK."""
from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass

from .http import ProviderError
from ..research import ResearchImportError, safe_source_uri


class WebSearchError(ProviderError):
    def __init__(self, message, *, status_code=None, stop_tool=False, rejected=False):
        super().__init__(message, status_code=status_code)
        self.stop_tool, self.rejected = stop_tool, rejected


@dataclass
class OpenAIWebSearchProvider:
    base_url: str
    provider_key: str
    model: str
    credentials: object
    api: str = 'auto'
    timeout: float = 60
    max_output_tokens: int = 2048

    def search(self, query: str, *, limit: int = 8, progress=None, should_cancel=None):
        from ..design_runtime import resolve_worker_path
        self.last_response, self.search_calls = {}, None
        secret = self.credentials.get(self.provider_key)
        if not secret:
            raise WebSearchError('SDK 原生搜索服务尚未配置 API Key', stop_tool=True, rejected=True)
        if self.api == 'chat_completions':
            raise WebSearchError('SDK 原生搜索需要 Responses 接口，请将搜索接口改为 Responses。', stop_tool=True, rejected=True)
        payload = dict(operation='web_search', apiKey=secret, baseUrl=self.base_url, provider=self.provider_key, model=self.model,
                       query=query, limit=limit, timeoutSeconds=self.timeout, maxOutputTokens=self.max_output_tokens)
        worker = resolve_worker_path()
        events = queue.Queue()
        started = time.monotonic()
        result = None
        process = None
        readers = []
        def drain(stream, stdout):
            try:
                for line in stream:
                    if stdout: events.put(line)
            finally:
                if stdout: events.put(None)
        try:
            process = subprocess.Popen([os.getenv('AICS_NODE') or shutil.which('node') or 'node', str(worker)],
                cwd=str(worker.parent), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding='utf-8', env={**os.environ, **({'ELECTRON_RUN_AS_NODE':'1'} if os.getenv('AICS_NODE_RUN_AS_NODE') == '1' else {})},
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            readers = [threading.Thread(target=drain,args=(process.stdout,True),daemon=True),
                       threading.Thread(target=drain,args=(process.stderr,False),daemon=True)]
            for reader in readers: reader.start()
            process.stdin.write(json.dumps(payload, ensure_ascii=False)+'\n')
            process.stdin.close()
            while True:
                if should_cancel and should_cancel():
                    raise WebSearchError('任务已停止，SDK 搜索已取消', stop_tool=True)
                remaining = self.timeout + 1 - (time.monotonic()-started)
                if remaining <= 0:
                    raise WebSearchError(f'SDK 原生搜索超过总时限（{self.timeout:g} 秒），已停止本轮重复搜索。', stop_tool=True)
                try: line = events.get(timeout=min(.1, remaining))
                except queue.Empty: continue
                if line is None: break
                event = json.loads(line)
                if event.get('type') == 'progress' and progress: progress(event['message'])
                elif event.get('type') == 'usage':
                    self.last_response['usage'] = event.get('usage') or {}
                    if 'searchCalls' in event: self.search_calls = event['searchCalls']
                elif event.get('type') == 'result': result = event['result']
                elif event.get('type') == 'error':
                    raise WebSearchError(str(event['message']).replace(secret,'[REDACTED]'), status_code=event.get('statusCode'),
                                         stop_tool=event.get('stopTool',True), rejected=event.get('rejected',False))
            if not result:
                raise WebSearchError('SDK 原生搜索执行中断，未返回完整结果；本轮不重复提交。', stop_tool=True)
            sources = []
            for source in result.get('sources', []):
                try: uri = safe_source_uri(source.get('url',''))
                except (ResearchImportError, ValueError, TypeError): continue
                sources.append({'url':uri,'title':str(source.get('title') or uri)[:300]})
            if not sources:
                raise WebSearchError('SDK 原生搜索未返回可核验的公开来源；本轮停止重复搜索。', stop_tool=True)
            return {**result, 'sources':sources[:limit]}
        except (OSError, ValueError) as error:
            raise WebSearchError('SDK 搜索运行环境异常或响应无效，请检查本地 Node 运行环境。', stop_tool=True) from error
        finally:
            if process:
                if process.poll() is None:
                    process.terminate()
                    try: process.wait(timeout=1)
                    except subprocess.TimeoutExpired: process.kill(); process.wait()
                for reader in readers: reader.join(timeout=1)
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream and not stream.closed: stream.close()
