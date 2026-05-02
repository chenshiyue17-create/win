from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from customer_context_assistant.models import AnalyzeResponse, InteractionRecord, MessageInput


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_id(prefix: str = "interaction") -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')}"


class InteractionStore:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir
        self.assets_dir = root_dir / "assets"
        self.log_file = root_dir / "interactions.jsonl"
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.assets_dir.mkdir(parents=True, exist_ok=True)
        self.log_file.touch(exist_ok=True)

    def save_asset(self, source_path: Path, interaction_id: str) -> Path | None:
        if not source_path.exists():
            return None
        suffix = source_path.suffix or ".png"
        target = self.assets_dir / f"{interaction_id}{suffix}"
        shutil.copy2(source_path, target)
        return target

    def append(
        self,
        *,
        source: str,
        input_type: str,
        output: AnalyzeResponse,
        messages: list[MessageInput] | None = None,
        raw_text: str = "",
        ocr_text: str = "",
        screenshot_path: Path | None = None,
        learning_candidate_ids: list[str] | None = None,
        metadata: dict[str, str] | None = None,
    ) -> InteractionRecord:
        item_id = record_id()
        saved_asset = self.save_asset(screenshot_path, item_id) if screenshot_path else None
        record = InteractionRecord(
            id=item_id,
            source=source,
            input_type=input_type,
            raw_text=raw_text,
            ocr_text=ocr_text,
            screenshot_path=str(saved_asset) if saved_asset else None,
            messages=messages or [],
            output=output,
            learning_candidate_ids=learning_candidate_ids or [],
            created_at=now_iso(),
            metadata=metadata or {},
        )
        with self.log_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.model_dump(), ensure_ascii=False) + "\n")
        return record

    def list(self, limit: int = 50) -> list[InteractionRecord]:
        if not self.log_file.exists():
            return []
        lines = [line for line in self.log_file.read_text(encoding="utf-8").splitlines() if line.strip()]
        selected = lines[-max(1, limit):]
        return [InteractionRecord.model_validate(json.loads(line)) for line in reversed(selected)]

    def count(self) -> int:
        if not self.log_file.exists():
            return 0
        return sum(1 for line in self.log_file.read_text(encoding="utf-8").splitlines() if line.strip())

    def export_distill_jsonl(self, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        records = list(reversed(self.list(limit=100000)))
        with output_path.open("w", encoding="utf-8") as handle:
            for record in records:
                prompt = record.ocr_text or record.raw_text
                interaction_analysis = "\n".join(hint.interaction_analysis for hint in record.output.hints if hint.interaction_analysis)
                copyable_reply = "\n".join(hint.suggested_reply for hint in record.output.hints if hint.suggested_reply)
                payload = {
                    "id": record.id,
                    "source": record.source,
                    "input": prompt,
                    "interaction_analysis": interaction_analysis,
                    "copyable_reply": copyable_reply,
                    "output": copyable_reply,
                    "messages": [message.model_dump() for message in record.messages],
                    "learning_candidate_ids": record.learning_candidate_ids,
                    "created_at": record.created_at,
                }
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return output_path
