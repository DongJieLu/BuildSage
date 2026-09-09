"""LangGraph 管道：BuildSage 四通道编排（确定性管道，非自主循环）。

router_node（L1 规则 + L2 LLM 分类）→ param / compat / rag / reject 四个并行出口之一
→ 共享出口（缓存写入 + qa_log 落库）。

设计要点（面试叙事）：
- 这是"确定性管道"：每个节点单一职责、无循环、无 LLM 自主决策工具调用；
  参数与兼容性是规则可枚举的确定性问题，交给 Agent 循环只会引入幻觉与延迟
  （与另一个 LangGraph 自主 Agent 项目形成"同一框架两种用法"的对比）。
- state 用 TypedDict，LangGraph 的 Reducer 语义保证节点只更新自己负责的键。
"""
from __future__ import annotations

import logging
import time
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.rag.cache import AnswerCache
from app.rag.generator import REJECT_ANSWER, Generator
from app.rag.retriever import retrieve
from app.rag.router import Router
from app.specs.extractor import extract_config, extract_slots
from app.specs.repository import SpecRepository
from app.specs.rules import check_compat, verdict

logger = logging.getLogger(__name__)

MIN_EVIDENCE_COUNT = 1   # 检索文档数低于此值视为无证据，拒答

# 展示字段的中文名（param 通道卡片用）
FIELD_LABELS = {
    "tdp_w": "TDP", "tdp_max_w": "最大睿频功耗", "vram_gb": "显存容量", "vram_type": "显存类型",
    "socket": "插槽", "cores": "核心", "threads": "线程", "boost_ghz": "最大频率",
    "memory_types": "支持内存", "pcie_gen": "PCIe 世代", "rated_w": "额定功率",
    "certification": "认证", "modularity": "模组化", "capacity_gb": "容量", "speed_mhz": "频率",
    "chipset": "芯片组", "form_factor": "板型", "length_mm": "长度", "release_year": "发布年份",
    "price_usd": "参考价", "msrp_usd": "首发价", "passmark_g3d": "G3D 分数", "passmark_cpu_mark": "CPU 分数",
}


class PipelineState(TypedDict, total=False):
    question: str
    category: str | None
    session_id: str | None
    history: list
    start_ts: float
    cached: dict | None          # 命中缓存时的完整结果
    route: dict                  # 路由决策
    result: dict                  # 最终输出（answer/citations/...）
    events: list                  # SSE 过程事件（route/progress）


