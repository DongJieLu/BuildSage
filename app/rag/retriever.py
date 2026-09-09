"""混合检索器（LangChain 版）：BM25 + 向量 → EnsembleRetriever（RRF 融合）→ 重排。

EduRAG 的手写三件（向量召回 / MySQL 关键词召回 / 手写 RRF）被标准组件取代：
- BM25Retriever：稀疏召回（无需 MySQL 全表扫描，进程内存索引）
- vectorstore.as_retriever()：稠密召回（BGE-M3 + Chroma）
- EnsembleRetriever：RRF 排名融合（只看排名不看原始分数量纲）
- ContextualCompressionRetriever + CrossEncoderReranker：bge-reranker 精排
"""
from __future__ import annotations

import logging
from functools import lru_cache

from langchain_community.retrievers import BM25Retriever
from langchain_classic.retrievers import EnsembleRetriever, ContextualCompressionRetriever
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever

from app.ingest.repository import KnowledgeRepository
from app.ingest.pipeline import get_vectorstore

logger = logging.getLogger(__name__)

TOP_K_RECALL = 20  # 召回 20 条交重排（CPU 环境 CrossEncoder 成本高，20→5 是精度/延迟折中）


def _all_chunks(category: str | None = None) -> list[Document]:
    """从 MySQL 读全部 chunk 构建 BM25 索引（含 category 过滤）。"""
    try:
        rows = KnowledgeRepository().list_chunks(category)
    except Exception as exc:  # noqa: BLE001
        logger.warning("BM25 索引构建读取 MySQL 失败: %s", exc)
        return []
    return [
        Document(
            page_content=r["chunk_text"],
            metadata={
                "chunk_id": r["chunk_id"],
                "doc_id": r["doc_id"],
                "doc_name": r["doc_name"],
                "category": r["category"],
                "title": r["title"] or "",
                "page_no": r["page_no"] or 0,
            },
        )
        for r in rows
    ]


@lru_cache(maxsize=16)
def _bm25_retriever(category: str | None) -> BM25Retriever | None:
    docs = _all_chunks(category)
    if not docs:
        return None
    return BM25Retriever.from_documents(docs, k=TOP_K_RECALL)


@lru_cache(maxsize=16)
def _vector_retriever(category: str | None) -> BaseRetriever:
    vs = get_vectorstore()
    if category:
        return vs.as_retriever(search_kwargs={"k": TOP_K_RECALL, "filter": {"category": category}})
    return vs.as_retriever(search_kwargs={"k": TOP_K_RECALL})


@lru_cache(maxsize=1)
def _reranker_compressor():
    """bge-reranker-large 精排压缩器（本地加载失败返回 None，降级为融合结果）。"""
    try:
        from langchain_classic.retrievers.document_compressors import CrossEncoderReranker

        from app.rerank.bge_rerank import BGEReranker

        return CrossEncoderReranker(model=BGEReranker(), top_n=5)
    except Exception as exc:  # noqa: BLE001
        logger.warning("重排模型加载失败，降级为 RRF 融合结果: %s", exc)
        return None


def get_hybrid_retriever(category: str | None = None) -> BaseRetriever:
    """按方向构建（或复用）混合检索器：Ensemble(BM25+向量)。"""
    bm25 = _bm25_retriever(category)
    vec = _vector_retriever(category)
    if bm25 is None:
        return vec
    return EnsembleRetriever(retrievers=[bm25, vec], k=TOP_K_RECALL, id_key="chunk_id")


def retrieve(query: str, category: str | None = None, top_k: int = 5, rerank: bool = True) -> list[Document]:
    """一站式检索入口：混合召回 →（可选）重排精筛，返回 Top-K 文档。"""
    hybrid = get_hybrid_retriever(category)
    compressor = _reranker_compressor() if rerank else None
    if compressor is not None:
        retriever = ContextualCompressionRetriever(base_compressor=compressor, base_retriever=hybrid)
    else:
        retriever = hybrid
    docs = retriever.invoke(query)
    return docs[:top_k]


def invalidate_retriever_cache(category: str | None = None) -> None:
    """文档增删后重建 BM25 / 检索器缓存。"""
    _bm25_retriever.cache_clear()
    _vector_retriever.cache_clear()
