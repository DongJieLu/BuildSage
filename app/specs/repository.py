"""规格库仓储：五类硬件参数的模糊查询（全部参数化 SQL）。

供参数直查（param 通道）与兼容性校验（compat 通道）把 LLM 抽取的
型号字符串解析成规格行。匹配策略：规范化后 LIKE 前缀/包含 + 相关度打分。
"""
from __future__ import annotations

import re
from sqlalchemy import text

from app.db.mysql import get_engine

TABLES = {
    "cpu": "cpu",
    "gpu": "gpu",
    "motherboard": "motherboard",
    "memory": "memory",
    "psu": "psu",
    "cooler": "cooler",
    "case": "pc_case",
}

_ID_COLS = {
    "cpu": "cpu_id", "gpu": "gpu_id", "motherboard": "mb_id",
    "memory": "mem_id", "psu": "psu_id", "cooler": "cooler_id", "case": "case_id",
}

# 参与匹配时剔除的噪声词（品牌词与容量词，避免 "850W" 匹配到 Corsair RM850e 之外）
_NOISE_RE = re.compile(r"(geforce|radeon|ryzen|intel|amd|core|nvidia|gb|w\b|显卡|处理器|主板|内存|电源|散热器|机箱|水冷|风冷)", re.I)


def normalize_query(q: str) -> str:
    """去噪声词后压掉所有空白：中文用户写「利民PA120」通常不带空格，
    而 DB 里是「利民 PA120 SE」，比较必须两边都去空格。"""
    return re.sub(r"\s+", "", _NOISE_RE.sub(" ", (q or "").strip())).lower()


def _squash(name: str) -> str:
    return re.sub(r"\s+", "", (name or "").lower())


class SpecRepository:
    def __init__(self, engine=None) -> None:
        self._engine = engine or get_engine()

    def search(self, category: str, query: str, limit: int = 5) -> list[dict]:
        """按类别模糊查询规格，返回按相关度排序的候选（可能为空）。"""
        if category not in TABLES or not query or not query.strip():
            return []
        table = TABLES[category]
        q = normalize_query(query)
        if not q:
            q = query.strip().lower()
        sql = (f"SELECT * FROM {table} WHERE LOWER(REPLACE(name, ' ', '')) LIKE :pat "
               f"ORDER BY release_year DESC LIMIT :limit") \
            if category in ("cpu", "gpu", "motherboard") else \
            f"SELECT * FROM {table} WHERE LOWER(REPLACE(name, ' ', '')) LIKE :pat LIMIT :limit"
        with self._engine.connect() as conn:
            rows = conn.execute(text(sql), {"pat": f"%{q}%", "limit": limit}).mappings().all()
            return [dict(r) for r in rows]

    def search_all(self, category: str, limit: int = 100) -> list[dict]:
        """浏览某类全部规格（无关键词），按年份/名称排序。"""
        if category not in TABLES:
            return []
        table = TABLES[category]
        # 只有 cpu/gpu/motherboard 有 release_year 列
        order = "ORDER BY release_year DESC, name" if category in ("cpu", "gpu", "motherboard") else "ORDER BY name"
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(f"SELECT * FROM {table} {order} LIMIT :limit"), {"limit": limit}
            ).mappings().all()
        return [dict(r) for r in rows]

    def best_match(self, category: str, query: str) -> dict | None:
        """返回最相关的单条规格（无候选返回 None）。"""
        cands = self.search(category, query, limit=5)
        if not cands:
            return None
        q = normalize_query(query)

        def score(row: dict) -> tuple[int, int]:
            name = _squash(row["name"])
            s = 0
            if name == q:
                s += 100
            if name.startswith(q):
                s += 40
            if q in name:
                s += 20
            s += 10 if row.get("source") == "manual" else 0
            # 同分时偏好名字更短的（基础型号优于衍生变体，如 RTX 4090 优于 4090 D）
            return s, -len(name)

        return max(cands, key=score)

    def count(self, category: str | None = None) -> dict:
        if category:
            table = TABLES[category]
            with self._engine.connect() as conn:
                n = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
            return {category: int(n or 0)}
        with self._engine.connect() as conn:
            return {cat: int(conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar() or 0)
                    for cat, t in TABLES.items()}