def _now_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def build_graph(
    router: Router | None = None,
    generator: Generator | None = None,
    spec_repo: SpecRepository | None = None,
    cache: AnswerCache | None = None,
):
    router = router or Router()
    generator = generator or Generator()
    spec_repo = spec_repo or SpecRepository()
    cache = cache or AnswerCache()

    # --- 节点 ---

    def cache_node(state: PipelineState) -> dict:
        cached = cache.get(state["question"], state.get("category"))
        if cached is not None:
            return {"cached": cached}
        return {}

    def router_node(state: PipelineState) -> dict:
        route = router.route(state["question"], state.get("history"))
        return {"route": route}

    def param_node(state: PipelineState) -> dict:
        slots = extract_slots(state["question"])
        events = [{"type": "progress", "stage": "slot_extraction", "detail": slots.model_name or slots.category}]
        if not slots.model_name and not slots.category:
            return _result(state, answer="未能识别您询问的硬件型号，请补充型号信息（如 RTX 4070、i9-14900K）。",
                           intent="param", strategy="slot-miss", events=events, rejected=True)
        row = spec_repo.best_match(slots.category or _guess_category(slots.model_name), slots.model_name)
        if row is None:
            return _result(state, answer=f"规格库中暂未收录「{slots.model_name}」，无法提供参数。",
                           intent="param", strategy="no-match", events=events, rejected=True)
        fields = slots.fields or [k for k in ("tdp_w", "vram_gb", "socket", "rated_w", "capacity_gb") if row.get(k)]
        card_lines = [f"**{row['name']}**"]
        for f in fields:
            if row.get(f) is not None:
                card_lines.append(f"- {FIELD_LABELS.get(f, f)}: {row[f]}")
        answer = "\n".join(card_lines)
        return _result(state, answer=answer, intent="param", strategy="direct-sql",
                       events=events, evidence_ids=[_spec_id(slots.category or _guess_category(slots.model_name), row)])

    def compat_node(state: PipelineState) -> dict:
        cfg = extract_config(state["question"], state.get("history"))
        events = [{"type": "progress", "stage": "config_extraction",
                   "detail": " ".join(filter(None, [cfg.cpu, cfg.gpu, cfg.motherboard, cfg.memory, cfg.psu]))}]
        parts: list[dict] = []
        specs: dict[str, dict | None] = {}
        for cat, name in (("cpu", cfg.cpu), ("gpu", cfg.gpu), ("motherboard", cfg.motherboard),
                          ("memory", cfg.memory), ("psu", cfg.psu)):
            if not name:
                specs[cat] = None
                continue
            if cat == "memory":
                mem_type = "DDR5" if "ddr5" in name.lower() else ("DDR4" if "ddr4" in name.lower() else "")
                specs[cat] = {"name": name, "mem_type": mem_type} if mem_type else spec_repo.best_match("memory", name)
            elif cat == "psu" and name.rstrip("Ww").isdigit():
                specs[cat] = {"name": name, "rated_w": int(name.rstrip("Ww"))}
            else:
                specs[cat] = spec_repo.best_match(cat, name)
        if not any(specs.values()):
            return _result(state, answer="未能识别配置清单中的硬件型号，请补充具体型号。",
                           intent="compat", strategy="config-miss", events=events, rejected=True)
        results = check_compat(
            cpu=specs.get("cpu"), motherboard=specs.get("motherboard"), memory=specs.get("memory"),
            gpu=specs.get("gpu"), psu=specs.get("psu"), case_limit_mm=cfg.case_limit_mm,
        )
        lines = []
        for r in results:
            icon = {"pass": "✅", "conflict": "❌", "warn": "💡", "skip": "➖"}[r.status]
            lines.append(f"{icon} {r.rule_id} {r.message}")
        v = verdict(results)
        lines.append({
            "pass": "**结论：配置兼容，可以放心装机。**",
            "warn": "**结论：可用，但存在提示项（见 💡 标注）。**",
            "conflict": "**结论：存在冲突，请按 ❌ 项调整配置。**",
        }[v])
        answer = "\n".join(lines)
        return _result(state, answer=answer, intent="compat", strategy="rules-engine", events=events,
                       evidence_ids=[r.rule_id for r in results])

    def rag_node(state: PipelineState) -> dict:
        events = [{"type": "progress", "stage": "retrieval", "detail": "混合检索 + 重排"}]
        docs = retrieve(state["question"], category=state.get("category"), top_k=5)
        if len(docs) < MIN_EVIDENCE_COUNT:
            return _result(state, answer=REJECT_ANSWER, intent="rag", strategy="no-evidence",
                           events=events, rejected=True)
        gen = generator.generate(state["question"], docs, history=state.get("history"))
        return _result(state, answer=gen.answer, intent="rag", strategy="hybrid+rerank", events=events,
                       citations=gen.citations, rejected=gen.rejected,
                       evidence_ids=[(d.metadata or {}).get("chunk_id") for d in docs if d.metadata])

    def reject_node(state: PipelineState) -> dict:
        return _result(state, answer=REJECT_ANSWER, intent="reject", strategy="", events=[], rejected=True)

    # --- 工具 ---

    def _result(state: PipelineState, answer: str, intent: str, strategy: str, events: list,
                citations: list | None = None, rejected: bool = False,
                evidence_ids: list | None = None) -> dict:
        result = {
            "intent": intent, "strategy": strategy, "answer": answer,
            "citations": citations or [], "rejected": rejected,
            "evidence_ids": evidence_ids or [],
            "latency_ms": _now_ms(state["start_ts"]),
        }
        cache.set(state["question"], state.get("category"), result, rejected=rejected)
        return {"result": result, "events": events}

    def _guess_category(model_name: str) -> str:
        import re

        n = model_name.lower()
        if re.search(r"(rtx|gtx|radeon|rx\s?\d{3,4})", n):
            return "gpu"
        if re.search(r"(i[3579]-\d|ryzen|ultra\s?\d)", n):
            return "cpu"
        if re.search(r"(ddr|内存)", n):
            return "memory"
        if re.search(r"(\d{3,4}w|电源|psu)", n):
            return "psu"
        return "motherboard"

    def _spec_id(category: str, row: dict) -> str:
        id_col = {"cpu": "cpu_id", "gpu": "gpu_id", "motherboard": "mb_id", "memory": "mem_id", "psu": "psu_id"}
        return f"{category}:{row.get(id_col.get(category, 'cpu_id'), '')}"

    # --- 组图 ---

    g = StateGraph(PipelineState)
    g.add_node("cache", cache_node)
    g.add_node("router", router_node)
    g.add_node("param", param_node)
    g.add_node("compat", compat_node)
    g.add_node("rag", rag_node)
    g.add_node("reject", reject_node)
    g.add_edge(START, "cache")
    # 缓存命中直接结束；未命中先过路由（route 键由 router_node 写入后才可读）
    g.add_conditional_edges("cache", lambda s: "hit" if s.get("cached") is not None else "miss",
                            {"hit": END, "miss": "router"})
    g.add_conditional_edges("router", lambda s: s["route"]["intent"],
                            {"param": "param", "compat": "compat", "rag": "rag", "reject": "reject"})
    for node in ("param", "compat", "rag", "reject"):
        g.add_edge(node, END)
    return g.compile()


