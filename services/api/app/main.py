from __future__ import annotations

import os
import asyncio
import re
import json
import base64
import logging
import mimetypes
import urllib.error
import urllib.request
from io import BytesIO
from math import ceil
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from .cors import CacheAwareCORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from .model_catalog import ModelCatalog
from .model_config import ModelSettings, EndpointModel, DEFAULT_DRAFT_IMAGE_MODEL, DEFAULT_IMAGE_MODEL, DEFAULT_VIDEO_MODEL
from .closeai_catalog import (
    CLOSEAI_CATALOG_CREDENTIAL,
    is_closeai_base_url,
    management_models_url,
    model_aliases,
    normalize_management_response,
)
from .model_router import MediaModelRouter
from .billing import BillingService, billing_scope

from .assets import AssetStore
from .achievements import AchievementService
from .design_tools import DesignToolError, DesignToolRegistry
from .evaluations import AIEvaluator
from .knowledge import KnowledgeStore
from .models import Project, ProjectCreate, ProjectUpdate, new_project
from .providers.http import ProviderError
from .image_output import prepare_image_output, reject_svg_output
from .providers.registry import ProviderRegistry
from .prompts import PromptService
from .research import ResearchImportError, ResearchStore
from .storage import ProjectStore, slugify
from .schedules import SchedulePlanRequest, ScheduleService, ScheduleUpdate
from .task_runtime import TaskRequestConflict, TaskRuntime
from .project_titles import ProjectTitleService
from .project_overview import project_overviews, ProjectPreviews, library_assets
from .canvas import CanvasConflict
from .video import VideoJobService
from .beta_testing import BetaTesting, router as testing_router
from .skills import SkillError
from .skill_routes import router as skills_router
from .reference_routes import router as reference_router
from .drawing import router as drawing_router
from .mascot import MascotService
from .mascot_routes import router as mascot_router
from .storage_management import router as storage_management_router
from .reference_library import ReferenceLibraryStore, ReferenceError
from .reference_analysis import ReferenceAnalyzer


logger = logging.getLogger(__name__)


def get_store() -> ProjectStore:
    return app.state.store


def get_tasks() -> TaskRuntime:
    return app.state.tasks


@asynccontextmanager
async def lifespan(application: FastAPI):
    application.state.store = ProjectStore(os.environ.get("AICS_WORKSPACE_ROOT"))
    application.state.assets = AssetStore(application.state.store)
    application.state.achievements = AchievementService(application.state.store)
    application.state.providers = ProviderRegistry()
    application.state.model_catalog = ModelCatalog(application.state.store)
    application.state.billing = BillingService(application.state.store, application.state.model_catalog)
    from .evolink_billing import EvoLinkReconciler
    application.state.evolink_billing = EvoLinkReconciler(application.state.billing, application.state.providers.credentials)
    application.state.providers.catalog = application.state.model_catalog
    application.state.providers.billing = application.state.billing
    application.state.mascot = MascotService(application.state.store, application.state.providers)
    embedding_provider = None
    embedding_key = os.environ.get("AICS_EMBEDDING_PROVIDER", "").strip()
    if embedding_key and embedding_key not in {"local", "local-deterministic"}:
        embedding_provider = application.state.providers.embedding(
            embedding_key,
            base_url=os.environ.get("AICS_EMBEDDING_BASE_URL") or None,
            model=os.environ.get("AICS_EMBEDDING_MODEL") or None,
        )
    application.state.knowledge = KnowledgeStore(application.state.store, embedding_provider=embedding_provider)
    application.state.research = ResearchStore(application.state.store, knowledge_store=application.state.knowledge)
    application.state.videos = VideoJobService(application.state.store)
    application.state.design_tools = DesignToolRegistry(
        application.state.store,
        knowledge_store=application.state.knowledge,
        research_store=application.state.research,
        asset_store=application.state.assets,
        provider_registry=application.state.providers,
        video_service=application.state.videos,
    )
    from .image_jobs import ImageJobs
    application.state.image_jobs = ImageJobs(application.state.store, application.state.design_tools.executions)
    application.state.audio_jobs = ImageJobs(application.state.store, application.state.design_tools.executions, 'generate_audio')
    application.state.references = ReferenceLibraryStore(application.state.store)
    application.state.references.migrate(application.state.knowledge)
    application.state.reference_analyzer = ReferenceAnalyzer(application.state.references, application.state.providers, embedding_provider)
    application.state.design_tools.reference_library = application.state.references
    application.state.design_tools.reference_analyzer = application.state.reference_analyzer
    if os.environ.get("AICS_TEST_MODE") != "1":
        application.state.reference_analyzer.start()
    application.state.skills = application.state.design_tools.skills
    from .bundled_skills import install_bundled_skills
    install_bundled_skills(application.state.skills)
    from .cad import cad_service
    application.state.cad = cad_service(application.state.store)
    if os.environ.get("AICS_TEST_MODE") != "1":
        import threading
        application.state.cad_health_thread = threading.Thread(target=application.state.cad.check_health, daemon=True)
        application.state.cad_health_thread.start()
    application.state.videos.providers = application.state.providers
    application.state.videos.assets = application.state.assets
    application.state.videos.canvas = application.state.design_tools.canvas_store
    application.state.project_previews = ProjectPreviews(application.state.store, application.state.design_tools.canvas_store)
    application.state.evaluator = AIEvaluator(application.state.providers)
    application.state.tasks = TaskRuntime(application.state.store, knowledge_store=application.state.knowledge, provider_registry=application.state.providers, research_store=application.state.research, asset_store=application.state.assets)
    application.state.tasks.reference_registry = application.state.design_tools
    from .delivery import DeliveryService
    from .late_image_results import sync_late_images
    image_delivery = DeliveryService(application.state.store, application.state.assets, application.state.design_tools.canvas_store)
    def sync_media_results(project_id, task_id):
        for jobs in (application.state.image_jobs, application.state.audio_jobs):
            sync_late_images(jobs, image_delivery, project_id, task_id)
    application.state.tasks.sync_image_results = sync_media_results
    application.state.image_jobs.on_settled = application.state.tasks.sync_image_results
    application.state.audio_jobs.on_settled = application.state.tasks.sync_image_results
    application.state.testing = BetaTesting(application.state.store, application.state.design_tools.canvas_store)
    application.state.testing.start_logging()
    application.state.design_tools.trace = application.state.tasks._append_trace
    application.state.project_titles = ProjectTitleService(application.state.store, application.state.providers)
    application.state.tasks.project_titles = application.state.project_titles
    from .server import install_shutdown_hook
    restore_shutdown_hook = install_shutdown_hook(application.state.tasks)
    application.state.tasks.recover_pending()
    if os.environ.get("AICS_TEST_MODE") != "1":
        application.state.videos.start()
    application.state.prompts = PromptService(application.state.store)
    application.state.schedules = ScheduleService(application.state.store, application.state.tasks, application.state.providers)
    application.state.design_tools.schedule_service = application.state.schedules
    application.state.schedules.start()
    try:
        yield
    finally:
        application.state.reference_analyzer.stop()
        application.state.cad.shutdown()
        if getattr(application.state, 'cad_health_thread', None):
            application.state.cad_health_thread.join(timeout=5)
        application.state.tasks.prepare_shutdown()
        restore_shutdown_hook()
        application.state.project_titles.stop()
        application.state.schedules.stop()
        application.state.videos.stop()
        application.state.testing.close()


CORS_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]
# The portable development launcher selects a free loopback port. Only that
# explicitly configured local origin is added; remote origins stay disallowed.
_dev_web_origin = os.environ.get("AICS_DEV_WEB_ORIGIN", "")
if re.fullmatch(r"http://(?:127\.0\.0\.1|localhost):[0-9]{1,5}", _dev_web_origin):
    if 0 < int(_dev_web_origin.rsplit(":", 1)[1]) <= 65535 and _dev_web_origin not in CORS_ORIGINS:
        CORS_ORIGINS.append(_dev_web_origin)

app = FastAPI(title="MxinspireX API", version="0.1.0", lifespan=lifespan)
app.include_router(testing_router)
app.include_router(skills_router)
app.include_router(reference_router)
app.include_router(drawing_router)
app.include_router(mascot_router)
app.include_router(storage_management_router)

@app.exception_handler(ReferenceError)
async def reference_error_handler(request: Request, error: ReferenceError):
    return JSONResponse(status_code=422, content={"detail": str(error)})



@app.exception_handler(SkillError)
async def skill_error_handler(request: Request, error: SkillError):
    return JSONResponse(status_code=error.status_code, content={'detail': str(error)})
from .cad_routes import router as cad_router
app.include_router(cad_router)
app.add_middleware(
    CacheAwareCORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    # The renderer may send standard fetch headers (for example Accept) and
    # future integrations can add their own request headers.  This is a local
    # desktop API, so allowing the requested headers keeps preflight handling
    # stable without widening the set of permitted origins.
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, error: Exception):
    """Keep malformed requests and unexpected provider responses observable.

    Route handlers still translate expected domain and provider failures into
    their specific status codes. This last-resort boundary prevents an
    unhandled Python exception from turning into an HTML response that the
    renderer interprets as a dead API, while keeping the detailed traceback in
    the sidecar log instead of returning it to the browser.
    """
    logger.exception("Unhandled API request failure: %s %s", request.method, request.url.path)
    response = JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "服务器处理请求失败，请重试或查看任务日志"},
    )
    # Starlette's ServerErrorMiddleware invokes this handler outside the CORS
    # middleware. Apply the same origin allowlist to its last-resort response.
    origin = request.headers.get("origin")
    if origin in CORS_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
    response.headers.add_vary_header("Origin")
    return response


Store = Annotated[ProjectStore, Depends(get_store)]
Tasks = Annotated[TaskRuntime, Depends(get_tasks)]


@app.get("/api/schedules")
def list_schedules():
    return app.state.schedules.list()


@app.post("/api/schedules/arrange")
def arrange_schedules(payload: SchedulePlanRequest):
    try:
        return app.state.schedules.arrange(payload)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except ProviderError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@app.post("/api/schedules/arrange/stream")
async def arrange_schedules_stream(payload: SchedulePlanRequest):
    from .schedule_stream import schedule_plan_events
    return StreamingResponse(schedule_plan_events(app.state.schedules, payload), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.put("/api/schedules/{schedule_id}")
def update_schedule(schedule_id: str, payload: ScheduleUpdate):
    try:
        return app.state.schedules.update(schedule_id, spec=payload)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="定时任务不存在") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/api/schedules/{schedule_id}/status")
def set_schedule_status(schedule_id: str, payload: dict):
    target = payload.get("status")
    if target not in {"active", "paused", "deleted"}:
        raise HTTPException(status_code=422, detail="无效的定时任务状态")
    try:
        return app.state.schedules.update(schedule_id, status=target)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="定时任务不存在") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/api/schedule-notifications")
def schedule_notifications(unread: bool = False):
    return app.state.schedules.notifications(unread=unread)


@app.post("/api/schedule-notifications/desktop")
def claim_desktop_schedule_notifications():
    return app.state.schedules.claim_desktop_notifications()


@app.post("/api/schedule-notifications/{notification_id}/read")
def read_schedule_notification(notification_id: str):
    app.state.schedules.mark_read(notification_id)
    return {"ok": True}


_SENSITIVE_ENDPOINT_QUERY_KEYS = {
    "key", "api_key", "apikey", "token", "access_token", "secret", "signature", "sig",
    "x-amz-signature", "x-amz-credential", "x-goog-api-key",
}


def _object_field(payload: dict, key: str, *, label: str | None = None) -> dict:
    """Read a JSON object field without allowing list/string type errors."""
    value = payload.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{label or key} 必须是对象",
        )
    return dict(value)


def _json_object(value, fallback: dict | None = None) -> dict:
    """Decode persisted JSON defensively so a damaged row cannot kill a route."""
    default = dict(fallback or {})
    try:
        parsed = json.loads(value) if value else default
    except (TypeError, json.JSONDecodeError):
        return default
    return dict(parsed) if isinstance(parsed, dict) else default


