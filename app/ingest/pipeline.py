"""LangChain 入库管线：loaders → splitters → HuggingFaceEmbeddings → Chroma。

与 EduRAG 手写 parser/chunker 的区别：文档解析与切分全部使用 LangChain 标准组件——
- Markdown 攻略按标题层级切分（MarkdownHeaderTextSplitter，保留标题链 metadata），
  再用 RecursiveCharacterTextSplitter 控制块长；
- PDF/DOCX/TXT 直接递归字符切分；
- 向量化用 langchain-huggingface 的 HuggingFaceEmbeddings（BAAI/bge-m3，1024 维）；
- 向量库用 langchain-chroma（开发期，schema 对齐 Milvus 便于迁移）。
"""
from __future__ import annotations

import uuid
from functools import lru_cache
from pathlib import Path

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)

from app.config import get_settings

COLLECTION_NAME = "buildsage_guides"

CHUNK_SIZE = 500
CHUNK_OVERLAP = 80
MIN_CHUNK_LEN = 20

_HEADERS_TO_SPLIT_ON = [("#", "h1"), ("##", "h2"), ("###", "h3")]


@lru_cache
def get_embeddings() -> HuggingFaceEmbeddings:
    """BGE-M3 嵌入模型（本地加载，normalize 后入库，与规格库检索共用）。"""
    return HuggingFaceEmbeddings(
        model_name=get_settings().embed_model_name,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )


@lru_cache
def get_vectorstore() -> Chroma:
    return Chroma(
        collection_name=COLLECTION_NAME,
        persist_directory=str(get_settings().chroma_persist_dir),
        embedding_function=get_embeddings(),
    )


def load_document(file_path: Path, file_type: str) -> list[Document]:
    """按文件类型选择 LangChain loader。"""
    if file_type in ("md", "markdown", "txt"):
        from langchain_community.document_loaders import TextLoader

        return TextLoader(str(file_path), encoding="utf-8").load()
    if file_type == "pdf":
        from langchain_community.document_loaders import PyPDFLoader

        return PyPDFLoader(str(file_path)).load()  # 每页一个 Document，metadata 带 page
    if file_type == "docx":
        from langchain_community.document_loaders import Docx2txtLoader

        return Docx2txtLoader(str(file_path)).load()
    raise ValueError(f"不支持的文件类型: {file_type}")


def split_documents(documents: list[Document], file_type: str) -> list[Document]:
    """Markdown 按标题切分保留标题链；其余递归字符切分。"""
    recursive = RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
    if file_type in ("md", "markdown"):
        header_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=_HEADERS_TO_SPLIT_ON, strip_headers=False)
        chunks: list[Document] = []
        for doc in documents:
            sections = header_splitter.split_text(doc.page_content)
            for sec in sections:
                sec.metadata = {**doc.metadata, **sec.metadata}  # 保留来源文件信息
            chunks.extend(recursive.split_documents(sections))
        return chunks
    return recursive.split_documents(documents)


def _clean_title(meta: dict) -> str:
    """标题链取最末级，供引用溯源展示。"""
    return meta.get("h3") or meta.get("h2") or meta.get("h1") or ""


class IngestPipeline:
    """文件 → Document 切分 → 向量化入库（Chroma）+ 元数据落库（MySQL）。"""

    def __init__(self, vectorstore=None, repository=None, embeddings=None) -> None:
        self._vectorstore = vectorstore
        self._repository = repository
        self._embeddings = embeddings

    def _get_vectorstore(self) -> Chroma:
        if self._vectorstore is None:
            self._vectorstore = get_vectorstore()
        return self._vectorstore

    def _get_repository(self):
        if self._repository is None:
            from app.ingest.repository import KnowledgeRepository

            self._repository = KnowledgeRepository()
        return self._repository

    def split_file(self, file_path: Path, file_type: str) -> list[Document]:
        documents = load_document(file_path, file_type)
        chunks = [c for c in split_documents(documents, file_type) if len(c.page_content.strip()) >= MIN_CHUNK_LEN]
        return chunks

    def ingest_file(self, file_path: Path, category: str, file_name: str | None = None) -> dict:
        """入库单个文档，返回 {"doc_id", "chunk_count"}。向量与元数据同批写入。"""
        file_path = Path(file_path)
        file_type = file_path.suffix.lstrip(".").lower()
        name = file_name or file_path.name
        chunks = self.split_file(file_path, file_type)
        if not chunks:
            raise ValueError("文档未提取到有效内容")

        doc_id = self._get_repository().insert_document(name, category, file_type)
        ids, metadatas, texts = [], [], []
        for chunk in chunks:
            vector_id = uuid.uuid4().hex
            chunk_id = self._get_repository().insert_chunk(
                doc_id=doc_id,
                doc_name=name,
                category=category,
                title=_clean_title(chunk.metadata),
                page_no=chunk.metadata.get("page"),
                chunk_text=chunk.page_content,
                milvus_id=vector_id,  # 复用 milvus_id 列存向量库 id（schema 对齐迁移）
            )
            ids.append(vector_id)
            texts.append(chunk.page_content)
            metadatas.append(
                {
                    "chunk_id": chunk_id,
                    "doc_id": doc_id,
                    "doc_name": name,
                    "category": category,
                    "title": _clean_title(chunk.metadata),
                    "page_no": chunk.metadata.get("page") or 0,  # Chroma metadata 不接受 None
                }
            )
        self._get_vectorstore().add_documents(
            documents=[Document(page_content=t, metadata=m) for t, m in zip(texts, metadatas)],
            ids=ids,
        )
        self._get_repository().update_doc_chunk_count(doc_id, len(chunks))
        return {"doc_id": doc_id, "chunk_count": len(chunks)}

    def delete_document(self, doc_id: int) -> None:
        """删除文档向量（MySQL 元数据删除由调用方完成）。"""
        self._get_vectorstore()._collection.delete(where={"doc_id": doc_id})
