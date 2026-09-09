"""会话存储（LangChain 消息版）：多轮历史 + 并发锁。

历史以 LangChain BaseMessage 列表返回（HumanMessage / AIMessage），
供 LCEL prompt 与 LangGraph 状态直接消费。Redis 不可用降级进程内存。
"""
from __future__ import annotations

import json
import logging

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

logger = logging.getLogger(__name__)

HISTORY_MAX_TURNS = 20
HISTORY_TTL_SEC = 1800
LOCK_TTL_SEC = 30


class SessionStore:
    def __init__(self, redis_client=None) -> None:
        self._redis = redis_client
        self._memory: dict[str, list[dict]] = {}
        self._redis_available: bool | None = None

    def _redis_ok(self) -> bool:
        if self._redis_available is not None:
            return self._redis_available
        try:
            if self._redis is None:
                from app.db.redis import get_redis_client

                self._redis = get_redis_client()
            self._redis.ping()
            self._redis_available = True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redis 不可用，会话降级为进程内存: %s", exc)
            self._redis_available = False
        return self._redis_available

    @staticmethod
    def _list_key(session_id: str) -> str:
        return f"qa:list:{session_id}"

    def append(self, session_id: str, question: str, answer: str) -> None:
        entry = json.dumps({"q": question, "a": answer}, ensure_ascii=False)
        if self._redis_ok():
            key = self._list_key(session_id)
            self._redis.rpush(key, entry)
            self._redis.ltrim(key, -HISTORY_MAX_TURNS, -1)
            self._redis.expire(key, HISTORY_TTL_SEC)
        else:
            buf = self._memory.setdefault(session_id, [])
            buf.append({"q": question, "a": answer})
            del buf[: max(0, len(buf) - HISTORY_MAX_TURNS)]

    def get_history(self, session_id: str) -> list[BaseMessage]:
        items: list[dict] = []
        if self._redis_ok():
            raw = self._redis.lrange(self._list_key(session_id), 0, -1)
            for r in raw or []:
                try:
                    items.append(json.loads(r))
                except (json.JSONDecodeError, TypeError):
                    continue
        else:
            items = self._memory.get(session_id, [])
        messages: list[BaseMessage] = []
        for it in items:
            messages.append(HumanMessage(content=it.get("q", "")))
            messages.append(AIMessage(content=it.get("a", "")))
        return messages

    def acquire_lock(self, key: str) -> bool:
        if not self._redis_ok():
            return True
        return bool(self._redis.set(f"qa:lock:{key}", "1", nx=True, ex=LOCK_TTL_SEC))

    def release_lock(self, key: str) -> None:
        if self._redis_ok():
            self._redis.delete(f"qa:lock:{key}")
