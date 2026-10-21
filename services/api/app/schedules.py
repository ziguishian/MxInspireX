from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Callable, Literal
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import new_project

logger = logging.getLogger(__name__)
UTC = timezone.utc


def timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


class ScheduleTiming(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["once", "daily", "weekly", "interval"]
    timezone: str = "Asia/Shanghai"
    time: str | None = None
    weekdays: list[int] = Field(default_factory=list)
    at: datetime | None = None
    intervalMinutes: int | None = Field(default=None, ge=1, le=525600)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("请选择有效时区") from error
        return value

    @model_validator(mode="after")
    def validate_timing(self):
        if self.kind in {"daily", "weekly"}:
            try:
                datetime.strptime(self.time or "", "%H:%M")
            except ValueError as error:
                raise ValueError("请指定执行时间（HH:MM）") from error
        if self.kind == "weekly" and (not self.weekdays or any(day not in range(7) for day in self.weekdays)):
            raise ValueError("每周任务需要选择星期（0 为周一，6 为周日）")
        if self.kind == "once" and (not self.at or self.at.tzinfo is None):
            raise ValueError("单次任务需要包含时区的执行时间")
        if self.kind == "interval" and not self.intervalMinutes:
            raise ValueError("请指定间隔分钟数")
        return self


def next_occurrence(timing: ScheduleTiming, after: datetime, *, anchor: datetime | None = None) -> datetime | None:
    after = after.astimezone(UTC)
    if timing.kind == "once":
        return timing.at.astimezone(UTC) if timing.at and timing.at > after else None
    if timing.kind == "interval":
        step = timedelta(minutes=timing.intervalMinutes)
        origin = (anchor or after).astimezone(UTC)
        return origin + step * max(1, int((after - origin) // step) + 1)
    zone = ZoneInfo(timing.timezone)
    local = after.astimezone(zone)
    hour, minute = map(int, timing.time.split(":"))
    for offset in range(9):
        day = local.date() + timedelta(days=offset)
        if timing.kind == "weekly" and day.weekday() not in timing.weekdays:
            continue
        candidate = datetime(day.year, day.month, day.day, hour, minute, tzinfo=zone)
        # Round-trip through UTC moves a nonexistent spring-forward time to
        # the first equivalent time after the DST gap; fall-back runs once.
        candidate = candidate.astimezone(UTC)
        if candidate > after:
            return candidate
    raise ValueError("无法计算下次执行时间")


class ScheduleSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=120)
    prompt: str = Field(min_length=1, max_length=12000)
    mode: Literal["agent", "reminder"] = "agent"
    timing: ScheduleTiming


class ProviderRef(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    key: Literal["openrouter", "evolink", "openai-compatible", "ollama"]
    baseUrl: str = Field(min_length=1, max_length=2000)
    model: str = Field(min_length=1, max_length=200)

    @field_validator("baseUrl")
    @classmethod
    def validate_url(cls, value):
        from urllib.parse import urlsplit
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("请使用不含凭据或查询参数的 Base URL")
        return value.rstrip("/")


class SchedulePlanRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=12000)
    timezone: str = "Asia/Shanghai"
    projectId: str | None = None
    requestId: str = Field(min_length=8, max_length=120)
    textProvider: ProviderRef
    allowExternalNetwork: bool = False
    imageModel: str | None = Field(default=None, max_length=200)


class ScheduleUpdate(ScheduleSpec):
    pass


SCHEMA = """
CREATE TABLE IF NOT EXISTS scheduled_jobs (
 id TEXT PRIMARY KEY, request_id TEXT NOT NULL, plan_index INTEGER NOT NULL,
 spec_json TEXT NOT NULL, provider_json TEXT NOT NULL, project_id TEXT,
 allow_network INTEGER NOT NULL DEFAULT 0,
 status TEXT NOT NULL DEFAULT 'active', next_run_at TEXT, created_at TEXT NOT NULL,
 UNIQUE(request_id, plan_index)
);
CREATE TABLE IF NOT EXISTS scheduled_runs (
 id TEXT PRIMARY KEY, schedule_id TEXT NOT NULL REFERENCES scheduled_jobs(id),
 due_at TEXT NOT NULL, status TEXT NOT NULL, task_id TEXT, project_id TEXT,
 created_at TEXT NOT NULL, finished_at TEXT, summary TEXT,
 UNIQUE(schedule_id, due_at)
);
CREATE TABLE IF NOT EXISTS schedule_notifications (
 id TEXT PRIMARY KEY, schedule_id TEXT NOT NULL, run_id TEXT NOT NULL,
 title TEXT NOT NULL, body TEXT NOT NULL, project_id TEXT, task_id TEXT,
 created_at TEXT NOT NULL, read_at TEXT, desktop_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_schedule_due ON scheduled_jobs(status, next_run_at);
"""


class ScheduleService:
    def __init__(self, store, tasks, providers):
        self.store, self.tasks, self.providers = store, tasks, providers
        self._stop = threading.Event()
        self._tick_lock = threading.Lock()
        self._plan_lock = threading.Lock()
        self._thread = None
        with store._connect() as db:
            db.executescript(SCHEMA)

    def start(self):
        self._thread = threading.Thread(target=self._loop, name="scheduled-jobs", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=6)

    def _loop(self):
        while not self._stop.wait(3):
            try:
                self.tick()
            except Exception:
                logger.exception("Scheduled task poll failed")

    def _view(self, row):
        return {"id": row["id"], **json.loads(row["spec_json"]), "status": row["status"], "nextRunAt": row["next_run_at"],
                "projectId": row["project_id"], "createdAt": row["created_at"]}

    def list(self):
        with self.store._connect() as db:
            rows = db.execute("SELECT * FROM scheduled_jobs WHERE status != 'deleted' ORDER BY created_at DESC").fetchall()
        return [self._view(row) for row in rows]

    def arrange(self, request: SchedulePlanRequest, progress: Callable | None = None):
        def report(stage, status, label):
            if progress:
                progress({"id": stage, "status": status, "label": label, "at": timestamp(datetime.now(UTC))})

        report("received", "completed", "已接收定时计划需求")
        report("context", "running", "正在核对时区与关联项目")
        with self._plan_lock:
            with self.store._connect() as db:
                previous = db.execute("SELECT * FROM scheduled_jobs WHERE request_id = ? ORDER BY plan_index", (request.requestId,)).fetchall()
            if previous:
                report("context", "completed", "已找到本次提交保存的计划，无需重复创建")
                return {"schedules": [self._view(row) for row in previous], "questions": []}
            if request.projectId and not self.store.get_project(request.projectId):
                raise ValueError("关联项目不存在")
            try:
                zone = ZoneInfo(request.timezone)
            except (ZoneInfoNotFoundError, ValueError) as error:
                raise ValueError("时区无效") from error
            now = datetime.now(UTC)
            from .model_config import ModelTier
            from .model_catalog import ModelCatalog
            from .model_router import ModelRouter, RouteTrace
            current_endpoint = {'key': request.textProvider.key, 'baseUrl': request.textProvider.baseUrl, 'model': request.textProvider.model}
            endpoint = (ModelRouter(self.providers.catalog, self.providers).endpoint(ModelTier.STANDARD, current_endpoint)
                        if isinstance(self.providers.catalog, ModelCatalog) else current_endpoint)
            provider = self.providers.text(endpoint['key'], base_url=endpoint['baseUrl'], model=endpoint['model'])
            report("context", "completed", f"时区与关联项目已确认 · {request.timezone}")
            report("planning", "running", "Agent 正在解析任务内容、执行方式与时间")
            started = time.time()
            try:
                raw = provider.complete(system=(
                    "你是 MxinspireX，由灵矩绘境研发的智能设计 Agent，当前负责定时任务规划。把用户计划拆成独立、可执行的定时任务，保留原意和时间。"
                    "只返回 JSON 对象 {\"schedules\":[...],\"questions\":[]}，最多 20 个任务。"
                    "任务字段 title、prompt（该周期具体做什么）、mode（agent 自动执行 / reminder 仅提醒）、timing。"
                    "timing 字段 kind: once/daily/weekly/interval、timezone（IANA）、time（HH:MM，daily/weekly 必须）、"
                    "weekdays（weekly 必须，周一=0 到周日=6）、at（once 必须，含时区 ISO 时间）、intervalMinutes（interval 必须）。"
                    "不适用的字段省略。用户说提醒我时使用 reminder，说帮我执行/收集/整理/生成时使用 agent。"
                    "缺少执行内容、日期、周期或具体时间，或要求当前规则无法表达时，返回 schedules:[] 和简短 questions，不要猜时间。"
                    "仅安排用户明确要求的任务，不把方案建议自动加入定时任务。禁止声称已经执行，禁止添加收件人、发消息或购买操作。"
                ), prompt=f"当前时间：{now.astimezone(zone).isoformat()}\n默认时区：{request.timezone}\n用户计划：\n{request.prompt}")
            except Exception as error:
                RouteTrace(self.store).append(f"schedule-plan:{request.requestId}", {
                    "call_kind": "schedule_plan", "tier": ModelTier.STANDARD.value, "provider": endpoint["key"],
                    "base_url": endpoint["baseUrl"], "model": endpoint["model"], "route_source": "automatic-standard",
                    "started_at": started, "latency_ms": round((time.time() - started) * 1000), "status": "failed",
                    "error_type": type(error).__name__, "submitted": None, "billing_certainty": "unknown",
                })
                raise
            RouteTrace(self.store).append(f"schedule-plan:{request.requestId}", {
                "call_kind": "schedule_plan", "tier": ModelTier.STANDARD.value, "provider": endpoint["key"],
                "base_url": endpoint["baseUrl"], "model": endpoint["model"], "route_source": "automatic-standard",
                "started_at": started, "latency_ms": round((time.time() - started) * 1000), "status": "succeeded",
                "error_type": None, "submitted": True, "billing_certainty": "settled",
            })
            report("planning", "completed", "Agent 已返回计划解析结果")
            report("validation", "running", "正在校验计划并计算下次执行时间")
            clean = raw.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            try:
                plan = json.loads(clean)
                if not isinstance(plan, dict):
                    raise ValueError("Agent 返回了无效的计划")
                questions = plan.get("questions") or []
                if questions:
                    if not isinstance(questions, list) or not all(isinstance(q, str) for q in questions):
                        raise ValueError("Agent 返回了无效的问题")
                    report("validation", "waiting", "需要补充信息，尚未创建定时任务")
                    return {"schedules": [], "questions": questions[:6]}
                items = plan.get("schedules")
                if not isinstance(items, list) or not 1 <= len(items) <= 20:
                    raise ValueError("请提供 1–20 个明确的定时任务")
                specs = [ScheduleSpec.model_validate(item) for item in items]
            except (json.JSONDecodeError, TypeError) as error:
                raise ValueError("Agent 未返回有效计划，请补充时间和任务内容后重试") from error
            return {"schedules": self.create(specs, request, now, progress=report, provider_ref=endpoint), "questions": []}

    def create(self, specs, request, now, progress=None, provider_ref=None):
        # Validate the whole plan before saving any task.
        next_runs = [next_occurrence(spec.timing, now) for spec in specs]
        if any(value is None for value in next_runs):
            raise ValueError("单次任务的执行时间已过去，请调整计划时间")
        if progress:
            progress("validation", "completed", f"已校验 {len(specs)} 个计划及执行时间")
            progress("saving", "running", "正在保存并启用定时任务")
        created = []
        with self.store._connect() as db:
            for index, (spec, due) in enumerate(zip(specs, next_runs)):
                job_id = str(uuid4())
                saved_provider = {
                    'key': (provider_ref or {}).get('key') or request.textProvider.key,
                    'baseUrl': (provider_ref or {}).get('baseUrl') or request.textProvider.baseUrl,
                    'model': (provider_ref or {}).get('model') or request.textProvider.model,
                    'api': (provider_ref or {}).get('api', 'auto'),
                    'imageModel': request.imageModel,
                }
                db.execute("INSERT INTO scheduled_jobs (id, request_id, plan_index, spec_json, provider_json, project_id, allow_network, next_run_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           (job_id, request.requestId, index, spec.model_dump_json(), json.dumps(saved_provider), request.projectId, int(request.allowExternalNetwork), timestamp(due), timestamp(now)))
                created.append(self._view(db.execute("SELECT * FROM scheduled_jobs WHERE id = ?", (job_id,)).fetchone()))
        if progress:
            progress("saving", "completed", f"已保存并启用 {len(created)} 个定时任务")
        return created

    def update(self, job_id, *, spec=None, status=None):
        now = datetime.now(UTC)
        with self.store._connect() as db:
            row = db.execute("SELECT * FROM scheduled_jobs WHERE id = ? AND status != 'deleted'", (job_id,)).fetchone()
            if not row:
                raise KeyError(job_id)
            new_spec = spec or ScheduleSpec.model_validate_json(row["spec_json"])
            new_status = status or ("active" if spec and row["status"] == "completed" else row["status"])
            due = next_occurrence(new_spec.timing, now) if new_status == "active" else None
            if new_status == "active" and due is None:
                raise ValueError("执行时间已过去，请先修改时间")
            db.execute("UPDATE scheduled_jobs SET spec_json = ?, status = ?, next_run_at = ? WHERE id = ?", (new_spec.model_dump_json(), new_status, timestamp(due) if due else None, job_id))
            return self._view(db.execute("SELECT * FROM scheduled_jobs WHERE id = ?", (job_id,)).fetchone())

    def notifications(self, *, unread=False):
        with self.store._connect() as db:
            rows = db.execute("SELECT * FROM schedule_notifications" + (" WHERE read_at IS NULL" if unread else "") + " ORDER BY created_at DESC LIMIT 100").fetchall()
        return [{"id": row["id"], "title": row["title"], "body": row["body"], "projectId": row["project_id"], "taskId": row["task_id"], "createdAt": row["created_at"], "readAt": row["read_at"]} for row in rows]

    def mark_read(self, notification_id):
        with self.store._connect() as db:
            db.execute("UPDATE schedule_notifications SET read_at = ? WHERE id = ?", (timestamp(datetime.now(UTC)), notification_id))

    def claim_desktop_notifications(self):
        # The desktop process claims notifications independently of renderer
        # read-state, so minimized/closed windows still get an OS notification.
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT * FROM schedule_notifications WHERE desktop_at IS NULL AND read_at IS NULL ORDER BY created_at LIMIT 20").fetchall()
            for row in rows:
                db.execute("UPDATE schedule_notifications SET desktop_at = ? WHERE id = ?", (timestamp(datetime.now(UTC)), row["id"]))
        return [{"id": row["id"], "title": row["title"], "body": row["body"], "projectId": row["project_id"]} for row in rows]

    def _notify(self, db, run, title, body, event, now):
        db.execute("INSERT OR IGNORE INTO schedule_notifications (id, schedule_id, run_id, title, body, project_id, task_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                   (f"{run['id']}:{event}", run["schedule_id"], run["id"], title, body[:1500], run["project_id"], run["task_id"], timestamp(now)))

    def tick(self, now=None):
        now = now or datetime.now(UTC)
        if not self._tick_lock.acquire(blocking=False):
            return
        try:
            with self.store._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                due_jobs = db.execute("SELECT * FROM scheduled_jobs j WHERE status = 'active' AND next_run_at <= ? AND NOT EXISTS (SELECT 1 FROM scheduled_runs r WHERE r.schedule_id = j.id AND r.status IN ('launching', 'running')) LIMIT 20", (timestamp(now),)).fetchall()
                for job in due_jobs:
                    spec = ScheduleSpec.model_validate_json(job["spec_json"])
                    due = next_occurrence(spec.timing, now, anchor=datetime.fromisoformat(job["next_run_at"]))
                    run_id = str(uuid4())
                    db.execute("INSERT OR IGNORE INTO scheduled_runs (id, schedule_id, due_at, status, task_id, project_id, created_at) VALUES (?, ?, ?, 'launching', ?, ?, ?)", (run_id, job["id"], job["next_run_at"], run_id if spec.mode == "agent" else None, job["project_id"], timestamp(now)))
                    db.execute("UPDATE scheduled_jobs SET next_run_at = ?, status = ? WHERE id = ?", (timestamp(due) if due else None, "active" if due else "completed", job["id"]))
            with self.store._connect() as db:
                pending = db.execute("SELECT r.*, j.spec_json, j.provider_json, j.allow_network, j.status AS job_status FROM scheduled_runs r JOIN scheduled_jobs j ON j.id = r.schedule_id WHERE r.status IN ('launching', 'running') ORDER BY r.created_at LIMIT 40").fetchall()
            for row in pending:
                self._advance(dict(row), now)
        finally:
            self._tick_lock.release()

    def _advance(self, run, now):
        spec = ScheduleSpec.model_validate_json(run["spec_json"])
        try:
            if run["status"] == "launching":
                if run["job_status"] in {"paused", "deleted"}:
                    with self.store._connect() as db:
                        db.execute("UPDATE scheduled_runs SET status = 'cancelled', finished_at = ? WHERE id = ?", (timestamp(now), run["id"]))
                    return
                if spec.mode == "reminder":
                    with self.store._connect() as db:
                        self._notify(db, run, spec.title, spec.prompt, "reminder", now)
                        db.execute("UPDATE scheduled_runs SET status = 'succeeded', finished_at = ?, summary = ? WHERE id = ?", (timestamp(now), spec.prompt, run["id"]))
                    return
                if not run["project_id"]:
                    slug = f"scheduled-{run['schedule_id']}"
                    # Reuse the deterministic project if the sidecar stopped
                    # between project creation and saving its schedule link.
                    project = next((p for p in self.store.list_projects() if p["slug"] == slug), None)
                    if not project:
                        project = self.store.create_project(new_project(name=spec.title, slug=slug, brief=spec.prompt, budget_minor=None, currency="CNY", root_path=str(self.store.workspace_root / slug)))
                    run["project_id"] = project["id"]
                    with self.store._connect() as db:
                        db.execute("UPDATE scheduled_jobs SET project_id = ? WHERE id = ?", (project["id"], run["schedule_id"]))
                        db.execute("UPDATE scheduled_runs SET project_id = ? WHERE id = ?", (project["id"], run["id"]))
                if not self.store.get_project(run["project_id"]):
                    raise ValueError("关联项目已删除，请重新设置定时任务")
                task = self.tasks.get_task(run["project_id"], run["task_id"])
                if not task:
                    provider_ref = json.loads(run["provider_json"])
                    media = {
                        "image": {"key": provider_ref["key"], "baseUrl": provider_ref["baseUrl"], "model": provider_ref.get("imageModel"), "manual": bool(provider_ref.get("imageModel"))},
                        "video": {"key": provider_ref["key"], "endpoint": provider_ref["baseUrl"], "manual": False},
                    }
                    self.tasks.enqueue(project_id=run["project_id"], task_id=run["task_id"], agent_key="design", workflow_step="design", brief=spec.prompt,
                        input_data={"textProvider": json.loads(run["provider_json"]), "allowExternalNetwork": bool(run["allow_network"]), "mediaProvider": media, "scheduledTask": {"id": run["schedule_id"], "dueAt": run["due_at"], "timezone": spec.timing.timezone}}, run_async=True)
                with self.store._connect() as db:
                    db.execute("UPDATE scheduled_runs SET status = 'running' WHERE id = ?", (run["id"],))
                    self._notify(db, run, f"开始执行：{spec.title}", "Agent 已接收定时任务，完成后会通知你。", "started", now)
            task = self.tasks.get_task(run["project_id"], run["task_id"])
            if task and task["status"] in {"succeeded", "failed", "cancelled"}:
                output = (task.get("output") or {}).get("structured_data") or {}
                summary = str(output.get("answer") or output.get("llmResponse") or output.get("reply") or output.get("finalOutput") or (task.get("error") or {}).get("message") or "结果已保存，可打开项目查看。")
                with self.store._connect() as db:
                    db.execute("UPDATE scheduled_runs SET status = ?, finished_at = ?, summary = ? WHERE id = ?", (task["status"], timestamp(now), summary[:4000], run["id"]))
                    label = {"succeeded": "已完成", "failed": "执行失败", "cancelled": "已停止"}[task["status"]]
                    if output.get('deliveryStatus') == 'needs_review':
                        from .delivery_findings import collect_findings, findings_summary
                        label = findings_summary(collect_findings(output))
                    self._notify(db, run, f"{label}：{spec.title}", summary, "finished", now)
        except Exception as error:
            with self.store._connect() as db:
                db.execute("UPDATE scheduled_runs SET status = 'failed', finished_at = ?, summary = ? WHERE id = ?", (timestamp(now), str(error)[:1500], run["id"]))
                self._notify(db, run, f"执行失败：{spec.title}", str(error), "finished", now)
