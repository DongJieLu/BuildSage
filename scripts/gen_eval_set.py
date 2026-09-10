"""金标集自动生成：从规格库与规则引擎生成可复现的评估数据（不含人工标注漂移）。

产出 data/eval/eval_set.jsonl，每行一类：
- param：参数直查（question + expected{category, model_key, field, value}）
- compat：兼容校验（question + expected{verdict, failed_rules}）
- rag：攻略问答（question + expected{doc_names}）→ Recall@5 / RAGAS
- reject：寒暄/无关（question + expected{intent=reject}）

硬指标的"金标准"直接来自结构化数据本身：参数真值 = 规格库字段值；
兼容真值 = 规则引擎对同套配置的判定。这是"结构化 RAG 可硬评估"的核心卖点。

用法：python scripts/gen_eval_set.py [--seed 42]
"""
import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy import text

from app.db.mysql import get_engine
from app.specs.rules import check_compat, verdict

OUT = Path(__file__).resolve().parent.parent / "data" / "eval" / "eval_set.jsonl"

# ---- param 模板：字段 → 问法与展示名 ----
PARAM_TEMPLATES = {
    "tdp_w": ("{model} 的 TDP 是多少", "功耗"),
    "vram_gb": ("{model} 显存多大", "显存"),
    "socket": ("{model} 用什么插槽", "插槽"),
    "rated_w": ("{model} 额定功率多少瓦", "功率"),
    "cores": ("{model} 有几个核心", "核心数"),
    "boost_ghz": ("{model} 最高频率多少", "频率"),
}

FIELD_COLUMNS = {
    "gpu": ["tdp_w", "vram_gb"],
    "cpu": ["tdp_w", "socket", "cores"],
    "psu": ["rated_w"],
}

QUESTION_DECOR = {
    "gpu": ["GeForce {m}", "RTX {m}", "{m}"],
    "cpu": ["i{m}", "{m}"],
    "psu": ["{m}"],
}


def fetch_models(per_cat: int = 12) -> dict[str, list[dict]]:
    """按类别抽取参数齐全的型号（psu 表无 release_year 列，单独查询）。"""
    engine = get_engine()
    out: dict[str, list[dict]] = {}
    for cat, cols in FIELD_COLUMNS.items():
        col_list = ", ".join(cols)
        year_filter = "WHERE release_year >= :y AND name IS NOT NULL" if cat != "psu" \
            else "WHERE name IS NOT NULL"
        params: dict = {"n": per_cat * 3}
        if cat != "psu":
            params["y"] = 2020
        with engine.connect() as conn:
            rows = conn.execute(
                text(f"SELECT name, {col_list} FROM {cat} {year_filter} ORDER BY RAND() LIMIT :n"),
                params,
            ).mappings().all()
        picked = [r for r in rows if all(r[c] is not None for c in cols)][:per_cat]
        out[cat] = picked
    return out


def gen_param(models: dict, rng: random.Random) -> list[dict]:
    items = []
    for cat, rows in models.items():
        for row in rows:
            field = rng.choice(FIELD_COLUMNS[cat])
            tmpl, label = PARAM_TEMPLATES[field]
            q = tmpl.format(model=row["name"])
            raw = row[field]
            value: float | int | str
            if field == "socket":
                value = str(raw)
            elif field in ("boost_ghz",):
                value = float(raw)
            else:
                value = int(raw)
            items.append({
                "type": "param", "question": q,
                "expected": {"category": cat, "model_key": row["name"], "field": field,
                             "value": value, "field_label": label},
            })
    return items


def gen_compat(models: dict, rng: random.Random) -> list[dict]:
    """从规则引擎生成正负例：真值 = check_compat 对同套配置的判定。"""
    # 组装若干"合法/非法"组合的素材
    cpu_pool = [r for rows in [models.get("cpu", [])] for r in rows]
    gpu_pool = [r for rows in [models.get("gpu", [])] for r in rows]
    items = []
    for i in range(16):
        cpu = rng.choice(cpu_pool)
        gpu = rng.choice(gpu_pool)
        # 主板按 CPU 插槽匹配（正例）或不匹配（负例）
        socket = cpu["socket"]
        with get_engine().connect() as conn:
            mb_match = conn.execute(
                text("SELECT name, socket, memory_types, pcie_gen FROM motherboard "
                     "WHERE socket = :s ORDER BY RAND() LIMIT 1"),
                {"s": socket},
            ).mappings().first()
            mb_wrong = conn.execute(
                text("SELECT name, socket, memory_types, pcie_gen FROM motherboard "
                     "WHERE socket != :s AND socket IS NOT NULL ORDER BY RAND() LIMIT 1"),
                {"s": socket},
            ).mappings().first()
        cpu_row = {"name": cpu["name"], "socket": cpu["socket"], "tdp_w": cpu["tdp_w"],
                   "tdp_max_w": None, "memory_types": "DDR5" if "DDR5" in str(cpu.get("socket") or "") else "DDR4"}
        # CPU memory_types 单独查（fetch 少量列）
        with get_engine().connect() as conn:
            full_cpu = conn.execute(text("SELECT name, socket, tdp_w, tdp_max_w, memory_types FROM cpu "
                                         "WHERE name = :n"), {"n": cpu["name"]}).mappings().first()
        cpu_row = dict(full_cpu) if full_cpu else cpu_row
        if isinstance(cpu_row.get("memory_types"), str):
            cpu_row["memory_types"] = [t for t in cpu_row["memory_types"].split(",") if t]
        gpu_row = {"name": gpu["name"], "tdp_w": gpu["tdp_w"], "pcie_gen": 4, "length_mm": None}

        def mb_dict(mb):
            d = dict(mb)
            if isinstance(d.get("memory_types"), str):
                d["memory_types"] = [t for t in d["memory_types"].split(",") if t]
            return d

        for mb, tag in ((mb_match, "match"), (mb_wrong, "wrong")):
            if mb is None:
                continue
            need = int(cpu_row.get("tdp_max_w") or cpu_row["tdp_w"]) + int(gpu["tdp_w"]) + 80
            # 一半给足瓦数（R3 过），一半不足（R3 冲突）
            psu_w = need + 150 if rng.random() < 0.5 else max(300, need - 250)
            mem_type = (mb_dict(mb).get("memory_types") or ["DDR5"])[0]
            q = (f"{cpu_row['name']} 配 {gpu['name']}，用 {psu_w}W 电源，"
                 f"{mb['name']}，{mem_type} 内存，帮我看看行不行")
            checks = check_compat(
                cpu=cpu_row, motherboard=mb_dict(mb),
                memory={"name": mem_type, "mem_type": mem_type},
                gpu=gpu_row, psu={"name": f"{psu_w}W", "rated_w": psu_w}, case_limit_mm=None,
            )
            items.append({
                "type": "compat", "question": q,
                "expected": {
                    "verdict": verdict(checks),
                    "failed_rules": [r.rule_id for r in checks if r.status == "conflict"],
                    "config": {"cpu": cpu_row["name"], "gpu": gpu["name"],
                               "motherboard": mb["name"], "psu_w": psu_w},
                },
            })
    return items


