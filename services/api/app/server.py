"""Studio server: stop Agent loops before shutting down their HTTP tools."""
import argparse
import os
import signal
import threading
from pathlib import Path

import uvicorn
from uvicorn.supervisors import ChangeReload


def install_shutdown_hook(runtime):
    """Also support users who launch the app through uvicorn's stock CLI."""
    if threading.current_thread() is not threading.main_thread(): return lambda: None
    installed = []
    for sig in (signal.SIGINT, signal.SIGTERM):
        previous = signal.getsignal(sig)
        owner = getattr(previous, '__self__', None)
        if not isinstance(owner, uvicorn.Server): continue
        owner.config.timeout_graceful_shutdown = 5
        def handler(signum, frame, original=previous):
            runtime.prepare_shutdown()
            original(signum, frame)
        signal.signal(sig, handler)
        installed.append((sig, previous, handler))
    def restore():
        for sig, previous, handler in installed:
            if signal.getsignal(sig) is handler: signal.signal(sig, previous)
    return restore


class StudioServer(uvicorn.Server):
    def handle_exit(self, sig, frame):
        from .main import app
        runtime = getattr(app.state, 'tasks', None)
        if runtime:
            runtime.prepare_shutdown()
        super().handle_exit(sig, frame)


def run(*, host='127.0.0.1', port=8765, reload=False):
    config = uvicorn.Config('app.main:app', host=host, port=port, reload=reload,
        reload_dirs=[str(Path(__file__).parent)] if reload else None,
        # Bundled skills are integrity checked during startup. If an editor
        # writes a skill resource and its manifest in separate filesystem
        # operations, the first reload may fail validation. Watching both the
        # resource and manifest extensions guarantees the completed update
        # triggers another reload instead of leaving only the reloader socket.
        reload_includes=['*.py', '*.mjs', '*.json', '*.md', '*.yaml', '*.yml'] if reload else None,
        timeout_graceful_shutdown=5, log_level=os.getenv('AICS_API_LOG_LEVEL', 'info'))
    server = StudioServer(config)
    if reload:
        sock = config.bind_socket()
        try:
            ChangeReload(config, target=server.run, sockets=[sock]).run()
        finally:
            sock.close()
    else:
        server.run()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default=os.getenv('AICS_API_HOST', '127.0.0.1'))
    parser.add_argument('--port', type=int, default=int(os.getenv('AICS_API_PORT', '8765')))
    parser.add_argument('--reload', action='store_true')
    run(**vars(parser.parse_args()))
