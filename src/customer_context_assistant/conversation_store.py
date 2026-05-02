from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from customer_context_assistant.models import ConversationSession, MessageInput


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_session_id(value: str) -> str:
    cleaned = re.sub(r"\s+", "-", value.strip())
    cleaned = re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]", "", cleaned)
    return cleaned[:64] or "default"


COMMON_CHAT_WORDS = {
    "微信",
    "企业微信",
    "在线客服",
    "客服",
    "发送",
    "输入",
    "消息",
    "聊天",
    "图片",
    "语音",
    "表情",
    "更多",
    "搜索",
    "门窗工具",
}

QUESTION_OR_NEED_PATTERN = r"(多少钱|价格|报价|想做|需要|怎么|多少|我家|有必要|吗|呢|？|\?)"
DOMAIN_WORD_PATTERN = r"(系统窗|玻璃|隔音|封阳台|安装|尺寸|阳台|断桥铝|门窗)"
NAME_MARKER_PATTERN = r"(姐|哥|总|经理|老板|先生|女士|老师|客户)"

RADAR_DIMENSIONS = {
    "需求清晰": ("系统窗", "断桥铝", "玻璃", "隔音", "隔热", "封阳台", "漏风", "西晒", "安全", "尺寸", "楼层", "临街"),
    "预算敏感": ("多少钱", "价格", "报价", "贵", "便宜", "预算", "优惠", "活动", "一平方", "能少"),
    "成交紧迫": ("今天", "明天", "近期", "马上", "尽快", "什么时候", "约测量", "上门", "安装", "装修"),
    "信任程度": ("你们", "品牌", "案例", "质保", "售后", "标准", "检测", "合同", "靠谱", "保证"),
    "风险顾虑": ("怕", "担心", "漏水", "漏风", "隔音不好", "踩坑", "变形", "开裂", "售后", "风险", "绝对"),
    "决策成熟": ("测量", "下单", "定金", "方案", "对比", "家里人", "决定", "什么时候做", "发地址", "报价单"),
}


def infer_session_id_from_text(text: str, fallback: str = "default") -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines[:8]:
        match = re.search(r"(?:客户昵称|昵称|微信名|联系人|备注|姓名|对方)[:：]\s*([0-9A-Za-z_\-\u4e00-\u9fff]{2,24})", line)
        if match and not re.search(QUESTION_OR_NEED_PATTERN, match.group(1)):
            return normalize_session_id(match.group(1))
    for line in lines[:5]:
        candidate = re.sub(r"^(客户|用户|客服|我|agent|support)[:：]\s*", "", line, flags=re.I).strip()
        candidate = re.sub(r"\s+", "", candidate)
        if 2 <= len(candidate) <= 18 and candidate not in COMMON_CHAT_WORDS:
            has_domain_word = re.search(DOMAIN_WORD_PATTERN, candidate)
            has_name_marker = re.search(NAME_MARKER_PATTERN, candidate)
            if not re.search(QUESTION_OR_NEED_PATTERN, candidate) and (not has_domain_word or has_name_marker):
                return normalize_session_id(candidate)
    return normalize_session_id(fallback)


def clamp_score(value: int) -> int:
    return max(0, min(100, value))


def score_customer_radar(messages: list[MessageInput]) -> dict[str, int]:
    text = "\n".join(message.text for message in messages if message.text.strip())
    lowered = text.lower()
    total_messages = len([message for message in messages if message.text.strip()])
    radar: dict[str, int] = {}
    for dimension, keywords in RADAR_DIMENSIONS.items():
        hits = sum(1 for keyword in keywords if keyword.lower() in lowered)
        radar[dimension] = clamp_score(18 + hits * 14 + min(total_messages, 8) * 3)
    if radar["预算敏感"] >= 60:
        radar["决策成熟"] = clamp_score(radar["决策成熟"] + 8)
    if radar["风险顾虑"] >= 60:
        radar["信任程度"] = clamp_score(radar["信任程度"] + 6)
    return radar


class ConversationStore:
    def __init__(self, path: Path, max_messages_per_session: int = 80) -> None:
        self.path = path
        self.max_messages_per_session = max_messages_per_session
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write({})

    def _read(self) -> dict[str, ConversationSession]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            raw = {}
        return {key: ConversationSession.model_validate(value) for key, value in raw.items()}

    def _write(self, sessions: dict[str, ConversationSession]) -> None:
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        payload = {key: session.model_dump() for key, session in sessions.items()}
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(self.path)

    def get_or_create(self, session_id: str, title: str | None = None) -> ConversationSession:
        safe_id = normalize_session_id(session_id)
        sessions = self._read()
        if safe_id in sessions:
            return sessions[safe_id]
        stamp = now_iso()
        session = ConversationSession(id=safe_id, title=title or safe_id, messages=[], radar=score_customer_radar([]), created_at=stamp, updated_at=stamp)
        sessions[safe_id] = session
        self._write(sessions)
        return session

    def append_messages(self, session_id: str, messages: list[MessageInput], title: str | None = None) -> ConversationSession:
        safe_id = normalize_session_id(session_id)
        sessions = self._read()
        session = sessions.get(safe_id) or self.get_or_create(safe_id, title=title)
        existing = list(session.messages)
        for message in messages:
            if message.text.strip():
                existing.append(MessageInput(id=message.id, sender=message.sender, text=message.text.strip()))
        session.messages = existing[-self.max_messages_per_session :]
        session.radar = score_customer_radar(session.messages)
        session.title = title or session.title
        session.updated_at = now_iso()
        sessions[safe_id] = session
        self._write(sessions)
        return session

    def recent_context(self, session_id: str, limit: int = 8) -> list[MessageInput]:
        session = self.get_or_create(session_id)
        return session.messages[-max(1, limit) :]

    def list_sessions(self) -> list[ConversationSession]:
        sessions = self._read()
        return sorted(sessions.values(), key=lambda item: item.updated_at, reverse=True)

    def clear(self, session_id: str) -> None:
        safe_id = normalize_session_id(session_id)
        sessions = self._read()
        if safe_id in sessions:
            del sessions[safe_id]
            self._write(sessions)
