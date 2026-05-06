from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_DIR = ROOT / "data" / "knowledge"
SOURCE_FILE = ROOT / "data" / "knowledge_base.json"
SEED_FILE = ROOT / "tasks" / "knowledge_base.seed.json"

GENERATED_PREFIX = "menchuang-"

DOMAIN_PHRASES = (
    "断桥铝",
    "系统窗",
    "门窗",
    "截面",
    "样角",
    "品牌",
    "系列",
    "结构",
    "主框",
    "副框",
    "玻扇",
    "压线",
    "活动压线",
    "闭口压线",
    "不可拆卸",
    "隔热条",
    "胶条",
    "等压胶条",
    "搭接",
    "冷腔",
    "暖腔",
    "外小冷腔",
    "内大暖腔",
    "内置铰链",
    "栅栏式隔热条",
    "承重",
    "水密",
    "气密",
    "保温",
    "隔热",
    "隔音",
    "五金",
    "玻璃",
    "lowe",
    "4sg",
    "超白",
    "三玻两腔",
    "开扇",
    "安装费",
    "运费",
    "吊装",
    "报价",
    "价格",
    "自爆",
    "8字纹",
    "蝴蝶纹",
    "讴铂",
    "欧泊",
    "新豪轩",
    "富轩",
    "富贵花",
    "皇派",
    "派雅",
    "轩尼斯",
    "兴发",
    "京港亚",
    "极景",
    "正典",
    "19分贝",
    "铂斯派",
    "卫洛柯",
    "伟昌",
    "坚美",
    "伟业",
    "好博",
    "江阴海达",
    "瑞纳斯",
)


@dataclass(frozen=True)
class Section:
    title: str
    body: str
    level: int


def slugify(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", value.lower()).strip("-")
    cleaned = re.sub(r"-+", "-", cleaned)
    if not cleaned:
        cleaned = fallback
    return cleaned[:80]


def read_json(path: Path) -> dict:
    if not path.exists():
        return {"entries": []}
    return json.loads(path.read_text(encoding="utf-8"))


def base_entries() -> list[dict]:
    entries = read_json(SOURCE_FILE).get("entries", [])
    result = []
    for entry in entries:
        entry_id = entry.get("id", "")
        if entry_id.startswith(GENERATED_PREFIX) or entry_id.startswith("feed-"):
            continue
        result.append(entry)
    return result


def split_sections(markdown: str, level: int = 2) -> list[Section]:
    pattern = re.compile(rf"^{'#' * level} (?P<title>.+)$", re.MULTILINE)
    matches = list(pattern.finditer(markdown))
    sections: list[Section] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        title = match.group("title").strip()
        body = markdown[start:end].strip()
        if body:
            sections.append(Section(title=title, body=body, level=level))
    return sections


def infer_tags(title: str, content: str, extra: list[str] | None = None) -> list[str]:
    text = f"{title}\n{content}".lower()
    tags = list(extra or [])
    for phrase in DOMAIN_PHRASES:
        if phrase.lower() in text and phrase not in tags:
            tags.append(phrase)
    return tags[:14] or ["门窗知识库"]


def reply_template(content: str) -> list[str]:
    candidates = []
    for raw_line in content.splitlines():
        line = re.sub(r"^[#>*\-\s]+", "", raw_line).strip()
        if not line:
            continue
        if "作者" in line and any(word in line for word in ("可以", "更好", "不建议", "像是", "价格", "五金", "压线", "隔热", "结构")):
            candidates.append(line[:220])
    if candidates:
        return [candidates[0]]
    return ["我先按图片里的结构证据判断，不直接按品牌名下结论；重点看主框/副框/玻扇、压线、隔热条、胶条搭接和报价包含项。"]


def entry(entry_id: str, title: str, content: str, tags: list[str], source: Path, kind: str) -> dict:
    return {
        "id": entry_id,
        "title": title,
        "content": content.strip(),
        "tags": tags,
        "image_path": "/static/assets/window-system.svg",
        "reply_templates": reply_template(content),
        "attachments": [
            {
                "label": source.name,
                "path": f"data/knowledge/{source.name}",
                "type": "markdown",
                "note": f"整库重建生成的{kind}知识卡。",
            }
        ],
        "version": {
            "version": "2.0.0",
            "updated_by": "rebuild_knowledge_base",
            "change_note": "granular rebuild from distilled markdown knowledge",
        },
    }


def build_from_file(path: Path) -> list[dict]:
    markdown = path.read_text(encoding="utf-8")
    stem = path.stem
    entries: list[dict] = []
    mapping = {
        "section_index": ("截面结构", "section"),
        "distilled_knowledge": ("蒸馏知识", "pattern"),
        "visual_sample_library": ("图文样本", "sample"),
        "brand_profiles": ("品牌画像", "brand"),
        "brand_series_profiles": ("系列画像", "series"),
        "case_studies": ("评论案例", "case"),
    }
    if stem in mapping:
        kind_label, slug_prefix = mapping[stem]
        for index, section in enumerate(split_sections(markdown, level=2), start=1):
            title = f"{kind_label}: {section.title}"
            content = f"## {section.title}\n\n{section.body}"
            entries.append(
                entry(
                    f"{GENERATED_PREFIX}{slug_prefix}-{index:04d}-{slugify(section.title, str(index))}",
                    title,
                    content,
                    infer_tags(title, content, [kind_label, "门窗知识库"]),
                    path,
                    kind_label,
                )
            )
        return entries

    title = markdown.splitlines()[0].lstrip("# ").strip() if markdown.splitlines() else stem
    entries.append(
        entry(
            f"{GENERATED_PREFIX}doc-{slugify(stem, stem)}",
            title,
            markdown,
            infer_tags(title, markdown, ["门窗知识库"]),
            path,
            "完整文档",
        )
    )
    return entries


def rebuild() -> list[dict]:
    entries = base_entries()
    for path in sorted(KNOWLEDGE_DIR.glob("*.md")):
        entries.extend(build_from_file(path))

    seen: set[str] = set()
    deduped: list[dict] = []
    for item in entries:
        if item["id"] in seen:
            continue
        seen.add(item["id"])
        deduped.append(item)
    return deduped


def main() -> int:
    entries = rebuild()
    payload = {"entries": entries}
    SOURCE_FILE.parent.mkdir(parents=True, exist_ok=True)
    SOURCE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    SEED_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"rebuilt_entries={len(entries)}")
    generated = sum(1 for item in entries if item["id"].startswith(GENERATED_PREFIX))
    print(f"generated_entries={generated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
