"""FastAPI 依赖：应用服务单例（懒加载，避免启动即连模型/DB）。"""
from __future__ import annotations

from functools import lru_cache

from app.db.qa_log_repository import QALogRepository
from app.ingest.repository import KnowledgeRepository
from app.ingest.service import IngestService
from app.rag.session import SessionStore
from app.specs.repository import SpecRepository

from app.api.stats import StatsService


@lru_cache
def _session_store() -> SessionStore:
    return SessionStore()


@lru_cache
def _qa_log() -> QALogRepository:
    return QALogRepository()


@lru_cache
def _ingest_service() -> IngestService:
    return IngestService()


@lru_cache
def _knowledge_repository() -> KnowledgeRepository:
    return KnowledgeRepository()


@lru_cache
def _spec_repository() -> SpecRepository:
    return SpecRepository()


@lru_cache
def _stats_service() -> StatsService:
    return StatsService(session_store=_session_store())


def get_qa_log() -> QALogRepository:
    return _qa_log()


def get_session_store() -> SessionStore:
    return _session_store()


def get_ingest_service() -> IngestService:
    return _ingest_service()


def get_knowledge_repository() -> KnowledgeRepository:
    return _knowledge_repository()


def get_spec_repository() -> SpecRepository:
    return _spec_repository()


def get_stats_service() -> StatsService:
    return _stats_service()
