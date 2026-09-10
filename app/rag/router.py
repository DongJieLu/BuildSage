"""查询路由：相关性判断 → rag | reject。

配置器复用 /chat 接口时，通过固定前缀进入 compat；普通聊天统一进入 RAG。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from pydantic import BaseModel, Field

from app.llm.models import get_chat_model

logger = logging.getLogger(__name__)

CHITCHAT_WORDS = ("你好", "您好", "谢谢", "再见", "在吗", "嗨", "hello", "hi")

CLASSIFY_PROMPT = (
    "你是 DIY 装机知识库的查询分类器，只输出 JSON："
    '{"intent":"rag|reject","confidence":0.0,"reason":"..."}。\n'
    "rag：需要检索装机攻略后综合回答的问题；"
    "reject：寒暄、闲聊或与 DIY 装机无关的问题。"
)


class RouteDecision(BaseModel):
    intent: str = Field(description="rag | reject")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    reason: str = ""


def _extract_json(content: str) -> dict | None:
    import json

    text = str(getattr(content, "content", content) or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _to_float(value, default: float = 0.5) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


class Router:
    def __init__(self, llm=None) -> None:
        self._llm = llm

    @staticmethod
    def _rule_route(question: str) -> dict | None:
        q = (question or "").strip()
        if len(q) <= 20 and any(word in q.lower() for word in CHITCHAT_WORDS):
            return {"intent": "reject", "confidence": 0.95, "reason": "寒暄/闲聊"}
        # 配置器仍复用 /chat 接口，保留这一条 UI 工具入口；普通聊天不走该分支。
        if q.startswith("帮我检查这套配置是否兼容："):
            return {"intent": "compat", "confidence": 1.0, "reason": "配置器兼容校验入口"}
        return None

    def _classify(self, question: str) -> dict:
        try:
            llm = self._llm or get_chat_model()
            messages = [("system", CLASSIFY_PROMPT), ("user", question)]
            data = None
            if hasattr(llm, "with_structured_output"):
                decision = llm.with_structured_output(
                    RouteDecision, method="function_calling"
                ).invoke(messages)
                if isinstance(decision, RouteDecision):
                    data = decision.model_dump()
                elif isinstance(decision, dict):
                    data = decision
            if data is None:
                data = _extract_json(llm.invoke(messages))
            if data and data.get("intent") in ("rag", "reject"):
                return {
                    "intent": data["intent"],
                    "confidence": _to_float(data.get("confidence")),
                    "reason": data.get("reason") or "",
                }
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM 路由分类失败，默认 rag: %s", exc)
        return {"intent": "rag", "confidence": 0.5, "reason": "LLM 分类失败，默认 rag"}

    def route(self, question: str, category: str | None = None) -> dict:
        detail: dict = {"l1": None, "l2": None}
        if not (question or "").strip():
            detail["l1"] = {"hit": True, "intent": "reject", "reason": "空问题"}
            return {"intent": "reject", "confidence": 1.0, "reason": "空问题", "route_detail": detail}

        l1 = self._rule_route(question)
        if l1:
            detail["l1"] = {"hit": True, **l1}
            return {**l1, "route_detail": detail}

        l3 = self._classify(question)
        detail["l2"] = l3
        if l3["intent"] == "reject":
            return {
                "intent": "reject",
                "confidence": l3["confidence"],
                "reason": "LLM 判定与装机知识库无关",
                "route_detail": detail,
            }
        return {
            "intent": "rag",
            "confidence": l3["confidence"],
            "reason": "进入统一 RAG 检索生成",
            "route_detail": detail,
        }


def rule_route(question: str) -> dict | None:
    """兼容旧版测试/调用方；真实问答请使用 Router.route。"""
    decision = Router._rule_route(question)
    if decision is None:
        import re

        q = (question or "").strip()
        if not q:
            return _RuleDecision("reject", 1.0, "空问题")
        model = re.search(
            r"(?:rtx|gtx|rx)\s?\d{3,4}\w*|i[3579]-\d{4,5}\w*|ryzen\s?\d\s?\d{4}\w*",
            q,
            re.I,
        )
        if model and any(word in q.lower() for word in ("tdp", "功耗", "显存", "核心", "线程", "频率", "vram")):
            return _RuleDecision("param", 0.9, "兼容旧版参数规则")
        if model and any(word in q for word in ("兼容", "带得动", "配", "能用", "支持", "够吗")):
            return _RuleDecision("compat", 0.85, "兼容旧版兼容性规则")
        if re.search(r"\b[abhzx]\d{3}[a-z]{0,2}\b", q, re.I) and any(
            word in q for word in ("兼容", "能用", "支持")
        ):
            return _RuleDecision("compat", 0.85, "兼容旧版兼容性规则")
        return None
    if decision["intent"] == "compat":
        return _RuleDecision(**decision)
    return _RuleDecision(**decision)


@dataclass
class _RuleDecision:
    """兼容旧测试的轻量 L1 决策对象。"""

    intent: str
    confidence: float
    reason: str
