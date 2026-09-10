"""BuildSage FastAPI 服务：RAG 问答（REST + SSE）+ 配置器 + 入库 + 统计。

统一响应包 {"code":0,"data":{...},"msg":"ok"}；
错误码：1001 参数错 / 2001 无证据 / 3001 服务内部错 / 4001 文档入库失败。

启动：uvicorn app.api.main:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.deps import (
    get_ingest_service,
    get_knowledge_repository,
    get_session_store,
    get_stats_service,
)
from app.api.schemas import ChatRequest
from app.ingest.service import ALLOWED_TYPES, MAX_FILE_SIZE
from app.rag.pipeline import answer, answer_stream

logger = logging.getLogger(__name__)

# 知识库方向（攻略语料分类）；规格库五类不在其列（直查不依赖分类）
CATEGORIES = ("guide", "cpu", "gpu", "motherboard", "memory", "psu")

app = FastAPI(title="BuildSage 装机参谋 API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _resp(code: int, data, msg: str, status: int = 200) -> JSONResponse:
    return JSONResponse(status_code=status, content={"code": code, "data": data, "msg": msg})


def ok(data) -> JSONResponse:
    return _resp(0, data, "ok")


def fail(code: int, msg: str, status: int = 200) -> JSONResponse:
    return _resp(code, None, msg, status)


def _jsonable(obj):
    """把 Decimal / datetime 等 MySQL 返回值转成 JSON 可序列化类型。"""
    from decimal import Decimal

    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, Decimal):
        return float(obj)
    if hasattr(obj, "isoformat"):
        return obj.isoformat(sep=" ", timespec="seconds")
    return obj


def _validate(req: ChatRequest) -> str | None:
    question = (req.question or "").strip()
    if not question:
        return "问题不能为空"
    if len(question) > 2000:
        return "问题过长（>2000 字符）"
    if req.category and req.category not in CATEGORIES:
        return f"不支持的 category: {req.category}"
    return None


# --- 问答 ---


@app.post("/api/v1/chat")
def chat(req: ChatRequest, session=Depends(get_session_store)):
    err = _validate(req)
    if err:
        return fail(1001, err, 400)
    lock_key = f"{req.category or 'all'}:{req.question}"
    if not session.acquire_lock(lock_key):
        return ok({"intent": "reject", "answer": "同一问题正在处理中，请稍后重试",
                  "citations": [], "strategy": "", "latency_ms": 0, "busy": True})
    try:
        history = session.get_history(req.session_id) if req.session_id else []
        result = answer(req.question, category=req.category, session_id=req.session_id, history=history)
        if req.session_id:
            session.append(req.session_id, req.question, result.get("answer", ""))
        _record_log(req, result)
        return ok(result)
    except Exception as exc:  # noqa: BLE001
        logger.exception("chat 接口异常")
        return fail(3001, f"服务内部错误: {exc}", 500)
    finally:
        session.release_lock(lock_key)


@app.post("/api/v1/chat/stream")
def chat_stream(req: ChatRequest, session=Depends(get_session_store)):
    err = _validate(req)
    if err:
        return fail(1001, err, 400)

    def gen():
        answer_text = ""
        intent = strategy = ""
        latency_ms = 0
        cache_hit = False
        rejected = False
        try:
            history = session.get_history(req.session_id) if req.session_id else []
            for event in answer_stream(req.question, category=req.category, session_id=req.session_id, history=history):
                etype = event.get("type")
                if etype == "token":
                    answer_text += event.get("content", "")
                elif etype == "route":
                    intent = event.get("intent", "")
                    strategy = event.get("strategy", "")
                elif etype == "done":
                    latency_ms = event.get("latency_ms", 0)
                    cache_hit = bool(event.get("cache_hit"))
                    rejected = bool(event.get("rejected"))
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            if req.session_id:
                session.append(req.session_id, req.question, answer_text)
            _record_log(req, {
                "intent": intent, "strategy": strategy, "answer": answer_text,
                "latency_ms": latency_ms, "cache_hit": cache_hit, "rejected": rejected,
                "evidence_ids": [],
            })
        except Exception as exc:  # noqa: BLE001
            logger.exception("stream 接口异常")
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _record_log(req: ChatRequest, result: dict) -> None:
    try:
        from app.api.deps import get_qa_log

        get_qa_log().insert_log(
            session_id=req.session_id or "",
            question=req.question,
            intent=result.get("intent", ""),
            strategy=result.get("strategy", ""),
            route_detail=result.get("route_detail", {}),
            evidence_ids=result.get("evidence_ids", []),
            answer=result.get("answer", ""),
            latency_ms=result.get("latency_ms", 0),
            cache_hit=result.get("cache_hit", False),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("qa_log 写入失败: %s", exc)


# --- 文档入库 / 检索 ---


@app.post("/api/v1/ingest")
async def ingest(file: UploadFile = File(...), category: str = Form(...), svc=Depends(get_ingest_service)):
    if category not in CATEGORIES:
        return fail(4001, f"不支持的 category: {category}", 400)
    suffix = Path(file.filename or "").suffix.lstrip(".").lower()
    if suffix not in ALLOWED_TYPES:
        return fail(4001, f"不支持的文件类型: {suffix or '未知'}", 400)

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        return fail(4001, f"文件超过大小限制 {MAX_FILE_SIZE // 1024 // 1024}MB", 400)

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{suffix}") as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)
        result = svc.ingest_file(tmp_path, category, file_name=file.filename)
        return ok(result)
    except Exception as exc:  # noqa: BLE001
        logger.exception("ingest 接口异常")
        return fail(4001, f"入库失败: {exc}", 400)
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


@app.get("/api/v1/sources")
def sources(category: str | None = None, repo=Depends(get_knowledge_repository)):
    try:
        docs = repo.list_documents(category or None)
        return ok({"documents": _jsonable(docs), "count": len(docs)})
    except Exception as exc:  # noqa: BLE001
        logger.exception("sources 接口异常")
        return fail(3001, f"服务内部错误: {exc}", 500)


@app.delete("/api/v1/sources/{doc_id}")
def delete_source(doc_id: int, svc=Depends(get_ingest_service), repo=Depends(get_knowledge_repository)):
    try:
        category = None
        docs = repo.list_documents()
        category = next((d.get("category") for d in docs if d.get("doc_id") == doc_id), None)
        svc.delete_document(doc_id, category=category)
        return ok({"deleted": doc_id})
    except Exception as exc:  # noqa: BLE001
        logger.exception("delete source 接口异常")
        return fail(3001, f"删除失败: {exc}", 500)


# --- 规格库 ---


@app.get("/api/v1/specs")
def specs(category: str, q: str = "", limit: int = 50):
    if category not in ("cpu", "gpu", "motherboard", "memory", "psu", "cooler", "case"):
        return fail(1001, f"不支持的 category: {category}", 400)
    try:
        from app.api.deps import get_spec_repository

        rows = get_spec_repository().search(category, q, limit=limit) if q else get_spec_repository().search_all(category, limit=limit)
        return ok({"items": _jsonable(rows), "count": len(rows)})
    except Exception as exc:  # noqa: BLE001
        logger.exception("specs 接口异常")
        return fail(3001, f"服务内部错误: {exc}", 500)


# --- 统计 / 健康 ---


@app.get("/api/v1/stats")
def stats(days: int = 7, svc=Depends(get_stats_service)):
    try:
        return ok(svc.get_stats(days=days))
    except Exception as exc:  # noqa: BLE001
        logger.exception("stats 接口异常")
        return fail(3001, f"服务内部错误: {exc}", 500)


@app.get("/api/v1/health")
def health():
    checks = {
        "mysql": _check_mysql(),
        "redis": _check_redis(),
        "vector_store": _check_vector(),
        "llm": _check_llm(),
        "specs": _check_specs(),
    }
    return ok(checks)


def _check_mysql() -> bool:
    try:
        from sqlalchemy import text

        from app.db.mysql import get_engine

        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001
        return False


def _check_redis() -> bool:
    try:
        from app.db.redis import get_redis_client

        return bool(get_redis_client().ping())
    except Exception:  # noqa: BLE001
        return False


def _check_vector() -> bool:
    try:
        from app.ingest.pipeline import get_vectorstore

        return get_vectorstore()._collection.count() >= 0
    except Exception:  # noqa: BLE001
        return False


def _check_llm() -> bool:
    try:
        from app.llm.models import get_chat_model

        get_chat_model()
        return True
    except Exception:  # noqa: BLE001
        return False


def _check_specs() -> dict:
    try:
        from app.api.deps import get_spec_repository

        return get_spec_repository().count()
    except Exception:  # noqa: BLE001
        return {}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.api.main:app", host="127.0.0.1", port=8000, reload=True)
