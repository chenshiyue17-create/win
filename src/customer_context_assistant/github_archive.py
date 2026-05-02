from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from customer_context_assistant.config import PROJECT_ROOT
from customer_context_assistant.models import GithubArchiveStatus, KnowledgeEntry


ARCHIVE_DIR = PROJECT_ROOT / "data" / "github_kb_repo"


def export_archive(entries: list[KnowledgeEntry], archive_dir: Path = ARCHIVE_DIR) -> GithubArchiveStatus:
    archive_dir.mkdir(parents=True, exist_ok=True)
    entries_dir = archive_dir / "entries"
    assets_dir = archive_dir / "assets"
    tables_dir = archive_dir / "tables"
    for directory in (entries_dir, assets_dir, tables_dir):
        directory.mkdir(parents=True, exist_ok=True)

    payload = {"entries": [entry.model_dump() for entry in entries]}
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    (archive_dir / "knowledge_base.json").write_text(serialized, encoding="utf-8")
    learning_queue = PROJECT_ROOT / "data" / "learning_queue.json"
    if learning_queue.exists():
        shutil.copy2(learning_queue, archive_dir / "learning_queue.json")
    conversations = PROJECT_ROOT / "data" / "conversations.json"
    if conversations.exists():
        shutil.copy2(conversations, archive_dir / "conversations.json")
    floating_state = PROJECT_ROOT / "data" / "floating_state.json"
    if floating_state.exists():
        shutil.copy2(floating_state, archive_dir / "floating_state.json")
    interactions_log = PROJECT_ROOT / "data" / "interactions" / "interactions.jsonl"
    if interactions_log.exists():
        shutil.copy2(interactions_log, archive_dir / "interactions.jsonl")
    distill_file = PROJECT_ROOT / "data" / "distill" / "interactions_distill.jsonl"
    if distill_file.exists():
        shutil.copy2(distill_file, archive_dir / "interactions_distill.jsonl")

    asset_count = 0
    for entry in entries:
        copied_image = _copy_local_asset(entry.image_path, assets_dir)
        if copied_image:
            asset_count += 1
        for attachment in entry.attachments:
            copied = _copy_local_asset(attachment.path, assets_dir)
            if copied:
                asset_count += 1
        _write_entry_markdown(entry, entries_dir / f"{entry.id}.md", copied_image)
        _write_tables(entry, tables_dir)

    version = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "entry_count": len(entries),
        "content_sha256": hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
        "includes": ["json", "markdown", "images", "attachments", "links", "tables", "version_info", "learning_queue", "conversation_sessions", "floating_state", "interaction_logs", "distill_jsonl"],
    }
    (archive_dir / "version.json").write_text(json.dumps(version, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_readme(archive_dir, len(entries))
    _ensure_git_repo(archive_dir)
    commit = _commit_changes(archive_dir)
    return GithubArchiveStatus(
        archive_dir=str(archive_dir),
        entries=len(entries),
        assets=asset_count,
        commit=commit,
        remote=_git_remote(archive_dir),
    )


def archive_status(archive_dir: Path = ARCHIVE_DIR) -> GithubArchiveStatus:
    kb_path = archive_dir / "knowledge_base.json"
    entries = 0
    if kb_path.exists():
        raw = json.loads(kb_path.read_text(encoding="utf-8"))
        entries = len(raw.get("entries", []))
    assets = len(list((archive_dir / "assets").glob("*"))) if (archive_dir / "assets").exists() else 0
    return GithubArchiveStatus(
        archive_dir=str(archive_dir),
        entries=entries,
        assets=assets,
        commit=_git_head(archive_dir),
        remote=_git_remote(archive_dir),
    )


def _copy_local_asset(path_value: str | None, assets_dir: Path) -> Path | None:
    if not path_value:
        return None
    if path_value.startswith("http://") or path_value.startswith("https://"):
        return None
    if path_value.startswith("/static/"):
        source = PROJECT_ROOT / path_value.lstrip("/")
    else:
        source = Path(path_value)
        if not source.is_absolute():
            source = PROJECT_ROOT / path_value.lstrip("/")
    if not source.exists() or not source.is_file():
        return None
    target = assets_dir / source.name
    shutil.copy2(source, target)
    return target


def _write_entry_markdown(entry: KnowledgeEntry, path: Path, copied_image: Path | None) -> None:
    lines = [
        f"# {entry.title}",
        "",
        f"- ID: `{entry.id}`",
        f"- Tags: {', '.join(entry.tags) if entry.tags else 'none'}",
        f"- Version: {entry.version.version}",
        f"- Updated: {entry.version.updated_at or 'not set'}",
        f"- Change note: {entry.version.change_note or 'not set'}",
        "",
    ]
    if copied_image:
        lines.extend([f"![{entry.title}](../assets/{copied_image.name})", ""])
    lines.extend(["## Knowledge", "", entry.content, "", "## Reply Templates", ""])
    lines.extend([f"- {item}" for item in entry.reply_templates] or ["- none"])
    lines.extend(["", "## Links", ""])
    lines.extend([f"- [{link.label}]({link.url}) - {link.note}" for link in entry.links] or ["- none"])
    lines.extend(["", "## Attachments", ""])
    lines.extend([f"- {item.label}: `{item.path}` ({item.type}) {item.note}" for item in entry.attachments] or ["- none"])
    if entry.tables:
        lines.extend(["", "## Tables", ""])
        lines.extend([f"- [{table.title}](../tables/{entry.id}-{index + 1}.csv)" for index, table in enumerate(entry.tables)])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_tables(entry: KnowledgeEntry, tables_dir: Path) -> None:
    for index, table in enumerate(entry.tables):
        table_path = tables_dir / f"{entry.id}-{index + 1}.csv"
        with table_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            if table.headers:
                writer.writerow(table.headers)
            writer.writerows(table.rows)


def _write_readme(archive_dir: Path, entry_count: int) -> None:
    readme = f"""# Door Window Knowledge Base

This repository is a versioned backup of the local door-and-window presales knowledge base.

- Entries: {entry_count}
- Main data: `knowledge_base.json`
- Human-readable entries: `entries/`
- Images and screenshots: `assets/`
- Tables: `tables/`
- Pending learning queue: `learning_queue.json`
- Conversation sessions: `conversations.json`
- Floating app state: `floating_state.json`
- Interaction logs: `interactions.jsonl`
- Distillation dataset: `interactions_distill.jsonl`
- Version manifest: `version.json`

Update flow:

1. Edit or import data in the local trainer.
2. Run `PYTHONPATH=src python3 kb_github_backup.py export`.
3. Review `git status` in this folder.
4. Push to GitHub after confirming the remote repository.
"""
    (archive_dir / "README.md").write_text(readme, encoding="utf-8")


def _ensure_git_repo(archive_dir: Path) -> None:
    if not (archive_dir / ".git").exists():
        subprocess.run(["git", "init"], cwd=str(archive_dir), check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    subprocess.run(["git", "config", "user.name", "Customer KB Bot"], cwd=str(archive_dir), check=True)
    subprocess.run(["git", "config", "user.email", "kb-backup@example.local"], cwd=str(archive_dir), check=True)


def _commit_changes(archive_dir: Path) -> str | None:
    subprocess.run(["git", "add", "."], cwd=str(archive_dir), check=True)
    status = subprocess.run(["git", "status", "--porcelain"], cwd=str(archive_dir), check=True, stdout=subprocess.PIPE, text=True)
    if not status.stdout.strip():
        return _git_head(archive_dir)
    message = f"Update knowledge base {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    subprocess.run(["git", "commit", "-m", message], cwd=str(archive_dir), check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return _git_head(archive_dir)


def _git_head(archive_dir: Path) -> str | None:
    if not (archive_dir / ".git").exists():
        return None
    result = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=str(archive_dir), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    return result.stdout.strip() or None


def _git_remote(archive_dir: Path) -> str | None:
    if not (archive_dir / ".git").exists():
        return None
    result = subprocess.run(["git", "remote", "get-url", "origin"], cwd=str(archive_dir), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    return result.stdout.strip() or None