def _default_openai_base_url() -> str:
    configured = os.environ.get("AICS_OPENAI_COMPATIBLE_BASE_URL", "https://api.openai-proxy.org").strip().rstrip("/")
    if not configured:
        configured = "https://api.openai-proxy.org"
    return configured if configured.endswith("/v1") else f"{configured}/v1"


def _openai_base_url(value: str | None) -> str:
    """Normalize either a gateway root or an OpenAI-compatible /v1 URL."""
    clean = (value or _default_openai_base_url()).strip().rstrip("/")
    if not clean:
        clean = _default_openai_base_url()
    return clean if clean.endswith("/v1") else f"{clean}/v1"


def _default_openrouter_base_url() -> str:
    configured = os.environ.get("AICS_OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").strip().rstrip("/")
    return configured or "https://openrouter.ai/api/v1"


def _default_ollama_base_url() -> str:
    configured = os.environ.get("AICS_OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1").strip().rstrip("/")
    if not configured:
        configured = "http://127.0.0.1:11434/v1"
    return configured if configured.endswith("/v1") else f"{configured}/v1"


def _provider_base_url(provider_key: str, value: str | None = None) -> str:
    """Normalize a provider URL while keeping OpenRouter the product default."""
    if value and str(value).strip():
        return _openai_base_url(str(value))
    if provider_key == "openrouter":
        return _default_openrouter_base_url()
    if provider_key == "ollama":
        return _default_ollama_base_url()
    if provider_key == "evolink":
        from .evolink import EVOLINK_BASE_URL
        return EVOLINK_BASE_URL
    return _openai_base_url(None)


def _safe_endpoint(value: str | None) -> str | None:
    """Keep provider routes portable without persisting query-string secrets."""
    if not value:
        return None
    try:
        parts = urlsplit(str(value))
        safe_query = [(key, item) for key, item in parse_qsl(parts.query, keep_blank_values=True) if key.lower() not in _SENSITIVE_ENDPOINT_QUERY_KEYS]
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(safe_query), ""))
    except ValueError:
        return str(value).split("#", 1)[0].split("?", 1)[0]


@app.get("/health")
def health() -> dict[str, object]:
    settings = app.state.model_catalog.settings()
    return {
        "status": "ok",
        "service": "aics-api",
        "agentRuntimeRevision": "delivery-identity-20261022-v16",
        "buildRevision": os.environ.get("AICS_BUILD_REVISION") or os.environ.get("AICS_BUILD_VERSION") or "development",
        "modelDefaultsVersion": settings.defaultsVersion,
        "preferredTextProvider": settings.preferredTextProvider.model_dump(mode="json"),
    }


@app.get("/api/providers")
def list_providers():
    return app.state.providers.list()


@app.get("/api/knowledge/embedding-status")
def embedding_status():
    return app.state.knowledge.embedding_status()


@app.post("/api/knowledge/text", status_code=status.HTTP_201_CREATED)
def ingest_global_knowledge(payload: dict):
    text = str(payload.get("text", ""))
    if not text.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="text 不能为空")
    return app.state.knowledge.ingest_global_text(
        path_relative=str(payload.get("pathRelative", "inline.txt")),
        text=text,
        title=payload.get("title"),
        parser="text",
    )


@app.post("/api/knowledge/upload", status_code=status.HTTP_201_CREATED)
async def upload_global_knowledge(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="文件名不能为空")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="文件不能为空")
    if len(content) > 25 * 1024 * 1024:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="单个知识库文件不能超过 25 MB")
    return app.state.knowledge.ingest_global_file(filename=file.filename, content=content)


@app.get("/api/knowledge/documents")
def list_global_knowledge_documents():
    return app.state.knowledge.list_global_documents()


@app.get("/api/knowledge/documents/{document_id}/content")
def get_global_knowledge_content(document_id: str, store: Store):
    document = next((item for item in app.state.knowledge.list_global_documents() if item["id"] == document_id), None)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="知识文档不存在")
    root = (store.workspace_root / "knowledge" / "documents").resolve()
    path = (store.workspace_root / document["pathRelative"]).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="知识文档不存在")
    return FileResponse(path, filename=document["title"], media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream", headers={"X-Content-Type-Options": "nosniff"})


@app.get("/api/knowledge/documents/{document_id}/structure")
def get_global_knowledge_structure(document_id: str, cursor: int = 0, limit: int = 30, locator: str | None = None):
    try:
        return app.state.knowledge.read_document(scope="global", document_id=document_id, cursor=cursor, limit=limit, locator=locator)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get("/api/knowledge/documents/{document_id}/parts")
def list_global_knowledge_parts(document_id: str, cursor: int = 0, limit: int = 100, kind: str | None = None):
    try:
        return app.state.knowledge.list_parts(scope="global", document_id=document_id, cursor=cursor, limit=limit, kind=kind)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get("/api/knowledge/documents/{document_id}/parts/{part_id}/content")
def get_global_knowledge_part(document_id: str, part_id: str, variant: str = "preview"):
    try:
        content, mime, filename = app.state.knowledge.part_content(scope="global", document_id=document_id, part_id=part_id, variant=variant)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return Response(content, media_type=mime, headers={"Content-Disposition": f'inline; filename="{Path(filename).name}"', "X-Content-Type-Options": "nosniff"})


@app.delete("/api/knowledge/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_global_knowledge_document(document_id: str):
    try:
        deleted = app.state.knowledge.delete_global_document(document_id=document_id)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
    if deleted is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="知识文档不存在")
    return None


@app.post("/api/knowledge/reindex")
def reindex_global_knowledge():
    return app.state.knowledge.reindex_global()


@app.get("/api/knowledge/search")
def search_global_knowledge(q: str):
    if not q.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="q 不能为空")
    return app.state.knowledge.global_search(query=q)


@app.get("/api/knowledge/vector-search")
def vector_search_global_knowledge(q: str):
    if not q.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="q 不能为空")
    return app.state.knowledge.global_vector_search(query=q)


