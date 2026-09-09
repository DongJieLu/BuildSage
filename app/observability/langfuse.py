"""可观测性：Langfuse 全链路追踪（可选，无密钥时静默降级为 no-op）。

支持两种部署（由环境变量决定）：
- Langfuse Cloud：填 LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_HOST（默认云）
- 自托管：docker compose --profile langfuse up（见 docker-compose.yml 注释块）

接入方式：LangChain CallbackHandler 挂到 LCEL 链与 LangGraph invoke，
自动捕获路由 LLM 调用、检索、生成每一步的输入输出与耗时。
"""
from __future__ import annotations

import logging
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)


def get_langfuse_handler() -> Any | None:
    """返回 Langfuse CallbackHandler；未配置密钥时返回 None（降级为无追踪）。"""
    settings = get_settings()
    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        return None
    try:
        from langfuse.langchain import CallbackHandler

        return CallbackHandler()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Langfuse 初始化失败，本次请求不追踪: %s", exc)
        return None


def with_observability(config: dict | None = None) -> dict:
    """把 Langfuse handler 注入 LangChain/LangGraph 的 config（callbacks）。"""
    cfg = dict(config or {})
    handler = get_langfuse_handler()
    if handler is not None:
        cfg.setdefault("callbacks", [])
        if isinstance(cfg["callbacks"], list):
            cfg["callbacks"].append(handler)
    return cfg
