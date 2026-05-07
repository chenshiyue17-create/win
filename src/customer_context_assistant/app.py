from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from customer_context_assistant.assistant_engine import AssistantEngine, build_direct_visual_reply
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
    KnowledgeAttachment,
    KnowledgeEntry,
    KnowledgeImportResponse,
    KnowledgeSearchRequest,
    KnowledgeStatus,
    LearningIngestRequest,
    LearningQueueResponse,
    LearningReviewRequest,
    MessageInput,
    RecognitionResponse,
)
from customer_context_assistant.recognizer import latest_customer_messages, recognize_image_payload, recognize_text_payload
from customer_context_assistant.structure_classifier import identify_brand_by_structure
from customer_context_assistant.visual_index import VisualIndex
try:
    from customer_context_assistant.web_harvester import harvest_comments_from_url
except ModuleNotFoundError:
    harvest_comments_from_url = None


LOGGER = logging.getLogger(__name__)


def _safe_upload_name(filename: str | None) -> str:
    suffix = Path(filename or "upload.bin").suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        suffix = ".png"
    return f"{uuid4().hex}{suffix}"


def _is_allowed_image_upload(file: UploadFile, allowed_types: tuple[str, ...]) -> bool:
    if file.content_type in allowed_types:
        return True
    return Path(file.filename or "").suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}


def _build_codex_handoff(
    *,
    image_path: Path,
    question: str,
    recognized_text: str,
    matches: list,
    visual_matches: list,
) -> str:
    match_lines = []
    for index, match in enumerate(matches[:6], start=1):
        entry = match.entry
        preview = " ".join(entry.content.split())[:360]
        match_lines.append(f"{index}. {entry.title}｜得分 {match.score}｜标签：{', '.join(entry.tags[:8])}\n   {preview}")
    knowledge = "\n".join(match_lines) if match_lines else "暂无明显知识命中。"
    visual_lines = []
    for index, match in enumerate(visual_matches[:5], start=1):
        entry = match.entry
        replies = " ".join(entry.author_replies)[:260] or "无作者回复摘录"
        brands = "、".join(entry.brand_clues) or "无明确品牌线索"
        visual_lines.append(
            f"{index}. {entry.title}｜视觉相似度 {match.score:.2f}｜品牌线索：{brands}\n"
            f"   原图：{entry.source_image}\n"
            f"   作者回复：{replies}"
        )
    visual_knowledge = "\n".join(visual_lines) if visual_lines else "暂无图库视觉相似样本。"
    return "\n".join(
        [
            "请把下面内容交给 Codex，并使用 menchuang-image-consultant skill 深度分析这张门窗图片。",
            "",
            f"图片路径：{image_path}",
            f"客户问题：{question or '帮我看这张门窗图片，判断结构优缺点、品牌线索、价格和追问清单。'}",
            f"OCR文本：{recognized_text or '无可用 OCR 文本，以图片视觉结构为主。'}",
            "",
            "图库视觉相似样本：",
            visual_knowledge,
            "",
            "仓库知识命中：",
            knowledge,
            "",
            "输出要求：",
            "1. 先识别图片类型和室内外方向，不确定就说明。",
            "2. 逐项看主框、副框、玻扇、压线、隔热条、胶条、玻璃入槽、五金位。",
            "3. 分析承重、隔热、水密、气密、工艺售后四条路径。",
            "4. 先看图库视觉相似样本的截面结构，再看作者回复里的品牌/结构证据；不要让品牌词或价格词替代结构判断。",
            "5. 品牌只能说疑似/像/有某类线索，除非图上有直接商标、型材喷码或报价单证据。",
            "6. 价格要结合安装、开扇、运费、吊装、玻璃增配，不要绝对化。",
            "7. 最后给一段能直接复制给客户的中文回复。",
        ]
    )


def _visual_matches_to_context(visual_matches: list) -> str:
    if not visual_matches:
        return ""
    lines = ["图库视觉相似样本命中："]
    for match in visual_matches[:5]:
        entry = match.entry
        replies = " ".join(entry.author_replies[:2])
        lines.append(
            "；".join(
                part
                for part in [
                    f"{entry.title} 视觉相似度 {match.score:.2f}",
                    f"品牌线索 {'、'.join(entry.brand_clues)}" if entry.brand_clues else "",
                    f"知识模式 {'、'.join(entry.knowledge_modes[:4])}" if entry.knowledge_modes else "",
                    f"客户问法 {entry.customer_question}" if entry.customer_question else "",
                    f"作者回复 {replies}" if replies else "",
                ]
                if part
            )
        )
    return "\n".join(lines)