@app.get("/api/projects/{project_id}/research/sources")
def list_research_sources(project_id: str, store: Store):
    if store.get_project(project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    return app.state.research.list_sources(project_id)


@app.post("/api/projects/{project_id}/research/sources/import-url", status_code=status.HTTP_201_CREATED)
def import_research_source(project_id: str, payload: dict, store: Store):
    if store.get_project(project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    try:
        return app.state.research.import_url(
            project_id=project_id,
            uri=str(payload.get("uri", "")),
            title=payload.get("title"),
            rights_status=str(payload.get("rightsStatus", "unknown")),
            preview_image_url=str(payload.get("previewImageUrl")) if payload.get("previewImageUrl") else None,
        )
    except ResearchImportError as error:
        detail = str(error)
        code = status.HTTP_502_BAD_GATEWAY if "抓取失败" in detail else status.HTTP_422_UNPROCESSABLE_ENTITY
        raise HTTPException(status_code=code, detail=detail) from error


@app.get("/api/projects/{project_id}/research/notes")
def list_research_notes(project_id: str, store: Store):
    if store.get_project(project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    return app.state.research.list_notes(project_id)


@app.post("/api/projects/{project_id}/research/notes", status_code=status.HTTP_201_CREATED)
def create_research_note(project_id: str, payload: dict, store: Store):
    if store.get_project(project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    try:
        confidence = payload.get("confidence")
        return app.state.research.create_note(
            project_id=project_id,
            source_id=payload.get("sourceId"),
            category=str(payload.get("category", "general")),
            body_md=str(payload.get("bodyMd", "")),
            claims=payload.get("claims") or [],
            confidence=float(confidence) if confidence is not None else None,
        )
    except ResearchImportError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error


@app.post("/api/providers/{provider_key}/credential", status_code=status.HTTP_204_NO_CONTENT)
def set_provider_credential(provider_key: str, payload: dict):
    secret = str(payload.get("secret", ""))
    if not secret:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="secret 不能为空")
    try:
        app.state.providers.set_credential(provider_key, secret)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(error)) from error
    return None


@app.post("/api/providers/{provider_key}/text")
def provider_text(provider_key: str, payload: dict):
    try:
        provider = app.state.providers.text(provider_key, base_url=_provider_base_url(provider_key, str(payload["baseUrl"]) if payload.get("baseUrl") else None), model=str(payload["model"]) if payload.get("model") else None)
        attachments = _resolve_provider_attachments(payload.get("assets") or payload.get("assetIds") or [])
        return {"provider": provider_key, "model": payload.get("model"), "content": provider.complete(system=str(payload.get("system", "")), prompt=str(payload.get("prompt", "")), model=payload.get("model"), attachments=attachments)}
    except ProviderError as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error


def _resolve_provider_attachments(raw_refs: object) -> list[dict[str, object]]:
    """Resolve local asset references into safe text/multimodal attachments.

    The renderer sends only project/asset ids. File bytes stay in the local
    workspace until this function prepares the provider request, which keeps
    the public API free of arbitrary filesystem paths.
    """
    if not isinstance(raw_refs, list):
        return []
    attachments: list[dict[str, object]] = []
    from .vision_preview import MAX_ITEMS, MAX_TOTAL_BYTES, make_vision_preview
    total_visual_bytes = 0
    for raw in raw_refs[:MAX_ITEMS]:
        if isinstance(raw, str):
            continue
        if not isinstance(raw, dict):
            continue
        project_id = str(raw.get("projectId") or raw.get("project_id") or "").strip()
        asset_id = str(raw.get("id") or raw.get("assetId") or "").strip()
        if not project_id or not asset_id:
            continue
        asset = app.state.assets.get_asset(project_id=project_id, asset_id=asset_id)
        if not asset:
            continue
        path = Path(str(asset.get("absolutePath") or ""))
        if not path.is_file():
            continue
        try:
            content = path.read_bytes()
        except OSError:
            continue
        mime = str(asset.get("mime") or "application/octet-stream")
        item: dict[str, object] = {"filename": path.name, "mime": mime, "byteSize": len(content), "kind": asset.get("kind")}
        if mime.startswith("image/"):
            preview = make_vision_preview(content)
            if preview and total_visual_bytes + preview["byteSize"] <= MAX_TOTAL_BYTES:
                item["data"] = base64.b64encode(preview.pop("content")).decode("ascii")
                item["mime"] = preview["mime"]
                item["visionPreview"] = {**preview, "normalized": True}
                total_visual_bytes += preview["byteSize"]
            else:
                item["text"] = "图像已保留为资产引用；首轮视觉预览超出 8 MB 预算，可按资产 ID 再检查。"
        elif len(content) > 8 * 1024 * 1024:
            item["text"] = "文件过大，已保留本地引用，未直接上传内容。"
        else:
            try:
                suffix = path.suffix.lower()
                if suffix in {".txt", ".md", ".markdown", ".csv", ".json", ".html", ".htm"}:
                    item["text"] = content.decode("utf-8", errors="replace")
                else:
                    extracted, _parser, warning = app.state.knowledge._extract_text(suffix, content)
                    item["text"] = extracted or warning or "该文件没有可提取的文本内容。"
            except Exception:
                item["text"] = "该文件已关联，但本地解析器未能提取文本。"
        attachments.append(item)
    return attachments


@app.middleware("http")
async def scope_usage(request: Request, call_next):
    parts = request.url.path.split("/")
    project_id = parts[3] if len(parts) > 3 and parts[1:3] == ["api", "projects"] else None
    with billing_scope(project_id=project_id):
        return await call_next(request)


@app.get("/api/providers/model-catalog")
def read_model_catalog(provider: str = "openrouter", baseUrl: str = ""):
    base_url = _provider_base_url(provider, baseUrl)
    return app.state.model_catalog.view(provider, base_url)


@app.get("/api/model-settings")
def get_model_settings():
    return app.state.model_catalog.settings().model_dump(mode="json")


@app.put("/api/model-settings")
def save_model_settings(payload: ModelSettings):
    prices = {}
    for key, price in payload.prices.items():
        try:
            provider, endpoint, model = json.loads(key)
            EndpointModel(provider=provider, baseUrl=endpoint, model=model)
            normalized = _provider_base_url(provider, endpoint) if provider in {"openrouter", "evolink", "openai-compatible", "ollama"} else endpoint.rstrip("/")
            prices[app.state.model_catalog.price_key(provider, normalized, model)] = price
        except (ValueError, TypeError):
            raise HTTPException(status_code=422, detail="价格必须绑定有效的服务、地址和模型")
    payload.prices = prices
    return app.state.model_catalog.save_settings(payload).model_dump(mode="json")


@app.put("/api/model-settings/preferred-provider")
def save_preferred_text_provider(payload: dict):
    key = str(payload.get('key') or '').strip()
    if not key:
        raise HTTPException(status_code=422, detail="Provider key 不能为空")
    try:
        endpoint = EndpointModel(baseUrl=str(payload.get('baseUrl') or ''))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    settings = app.state.model_catalog.set_preferred_text_provider(key, endpoint.baseUrl)
    return settings.preferredTextProvider.model_dump(mode="json")


@app.get("/api/credits")
def credit_summary(projectId: str | None = None):
    return app.state.billing.summary(projectId)


@app.get("/api/credits/prices")
def credit_prices():
    from .credit_reporting import price_catalog
    return price_catalog(app.state.model_catalog)


@app.post('/api/billing/evolink/reconcile')
def reconcile_evolink_billing():
    return app.state.evolink_billing.reconcile()


@app.put("/api/credits/prices")
def save_credit_price(payload: dict):
    from .model_config import ModelPrice
    try:
        endpoint = EndpointModel(**{key: payload.get(key, '') for key in ('provider', 'baseUrl', 'model')})
        price = ModelPrice(**payload.get('price', {}))
        if not endpoint.provider or not endpoint.baseUrl or not endpoint.model or len(price.model_dump(exclude_none=True)) < 2:
            raise ValueError('请填写服务、模型和至少一个单价')
    except (ValueError, TypeError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    catalog = app.state.model_catalog
    settings = catalog.settings()
    settings.prices[catalog.price_key(endpoint.provider, endpoint.baseUrl, endpoint.model)] = price
    catalog.save_settings(settings)
    return {'saved': True, 'price': catalog.price(endpoint.provider, endpoint.baseUrl, endpoint.model)}


@app.get("/api/tasks/{task_id}/model-trace")
def get_model_trace(task_id: str):
    from .model_router import RouteTrace
    return RouteTrace(app.state.store).list(task_id)


@app.post("/api/providers/openai-compatible/detect")
def detect_openai_compatible_models(payload: dict):
    """Probe the gateway's standard /v1/models endpoint without exposing secrets.

    The response keeps the complete model catalog, including capability
    metadata returned by OpenRouter and compatible gateways. The renderer can
    cache this metadata locally and still fall back to the legacy ID arrays.
    """
    provider_key = str(payload.get("provider") or "openrouter").strip()
    provider_spec = next((item for item in app.state.providers.list() if item["key"] == provider_key), None)
    base_url = _provider_base_url(
        provider_key,
        str(payload.get("baseUrl") or (provider_spec or {}).get("defaultBaseUrl") or ""),
    )
    try:
        EndpointModel(baseUrl=base_url)
    except ValueError:
        raise HTTPException(status_code=422, detail="Base URL 不得包含凭据、查询参数或片段")
    secret = str(
        payload.get("secret")
        or app.state.providers.credentials.get(provider_key)
        or ""
    ).strip()
    requires_key = provider_spec is None or provider_spec.get("requiresKey") is not False
    if not secret and requires_key:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="请先输入 API Key，再探测模型")
    request_secret = secret or provider_key
    request = urllib.request.Request(
        f"{base_url}/models",
        headers={"Authorization": f"Bearer {request_secret}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        message = "模型列表接口不存在（404），请检查中转站 Base URL" if error.code == 404 else f"模型探测失败（HTTP {error.code}）：{detail[:180]}"
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=message.replace(secret, "[REDACTED]") if secret else message) from error
    except (urllib.error.URLError, TimeoutError, ValueError) as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"模型探测失败：{error}") from error
    raw_items = body.get("data") if isinstance(body, dict) else body
    # A few gateways return the OpenAI list under ``models``. Accept that
    # shape as well so detection remains useful across compatible proxies.
    if not isinstance(raw_items, list) and isinstance(body, dict):
        raw_items = body.get("models")
    if not isinstance(raw_items, list):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="模型接口未返回有效的模型列表")
    model_items = [({"id": item.strip()} if isinstance(item, str) else item) for item in raw_items]
    model_items = [item for item in model_items if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"].strip()]
    if provider_key == 'evolink':
        from .evolink import normalize_evolink_model
        model_items = [normalize_evolink_model(item) for item in model_items]
    if provider_key == "ollama":
        # Ollama's OpenAI-compatible /models response intentionally stays
        # minimal. Record the known text-only gpt-oss family so image
        # attachments fail local preflight instead of reaching the model.
        model_items = [
            {
                **item,
                **({"input_modalities": ["text"], "output_modalities": ["text"], "supported_endpoint_types": ["/chat/completions"]}
                   if re.search(r"(?:^|[/_-])gpt[-_]oss(?::|-)?20b(?:$|[-_:])", str(item["id"]), re.I) else {}),
            }
            for item in model_items
        ]
    from .model_capabilities import model_record

    catalog_by_id = {record["id"]: record for record in (model_record(item) for item in model_items)}
    catalog_sources = ["evolink" if provider_key == 'evolink' else "openai-compatible"]
    catalog_warnings = []
    catalog_coverage = "standard"
    if provider_key == 'evolink' and any(item.get('integrationNote') for item in model_items):
        catalog_warnings.append('专用音乐、语音、视频编辑等尚未适配的接口保留在未分类目录，不会混入对话或画布生成菜单。')
    closeai = provider_key == "openai-compatible" and is_closeai_base_url(base_url)
    supplied_catalog_secret = str(payload.get("catalogSecret") or "").strip()
    catalog_secret = supplied_catalog_secret or str(
        app.state.providers.credentials.get(CLOSEAI_CATALOG_CREDENTIAL) or ""
    ).strip()
    management_catalog_loaded = False
    if closeai and catalog_secret:
        management_request = urllib.request.Request(
            management_models_url(base_url),
            headers={"Authorization": f"Bearer {catalog_secret}", "Accept": "application/json"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(management_request, timeout=20) as response:
                management_body = json.loads(response.read().decode("utf-8"))
            for record in normalize_management_response(management_body):
                existing = catalog_by_id.get(record["id"], {})
                catalog_by_id[record["id"]] = model_record({**existing, **record})
            management_catalog_loaded = True
            catalog_sources.append("closeai-management")
            catalog_coverage = "complete"
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            reason = f"CloseAI 完整目录同步失败（HTTP {error.code}）：{detail[:160]}"
            reason = reason.replace(catalog_secret, "[REDACTED]")
            if supplied_catalog_secret:
                raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=reason) from error
            catalog_warnings.append("已保存的 CloseAI 目录管理密钥不可用，本次使用普通模型目录。")
        except (urllib.error.URLError, TimeoutError, ValueError) as error:
            if supplied_catalog_secret:
                reason = f"CloseAI 完整目录同步失败：{error}".replace(catalog_secret, "[REDACTED]")
                raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=reason) from error
            catalog_warnings.append("CloseAI 完整目录暂时不可用，本次使用普通模型目录。")
    elif closeai:
        catalog_coverage = "partial"
        catalog_warnings.append("未配置 CloseAI 目录管理密钥，普通 API 目录可能遗漏图像、视频或音频模型。")
    if provider_key == "openrouter":
        # These read-only discoveries run together, only on settings sync.
        from concurrent.futures import ThreadPoolExecutor
        def discover(kind):
            req = urllib.request.Request(f"{base_url}/{kind}s/models", headers={"Authorization": f"Bearer {secret}", "Accept": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=15) as response:
                    return kind, json.loads(response.read()).get("data", [])
            except (urllib.error.URLError, TimeoutError, ValueError):
                return kind, []
        with ThreadPoolExecutor(max_workers=2) as pool:
            for kind, items in pool.map(discover, ["image", "video"]):
                for item in items if isinstance(items, list) else []:
                    if isinstance(item, dict) and item.get("id"):
                        existing = catalog_by_id.get(item["id"], {})
                        catalog_by_id[item["id"]] = model_record({**existing, **item, "output_modalities": [kind]})
    # CloseAI's list endpoint can omit non-chat models. Resolve configured
    # media IDs with the standard read-only model detail endpoint, only here
    # during an explicit settings sync. Never add an unconfirmed model ID.
    missing_models = []
    if closeai:
        from concurrent.futures import ThreadPoolExecutor
        from urllib.parse import quote
        configured = app.state.model_catalog.settings().media
        preferred = list(dict.fromkeys(model for slots in configured.values() for model in slots.values() if model))[:8]
        def comparable(value):
            return str(value).rsplit("/", 1)[-1].casefold().replace("_", "-")
        available = {comparable(model) for model in catalog_by_id}
        missing = [model for model in preferred if comparable(model) not in available]
        def lookup(model):
            for alias in model_aliases(model):
                request = urllib.request.Request(f"{base_url}/models/{quote(alias, safe='')}", headers={"Authorization": f"Bearer {secret}", "Accept": "application/json"})
                try:
                    with urllib.request.urlopen(request, timeout=8) as response:
                        record = json.loads(response.read())
                    if isinstance(record, dict) and isinstance(record.get("data"), dict):
                        record = record["data"]
                    returned_id = str(record.get("id", "")).strip() if isinstance(record, dict) else ""
                    if returned_id and returned_id.casefold() == alias.casefold():
                        return model_record(record)
                except (urllib.error.URLError, TimeoutError, ValueError):
                    continue
            return None
        with ThreadPoolExecutor(max_workers=4) as pool:
            for requested, record in zip(missing, pool.map(lookup, missing)):
                if record:
                    catalog_by_id[record["id"]] = {**record, "catalogSource": "model-detail"}
                else:
                    missing_models.append(requested)
    catalog = [catalog_by_id[key] for key in sorted(catalog_by_id)]
    models = [str(record["id"]) for record in catalog]
    text_models = sorted(str(record["id"]) for record in catalog if "text" in record["kinds"])
    image_models = sorted(str(record["id"]) for record in catalog if "image" in record["kinds"])
    video_models = sorted(str(record["id"]) for record in catalog if "video" in record["kinds"])
    audio_models = sorted(str(record["id"]) for record in catalog if "audio" in record["kinds"])
    embedding_models = sorted(str(record["id"]) for record in catalog if "embedding" in record["kinds"])
    three_d_models = sorted(str(record["id"]) for record in catalog if "3d" in record["kinds"])
    unknown_models = sorted(str(record["id"]) for record in catalog if "unknown" in record["kinds"])
    snapshot = {
        "baseUrl": base_url,
        "models": models,
        "modelCatalog": catalog,
        "textModels": text_models,
        "imageModels": image_models,
        "videoModels": video_models,
        "audioModels": audio_models,
        "embeddingModels": embedding_models,
        "threeDModels": three_d_models,
        "unknownModels": unknown_models,
        "count": len(models),
        "unavailableModels": missing_models,
        "catalogCoverage": catalog_coverage,
        "catalogSources": catalog_sources,
        "catalogWarnings": catalog_warnings,
    }
    if requires_key and payload.get("saveCredential") and payload.get("secret"):
        app.state.providers.set_credential(provider_key, secret)
    if management_catalog_loaded and payload.get("saveCatalogCredential") and supplied_catalog_secret:
        app.state.providers.set_catalog_credential(provider_key, supplied_catalog_secret)
    app.state.model_catalog.save(provider_key, base_url, snapshot)
    return app.state.model_catalog.view(provider_key, base_url)


@app.get("/api/research/search")
def search_design_references(query: str, num: int = 10, page: int = 1, baseUrl: str | None = None):
    """Proxy design-led web search through the configured OpenAI-compatible gateway.

    The browser never receives the API key. Results are normalized so the UI can
    render different gateway response shapes without coupling to a vendor SDK.
    """
    clean_query = query.strip()
    if not clean_query:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="query 不能为空")
    base_url = (baseUrl or os.environ.get("AICS_OPENAI_COMPATIBLE_BASE_URL", "https://api.openai-proxy.org")).strip().rstrip("/")
    if base_url.endswith("/v1"):
        base_url = base_url[:-3].rstrip("/")
    endpoint = f"{base_url}/api/v1/plugins/google-search"
    credential = app.state.providers.credentials.get("openrouter") or app.state.providers.credentials.get("openai-compatible")
    params = urlencode({"query": clean_query, "num": min(max(int(num), 1), 10), "page": max(int(page), 1)})
    headers = {"Accept": "application/json"}
    if credential:
        headers["Authorization"] = f"Bearer {credential}"
    request = urllib.request.Request(f"{endpoint}?{params}", headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"搜索网关返回 {error.code}: {detail[:300]}") from error
    except (urllib.error.URLError, TimeoutError, ValueError) as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"搜索网关不可用：{error}") from error

    raw_results = payload.get("results") if isinstance(payload, dict) else payload
    if isinstance(raw_results, dict):
        raw_results = raw_results.get("organic_results") or raw_results.get("items") or raw_results.get("data") or []
    if isinstance(raw_results, dict):
        raw_results = raw_results.get("results") or raw_results.get("items") or []
    normalized = []

    def image_url_from(item: dict) -> str | None:
        """Read only an actual remote preview URL from gateway result shapes."""
        candidates = [item.get("image"), item.get("image_url"), item.get("thumbnail"), item.get("thumbnailUrl"), item.get("imageUrl")]
        for candidate in candidates:
            if isinstance(candidate, dict):
                candidate = candidate.get("url") or candidate.get("src") or candidate.get("href")
            value = str(candidate or "").strip()
            if value.startswith(("https://", "http://")):
                return value
        return None

    for item in raw_results if isinstance(raw_results, list) else []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or item.get("link") or item.get("href") or "")
        if not url:
            continue
        preview_image = image_url_from(item)
        normalized.append({
            "title": str(item.get("title") or item.get("name") or "设计参考"),
            "url": url,
            "snippet": str(item.get("snippet") or item.get("description") or item.get("body") or ""),
            "domain": str(item.get("domain") or urlsplit(url).netloc),
            # Never substitute a bundled/local image here. If the search
            # provider does not return a thumbnail, the renderer shows an
            # explicit no-preview state instead of making local art look like
            # a network reference.
            "image": preview_image,
            "imageSource": "network" if preview_image else None,
        })
    return {"query": clean_query, "results": normalized[:10]}


