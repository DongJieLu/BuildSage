"""LangGraph 管道单测：reject 通道（不依赖 LLM/DB）与图结构。"""
from app.rag.pipeline import PipelineState, build_graph


def test_reject_channel_end_to_end():
    """寒暄问题走 L1 规则直接 reject，FakeLLM 不被调用。"""
    graph = build_graph(
        router=_FakeRouter(),
        generator=None,
        spec_repo=None,
        cache=_NoCache(),
    )
    final = graph.invoke({
        "question": "你好",
        "category": None,
        "session_id": "s1",
        "history": [],
        "start_ts": 0,
    })
    assert final["result"]["intent"] == "reject"
    assert final["result"]["rejected"] is True


def test_param_channel_with_stub():
    """param 通道：stub 槽位抽取 + 内存规格库 → 参数卡片。"""
    graph = build_graph(
        router=_FakeRouter("param"),
        generator=None,
        spec_repo=_StubSpecRepo(),
        cache=_NoCache(),
    )
    import app.rag.pipeline as pl
    orig = pl.extract_slots
    pl.extract_slots = lambda q: _Slots()
    try:
        final = graph.invoke({
            "question": "RTX 4070 的 TDP 是多少",
            "category": None, "session_id": None, "history": [], "start_ts": 0,
        })
        r = final["result"]
        assert r["intent"] == "param"
        assert r["strategy"] == "direct-sql"
        assert "200" in r["answer"]  # TDP 值出现在卡片里
    finally:
        pl.extract_slots = orig


def test_compat_channel_with_stub():
    """compat 通道：stub 配置抽取 + 规则引擎 → 核验单。"""
    graph = build_graph(
        router=_FakeRouter("compat"),
        generator=None,
        spec_repo=_StubSpecRepo(),
        cache=_NoCache(),
    )
    import app.rag.pipeline as pl
    orig = pl.extract_config
    pl.extract_config = lambda q, history=None: _Config()
    try:
        final = graph.invoke({
            "question": "14900K 配 4090 用 650W 电源行吗",
            "category": None, "session_id": None, "history": [], "start_ts": 0,
        })
        r = final["result"]
        assert r["intent"] == "compat"
        assert r["strategy"] == "rules-engine"
        assert "❌" in r["answer"]       # 功耗不足冲突
        assert "R3" in r["answer"]
        assert "R1" in r["answer"]      # 插槽核验也在
        assert r["evidence_ids"] and "R1" in r["evidence_ids"]
    finally:
        pl.extract_config = orig


def test_rag_channel_reject_when_no_docs():
    """rag 通道：检索无文档 → 拒答（stub retriever 返回空）。"""
    import app.rag.pipeline as pl

    graph = build_graph(
        router=_FakeRouter("rag"),
        generator=None,
        spec_repo=None,
        cache=_NoCache(),
    )
    orig = pl.retrieve
    pl.retrieve = lambda q, category=None, top_k=5, rerank=True: []
    try:
        final = graph.invoke({
            "question": "随便什么攻略问题",
            "category": None, "session_id": None, "history": [], "start_ts": 0,
        })
        assert final["result"]["intent"] == "rag"
        assert final["result"]["rejected"] is True
        assert final["result"]["strategy"] == "no-evidence"
    finally:
        pl.retrieve = orig


# ---- stubs ----

class _FakeRouter:
    def __init__(self, intent: str = "reject"):
        self._intent = intent

    def route(self, question, history=None):
        return {"intent": self._intent, "confidence": 0.9, "reason": "stub",
                "route_detail": {"stub": True}}


class _NoCache:
    def get(self, q, c):
        return None

    def set(self, q, c, d, rejected=False):
        pass


class _Slots:
    category = "gpu"
    model_name = "RTX 4070"
    fields = ["tdp_w"]


class _Config:
    cpu = "i9-14900K"
    gpu = "RTX 4090"
    motherboard = "Z790"
    memory = "DDR5"
    psu = "650W"
    case_limit_mm = None


class _StubSpecRepo:
    def best_match(self, category, query):
        data = {
            "gpu": {"gpu_id": 1, "name": "GeForce RTX 4070", "tdp_w": 200, "vram_gb": 12},
            "cpu": {"cpu_id": 2, "name": "Intel Core i9-14900K", "socket": "LGA1700",
                    "tdp_w": 125, "tdp_max_w": 253, "memory_types": "DDR4,DDR5"},
            "motherboard": {"mb_id": 3, "name": "MSI MAG Z790 TOMAHAWK", "socket": "LGA1700",
                            "memory_types": "DDR5", "pcie_gen": 5},
            "memory": {"mem_id": 4, "name": "DDR5 6000 32GB", "mem_type": "DDR5"},
            "psu": {"psu_id": 5, "name": "MSI MAG A650BN", "rated_w": 650},
        }
        return data.get(category)

    def search(self, category, query, limit=5):
        m = self.best_match(category, query)
        return [m] if m else []
