import json
import asyncio
import threading
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.schedules import SchedulePlanRequest, ScheduleService, ScheduleSpec, ScheduleTiming, next_occurrence
from app.storage import ProjectStore
from app.task_runtime import TaskRuntime

UTC = timezone.utc
NOW = datetime(2030, 1, 7, 0, 0, tzinfo=UTC)  # Monday, 08:00 in Shanghai


def plan_request(**overrides):
    return SchedulePlanRequest.model_validate({"prompt": "每天 9 点整理文旅设计简报", "requestId": "test-request-001", "textProvider": {"key": "openai-compatible", "baseUrl": "https://relay.test/v1", "model": "relay-chat"}, **overrides})


def spec(**overrides):
    return ScheduleSpec.model_validate({"title": "设计简报", "prompt": "整理一份文旅设计简报", "mode": "reminder", "timing": {"kind": "daily", "time": "09:00", "timezone": "Asia/Shanghai"}, **overrides})


class FakeTasks:
    def __init__(self):
        self.records = {}
        self.calls = []

    def get_task(self, project_id, task_id):
        return self.records.get(task_id)

    def enqueue(self, **kwargs):
        self.calls.append(kwargs)
        self.records[kwargs["task_id"]] = {"id": kwargs["task_id"], "status": "running"}
        return self.records[kwargs["task_id"]]


@pytest.fixture
def service(tmp_path):
    return ScheduleService(ProjectStore(str(tmp_path)), FakeTasks(), Mock())


def test_next_times_respect_timezone_weekdays_and_interval():
    assert next_occurrence(spec().timing, NOW) == NOW + timedelta(hours=1)
    weekly = ScheduleTiming(kind="weekly", time="09:00", weekdays=[2, 4], timezone="Asia/Shanghai")
    assert next_occurrence(weekly, NOW) == NOW + timedelta(days=2, hours=1)
    every_hour = ScheduleTiming(kind="interval", intervalMinutes=60)
    assert next_occurrence(every_hour, NOW + timedelta(hours=5, minutes=20), anchor=NOW) == NOW + timedelta(hours=6)
    once = ScheduleTiming(kind="once", at=NOW + timedelta(hours=1))
    assert next_occurrence(once, NOW) == NOW + timedelta(hours=1)
    assert next_occurrence(once, NOW + timedelta(hours=1)) is None


def test_daily_dst_does_not_fire_twice():
    timing = ScheduleTiming(kind="daily", time="01:30", timezone="America/New_York")
    first = next_occurrence(timing, datetime(2026, 11, 1, 4, tzinfo=UTC))
    assert first == datetime(2026, 11, 1, 5, 30, tzinfo=UTC)
    assert next_occurrence(timing, first) == datetime(2026, 11, 2, 6, 30, tzinfo=UTC)
    spring = ScheduleTiming(kind="daily", time="02:30", timezone="America/New_York")
    assert next_occurrence(spring, datetime(2026, 3, 8, 5, tzinfo=UTC)) == datetime(2026, 3, 8, 7, 30, tzinfo=UTC)


@pytest.mark.parametrize("timing", [
    {"kind": "daily", "time": "25:00"}, {"kind": "weekly", "time": "09:00", "weekdays": []},
    {"kind": "weekly", "time": "09:00", "weekdays": [7]}, {"kind": "once", "at": "2030-01-07T12:00:00"},
    {"kind": "interval", "intervalMinutes": 0}, {"kind": "daily", "time": "09:00", "timezone": "Bad/Zone"},
])
def test_invalid_timing_is_rejected(timing):
    with pytest.raises(ValidationError):
        ScheduleTiming.model_validate(timing)


def test_agent_organizes_multiple_plans_and_retries_are_idempotent(service):
    provider = service.providers.text.return_value
    provider.complete.return_value = json.dumps({"schedules": [spec().model_dump(mode="json"), spec(title="设计研究", mode="agent").model_dump(mode="json")], "questions": []})
    request = plan_request()
    first = service.arrange(request)
    second = service.arrange(request)
    assert len(first["schedules"]) == 2
    assert first == second
    provider.complete.assert_called_once()
    service.providers.text.assert_called_once_with("openai-compatible", base_url="https://relay.test/v1", model="relay-chat")
    assert all(job["nextRunAt"] for job in service.list())


def test_agent_clarifications_do_not_create_partial_schedules(service):
    service.providers.text.return_value.complete.return_value = json.dumps({"questions": ["每天几点执行？"], "schedules": [spec().model_dump(mode="json")]})
    assert service.arrange(plan_request())["questions"] == ["每天几点执行？"]
    assert service.list() == []


