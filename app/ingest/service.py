"""入库编排：LangChain 管线（loaders/splitters/向量化）+ MySQL 元数据，支持增量（先删后插）。

P2 起文档解析/切分/向量化由 app.ingest.pipeline（LangChain 标准组件）承担，
本模块负责文件校验、编排与缓存失效。
"""
from __future__ import annotations

import logging
from pathlib import Path

from app.ingest.pipeline import IngestPipeline

logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 20 * 1024 * 1024  # 单文件 ≤ 20MB
ALLOWED_TYPES = {"pdf", "docx", "txt", "md", "markdown"}


class IngestService:
    def __init__(self, pipeline: IngestPipeline | None = None) -> None:
        self._pipeline = pipeline or IngestPipeline()

    def ingest_file(self, file_path: Path, category: str, file_name: str | None = None) -> dict:
        """入库单个文档，返回 {"doc_id", "chunk_count"}。"""
        file_path = Path(file_path)
        file_type = file_path.suffix.lstrip(".").lower()
        if file_type not in ALLOWED_TYPES:
            raise ValueError(f"不支持的文件类型: {file_type}")
        if file_path.stat().st_size > MAX_FILE_SIZE:
            raise ValueError(f"文件超过大小限制 {MAX_FILE_SIZE // 1024 // 1024}MB")

        result = self._pipeline.ingest_file(file_path, category, file_name=file_name)
        self._invalidate_cache(category)
        return result

    def delete_document(self, doc_id: int, category: str | None = None) -> None:
        """删除文档（MySQL chunks + doc 标记删除 + Chroma 向量）。"""
        from app.ingest.repository import KnowledgeRepository

        milvus_ids = KnowledgeRepository().delete_document(doc_id)
        if milvus_ids:
            self._pipeline.delete_document(doc_id)
        if category:
            self._invalidate_cache(category)

    def _invalidate_cache(self, category: str | None) -> None:
        """文档更新后清理该方向的答案缓存。"""
        try:
            from app.rag.cache import AnswerCache

            AnswerCache().invalidate_category(category)
        except Exception as exc:  # noqa: BLE001
            logger.warning("答案缓存清理失败: %s", exc)
