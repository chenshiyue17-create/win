from __future__ import annotations

import logging
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from customer_context_assistant.assistant_engine import AssistantEngine
from customer_context_assistant.config import Settings, load_settings
from customer_context_assistant.conversation_store import ConversationStore, infer_session_id_from_text
from customer_context_assistant.github_archive import archive_status, export_archive
from customer_context_assistant.interaction_store import InteractionStore
from customer_context_assistant.knowledge_base import KnowledgeBase
from customer_context_assistant.learning_engine import LearningQueue
from customer_context_assistant.logging_setup import configure_logging
from customer_context_assistant.models import (
    AnalyzeRequest,
    AnalyzeResponse,
    ConversationSession,
    InteractionLogResponse,
    KnowledgeBatch,
    KnowledgeEntry,
    KnowledgeImportResponse,
    KnowledgeSearchRequest,
    KnowledgeStatus,
    LearningIngestRequest,
    LearningQueueResponse,
    LearningReviewRequest,
    RecognitionResponse,
)
from customer_context_assistant.recognizer import latest_customer_messages, recognize_image_payload, recognize_text_payload
from customer_context_assistant.web_harvester import harvest_comments_from_url


LOGGER = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    configure_logging(settings.app.log_file)
    settings.root.joinpath("output").mkdir(exist_ok=True)
    settings.root.joinpath("logs").mkdir(exist_ok=True)

    kb = KnowledgeBase(
        settings.knowledge_base.source_file,
        seed_file=settings.knowledge_base.seed_file,
        backup_dir=settings.knowledge_base.backup_dir,
        min_entries=settings.knowledge_base.min_entries,
    )
    engine = AssistantEngine(kb, settings.knowledge_base, settings.assistant, llm_config=settings.llm)
    learning_queue = LearningQueue(settings.root / "data" / "learning_queue.json", llm_config=settings.llm)
    interaction_store = InteractionStore(settings.root / "data" / "interactions")
    conversation_store = ConversationStore(settings.root / "data" / "conversations.json")
    app = FastAPI(title=settings.app.name)
    static_dir = settings.root / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    @app.get("/overlay")
    def overlay() -> FileResponse:
        return FileResponse(static_dir / "overlay.html")

    @app.get("/kb-trainer")
    def kb_trainer() -> FileResponse:
        return FileResponse(static_dir / "kb_trainer.html")

    @app.get("/api/health")
    def health() -> dict[str, object]:
        return {"ok": True, "entries": len(kb.list_entries())}

    @app.get("/api/kb")
    def list_kb() -> dict[str, object]:
        return {"entries": [entry.model_dump() for entry in kb.list_entries()]}

    @app.get("/api/kb/status", response_model=KnowledgeStatus)
    def kb_status() -> KnowledgeStatus:
        return kb.status()

    @app.post("/api/kb/backup", response_model=KnowledgeStatus)
    def backup_kb() -> KnowledgeStatus:
        kb.create_backup(reason="manual")
        return kb.status()

    @app.get("/api/kb/github/status")
    def github_archive_status() -> dict[str, object]:
        return archive_status().model_dump()

    @app.post("/api/kb/github/export")
    def github_archive_export() -> dict[str, object]:
        return export_archive(kb.list_entries()).model_dump()

    @app.post("/api/kb/entry")
    def add_kb_entry(entry: KnowledgeEntry) -> KnowledgeEntry:
        try:
            return kb.add_entry(entry)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.put("/api/kb/entry/{entry_id}")
    def upsert_kb_entry(entry_id: str, entry: KnowledgeEntry) -> KnowledgeEntry:
        if entry_id != entry.id:
            raise HTTPException(status_code=400, detail="entry id does not match path")
        saved, _ = kb.upsert_entry(entry)
        return saved

    @app.post("/api/kb/import", response_model=KnowledgeImportResponse)
    def import_kb(batch: KnowledgeBatch) -> KnowledgeImportResponse:
        try:
            created, updated, entries = kb.import_entries(batch.entries, batch.mode)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return KnowledgeImportResponse(total=len(entries), created=created, updated=updated, entries=entries)

    @app.post("/api/kb/search")
    def search_kb(request: KnowledgeSearchRequest) -> dict[str, object]:
        if not request.query.strip():
            raise HTTPException(status_code=400, detail="query is required")
        matches = kb.search(request.query, limit=max(1, min(request.limit, 20)), min_score=1)
        return {"matches": [match.model_dump() for match in matches]}

    @app.post("/api/recognize-text", response_model=RecognitionResponse)
    def recognize_text(payload: dict[str, str]) -> RecognitionResponse:
        text = payload.get("text", "")
        if not text.strip():
            raise HTTPException(status_code=400, detail="text is required")
        return recognize_text_payload(text)

    @app.post("/api/recognize-image", response_model=RecognitionResponse)
    async def recognize_image(file: UploadFile = File(...)) -> RecognitionResponse:
        if file.content_type not in settings.recognition.allowed_image_types:
            raise HTTPException(status_code=400, detail="Only png, jpeg, or webp screenshots are supported")
        data = await file.read()
        max_bytes = settings.recognition.max_upload_mb * 1024 * 1024
        if len(data) > max_bytes:
            raise HTTPException(status_code=400, detail=f"Image is larger than {settings.recognition.max_upload_mb} MB")
        upload_dir = settings.root / "output" / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        safe_name = Path(file.filename or "window.png").name
        upload_dir.joinpath(safe_name).write_bytes(data)
        try:
            return recognize_image_payload(data, settings.recognition.ocr_language)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/harvest-url", response_model=RecognitionResponse)
    async def harvest_url(payload: dict) -> RecognitionResponse:
        url = payload.get("url")
        if not url:
            raise HTTPException(status_code=400, detail="URL is required")
        return await harvest_comments_from_url(url, settings.recognition.ocr_language)

    @app.post("/api/analyze", response_model=AnalyzeResponse)
    def analyze(request: AnalyzeRequest) -> AnalyzeResponse:
        if not request.messages:
            raise HTTPException(status_code=400, detail="messages cannot be empty")
        target_messages = latest_customer_messages(request.messages)
        if not target_messages:
            return AnalyzeResponse(hints=[])
        raw_text = "\n".join(message.text for message in request.messages)
        session_id = infer_session_id_from_text(raw_text, request.session_id)
        prior_context = conversation_store.recent_context(session_id, limit=8)
        analysis_messages = prior_context + target_messages
        candidates = []
        if request.learn:
            candidates = learning_queue.ingest_messages(target_messages, kb, source="analyze")
        response = engine.analyze(AnalyzeRequest(
            messages=analysis_messages, 
            include_safety=request.include_safety, 
            session_id=session_id,
            image_bytes=request.image_bytes
        ))
        conversation_store.append_messages(session_id, target_messages)
        interaction_store.append(
            source="api_analyze",
            input_type="text",
            raw_text=raw_text,
            messages=target_messages,
            output=response,
            learning_candidate_ids=[candidate.id for candidate in candidates],
            metadata={"session_id": session_id},
        )
        return response

    @app.get("/api/conversations", response_model=list[ConversationSession])
    def list_conversations() -> list[ConversationSession]:
        return conversation_store.list_sessions()

    @app.get("/api/interactions", response_model=InteractionLogResponse)
    def list_interactions(limit: int = 50) -> InteractionLogResponse:
        safe_limit = max(1, min(limit, 500))
        records = interaction_store.list(limit=safe_limit)
        return InteractionLogResponse(records=records, total=interaction_store.count())

    @app.post("/api/interactions/export")
    def export_interactions() -> dict[str, str]:
        output = interaction_store.export_distill_jsonl(settings.root / "data" / "distill" / "interactions_distill.jsonl")
        return {"output_path": str(output)}

    @app.get("/api/learning/candidates", response_model=LearningQueueResponse)
    def list_learning_candidates(status: str = "pending") -> LearningQueueResponse:
        return LearningQueueResponse(candidates=learning_queue.list(status=status or None))

    @app.post("/api/learning/ingest", response_model=LearningQueueResponse)
    def ingest_learning(request: LearningIngestRequest) -> LearningQueueResponse:
        if not request.messages:
            raise HTTPException(status_code=400, detail="messages cannot be empty")
        created = learning_queue.ingest_messages(request.messages, kb, source=request.source)
        return LearningQueueResponse(candidates=created)

    @app.post("/api/learning/candidates/{candidate_id}/approve")
    def approve_learning_candidate(candidate_id: str, request: LearningReviewRequest) -> dict[str, object]:
        try:
            candidate = learning_queue.approve(candidate_id, kb, review_note=request.review_note)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="candidate not found") from exc
        return {"candidate": candidate.model_dump(), "knowledge_status": kb.status().model_dump()}

    @app.post("/api/learning/candidates/{candidate_id}/reject")
    def reject_learning_candidate(candidate_id: str, request: LearningReviewRequest) -> dict[str, object]:
        try:
            candidate = learning_queue.update_status(candidate_id, "rejected", review_note=request.review_note)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="candidate not found") from exc
        return {"candidate": candidate.model_dump()}

    return app


def run() -> None:
    settings = load_settings()
    uvicorn.run(
        "customer_context_assistant.app:create_app",
        host=settings.app.host,
        port=settings.app.port,
        factory=True,
        reload=False,
    )
