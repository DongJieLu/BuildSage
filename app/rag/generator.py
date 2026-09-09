"""生成器（LangChain LCEL 版）：检索片段 + 问题 → 流式/非流式回答（带引用）。

EduRAG 手写 JSON prompt + 正则解析被 LCEL 链取代；流式输出直接走 ChatOpenAI 的 .stream()。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from app.llm.models import get_chat_model

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "你是装机参谋 BuildSage，一位 DIY 装机顾问。请严格依据用户提供的「参考片段」回答问题，"
    "不得使用片段之外的知识编造参数或结论。回答正文中引用片段处标注来源编号（如 [1]）。"
    "若参考片段不足以回答问题，请直接说明「未在资料中找到」，不要猜测。"
    "只输出回答正文本身，不要输出 JSON 或任何额外格式。"
)

REJECT_ANSWER = "抱歉，我暂时无法根据当前知识库回答这个问题。您可以尝试换个问法，或补充更多背景信息。"

NOT_FOUND_MARKERS = ("未在资料中找到", "未找到", "找不到", "无法回答", "资料中未")


@dataclass
class GenerationResult:
    answer: str
    citations: list[dict] = field(default_factory=list)
    rejected: bool = False

    def to_dict(self) -> dict:
        return {"answer": self.answer, "citations": self.citations, "rejected": self.rejected}


def _format_refs(contexts: list[Document]) -> str:
    refs = []
    for i, doc in enumerate(contexts, 1):
        meta = doc.metadata or {}
        refs.append(f"[{i}] ({meta.get('doc_name', '')}, {meta.get('title', '')})\n{doc.page_content.strip()}")
    return "\n\n".join(refs) if refs else "（无参考片段）"


def _build_prompt() -> ChatPromptTemplate:
    return ChatPromptTemplate.from_messages(
        [
            ("system", SYSTEM_PROMPT),
            ("human", "参考片段：\n{refs}\n\n{history_block}用户问题：{question}"),
        ]
    )


def _history_block(history: list | None) -> str:
    """多轮历史（LangChain BaseMessage 列表）。"""
    if not history:
        return ""
    lines = []
    for m in history[-6:]:
        role = "用户" if getattr(m, "type", "") == "human" else "助手"
        lines.append(f"{role}: {m.content}")
    return "对话历史：\n" + "\n".join(lines) + "\n\n"


class Generator:
    """LCEL 生成链：prompt | llm | StrOutputParser。"""

    def __init__(self, llm=None) -> None:
        self._llm = llm or get_chat_model()
        self._chain = _build_prompt() | self._llm | StrOutputParser()

    def generate(self, question: str, contexts: list[Document], history: list | None = None) -> GenerationResult:
        answer = self._chain.invoke(
            {"refs": _format_refs(contexts), "history_block": _history_block(history), "question": question}
        ).strip()
        return self._parse(answer, contexts)

    def stream(self, question: str, contexts: list[Document], history: list | None = None):
        """流式产出回答 token；调用方累积后交给 parse。"""
        yield from self._chain.stream(
            {"refs": _format_refs(contexts), "history_block": _history_block(history), "question": question}
        )

    @staticmethod
    def _parse(answer: str, contexts: list[Document]) -> GenerationResult:
        answer = (answer or "").strip()
        not_found = any(marker in answer for marker in NOT_FOUND_MARKERS)
        if not answer or not_found:
            return GenerationResult(answer=answer or REJECT_ANSWER, citations=[], rejected=True)
        citations = [
            {
                "doc_name": (d.metadata or {}).get("doc_name", ""),
                "title": (d.metadata or {}).get("title", ""),
                "text": (d.page_content or "")[:200],
            }
            for d in contexts
        ]
        return GenerationResult(answer=answer, citations=citations, rejected=False)
