from pathlib import Path

from PIL import Image
import pytest

from floating_region_assistant import (
    Region,
    crop_region,
    crop_region_from_space,
    ensure_screen_capture_permission,
    fingerprint_distance,
    first_suggested_reply,
    format_hints,
    image_fingerprint,
    load_floating_state,
    normalize_ocr_text,
    region_from_dict,
    region_to_image_box,
    region_to_dict,
    save_floating_state,
)
import floating_region_assistant as floating_app
from customer_context_assistant.models import AnalyzeResponse, Hint


def test_region_normalization_and_validation() -> None:
    region = Region(100, 90, 10, 20).normalized()
    assert region.left == 10
    assert region.top == 20
    assert region.width == 90
    assert region.height == 70
    assert region.is_valid()


def test_crop_region_writes_image(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    target = tmp_path / "target.png"
    Image.new("RGB", (100, 80), "white").save(source)

    crop_region(source, Region(10, 10, 60, 50), target)

    with Image.open(target) as image:
        assert image.size == (50, 40)


def test_crop_region_scales_from_retina_screen_space(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    target = tmp_path / "target.png"
    Image.new("RGB", (200, 160), "white").save(source)

    crop_region_from_space(source, Region(10, 10, 60, 50), target, (100, 80))

    with Image.open(target) as image:
        assert image.size == (100, 80)


def test_region_to_image_box_clamps_and_scales() -> None:
    box = region_to_image_box(Region(-10, 5, 60, 50), (200, 160), (100, 80))

    assert box == (0, 10, 120, 100)


def test_normalize_ocr_text_removes_blank_lines_and_spaces() -> None:
    assert normalize_ocr_text("  客户：系统窗多少钱？  \n\n  门店：需要尺寸  ") == "客户：系统窗多少钱？\n门店：需要尺寸"


def test_image_fingerprint_detects_meaningful_change(tmp_path: Path) -> None:
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    Image.new("RGB", (100, 80), "white").save(first)
    image = Image.new("RGB", (100, 80), "white")
    for x in range(20, 80):
        for y in range(20, 60):
            image.putpixel((x, y), (0, 0, 0))
    image.save(second)

    assert fingerprint_distance(image_fingerprint(first), image_fingerprint(second)) > 5


def test_region_overlay_geometry_uses_normalized_region() -> None:
    region = Region(100, 90, 10, 20).normalized()
    assert f"{region.width}x{region.height}+{region.left}+{region.top}" == "90x70+10+20"


def test_floating_state_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "floating_state.json"
    region = Region(100, 90, 10, 20).normalized()

    save_floating_state(path, session_id=" 张三 客户 ", region=region)
    state = load_floating_state(path)

    assert state["session_id"] == "张三-客户"
    assert region_from_dict(state["region"]) == region
    assert region_to_dict(region) == {"left": 10, "top": 20, "right": 100, "bottom": 90}


def test_radar_dimensions_are_available_on_new_session(tmp_path: Path) -> None:
    from customer_context_assistant.conversation_store import ConversationStore

    store = ConversationStore(tmp_path / "conversations.json")
    session = store.get_or_create("客户A")

    assert set(session.radar) == {"需求清晰", "预算敏感", "成交紧迫", "信任程度", "风险顾虑", "决策成熟"}


def test_format_hints_empty_response() -> None:
    text = format_hints(AnalyzeResponse(hints=[]), ["OCR 不可用"])
    assert "OCR 不可用" in text
    assert "没有识别到" in text


def test_format_hints_separates_internal_analysis_from_reply() -> None:
    response = AnalyzeResponse(
        hints=[
            Hint(
                message_id="m1",
                intent="异议处理",
                confidence=0.8,
                summary="客户在比较价格",
                interaction_analysis="内部分析，不要复制给客户。",
                suggested_reply="您可以先按配置和安装边界比较。",
            )
        ]
    )

    text = format_hints(response)

    assert "互动分析（内部看，不复制给客户）" in text
    assert "可复制回复" in text
    assert "内部分析，不要复制给客户。" in text


def test_permission_help_text_mentions_app_stays_open() -> None:
    source = Path("floating_region_assistant.py").read_text(encoding="utf-8")

    assert "权限或截图失败，App 已保持打开" in source
    assert "打开权限设置" in source
    assert "清空失效锁" in source
    assert "工具不会再自动反复请求权限" in source
    assert "直接在当前桌面上拖动选择聊天区域" in source
    assert "已锁定监听区" in source
    assert "keep_overlay=True" in source
    assert "选区边框保留" in source
    assert "self.windows: list[object]" in source
    assert "_create_frame_windows" in source
    assert "已取消框选" in source
    assert "WM_DELETE_WINDOW" in source


def test_global_hotkey_is_opt_in_to_avoid_permission_popup() -> None:
    source = Path("floating_region_assistant.py").read_text(encoding="utf-8")

    assert "MENCHUANG_ENABLE_GLOBAL_HOTKEY" in source
    assert "全局热键默认关闭" in source
    assert "点“开始监听”后再读取屏幕" in source


def test_screen_capture_preflight_blocks_repeated_system_prompts(monkeypatch) -> None:
    monkeypatch.setattr(floating_app, "screen_capture_authorized", lambda: False)

    with pytest.raises(PermissionError, match="已阻止本次截图请求"):
        ensure_screen_capture_permission()


def test_first_suggested_reply_returns_first_reply() -> None:
    response = AnalyzeResponse(
        hints=[
            Hint(
                message_id="m1",
                intent="玻璃配置",
                confidence=0.8,
                summary="命中知识库：玻璃配置",
                suggested_reply="建议先确认楼层、噪音源和窗洞尺寸。",
            )
        ]
    )
    assert first_suggested_reply(response) == "建议先确认楼层、噪音源和窗洞尺寸。"
