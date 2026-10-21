from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Callable


class LocalVectorIndex:
    """Embedded vector index with an optional LanceDB backend.

    The deterministic hash embedding is deliberately an offline development
    fallback. A production embedding adapter can replace ``embed`` without
    changing the KnowledgeStore contract.
    """

    dimension = 32

    def __init__(self, root: str | Path, embedder: Callable[[list[str]], list[list[float]]] | None = None) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.embedder = embedder
        self.fallback_path = self.root / "chunks.jsonl"
        self._lancedb = None
        self._table = None
        try:
            import lancedb

            self._lancedb = lancedb
            database = lancedb.connect(str(self.root / "lancedb"))
            try:
                self._table = database.open_table("knowledge_chunks")
            except Exception:
                self._table = None
        except ImportError:
            pass

    @classmethod
    def embed(cls, text: str) -> list[float]:
        vector = [0.0] * cls.dimension
        encoded = text.encode("utf-8", errors="ignore")
        for index in range(0, len(encoded), 2):
            digest = hashlib.sha256(encoded[index : index + 2]).digest()
            slot = int.from_bytes(digest[:2], "big") % cls.dimension
            vector[slot] += 1.0 if digest[2] % 2 else -1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    def add(self, records: list[dict[str, Any]]) -> None:
        if not records:
            return
        vectors = self._embed_many([str(record.get("text", "")) for record in records])
        normalized = [{**record, "vector": vectors[index]} for index, record in enumerate(records)]
        if self._lancedb:
            database = self._lancedb.connect(str(self.root / "lancedb"))
            if self._table is None:
                self._table = database.create_table("knowledge_chunks", normalized)
            else:
                self._table.add(normalized)
            return
        with self.fallback_path.open("a", encoding="utf-8") as stream:
            for record in normalized:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")

    def remove(self, chunk_ids: list[str]) -> None:
        """Remove indexed chunks after their source document is deleted."""
        ids = {str(chunk_id) for chunk_id in chunk_ids if str(chunk_id)}
        if not ids:
            return
        if self._table is not None:
            # UUIDs are generated locally, so quoting and escaping here is
            # deterministic. LanceDB may not be installed in offline mode;
            # fallback storage is handled below.
            quoted = ", ".join(f"'{chunk_id.replace(chr(39), chr(39) + chr(39))}'" for chunk_id in ids)
            try:
                self._table.delete(f"chunk_id IN ({quoted})")
                return
            except Exception:
                # Keep deletion best-effort for older LanceDB releases whose
                # table implementation does not expose delete().
                pass
        if not self.fallback_path.exists():
            return
        kept = []
        for line in self.fallback_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                kept.append(line)
                continue
            if str(record.get("chunk_id", "")) not in ids:
                kept.append(line)
        temporary = self.fallback_path.with_suffix(".tmp")
        temporary.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
        temporary.replace(self.fallback_path)

    def search(self, *, project_id: str, query: str, limit: int = 8) -> list[dict[str, Any]]:
        vector = self._embed_many([query])[0]
        if self._table is not None:
            return [row for row in self._table.search(vector).where(f"project_id = '{project_id}'").limit(limit).to_list()]
        if not self.fallback_path.exists():
            return []
        candidates = []
        for line in self.fallback_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get("project_id") != project_id:
                continue
            score = sum(left * right for left, right in zip(vector, record.get("vector", [])))
            candidates.append({**record, "_distance": 1 - score})
        return sorted(candidates, key=lambda item: item["_distance"])[:limit]

    def _embed_many(self, texts: list[str]) -> list[list[float]]:
        if self.embedder is None:
            return [self.embed(text) for text in texts]
        vectors = self.embedder(texts)
        if len(vectors) != len(texts):
            raise ValueError("Embedding Provider 返回数量与输入不一致")
        normalized = [[float(value) for value in vector] for vector in vectors]
        if any(not vector for vector in normalized):
            raise ValueError("Embedding Provider 返回空向量")
        return normalized