@app.get("/api/projects/{project_id}/prompts")
def list_prompt_templates(project_id: str, store: Store):
    if store.get_project(project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    return app.state.prompts.list_templates(project_id)


@app.post("/api/projects/{project_id}/prompts", status_code=status.HTTP_201_CREATED)
def create_prompt_template(project_id: str, payload: dict, store: Store):
    if store.get_project(project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    try:
        return app.state.prompts.create_template(project_id=project_id, payload=payload)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error


@app.get("/api/prompts/{template_id}")
def get_prompt_template(template_id: str):
    try:
        return app.state.prompts.get_template(template_id)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


@app.post("/api/prompts/{template_id}/versions", status_code=status.HTTP_201_CREATED)
def create_prompt_version(template_id: str, payload: dict):
    try:
        return app.state.prompts.create_version(template_id=template_id, content=payload.get("content"))
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error


@app.get("/api/projects", response_model=list[Project])
def list_projects(store: Store):
    projects = store.list_projects()
    pending = {project["id"]: app.state.project_titles.schedule(project["id"]) for project in projects}
    # A worker may have finished between the first read and scheduling. Read
    # fresh names so a stale placeholder is never returned as the final title.
    return project_overviews(store, [{**project, "titlePending": pending.get(project["id"], False)} for project in store.list_projects()])


@app.get('/api/library/assets')
def get_library_assets(store: Store):
    return library_assets(store)


@app.get('/api/achievements')
def get_achievements():
    return app.state.achievements.status()


@app.post('/api/achievements/{achievement_id}/claim')
def claim_achievement(achievement_id: str):
    try:
        return app.state.achievements.claim(achievement_id)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error


@app.get('/api/library/html')
def get_library_html():
    return app.state.project_previews.html_assets()


@app.get('/api/projects/{project_id}/canvas/html/{node_id}')
def get_canvas_html(project_id: str, node_id: str):
    try:
        return app.state.project_previews.html_document(project_id, node_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get('/api/projects/{project_id}/preview')
def get_project_preview(project_id: str):
    try:
        return app.state.project_previews.get(project_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get("/api/projects/{project_id}", response_model=Project)
def get_project(project_id: str, store: Store):
    project = store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    return project


@app.post("/api/projects", response_model=Project, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, store: Store):
    base_slug = slugify(payload.name)
    existing = {project["slug"] for project in store.list_projects()}
    slug = base_slug
    suffix = 2
    while slug in existing:
        slug = f"{base_slug}-{suffix}"
        suffix += 1

    root_path = str(store.workspace_root / slug)
    project = new_project(name=payload.name, slug=slug, brief=payload.brief, budget_minor=payload.budgetMinor, currency=payload.currency, root_path=root_path)
    try:
        return store.create_project(project)
    except Exception as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"项目创建失败：{error}") from error


@app.post("/api/intake", status_code=status.HTTP_201_CREATED)
async def create_intake(
    store: Store,
    name: str = Form(...),
    brief: str = Form(""),
    currency: str = Form("CNY"),
    budget_minor: int | None = Form(None, alias="budgetMinor"),
    auto_title: bool = Form(False, alias="autoTitle"),
    files: list[UploadFile] | None = File(default=None),
):
    """Create a local project record and parse all submitted intake files.

    The endpoint accepts multipart form data and stores the files locally while
    parsing them through ``KnowledgeStore.ingest_file``. A later Agent task may
    explicitly resolve the stored file as an attachment for the selected text
    provider; arbitrary paths are never accepted from the client.
    """
    clean_name = "新对话" if auto_title else name.strip()
    if not clean_name:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="项目名称不能为空")
    if len(files or []) > 12:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="一次最多上传 12 个文件")
    base_slug = slugify(clean_name)
    existing = {project["slug"] for project in store.list_projects()}
    slug = base_slug
    suffix = 2
    while slug in existing:
        slug = f"{base_slug}-{suffix}"
        suffix += 1
    root_path = str(store.workspace_root / slug)
    project = new_project(name=clean_name, slug=slug, brief=brief.strip(), budget_minor=budget_minor, currency=currency.strip() or "CNY", root_path=root_path)
    project["titleMode"] = "auto" if auto_title else "manual"
    try:
        project = store.create_project(project)
    except Exception as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"项目创建失败：{error}") from error

    parsed: list[dict] = []
    total_bytes = 0
    for upload in files or []:
        if not upload.filename:
            continue
        content = await upload.read()
        total_bytes += len(content)
        if total_bytes > 25 * 1024 * 1024:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="一次上传总大小不能超过 25 MB")
        if not content:
            parsed.append({"filename": Path(upload.filename).name, "status": "empty", "warning": "文件为空，未解析"})
            continue
        try:
            parsed.append(app.state.knowledge.ingest_file(project_id=project["id"], filename=upload.filename, content=content))
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
    return {"project": project, "files": parsed, "parsedCount": len([item for item in parsed if item.get("documentId")])}


@app.put("/api/projects/{project_id}", response_model=Project)
def update_project(project_id: str, payload: ProjectUpdate, store: Store):
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("name") is not None and not changes["name"].strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="项目名称不能为空")
    project = store.update_project(project_id, changes)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    return project_overviews(store, [project])[0]


