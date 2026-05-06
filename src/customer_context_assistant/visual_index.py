from __future__ import annotations

import io
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageFilter, ImageOps


LOGGER = logging.getLogger(__name__)
IMAGE_LINE_RE = re.compile(r"- 图片:\s*`([^`]+)`")
FIELD_RE = re.compile(r"- ([^:：]+)[:：]\s*(.*)")


@dataclass(frozen=True)
class VisualFingerprint:
    average_hash: str
    difference_hash: str
    edge_grid: list[float]
    projection: list[float]

    def to_dict(self) -> dict[str, object]:
        return {
            "average_hash": self.average_hash,
            "difference_hash": self.difference_hash,
            "edge_grid": self.edge_grid,
            "projection": self.projection,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "VisualFingerprint":
        return cls(
            average_hash=str(payload.get("average_hash", "")),
            difference_hash=str(payload.get("difference_hash", "")),
            edge_grid=[float(item) for item in payload.get("edge_grid", [])],
            projection=[float(item) for item in payload.get("projection", [])],
        )


@dataclass(frozen=True)
class VisualIndexEntry:
    id: str
    title: str
    image: str
    source_image: str
    source_file: str
    source_note: str
    topic: str
    brand_clues: list[str]
    knowledge_modes: list[str]
    customer_question: str
    author_replies: list[str]
    fingerprint: VisualFingerprint

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "image": self.image,
            "source_image": self.source_image,
            "source_file": self.source_file,
            "source_note": self.source_note,
            "topic": self.topic,
            "brand_clues": self.brand_clues,
            "knowledge_modes": self.knowledge_modes,
            "customer_question": self.customer_question,
            "author_replies": self.author_replies,
            "fingerprint": self.fingerprint.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "VisualIndexEntry":
        return cls(
            id=str(payload.get("id", "")),
            title=str(payload.get("title", "")),
            image=str(payload.get("image", "")),
            source_image=str(payload.get("source_image", "")),
            source_file=str(payload.get("source_file", "")),
            source_note=str(payload.get("source_note", "")),
            topic=str(payload.get("topic", "")),
            brand_clues=[str(item) for item in payload.get("brand_clues", [])],
            knowledge_modes=[str(item) for item in payload.get("knowledge_modes", [])],
            customer_question=str(payload.get("customer_question", "")),
            author_replies=[str(item) for item in payload.get("author_replies", [])],
            fingerprint=VisualFingerprint.from_dict(payload.get("fingerprint", {})),
        )


@dataclass(frozen=True)
class VisualMatch:
    entry: VisualIndexEntry
    score: float
    distance: float
    reasons: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "entry": self.entry.to_dict(),
            "score": round(self.score, 4),
            "distance": round(self.distance, 4),
            "reasons": self.reasons,
        }


class VisualIndex:
    def __init__(self, entries: list[VisualIndexEntry] | None = None) -> None:
        self.entries = entries or []

    @classmethod
    def load(cls, path: Path) -> "VisualIndex":
        if not path.exists():
            LOGGER.warning("Visual index does not exist: %s", path)
            return cls([])
        raw = json.loads(path.read_text(encoding="utf-8"))
        entries = [VisualIndexEntry.from_dict(item) for item in raw.get("entries", [])]
        return cls(entries)

    def match_bytes(self, data: bytes, limit: int = 5) -> list[VisualMatch]:
        if not self.entries:
            return []
        fingerprint = fingerprint_image_bytes(data)
        matches: list[VisualMatch] = []
        for entry in self.entries:
            distance = fingerprint_distance(fingerprint, entry.fingerprint)
            score = max(0.0, 1.0 - distance)
            reasons = _match_reasons(entry, distance)
            matches.append(VisualMatch(entry=entry, score=score, distance=distance, reasons=reasons))
        matches.sort(key=lambda item: (item.distance, -len(item.entry.brand_clues)))
        return matches[: max(1, limit)]


def fingerprint_image_path(path: Path) -> VisualFingerprint:
    with Image.open(path) as image:
        return fingerprint_image(image)


def fingerprint_image_bytes(data: bytes) -> VisualFingerprint:
    with Image.open(io.BytesIO(data)) as image:
        return fingerprint_image(image)


def fingerprint_image(image: Image.Image) -> VisualFingerprint:
    gray = ImageOps.grayscale(image).resize((64, 64), Image.Resampling.LANCZOS)
    return VisualFingerprint(
        average_hash=_average_hash(gray),
        difference_hash=_difference_hash(gray),
        edge_grid=_edge_grid(gray),
        projection=_projection(gray),
    )


def fingerprint_distance(left: VisualFingerprint, right: VisualFingerprint) -> float:
    hash_bits = len(left.average_hash) + len(left.difference_hash)
    if hash_bits == 0:
        return 1.0
    hash_distance = (
        _hamming(left.average_hash, right.average_hash) + _hamming(left.difference_hash, right.difference_hash)
    ) / hash_bits
    edge_distance = _vector_l1(left.edge_grid, right.edge_grid)
    projection_distance = _vector_l1(left.projection, right.projection)
    return min(1.0, (hash_distance * 0.46) + (edge_distance * 0.34) + (projection_distance * 0.20))


