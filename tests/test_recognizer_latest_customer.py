from customer_context_assistant.models import MessageInput
from customer_context_assistant.recognizer import latest_customer_messages, recognize_text_payload


def test_latest_customer_messages_prefers_last_customer_line() -> None:
    recognized = recognize_text_payload(
        "\n".join(
            [
                "客户：之前问过隔音玻璃",
                "客服：可以先看楼层和预算",
                "客户：那封阳台系统窗多少钱一平方？",
            ]
        )
    )

    latest = latest_customer_messages(recognized.messages)

    assert len(latest) == 1
    assert latest[0].sender == "customer"
    assert latest[0].text == "那封阳台系统窗多少钱一平方？"


def test_latest_customer_messages_ignores_agent_tail() -> None:
    messages = [
        MessageInput(id="m1", sender="customer", text="临街玻璃怎么选？"),
        MessageInput(id="m2", sender="agent", text="建议先确认噪音源。"),
    ]

    latest = latest_customer_messages(messages)

    assert len(latest) == 1
    assert latest[0].id == "m1"
    assert latest[0].text == "临街玻璃怎么选？"


def test_latest_customer_messages_returns_empty_without_customer_message() -> None:
    latest = latest_customer_messages([MessageInput(id="m1", sender="agent", text="好的")])

    assert latest == []