def _apply_direct_visual_reply(response: AnalyzeResponse, visual_matches: list) -> AnalyzeResponse:
    if not response.hints or not visual_matches:
        return response
    top = visual_matches[0]
    if top.score < 0.86 or not top.entry.author_replies:
        return response
    direct_reply = build_direct_visual_reply(top.entry.author_replies, top.entry.brand_clues)
    if not direct_reply:
        return response
    hint = response.hints[0]
    hint.suggested_reply = direct_reply
    hint.interaction_analysis = (
        f"图库高相似样本直接命中：{top.entry.title}，相似度 {top.score:.0%}。"
        "已优先采用该样本绑定的真实回复并净化成客户可读话术；品牌只作为线索，不直接定论。 "
        + hint.interaction_analysis
    )
    return response


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
    engine = AssistantEngine(kb, settings.knowledge_base, settings.assistant)
    visual_index = VisualIndex.load(settings.root / "data" / "visual_index.json")
    learning_queue = LearningQueue(settings.root / "data" / "learning_queue.json")
    interaction_store = InteractionStore(settings.root / "data" / "interactions")
    conversation_store = ConversationStore(settings.root / "data" / "conversations.json")
    app = FastAPI(title=settings.app.name)
    static_dir = settings.root / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    knowledge_assets_dir = settings.root / "data" / "knowledge_assets"
    knowledge_assets_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/knowledge-assets", StaticFiles(directory=knowledge_assets_dir), name="knowledge-assets")

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
        return {"ok": True, "entries": len(kb.list_entries()), "visual_entries": len(visual_index.entries)}

    @app.post("/api/vision/match")
    async def match_vision(file: UploadFile = File(...), limit: int = Form(5)) -> dict[str, object]:
        if not _is_allowed_image_upload(file, settings.recognition.allowed_image_types):
            raise HTTPException(status_code=400, detail="Only png, jpeg, or webp images are supported")
        data = await file.read()
        max_bytes = settings.recognition.max_upload_mb * 1024 * 1024
        if len(data) > max_bytes:
            raise HTTPException(status_code=400, detail=f"Image is larger than {settings.recognition.max_upload_mb} MB")
        matches = visual_index.match_bytes(data, limit=max(1, min(limit, 20)))
        return {
            "matches": [match.to_dict() for match in matches],
            "visual_entries": len(visual_index.entries),
            "rule": "先用本地图库视觉指纹找相似截面图，再读取该图绑定的评论回复和品牌结构线索。",
        }

    @app.post("/api/structure/identify")
    def identify_structure(payload: dict) -> dict[str, object]:
        description = str(payload.get("description", "")).strip()
        if not description:
            raise HTTPException(status_code=400, detail="description is required")
        candidates = identify_brand_by_structure(kb, description, limit=int(payload.get("limit", 5) or 5))
        return {
            "candidates": [
                {
                    "brand": item.brand,
                    "series": item.series,
                    "features": item.features,
                    "score": item.score,
                    "evidence": item.evidence,
                    "entry_id": item.entry_id,
                }
                for item in candidates
            ],
            "rule": "先识别截面可见特征，再用品牌结构指纹匹配；少于两个结构特征不做品牌判断。",
        }

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

    @app.post("/api/kb/feed")
    async def feed_knowledge(
        title: str = Form(...),
        content: str = Form(...),
        tags: str = Form(""),
        reply_template: str = Form(""),
        source_note: str = Form("manual"),
        file: Optional[UploadFile] = File(None),
    ) -> dict[str, object]:
        if not title.strip() or not content.strip():
            raise HTTPException(status_code=400, detail="title and content are required")

        asset_path = ""
        attachments: list[KnowledgeAttachment] = []
        if file and file.filename:
            data = await file.read()
            max_bytes = settings.recognition.max_upload_mb * 1024 * 1024
            if len(data) > max_bytes:
                raise HTTPException(status_code=400, detail=f"File is larger than {settings.recognition.max_upload_mb} MB")
            upload_dir = settings.root / "data" / "knowledge_assets"
            upload_dir.mkdir(parents=True, exist_ok=True)
            safe_name = _safe_upload_name(file.filename)
            saved = upload_dir / safe_name
            saved.write_bytes(data)
            asset_path = f"/knowledge-assets/{safe_name}"
            attachments.append(
                KnowledgeAttachment(
                    label=file.filename,
                    path=str(saved.relative_to(settings.root)),
                    type=file.content_type or "file",
                    note="通过投喂入口上传的知识素材",
                )
            )

        entry = KnowledgeEntry(
            id=f"feed-{uuid4().hex[:12]}",
            title=title.strip(),
            content=f"{content.strip()}\n\n来源备注：{source_note.strip() or 'manual'}",
            tags=[item.strip() for item in tags.replace("，", ",").split(",") if item.strip()],
            image_path=asset_path or "/static/assets/window-system.svg",
            reply_templates=[line.strip() for line in reply_template.splitlines() if line.strip()],
            attachments=attachments,
        )
        saved, created = kb.upsert_entry(entry)
        return {"entry": saved.model_dump(), "created": created, "knowledge_status": kb.status().model_dump()}

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
        if not _is_allowed_image_upload(file, settings.recognition.allowed_image_types):
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

    @app.post("/api/vision/analyze")
    async def analyze_image(
        file: UploadFile = File(...),
        question: str = Form(""),
        session_id: str = Form("default"),
        learn: bool = Form(False),
    ) -> dict[str, object]:
        if not _is_allowed_image_upload(file, settings.recognition.allowed_image_types):
            raise HTTPException(status_code=400, detail="Only png, jpeg, or webp images are supported")
        data = await file.read()
        max_bytes = settings.recognition.max_upload_mb * 1024 * 1024
        if len(data) > max_bytes:
            raise HTTPException(status_code=400, detail=f"Image is larger than {settings.recognition.max_upload_mb} MB")

        upload_dir = settings.root / "data" / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        safe_name = _safe_upload_name(file.filename)
        upload_path = upload_dir / safe_name
        upload_path.write_bytes(data)

        recognition = recognize_image_payload(data, settings.recognition.ocr_language)
        recognized_text = recognition.text.strip()
        visual_matches = visual_index.match_bytes(data, limit=5)
        visual_context = _visual_matches_to_context(visual_matches)
        combined_text = "\n".join(part for part in [question.strip(), recognized_text, visual_context] if part)
        if not combined_text:
            combined_text = "客户上传了一张门窗/断桥铝/系统窗图片，请按图片结构分析。"
        messages = [MessageInput(id="image-1", sender="customer", text=combined_text)]
        response = engine.analyze(
            AnalyzeRequest(
                messages=messages,
                include_safety=True,
                learn=learn,
                session_id=session_id,
                image_bytes=data,
            )
        )
        response = _apply_direct_visual_reply(response, visual_matches)
        matches = response.hints[0].matched_entries if response.hints else []
        codex_handoff = _build_codex_handoff(
            image_path=upload_path,
            question=question,
            recognized_text=recognized_text,
            matches=matches,
            visual_matches=visual_matches,
        )
        interaction_store.append(
            source="api_vision_analyze",
            input_type="image",
            raw_text=question,
            ocr_text=recognized_text,
            screenshot_path=upload_path,
            messages=messages,
            output=response,
            metadata={
                "session_id": session_id,
                "filename": file.filename or "",
                "visual_matches": ",".join(match.entry.id for match in visual_matches[:5]),
            },
        )
        return {
            "analysis": response.model_dump(),
            "recognition": recognition.model_dump(),
            "visual_matches": [match.to_dict() for match in visual_matches],
            "upload_path": str(upload_path),
            "knowledge_status": kb.status().model_dump(),
            "codex_handoff": codex_handoff,
            "local_only": True,
        }

    @app.post("/api/harvest-url", response_model=RecognitionResponse)
    async def harvest_url(payload: dict) -> RecognitionResponse:
        if harvest_comments_from_url is None:
            raise HTTPException(status_code=503, detail="Playwright is not installed; URL harvesting is unavailable")
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
        has_explicit_context = request.session_id.strip() not in {"", "default"} or session_id != "default"
        prior_context = conversation_store.recent_context(session_id, limit=8) if has_explicit_context else []
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
