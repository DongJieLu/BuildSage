"""bge-reranker-large 适配器（langchain-huggingface 1.x 移除了 HuggingFaceCrossEncoder）。

实现 langchain_classic 的 BaseCrossEncoder 接口（score(text_pairs)），
包一层 sentence-transformers 的 CrossEncoder，即可接入标准组件
CrossEncoderReranker + ContextualCompressionRetriever 精排管道。
"""
from __future__ import annotations

import numpy as np
from langchain_classic.retrievers.document_compressors.cross_encoder_rerank import BaseCrossEncoder

from app.config import get_settings


class BGEReranker(BaseCrossEncoder):
    """CrossEncoder 适配器：sigmoid 归一化到 0~1，便于与阈值比较。"""

    def __init__(self, model_name: str | None = None) -> None:
        from sentence_transformers import CrossEncoder

        self._model = CrossEncoder(model_name or get_settings().rerank_model_name)

    def score(self, text_pairs: list[tuple[str, str]]) -> list[float]:
        if not text_pairs:
            return []
        raw = np.asarray(self._model.predict(list(text_pairs)), dtype="float32")
        probs = 1.0 / (1.0 + np.exp(-raw))
        return [float(p) for p in probs]
