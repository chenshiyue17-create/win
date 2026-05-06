from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


APP_SUPPORT_ROOT = Path.home() / "Library" / "Application Support" / "门窗工具"
BUNDLE_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
PROJECT_ROOT = APP_SUPPORT_ROOT if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class AppConfig:
    name: str
    host: str
    port: int
    log_file: Path


@dataclass(frozen=True)
class KnowledgeConfig:
    source_file: Path
    seed_file: Path
    backup_dir: Path
    min_entries: int
    max_results: int
    min_score: int


@dataclass(frozen=True)
class RecognitionConfig:
    max_upload_mb: int
    allowed_image_types: tuple[str, ...]
    ocr_language: str


@dataclass(frozen=True)
class AssistantConfig:
    confidence_floor: float
    safety_stop_words: tuple[str, ...]


@dataclass(frozen=True)
class Settings:
    root: Path
    app: AppConfig
    knowledge_base: KnowledgeConfig
    recognition: RecognitionConfig
    assistant: AssistantConfig


def _as_path(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def ensure_runtime_files(root: Path = PROJECT_ROOT, bundle_root: Path = BUNDLE_ROOT) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for directory in ("logs", "output", "data"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    for relative in ("config.yaml",):
        source = bundle_root / relative
        target = root / relative
        if source.exists() and not target.exists():
            shutil.copy2(source, target)
    for relative in ("static", "tasks"):
        source_dir = bundle_root / relative
        target_dir = root / relative
        if source_dir.exists() and not target_dir.exists():
            shutil.copytree(source_dir, target_dir)
    data_defaults = {
        "knowledge_base.json": bundle_root / "data" / "knowledge_base.json",
        "learning_queue.json": bundle_root / "data" / "learning_queue.json",
    }
    for filename, source in data_defaults.items():
        target = root / "data" / filename
        if source.exists() and not target.exists():
            shutil.copy2(source, target)


def load_settings(config_path: str | Path | None = None) -> Settings:
    ensure_runtime_files()
    raw_path = config_path or os.getenv("CUSTOMER_ASSISTANT_CONFIG") or PROJECT_ROOT / "config.yaml"
    path = Path(raw_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    app = data.get("app", {})
    kb = data.get("knowledge_base", {})
    rec = data.get("recognition", {})
    assistant = data.get("assistant", {})

    return Settings(
        root=PROJECT_ROOT,
        app=AppConfig(
            name=str(app.get("name", "Customer Assistant")),
            host=os.getenv("CUSTOMER_ASSISTANT_HOST", str(app.get("host", "127.0.0.1"))),
            port=int(os.getenv("CUSTOMER_ASSISTANT_PORT", app.get("port", 8787))),
            log_file=_as_path(PROJECT_ROOT, str(app.get("log_file", "logs/app.log"))),
        ),
        knowledge_base=KnowledgeConfig(
            source_file=_as_path(PROJECT_ROOT, str(kb.get("source_file", "data/knowledge_base.json"))),
            seed_file=_as_path(PROJECT_ROOT, str(kb.get("seed_file", "tasks/knowledge_base.seed.json"))),
            backup_dir=_as_path(PROJECT_ROOT, str(kb.get("backup_dir", "data/kb_backups"))),
            min_entries=int(kb.get("min_entries", 1)),
            max_results=int(kb.get("max_results", 4)),
            min_score=int(kb.get("min_score", 1)),
        ),
        recognition=RecognitionConfig(
            max_upload_mb=int(rec.get("max_upload_mb", 8)),
            allowed_image_types=tuple(rec.get("allowed_image_types", ["image/png", "image/jpeg"])),
            ocr_language=str(rec.get("ocr_language", "chi_sim+eng")),
        ),
        assistant=AssistantConfig(
            confidence_floor=float(assistant.get("confidence_floor", 0.18)),
            safety_stop_words=tuple(assistant.get("safety_stop_words", [])),
        ),
    )