# rag 金标：问题 → (应命中文档, 回答必含关键信息点)。
# answer_keys 取自攻略原文的核心事实，用于评估"回答内容准确率"——
# 即 RAG 通道是否真的把知识库里的知识查准并答出来，而不只是检索到了文档。
RAG_GOLD = [
    ("电源功率怎么算", ["01_电源选购与功率计算.md"], ["80"]),
    ("80PLUS 金牌认证值得买吗", ["01_电源选购与功率计算.md"], ["转换效率", "金牌"]),
    ("ATX 3.0 电源有什么好处", ["01_电源选购与功率计算.md"], ["12VHPWR"]),
    ("DDR4 和 DDR5 应该怎么选", ["02_DDR4与DDR5怎么选.md"], ["AM4"]),
    ("AM5 平台内存频率选多少合适", ["02_DDR4与DDR5怎么选.md", "06_内存容量与频率指南.md"], ["6000"]),
    ("游戏和生产力 CPU 怎么挑", ["03_CPU选购指南.md"], ["缓存", "核心"]),
    ("9800X3D 为什么适合游戏", ["03_CPU选购指南.md"], ["缓存"]),
    ("显卡按分辨率选档位", ["04_显卡选购指南.md"], ["2K"]),
    ("2K 分辨率配什么显卡", ["04_显卡选购指南.md"], ["4070"]),
    ("A 卡和 N 卡怎么分", ["04_显卡选购指南.md"], ["DLSS", "FSR"]),
    ("选主板第一步看什么", ["05_主板选购指南.md"], ["插槽"]),
    ("B760 和 Z790 有什么区别", ["05_主板选购指南.md"], ["超频"]),
    ("内存容量 16G 够用吗", ["06_内存容量与频率指南.md"], ["32GB"]),
    ("双通道有什么必要", ["06_内存容量与频率指南.md"], ["带宽"]),
    ("5000 元装机怎么配", ["07_5000元装机配置.md"], ["4060"]),
    ("8000 元装机思路是什么", ["08_8000元装机配置.md"], ["4070"]),
    ("15000 元装机怎么配", ["09_15000元装机配置.md"], ["4080"]),
    ("i9 级别用什么散热", ["10_散热器选购指南.md"], ["360"]),
    ("风冷和水冷哪个好", ["10_散热器选购指南.md"], ["漏液", "可靠"]),
    ("机箱风道怎么设计", ["11_机箱与风道指南.md"], ["前进后出"]),
    ("显卡限长怎么看", ["11_机箱与风道指南.md"], ["320"]),
    ("PCIe 4.0 和 5.0 差距大吗", ["12_PCIe世代与带宽科普.md"], ["翻倍", "带宽"]),
    ("老主板插新显卡会损失性能吗", ["12_PCIe世代与带宽科普.md"], ["向下兼容"]),
    ("装机最容易翻车的兼容性问题", ["13_装机兼容性避坑清单.md"], ["插槽"]),
    ("下单前应该核对哪些兼容性", ["13_装机兼容性避坑清单.md"], ["插槽", "内存"]),
    ("固态硬盘容量怎么选", ["14_固态硬盘选购指南.md"], ["2TB"]),
    ("PCIe 5.0 固态值得买吗", ["14_固态硬盘选购指南.md", "12_PCIe世代与带宽科普.md"], ["发热"]),
]

REJECT_GOLD = [
    "你好", "在吗", "谢谢啦", "今天天气怎么样", "讲个笑话",
    "你会做饭吗", "帮我写个请假条", "NBA 最近有什么新闻",
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    rng = random.Random(args.seed)

    models = fetch_models()
    items = gen_param(models, rng) + gen_compat(models, rng)
    items += [{"type": "rag", "question": q, "expected": {"doc_names": docs, "answer_keys": keys}}
              for q, docs, keys in RAG_GOLD]
    items += [{"type": "reject", "question": q, "expected": {"intent": "reject"}} for q in REJECT_GOLD]

    rng.shuffle(items)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    dist = {}
    for it in items:
        dist[it["type"]] = dist.get(it["type"], 0) + 1
    print(f"金标集已生成：{OUT}（共 {len(items)} 条，分布 {dist}，seed={args.seed}）")


if __name__ == "__main__":
    main()
