from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class Segment:
    bbox: tuple[int, int, int, int]
    confidence: float


def find_comment_segments(image_path: str | Path, config: dict[str, Any] | None = None) -> list[Segment]:
    # 默认配置，针对小红书评论区视觉比例优化
    cfg = {
        "side_margin_ratio": 0.08,
        "top_skip_ratio": 0.08,
        "bottom_skip_ratio": 0.03,
        "row_dark_pixel_threshold": 0.055,
        "merge_gap": 16,
        "min_comment_height": 32,
        "max_comment_height": 400,
    }
    if config:
        cfg.update(config)

    image = Image.open(image_path).convert("RGB")
    width, height = image.size
    gray = ImageOps.grayscale(image)
    
    left = int(width * cfg["side_margin_ratio"])
    right = int(width * (1 - cfg["side_margin_ratio"]))
    top = int(height * cfg["top_skip_ratio"])
    bottom = int(height * (1 - cfg["bottom_skip_ratio"]))
    
    rows = []
    for y in range(top, bottom):
        dark = 0
        total = max(right - left, 1)
        for x in range(left, right, 3):
            if gray.getpixel((x, y)) < 178:
                dark += 3
        rows.append((y, dark / total))

    active_rows = [y for y, density in rows if density >= cfg["row_dark_pixel_threshold"]]
    raw_groups = _group_rows(active_rows, cfg["merge_gap"])
    
    segments: list[Segment] = []
    for start, end in raw_groups:
        padded = (max(top, start - 10), min(bottom, end + 14))
        block_height = padded[1] - padded[0]
        if cfg["min_comment_height"] <= block_height <= cfg["max_comment_height"]:
            density = _average_density(rows, padded[0], padded[1])
            segments.append(Segment((0, padded[0], width, padded[1]), min(round(density * 5, 3), 0.99)))
            
    return _merge_nearby_segments(segments, cfg["merge_gap"], cfg["max_comment_height"])


def _group_rows(rows: list[int], max_gap: int) -> list[tuple[int, int]]:
    if not rows:
        return []
    groups: list[tuple[int, int]] = []
    start = prev = rows[0]
    for row in rows[1:]:
        if row - prev <= max_gap:
            prev = row
            continue
        groups.append((start, prev))
        start = prev = row
    groups.append((start, prev))
    return groups


def _average_density(rows: list[tuple[int, float]], start: int, end: int) -> float:
    values = [density for y, density in rows if start <= y <= end]
    return sum(values) / len(values) if values else 0.0


def _merge_nearby_segments(segments: list[Segment], merge_gap: int, max_height: int) -> list[Segment]:
    if not segments:
        return []
    merged: list[Segment] = [segments[0]]
    for segment in segments[1:]:
        prev = merged[-1]
        if segment.bbox[1] - prev.bbox[3] <= merge_gap:
            bbox = (0, prev.bbox[1], segment.bbox[2], segment.bbox[3])
            height = bbox[3] - bbox[1]
            if height <= max_height:
                merged[-1] = Segment(bbox, max(prev.confidence, segment.confidence))
                continue
        merged.append(segment)
    return merged