# 模块级单例（编译一次）
_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


def answer(question: str, category: str | None = None, session_id: str | None = None,
           history: list | None = None) -> dict:
    """同步问答入口（非流式）。"""
    state: PipelineState = {
        "question": question,
        "category": category,
        "session_id": session_id,
        "history": history or [],
        "start_ts": time.perf_counter(),
    }
    final = get_graph().invoke(state)
    if final.get("cached") is not None:
        out = dict(final["cached"])
        out["cache_hit"] = True
        return out
    out = dict(final["result"])
    out["cache_hit"] = False
    return out


def answer_stream(question: str, category: str | None = None, session_id: str | None = None,
                  history: list | None = None):
    """SSE 事件流入口：route / progress / token / citation / done。

    LangGraph 同步图没有流式 token 透传，这里对 rag 通道在图外做流式生成
    （缓存/路由/检索仍走图，保证链路一致）。
    """
    start = time.perf_counter()
    cache = AnswerCache()
    cached = cache.get(question, category)
    if cached is not None:
        yield {"type": "route", "intent": cached.get("intent", "rag"), "strategy": cached.get("strategy", "")}
        yield {"type": "token", "content": cached.get("answer", "")}
        yield {"type": "citation", "citations": cached.get("citations", [])}
        yield {"type": "done", "latency_ms": _now_ms(start), "rejected": cached.get("rejected", False), "cache_hit": True}
        return

    router = Router()
    route = router.route(question, history)
    intent = route["intent"]
    yield {"type": "route", "intent": intent, "strategy": ""}

    if intent == "reject":
        yield {"type": "token", "content": REJECT_ANSWER}
        yield {"type": "citation", "citations": []}
        result = {"intent": "reject", "answer": REJECT_ANSWER, "citations": [], "rejected": True,
                  "strategy": "", "evidence_ids": [], "latency_ms": _now_ms(start)}
        cache.set(question, category, result, rejected=True)
        yield {"type": "done", "latency_ms": _now_ms(start), "rejected": True, "cache_hit": False}
        return

    if intent == "param":
        yield {"type": "progress", "stage": "slot_extraction"}
        out = answer(question, category, session_id, history)
        for ev in out.get("events", []) or []:
            yield ev
        yield {"type": "token", "content": out["answer"]}
        yield {"type": "citation", "citations": out.get("citations", [])}
        yield {"type": "done", "latency_ms": out["latency_ms"], "rejected": out.get("rejected", False), "cache_hit": False}
        return

    if intent == "compat":
        yield {"type": "progress", "stage": "config_extraction"}
        out = answer(question, category, session_id, history)
        yield {"type": "token", "content": out["answer"]}
        yield {"type": "citation", "citations": []}
        yield {"type": "done", "latency_ms": out["latency_ms"], "rejected": out.get("rejected", False), "cache_hit": False}
        return

    # rag：图外流式（检索 → 逐 token 生成）
    yield {"type": "progress", "stage": "retrieval"}
    docs = retrieve(question, category=category, top_k=5)
    if len(docs) < MIN_EVIDENCE_COUNT:
        yield {"type": "token", "content": REJECT_ANSWER}
        yield {"type": "citation", "citations": []}
        result = {"intent": "rag", "answer": REJECT_ANSWER, "citations": [], "rejected": True,
                  "strategy": "no-evidence", "evidence_ids": [], "latency_ms": _now_ms(start)}
        cache.set(question, category, result, rejected=True)
        yield {"type": "done", "latency_ms": _now_ms(start), "rejected": True, "cache_hit": False}
        return
    generator = Generator()
    buf = []
    for token in generator.stream(question, docs, history=history):
        buf.append(token)
        yield {"type": "token", "content": token}
    gen = Generator._parse("".join(buf), docs)
    result = {
        "intent": "rag", "answer": gen.answer, "citations": gen.citations,
        "rejected": gen.rejected, "strategy": "hybrid+rerank",
        "evidence_ids": [(d.metadata or {}).get("chunk_id") for d in docs if d.metadata],
        "latency_ms": _now_ms(start),
    }
    cache.set(question, category, result, rejected=gen.rejected)
    yield {"type": "citation", "citations": gen.citations}
    yield {"type": "done", "latency_ms": result["latency_ms"], "rejected": gen.rejected, "cache_hit": False}
