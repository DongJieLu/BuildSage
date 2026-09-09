"""统计聚合：意图分布 / 策略分布 / 平均延迟 / 热点问题（qa_log + 规格库规模）。"""
from __future__ import annotations

from app.db.qa_log_repository import QALogRepository
from app.specs.repository import SpecRepository


class StatsService:
    def __init__(self, qa_log=None, spec_repo=None, session_store=None) -> None:
        self._qa_log = qa_log or QALogRepository()
        self._specs = spec_repo or SpecRepository()
        self._session = session_store

    def get_stats(self, days: int = 7) -> dict:
        base = self._qa_log.stats(days)
        try:
            spec_scale = self._specs.count()
        except Exception:  # noqa: BLE001
            spec_scale = {}
        # 热点问题：近 N 天按 question 聚合 Top10
        hot = self._qa_log.hot_questions(10) if hasattr(self._qa_log, "hot_questions") else []
        return {
            "days": days,
            "total": base["total"],
            "intent_distribution": base["intent_distribution"],
            "strategy_distribution": base["strategy_distribution"],
            "avg_latency_ms": base["avg_latency_ms"],
            "daily": base["daily"],
            "hot_questions": hot,
            "spec_scale": spec_scale,
        }
