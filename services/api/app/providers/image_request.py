"""Per-call notification at image dispatch, after adapter and budget validation."""
from contextlib import contextmanager
from contextvars import ContextVar

_listener = ContextVar('image_request_listener', default=None)


@contextmanager
def image_request_scope(on_start):
    token = _listener.set(on_start)
    try:
        yield
    finally:
        _listener.reset(token)


def image_request_started():
    listener = _listener.get()
    if listener:
        listener()
