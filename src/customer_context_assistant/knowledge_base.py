from __future__ import annotations

import json
import logging
import re
import shutil
from datetime import datetime
from pathlib import Path

from customer_context_assistant.models import KnowledgeEntry, KnowledgeMatch, KnowledgeStatus


LOGGER = logging.getLogger(__name__)
TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)

DOMAIN_PHRASES = (
    "断桥铝",
    "系统窗",
    "铝材",
    "型材",
    "玻璃",
    "中空玻璃",
    "夹胶玻璃",
    "lowe",
    "隔音",
    "隔热",
    "五金",
    "密封",
    "注胶",
    "组角",
    "壁厚",
    "报价",
    "测量",
    "推拉窗",
    "平开窗",
    "封阳台",
    "极简",
    "窄边框",
    "阳台门",
    "材料",
    "门窗",
    "提升门",
    "推拉门",
    "平开门",
    "弧形",
    "异形窗",
    "电动提升窗",
    "提升窗",
    "后期维护",
    "维护",
    "截面",
    "样角",
    "主框",
    "副框",
    "玻扇",
    "压线",
    "活动压线",
    "闭口压线",
    "不可拆卸",
    "隔热条",
    "胶条",
    "等压胶条",
    "搭接",
    "冷腔",
    "暖腔",
    "外小冷腔",
    "内大暖腔",
    "内置铰链",
    "栅栏式隔热条",
    "承重",
    "水密",
    "气密",
    "保温",
    "开扇",
    "安装费",
    "运费",
    "吊装",
    "4sg",
    "超白",
    "三玻两腔",
    "自爆",
    "包含安装",
    "包含安装费",
    "质保",
    "五金质保",
    "一年",
    "799",
    "898",
    "1280",
    "100系列",
    "105系列",
    "116系列",
    "8字纹",
    "蝴蝶纹",
    "讴铂",
    "欧泊",
    "新豪轩",
    "富轩",
    "富贵花",
    "皇派",
    "派雅",
    "轩尼斯",
    "兴发",
    "京港亚",
    "极景",
    "正典",
    "19分贝",
    "铂斯派",
    "卫洛柯",
    "伟昌",
    "坚美",
    "伟业",
    "好博",
    "江阴海达",
    "瑞纳斯",
)

BRAND_PHRASES = (
    "讴铂",
    "欧泊",
    "新豪轩",
    "富轩",
    "富贵花",
    "皇派",
    "派雅",
    "轩尼斯",
    "兴发",
    "京港亚",
    "极景",
    "正典",
    "19分贝",
    "铂斯派",
    "卫洛柯",
    "伟昌",
    "坚美",
    "伟业",
)

HIGH_SIGNAL_PHRASES = (
    "799",
    "898",
    "1280",
    "五金质保",
    "包含安装费",
    "包含安装",
    "开扇",
    "一年",
    "100系列",
    "105系列",
    "116系列",
)


def tokenize(text: str) -> set[str]:
    lowered = text.lower()
    tokens = set(TOKEN_RE.findall(lowered))
    for word in DOMAIN_PHRASES:
        if word in lowered:
            tokens.add(word)
    return tokens


