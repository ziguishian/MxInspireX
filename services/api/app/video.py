from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class VideoJobService:
    def __init__(self, store, providers=None, assets=None, canvas=None) -> None:
        self.store = store
        self.providers, self.assets, self.canvas = providers, assets, canvas
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if not self._thread and self.providers:
            self._thread = threading.Thread(target=self._run, name="video-completion", daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _run(self):
        while not self._stop.wait(3):
            try:
                self.tick()
            except Exception:
                # Workspace shutdown/transient database contention must not
                # permanently disable all future job tracking.
                continue

    def tick(self):
        with self.store._connect() as db:
            rows = db.execute("SELECT project_id,id FROM video_jobs WHERE (output_asset_id IS NULL AND status NOT IN ('failed','cancelled','expired')) OR (output_asset_id IS NOT NULL AND COALESCE(json_extract(metadata_json,'$.canvasSynced'),0)=0)").fetchall()
        for row in rows:
            if self._stop.is_set():
                break
            record = self.get(row["project_id"], row["id"])
            if not record.get("outputAssetId") and (datetime.now(timezone.utc) - datetime.fromisoformat(record["createdAt"])).total_seconds() > 86400:
                self.update(row["project_id"], row["id"], status="expired", error="视频超过 24 小时未返回可用结果")
                self.refresh(row["project_id"], row["id"])
                continue
            if not record.get("outputAssetId") and not record.get("jobId"):
                self.update(row["project_id"], row["id"], status="failed", error="视频接口未返回可查询的任务编号")
                self.refresh(row["project_id"], row["id"])
                continue
            if record["metadata"].get("nextPollAt", 0) > time.time():
                continue
            try:
                self.refresh(row["project_id"], row["id"])
            except Exception as error:
                meta = self.get(row["project_id"], row["id"])["metadata"]
                attempts = int(meta.get("pollFailures", 0)) + 1
                # Failed downloads and transient provider errors remain recoverable.
                self.update(row["project_id"], row["id"], metadata={**meta, "pollFailures": attempts, "nextPollAt": time.time() + min(300, 5 * 2 ** min(attempts, 6))}, error=str(error)[:300])
        self.settle_tasks()

    def refresh(self, project_id, record_id, *, retry=False):
        with self._lock:
            record = self.get(project_id, record_id)
            if not record:
                raise ValueError("视频任务不存在")
            meta = record["metadata"]
            asset = self.assets.get_asset(project_id=project_id, asset_id=record["outputAssetId"]) if record.get("outputAssetId") else None
            # Recover a download saved immediately before a process interruption.
            asset = asset or next((a for a in self.assets.list_assets(project_id) if a.get("metadata", {}).get("videoJobRecordId") == record_id), None)
            result = {}
            if not asset and (retry or record["status"] not in {"failed", "cancelled", "expired"}):
                if not record.get("jobId"):
                    raise ValueError("视频任务没有可查询的 Job ID")
                from .billing import billing_scope
                with billing_scope(project_id=project_id, task_id=meta.get("taskId")):
                    provider = self.providers.video(record["provider"], endpoint=meta.get("endpoint"), model=record["model"])
                    result = provider.retrieve(job_id=record["jobId"], prompt=record["prompt"], model=record["model"], **(meta.get("params") or {}))
                content = result.pop("content", None)
                if content:
                    asset = self.assets.add_bytes(project_id=project_id, kind="video", filename=f"video-{record_id}.mp4", content=content,
                        metadata={"source": meta.get("source", "video-job"), "taskId": meta.get("taskId"), "canvasNodeId": meta.get("canvasNodeId"), "executionReceipt": meta.get("executionReceipt"), "videoJobRecordId": record_id, "model": record["model"], "provider": record["provider"], "prompt": record["prompt"],
                                  "sourceAssetId": record.get('sourceAssetId'), "sourceAssetIds": meta.get('sourceAssetIds', []), "lastFrameAssetId": meta.get('lastFrameAssetId'), "params": meta.get('params', {})})
            status = "backfilling" if asset else str(result.get("status") or record["status"]).lower()
            if status in {"completed", "succeeded", "success"} and not asset:
                status = "downloading"
            record = self.update(project_id, record_id, status=status, metadata={**meta, **result, "canvasSynced": False, "nextPollAt": time.time() + 5, "pollFailures": 0}, output_asset_id=asset["id"] if asset else None, error=result.get("error"))
            if self.canvas:
                board = self.canvas.load(project_id)
                target = next((n for n in board["nodes"] if n["id"] == meta.get("canvasNodeId") or (n.get("data", {}).get("job") or {}).get("id") == record_id), None)
                if asset and asset["id"] not in board.get("hiddenAssetIds", []):
                    self.canvas.ensure_asset_node(project_id, asset, task_id=meta.get("taskId"), target_node_id=target["id"] if target else None)
                elif target:
                    failed = status in {"failed", "cancelled", "expired"}
                    self.canvas.update_node(project_id, target["id"], {"data": {"job": record, "generating": not failed, "status": "生成失败" if failed else "生成中", "error": str(result.get("error") or record.get("error") or "视频生成失败") if failed else ""}})
            if asset:
                status = "succeeded"
                record = self.update(project_id, record_id, status=status, metadata={**record["metadata"], "canvasSynced": True}, error=None)
            return {"job": record, "status": status, "asset": asset}

    def settle_tasks(self):
        # Keep the task/SSE alive until every submitted video has a local asset.
        with self.store._connect() as db:
            rows = db.execute("SELECT id,project_id,input_json,output_json,trace_json FROM tasks WHERE status='running' AND output_json IS NOT NULL").fetchall()
        for row in rows:
            output = json.loads(row["output_json"])
            ids = output.get("provenance", {}).get("pendingMedia", [])
            if not ids and not output.get("provenance", {}).get("awaitingDelivery"):
                continue
            jobs = [self.get(row["project_id"], id) for id in ids]
            if any(not job or job.get("outputAssetId") and not job["metadata"].get("canvasSynced") or not job.get("outputAssetId") and job["status"] not in {"failed", "cancelled", "expired"} for job in jobs):
                continue
            failed = any(not job.get("outputAssetId") for job in jobs)
            generation_failed = failed
            context = json.loads(row["input_json"] or "{}")
            if context.get("deliveryVerification"):
                from .delivery import DeliveryService
                check = DeliveryService(self.store, self.assets, self.canvas).inspect_task(row["project_id"], row["id"], output.get("artifact_refs"))
                if check["pendingMedia"] or check["pendingPreview"]:
                    continue
                output["structured_data"]["delivery"] = check
                output["artifact_refs"] = check["artifact_refs"]
                failed = failed or bool(check["issues"])
            usable = any(a.get('ready') for a in output.get('structured_data',{}).get('delivery',{}).get('artifacts',[])) or any(job.get('outputAssetId') for job in jobs)
            delivery_status = 'needs_review' if failed and usable else 'failed' if failed else 'passed'
            status = "failed" if delivery_status == 'failed' else "succeeded"
            output.setdefault('structured_data',{})['deliveryStatus'] = delivery_status
            from .delivery_findings import annotate_delivery
            annotate_delivery(output['structured_data'])
            output["status"] = status
            output["provenance"]["pendingMedia"] = []
            output["provenance"]["awaitingDelivery"] = False
            if not failed:
                output["provenance"].setdefault("artifactKinds", []).append("video")
            reason = "；".join(output.get("structured_data", {}).get("delivery", {}).get("issues", [])) or "视频生成失败，请查看画布中的任务错误"
            from .delivery_findings import settled_answer
            answer = output["structured_data"].get("answer", "")
            output["structured_data"]["answer"] = settled_answer(answer + ("\n交付未完成：" + reason if failed else "\n作品已生成并保存到右侧画布。"))
            for job in jobs:
                if job.get("outputAssetId"):
                    output.setdefault("artifact_refs", []).append({"entity_type": "asset", "entity_id": job["outputAssetId"]})
            trace = json.loads(row["trace_json"] or "[]")
            failure_message = "视频生成失败" if generation_failed else "产物已保存，但交付检查未通过：" + reason
            trace.append({"at": utc_now(), "phase": 'needs_review' if delivery_status == 'needs_review' else status, "message": failure_message if failed else "视频已保存，任务完成"})
            with self.store._connect() as db:
                db.execute("UPDATE tasks SET status=?,output_json=?,trace_json=?,error_json=?,updated_at=? WHERE id=? AND status='running'", (status, json.dumps(output, ensure_ascii=False), json.dumps(trace[-80:], ensure_ascii=False), json.dumps({"message": reason}, ensure_ascii=False) if status == 'failed' else None, utc_now(), row["id"]))
                if db.execute("SELECT 1 FROM sqlite_master WHERE name='agent_repair_budget'").fetchone():
                    db.execute('UPDATE agent_repair_budget SET active=0 WHERE task_id=?',(row['id'],))

    def create(self, project_id: str, *, provider: str, model: str, status: str, job_id: str | None, prompt: str, source_asset_id: str | None, metadata: dict | None = None, output_asset_id: str | None = None, error: str | None = None) -> dict:
        now = utc_now()
        record_id = str(uuid4())
        with self.store._connect() as connection:
            connection.execute("INSERT INTO video_jobs (id, project_id, provider, model, status, job_id, prompt, source_asset_id, output_asset_id, metadata_json, error, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (record_id, project_id, provider, model, status, job_id, prompt, source_asset_id, output_asset_id, json.dumps(metadata or {}, ensure_ascii=False), error, now, now))
        return self.get(project_id, record_id) or {}

    def get(self, project_id: str, record_id: str) -> dict | None:
        with self.store._connect() as connection:
            row = connection.execute("SELECT * FROM video_jobs WHERE project_id = ? AND id = ?", (project_id, record_id)).fetchone()
        return self._row(row) if row else None

    def list(self, project_id: str) -> list[dict]:
        with self.store._connect() as connection:
            rows = connection.execute("SELECT * FROM video_jobs WHERE project_id = ? ORDER BY created_at DESC", (project_id,)).fetchall()
        return [self._row(row) for row in rows]

    def update(self, project_id: str, record_id: str, *, status: str | None = None, metadata: dict | None = None, output_asset_id: str | None = None, error: str | None = None) -> dict | None:
        current = self.get(project_id, record_id)
        if current is None:
            return None
        now = utc_now()
        next_status = status if status is not None else current["status"]
        next_metadata = metadata if metadata is not None else current["metadata"]
        next_output = output_asset_id if output_asset_id is not None else current["outputAssetId"]
        with self.store._connect() as connection:
            connection.execute("UPDATE video_jobs SET status = ?, output_asset_id = ?, metadata_json = ?, error = ?, updated_at = ? WHERE project_id = ? AND id = ?", (next_status, next_output, json.dumps(next_metadata, ensure_ascii=False), str(error) if error else None, now, project_id, record_id))
        return self.get(project_id, record_id)

    @staticmethod
    def _row(row) -> dict:
        return {"id": row["id"], "projectId": row["project_id"], "provider": row["provider"], "model": row["model"], "status": row["status"], "jobId": row["job_id"], "prompt": row["prompt"], "sourceAssetId": row["source_asset_id"], "outputAssetId": row["output_asset_id"], "metadata": json.loads(row["metadata_json"] or "{}"), "error": row["error"], "createdAt": row["created_at"], "updatedAt": row["updated_at"]}