@app.delete("/api/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: str, store: Store):
    try:
        if store.get_project(project_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
        # KnowledgeStore owns the vector index and FTS cleanup; run it before
        # ProjectStore removes the project row and directory.
        app.state.knowledge.delete_project_documents(project_id)
        deleted = store.delete_project(project_id)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    if deleted is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    return None


@app.get("/api/projects/{project_id}/settings")
def get_project_settings(project_id: str, store: Store):
    if store.get_project(project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    return store.get_project_settings(project_id)


@app.put("/api/projects/{project_id}/settings")
def update_project_settings(project_id: str, payload: dict, store: Store):
    if store.get_project(project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    try:
        changes = {}
        if "locale" in payload:
            changes["locale"] = str(payload["locale"])
        if "privacyMode" in payload:
            changes["privacyMode"] = str(payload["privacyMode"])
        if "defaultProviderRefs" in payload:
            changes["defaultProviderRefs"] = payload["defaultProviderRefs"] or {}
        if "stylePresets" in payload:
            changes["stylePresets"] = payload["stylePresets"] or {}
        return store.update_project_settings(project_id, changes)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error


@app.post("/api/projects/{project_id}/tasks", status_code=status.HTTP_201_CREATED)
def run_task(project_id: str, payload: dict, store: Store, tasks: Tasks):
    try:
        project = store.get_project(project_id)
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
        agent_key = str(payload.get("agentKey", "design"))
        workflow_step = str(payload.get("workflowStep", "design"))
        # All tasks share the design runtime in both production and tests.
        if agent_key != "design":
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="仅支持 design Agent 任务",
            )
        input_data = payload.get("input", {})
        if input_data is None:
            input_data = {}
        if not isinstance(input_data, dict):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="任务 input 必须是对象")
        brief = str(payload.get("brief") or project["brief"]).strip() or project["brief"]
        return tasks.enqueue(project_id=project_id, agent_key=agent_key, workflow_step=workflow_step, brief=brief, input_data=input_data, run_async=bool(payload.get("async", False)), request_id=payload.get("requestId"))
    except TaskRequestConflict as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    except HTTPException:
        raise
    except Exception as error:
        # Synchronous agent execution can fail while resolving a provider or
        # calling a gateway.  Letting that exception escape produces an opaque
        # browser-level CORS error because the unhandled 500 response bypasses
        # the normal middleware path.  Return a structured response instead so
        # the renderer can show the actionable provider error.
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Agent 运行失败：{error}") from error


@app.patch('/api/projects/{project_id}/tasks/{task_id}')
def edit_task(project_id: str, task_id: str, payload: dict, tasks: Tasks):
    try:
        task = tasks.edit(project_id, task_id, brief=payload.get('brief'), input_data=payload.get('input'), run_async=True)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if task is None:
        raise HTTPException(status_code=404, detail='要编辑的消息不存在')
    return task


@app.get("/api/projects/{project_id}/tasks/{task_id}/events")
async def task_events(project_id: str, task_id: str, request: Request, tasks: Tasks):
    if tasks.get_task(project_id, task_id) is None:
        raise HTTPException(status_code=404, detail="任务不存在")

    async def events():
        previous = ""
        started = asyncio.get_running_loop().time()
        while not tasks._stopping.is_set() and not await request.is_disconnected():
            task = await asyncio.to_thread(tasks.get_task, project_id, task_id)
            if task is None:
                break
            payload = json.dumps(task, ensure_ascii=False)
            if payload != previous:
                yield f"event: task\ndata: {payload}\n\n"
                previous = payload
            if task["status"] in {"succeeded", "failed", "cancelled"}:
                break
            if asyncio.get_running_loop().time() - started >= 20:
                # Bounded streams cannot indefinitely hold graceful shutdown.
                break
            yield ': heartbeat\n\n'
            await asyncio.sleep(0.3)

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post('/api/projects/{project_id}/tasks/{task_id}/retry')
def retry_task(project_id: str, task_id: str, tasks: Tasks):
    try:
        task = tasks.retry(project_id, task_id)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if task is None:
        raise HTTPException(status_code=404, detail='任务不存在')
    return task


@app.post('/api/projects/{project_id}/agent-session')
def agent_session(project_id: str, payload: dict, request: Request, store: Store):
    from .agent_sessions import AgentSessionStore
    try:
        return AgentSessionStore(store).dispatch(project_id, request.headers.get('x-aics-task-id'), payload)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post('/api/projects/{project_id}/tasks/{task_id}/html-preview')
def html_generation_preview(project_id: str, task_id: str, payload: dict, store: Store):
    from .html_generation import HtmlGenerationPreviews
    service = HtmlGenerationPreviews(store, app.state.design_tools.canvas_store)
    if store.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail='项目不存在')
    try:
        if payload.get('state') == 'finished':
            if not payload.get('callId'): raise ValueError('生成标识无效')
            service.finish(project_id, task_id, payload['callId'])
            return {'status': 'finished'}
        return service.begin(project_id, task_id, payload.get('callId'))
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post('/api/projects/{project_id}/tasks/{task_id}/tool-result')
def get_tool_result(project_id: str, task_id: str, payload: dict, store: Store):
    """Read an exact receipt after a worker connection is lost, without replay."""
    task = app.state.tasks.get_task(project_id, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail='任务不存在')
    if task['status'] == 'cancelled': return {'state': 'cancelled'}
    if payload.get('name') not in {'generate_image','generate_audio'} or not isinstance(payload.get('arguments'), dict):
        raise HTTPException(status_code=422, detail='仅支持查询原始图片或语音请求回执')
    jobs = app.state.audio_jobs if payload['name'] == 'generate_audio' else app.state.image_jobs
    return jobs.read_arguments(project_id, task_id, payload['arguments'])


@app.get('/api/projects/{project_id}/tasks/{task_id}/image-operations/{operation_id}')
def get_image_operation(project_id: str, task_id: str, operation_id: str):
    return app.state.image_jobs.read(project_id, task_id, operation_id)


@app.get('/api/projects/{project_id}/tasks/{task_id}/audio-operations/{operation_id}')
def get_audio_operation(project_id: str, task_id: str, operation_id: str):
    return app.state.audio_jobs.read(project_id, task_id, operation_id)


@app.post("/api/projects/{project_id}/agent-tools/{tool_name}")
def execute_agent_tool(project_id: str, tool_name: str, payload: dict, request: Request, store: Store):
    headers = dict(request.headers)
    task_id = headers.get('x-aics-task-id')
    if tool_name in {'generate_image','generate_audio'} and task_id and headers.get('x-aics-async-tool') == '1':
        jobs = app.state.audio_jobs if tool_name == 'generate_audio' else app.state.image_jobs
        operation = jobs.submit(project_id, task_id, payload,
            lambda: _execute_agent_tool(project_id, tool_name, payload, headers, store))
        return JSONResponse(status_code=202, content=operation)
    return _execute_agent_tool(project_id, tool_name, payload, headers, store)


def _execute_agent_tool(project_id, tool_name, payload, headers, store):
    if store.get_project(project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    if tool_name not in DesignToolRegistry.TOOL_NAMES:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="设计工具不存在")
    task_id = headers.get("x-aics-task-id") or None
    if task_id:
        task = app.state.tasks.get_task(project_id, task_id)
        if task is None or task["status"] == "cancelled":
            raise HTTPException(status_code=409, detail="任务不存在或已停止")
        from .task_updates import TaskUpdates
        try: update_revision = int(headers.get('x-aics-update-revision', '0'))
        except ValueError: update_revision = 0
        if tool_name not in {'budget_check', 'budget_settle', 'report_progress'} and TaskUpdates(store).pending_after(project_id, task_id, update_revision):
            return {'status': 'task_update_pending', 'instruction': '用户已补充当前任务。此调用尚未执行、未提交服务商；请先读取补充要求并重新判断剩余工作，不要重复已提交的生成请求。'}
    elif tool_name in {'canvas_update_node', 'canvas_restore_node', 'canvas_link_nodes'}:
        touched = {str(payload[key]) for key in ('node_id', 'source_node_id', 'target_node_id') if payload.get(key)}
        if touched & app.state.design_tools.canvas_store.active_node_ids(project_id):
            raise HTTPException(status_code=409, detail="该节点正被任务使用，请等待任务完成或先停止任务")
    try:
        with billing_scope(project_id=project_id, task_id=task_id):
            return app.state.design_tools.execute(
                project_id=project_id,
                task_id=task_id,
                name=tool_name,
                arguments=payload if isinstance(payload, dict) else {},
                preview_call_id=headers.get('x-aics-html-preview-call-id'),
                operation_id=headers.get('x-aics-tool-call-id'),
                agent_role=headers.get('x-aics-agent-role', 'design'),
            )
    except SkillError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error
    except DesignToolError as error:
        if error.stop_tool:
            return JSONResponse(status_code=422, content={'detail': str(error), 'errorCode': error.error_code, 'stopTool': True, 'retryable': False})
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
    except HTTPException:
        raise
    except (ProviderError, ValueError) as error:
        if tool_name in {'generate_image','generate_audio'} and getattr(error, 'error_code', None) in {'image_result_unconfirmed', 'image_response_timeout','provider_result_unconfirmed'}:
            return {'tool': tool_name, 'status': 'generation_unconfirmed', 'message': str(error),
                    'errorCode': error.error_code, 'retryable': False, 'submitted': True, 'billingCertainty': 'unknown',
                    'instruction': '保留已保存媒体；本项结果待核对，不得重发或改参数重试。'}
        if getattr(error, 'stop_tool', False):
            return JSONResponse(status_code=422, content={'detail': str(error), 'errorCode': error.error_code, 'stopTool': True, 'retryable': False})
        raise HTTPException(status_code=402 if getattr(error,'status_code',None)==402 else status.HTTP_502_BAD_GATEWAY, detail=str(error)) from error


@app.get("/api/projects/{project_id}/canvas")
def get_project_canvas(project_id: str, store: Store):
    if store.get_project(project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    # Reconcile older Agent turns that saved a file but omitted the canvas tool.
    hidden = set(app.state.design_tools.canvas_store.load(project_id).get("hiddenAssetIds", []))
    for asset in reversed(app.state.assets.list_assets(project_id)):
        metadata = asset.get("metadata") or {}
        if metadata.get("source") == "design-agent-tool" and asset["id"] not in hidden:
            target = metadata.get("canvasNodeId")
            board = app.state.design_tools.canvas_store.load(project_id)
            if any(n.get("data", {}).get("assetId") == asset["id"] for n in board["nodes"]):
                continue
            if not any(n["id"] == target for n in board["nodes"]):
                target = None
            app.state.design_tools.canvas_store.ensure_asset_node(project_id, asset, task_id=metadata.get("taskId"), target_node_id=target)
    from .delivery import DeliveryService
    delivery = DeliveryService(store, app.state.assets, app.state.design_tools.canvas_store)
    board = delivery.canvas.load(project_id)
    with store._connect() as db:
        tasks = {r["id"]: json.loads(r["input_json"] or "{}") for r in db.execute("SELECT id,input_json FROM tasks WHERE project_id=? AND status='running'", (project_id,))}
    for node in board["nodes"]:
        node['data'].pop('deliveryReview',None)
        context = tasks.get(node.get("meta", {}).get("taskId"), {})
        node["deliveryProbe"] = {"fingerprint": delivery.fingerprint(node), "required": bool(context.get("deliveryVerification")), "result": delivery.check(project_id, node)}
        if node["deliveryProbe"]["result"]:
            node["deliveryProbe"]["result"].pop("frames", None)
    board['lockedNodeIds'] = sorted(delivery.canvas.active_node_ids(project_id, board))
    return board


@app.post("/api/projects/{project_id}/canvas/{node_id}/delivery-check")
def save_delivery_check(project_id: str, node_id: str, payload: dict, store: Store):
    from .delivery import DeliveryService, DELIVERY_PROBE_VERSION
    if payload.get('probeVersion') != DELIVERY_PROBE_VERSION:
        raise HTTPException(status_code=409, detail='预览检查程序已更新，请刷新页面后重新检查')
    try:
        return DeliveryService(store, app.state.assets, app.state.design_tools.canvas_store).record_check(project_id, node_id, payload.get("fingerprint"), payload.get("result") or {})
    except (ValueError, TypeError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/api/delivery/claim")
def claim_delivery_previews(store: Store, payload: dict | None = None):
    from .delivery import DeliveryService, DELIVERY_PROBE_VERSION
    # An old browser tab can outlive an app update. It must not claim work or
    # overwrite checks produced by the current media probe.
    if (payload or {}).get('probeVersion') != DELIVERY_PROBE_VERSION:
        return []
    return DeliveryService(store, app.state.assets, app.state.design_tools.canvas_store).claim_previews()


@app.patch("/api/projects/{project_id}/canvas")
def patch_project_canvas(project_id: str, payload: dict, store: Store):
    if store.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    try:
        return app.state.design_tools.canvas_store.apply_changes(project_id, payload)
    except CanvasConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except (ValueError, KeyError, TypeError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/api/projects/{project_id}/tasks")
def list_tasks(project_id: str, store: Store, tasks: Tasks):
    try:
        if store.get_project(project_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
        return tasks.list_tasks(project_id)
    except HTTPException:
        raise
    except Exception as error:
        # Convert storage/runtime failures into a normal response so the
        # renderer receives CORS headers and can show the underlying issue.
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"任务历史读取失败：{error}") from error


@app.get('/api/tasks/activity')
def task_activity(store: Store):
    from .task_activity import list_activity
    return list_activity(store)


@app.get("/api/projects/{project_id}/tasks/{task_id}")
def get_task(project_id: str, task_id: str, store: Store, tasks: Tasks):
    try:
        if store.get_project(project_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
        task = tasks.get_task(project_id, task_id)
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"任务读取失败：{error}") from error
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    return task


@app.post("/api/projects/{project_id}/tasks/{task_id}/cancel")
def cancel_task(project_id: str, task_id: str, store: Store, tasks: Tasks):
    if store.get_project(project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    task = tasks.cancel(project_id, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    return task


@app.get("/api/projects/{project_id}/tasks/{task_id}/inspection")
def inspect_task_request(project_id: str, task_id: str, store: Store, tasks: Tasks):
    task = tasks.get_task(project_id, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    from .task_inspection import inspect_task
    from .image_recovery import ImageRecovery
    return {**inspect_task(store, app.state.billing, app.state.design_tools.canvas_store, project_id, task),
            'recoverableImages': ImageRecovery(app.state.design_tools).list(project_id, task_id)}


@app.post('/api/projects/{project_id}/tasks/{task_id}/image-results/{receipt_id}/recover')
def recover_image_result(project_id: str, task_id: str, receipt_id: str):
    from .image_recovery import ImageRecovery
    from .providers.http import ProviderError
    try:
        return ImageRecovery(app.state.design_tools, {'generate_image':app.state.image_jobs,'generate_audio':app.state.audio_jobs}).recover(project_id, task_id, receipt_id)
    except ProviderError as error:
        raise HTTPException(502, str(error)) from error


@app.get('/api/projects/{project_id}/tasks/{task_id}/updates')
def list_task_updates(project_id: str, task_id: str, store: Store):
    from .task_updates import TaskUpdates
    try: return TaskUpdates(store).list(project_id, task_id)
    except KeyError as error: raise HTTPException(status_code=404, detail=str(error)) from error


@app.post('/api/projects/{project_id}/tasks/{task_id}/updates')
def append_task_update(project_id: str, task_id: str, payload: dict, store: Store):
    from .task_updates import TaskUpdates
    try: return TaskUpdates(store).append(project_id, task_id, payload.get('requestId'), payload.get('text'))
    except KeyError as error: raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error: raise HTTPException(status_code=409, detail=str(error)) from error


@app.post('/api/projects/{project_id}/tasks/{task_id}/updates/acknowledge')
def acknowledge_task_updates(project_id: str, task_id: str, payload: dict, store: Store):
    from .task_updates import TaskUpdates
    revision = payload.get('revision')
    if not isinstance(revision, int) or revision < 0: raise HTTPException(status_code=422, detail='补充版本无效')
    try: return TaskUpdates(store).acknowledge(project_id, task_id, revision)
    except KeyError as error: raise HTTPException(status_code=404, detail=str(error)) from error


@app.post("/api/projects/{project_id}/knowledge/text", status_code=status.HTTP_201_CREATED)
def ingest_knowledge(project_id: str, payload: dict, store: Store):
    if store.get_project(project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    knowledge: KnowledgeStore = app.state.knowledge
    text = str(payload.get("text", ""))
    if not text.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="text 不能为空")
    return knowledge.ingest_text(project_id=project_id, path_relative=str(payload.get("pathRelative", "inline.txt")), text=text, title=payload.get("title"))


@app.post("/api/projects/{project_id}/knowledge/upload", status_code=status.HTTP_201_CREATED)
async def upload_knowledge(project_id: str, store: Store, file: UploadFile = File(...)):
    if store.get_project(project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    if not file.filename:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="文件名不能为空")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="文件不能为空")
    if len(content) > 25 * 1024 * 1024:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="单个知识库文件不能超过 25 MB")
    try:
        return app.state.knowledge.ingest_file(project_id=project_id, filename=file.filename, content=content)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


@app.get("/api/projects/{project_id}/knowledge/documents")
def list_knowledge_documents(project_id: str, store: Store):
    if store.get_project(project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    return app.state.knowledge.list_documents(project_id)


@app.get("/api/projects/{project_id}/knowledge/documents/{document_id}/content")
def get_project_knowledge_content(project_id: str, document_id: str, store: Store):
    project = store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail='项目不存在')
    document = next((item for item in app.state.knowledge.list_documents(project_id) if item['id'] == document_id), None)
    if document is None:
        raise HTTPException(status_code=404, detail='引用文件不存在')
    root = Path(project['rootPath']).resolve()
    allowed = (root / 'knowledge' / 'parsed').resolve()
    path = (root / document['pathRelative']).resolve()
    if not allowed.is_relative_to(root) or not path.is_relative_to(allowed) or not path.is_file():
        raise HTTPException(status_code=404, detail='引用文件不存在')
    filename = document['title'] + (path.suffix if not document['title'].endswith(path.suffix) else '')
    return FileResponse(path, filename=filename, media_type=mimetypes.guess_type(path.name)[0] or 'application/octet-stream', headers={'X-Content-Type-Options': 'nosniff'})


@app.get("/api/projects/{project_id}/knowledge/documents/{document_id}/structure")
def get_project_knowledge_structure(project_id: str, document_id: str, store: Store, cursor: int = 0, limit: int = 30, locator: str | None = None):
    if store.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    try:
        return app.state.knowledge.read_document(scope="project", project_id=project_id, document_id=document_id,
                                                 cursor=cursor, limit=limit, locator=locator)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get("/api/projects/{project_id}/knowledge/documents/{document_id}/parts")
def list_project_knowledge_parts(project_id: str, document_id: str, store: Store, cursor: int = 0, limit: int = 100, kind: str | None = None):
    if store.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    try:
        return app.state.knowledge.list_parts(scope="project", project_id=project_id, document_id=document_id,
                                              cursor=cursor, limit=limit, kind=kind)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get("/api/projects/{project_id}/knowledge/documents/{document_id}/parts/{part_id}/content")
def get_project_knowledge_part(project_id: str, document_id: str, part_id: str, store: Store, variant: str = "preview"):
    if store.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    try:
        content, mime, filename = app.state.knowledge.part_content(scope="project", project_id=project_id,
                                                                  document_id=document_id, part_id=part_id, variant=variant)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return Response(content, media_type=mime, headers={"Content-Disposition": f'inline; filename="{Path(filename).name}"', "X-Content-Type-Options": "nosniff"})


@app.delete("/api/projects/{project_id}/knowledge/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_knowledge_document(project_id: str, document_id: str, store: Store):
    if store.get_project(project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    try:
        deleted = app.state.knowledge.delete_document(project_id=project_id, document_id=document_id)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
    if deleted is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="知识文档不存在")
    return None


@app.post("/api/projects/{project_id}/knowledge/reindex")
def reindex_knowledge(project_id: str, store: Store):
    if store.get_project(project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    return app.state.knowledge.reindex_project(project_id)


@app.get("/api/projects/{project_id}/knowledge/search")
def search_knowledge(project_id: str, q: str, store: Store):
    if store.get_project(project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    return app.state.knowledge.search(project_id=project_id, query=q)


@app.get("/api/projects/{project_id}/knowledge/vector-search")
def vector_search_knowledge(project_id: str, q: str, store: Store):
    if store.get_project(project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    return app.state.knowledge.vector_search(project_id=project_id, query=q)


@app.get("/api/projects/{project_id}/assets")
def list_assets(project_id: str, store: Store):
    if store.get_project(project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    return app.state.assets.list_assets(project_id)


@app.post("/api/projects/{project_id}/assets/upload", status_code=status.HTTP_201_CREATED)
async def upload_asset(
    project_id: str,
    store: Store,
    file: UploadFile = File(...),
    kind: str = Form("original"),
    source_credit: str | None = Form(None, alias="sourceCredit"),
    source_file: str | None = Form(None, alias="sourceFile"),
    source_role: str | None = Form(None, alias="sourceRole"),
):
    if store.get_project(project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    if not file.filename:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="文件名不能为空")
    allowed_kinds = {"image", "3d", "cad", "document", "original"}
    if kind not in allowed_kinds:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"kind 必须是: {', '.join(sorted(allowed_kinds))}")
    if source_role and source_role not in {"deliverable", "reference"}:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="sourceRole 必须是 deliverable 或 reference")
    if source_credit and len(source_credit) > 300 or source_file and len(source_file) > 300:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="素材来源信息过长")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="文件不能为空")
    metadata = {"source": "user-upload", "originalName": file.filename}
    if source_credit:
        metadata["sourceCredit"] = source_credit.strip()
    if source_file:
        metadata["sourceFile"] = source_file.strip()
    if source_role:
        metadata["sourceRole"] = source_role
    return app.state.assets.add_bytes(project_id=project_id, kind=kind, filename=file.filename, content=content, metadata=metadata)


@app.delete("/api/projects/{project_id}/assets/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_asset(project_id: str, asset_id: str, store: Store):
    if store.get_project(project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    try:
        deleted = app.state.assets.delete_asset(project_id=project_id, asset_id=asset_id)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
    if deleted is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资产不存在")
    return None


@app.get("/api/projects/{project_id}/assets/{asset_id}/content")
def get_asset_content(project_id: str, asset_id: str, store: Store):
    if store.get_project(project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    asset = app.state.assets.get_asset(project_id=project_id, asset_id=asset_id)
    if asset is None or not Path(asset["absolutePath"]).is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资产不存在")
    return FileResponse(asset["absolutePath"], media_type=asset["mime"], filename=Path(asset["pathRelative"]).name)


@app.get("/api/projects/{project_id}/video/jobs")
def list_video_jobs(project_id: str, store: Store):
    if store.get_project(project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    return app.state.videos.list(project_id)


@app.post("/api/projects/{project_id}/video/jobs/{job_record_id}/refresh")
def refresh_video_job(project_id: str, job_record_id: str, store: Store):
    if store.get_project(project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    record = app.state.videos.get(project_id, job_record_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="视频任务不存在")
    try:
        result = app.state.videos.refresh(project_id, job_record_id, retry=True)
        app.state.videos.settle_tasks()
        return result
    except (ProviderError, ValueError) as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@app.post("/api/projects/{project_id}/video/jobs", status_code=status.HTTP_201_CREATED)
def create_video_job(project_id: str, payload: dict, store: Store):
    if store.get_project(project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    prompt = str(payload.get("prompt", "")).strip()
    if not prompt:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="视频 Prompt 不能为空")
    from .video_inputs import video_inputs
    try:
        source_asset_id, last_frame_asset_id, video_params = video_inputs(payload.get('sourceAssetId'), payload.get('sourceAssetIds'), payload.get('lastFrameAssetId'), _object_field(payload, 'params'))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    frame_assets = []
    for asset_id in (source_asset_id, last_frame_asset_id):
        asset = app.state.assets.get_asset(project_id=project_id, asset_id=asset_id) if asset_id else None
        if asset_id and asset is None:
            raise HTTPException(status_code=404, detail='输入资产不存在')
        if asset and asset.get('kind') != 'image':
            raise HTTPException(status_code=422, detail='视频首尾帧必须是图像资产')
        frame_assets.append(asset)
    frame_metadata = {'sourceAssetId':source_asset_id, 'sourceAssetIds':[id for id in (source_asset_id,last_frame_asset_id) if id], 'lastFrameAssetId':last_frame_asset_id}
    provider_key = str(payload.get("provider") or "seedream")
    model = str(payload.get("model") or DEFAULT_VIDEO_MODEL)
    if provider_key in {"openrouter", "openai-compatible", "evolink"}:
        try:
            model = MediaModelRouter(app.state.model_catalog).route("video", provider=provider_key, base_url=_provider_base_url(provider_key, str(payload.get("endpoint") or "")), model=payload.get("model"), quality=payload.get("quality", "standard"))
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
    try:
        provider = app.state.providers.video(provider_key, endpoint=str(payload.get("endpoint")) if payload.get("endpoint") else None, model=model)
        if last_frame_asset_id and not getattr(provider, 'supports_last_frame', False):
            raise HTTPException(status_code=422, detail='当前视频服务不支持首尾帧，请使用 OpenRouter 视频服务')
        video_params.pop("prompt", None)
        video_params.pop("model", None)
        video_params.pop("source_asset", None)
        video_params.pop("ipProfileId", None)
        video_params.pop("ipProfileVersion", None)
        for field, label in (('style','视觉风格'),('camera','镜头运动'),('camera_motion','镜头运动')):
            if video_params.get(field): prompt += f'\n{label}：{video_params[field]}'
        frame_options = {'last_frame_asset':frame_assets[1]['absolutePath']} if last_frame_asset_id else {}
        job = provider.generate(prompt=prompt, source_asset=frame_assets[0]['absolutePath'] if frame_assets[0] else None, model=model, **frame_options, **{k:v for k,v in video_params.items() if k not in {'style','camera','camera_motion'}})
        if not isinstance(job, dict):
            raise ProviderError("视频 Provider 返回了无效的任务对象")
    except ProviderError as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    output_asset_id = None
    video_content = job.pop("content", None)
    if isinstance(video_content, (bytes, bytearray)) and video_content:
        extension = str(job.pop("extension", "mp4")).lstrip(".")
        asset = app.state.assets.add_bytes(project_id=project_id, kind="video", filename=f"seedream-{uuid4().hex}.{extension}", content=bytes(video_content), metadata={"provider": provider_key, "model": model, **frame_metadata, "params":video_params, "prompt": prompt})
        output_asset_id = asset["id"]
    # Providers may need an absolute local path for upload/sidecar calls, but
    # persisted lineage must stay portable and project-scoped.
    if isinstance(job, dict) and "sourceAsset" in job:
        job["sourceAsset"] = source_asset_id
    record = app.state.videos.create(project_id, provider=provider_key, model=model, status=job.get("status", "submitted"), job_id=job.get("jobId"), prompt=prompt, source_asset_id=source_asset_id, metadata={**job, **frame_metadata, "endpoint": _safe_endpoint(str(payload.get("endpoint")) if payload.get("endpoint") else None), "params": video_params}, output_asset_id=output_asset_id)
    return {"job": record, "provider": provider_key, "status": record["status"], "asset": app.state.assets.get_asset(project_id=project_id, asset_id=output_asset_id) if output_asset_id else None}


@app.post("/api/projects/{project_id}/generations/image", status_code=status.HTTP_201_CREATED)
def generate_image(project_id: str, payload: dict, store: Store):
    if store.get_project(project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    prompt = str(payload.get("prompt", "")).strip()
    if not prompt:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="prompt 不能为空")
    return _run_image_generation(project_id=project_id, payload=payload, store=store)


_LEGACY_IMAGE_MODELS = {"gpt-image-1", "dall-e", "dall-e-2", "dall-e-3", "dalle", "dalle-2", "dalle-3"}


def _pad_image_to_ratio(content: bytes, image_ratio: str) -> tuple[bytes, str | None]:
    """Pad raster output to the requested ratio without cropping the subject."""
    if image_ratio != "3:4" or not content:
        return content, None
    try:
        from PIL import Image
        source = Image.open(BytesIO(content)).convert("RGBA")
        width, height = source.size
        if not width or not height or abs((width / height) - 0.75) < 0.005:
            return content, None
        if width / height > 0.75:
            target_width, target_height = width, ceil(width / 0.75)
        else:
            target_width, target_height = ceil(height * 0.75), height
        canvas = Image.new("RGBA", (target_width, target_height), (0, 0, 0, 0))
        canvas.paste(source, ((target_width - width) // 2, (target_height - height) // 2), source)
        output = BytesIO()
        canvas.save(output, format="PNG", optimize=True)
        return output.getvalue(), "png"
    except Exception:
        # Leave undecodable data for the generation boundary to handle.
        return content, None


def _run_image_generation(*, project_id: str, payload: dict, store: ProjectStore, parent_generation_id: str | None = None, parent_asset_id: str | None = None) -> dict:
    from .image_quality import decide_image_policy, apply_policy_dimensions
    params = _object_field(payload, 'params')
    prompt = str(payload.get("prompt", "")).strip()
    decision = decide_image_policy(payload.get('quality'), user_message=prompt, prompt=prompt, params=params,
                                   has_references=bool(parent_asset_id))
    tier = decision['tier']
    params = apply_policy_dimensions(params, decision)
    test_mode = os.environ.get("AICS_TEST_MODE") == "1"
    provider_key = str(payload.get("provider") or ("local-placeholder" if test_mode else "openai-image"))
    requested_model = str(payload.get("model") or "").strip()
    model = requested_model or ("placeholder-v0" if provider_key == "local-placeholder" else
                                DEFAULT_DRAFT_IMAGE_MODEL if tier == "draft" else DEFAULT_IMAGE_MODEL)
    purpose = str(params.get("purpose") or "").strip()
    image_ratio = str(
        payload.get("imageRatio")
        or params.get("imageRatio")
    ).strip()
    if image_ratio:
        params["imageRatio"] = image_ratio
    # Style/material are product-level choices, not portable OpenAI image API
    # fields. Carry them in the natural-language prompt so every compatible
    # gateway can use the intent without rejecting unknown JSON properties.
    prompt_hints = []
    style_hint = str(payload.get("style") or params.get("style") or "").strip()
    material_hint = str(payload.get("material") or params.get("material") or "").strip()
    if style_hint and style_hint != "智能识别":
        prompt_hints.append(f"视觉风格：{style_hint}")
    if material_hint:
        prompt_hints.append(f"材质表现：{material_hint}")
    provider_prompt = f"{prompt}\n" + "；".join(prompt_hints) if prompt_hints else prompt
    try:
        extension = str(payload.get('extension') or params.get('output_format') or 'png').strip().lower().lstrip('.')
        if extension not in {'png', 'jpeg', 'jpg', 'webp'}:
            raise ValueError('图像输出格式只允许 PNG、JPEG 或 WebP；SVG 绘图已全局禁用。')
        provider_prompt, params = prepare_image_output(provider_prompt, params)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    negative_prompt = str(payload.get("negativePrompt", ""))
    prompt_version_id = payload.get("promptVersionId")
    if prompt_version_id:
        with store._connect() as connection:
            prompt_version = connection.execute("SELECT 1 FROM prompt_versions v JOIN prompt_templates t ON t.id = v.prompt_template_id WHERE v.id = ? AND t.project_id = ?", (prompt_version_id, project_id)).fetchone()
        if prompt_version is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Prompt 版本不属于当前项目")
    generation_id = str(uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with store._connect() as connection:
        connection.execute("INSERT INTO generations (id, project_id, provider, model, prompt_version_id, prompt_text, negative_prompt, params_json, parent_asset_id, parent_generation_id, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'running', ?)", (generation_id, project_id, provider_key, model, prompt_version_id, prompt, negative_prompt, json.dumps(params, ensure_ascii=False), parent_asset_id, parent_generation_id, now))
    try:
        base_url = str(payload.get("baseUrl") or _default_openai_base_url())
        provider_params = dict(params)
        provider_params.pop("prompt", None)
        provider_params.pop("negative_prompt", None)
        provider_params.pop("model", None)
        provider_params.pop("source_asset_path", None)
        provider_params.pop("source_asset_paths", None)
        provider_params.pop("mask_asset_path", None)
        if parent_asset_id:
            parent_asset = app.state.assets.get_asset(project_id=project_id, asset_id=parent_asset_id)
            if parent_asset:
                provider_params["source_asset_path"] = parent_asset["absolutePath"]
        if payload.get("maskAssetId"):
            mask_asset = app.state.assets.get_asset(project_id=project_id, asset_id=str(payload["maskAssetId"]))
            if mask_asset is None:
                raise ValueError("maskAssetId 不属于当前项目或资产不存在")
            if mask_asset.get("kind") != "image":
                raise ValueError("maskAssetId 必须指向 image 资产")
            provider_params["mask_asset_path"] = mask_asset["absolutePath"]
        from .image_routing import build_image_route, dispatch_image_route
        try:
            route_plan,route_candidates=build_image_route(
                app.state.providers,provider=provider_key,base_url=base_url,requested_model=requested_model or ('placeholder-v0' if provider_key=='local-placeholder' else None),
                decision=decision,params=provider_params,has_references=bool(parent_asset_id),reference_count=1 if parent_asset_id else 0,
            )
        except ValueError as error:
            raise HTTPException(status_code=422,detail=str(error)) from error
        from .conversation_memory import ConversationMemoryService
        reference_snapshot=ConversationMemoryService(store).validate_generation(project_id,None,{'source_asset_id':parent_asset_id})
        def validate_image(content,candidate):
            if not content:
                raise ValueError('图像 Provider 没有返回可保存的内容')
            return reject_svg_output(content,transparent_requested=candidate.options.get('background')=='transparent')
        content,candidate,image_route,image_info=dispatch_image_route(
            route_plan,route_candidates,prompt=provider_prompt,negative_prompt=negative_prompt or None,validate_content=validate_image,
        )
        model,provider,provider_params,quality_info=candidate.model,candidate.adapter,candidate.options,candidate.quality
        for key in ('quality', 'input_fidelity', 'size', 'resolution', 'aspectRatio', 'aspect_ratio'):
            params.pop(key, None)
            if key in provider_params:
                params[key] = provider_params[key]
        with store._connect() as quality_db:
            quality_db.execute('UPDATE generations SET model=?, params_json=? WHERE id=?',(model,json.dumps(params),generation_id))
        if image_info.get('verified'):
            extension = {'jpeg':'jpg'}.get(image_info['format'], image_info['format'])
        content, normalized_extension = _pad_image_to_ratio(content, image_ratio)
        if normalized_extension:
            extension = normalized_extension
        image_contract = {"schemaVersion": "langju-agent-v1", "outputKind": "raster", "imageRatio": image_ratio or "16:9", "imageFit": "contain", "imageRole": payload.get("imageRole") or "生成图像", "prompt": prompt, "negativePrompt": negative_prompt or "文字、Logo、水印、UI、边框、拼贴、多角色、裁切主体、SVG、矢量图、乱码", "provider": provider_key, "model": model, "status": "generated"}
        asset = app.state.assets.add_bytes(project_id=project_id, kind="image", filename=f"generation-{generation_id}.{extension}", content=content, metadata={"imageQuality":quality_info,"imageRoute":image_route,"referenceSnapshot":reference_snapshot,"sourceAssetIds":[parent_asset_id] if parent_asset_id else [],"generationId": generation_id, "prompt": prompt, "negativePrompt": negative_prompt, "provider": provider_key, "model": model, "params": params, "imageRatio": image_ratio or None, "imageFit": "contain", "imageRequired": payload.get("imageRequired", True), "imageRole": payload.get("imageRole"), "outputKind": "raster", "contractVersion": "langju-agent-v1", "source": "report-agent" if payload.get("imageRequired") is not False else "user-requested"})
        with store._connect() as connection:
            connection.execute("UPDATE generations SET asset_id = ?, status = 'succeeded' WHERE id = ?", (asset["id"], generation_id))
        return {"generationId": generation_id, "provider": provider_key, "model": model, "status": "succeeded", "asset": asset, "parentGenerationId": parent_generation_id, "imageRoute":image_route,"imageOutput": {**image_contract, "assetId": asset["id"], "generationId": generation_id}}
    except (ProviderError, ValueError) as error:
        with store._connect() as connection:
            connection.execute("UPDATE generations SET status = 'failed', evaluation_json = ? WHERE id = ?", (json.dumps({"error": str(error)}, ensure_ascii=False), generation_id))
        if isinstance(error, ProviderError):
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from error
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error


@app.get("/api/projects/{project_id}/generations")
def list_generations(project_id: str, store: Store):
    if store.get_project(project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    with store._connect() as connection:
        rows = connection.execute("SELECT * FROM generations WHERE project_id = ? ORDER BY created_at DESC", (project_id,)).fetchall()
        evaluations = connection.execute("SELECT * FROM evaluations WHERE generation_id IN (SELECT id FROM generations WHERE project_id = ?) ORDER BY created_at DESC", (project_id,)).fetchall()
    evaluation_map: dict[str, list[dict]] = {}
    for row in evaluations:
        evaluation_map.setdefault(row["generation_id"], []).append({"id": row["id"], "evaluatorType": row["evaluator_type"], "score": json.loads(row["score_json"] or "{}"), "feedback": row["feedback_md"], "createdAt": row["created_at"]})
    return [_generation_row(row, evaluation_map.get(row["id"], [])) for row in rows]


@app.get("/api/projects/{project_id}/generations/{generation_id}")
def get_generation(project_id: str, generation_id: str, store: Store):
    if store.get_project(project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    with store._connect() as connection:
        row = connection.execute("SELECT * FROM generations WHERE id = ? AND project_id = ?", (generation_id, project_id)).fetchone()
        evaluations = connection.execute("SELECT * FROM evaluations WHERE generation_id = ? ORDER BY created_at DESC", (generation_id,)).fetchall()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="生成记录不存在")
    return _generation_row(row, [{"id": item["id"], "evaluatorType": item["evaluator_type"], "score": json.loads(item["score_json"] or "{}"), "feedback": item["feedback_md"], "createdAt": item["created_at"]} for item in evaluations])


def _generation_row(row, evaluations: list[dict]) -> dict:
    metadata = json.loads(row["evaluation_json"] or "{}")
    return {"id": row["id"], "projectId": row["project_id"], "provider": row["provider"], "model": row["model"], "promptVersionId": row["prompt_version_id"], "prompt": row["prompt_text"] if "prompt_text" in row.keys() else "", "negativePrompt": row["negative_prompt"] if "negative_prompt" in row.keys() else "", "params": json.loads(row["params_json"] or "{}"), "assetId": row["asset_id"] if "asset_id" in row.keys() else None, "parentAssetId": row["parent_asset_id"], "parentGenerationId": row["parent_generation_id"] if "parent_generation_id" in row.keys() else None, "status": row["status"], "providerJob": metadata.get("job"), "evaluations": evaluations, "createdAt": row["created_at"]}


@app.post("/api/projects/{project_id}/generations/{generation_id}/evaluate", status_code=status.HTTP_201_CREATED)
def evaluate_generation(project_id: str, generation_id: str, payload: dict, store: Store):
    if store.get_project(project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    evaluator_type = str(payload.get("evaluatorType", "human")).strip() or "human"
    feedback = str(payload.get("feedback", ""))
    score = payload.get("score") or {}
    with store._connect() as connection:
        exists = connection.execute("SELECT 1 FROM generations WHERE id = ? AND project_id = ?", (generation_id, project_id)).fetchone()
        if exists is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="生成记录不存在")
        evaluation_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()
        connection.execute("INSERT INTO evaluations (id, generation_id, evaluator_type, score_json, feedback_md, created_at) VALUES (?, ?, ?, ?, ?, ?)", (evaluation_id, generation_id, evaluator_type, json.dumps(score, ensure_ascii=False), feedback, now))
        connection.execute("UPDATE generations SET evaluation_json = ? WHERE id = ?", (json.dumps({"latest": score, "feedback": feedback}, ensure_ascii=False), generation_id))
    return {"id": evaluation_id, "generationId": generation_id, "evaluatorType": evaluator_type, "score": score, "feedback": feedback, "createdAt": now}


@app.post("/api/projects/{project_id}/generations/{generation_id}/evaluate-ai", status_code=status.HTTP_201_CREATED)
def evaluate_generation_ai(project_id: str, generation_id: str, store: Store):
    if store.get_project(project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    with store._connect() as connection:
        row = connection.execute("SELECT * FROM generations WHERE id = ? AND project_id = ?", (generation_id, project_id)).fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="生成记录不存在")
    asset = app.state.assets.get_asset(project_id=project_id, asset_id=row["asset_id"]) if row["asset_id"] else None
    if asset is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="生成记录没有可评价的真实图像资产")
    try:
        asset_path = Path(str(asset.get("absolutePath") or ""))
        asset_content = asset_path.read_bytes()
        evaluation = app.state.evaluator.evaluate_image(
            prompt=row["prompt_text"],
            params=json.loads(row["params_json"] or "{}"),
            provider=row["provider"],
            has_lineage=bool(row["parent_generation_id"] or row["parent_asset_id"]),
            image_content=asset_content,
            image_mime=asset.get("mime") or "image/png",
            trace_id=f"image-evaluation:{generation_id}",
        )
    except (OSError, ProviderError, ValueError) as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"AI 图像评价失败，未生成虚拟评分：{error}") from error
    evaluation_id = str(uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with store._connect() as connection:
        connection.execute("INSERT INTO evaluations (id, generation_id, evaluator_type, score_json, feedback_md, created_at) VALUES (?, ?, 'ai', ?, ?, ?)", (evaluation_id, generation_id, json.dumps(evaluation["score"], ensure_ascii=False), evaluation["feedback"], now))
        connection.execute("UPDATE generations SET evaluation_json = ? WHERE id = ?", (json.dumps({"latest": evaluation["score"], "feedback": evaluation["feedback"], "evaluatorType": "ai", "provenance": evaluation["provenance"]}, ensure_ascii=False), generation_id))
    return {"id": evaluation_id, "generationId": generation_id, "evaluatorType": "ai", "score": evaluation["score"], "feedback": evaluation["feedback"], "provenance": evaluation["provenance"], "createdAt": now}


@app.post("/api/projects/{project_id}/generations/{generation_id}/regenerate", status_code=status.HTTP_201_CREATED)
def regenerate_generation(project_id: str, generation_id: str, payload: dict, store: Store):
    if store.get_project(project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    with store._connect() as connection:
        row = connection.execute("SELECT * FROM generations WHERE id = ? AND project_id = ?", (generation_id, project_id)).fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="生成记录不存在")
    params = _object_field(payload, "params") if payload.get("params") is not None else _json_object(row["params_json"])
    next_payload = {"prompt": payload.get("prompt") or row["prompt_text"], "negativePrompt": payload.get("negativePrompt") if payload.get("negativePrompt") is not None else row["negative_prompt"], "provider": payload.get("provider") or row["provider"], "model": payload.get("model") or row["model"], "baseUrl": payload.get("baseUrl") or _default_openai_base_url(), "maskAssetId": payload.get("maskAssetId"), "quality":payload.get("quality") or ((payload.get("params") or {}).get("quality") if isinstance(payload.get("params"),dict) else None) or "final", "params": params}
    return _run_image_generation(project_id=project_id, payload=next_payload, store=store, parent_generation_id=generation_id, parent_asset_id=row["asset_id"])


@app.post("/api/projects/{project_id}/generations/3d", status_code=status.HTTP_201_CREATED)
def generate_3d(project_id: str, payload: dict, store: Store):
    if store.get_project(project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    prompt = str(payload.get("prompt", "")).strip()
    if not prompt:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="prompt 不能为空")
    endpoint = str(payload.get("endpoint")) if payload.get("endpoint") else None
    provider_hint = str(payload.get("provider")) if payload.get("provider") and str(payload.get("provider")).lower() not in {"auto", "native"} else None
    provider_key = app.state.providers.detect_3d_provider(endpoint, provider_hint)
    output_format = str(payload.get("outputFormat", "glb")).lower()
    if output_format not in {"glb", "gltf", "obj", "fbx", "stl"}:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="outputFormat 必须是 glb/gltf/obj/fbx/stl")
    generation_id = str(uuid4())
    now = datetime.now(timezone.utc).isoformat()
    params = _object_field(payload, "params")
    source_asset_id = payload.get("sourceAssetId")
    source_asset = None
    if source_asset_id:
        source_asset = app.state.assets.get_asset(project_id=project_id, asset_id=str(source_asset_id))
        if source_asset is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="输入资产不存在")
    with store._connect() as connection:
        connection.execute("INSERT INTO generations (id, project_id, provider, model, prompt_text, negative_prompt, params_json, parent_asset_id, status, created_at) VALUES (?, ?, ?, ?, ?, '', ?, ?, 'running', ?)", (generation_id, project_id, provider_key, str(payload.get("model") or provider_key), prompt, json.dumps({**params, "outputFormat": output_format}, ensure_ascii=False), source_asset_id, now))
    try:
        provider_params = dict(params)
        provider_params.pop("prompt", None)
        provider_params.pop("source_asset", None)
        provider_params.pop("outputFormat", None)
        provider_params.pop("output_format", None)
        provider_params.pop("ipProfileId", None)
        provider_params.pop("ipProfileVersion", None)
        media_settings = app.state.model_catalog.settings().media["3d"]
        selected_model = payload.get("model") or media_settings.get("draft" if payload.get("quality") == "draft" else "final")
        if selected_model:
            provider_params["model"] = selected_model
        job = app.state.providers.three_d(provider_key, endpoint=endpoint).generate(prompt=prompt, source_asset=source_asset["absolutePath"] if source_asset else None, output_format=output_format, **provider_params)
        if not isinstance(job, dict):
            raise ProviderError("3D Provider 返回了无效的任务对象")
        output_asset_id = None
        model_content = job.pop("content", None)
        if isinstance(model_content, (bytes, bytearray)) and model_content:
            extension = str(job.pop("extension", output_format)).lstrip(".")
            asset = app.state.assets.add_bytes(project_id=project_id, kind="3d", filename=f"{provider_key}-{generation_id}.{extension}", content=bytes(model_content), metadata={"provider": provider_key, "model": str(payload.get("model") or provider_key), "sourceAssetId": source_asset_id, "prompt": prompt, "outputFormat": output_format})
            output_asset_id = asset["id"]
        if isinstance(job, dict) and "sourceAsset" in job:
            job["sourceAsset"] = source_asset_id
        # Keep the user-configured endpoint in the job envelope so a later
        # refresh can recover an async task after the app or sidecar restarts.
        if isinstance(job, dict):
            job["endpoint"] = _safe_endpoint(endpoint)
        with store._connect() as connection:
            connection.execute("UPDATE generations SET asset_id = ?, status = ?, evaluation_json = ? WHERE id = ?", (output_asset_id, job.get("status", "submitted"), json.dumps({"job": job}, ensure_ascii=False), generation_id))
        return {"generationId": generation_id, "provider": provider_key, "status": job.get("status", "submitted"), "job": job, "sourceAssetId": source_asset_id, "asset": app.state.assets.get_asset(project_id=project_id, asset_id=output_asset_id) if output_asset_id else None}
    except (ProviderError, ValueError) as error:
        with store._connect() as connection:
            connection.execute("UPDATE generations SET status = 'failed', evaluation_json = ? WHERE id = ?", (json.dumps({"error": str(error)}, ensure_ascii=False), generation_id))
        if isinstance(error, ProviderError):
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from error
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error


@app.post("/api/projects/{project_id}/generations/{generation_id}/3d/refresh")
def refresh_3d_generation(project_id: str, generation_id: str, store: Store):
    """Refresh a submitted native/generic 3D task and persist model bytes."""
    if store.get_project(project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    with store._connect() as connection:
        row = connection.execute("SELECT * FROM generations WHERE id = ? AND project_id = ?", (generation_id, project_id)).fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="3D 生成记录不存在")
    envelope = _json_object(row["evaluation_json"])
    saved_job = envelope.get("job") if isinstance(envelope, dict) else None
    if not isinstance(saved_job, dict) or not saved_job.get("jobId"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="当前 3D 任务没有可查询的 Job ID")
    endpoint = _safe_endpoint(saved_job.get("endpoint"))
    if not endpoint:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="当前 3D 任务没有保存 endpoint，无法刷新")
    params = _json_object(row["params_json"])
    output_format = str(params.get("outputFormat") or saved_job.get("outputFormat") or "glb").lower()
    source_asset = app.state.assets.get_asset(project_id=project_id, asset_id=str(row["parent_asset_id"])) if row["parent_asset_id"] else None
    provider_params = dict(saved_job.get("params")) if isinstance(saved_job.get("params"), dict) else {}
    for reserved in ("prompt", "source_asset", "outputFormat", "output_format", "ipProfileId", "ipProfileVersion", "jobId", "job_id", "endpoint"):
        provider_params.pop(reserved, None)
    try:
        provider = app.state.providers.three_d(row["provider"], endpoint=str(endpoint))
        result = provider.retrieve(job_id=str(saved_job["jobId"]), prompt=row["prompt_text"], source_asset=source_asset["absolutePath"] if source_asset else None, output_format=output_format, **provider_params)
        if not isinstance(result, dict):
            raise ProviderError("3D Provider 返回了无效的任务对象")
    except ProviderError as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    output_asset_id = row["asset_id"]
    model_content = result.pop("content", None)
    if isinstance(model_content, (bytes, bytearray)) and model_content:
        extension = str(result.pop("extension", output_format)).lstrip(".")
        asset = app.state.assets.add_bytes(project_id=project_id, kind="3d", filename=f"{row['provider']}-{generation_id}.{extension}", content=bytes(model_content), metadata={"provider": row["provider"], "model": row["model"], "sourceAssetId": row["parent_asset_id"], "ipProfileVersion": params.get("ipProfileVersion"), "prompt": row["prompt_text"], "outputFormat": output_format})
        output_asset_id = asset["id"]
    if isinstance(result, dict):
        result["endpoint"] = endpoint
        if saved_job.get("canvasNodeId"):
            result["canvasNodeId"] = saved_job["canvasNodeId"]
        if "sourceAsset" in result:
            result["sourceAsset"] = row["parent_asset_id"]
    next_status = result.get("status", row["status"])
    with store._connect() as connection:
        connection.execute("UPDATE generations SET asset_id = ?, status = ?, evaluation_json = ? WHERE id = ?", (output_asset_id, next_status, json.dumps({"job": result}, ensure_ascii=False), generation_id))
    if output_asset_id and saved_job.get("canvasNodeId"):
        app.state.design_tools.canvas_store.ensure_asset_node(project_id, app.state.assets.get_asset(project_id=project_id, asset_id=output_asset_id), target_node_id=saved_job["canvasNodeId"])
    return {"generationId": generation_id, "provider": row["provider"], "status": next_status, "job": result, "sourceAssetId": row["parent_asset_id"], "asset": app.state.assets.get_asset(project_id=project_id, asset_id=output_asset_id) if output_asset_id else None}