def test_invalid_batch_does_not_partially_save(service):
    with pytest.raises(ValueError):
        service.create([spec(), spec(timing={"kind": "once", "at": NOW.isoformat()})], plan_request(), NOW)
    assert service.list() == []


def test_reminders_are_durable_once_per_occurrence_and_catch_up_once(service):
    job = service.create([spec()], plan_request(), NOW)[0]
    assert service.notifications() == []
    service.tick(NOW + timedelta(hours=1))
    service.tick(NOW + timedelta(hours=1, seconds=3))
    assert len(service.notifications()) == 1
    recovered = ScheduleService(service.store, service.tasks, service.providers)
    recovered.tick(NOW + timedelta(days=5, hours=2))
    assert len(recovered.notifications()) == 2
    assert recovered.list()[0]["nextRunAt"] == (NOW + timedelta(days=6, hours=1)).isoformat()
    assert recovered.list()[0]["id"] == job["id"]


def test_pause_resume_and_delete(service):
    job = service.create([spec()], plan_request(), NOW)[0]
    service.update(job["id"], status="paused")
    service.tick(NOW + timedelta(days=1))
    assert not service.notifications()
    assert service.list()[0]["nextRunAt"] is None
    assert service.update(job["id"], status="active")["nextRunAt"]
    service.update(job["id"], status="deleted")
    assert service.list() == []


def test_agent_execution_uses_current_provider_and_persists_results(service):
    service.create([spec(mode="agent")], plan_request(imageModel="relay-image", allowExternalNetwork=True), NOW)
    service.tick(NOW + timedelta(hours=1))
    assert len(service.tasks.calls) == 1
    call = service.tasks.calls[0]
    assert call["agent_key"] == "design"
    assert call["input_data"]["textProvider"]["model"] == "relay-chat"
    assert call["input_data"]["mediaProvider"]["image"]["model"] == "relay-image"
    assert call["input_data"]["allowExternalNetwork"] is True
    assert len(service.store.list_projects()) == 1
    # No overlapping runs while the previous execution is still running.
    service.tick(NOW + timedelta(days=2))
    assert len(service.tasks.calls) == 1
    service.tasks.records[call["task_id"]] = {"status": "succeeded", "output": {"structured_data": {"answer": "简报已完成"}}}
    service.tick(NOW + timedelta(days=2, seconds=3))
    notices = service.notifications()
    assert len(notices) == 2
    assert notices[0]["body"] == "简报已完成"
    assert notices[0]["projectId"] == call["project_id"]
    assert len(service.claim_desktop_notifications()) == 2
    assert service.claim_desktop_notifications() == []
    service.mark_read(notices[0]["id"])
    assert len(service.notifications(unread=True)) == 1


def test_startup_recovers_task_created_before_scheduler_status_was_saved(service):
    service.create([spec(mode="agent")], plan_request(), NOW)
    original = service.tasks.enqueue

    def crash_after_enqueue(**kwargs):
        original(**kwargs)
        raise SystemExit("simulated process stop")

    service.tasks.enqueue = crash_after_enqueue
    with pytest.raises(SystemExit):
        service.tick(NOW + timedelta(hours=1))
    service.tasks.enqueue = original
    ScheduleService(service.store, service.tasks, service.providers).tick(NOW + timedelta(hours=1, seconds=3))
    assert len(service.tasks.calls) == 1
    assert len(service.store.list_projects()) == 1
    assert len(service.notifications()) == 1


def test_failure_is_recorded_and_notified(service):
    service.create([spec(mode="agent")], plan_request(), NOW)
    service.tasks.enqueue = Mock(side_effect=ValueError("模型暂不可用"))
    service.tick(NOW + timedelta(hours=1))
    assert service.notifications()[0]["title"].startswith("执行失败")
    assert service.notifications()[0]["body"] == "模型暂不可用"
    with service.store._connect() as db:
        assert db.execute("SELECT status FROM scheduled_runs").fetchone()[0] == "failed"


def test_supplied_task_id_is_idempotent(tmp_path):
    runtime = TaskRuntime(ProjectStore(str(tmp_path)))
    with patch.object(runtime, "_start_worker") as start:
        task = runtime.enqueue(project_id="schedule-project", agent_key="design", workflow_step="design", brief="test", run_async=True, task_id="scheduled-run-id")
        second = runtime.enqueue(project_id="schedule-project", agent_key="design", workflow_step="design", brief="test", run_async=True, task_id="scheduled-run-id")
    assert task["id"] == second["id"]
    assert len(runtime.list_tasks("schedule-project")) == 1
    start.assert_called_once()


