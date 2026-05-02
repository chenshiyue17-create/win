from customer_context_assistant.recognizer import split_window_text


def test_window_text_split_detects_senders() -> None:
    messages = split_window_text("客户：想做系统窗\n客服：我先了解尺寸\n客户：玻璃怎么选")
    assert len(messages) == 3
    assert messages[0].sender == "customer"
    assert messages[1].sender == "agent"
    assert messages[2].text == "玻璃怎么选"