def parse_visual_sample_library(path: Path) -> list[dict[str, object]]:
    text = path.read_text(encoding="utf-8")
    blocks = re.split(r"(?=^## 样本 \d+)", text, flags=re.MULTILINE)
    samples: list[dict[str, object]] = []
    for block in blocks:
        if not block.strip().startswith("## 样本"):
            continue
        lines = [line.rstrip() for line in block.splitlines()]
        title = lines[0].lstrip("# ").strip()
        fields: dict[str, str] = {}
        image = ""
        author_replies: list[str] = []
        in_replies = False
        for line in lines[1:]:
            image_match = IMAGE_LINE_RE.search(line)
            if image_match:
                image = image_match.group(1)
                continue
            if line.startswith("### 作者回复"):
                in_replies = True
                continue
            if in_replies and line.startswith("- "):
                author_replies.append(line[2:].strip())
                continue
            field_match = FIELD_RE.match(line)
            if field_match:
                fields[field_match.group(1).strip()] = field_match.group(2).strip()
        if image:
            samples.append(
                {
                    "title": title,
                    "image": image,
                    "source_note": fields.get("来源笔记", ""),
                    "source_file": fields.get("来源文件", ""),
                    "topic": fields.get("主题", ""),
                    "brand_clues": _split_list(fields.get("品牌线索", "")),
                    "knowledge_modes": _split_list(fields.get("知识模式", "")),
                    "customer_question": fields.get("客户问题", ""),
                    "author_replies": author_replies,
                }
            )
    return samples


def build_image_lookup(root: Path) -> dict[str, Path]:
    lookup: dict[str, Path] = {}
    if not root.exists():
        return lookup
    for path in root.rglob("*"):
        if path.suffix.lower() in {".webp", ".png", ".jpg", ".jpeg"}:
            lookup.setdefault(path.name, path)
    return lookup


def build_visual_entries(sample_library: Path, image_root: Path) -> list[VisualIndexEntry]:
    image_lookup = build_image_lookup(image_root)
    entries: list[VisualIndexEntry] = []
    for index, sample in enumerate(parse_visual_sample_library(sample_library), start=1):
        image = str(sample["image"])
        source_image = image_lookup.get(Path(image).name)
        if source_image is None:
            LOGGER.warning("Skipping visual sample without source image: %s", image)
            continue
        try:
            fingerprint = fingerprint_image_path(source_image)
        except OSError as exc:
            LOGGER.warning("Skipping unreadable visual sample %s: %s", source_image, exc)
            continue
        entries.append(
            VisualIndexEntry(
                id=f"visual-sample-{index:04d}",
                title=str(sample["title"]),
                image=image,
                source_image=str(source_image),
                source_file=str(sample["source_file"]),
                source_note=str(sample["source_note"]),
                topic=str(sample["topic"]),
                brand_clues=[str(item) for item in sample["brand_clues"]],
                knowledge_modes=[str(item) for item in sample["knowledge_modes"]],
                customer_question=str(sample["customer_question"]),
                author_replies=[str(item) for item in sample["author_replies"]],
                fingerprint=fingerprint,
            )
        )
    return entries


def save_visual_index(entries: list[VisualIndexEntry], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": "1.0.0",
        "description": "Local perceptual visual index built from the door/window graph-text knowledge library.",
        "entries": [entry.to_dict() for entry in entries],
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _average_hash(gray: Image.Image) -> str:
    thumb = gray.resize((8, 8), Image.Resampling.LANCZOS)
    values = list(thumb.getdata())
    mean = sum(values) / len(values)
    return "".join("1" if value >= mean else "0" for value in values)


def _difference_hash(gray: Image.Image) -> str:
    thumb = gray.resize((9, 8), Image.Resampling.LANCZOS)
    values = list(thumb.getdata())
    bits = []
    for y in range(8):
        offset = y * 9
        for x in range(8):
            bits.append("1" if values[offset + x] > values[offset + x + 1] else "0")
    return "".join(bits)


def _edge_grid(gray: Image.Image) -> list[float]:
    edges = gray.filter(ImageFilter.FIND_EDGES).resize((8, 8), Image.Resampling.BILINEAR)
    return [round(value / 255.0, 4) for value in edges.getdata()]


def _projection(gray: Image.Image) -> list[float]:
    edges = gray.filter(ImageFilter.FIND_EDGES).resize((32, 32), Image.Resampling.BILINEAR)
    pixels = list(edges.getdata())
    rows = [sum(pixels[y * 32 : (y + 1) * 32]) / (32 * 255.0) for y in range(32)]
    cols = [sum(pixels[x + y * 32] for y in range(32)) / (32 * 255.0) for x in range(32)]
    return [round(value, 4) for value in rows + cols]


def _hamming(left: str, right: str) -> int:
    length = min(len(left), len(right))
    if length == 0:
        return max(len(left), len(right))
    return sum(1 for index in range(length) if left[index] != right[index]) + abs(len(left) - len(right))


def _vector_l1(left: list[float], right: list[float]) -> float:
    length = min(len(left), len(right))
    if length == 0:
        return 1.0
    total = sum(abs(left[index] - right[index]) for index in range(length)) / length
    return min(1.0, total + (abs(len(left) - len(right)) / max(len(left), len(right), 1)))


def _split_list(value: str) -> list[str]:
    if not value or value == "无":
        return []
    return [item.strip() for item in re.split(r"[,，、]", value) if item.strip()]


def _match_reasons(entry: VisualIndexEntry, distance: float) -> list[str]:
    reasons = [f"图库视觉距离 {distance:.3f}"]
    if entry.brand_clues:
        reasons.append("样本品牌线索：" + "、".join(entry.brand_clues[:4]))
    if entry.author_replies:
        reasons.append("样本含作者图文回复")
    return reasons
