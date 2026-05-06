from __future__ import annotations

import json
import logging
import re

from customer_context_assistant.config import AssistantConfig, KnowledgeConfig
from customer_context_assistant.knowledge_base import KnowledgeBase, tokenize
from customer_context_assistant.models import AnalyzeRequest, AnalyzeResponse, Hint, MessageInput


LOGGER = logging.getLogger(__name__)

INTENT_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("窗型选择", ("系统窗", "断桥铝", "推拉窗", "平开窗", "封阳台", "窗型", "阳台")),
    ("铝材/型材", ("铝材", "型材", "壁厚", "原生铝", "再生铝", "6063", "腔体")),
    ("玻璃配置", ("玻璃", "中空", "夹胶", "lowe", "low-e", "钢化", "三玻两腔")),
    ("隔音隔热", ("隔音", "隔热", "保温", "漏风", "噪音", "临街", "西晒")),
    ("五金密封", ("五金", "执手", "合页", "密封条", "胶条", "锁点", "开合")),
    ("工艺安装", ("注胶", "组角", "拼角", "安装", "打胶", "防水", "副框")),
    ("测量报价", ("报价", "多少钱", "价格", "预算", "测量", "尺寸", "平方")),
]


def detect_intent(text: str) -> str:
    lowered = text.lower()
    for intent, keywords in INTENT_RULES:
        if any(keyword in lowered for keyword in keywords):
            return intent
    return "一般咨询"


def detect_warnings(text: str, stop_words: tuple[str, ...]) -> list[str]:
    warnings = []
    for word in stop_words:
        if word and word in text:
            warnings.append(f"包含敏感或需要人工确认的信息：{word}")
    if re.search(r"\b\d{15,18}\b", text):
        warnings.append("疑似身份证或长数字隐私信息，回复前请脱敏。")
    return warnings


def _clean_line(line: str) -> str:
    cleaned = re.sub(r"^[#>*\\-\\s]+", "", line).strip()
    cleaned = re.sub(r"`", "", cleaned)
    return re.sub(r"\s+", " ", cleaned)


def _relevant_knowledge_lines(query: str, matches: list, limit: int = 5) -> list[str]:
    query_tokens = tokenize(query)
    if not query_tokens:
        return []
    scored: list[tuple[int, str]] = []
    for match in matches[:6]:
        for raw_line in match.entry.content.splitlines():
            line = _clean_line(raw_line)
            if len(line) < 16 or line.startswith(("图片:", "来源", "样本数", "品牌画像数")):
                continue
            line_tokens = tokenize(line)
            overlap = query_tokens & line_tokens
            score = len(overlap)
            if "作者" in line:
                score += 2
            if any(word in line for word in ("讴铂", "欧泊", "新豪轩", "799", "1280", "五金质保", "内置铰链", "外小冷腔", "压线", "隔热条", "价格", "五金")):
                score += 1
            if score >= 2:
                scored.append((score + match.score, line))
    seen: set[str] = set()
    result: list[str] = []
    for _, line in sorted(scored, key=lambda item: item[0], reverse=True):
        if line in seen:
            continue
        seen.add(line)
        result.append(line)
        if len(result) >= limit:
            break
    return result


def build_reply(message: MessageInput, matches: list, warnings: list[str]) -> str:
    if warnings:
        return "这个点需要谨慎表达，不能做绝对化承诺。我先按客户户型、楼层、朝向、噪音源和预算来判断适合配置，再给可落地的建议。"
    lines = _relevant_knowledge_lines(message.text, matches, limit=3)
    if lines:
        first = lines[0]
        if "讴铂" in first or "欧泊" in first or "内置铰链" in first:
            return (
                "这款从知识库相似案例看，比较像讴铂/欧泊一类的内置铰链结构，但品牌只能说疑似，不能直接认定。"
                "它的优点是内置铰链稳定性相对更好，外小冷腔、内大暖腔的设计对型材保温隔热有帮助。"
                "继续追问商家五金具体品牌、隔热条/胶条品牌、玻璃配置、安装和开扇费用，再判断价格是否合适。"
            )
        if "新豪轩" in first and any(word in first for word in ("799", "1280", "五金质保", "质保")):
            return (
                "这款从知识库相似案例看，疑似新豪轩产品，但品牌仍建议按商家报价单或型材标识确认。"
                "参考同类评论案例：价格大概 799/平，开扇一般 1280 左右，重点要确认是否包含安装费、运费和玻璃增配。"
                "另外这类案例里提到五金质保可能只有一年，建议让商家把五金品牌、质保年限、胶条/隔热条品牌和售后范围写进合同。"
            )
        return "参考知识库相似判断：" + first[:180] + " 建议再补充五金、胶条、隔热条、玻璃配置和报价包含项后确认。"
    if matches and matches[0].entry.reply_templates:
        return matches[0].entry.reply_templates[0]
    return f"收到，关于“{message.text[:28]}”，我建议先问清楚使用场景、楼层朝向、是否临街、洞口尺寸和预算，再给门窗配置。"


