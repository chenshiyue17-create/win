from __future__ import annotations

import json
import logging
import re

import httpx
from customer_context_assistant.config import AssistantConfig, KnowledgeConfig, LLMConfig
from customer_context_assistant.knowledge_base import KnowledgeBase
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


def build_reply(message: MessageInput, matches: list, warnings: list[str]) -> str:
    if warnings:
        return "这个点需要谨慎表达，不能做绝对化承诺。我先按客户户型、楼层、朝向、噪音源和预算来判断适合配置，再给可落地的建议。"
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
    def __init__(self, knowledge_base: KnowledgeBase, kb_config: KnowledgeConfig, assistant_config: AssistantConfig, llm_config: LLMConfig | None = None) -> None:
        self.knowledge_base = knowledge_base
        self.kb_config = kb_config
        self.assistant_config = assistant_config
        self.llm_config = llm_config

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

        # 尝试使用 Gemini 增强分析
        interaction_analysis = ""
        suggested_reply = ""
        
        if self.llm_config and self.llm_config.api_key:
            try:
                interaction_analysis, suggested_reply = self._analyze_with_gemini(
                    message, context, matches, warnings, image_bytes=request.image_bytes
                )
            except Exception as exc:
                LOGGER.warning(f"Gemini 分析失败，降级到本地逻辑: {exc}")

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

    def _analyze_with_gemini(self, message: MessageInput, context: list[MessageInput], matches: list, warnings: list[str], image_bytes: bytes | None = None) -> tuple[str, str]:
        """利用 Gemini 结合本地知识库和图片内容生成回复"""
        import base64
        
        context_str = "\n".join([f"{m.sender}: {m.text}" for m in context])
        kb_context = ""
        if matches:
            kb_context = "\n\n".join([f"【知识点: {m.entry.title}】\n内容: {m.entry.content}\n建议话术参考: {', '.join(m.entry.reply_templates)}" for m in matches])

        prompt = f"""你是一个顶级的门窗技术专家，擅长通过型材样角截面识别品牌和性能。

1. 任务要求：
- 如果提供了图片，请仔细观察型材的“截面结构”。
- 分析：腔体数量、隔热条形状(PA66)、密封道数、型材壁厚感官。
- 识别品牌：尝试识别这是否为 旭格、维诺斯盾、轩尼斯、希美克、派雅、皇派、新豪轩等知名品牌或其仿品。
- 每个品牌的腔体槽位和等温线设计是独特的，请指出其结构优劣。

2. 本地知识库参考：
{kb_context or "未匹配到特定本地知识，请基于您的行业大脑回答。"}

3. 对话上下文：
{context_str}

4. 客户当前问题：{message.text}

{'5. 风险警告：' + ', '.join(warnings) if warnings else ''}

请输出 JSON：
- interaction_analysis: 深度结构分析+品牌识别结论（如果是样角，必须指出结构特征）。
- suggested_reply: 给客户的专业建议。
"""
        messages = [
            {"role": "system", "content": "你是一个严谨的门窗样角识别专家。"},
        ]
        
        user_content = [{"type": "text", "text": prompt}]
        
        if image_bytes:
            b64_image = base64.b64encode(image_bytes).decode("utf-8")
            user_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64_image}"}
            })
            
        messages.append({"role": "user", "content": user_content})

        headers = {
            "Authorization": f"Bearer {self.llm_config.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.llm_config.model,
            "messages": messages,
            "temperature": self.llm_config.temperature,
            "response_format": {"type": "json_object"}
        }
        
        with httpx.Client(timeout=25.0) as client:
            resp = client.post(f"{self.llm_config.base_url}/chat/completions", json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            return parsed.get("interaction_analysis", ""), parsed.get("suggested_reply", "")
