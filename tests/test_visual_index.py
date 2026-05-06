from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw

from customer_context_assistant.visual_index import (
    VisualIndex,
    build_visual_entries,
    fingerprint_distance,
    fingerprint_image_path,
    save_visual_index,
)


def _section_image(path: Path, offset: int = 0) -> None:
    image = Image.new("RGB", (120, 90), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((10 + offset, 10, 55 + offset, 78), outline="black", width=4)
    draw.rectangle((62, 12 + offset, 108, 76 + offset), outline="black", width=4)
    draw.line((18, 45, 100, 45), fill="black", width=3)
    image.save(path)


def test_visual_index_matches_existing_knowledge_image(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    image_dir = source_root / "note" / "images"
    image_dir.mkdir(parents=True)
    target = image_dir / "brand-section.webp"
    other = image_dir / "other-section.webp"
    _section_image(target)
    Image.new("RGB", (120, 90), "black").save(other)

    sample_library = tmp_path / "visual_sample_library.md"
    sample_library.write_text(
        "\n".join(
            [
                "## 样本 1",
                "",
                "- 图片: `images/brand-section.webp`",
                "- 来源笔记: 测试笔记",
                "- 来源文件: index.md",
                "- 主题: 帮忙看一下",
                "- 品牌线索: 新豪轩",
                "- 知识模式: 主框两个腔体",
                "- 客户问题: 帮忙看一下这款怎么样？",
                "",
                "### 作者回复",
                "- 这个是新豪轩的产品，重点看主框腔体和承重。",
                "",
                "## 样本 2",
                "",
                "- 图片: `images/other-section.webp`",
                "- 来源笔记: 测试笔记",
                "- 来源文件: index.md",
                "- 主题: 其他",
                "- 品牌线索: 富轩",
                "- 知识模式: 其他结构",
                "- 客户问题: 另一款",
                "",
                "### 作者回复",
                "- 这是另一类结构。",
            ]
        ),
        encoding="utf-8",
    )

    entries = build_visual_entries(sample_library, source_root, include_all_images=False)
    output = tmp_path / "visual_index.json"
    save_visual_index(entries, output)

    index = VisualIndex.load(output)
    buffer = BytesIO()
    Image.open(target).save(buffer, format="PNG")
    matches = index.match_bytes(buffer.getvalue(), limit=2)

    assert matches
    assert matches[0].entry.image == "原始知识库/note/images/brand-section.webp"
    assert matches[0].entry.brand_clues == ["新豪轩"]
    assert matches[0].score > 0.95


def test_visual_index_can_scan_all_raw_knowledge_images(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    note = source_root / "品牌笔记_abc"
    image_dir = note / "images"
    image_dir.mkdir(parents=True)
    target = image_dir / "raw-section.webp"
    _section_image(target)
    (note / "index.md").write_text(
        "\n".join(
            [
                "# 品牌笔记",
                "**客户A**: 帮我看看新豪轩这款怎么样",
                "  ![img](images/raw-section.webp)",
                "  └─ **满天窗(帮看门窗结构)**: 满天窗(帮看门窗结构) 作者 这个主框两个腔体，不能满注胶，超大玻璃承重比较差。",
            ]
        ),
        encoding="utf-8",
    )
    sample_library = tmp_path / "visual_sample_library.md"
    sample_library.write_text("# empty\n", encoding="utf-8")

    entries = build_visual_entries(sample_library, source_root, include_all_images=True)

    assert len(entries) == 1
    assert entries[0].source_image == "原始知识库/品牌笔记_abc/images/raw-section.webp"
    assert "新豪轩" in entries[0].brand_clues
    assert "主框两个腔体" in entries[0].knowledge_modes
    assert entries[0].author_replies


def test_visual_fingerprint_tolerates_small_photo_shift(tmp_path: Path) -> None:
    base = tmp_path / "base.png"
    shifted = tmp_path / "shifted.png"
    _section_image(base)
    _section_image(shifted, offset=2)

    base_fingerprint = fingerprint_image_path(base)
    shifted_fingerprint = fingerprint_image_path(shifted)

    assert len(base_fingerprint.average_hash) == 64
    assert len(shifted_fingerprint.difference_hash) == 64
    assert fingerprint_distance(base_fingerprint, shifted_fingerprint) < 0.25
