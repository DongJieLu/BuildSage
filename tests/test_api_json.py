"""API 序列化回归测试：MySQL 返回值（Decimal / datetime）必须可 JSON 化。"""
from datetime import datetime
from decimal import Decimal

from app.api.main import _jsonable


def test_jsonable_decimal():
    assert _jsonable(Decimal("599.00")) == 599.0


def test_jsonable_datetime():
    assert _jsonable(datetime(2026, 9, 9, 12, 30, 0)) == "2026-09-09 12:30:00"


def test_jsonable_nested():
    row = {"doc_id": 1, "created_at": datetime(2026, 9, 9, 1, 2, 3), "msrp": Decimal("1599.00")}
    out = _jsonable([row])
    assert out == [{"doc_id": 1, "created_at": "2026-09-09 01:02:03", "msrp": 1599.0}]
    import json

    json.dumps(out)  # 不抛异常即通过


def test_jsonable_passthrough():
    assert _jsonable({"a": [1, "x", None, True]}) == {"a": [1, "x", None, True]}
