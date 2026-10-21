"""One short background title after three completed conversation turns."""
from __future__ import annotations

import logging
import queue
import re
import threading
import time

from .conversation_context import _object


logger = logging.getLogger(__name__)
MIN_TURNS = 3
DELIVERABLES = (
    ('图标|icon', '图标设计'), ('logo|标志|徽标', 'Logo 设计'), ('海报|poster', '海报设计'),
    ('包装|礼盒|盒型', '包装设计'), ('网页|网站|web|landing', '网页设计'),
    ('展厅|展馆|空间', '空间设计'), ('视频|动画', '视频设计'), ('文案|copy', '文案设计'),
    ('cad|三维|3d|模型', '三维设计'), ('品牌|vi', '品牌设计'),
)
TOPIC_NOISE = re.compile(r'^(?:你好|您好|谢谢|多谢|继续|可以|好的|没问题|hello|hi|hey)[！!。，,.？?~～\s]*$', re.I)


def local_title(turns):
    """Create a stable title without a paid model request."""
    messages = [re.sub(r'\s+', ' ', str(turn.get('user') or '')).strip() for turn in turns]
    meaningful = [text for text in messages if text and not TOPIC_NOISE.fullmatch(text)]
    if not meaningful:
        return None
    joined = '；'.join(meaningful[-6:])
    deliverable = next((label for pattern, label in DELIVERABLES if re.search(pattern, joined, re.I)), '设计任务')
    subject = ''
    for text in meaningful:
        cleaned = re.sub(r'^(?:请|麻烦|帮我|给我|我想|我希望|需要|只需要|请帮我)(?:设计|制作|创建|做|生成)?', '', text, flags=re.I)
        cleaned = re.split(r'[，。；;！!?？\n]|(?:不要|不需要|改成|修改为)', cleaned, 1)[0]
        cleaned = re.sub(r'(?:的)?(?:图标|icon|logo|标志|徽标|海报|poster|包装|礼盒|网页|网站|视频|动画|文案|设计)$', '', cleaned, flags=re.I)
        cleaned = re.sub(r'^(?:设计|制作|创建|生成|做)', '', cleaned).strip(' ：:、-')
        if 2 <= len(cleaned) <= 22 and not re.fullmatch(r'(?:圆润|简洁|现代|高级|好看|完整|一个|一套|一下)+', cleaned):
            subject = cleaned
            break
    if not subject:
        subject = re.sub(r'^(?:请|帮我|给我|我想|我希望|需要|只需要)', '', meaningful[-1]).strip(' ：:、-')
    title = f'{subject} {deliverable}'.strip()
    title = re.sub(r'\s+', ' ', title).strip('"“”「」')
    if len(title) > 32:
        room = max(2, 32 - len(deliverable) - 1)
        title = f'{subject[:room]} {deliverable}'.strip()
    return title if 2 <= len(title) <= 32 else None


class ProjectTitleService:
    def __init__(self, store, providers):
        self.store, self.providers = store, providers
        self._lock = threading.Lock()
        self._pending: set[str] = set()
        self._queue = queue.Queue()
        self._closed = threading.Event()
        self._worker = None

    def _candidate(self, project_id):
        with self.store._connect() as db:
            project = db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
            if not project or project["title_mode"] != "auto" or project["title_generated_at"] or project["title_retry_after"] > time.time():
                return None
            rows = db.execute("""SELECT input_json, output_json FROM tasks
                WHERE project_id=? AND agent_key='design' AND status='succeeded' AND superseded_by IS NULL
                ORDER BY created_at, COALESCE(turn_order,rowid)""", (project_id,)).fetchall()
        # Retries, failed calls and internal execution steps are not new rounds.
        turns = []
        for row in rows:
            inputs, output = _object(row["input_json"]), _object(row["output_json"])
            if inputs.get('taskSurface', 'conversation') == 'canvas_node':
                continue
            user = str(inputs.get("userMessage") or "").strip()
            if not user:
                continue
            structured = output.get("structured_data") or {}
            turns.append({"user": user[:600], "assistant": str(structured.get("answer") or structured.get("message") or "")[:600],
                          "provider": inputs.get("textProvider")})
        count = len(turns)
        if count < MIN_TURNS or count <= project["title_attempt_turns"]:
            return None
        # A bounded opening + recent context, never raw files, tools or secrets.
        chosen = turns if count <= 8 else turns[:2] + turns[-6:]
        return {"name": project["name"], "count": count,
                "turns": [{"user": turn["user"], "assistant": turn["assistant"]} for turn in chosen]}

    def schedule(self, project_id):
        if self._closed.is_set():
            return False
        with self._lock:
            if project_id in self._pending:
                return True
            if not self._candidate(project_id):
                return False
            self._pending.add(project_id)
            self._queue.put(project_id)
            if self._worker is None:
                # One daemon keeps title work bounded and outside task latency.
                self._worker = threading.Thread(target=self._run, name="project-titles", daemon=True)
                self._worker.start()
            return True

    def pending(self, project_id):
        with self._lock:
            return project_id in self._pending

    def stop(self):
        self._closed.set()
        self._queue.put(None)

    def _run(self):
        while not self._closed.is_set():
            project_id = self._queue.get()
            if project_id is None:
                return
            try:
                self.generate(project_id)
            except Exception as error:
                # No provider payloads/keys in logs; a title failure never fails
                # or replays the actual design task. Retry only on a later visit.
                logger.warning("Project title deferred for %s (%s)", project_id, type(error).__name__)
                try:
                    with self.store._connect() as db:
                        db.execute("UPDATE projects SET title_retry_after=? WHERE id=?", (time.time() + 300, project_id))
                except Exception:
                    logger.warning("Unable to persist project title retry state")
            finally:
                with self._lock:
                    self._pending.discard(project_id)

    def generate(self, project_id):
        candidate = self._candidate(project_id)
        if not candidate or self._closed.is_set():
            return False
        title = local_title(candidate["turns"])
        if self._closed.is_set():
            return False
        if title is None:
            with self.store._connect() as db:
                db.execute("UPDATE projects SET title_attempt_turns=? WHERE id=? AND title_mode='auto' AND title_generated_at IS NULL",
                           (candidate["count"], project_id))
            return False
        if not isinstance(title, str) or not 2 <= len(title.strip()) <= 32 or any(char in title for char in '\n\r\t'):
            raise ValueError("Invalid project title")
        title = title.strip().strip('"“”「」')
        if len(title) < 2 or title in {"你好", "新对话", "未命名设计任务"}:
            raise ValueError("Uninformative project title")
        return self.store.save_generated_title(project_id, candidate["name"], title, candidate["count"])
