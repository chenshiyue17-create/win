from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from customer_context_assistant.knowledge_base import KnowledgeBase, tokenize
from customer_context_assistant.models import KnowledgeEntry, KnowledgeMatch, KnowledgeVersion, LearningCandidate, MessageInput

LOGGER = logging.getLogger(__name__)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def slugify_text(text: str) -> str:
    ascii_part = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if ascii_part:
        return ascii_part[:48]
    return "learned-" + str(abs(hash(text)))[:10]


def extract_tags(text: str) -> list[str]:
    preferred = [
        "系统窗",
        "断桥铝",
        "铝材",
        "型材",
        "壁厚",
        "玻璃",
        "夹胶玻璃",
        "中空玻璃",
        "Low-E",
        "隔音",
        "隔热",
        "五金",
        "密封",
        "安装",
        "报价",
        "测量",
        "封阳台",
        "极简",
        "窄边框",
        "阳台门",
        "弧形",
        "异形窗",
        "电动提升窗",
        "提升窗",
        "后期维护",
        "维护",
    ]
    lowered = text.lower()
    tags = [tag for tag in preferred if tag.lower() in lowered or tag in text]
    return tags[:8] or sorted(tokenize(text))[:6]


def candidate_title(text: str, tags: list[str]) -> str:
    if tags:
        return "待训练：" + " / ".join(tags[:3])
    clean = re.sub(r"^(客户|用户)[:：]\s*", "", text).strip()
    return "待训练：" + clean[:18]


class LearningQueue:
    def __init__(self, queue_file: Path) -> None:
        self.queue_file = queue_file
        self.queue_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.queue_file.exists():
            self._persist([])

    def list(self, status: str | None = None) -> list[LearningCandidate]:
        items = self._load()
        if status:
            return [item for item in items if item.status == status]
        return items

    def ingest_messages(self, messages: list[MessageInput], kb: KnowledgeBase, source: str = "manual") -> list[LearningCandidate]:
        created: list[LearningCandidate] = []
        items = self._load()
        existing_keys = {self._dedupe_key(item.source_text) for item in items}

        for message in messages:
            if message.sender == "agent" or not message.text.strip():
                continue
            matches = kb.search(message.text, limit=3, min_score=1)
            reason = self._reason_for_learning(message.text, matches)
            if not reason:
                continue
            key = self._dedupe_key(message.text)
            if key in existing_keys:
                continue
            candidate = self._build_candidate(message.text, reason, matches, source)
            items.append(candidate)
            created.append(candidate)
            existing_keys.add(key)

        if created:
            self._persist(items)
        return created

    def approve(self, candidate_id: str, kb: KnowledgeBase, review_note: str = "") -> LearningCandidate:
        items = self._load()
        for index, item in enumerate(items):
            if item.id == candidate_id:
                item.status = "approved"
                item.review_note = review_note
                item.updated_at = now_iso()
                kb.upsert_entry(item.suggested_entry)
                items[index] = item
                self._persist(items)
                return item
        raise KeyError(candidate_id)

    def update_status(self, candidate_id: str, status: str, review_note: str = "") -> LearningCandidate:
        if status not in {"pending", "approved", "rejected"}:
            raise ValueError("status must be pending, approved, or rejected")
        items = self._load()
        for index, item in enumerate(items):
            if item.id == candidate_id:
                item.status = status
                item.review_note = review_note
                item.updated_at = now_iso()
                items[index] = item
                self._persist(items)
                return item
        raise KeyError(candidate_id)

    def _build_candidate(self, text: str, reason: str, matches: list[KnowledgeMatch], source: str) -> LearningCandidate:
        tags = extract_tags(text)
        entry_id = "learn-" + slugify_text("-".join(tags) + "-" + text)
        created_at = now_iso()

        suggested_entry = KnowledgeEntry(
            id=entry_id,
            title=candidate_title(text, tags),
            content=f"来自{source}互动的待确认知识点：{text}",
            tags=tags,
            image_path="/static/assets/window-system.svg",
            reply_templates=[f"这个问题我先确认具体场景：{text[:40]}。建议结合楼层、尺寸、预算和使用痛点再给配置。"],
            version=KnowledgeVersion(version="0.1.0", updated_at=created_at, updated_by="learning_queue", change_note=reason),
        )

        return LearningCandidate(
            id=entry_id,
            status="pending",
            source_text=text,
            reason=reason,
            suggested_entry=suggested_entry,
            related_matches=matches,
            created_at=created_at,
        )

    def _reason_for_learning(self, text: str, matches: list[KnowledgeMatch]) -> str:
        if not matches:
            return "未命中现有知识库"
        top_score = matches[0].score
        if top_score <= 1:
            return "低置信命中，需要补充训练"
        if len(matches) >= 2 and abs(matches[0].score - matches[1].score) <= 1:
            return "多个知识条目命中接近，可能存在边界冲突"
        if len(text) >= 80 and top_score < 5:
            return "长问题但知识命中不足"
        return ""

    def _load(self) -> list[LearningCandidate]:
        raw = json.loads(self.queue_file.read_text(encoding="utf-8"))
        return [LearningCandidate.model_validate(item) for item in raw.get("candidates", [])]

    def _persist(self, items: list[LearningCandidate]) -> None:
        tmp_path = self.queue_file.with_suffix(".json.tmp")
        payload = {"candidates": [item.model_dump() for item in items]}
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(self.queue_file)

    def _dedupe_key(self, text: str) -> str:
        return re.sub(r"\s+", "", text.lower())[:120]
