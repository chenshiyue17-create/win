import json

from customer_context_assistant.github_archive import export_archive
from customer_context_assistant.models import KnowledgeAttachment, KnowledgeEntry, KnowledgeLink, KnowledgeTable


def test_export_archive_writes_git_ready_repo(tmp_path) -> None:
    entry = KnowledgeEntry(
        id="glass-test",
        title="玻璃测试知识",
        content="临街噪音可考虑夹胶中空玻璃。",
        tags=["玻璃", "隔音"],
        image_path="/static/assets/glass.svg",
        reply_templates=["先确认噪音源、楼层和窗洞尺寸。"],
        links=[KnowledgeLink(label="标准入口", url="https://openstd.samr.gov.cn/", note="人工核对")],
        attachments=[KnowledgeAttachment(label="玻璃图", path="/static/assets/glass.svg", type="image")],
        tables=[
            KnowledgeTable(
                title="配置表",
                headers=["场景", "配置"],
                rows=[["临街", "夹胶中空"]],
            )
        ],
    )

    status = export_archive([entry], tmp_path / "repo")

    assert status.entries == 1
    assert status.assets >= 1
    assert status.commit
    assert (tmp_path / "repo" / ".git").exists()
    assert (tmp_path / "repo" / "entries" / "glass-test.md").exists()
    assert (tmp_path / "repo" / "tables" / "glass-test-1.csv").exists()
    version = json.loads((tmp_path / "repo" / "version.json").read_text(encoding="utf-8"))
    assert version["entry_count"] == 1
