from __future__ import annotations

import hashlib
import html
import ipaddress
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from uuid import uuid4


class ResearchImportError(RuntimeError):
    pass


_SENSITIVE_QUERY_KEYS = {
    "key", "api_key", "apikey", "token", "access_token", "secret", "signature", "sig",
    "x-amz-signature", "x-amz-credential", "x-goog-api-key",
}
_MAX_SOURCE_BYTES = 5 * 1024 * 1024


def _is_non_public_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return whether an address must never be fetched by the research importer."""
    candidates = [address]
    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None:
        candidates.append(mapped)
    return any(
        candidate.is_private
        or candidate.is_loopback
        or candidate.is_link_local
        or candidate.is_reserved
        or candidate.is_multicast
        or candidate.is_unspecified
        for candidate in candidates
    )


def _host_resolves_to_non_public(hostname: str) -> bool:
    """Resolve a hostname before fetching so a public-looking URL cannot target a LAN host."""
    normalized = hostname.strip("[]").rstrip(".").lower()
    if not normalized:
        return True
    try:
        return _is_non_public_address(ipaddress.ip_address(normalized))
    except ValueError:
        try:
            addresses = socket.getaddrinfo(normalized, None, type=socket.SOCK_STREAM)
        except socket.gaierror:
            # Keep unknown/public DNS failures as normal fetch errors; do not make
            # importing a URL depend on a second, stricter DNS policy.
            return False
        for item in addresses:
            sockaddr = item[4] if len(item) > 4 else ()
            resolved = sockaddr[0] if sockaddr else ""
            try:
                if resolved and _is_non_public_address(ipaddress.ip_address(resolved)):
                    return True
            except ValueError:
                continue
    return False


def safe_source_uri(value: str) -> str:
    """Normalize a source URL and remove query credentials before persistence."""
    try:
        parts = urllib.parse.urlsplit(str(value).strip())
        hostname = (parts.hostname or "").lower()
    except ValueError as error:
        raise ResearchImportError("研究来源 URL 格式无效") from error
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ResearchImportError("研究来源必须是 http/https URL")
    if parts.username or parts.password:
        raise ResearchImportError("研究来源 URL 不能包含用户名或密码")
    if hostname in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}:
        raise ResearchImportError("为避免本地回环访问，研究来源不允许使用 localhost/127.0.0.1")
    if _host_resolves_to_non_public(hostname):
        raise ResearchImportError("为避免 SSRF，研究来源不能指向私网、回环、链路本地或保留地址")
    query = [(key, item) for key, item in urllib.parse.parse_qsl(parts.query, keep_blank_values=True) if key.lower() not in _SENSITIVE_QUERY_KEYS]
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path or "/", urllib.parse.urlencode(query), ""))


class _HTMLTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self._in_title = False
        self._skip_depth = 0
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag == "title":
            self._in_title = True
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self._in_title = False
        if tag in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        text = html.unescape(data).strip()
        if not text or self._skip_depth:
            return
        if self._in_title:
            self.title += f" {text}"
        else:
            self._chunks.append(text)

    @property
    def text(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self._chunks)).strip()


class ResearchStore:
    """Project-scoped research source registry with explicit URL snapshots."""

    def __init__(self, store, knowledge_store=None) -> None:
        self.store = store
        self.knowledge_store = knowledge_store

    def import_url(self, *, project_id: str, uri: str, title: str | None = None, rights_status: str = "unknown", preview_image_url: str | None = None) -> dict[str, Any]:
        project = self.store.get_project(project_id)
        if project is None:
            raise ResearchImportError("项目不存在")
        safe_uri = safe_source_uri(uri)
        safe_preview_image_url = None
        if preview_image_url:
            try:
                safe_preview_image_url = safe_source_uri(preview_image_url)
            except ResearchImportError:
                # Search providers occasionally return data URLs, tracking
                # URLs, or a private thumbnail host. Keep the source page but
                # never persist an unsafe/non-network preview reference.
                safe_preview_image_url = None
        if rights_status not in {"unknown", "review", "allowed", "restricted"}:
            raise ResearchImportError("rightsStatus 必须是 unknown/review/allowed/restricted")
        content, content_type = self._fetch(safe_uri)
        source_id = str(uuid4())
        suffix = ".html" if "html" in content_type or content.lstrip().lower().startswith((b"<!doctype html", b"<html")) else ".bin"
        filename = f"{source_id}{suffix}"
        relative = f"research/sources/{filename}"
        snapshot = Path(project["rootPath"]) / relative
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_bytes(content)
        checksum = hashlib.sha256(content).hexdigest()
        extracted_text, parsed_title = self._extract(content, content_type)
        source_title = (title or parsed_title or urllib.parse.urlsplit(safe_uri).netloc).strip()[:300]
        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
        with self.store._connect() as connection:
            connection.execute(
                "INSERT INTO research_sources (id, project_id, source_type, uri, title, fetched_at, checksum, rights_status, snapshot_path, preview_image_url) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (source_id, project_id, "web", safe_uri, source_title, now, checksum, rights_status, relative, safe_preview_image_url),
            )
        indexed = None
        if extracted_text and self.knowledge_store is not None:
            indexed = self.knowledge_store.ingest_text(project_id=project_id, path_relative=relative, text=extracted_text, title=source_title)
        return {
            "id": source_id,
            "projectId": project_id,
            "sourceType": "web",
            "uri": safe_uri,
            "title": source_title,
            "checksum": checksum,
            "rightsStatus": rights_status,
            "snapshotPath": relative,
            "previewImageUrl": safe_preview_image_url,
            "contentType": content_type,
            "textLength": len(extracted_text),
            "indexed": indexed,
            "fetchedAt": now,
        }

    def list_sources(self, project_id: str) -> list[dict[str, Any]]:
        with self.store._connect() as connection:
            rows = connection.execute(
                "SELECT id, source_type, uri, title, author, published_at, fetched_at, checksum, rights_status, snapshot_path, preview_image_url FROM research_sources WHERE project_id = ? ORDER BY fetched_at DESC",
                (project_id,),
            ).fetchall()
        return [
            {
                "id": row["id"], "sourceType": row["source_type"], "uri": row["uri"], "title": row["title"],
                "author": row["author"], "publishedAt": row["published_at"], "fetchedAt": row["fetched_at"],
                "checksum": row["checksum"], "rightsStatus": row["rights_status"], "snapshotPath": row["snapshot_path"],
                "previewImageUrl": row["preview_image_url"] if "preview_image_url" in row.keys() else None,
            }
            for row in rows
        ]

    def create_note(self, *, project_id: str, source_id: str | None, category: str, body_md: str, claims: list[dict[str, Any]] | None = None, confidence: float | None = None) -> dict[str, Any]:
        if self.store.get_project(project_id) is None:
            raise ResearchImportError("项目不存在")
        if source_id:
            with self.store._connect() as connection:
                exists = connection.execute("SELECT 1 FROM research_sources WHERE id = ? AND project_id = ?", (source_id, project_id)).fetchone()
            if exists is None:
                raise ResearchImportError("研究来源不存在或不属于当前项目")
        category = str(category or "general").strip() or "general"
        body_md = str(body_md or "").strip()
        if not body_md:
            raise ResearchImportError("研究笔记不能为空")
        if confidence is not None and not 0 <= float(confidence) <= 1:
            raise ResearchImportError("confidence 必须在 0 到 1 之间")
        note_id = str(uuid4())
        with self.store._connect() as connection:
            connection.execute(
                "INSERT INTO research_notes (id, project_id, source_id, category, body_md, claims_json, confidence) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (note_id, project_id, source_id, category, body_md, __import__("json").dumps(claims or [], ensure_ascii=False), confidence),
            )
        return self._note_by_id(note_id)

    def list_notes(self, project_id: str) -> list[dict[str, Any]]:
        with self.store._connect() as connection:
            rows = connection.execute("SELECT id, source_id, category, body_md, claims_json, confidence FROM research_notes WHERE project_id = ? ORDER BY rowid DESC", (project_id,)).fetchall()
        return [self._note_dict(row) for row in rows]

    def _note_by_id(self, note_id: str) -> dict[str, Any]:
        with self.store._connect() as connection:
            row = connection.execute("SELECT id, source_id, category, body_md, claims_json, confidence FROM research_notes WHERE id = ?", (note_id,)).fetchone()
        return self._note_dict(row)

    @staticmethod
    def _note_dict(row) -> dict[str, Any]:
        return {"id": row["id"], "sourceId": row["source_id"], "category": row["category"], "bodyMd": row["body_md"], "claims": __import__("json").loads(row["claims_json"] or "[]"), "confidence": row["confidence"]}

    @staticmethod
    def _fetch(uri: str) -> tuple[bytes, str]:
        request = urllib.request.Request(uri, headers={"User-Agent": "AI-Creative-Studio/0.1 research-ingest"}, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                content_type = response.headers.get("Content-Type", "application/octet-stream").split(";", 1)[0].strip().lower()
                chunks: list[bytes] = []
                total = 0
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > _MAX_SOURCE_BYTES:
                        raise ResearchImportError("研究来源超过 5MB 大小上限")
                    chunks.append(chunk)
        except ResearchImportError:
            raise
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as error:
            raise ResearchImportError(f"研究来源抓取失败: {error}") from error
        return b"".join(chunks), content_type

    @staticmethod
    def _extract(content: bytes, content_type: str) -> tuple[str, str]:
        if "html" not in content_type and not content.lstrip().lower().startswith((b"<!doctype html", b"<html")):
            if not (content_type.startswith("text/") or content_type in {"application/json", "application/xml", "text/xml"}):
                return "", ""
            return content.decode("utf-8", errors="replace"), ""
        parser = _HTMLTextParser()
        parser.feed(content.decode("utf-8", errors="replace"))
        return parser.text, re.sub(r"\s+", " ", parser.title).strip()
