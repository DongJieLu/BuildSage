"""检索策略引擎：direct / hyde / subquery / rewrite。"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from app.llm.models import get_chat_model

logger = logging.getLogger(__name__)

VALID_STRATEGIES = ("direct", "hyde", "subquery", "rewrite")

STRATEGY_PROMPT = (
    "你是 DIY 装机知识库的检索策略决策器。只输出 JSON："
    '{"strategy":"direct|hyde|subquery|rewrite","queries":["..."],"reason":"..."}。\n'
    "direct：问题清晰，直接检索原问题；"
    "hyde：问题口语化，先生成一段假设性知识库文本；"
    "subquery：问题包含多个并列主题，拆成 2 到 3 个子问题；"
    "rewrite：结合对话历史，把包含“它/这个/上面”等指代的问题改写成独立问题。"
)

HYDE_PROMPT = (
    "你是 DIY 装机知识库的检索辅助器。根据问题生成一段可能出现在装机知识文档里的"
    "事实性文本，只输出文本本身，不要解释，不要编造具体品牌参数。"
)


@dataclass
class StrategyPlan:
    strategy: str
    queries: list[str] = field(default_factory=list)
    reason: str = ""


def _extract_json(content: str) -> dict | None:
    text = (content or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _message_content(message) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, list):
        return "".join(
            item.get("text", "") if isinstance(item, dict) else str(item)
            for item in content
        )
    return str(content or "")


class StrategyEngine:
    def __init__(self, llm=None) -> None:
        self._llm = llm

    def _get_llm(self):
        if self._llm is None:
            self._llm = get_chat_model()
        return self._llm

    def plan(self, question: str, history: list | None = None) -> StrategyPlan:
        data = self._select(question, history)
        strategy = data["strategy"]
        if strategy == "hyde":
            hypothesis = self._hypothesis(question)
            return StrategyPlan("hyde", [hypothesis or question], data.get("reason", ""))
        if strategy in ("subquery", "rewrite"):
            queries = self._clean_queries(data.get("queries"))
            return StrategyPlan(strategy, queries or [question], data.get("reason", ""))
        return StrategyPlan("direct", [question], data.get("reason", ""))

    def _select(self, question: str, history: list | None) -> dict:
        history_text = ""
        if history:
            lines = []
            for message in history[-6:]:
                role = "用户" if getattr(message, "type", "") in ("human", "user") else "助手"
                lines.append(f"{role}: {getattr(message, 'content', '')}")
            history_text = "\n对话历史：\n" + "\n".join(lines)
        try:
            response = self._get_llm().invoke(
                [
                    ("system", STRATEGY_PROMPT),
                    ("user", f"{history_text}\n当前问题：{question}"),
                ]
            )
            data = _extract_json(_message_content(response))
            if data and data.get("strategy") in VALID_STRATEGIES:
                return data
        except Exception as exc:  # noqa: BLE001
            logger.warning("检索策略决策失败，默认 direct: %s", exc)
        return {"strategy": "direct", "queries": [question], "reason": "策略决策失败，默认 direct"}

    def _hypothesis(self, question: str) -> str:
        try:
            response = self._get_llm().invoke(
                [("system", HYDE_PROMPT), ("user", question)]
            )
            return _message_content(response).strip()
        except Exception as exc:  # noqa: BLE001
            logger.warning("HyDE 生成失败，回退原问题: %s", exc)
            return ""

    @staticmethod
    def _clean_queries(queries) -> list[str]:
        if not isinstance(queries, list):
            return []
        return [str(query).strip() for query in queries if str(query).strip()]
