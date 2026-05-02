import json
from pathlib import Path

from PIL import Image

from customer_context_assistant.interaction_store import InteractionStore
from customer_context_assistant.models import AnalyzeResponse, Hint, MessageInput


def make_response() -> AnalyzeResponse:
    return AnalyzeResponse(
        hints=[
            Hint(
                message_id="m1",
                intent="玻璃配置",
                confidence=0.88,
                summary="命中知识库：玻璃配置",
                suggested_reply="临街隔音建议先确认噪音源、楼层和窗洞尺寸。",
            )
        ]
    )


def test_interaction_store_records_input_output_and_asset(tmp_path: Path) -> None:
    store = InteractionStore(tmp_path / "interactions")
    screenshot = tmp_path / "shot.png"
    Image.new("RGB", (24, 24), "white").save(screenshot)

    record = store.append(
        source="test",
        input_type="screenshot",
        ocr_text="客户：临街玻璃怎么选？",
        screenshot_path=screenshot,
        messages=[MessageInput(id="m1", sender="customer", text="临街玻璃怎么选？")],
        output=make_response(),
        learning_candidate_ids=["learn-1"],
    )

    assert store.count() == 1
    assert record.screenshot_path
    assert Path(record.screenshot_path).exists()
    loaded = store.list()[0]
    assert loaded.output.hints[0].suggested_reply.startswith("临街隔音")


def test_interaction_store_exports_distill_jsonl(tmp_path: Path) -> None:
    store = InteractionStore(tmp_path / "interactions")
    store.append(
        source="test",
        input_type="clipboard",
        raw_text="客户：系统窗怎么选？",
        messages=[MessageInput(id="m1", sender="customer", text="系统窗怎么选？")],
        output=make_response(),
    )

    output = store.export_distill_jsonl(tmp_path / "distill" / "out.jsonl")
    line = output.read_text(encoding="utf-8").strip()
    payload = json.loads(line)
    assert payload["input"] == "客户：系统窗怎么选？"
    assert "临街隔音" in payload["output"]
