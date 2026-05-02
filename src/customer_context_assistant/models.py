from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class KnowledgeAttachment(BaseModel):
    label: str
    path: str
    type: str = "file"
    note: str = ""


class KnowledgeLink(BaseModel):
    label: str
    url: str
    note: str = ""


class KnowledgeTable(BaseModel):
    title: str
    headers: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)


class KnowledgeVersion(BaseModel):
    version: str = "1.0.0"
    updated_at: Optional[str] = None
    updated_by: str = "local"
    change_note: str = ""


class KnowledgeEntry(BaseModel):
    id: str
    title: str
    content: str
    tags: list[str] = Field(default_factory=list)
    image_path: Optional[str] = None
    reply_templates: list[str] = Field(default_factory=list)
    links: list[KnowledgeLink] = Field(default_factory=list)
    attachments: list[KnowledgeAttachment] = Field(default_factory=list)
    tables: list[KnowledgeTable] = Field(default_factory=list)
    version: KnowledgeVersion = Field(default_factory=KnowledgeVersion)


class KnowledgeMatch(BaseModel):
    entry: KnowledgeEntry
    score: int
    reasons: list[str] = Field(default_factory=list)


class KnowledgeBatch(BaseModel):
    entries: list[KnowledgeEntry] = Field(default_factory=list)
    mode: str = "upsert"


class KnowledgeSearchRequest(BaseModel):
    query: str
    limit: int = 6


class KnowledgeImportResponse(BaseModel):
    total: int
    created: int
    updated: int
    entries: list[KnowledgeEntry] = Field(default_factory=list)


class KnowledgeStatus(BaseModel):
    source_file: str
    seed_file: Optional[str] = None
    backup_dir: Optional[str] = None
    entries: int
    backups: int
    latest_backup: Optional[str] = None


class GithubArchiveStatus(BaseModel):
    archive_dir: str
    entries: int
    assets: int
    commit: Optional[str] = None
    remote: Optional[str] = None


class MessageInput(BaseModel):
    id: Optional[str] = None
    sender: str = "customer"
    text: str


class AnalyzeRequest(BaseModel):
    messages: list[MessageInput]
    include_safety: bool = True
    learn: bool = False
    session_id: str = "default"


class Hint(BaseModel):
    message_id: str
    intent: str
    confidence: float
    summary: str
    interaction_analysis: str = ""
    suggested_reply: str
    matched_entries: list[KnowledgeMatch] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class AnalyzeResponse(BaseModel):
    hints: list[Hint]


class RecognitionResponse(BaseModel):
    source: str
    text: str
    messages: list[MessageInput]
    warnings: list[str] = Field(default_factory=list)


class LearningCandidate(BaseModel):
    id: str
    status: str = "pending"
    source_text: str
    reason: str
    suggested_entry: KnowledgeEntry
    related_matches: list[KnowledgeMatch] = Field(default_factory=list)
    created_at: str
    updated_at: Optional[str] = None
    review_note: str = ""


class LearningIngestRequest(BaseModel):
    messages: list[MessageInput]
    source: str = "manual"


class LearningQueueResponse(BaseModel):
    candidates: list[LearningCandidate] = Field(default_factory=list)


class LearningReviewRequest(BaseModel):
    status: str
    review_note: str = ""


class InteractionRecord(BaseModel):
    id: str
    source: str
    input_type: str
    raw_text: str = ""
    ocr_text: str = ""
    screenshot_path: Optional[str] = None
    messages: list[MessageInput] = Field(default_factory=list)
    output: AnalyzeResponse
    learning_candidate_ids: list[str] = Field(default_factory=list)
    created_at: str
    metadata: dict[str, str] = Field(default_factory=dict)


class InteractionLogResponse(BaseModel):
    records: list[InteractionRecord] = Field(default_factory=list)
    total: int = 0


class ConversationSession(BaseModel):
    id: str
    title: str
    messages: list[MessageInput] = Field(default_factory=list)
    radar: dict[str, int] = Field(default_factory=dict)
    created_at: str
    updated_at: str
