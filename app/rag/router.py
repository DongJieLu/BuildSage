"""查询路由（LangChain 版）：L1 规则词 + L2 LLM 结构化分类 → param | compat | rag | reject。

EduRAG 三层路由（规则/FAQ语义/LLM 分类）演进为四通道：
- param：参数直查（型号 + 参数字段，查规格库）
- compat：兼容性校验（配置清单或多件对比）
- rag：选购攻略深度问答
- reject：寒暄/无关
L1 规则零成本拦截高频模式，其余走 with_structured_output 的 LLM 分类。
"""
from __future__ import annotations

import logging
import re

from pydantic import BaseModel, Field

from app.llm.models import get_chat_model

logger = logging.getLogger(__name__)

# L1 规则词：确定性强的模式直接分流，不花 LLM 调用
CHITCHAT_WORDS = ("你好", "您好", "谢谢", "再见", "在吗", "嗨", "hello", "hi")
# 型号 + 参数字段模式：如 "4070 的 tdp"、"14900K 功耗多少"
_MODEL_RE = re.compile(
    r"\b(?:rtx|gtx)\s?\d{3,4}\w*|(?:radeon\s+)?rx\s?\d{3,4}\w*|i[3579]-\d{4,5}\w*"
    r"|(?:ryzen\s?\d\s?\d{4}\w*)|ultra\s?\d\s?\d{3}\w*"
    r"|\b[abhzxy]?\d{3}[a-z]?\b(?:\s?(?:motherboard|主板|芯片组|tomahawk|gaming|aorus|tuf|plus|max))?",
    re.I,
)
_PARAM_WORDS = (
    "tdp", "功耗", "参数", "多少瓦", "瓦数", "显存", "核心数", "线程", "频率",
    "插槽", "socket", "接口", "规格", "多大内存", "长度", "vram", "价格",
)
_COMPAT_WORDS = (
    "兼容", "能不能配", "能不能用", "带得动", "能装吗", "冲突", "匹配吗",
    "能插", "行不行", "合适吗", "搭不搭", "装得上", "够吗", "够不够",
    "能用", "可以用", "支持吗", "装吗", "上得了", "吃得住", "支持",
)


class RouteDecision(BaseModel):
    """with_structured_output 的目标 schema。"""

    intent: str = Field(description="param | compat | rag | reject")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    reason: str = Field(default="")


ROUTE_SYSTEM_PROMPT = (
    "你是装机问答的路由分类器。将用户问题分为四类，只依据问题本身判断：\n"
    "- param：询问具体硬件型号的某个参数数值（如「RTX 4070 的 TDP 是多少」「i9-14900K 用什么插槽」）\n"
    "- compat：判断多个配件之间能否搭配/兼容，或配置清单的功耗/尺寸核算（如「i9-14900K 配 650W 电源够吗」「B650 主板能用 DDR4 吗」）\n"
    "- rag：装机选购建议、科普、攻略类开放问题（如「5000 预算怎么配」「DDR4 和 DDR5 怎么选」）\n"
    "- reject：寒暄闲聊或与装机完全无关的问题"
)

VALID_INTENTS = ("param", "compat", "rag", "reject")


def rule_route(question: str) -> RouteDecision | None:
    """L1 规则：零成本拦截确定模式。"""
    q = (question or "").strip()
    if not q:
        return RouteDecision(intent="reject", confidence=1.0, reason="空问题")
    if len(q) <= 20 and any(w in q.lower() for w in CHITCHAT_WORDS):
        return RouteDecision(intent="reject", confidence=0.95, reason="寒暄/闲聊")
    q_lower = q.lower()
    has_model = bool(_MODEL_RE.search(q))
    if has_model and any(w in q_lower for w in _PARAM_WORDS):
        # 型号+参数词 → param；但若同时出现兼容词（"4070 配 650W 电源够吗"）→ compat
        if any(w in q for w in _COMPAT_WORDS):
            return RouteDecision(intent="compat", confidence=0.9, reason="型号+兼容词命中")
        return RouteDecision(intent="param", confidence=0.92, reason="型号+参数词命中")
    if any(w in q for w in _COMPAT_WORDS):
        return RouteDecision(intent="compat", confidence=0.85, reason="兼容词命中")
    return None


class Router:
    def __init__(self, llm=None) -> None:
        self._llm = llm

    def _classify(self, question: str) -> RouteDecision:
        try:
            llm = self._llm or get_chat_model()
            structured = llm.with_structured_output(RouteDecision, method="function_calling")
            decision = structured.invoke(
                [{"role": "system", "content": ROUTE_SYSTEM_PROMPT}, {"role": "user", "content": question}]
            )
            if isinstance(decision, RouteDecision) and decision.intent in VALID_INTENTS:
                return decision
            return RouteDecision(intent="rag", confidence=0.5, reason="结构化输出异常回退 rag")
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM 路由分类失败，默认 rag: %s", exc)
            return RouteDecision(intent="rag", confidence=0.5, reason=f"LLM 分类失败默认 rag: {exc}")

    def route(self, question: str, history: list | None = None) -> dict:
        """返回 {intent, confidence, reason, route_detail}。"""
        detail: dict = {"l1": None, "l2": None}
        l1 = rule_route(question)
        if l1 is not None:
            detail["l1"] = {"hit": True, "intent": l1.intent, "reason": l1.reason}
            return {"intent": l1.intent, "confidence": l1.confidence, "reason": l1.reason, "route_detail": detail}
        decision = self._classify(question)
        if decision.intent not in VALID_INTENTS:
            decision = RouteDecision(intent="rag", confidence=0.5, reason=f"非法 intent 回退 rag: {decision.intent}")
        detail["l2"] = {"intent": decision.intent, "confidence": decision.confidence, "reason": decision.reason}
        return {
            "intent": decision.intent,
            "confidence": decision.confidence,
            "reason": decision.reason,
            "route_detail": detail,
        }