def build_interaction_analysis(message: MessageInput, context: list[MessageInput], matches: list, warnings: list[str]) -> str:
    points: list[str] = []
    if context:
        points.append(f"该客户已有 {len(context)} 条上下文，先承接前文，不要重新从零问。")
    if warnings:
        points.append("存在敏感或绝对化表达风险，回复要转为条件判断和人工确认。")
    intent = detect_intent(message.text)
    if intent == "测量报价":
        points.append("客户处在价格/决策推进阶段，先补齐尺寸、楼层、开启方式、预算和安装边界，再报价。")
    elif intent == "玻璃配置":
        points.append("客户关注性能结果，先确认噪音源、西晒、安全和楼层，再推荐玻璃组合。")
    elif intent == "隔音隔热":
        points.append("客户关注痛点改善，避免承诺绝对效果，用场景诊断加可验证配置沟通。")
    elif intent == "工艺安装":
        points.append("客户关注落地风险，重点解释安装、收口、防水、排水和售后边界。")
    else:
        points.append("先识别客户真实动机：省钱、怕踩坑、想比较、还是准备下单，再决定追问深度。")
    if matches:
        points.append(f"可引用知识库：{matches[0].entry.title}。")
    relevant_lines = _relevant_knowledge_lines(message.text, matches, limit=3)
    if relevant_lines:
        points.append("命中的具体判断：" + " / ".join(relevant_lines))
    if message.text and any(word in message.text for word in ("图片", "截面", "样角", "结构", "品牌", "价格")):
        points.append("本地工具不调用外部识图 API；先基于图片保存路径、OCR 文本和知识命中生成初判，深度视觉结构判断交给 Codex。")
    return " ".join(points)


def summarize(message: MessageInput, matches: list) -> str:
    if matches:
        return f"命中知识库：{matches[0].entry.title}"
    if len(message.text) > 36:
        return message.text[:36] + "..."
    return message.text


def latest_customer_message(messages: list[MessageInput]) -> tuple[int, MessageInput] | None:
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if message.sender != "agent" and message.text.strip():
            return index, message
    return None


class AssistantEngine:
    def __init__(self, knowledge_base: KnowledgeBase, kb_config: KnowledgeConfig, assistant_config: AssistantConfig) -> None:
        self.knowledge_base = knowledge_base
        self.kb_config = kb_config
        self.assistant_config = assistant_config

    def analyze(self, request: AnalyzeRequest) -> AnalyzeResponse:
        latest = latest_customer_message(request.messages)
        if latest is None:
            return AnalyzeResponse(hints=[])
        index, message = latest
        context = request.messages[max(0, index - 8) : index]
        context_text = "\n".join(item.text for item in context if item.text.strip())
        search_text = (context_text + "\n" + message.text).strip() if context_text else message.text
        message_id = message.id or f"msg-{index + 1}"
        matches = self.knowledge_base.search(
            search_text,
            limit=self.kb_config.max_results,
            min_score=self.kb_config.min_score,
        )
        warnings = detect_warnings(message.text, self.assistant_config.safety_stop_words) if request.include_safety else []
        
        intent = detect_intent(search_text)
        confidence = min(0.96, max(self.assistant_config.confidence_floor, (matches[0].score / 12) if matches else 0.2))
        summary = summarize(message, matches)
        if context:
            summary = f"结合本客户最近 {len(context)} 条上下文：" + summary

        interaction_analysis = ""
        suggested_reply = ""

        if not suggested_reply:
            interaction_analysis = build_interaction_analysis(message, context, matches, warnings)
            suggested_reply = build_reply(message, matches, warnings)

        return AnalyzeResponse(
            hints=[
                Hint(
                    message_id=message_id,
                    intent=intent,
                    confidence=round(confidence, 2),
                    summary=summary,
                    interaction_analysis=interaction_analysis,
                    suggested_reply=suggested_reply,
                    matched_entries=matches,
                    warnings=warnings,
                )
            ]
        )
