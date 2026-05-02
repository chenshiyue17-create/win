import json

from customer_context_assistant.knowledge_base import KnowledgeBase
from customer_context_assistant.learning_engine import LearningQueue
from customer_context_assistant.models import KnowledgeEntry, MessageInput


def make_kb(path):
    path.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "id": "glass-base",
                        "title": "玻璃基础",
                        "content": "玻璃会影响隔音隔热。",
                        "tags": ["玻璃", "隔音"],
                        "reply_templates": ["先确认玻璃需求。"],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return KnowledgeBase(path, backup_dir=path.parent / "backups", min_entries=1)


def test_learning_queue_ingests_unknown_question(tmp_path) -> None:
    kb = make_kb(tmp_path / "kb.json")
    queue = LearningQueue(tmp_path / "learning_queue.json")

    created = queue.ingest_messages(
        [MessageInput(id="m1", sender="customer", text="客户问窄边框极简门和系统窗怎么搭配？")],
        kb,
        source="test",
    )

    assert len(created) == 1
    assert created[0].status == "pending"
    assert "未命中" in created[0].reason or "低置信" in created[0].reason
    assert created[0].suggested_entry.tags


def test_learning_queue_approve_writes_to_knowledge_base(tmp_path) -> None:
    kb = make_kb(tmp_path / "kb.json")
    queue = LearningQueue(tmp_path / "learning_queue.json")
    created = queue.ingest_messages(
        [MessageInput(id="m1", sender="customer", text="极简窄边框阳台门怎么选材料？")],
        kb,
        source="test",
    )

    approved = queue.approve(created[0].id, kb, review_note="ok")

    assert approved.status == "approved"
    assert kb.search("极简窄边框阳台门")


def test_learning_queue_reject_does_not_write_to_knowledge_base(tmp_path) -> None:
    kb = make_kb(tmp_path / "kb.json")
    queue = LearningQueue(tmp_path / "learning_queue.json")
    created = queue.ingest_messages(
        [MessageInput(id="m1", sender="customer", text="一个和门窗无关的问题")],
        kb,
        source="test",
    )

    rejected = queue.update_status(created[0].id, "rejected", review_note="bad")

    assert rejected.status == "rejected"
    assert not kb.search("一个和门窗无关的问题")