class KnowledgeBase:
    def __init__(
        self,
        source_file: Path,
        seed_file: Path | None = None,
        backup_dir: Path | None = None,
        min_entries: int = 0,
    ) -> None:
        self.source_file = source_file
        self.seed_file = seed_file
        self.backup_dir = backup_dir
        self.min_entries = min_entries
        self.entries: list[KnowledgeEntry] = []
        self.reload()

    def reload(self) -> None:
        self._ensure_source_file()
        raw = self._read_raw_with_recovery()
        entries = raw.get("entries", raw if isinstance(raw, list) else [])
        if len(entries) < self.min_entries:
            raise ValueError(f"Knowledge base has {len(entries)} entries, below required minimum {self.min_entries}")
        self.entries = [KnowledgeEntry.model_validate(item) for item in entries]
        LOGGER.info("Loaded %s knowledge entries", len(self.entries))

    def list_entries(self) -> list[KnowledgeEntry]:
        return self.entries

    def add_entry(self, entry: KnowledgeEntry) -> KnowledgeEntry:
        if any(existing.id == entry.id for existing in self.entries):
            raise ValueError(f"Knowledge entry already exists: {entry.id}")
        self.entries.append(entry)
        self._persist()
        return entry

    def upsert_entry(self, entry: KnowledgeEntry) -> tuple[KnowledgeEntry, bool]:
        for index, existing in enumerate(self.entries):
            if existing.id == entry.id:
                self.entries[index] = entry
                self._persist()
                return entry, False
        self.entries.append(entry)
        self._persist()
        return entry, True

    def import_entries(self, entries: list[KnowledgeEntry], mode: str = "upsert") -> tuple[int, int, list[KnowledgeEntry]]:
        if mode not in {"upsert", "create_only"}:
            raise ValueError("mode must be upsert or create_only")
        created = 0
        updated = 0
        imported: list[KnowledgeEntry] = []
        by_id = {entry.id: index for index, entry in enumerate(self.entries)}
        for entry in entries:
            existing_index = by_id.get(entry.id)
            if mode == "create_only" and existing_index is not None:
                continue
            if existing_index is None:
                by_id[entry.id] = len(self.entries)
                self.entries.append(entry)
                created += 1
            else:
                self.entries[existing_index] = entry
                updated += 1
            imported.append(entry)
        self._persist()
        return created, updated, imported

    def search(self, query: str, limit: int = 4, min_score: int = 1) -> list[KnowledgeMatch]:
        query_tokens = tokenize(query)
        matches: list[KnowledgeMatch] = []
        lowered_query = query.lower()

        for entry in self.entries:
            haystack = " ".join([entry.title, entry.content, " ".join(entry.tags), " ".join(entry.reply_templates)])
            entry_tokens = tokenize(haystack)
            overlap = query_tokens & entry_tokens
            reasons = sorted(overlap)[:6]
            score = len(overlap)
            for tag in entry.tags:
                if tag.lower() in lowered_query:
                    score += 3
                    reasons.append(tag)
            for phrase in tokenize(entry.title):
                if phrase in lowered_query:
                    score += 2
            lowered_haystack = haystack.lower()
            for phrase in BRAND_PHRASES:
                if phrase in lowered_query and phrase in lowered_haystack:
                    score += 8
                    reasons.append(phrase)
            for phrase in HIGH_SIGNAL_PHRASES:
                if phrase in lowered_query and phrase in lowered_haystack:
                    score += 3
                    reasons.append(phrase)
            if score > 0 and not entry.id.startswith("menchuang-") and not entry.id.startswith("feed-"):
                score += 6
            if score >= min_score:
                matches.append(KnowledgeMatch(entry=entry, score=score, reasons=sorted(set(reasons))))

        matches.sort(key=lambda item: item.score, reverse=True)
        return matches[:limit]

    def create_backup(self, reason: str = "auto") -> Path | None:
        if not self.source_file.exists() or not self.backup_dir:
            return None
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        backup_path = self.backup_dir / f"knowledge_base.{reason}.{stamp}.json"
        shutil.copy2(self.source_file, backup_path)
        return backup_path

    def status(self) -> KnowledgeStatus:
        backups = self._backup_files()
        latest = backups[-1] if backups else None
        return KnowledgeStatus(
            source_file=str(self.source_file),
            seed_file=str(self.seed_file) if self.seed_file else None,
            backup_dir=str(self.backup_dir) if self.backup_dir else None,
            entries=len(self.entries),
            backups=len(backups),
            latest_backup=str(latest) if latest else None,
        )

    def _persist(self) -> None:
        if len(self.entries) < self.min_entries:
            raise ValueError("Refusing to persist an empty or undersized knowledge base")
        self.source_file.parent.mkdir(parents=True, exist_ok=True)
        self.create_backup(reason="auto")
        payload = {"entries": [entry.model_dump() for entry in self.entries]}
        serialized = json.dumps(payload, ensure_ascii=False, indent=2)
        tmp_path = self.source_file.with_suffix(self.source_file.suffix + ".tmp")
        tmp_path.write_text(serialized, encoding="utf-8")
        json.loads(tmp_path.read_text(encoding="utf-8"))
        tmp_path.replace(self.source_file)

    def _ensure_source_file(self) -> None:
        if self.source_file.exists():
            return
        restored = self._restore_from_latest_backup()
        if restored:
            LOGGER.warning("Knowledge base restored from backup: %s", restored)
            return
        if self.seed_file and self.seed_file.exists():
            self.source_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.seed_file, self.source_file)
            LOGGER.warning("Knowledge base restored from seed file: %s", self.seed_file)
            return
        raise FileNotFoundError(f"Knowledge base not found: {self.source_file}")

    def _read_raw_with_recovery(self) -> dict:
        try:
            raw = json.loads(self.source_file.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                return {"entries": raw}
            if isinstance(raw, dict):
                return raw
            raise ValueError("knowledge file root must be an object or list")
        except Exception as exc:
            LOGGER.warning("Knowledge base is unreadable, attempting recovery: %s", exc)
            broken_path = self.source_file.with_suffix(self.source_file.suffix + ".broken")
            shutil.copy2(self.source_file, broken_path)
            restored = self._restore_from_latest_backup()
            if not restored and self.seed_file and self.seed_file.exists():
                shutil.copy2(self.seed_file, self.source_file)
            return json.loads(self.source_file.read_text(encoding="utf-8"))

    def _backup_files(self) -> list[Path]:
        if not self.backup_dir or not self.backup_dir.exists():
            return []
        return sorted(self.backup_dir.glob("knowledge_base.*.json"))

    def _restore_from_latest_backup(self) -> Path | None:
        backups = self._backup_files()
        if not backups:
            return None
        latest = backups[-1]
        self.source_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(latest, self.source_file)
        return latest
