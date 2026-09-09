"""LLM 封装（LangChain 版）：ChatOpenAI 走 DeepSeek 兼容接口，缺 key 自动降级 FakeLLM。

EduRAG 手写 BaseLLM/openai SDK 封装被 langchain-openai 的 ChatOpenAI 取代；
MockLLM 由 langchain_core.language_models.fake 的 FakeListLLM / FakeMessagesListChatModel 充当。
"""
from __future__ import annotations

from functools import lru_cache

from langchain_core.language_models.chat_models import BaseChatModel


@lru_cache
def get_chat_model() -> BaseChatModel:
    """返回项目唯一的 LLM 实例（DeepSeek 兼容接口；无 key 时降级 FakeListLLM）。"""
    from app.config import get_settings

    settings = get_settings()
    if settings.llm_provider != "deepseek" or not settings.deepseek_api_key:
        from langchain_core.language_models import FakeListChatModel

        return FakeListChatModel(
            responses=[
                '{"intent":"rag","confidence":0.5,"reason":"LLM 不可用，默认 RAG"}',
                '{"strategy":"direct","queries":[],"reason":"LLM 不可用，默认 direct"}',
            ],
            sleep=None,
        )
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=settings.deepseek_model,
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        temperature=0,
        timeout=settings.llm_timeout_sec,
    )
