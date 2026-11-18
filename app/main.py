"""FastAPI entrypoint for the team knowledge-base agent."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import (
    Depends,
    FastAPI,
    File,
    HTTPException,
    Path as PathParam,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.agent import AgentService
from app.config import Settings, get_settings
from app.knowledge import (
    DocumentNotFound,
    DocumentParseError,
    DuplicateDocument,
    KnowledgeBase,
    TeamNotFound,
    UnsupportedFileType,
)
from app.schemas import (
    SESSION_ID_PATTERN,
    TEAM_ID_PATTERN,
    ChatRequest,
    ChatResponse,
    DocumentListResponse,
    DocumentResponse,
    HealthResponse,
    HistoryResponse,
    TeamCreate,
    TeamResponse,
    TeamStatsResponse,
)

logger = logging.getLogger("agent")
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = app.state.settings
    knowledge_base = KnowledgeBase(settings)
    app.state.kb = knowledge_base
    app.state.service = AgentService(settings, knowledge_base)
    logger.info(
        "Agent ready (model=%s, demo=%s, data=%s)",
        app.state.service.model_name,
        app.state.service.demo_mode,
        knowledge_base.data_dir,
    )
    yield
    app.state.service = None
    app.state.kb = None


def get_service(request: Request) -> AgentService:
    service = getattr(request.app.state, "service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Agent is not initialized")
    return service


def get_kb(request: Request) -> KnowledgeBase:
    kb = getattr(request.app.state, "kb", None)
    if kb is None:
        raise HTTPException(status_code=503, detail="Knowledge base is not initialized")
    return kb


ServiceDep = Annotated[AgentService, Depends(get_service)]
KnowledgeDep = Annotated[KnowledgeBase, Depends(get_kb)]
SessionId = Annotated[str, PathParam(pattern=SESSION_ID_PATTERN)]
TeamId = Annotated[str, PathParam(pattern=TEAM_ID_PATTERN)]
TeamQuery = Annotated[str, Query(pattern=TEAM_ID_PATTERN)]


def _team_response(team) -> TeamResponse:
    return TeamResponse(
        id=team.id,
        name=team.name,
        document_count=team.document_count,
        created_at=team.created_at,
    )


def _document_response(document, team_id: str) -> DocumentResponse:
    return DocumentResponse(
        id=document.id,
        team_id=document.team_id,
        filename=document.filename,
        content_type=document.content_type,
        size_bytes=document.size_bytes,
        page_count=document.page_count,
        chunk_count=document.chunk_count,
        created_at=document.created_at,
        download_url=f"/api/teams/{team_id}/documents/{document.id}/download",
    )


def _knowledge_error(exc: Exception) -> HTTPException:
    if isinstance(exc, TeamNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, DocumentNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, DuplicateDocument):
        return HTTPException(
            status_code=409,
            detail=f"这个文件已经上传过（document_id={exc.document_id}）",
        )
    if isinstance(exc, UnsupportedFileType):
        return HTTPException(status_code=415, detail=str(exc))
    if isinstance(exc, DocumentParseError):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description="Team-scoped knowledge base agent built with LangChain and FastAPI.",
        lifespan=lifespan,
    )
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=settings.cors_origin_list != ["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/healthz", response_model=HealthResponse, tags=["system"])
    async def health(service: ServiceDep) -> HealthResponse:
        return HealthResponse(
            app=settings.app_name,
            version=__version__,
            model=service.model_name,
            demo_mode=service.demo_mode,
            web_search=service.web_search_available,
        )

    @app.post("/api/teams", response_model=TeamResponse, status_code=201, tags=["teams"])
    async def create_team(payload: TeamCreate, kb: KnowledgeDep) -> TeamResponse:
        return _team_response(kb.create_team(payload.name))

    @app.get("/api/teams", response_model=list[TeamResponse], tags=["teams"])
    async def list_teams(kb: KnowledgeDep) -> list[TeamResponse]:
        return [_team_response(team) for team in kb.list_teams()]

    @app.get(
        "/api/teams/{team_id}/stats",
        response_model=TeamStatsResponse,
        tags=["teams"],
    )
    async def team_stats(team_id: TeamId, kb: KnowledgeDep) -> TeamStatsResponse:
        try:
            documents, chunks = kb.stats(team_id)
        except TeamNotFound as exc:
            raise _knowledge_error(exc) from exc
        return TeamStatsResponse(team_id=team_id, documents=documents, chunks=chunks)

    @app.post(
        "/api/teams/{team_id}/documents",
        response_model=DocumentResponse,
        status_code=201,
        tags=["knowledge"],
    )
    async def upload_document(
        team_id: TeamId,
        kb: KnowledgeDep,
        file: UploadFile = File(...),
    ) -> DocumentResponse:
        try:
            kb.require_team(team_id)
        except TeamNotFound as exc:
            raise _knowledge_error(exc) from exc

        if not file.filename:
            raise HTTPException(status_code=422, detail="缺少文件名")
        max_bytes = settings.max_upload_mb * 1024 * 1024
        data = await file.read(max_bytes + 1)
        await file.close()
        if len(data) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"文件超过 {settings.max_upload_mb} MB 限制",
            )

        try:
            document = kb.add_document(
                team_id=team_id,
                filename=file.filename,
                content_type=file.content_type or "application/octet-stream",
                data=data,
            )
        except Exception as exc:
            raise _knowledge_error(exc) from exc
        return _document_response(document, team_id)

    @app.get(
        "/api/teams/{team_id}/documents",
        response_model=DocumentListResponse,
        tags=["knowledge"],
    )
    async def list_documents(team_id: TeamId, kb: KnowledgeDep) -> DocumentListResponse:
        try:
            documents = kb.list_documents(team_id)
        except TeamNotFound as exc:
            raise _knowledge_error(exc) from exc
        return DocumentListResponse(
            team_id=team_id,
            documents=[_document_response(document, team_id) for document in documents],
        )

    @app.delete(
        "/api/teams/{team_id}/documents/{document_id}",
        status_code=204,
        response_class=Response,
        tags=["knowledge"],
    )
    async def delete_document(
        team_id: TeamId,
        document_id: str,
        kb: KnowledgeDep,
    ) -> Response:
        try:
            kb.delete_document(team_id, document_id)
        except (TeamNotFound, DocumentNotFound) as exc:
            raise _knowledge_error(exc) from exc
        return Response(status_code=204)

    @app.get(
        "/api/teams/{team_id}/documents/{document_id}/download",
        tags=["knowledge"],
    )
    async def download_document(
        team_id: TeamId,
        document_id: str,
        kb: KnowledgeDep,
    ) -> FileResponse:
        try:
            document = kb.get_document(team_id, document_id)
        except DocumentNotFound as exc:
            raise _knowledge_error(exc) from exc
        path = Path(document.stored_path)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="原始文件不存在")
        return FileResponse(
            path,
            media_type=document.content_type,
            filename=document.filename,
        )

    @app.post("/api/chat", response_model=ChatResponse, tags=["agent"])
    async def chat(payload: ChatRequest, service: ServiceDep) -> ChatResponse:
        if len(payload.message) > settings.max_input_chars:
            raise HTTPException(
                status_code=422,
                detail=f"message exceeds {settings.max_input_chars} characters",
            )

        session_id = payload.session_id or uuid4().hex
        try:
            return await service.chat(payload.team_id, session_id, payload.message)
        except TeamNotFound as exc:
            raise _knowledge_error(exc) from exc
        except Exception as exc:  # pragma: no cover - provider/network failure path
            logger.exception("Agent invocation failed for session %s", session_id)
            raise HTTPException(
                status_code=502,
                detail="Agent invocation failed. Check the LLM configuration and try again.",
            ) from exc

    @app.get(
        "/api/sessions/{session_id}/history",
        response_model=HistoryResponse,
        tags=["sessions"],
    )
    async def history(
        session_id: SessionId,
        service: ServiceDep,
        team_id: TeamQuery = "default",
    ) -> HistoryResponse:
        try:
            return await service.history(team_id, session_id)
        except TeamNotFound as exc:
            raise _knowledge_error(exc) from exc

    @app.delete(
        "/api/sessions/{session_id}",
        status_code=204,
        response_class=Response,
        tags=["sessions"],
    )
    async def reset(
        session_id: SessionId,
        service: ServiceDep,
        team_id: TeamQuery = "default",
    ) -> Response:
        try:
            await service.reset(team_id, session_id)
        except TeamNotFound as exc:
            raise _knowledge_error(exc) from exc
        return Response(status_code=204)

    return app


app = create_app()
