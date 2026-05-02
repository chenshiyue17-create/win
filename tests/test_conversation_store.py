from pathlib import Path

from customer_context_assistant.conversation_store import ConversationStore, infer_session_id_from_text, normalize_session_id, score_customer_radar
from customer_context_assistant.models import MessageInput


def test_normalize_session_id_keeps_chinese_customer_name() -> None:
    assert normalize_session_id(" 张三 客户 #1 ") == "张三-客户-1"


def test_infer_session_id_from_explicit_nickname() -> None:
    text = "昵称：李总临街隔音\n客户：三玻两腔多少钱？"

    assert infer_session_id_from_text(text, "default") == "李总临街隔音"


def test_infer_session_id_from_chat_header_line() -> None:
    text = "王姐封阳台\n客户：想做系统窗"

    assert infer_session_id_from_text(text, "default") == "王姐封阳台"


def test_infer_session_id_falls_back_for_question_only_text() -> None:
    text = "系统窗多少钱一平方？"

    assert infer_session_id_from_text(text, "客户-1") == "客户-1"


def test_conversation_store_keeps_sessions_isolated(tmp_path: Path) -> None:
    store = ConversationStore(tmp_path / "conversations.json", max_messages_per_session=3)
    store.append_messages("客户A", [MessageInput(id="a1", sender="customer", text="临街隔音")])
    store.append_messages("客户B", [MessageInput(id="b1", sender="customer", text="封阳台报价")])
    store.append_messages("客户A", [MessageInput(id="a2", sender="customer", text="三玻两腔")])

    assert [message.text for message in store.recent_context("客户A")] == ["临街隔音", "三玻两腔"]
    assert [message.text for message in store.recent_context("客户B")] == ["封阳台报价"]


def test_conversation_store_trims_old_messages(tmp_path: Path) -> None:
    store = ConversationStore(tmp_path / "conversations.json", max_messages_per_session=2)
    store.append_messages(
        "客户A",
        [
            MessageInput(id="1", sender="customer", text="第一条"),
            MessageInput(id="2", sender="customer", text="第二条"),
            MessageInput(id="3", sender="customer", text="第三条"),
        ],
    )

    assert [message.text for message in store.recent_context("客户A", limit=5)] == ["第二条", "第三条"]


def test_customer_radar_scores_multiple_dimensions() -> None:
    radar = score_customer_radar(
        [
            MessageInput(id="1", sender="customer", text="我家临街，担心隔音不好，也怕漏水"),
            MessageInput(id="2", sender="customer", text="系统窗多少钱一平方？近期装修，想约测量"),
        ]
    )

    assert radar["需求清晰"] > 40
    assert radar["预算敏感"] > 40
    assert radar["成交紧迫"] > 40
    assert radar["风险顾虑"] > 40


def test_conversation_store_updates_radar_per_session(tmp_path: Path) -> None:
    store = ConversationStore(tmp_path / "conversations.json")
    store.append_messages("客户A", [MessageInput(id="a1", sender="customer", text="临街隔音，预算一万左右")])
    store.append_messages("客户B", [MessageInput(id="b1", sender="customer", text="先看看案例和质保")])

    assert store.get_or_create("客户A").radar["预算敏感"] > store.get_or_create("客户B").radar["预算敏感"]
    assert store.get_or_create("客户B").radar["信任程度"] > 20
