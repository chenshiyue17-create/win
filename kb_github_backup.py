from __future__ import annotations

import argparse
import subprocess

from customer_context_assistant.config import load_settings
from customer_context_assistant.github_archive import ARCHIVE_DIR, archive_status, export_archive
from customer_context_assistant.knowledge_base import KnowledgeBase


def load_entries():
    settings = load_settings()
    kb = KnowledgeBase(
        settings.knowledge_base.source_file,
        seed_file=settings.knowledge_base.seed_file,
        backup_dir=settings.knowledge_base.backup_dir,
        min_entries=settings.knowledge_base.min_entries,
    )
    return kb.list_entries()


def print_status(status) -> None:
    print(f"仓库目录：{status.archive_dir}")
    print(f"知识条目：{status.entries}")
    print(f"素材数量：{status.assets}")
    print(f"当前提交：{status.commit or '无'}")
    print(f"GitHub 远程：{status.remote or '未配置'}")


def main() -> None:
    parser = argparse.ArgumentParser(description="导出门窗知识库到 Git/GitHub 备份仓库")
    parser.add_argument("action", choices=["export", "status", "push"])
    parser.add_argument("--remote", help="GitHub 仓库地址，例如 git@github.com:user/repo.git")
    args = parser.parse_args()

    if args.action == "export":
        status = export_archive(load_entries())
        print_status(status)
        return

    if args.action == "status":
        print_status(archive_status())
        return

    if args.action == "push":
        if args.remote:
            if not archive_status().remote:
                subprocess.run(["git", "remote", "add", "origin", args.remote], cwd=str(ARCHIVE_DIR), check=True)
            else:
                subprocess.run(["git", "remote", "set-url", "origin", args.remote], cwd=str(ARCHIVE_DIR), check=True)
        if not archive_status().remote:
            raise SystemExit("未配置 GitHub remote。请加 --remote 或先在 data/github_kb_repo 配置 origin。")
        subprocess.run(["git", "push", "-u", "origin", "master"], cwd=str(ARCHIVE_DIR), check=True)
        print_status(archive_status())


if __name__ == "__main__":
    main()
