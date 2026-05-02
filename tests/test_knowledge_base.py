import json

from customer_context_assistant.config import load_settings
from customer_context_assistant.knowledge_base import KnowledgeBase
from customer_context_assistant.models import KnowledgeEntry


def test_knowledge_search_finds_window_glass() -> None:
    settings = load_settings()
    kb = KnowledgeBase(settings.knowledge_base.source_file)
    matches = kb.search("临街想换系统窗，玻璃怎么选，隔音好一点")
    assert matches
    assert matches[0].entry.id in {"glass-package", "system-window-selection"}


def test_knowledge_search_finds_transaction_psychology() -> None:
    settings = load_settings()
    kb = KnowledgeBase(settings.knowledge_base.source_file)
    matches = kb.search("客户说太贵了 怎么做异议处理 交易心理", limit=5, min_score=1)

    assert any(match.entry.id.startswith("psychology-") for match in matches)


def test_knowledge_import_upserts_training_data(tmp_path) -> None:
    source = tmp_path / "kb.json"
    source.write_text(json.dumps({"entries": []}, ensure_ascii=False), encoding="utf-8")
    kb = KnowledgeBase(source)
    entry = KnowledgeEntry(
        id="street-noise-glass",
        title="临街隔音玻璃",
        content="临街噪音优先考虑夹胶中空玻璃，也要结合窗框密封和安装。",
        tags=["临街", "隔音", "玻璃", "夹胶玻璃"],
        image_path="/static/assets/glass.svg",
        reply_templates=["临街隔音建议先看噪音源，再考虑夹胶中空和密封配置。"],
    )

    created, updated, imported = kb.import_entries([entry])
    assert created == 1
    assert updated == 0
    assert imported[0].id == "street-noise-glass"

    updated_entry = entry.model_copy(update={"title": "临街隔音玻璃升级"})
    created, updated, _ = kb.import_entries([updated_entry])
    assert created == 0
    assert updated == 1
    assert kb.search("临街怎么做隔音玻璃")[0].entry.title == "临街隔音玻璃升级"


def test_knowledge_base_restores_missing_source_from_seed(tmp_path) -> None:
    seed = tmp_path / "seed.json"
    source = tmp_path / "kb.json"
    seed.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "id": "seed-window",
                        "title": "种子系统窗知识",
                        "content": "系统窗种子知识用于误删恢复。",
                        "tags": ["系统窗"],
                        "reply_templates": ["先恢复基础知识库。"],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    kb = KnowledgeBase(source, seed_file=seed, backup_dir=tmp_path / "backups", min_entries=1)
    assert source.exists()
    assert kb.list_entries()[0].id == "seed-window"


def test_knowledge_base_creates_backup_before_atomic_write(tmp_path) -> None:
    source = tmp_path / "kb.json"
    backups = tmp_path / "backups"
    source.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "id": "base",
                        "title": "基础知识",
                        "content": "基础内容",
                        "tags": ["系统窗"],
                        "reply_templates": ["基础回复"],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    kb = KnowledgeBase(source, backup_dir=backups, min_entries=1)
    kb.upsert_entry(
        KnowledgeEntry(
            id="glass",
            title="玻璃知识",
            content="玻璃内容",
            tags=["玻璃"],
            reply_templates=["玻璃回复"],
        )
    )

    assert list(backups.glob("knowledge_base.auto.*.json"))
    assert json.loads(source.read_text(encoding="utf-8"))["entries"][1]["id"] == "glass"
