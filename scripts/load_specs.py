"""把 data/specs/*.json 导入 MySQL 规格库（先清后插，幂等）。

数据来源：
- cpu_intel.json / gpu_nvidia.json / gpu_amd.json：extract_specs.py 从公开规格页抽取
- cpu_amd.json / motherboard.json / memory.json / psu.json：人工整理
用法：python scripts/load_specs.py
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy import text

from app.db.mysql import get_engine

SPECS = Path(__file__).resolve().parent.parent / "data" / "specs"


def load(filename: str) -> list[dict]:
    return json.loads((SPECS / filename).read_text(encoding="utf-8"))


def to_int(value) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def to_float(value) -> float | None:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def norm_cpu(row: dict) -> dict:
    return {
        "name": row["name"], "brand": row["brand"], "socket": row.get("socket"),
        "cores": to_int(row.get("cores")), "threads": to_int(row.get("threads")),
        "tdp_w": to_int(row.get("tdp_w")), "tdp_max_w": to_int(row.get("tdp_max_w")),
        "boost_ghz": to_float(row.get("boost_ghz")),
        "memory_types": ",".join(row.get("memory_types") or []),
        "release_year": to_int(row.get("release_year")),
        "passmark_cpu_mark": to_int(row.get("passmark_cpu_mark")),
        "source": row.get("source", "manual"),
    }


def norm_gpu(row: dict) -> dict:
    gen = to_int(row.get("pcie_gen"))
    return {
        "name": row["name"], "brand": row["brand"],
        "vram_gb": to_int(row.get("vram_gb")), "vram_type": row.get("vram_type"),
        "tdp_w": to_int(row.get("tdp_w")), "length_mm": to_int(row.get("length_mm")),
        "recommended_psu_w": to_int(row.get("recommended_psu_w")),
        "pcie_gen": gen, "release_year": to_int(row.get("release_year")),
        "msrp_usd": to_float(row.get("msrp_usd")),
        "passmark_g3d": to_int(row.get("passmark_g3d")),
        "source": row.get("source", "manual"),
    }


def norm_mb(row: dict) -> dict:
    return {
        "name": row["name"], "brand": row["brand"], "chipset": row.get("chipset"),
        "socket": row.get("socket"),
        "memory_types": ",".join(row.get("memory_types") or []),
        "form_factor": row.get("form_factor"),
        "pcie_gen": to_int(row.get("pcie_gen")), "release_year": to_int(row.get("release_year")),
        "source": row.get("source", "manual"),
    }


def norm_memory(row: dict) -> dict:
    return {
        "name": row["name"], "brand": row["brand"], "mem_type": row.get("mem_type"),
        "capacity_gb": to_int(row.get("capacity_gb")), "speed_mhz": to_int(row.get("speed_mhz")),
        "modules": to_int(row.get("modules")), "source": row.get("source", "manual"),
    }


def norm_psu(row: dict) -> dict:
    return {
        "name": row["name"], "brand": row["brand"], "rated_w": to_int(row.get("rated_w")),
        "certification": row.get("certification"), "modularity": row.get("modularity"),
        "atx3": 1 if row.get("atx3") else 0, "source": row.get("source", "manual"),
    }


INSERTS = {
    "cpu": ("INSERT INTO cpu (name, brand, socket, cores, threads, tdp_w, tdp_max_w, boost_ghz, "
            "memory_types, release_year, passmark_cpu_mark, source) "
            "VALUES (:name, :brand, :socket, :cores, :threads, :tdp_w, :tdp_max_w, :boost_ghz, "
            ":memory_types, :release_year, :passmark_cpu_mark, :source)", norm_cpu),
    "gpu": ("INSERT INTO gpu (name, brand, vram_gb, vram_type, tdp_w, length_mm, recommended_psu_w, "
            "pcie_gen, release_year, msrp_usd, passmark_g3d, source) "
            "VALUES (:name, :brand, :vram_gb, :vram_type, :tdp_w, :length_mm, :recommended_psu_w, "
            ":pcie_gen, :release_year, :msrp_usd, :passmark_g3d, :source)", norm_gpu),
    "motherboard": ("INSERT INTO motherboard (name, brand, chipset, socket, memory_types, form_factor, "
                    "pcie_gen, release_year, source) "
                    "VALUES (:name, :brand, :chipset, :socket, :memory_types, :form_factor, "
                    ":pcie_gen, :release_year, :source)", norm_mb),
    "memory": ("INSERT INTO memory (name, brand, mem_type, capacity_gb, speed_mhz, modules, source) "
               "VALUES (:name, :brand, :mem_type, :capacity_gb, :speed_mhz, :modules, :source)", norm_memory),
    "psu": ("INSERT INTO psu (name, brand, rated_w, certification, modularity, atx3, source) "
            "VALUES (:name, :brand, :rated_w, :certification, :modularity, :atx3, :source)", norm_psu),
}


def dedupe(rows: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for r in rows:
        key = re.sub(r"[^a-z0-9]", "", r["name"].lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def main() -> None:
    cpus = dedupe(load("cpu_intel.json") + load("cpu_amd.json"))
    gpus = dedupe(load("gpu_nvidia.json") + load("gpu_amd.json"))
    mbs = dedupe(load("motherboard.json"))
    mems = dedupe(load("memory.json"))
    psus = dedupe(load("psu.json"))
    data = {"cpu": cpus, "gpu": gpus, "motherboard": mbs, "memory": mems, "psu": psus}

    engine = get_engine()
    with engine.begin() as conn:
        for table in ("memory", "psu", "motherboard", "gpu", "cpu"):  # 先子后父无所谓，仅顺序美观
            conn.execute(text(f"DELETE FROM {table}"))
        for table, rows in data.items():
            sql, norm = INSERTS[table]
            conn.execute(text(sql), [norm(r) for r in rows])
    for table, rows in data.items():
        print(f"{table:12s}: {len(rows)} 条已导入")


if __name__ == "__main__":
    main()
