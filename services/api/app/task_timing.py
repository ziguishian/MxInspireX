"""Local phase timings only; never retain request content or credentials."""
import time


def record_timing(store, task_id, phase, started):
    if not task_id:
        return
    from .model_router import RouteTrace
    RouteTrace(store).append(task_id, {'call_kind': 'runtime_timing', 'phase': phase,
        'latency_ms': round((time.monotonic() - started) * 1000)})