def test_schedule_http_endpoints(tmp_path, monkeypatch):
    monkeypatch.setenv("AICS_WORKSPACE_ROOT", str(tmp_path))
    with TestClient(app) as client:
        app.state.model_catalog.save('openai-compatible', 'https://relay.test/v1', {'models': ['openai/gpt-6-luna', 'gpt-5.6-terra']})
        with patch.object(app.state.providers, "text") as text:
            text.return_value.complete.return_value = json.dumps({"schedules": [spec().model_dump(mode="json")], "questions": []})
            response = client.post("/api/schedules/arrange", json=plan_request().model_dump(mode="json"))
        assert response.status_code == 200
        job_id = response.json()["schedules"][0]["id"]
        assert len(client.get("/api/schedules").json()) == 1
        assert client.post(f"/api/schedules/{job_id}/status", json={"status": "paused"}).json()["status"] == "paused"
        assert client.put(f"/api/schedules/{job_id}", json=spec(title="新标题").model_dump(mode="json")).json()["title"] == "新标题"
        assert client.post(f"/api/schedules/{job_id}/status", json={"status": "invalid"}).status_code == 422
        assert client.get("/api/schedule-notifications").json() == []
        assert client.post("/api/schedule-notifications/desktop").json() == []


def test_planning_progress_is_visible_while_model_is_still_running(service):
    from app.schedule_stream import schedule_plan_events
    release = threading.Event()

    def complete(**_):
        assert release.wait(5), "The model should be released after its running event arrives"
        return json.dumps({"schedules": [spec().model_dump(mode="json")], "questions": []})

    service.providers.text.return_value.complete.side_effect = complete

    async def consume():
        events = []
        try:
            async for frame in schedule_plan_events(service, plan_request()):
                if not frame.startswith('event:'):
                    continue
                kind, raw = frame.strip().split('\ndata: ', 1)
                event = json.loads(raw)
                events.append((kind, event))
                if event.get('id') == 'planning' and event.get('status') == 'running':
                    assert service.list() == []
                    release.set()
        finally:
            release.set()
        return events

    events = asyncio.run(consume())
    assert events[-1][0] == 'event: result'
    assert len(events[-1][1]['schedules']) == 1
    assert [(event['id'], event['status']) for kind, event in events if kind == 'event: progress'] == [
        ('received', 'completed'), ('context', 'running'), ('context', 'completed'),
        ('planning', 'running'), ('planning', 'completed'), ('validation', 'running'),
        ('validation', 'completed'), ('saving', 'running'), ('saving', 'completed'),
    ]


def test_planning_clarification_never_reports_saved(service):
    service.providers.text.return_value.complete.return_value = json.dumps({'schedules': [], 'questions': ['几点执行？']})
    events = []
    result = service.arrange(plan_request(), progress=events.append)
    assert result['questions'] == ['几点执行？']
    assert events[-1]['status'] == 'waiting'
    assert not any(event['id'] == 'saving' for event in events)
    assert service.list() == []


def test_stream_endpoint_reports_failure_and_retains_request_id_deduplication(tmp_path, monkeypatch):
    monkeypatch.setenv('AICS_WORKSPACE_ROOT', str(tmp_path))
    with TestClient(app) as client:
        app.state.model_catalog.save('openai-compatible', 'https://relay.test/v1', {'models': ['openai/gpt-6-luna', 'gpt-5.6-terra']})
        with patch.object(app.state.providers, 'text') as text:
            text.return_value.complete.side_effect = ValueError('模型暂不可用')
            response = client.post('/api/schedules/arrange/stream', json=plan_request().model_dump(mode='json'))
            assert response.status_code == 200
            assert 'text/event-stream' in response.headers['content-type']
            assert 'event: error' in response.text
            assert '模型暂不可用' in response.text
            assert '"status": "failed"' in response.text
            assert app.state.schedules.list() == []
            text.return_value.complete.side_effect = None
            text.return_value.complete.return_value = json.dumps({'schedules': [spec().model_dump(mode='json')], 'questions': []})
            for _ in range(2):
                response = client.post('/api/schedules/arrange/stream', json=plan_request().model_dump(mode='json'))
                assert 'event: result' in response.text
            assert len(app.state.schedules.list()) == 1
            assert text.return_value.complete.call_count == 2
