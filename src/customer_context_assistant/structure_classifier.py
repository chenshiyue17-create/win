from __future__ import annotations

from dataclasses import dataclass

from customer_context_assistant.knowledge_base import KnowledgeBase, STRUCTURE_SIGNAL_PHRASES


@dataclass(frozen=True)
class StructureCandidate:
    brand: str
    series: str
    features: list[str]
    score: int
    evidence: str
    entry_id: str


def _field(content: str, label: str) -> str:
    prefix = f"{label}："
    for line in content.splitlines():
        if line.startswith(prefix):
            return line.removeprefix(prefix).strip()
    return ""


def extract_visible_features(text: str) -> list[str]:
    lowered = text.lower()
    return [feature for feature in STRUCTURE_SIGNAL_PHRASES if feature.lower() in lowered]


def identify_brand_by_structure(kb: KnowledgeBase, visual_description: str, limit: int = 5) -> list[StructureCandidate]:
    features = extract_visible_features(visual_description)
    if len(features) < 2:
        return []

    query = visual_description + " 截面 结构 像什么品牌"
    candidates: list[StructureCandidate] = []
    for match in kb.search(query, limit=30, min_score=1):
        entry = match.entry
        if not entry.id.startswith("menchuang-brand-structure-"):
            continue
        brand = _field(entry.content, "品牌结构指纹")
        series = _field(entry.content, "系列/型号线索")
        card_features = [item.strip() for item in _field(entry.content, "截面结构特征").split("、") if item.strip()]
        shared = [feature for feature in features if feature in card_features]
        if len(shared) < 2:
            continue
        candidates.append(
            StructureCandidate(
                brand=brand,
                series=series or "未明确到系列",
                features=shared,
                score=match.score + len(shared) * 10,
                evidence=_field(entry.content, "证据原文"),
                entry_id=entry.id,
            )
        )

    candidates.sort(key=lambda item: item.score, reverse=True)
    deduped: list[StructureCandidate] = []
    seen: set[tuple[str, str, tuple[str, ...]]] = set()
    for candidate in candidates:
        key = (candidate.brand, candidate.series, tuple(candidate.features))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
        if len(deduped) >= limit:
            break
    return deduped
