"""四通道路由单测：L1 规则（不依赖 LLM/DB）。"""
from app.rag.router import rule_route


def test_l1_param_model_plus_field():
    for q in ("RTX 4070 的 TDP 是多少", "i9-14900K 功耗多少瓦", "RX 7900 XTX 显存多大"):
        d = rule_route(q)
        assert d is not None and d.intent == "param", q


def test_l1_param_english():
    d = rule_route("RTX 4090 vram")
    assert d is not None and d.intent == "param"


def test_l1_compat_keyword():
    for q in ("B650 主板能用 DDR4 吗", "i9-14900K 配 650W 电源带得动吗", "这个配置兼容吗", "Z790 支持 DDR5 吗"):
        d = rule_route(q)
        assert d is not None and d.intent == "compat", q


def test_l1_compat_beats_param_when_both():
    d = rule_route("RTX 4090 配 650W 电源够吗")
    assert d is not None and d.intent == "compat"


def test_l1_reject_chitchat():
    d = rule_route("你好")
    assert d is not None and d.intent == "reject"
    d = rule_route("在吗")
    assert d is not None and d.intent == "reject"


def test_l1_reject_empty():
    d = rule_route("")
    assert d is not None and d.intent == "reject"


def test_l1_open_question_falls_through():
    """开放问题不命中规则 → None，交给 L2 LLM 分类。"""
    for q in ("5000 元预算怎么装机", "DDR4 和 DDR5 怎么选", "水冷和风冷哪个好"):
        assert rule_route(q) is None, q
