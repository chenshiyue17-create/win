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
    "开扇1280",
    "包含安装",
    "包含安装费",
    "安装费",
    "运费",
    "吊装",
    "报价",
    "价格",
    "质保",
    "五金质保",
    "一年",
    "799",
    "898",
    "1280",
    "100系列",
    "105系列",
    "116系列",
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

REPLY_AUTHORS = ("满天窗", "门窗砍价官")
REPLY_SIGNAL_WORDS = (
    "可以",
    "更好",
    "不建议",
    "像是",
    "好像是",
    "产品",
    "价格",
    "报价",
    "一个平方",
    "开扇",
    "安装费",
    "包含安装",
    "运费",
    "五金",
    "质保",
    "压线",
    "隔热",
    "结构",
    "腔体",
    "胶条",
    "隔热条",
    "玻璃",
    "品牌",
    "系列",
    "pass",
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


def clean_reply_line(raw_line: str) -> str:
    line = re.sub(r"^[#>*\-\s└─`]+", "", raw_line).strip()
    line = re.sub(r"`+", "", line)
    return re.sub(r"\s+", " ", line)


def is_reply_knowledge_line(line: str) -> bool:
    if len(line) < 24 or len(line) > 520:
        return False
    if not any(author in line for author in REPLY_AUTHORS):
        return False
    if "作者" not in line and "回复" not in line:
        return False
    return any(word in line for word in REPLY_SIGNAL_WORDS)


def reply_line_content(line: str, source: Path) -> str:
    return "\n".join(
        [
            line,
            "",
            "使用规则：这是从整库图文评论里拆出的独立作者回复知识卡。先看当前图片/客户问题，再把这条作为相似案例校准；涉及品牌只能说疑似或相似线索，价格要结合城市、安装、开扇、玻璃增配、运费、吊装和质保边界。",
            f"来源文件：data/knowledge/{source.name}",
        ]
    )


def extract_reply_line_entries(path: Path, markdown: str) -> list[dict]:
    entries: list[dict] = []
    seen_lines: set[str] = set()
    for index, raw_line in enumerate(markdown.splitlines(), start=1):
        line = clean_reply_line(raw_line)
        if line in seen_lines or not is_reply_knowledge_line(line):
            continue
        seen_lines.add(line)
        short_title = line
        if len(short_title) > 72:
            short_title = short_title[:72] + "..."
        title = f"作者回复: {short_title}"
        content = reply_line_content(line, path)
        entries.append(
            entry(
                f"{GENERATED_PREFIX}reply-{slugify(path.stem, path.stem)}-{index:04d}-{slugify(line[:36], str(index))}",
                title,
                content,
                infer_tags(title, content, ["作者回复", "评论知识", "门窗知识库"]),
                path,
                "作者回复",
            )
        )
    return entries


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
        entries.extend(extract_reply_line_entries(path, markdown))
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
    entries.extend(extract_reply_line_entries(path, markdown))
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
