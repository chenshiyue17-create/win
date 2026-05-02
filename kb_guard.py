from __future__ import annotations

import argparse
import shutil

from customer_context_assistant.config import load_settings
from customer_context_assistant.knowledge_base import KnowledgeBase


def build_kb() -> KnowledgeBase:
    settings = load_settings()
    return KnowledgeBase(
        settings.knowledge_base.source_file,
        seed_file=settings.knowledge_base.seed_file,
        backup_dir=settings.knowledge_base.backup_dir,
        min_entries=settings.knowledge_base.min_entries,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="门窗知识库安全维护工具")
    parser.add_argument("action", choices=["status", "backup", "restore-seed", "restore-latest"])
    args = parser.parse_args()

    kb = build_kb()
    if args.action == "backup":
        backup = kb.create_backup(reason="manual")
        print(f"已备份：{backup}")
    elif args.action == "restore-seed":
        if not kb.seed_file or not kb.seed_file.exists():
            raise SystemExit("没有找到种子知识库")
        shutil.copy2(kb.seed_file, kb.source_file)
        kb.reload()
        print(f"已从种子恢复：{kb.seed_file}")
    elif args.action == "restore-latest":
        restored = kb._restore_from_latest_backup()
        if not restored:
            raise SystemExit("没有可用备份")
        kb.reload()
        print(f"已从最近备份恢复：{restored}")

    status = kb.status()
    print(f"知识条目：{status.entries}")
    print(f"备份数量：{status.backups}")
    print(f"最近备份：{status.latest_backup or '无'}")


if __name__ == "__main__":
    main()
