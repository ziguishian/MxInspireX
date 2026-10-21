"""Bounded, read-only context from one project's design conversation.

No profile, cross-project memory, vector index, or extra persistent summary.
The existing task log remains the source of truth, including after reopening.
"""
from __future__ import annotations

import json
import re
from typing import Any


def _object(raw):
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def _clip(value, limit=1200):
    text = str(value or "")
    return text if len(text) <= limit else text[:limit] + "…（可用 conversation_read 回查原文）"


def _terms(text):
    text = str(text).casefold()
    words = re.findall(r"[a-z0-9_-]{2,}|[\u4e00-\u9fff]+", text)
    return {part for word in words for part in ([word] if word.isascii() or len(word) < 3 else [word[i:i+2] for i in range(len(word)-1)])}


class ConversationContext:
    def __init__(self, store):
        self.store = store

    def _rows(self, project_id, task_id):
        with self.store._connect() as db:
            current = db.execute("SELECT COALESCE(turn_order,rowid) AS position, created_at, input_json FROM tasks WHERE project_id=? AND id=? AND agent_key='design'", (project_id, task_id)).fetchone()
            if current is None:
                raise ValueError("当前对话任务不存在或不属于此项目")
            if _object(current['input_json']).get('taskSurface') == 'canvas_node':
                return []
            rows = db.execute("""SELECT id, status, input_json, output_json, created_at FROM tasks
                WHERE project_id=? AND agent_key='design' AND superseded_by IS NULL AND
                  (created_at < ? OR (created_at = ? AND COALESCE(turn_order,rowid) < ?))
                ORDER BY created_at, COALESCE(turn_order,rowid)""", (project_id, current["created_at"], current["created_at"], current["position"])).fetchall()
            return [row for row in rows if _object(row['input_json']).get('taskSurface', 'conversation') != 'canvas_node']

    def _updates(self, task_id):
        with self.store._connect() as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='task_updates'").fetchone(): return []
            return [{'text': row['text'], 'appliedAt': row['applied_at']} for row in db.execute('SELECT text,applied_at FROM task_updates WHERE task_id=? ORDER BY revision', (task_id,))]

    def _turn(self, row, *, include_artifacts=True):
        inputs, output = _object(row["input_json"]), _object(row["output_json"])
        structured = output.get("structured_data") or {}
        from .delivery_findings import annotate_delivery
        annotate_delivery(structured)
        answer = structured.get("answer") or structured.get("message") or ""
        if structured.get('deliveryStatus') == 'needs_review':
            from .delivery_findings import collect_findings, findings_summary
            answer = '该轮产物已保存；' + findings_summary(collect_findings(structured)) + '。\n' + str(answer)
        # An unsuccessful/unfinished attempt is not a successful delivery.
        if row["status"] != "succeeded":
            answer = {"failed": "该轮执行失败，不代表已完成。", "cancelled": "该轮已取消。", "running": "该轮仍在执行，未确认完成。", "queued": "该轮排队中。"}.get(row["status"], "该轮未确认完成。")
        references = []
        for key in ("referencedAssets", "referencedNodes", "referencedFiles"):
            for ref in (inputs.get(key) or [])[:8]:
                if isinstance(ref, dict):
                    references.append({"referenceType":{'referencedAssets':'asset','referencedNodes':'node','referencedFiles':'file'}[key],
                                       **{k: _clip(ref[k], 180) for k in ("id", "nodeId", "assetId", "projectId", "documentId", "filename", "title") if ref.get(k)}})
        artifacts = []
        records = output.get("provenance", {}).get("recovery", {}).get("toolOutputs", []) if include_artifacts else []
        if include_artifacts and not records:
            # The routing layer removes bulky recovery data from final answers.
            # Read committed receipts directly without changing execution state.
            with self.store._connect() as db:
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='tool_receipts'").fetchone():
                    receipts = db.execute("SELECT name, output FROM tool_receipts WHERE task_id=? AND status='completed' AND (name LIKE 'generate_%' OR name LIKE 'canvas_create_%' OR name IN ('image_edit','media_edit','canvas_update_node','canvas_restore_node','transcribe_audio')) ORDER BY rowid DESC LIMIT 8", (row["id"],)).fetchall()
                    records = [{"name": receipt["name"], "output": _object(receipt["output"])} for receipt in reversed(receipts)]
        for record in records:
            result = record.get("output") or {}
            asset, node = result.get("asset") or {}, result.get("node") or {}
            if not (result.get("assetId") or node.get("id")):
                continue
            artifacts.append({"tool": record.get("name"), "assetId": result.get("assetId") or asset.get("id"),
                              "nodeId": node.get("id"), "title": _clip(node.get("data", {}).get("title"), 160),
                              "kind": result.get("outputKind") or asset.get("kind") or node.get("data", {}).get("kind"), "status": result.get("status"),
                              "sourceAssetId": asset.get("metadata", {}).get("sourceAssetId"),
                              "params": {k: _clip(v, 100) for k, v in (asset.get("metadata", {}).get("params") or {}).items() if k in {"background", "output_format", "size", "aspectRatio", "quality"}},
                              "hasTransparency": result.get("imageOutput", {}).get("hasTransparency")})
        return {"taskId": row["id"], "at": row["created_at"], "status": row["status"],
                "deliveryStatus": structured.get("deliveryStatus"),
                "user": str(inputs.get("userMessage") or "") + "".join("\n执行中补充：" + item["text"] for item in self._updates(row["id"]) if item.get("appliedAt")), "assistant": str(answer),
                "references": references, "artifacts": artifacts[-8:],
                "warnings": [_clip(item, 300) for item in output.get("warnings", [])[:4]],
                "clarification": structured.get("clarification")}

    def build(self, project_id, task_id, query=""):
        rows = self._rows(project_id, task_id)
        turns = [self._turn(row, include_artifacts=index >= len(rows)-6) for index, row in enumerate(rows)]
        recent = turns[-6:]
        messages, outcomes = [], []
        for turn in recent:
            if turn["user"]:
                messages.append({"role": "user", "content": _clip(turn["user"], 1800), "taskId": turn["taskId"]})
            if turn["assistant"]:
                messages.append({"role": "assistant", "content": _clip(turn["assistant"], 1800), "taskId": turn["taskId"]})
            outcomes.append({k: turn[k] for k in ("taskId", "status", "deliveryStatus", "references", "artifacts", "warnings")})
            if turn["clarification"]:
                outcomes[-1]["historicalClarification"] = _clip(json.dumps(turn["clarification"], ensure_ascii=False), 1800)
        earlier = turns[:-6]
        terms = _terms(query)
        # Keep the opening request, recent decisions and relevant original user
        # statements. These are excerpts, never invented semantic summaries.
        ranked = sorted(range(len(earlier)), key=lambda i: (len(terms & _terms(earlier[i]["user"])), i), reverse=True)
        selected = list(dict.fromkeys(([0] if earlier else []) + list(range(max(0, len(earlier)-6), len(earlier))) + ranked))[:14]
        notes, budget = [], 7500
        for index in sorted(selected):
            item = earlier[index]
            excerpt = _clip(item["user"], min(500, budget))
            if not excerpt or len(excerpt) > budget:
                continue
            notes.append({"taskId": item["taskId"], "user": excerpt})
            budget -= len(excerpt)
        return {"scope": "project-conversation", "projectId": project_id, "taskId": task_id,
                "historyTurnCount": len(turns), "messages": messages, "earlierUserExcerpts": notes,
                "recentOutcomes": outcomes,
                "hasEarlierHistory": len(turns) > len(recent),
                "recallTool": "conversation_read"}

    def read(self, project_id, task_id, *, query="", turn_id=None, offset=0, limit=5, text_offset=0):
        rows = self._rows(project_id, task_id)
        by_id = {row["id"]: row for row in rows}
        turns = [self._turn(row, include_artifacts=False) for row in rows]
        if turn_id:
            turns = [turn for turn in turns if turn["taskId"] == turn_id]
        elif query:
            terms = _terms(query)
            scored = [(len(terms & _terms(turn["user"] + " " + turn["assistant"])), i, turn) for i, turn in enumerate(turns)]
            turns = [item[2] for item in sorted(scored, key=lambda item: (item[0], item[1]), reverse=True) if item[0]]
        start, limit, text_start = max(0, int(offset)), max(1, min(5, int(limit))), max(0, int(text_offset))
        results = []
        for turn in turns[start:start+limit]:
            turn = self._turn(by_id[turn["taskId"]])
            result = {**turn, "user": turn["user"][text_start:text_start+2500], "assistant": turn["assistant"][text_start:text_start+2500]}
            result["nextTextOffset"] = text_start+2500 if max(len(turn["user"]), len(turn["assistant"])) > text_start+2500 else None
            # Questions remain historical context, not a new pending task.
            result["clarification"] = _clip(json.dumps(turn["clarification"], ensure_ascii=False), 1500) if turn["clarification"] else None
            results.append(result)
        return {"scope": "project-conversation", "projectId": project_id, "results": results,
                "total": len(turns), "nextOffset": start+limit if start+limit < len(turns) else None}
