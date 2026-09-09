"""规格抽取：Wikipedia 规格列表 + PassMark 性能榜 → data/specs/*.json。

数据源（data/docs/*.html，不入 git）：
- wikipedia_intel_cpu_list.html  → cpu_intel.json（Skylake 起，含 Core Ultra）
- wikipedia_nvidia_gpu_list.html → gpu_nvidia.json（GTX 10 系起）
- wikipedia_amd_gpu_list.html    → gpu_amd.json（RX 400 系起）
- passmark_cpu_list.html / passmark_gpu_list.html → 性能分与价格合并进上述产物

核心思路：Wikipedia 规格表大量使用 rowspan/colspan（模型列跨行、子表头跨列），
直接按列头取值必然错位。先做「网格展开」（grid expand）把每张表还原成规则二维表，
再按列头语义定位字段。来源与许可见 data/SOURCES.md。

用法：.venv/Scripts/python.exe scripts/extract_specs.py [--debug]
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup, Tag

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "data" / "docs"
OUT = ROOT / "data" / "specs"

MIN_GPU_YEAR = 2016   # GTX 10 / RX 400 起
MIN_CPU_YEAR = 2015   # Skylake 起

GPU_NAME_RE = re.compile(r"GeForce\s+(?:RTX|GTX|GT)\s*\d{2,4}\w*|Radeon\s+(?:RX|VII)\s*\S*")
CPU_MODEL_RE = re.compile(r"(?:Core\s+)?i[3579]-\d{4,5}[A-Z]{0,3}|Ultra\s+\d\s+\d{3}[A-Z]{0,3}")
TDP_RE = re.compile(r"(\d{2,4})\s*W\b", re.I)
VRAM_GB_RE = re.compile(r"^(\d{1,2})\s*(?:GB)?$")
VRAM_TYPE_RE = re.compile(r"(GDDR\w+|HBM\w+)", re.I)
PCIE_RE = re.compile(r"PCIe\s*(\d(?:\.\d)?)", re.I)
YEAR_RE = re.compile(r"\b(20[0-2]\d)\b")
MSRP_RE = re.compile(r"\$\s*([\d,]{3,5})")
SOCKET_RE = re.compile(r"(LGA\s?\d{4}|AM[45])", re.I)
INT_RE = re.compile(r"^\d{1,5}$")
FLOAT_RE = re.compile(r"\b(\d\.\d{1,2})\b")

DEBUG = "--debug" in sys.argv
PROBES = ("4090", "RTX 4070", "7900 XTX", "14900K", "13600K", "285K")


# ---------- 网格展开 ----------

def _span(cell: Tag, attr: str) -> int:
    m = re.match(r"\d+", str(cell.get(attr) or "1"))
    return max(1, int(m.group())) if m else 1


def grid_expand(table: Tag) -> tuple[list[str], list[list[str]]]:
    """把含 rowspan/colspan 的 HTML 表还原成规则二维表。

    返回 (headers, rows)：headers 为主表头+子表头拼接（colspan 展平），
    rows 中每个单元格已按 rowspan 向下复制。
    """
    trs = table.select("tr")
    grid: dict[tuple[int, int], str] = {}
    header_rows = 0
    for r, tr in enumerate(trs):
        cells = tr.find_all(["td", "th"])
        if header_rows == r and cells and all(c.name == "th" for c in cells):
            header_rows = r + 1
        c = 0
        for cell in cells:
            while (r, c) in grid:
                c += 1
            text = cell.get_text(" ", strip=True)
            for dr in range(_span(cell, "rowspan")):
                for dc in range(_span(cell, "colspan")):
                    grid[(r + dr, c + dc)] = text
            c += _span(cell, "colspan")
    if not grid:
        return [], []
    n_cols = max(c for _, c in grid) + 1
    headers = [" ".join(filter(None, (grid.get((r, c), "") for r in range(header_rows)))).strip().lower()
               for c in range(n_cols)]
    rows = [[grid.get((r, c), "") for c in range(n_cols)] for r in range(header_rows, len(trs))]
    return headers, rows


def find_col(headers: list[str], *keywords: str) -> int | None:
    for i, h in enumerate(headers):
        if all(k in h for k in keywords):
            return i
    return None


def find_col2(headers: list[str], *alias: tuple[str, ...]) -> int | None:
    """多组关键词依次查找（正确处理 0 号列：不能写 find_col(a) or find_col(b)）。"""
    for keys in alias:
        col = find_col(headers, *keys)
        if col is not None:
            return col
    return None


def col_value(rows: list[list[str]], col: int | None, regex: re.Pattern, group: int = 1) -> str | None:
    """取某列全部行值（处理同一模型跨多行的 rowspan 残留），逐行用正则匹配。"""
    if col is None:
        return None
    for row in rows:
        if col < len(row):
            m = regex.search(row[col])
            if m:
                return m.group(group)
    return None


def parse_year(text: str) -> int | None:
    m = YEAR_RE.search(text)
    return int(m.group(1)) if m and 2000 <= int(m.group(1)) <= 2026 else None


def max_ghz(text: str) -> float | None:
    nums = [float(x) for x in FLOAT_RE.findall(text) if 0.5 <= float(x) <= 6.0]
    return max(nums) if nums else None


# ---------- GPU ----------

def extract_gpu(filename: str, brand: str) -> list[dict]:
    soup = BeautifulSoup((DOCS / filename).read_text(encoding="utf-8", errors="replace"), "lxml")
    items: dict[str, dict] = {}
    for table in soup.select("table.wikitable"):
        headers, rows = grid_expand(table)
        tdp_col = find_col2(headers, ("tdp",), ("tbp",))
        launch_col = find_col2(headers, ("launch",), ("release date",))
        price_col = find_col2(headers, ("msrp",), ("price",))
        bus_col = find_col2(headers, ("bus interface",), ("bus type",))
        mem_size_col = find_col2(headers, ("memory", "size"), ("memory", "config"))
        mem_type_col = find_col(headers, "memory", "type")
        for row in rows:
            if not row or not GPU_NAME_RE.search(row[0]):
                continue
            name = re.sub(r"\s*\[\s*\d+\s*\]", "", row[0]).strip()   # 去引用角标
            if re.search(r"mobile|laptop|\d{3,4}M\b", name, re.I):   # 过滤移动端
                continue
            year = parse_year(row[launch_col]) if (launch_col is not None and launch_col < len(row)) else None
            if year is None:
                for cell in row[1:]:
                    year = parse_year(cell)
                    if year:
                        break
            if year is None or year < MIN_GPU_YEAR:
                continue
            # TDP：列头 tdp/tbp；值为 "450 W" 或裸数字
            tdp = None
            if tdp_col is not None and tdp_col < len(row):
                m = TDP_RE.search(row[tdp_col]) or (re.match(r"^(\d{2,4})$", row[tdp_col]) and row[tdp_col])
                if m:
                    tdp = int(m.group(1) if hasattr(m, "group") else m)
                    if tdp > 800:
                        tdp = None
            # 显存：在本行找到显存类型单元格（GDDR6X/HBM），容量取其邻位（左1~2格）
            vram_gb = vram_type = None
            type_idx = next((i for i, c in enumerate(row) if VRAM_TYPE_RE.fullmatch(c.strip()) or VRAM_TYPE_RE.search(c) and "bit" in c.lower()), None)
            if type_idx is not None:
                m = VRAM_TYPE_RE.search(row[type_idx])
                vram_type = m.group(1).upper()
                for off in (1, 2):
                    i = type_idx - off
                    if i >= 0:
                        vm = re.match(r"^(\d{1,2})(\s*GB)?$", row[i])
                        if vm:
                            vram_gb = int(vm.group(1))
                            break
            if vram_gb is None:  # 兜底：表级容量列
                if mem_size_col is not None:
                    for row_v in rows:
                        if mem_size_col < len(row_v):
                            vm = VRAM_GB_RE.match(row_v[mem_size_col])
                            if vm:
                                vram_gb = int(vm.group(1))
                                break
            pcie = None
            if bus_col is not None:
                pcie = col_value(rows, bus_col, PCIE_RE)
            if pcie is None:
                m = PCIE_RE.search(" ".join(row))
                pcie = m.group(1) if m else None
            msrp = None
            price_text = " ".join(row[price_col] for i in [price_col] if i is not None and i < len(row))
            m = MSRP_RE.search(price_text) or MSRP_RE.search(" ".join(row))
            if m:
                msrp = float(m.group(1).replace(",", ""))
            item = {
                "name": name, "brand": brand, "vram_gb": vram_gb, "vram_type": vram_type,
                "tdp_w": tdp, "pcie_gen": pcie, "release_year": year,
                "msrp_usd": msrp, "source": "wikipedia",
            }
            key = re.sub(r"[^a-z0-9]", "", name.lower())
            old = items.get(key)
            if old is None or sum(v is None for v in item.values()) < sum(v is None for v in old.values()):
                items[key] = item
            if DEBUG and any(p in name for p in PROBES):
                print(f"[debug gpu] name={name!r} tdp={tdp} vram={vram_gb}/{vram_type} pcie={pcie}")
                print(f"    headers={headers}")
                print(f"    row={row}")
    return list(items.values())


# ---------- CPU（Intel）----------

def intel_socket(headers: list[str], row: list[str], name: str) -> str | None:
    socket_col = find_col(headers, "socket")
    if socket_col is not None and socket_col < len(row):
        m = SOCKET_RE.search(row[socket_col])
        if m:
            return re.sub(r"\s+", "", m.group(1)).upper()
    m = SOCKET_RE.search(" ".join(row))
    if m:
        return re.sub(r"\s+", "", m.group(1)).upper()
    # 依据世代推断（桌面插槽世代规律）
    gen_m = re.search(r"i[3579]-(\d{2})\d{3}|Ultra\s+\d\s+(\d)", name)
    if "ultra" in name.lower():
        return "LGA1851"
    if gen_m and gen_m.group(1):
        gen = int(gen_m.group(1))
        if 12 <= gen <= 14:
            return "LGA1700"
        if gen in (10, 11):
            return "LGA1200"
        if 6 <= gen <= 9:
            return "LGA1151"
    return None


INTEL_GEN_YEAR = {14: 2023, 13: 2022, 12: 2021, 11: 2021, 10: 2020, 9: 2018, 8: 2017, 7: 2015, 6: 2015}


def extract_cpu_intel() -> list[dict]:
    soup = BeautifulSoup((DOCS / "wikipedia_intel_cpu_list.html").read_text(encoding="utf-8", errors="replace"), "lxml")
    items: dict[str, dict] = {}
    for table in soup.select("table.wikitable"):
        headers, rows = grid_expand(table)
        tdp_cols = [i for i, h in enumerate(headers) if "tdp" in h or "power" in h]
        model_col = find_col(headers, "model")
        brand_col = find_col2(headers, ("branding",), ("processor family",))
        cores_total_col = find_col(headers, "cores", "total")
        core_col = find_col(headers, "cores")
        clock_col = find_col(headers, "clock")
        clock_cols = [i for i, h in enumerate(headers) if "clock rate" in h]
        for row in rows:
            if not row:
                continue
            if any("BGA" in c.upper() for c in row):   # 跳过移动端 BGA 封装（板载不可装机）
                continue
            # 取名：两列式（branding "Core i9" + model "14900KS"）或一体式（"i9-14900K"）
            brand_text = row[brand_col] if (brand_col is not None and brand_col < len(row)) else ""
            model_text = row[model_col] if (model_col is not None and model_col < len(row)) else ""
            name = None
            m = CPU_MODEL_RE.search(" ".join(row[:4]))
            if model_text and re.match(r"^\d{4,5}[A-Z]{0,3}$", model_text.strip()) and re.search(r"i[3579]", brand_text):
                name = f"Intel {brand_text.strip()}-{model_text.strip()}"   # Intel Core i9-14900KS
                name = name.replace("Core Core", "Core")
            elif m and m.group(0).startswith("Ultra"):
                name = "Intel Core " + re.sub(r"\s+", " ", m.group(0))       # Intel Core Ultra 7 270K
            elif m:
                name = "Intel Core " + m.group(0).replace("Core ", "")       # Intel Core i9-14900K
            if not name:
                continue
            token = name.replace("Intel Core Ultra ", "").replace("Intel Core ", "")
            if re.search(r"(HK|HQ|H|U|Y)$", token):   # 移动端后缀
                continue
            # TDP：tdp 列可能有多列（base / max turbo）
            tdp = tdp_max = None
            vals = []
            for i in tdp_cols:
                if i < len(row):
                    mm = TDP_RE.search(row[i]) or (re.match(r"^(\d{2,4})$", row[i]) and row[i])
                    if mm:
                        vals.append(int(mm.group(1) if hasattr(mm, "group") else mm))
            if vals:
                tdp = min(vals)
                tdp_max = max(vals) if len(vals) > 1 else None
            if tdp is not None and tdp < 35:  # 过滤移动端
                continue
            # 年份：发布列 → 行内扫描 → 世代推断
            year = None
            year_col = find_col2(headers, ("release",), ("launch",))
            if year_col is not None and year_col < len(row):
                year = parse_year(row[year_col])
            if year is None:
                for cell in row:
                    year = parse_year(cell)
                    if year:
                        break
            if year is None and re.match(r"i[3579]-(\d{2})", token):
                year = INTEL_GEN_YEAR.get(int(re.match(r"i[3579]-(\d{2})", token).group(1)))
            if year is None or year < MIN_CPU_YEAR:
                continue
            cores = threads = None
            ccol = cores_total_col or core_col
            if ccol is not None and ccol < len(row):
                cm = re.match(r"(\d{1,2})\s*(?:\((\d{1,2}))?", row[ccol])
                if cm:
                    cores, threads = int(cm.group(1)), int(cm.group(2)) if cm.group(2) else None
            boost = None
            for i in clock_cols:
                if i < len(row):
                    g = max_ghz(row[i])
                    if g and (boost is None or g > boost):
                        boost = g
            memory_types = sorted({t.upper() for t in re.findall(r"DDR[345]", " ".join(row))})
            if not memory_types:  # 按插槽世代补齐内存代（桌面平台公开规格）
                fallback = {"LGA1700": ["DDR4", "DDR5"], "LGA1851": ["DDR5"], "LGA1200": ["DDR4"], "LGA1151": ["DDR4"]}
                memory_types = fallback.get(item_socket := intel_socket(headers, row, name), [])
            item = {
                "name": name, "brand": "Intel",
                "socket": item_socket if memory_types else intel_socket(headers, row, name),
                "cores": cores, "threads": threads, "tdp_w": tdp, "tdp_max_w": tdp_max,
                "boost_ghz": boost, "memory_types": memory_types,
                "release_year": year, "source": "wikipedia",
            }
            key = re.sub(r"[^a-z0-9]", "", name.lower())
            old = items.get(key)
            if old is None or sum(v is None for v in item.values()) < sum(v is None for v in old.values()):
                items[key] = item
            if DEBUG and any(p in name for p in PROBES):
                print(f"[debug cpu] name={name!r} tdp={tdp}/{tdp_max} socket={item['socket']} cores={cores}T{threads}")
                print(f"    headers={headers}")
                print(f"    row={row}")
    return list(items.values())


# ---------- PassMark ----------

def parse_passmark(filename: str) -> dict[str, dict]:
    soup = BeautifulSoup((DOCS / filename).read_text(encoding="utf-8", errors="replace"), "lxml")
    out: dict[str, dict] = {}
    for tb in soup.select("table"):
        headers, rows = grid_expand(tb)
        for row in rows:
            if len(row) < 2 or not row[0] or not re.match(r"^\d{1,6}$", row[1]):
                continue
            name = re.sub(r"\s*@.*$", "", re.sub(r"\s*\(.*?\)\s*", " ", row[0])).strip()   # 去括注与 @频率
            key = re.sub(r"[^a-z0-9]", "", name.lower())
            if key:
                out[key] = {"score": int(row[1]), "price_usd": None}
    # 价格列在更右侧，补扫
    for tb in soup.select("table"):
        headers, rows = grid_expand(tb)
        price_col = find_col(headers, "price")
        for row in rows:
            if price_col is None or price_col >= len(row):
                continue
            name = re.sub(r"\s*@.*$", "", re.sub(r"\s*\(.*?\)\s*", " ", row[0])).strip() if row else ""
            key = re.sub(r"[^a-z0-9]", "", name.lower())
            m = MSRP_RE.search(row[price_col])
            if key in out and m:
                out[key]["price_usd"] = float(m.group(1).replace(",", ""))
    return out


def merge_passmark(items: list[dict], pm: dict[str, dict], score_field: str) -> None:
    for it in items:
        key = re.sub(r"[^a-z0-9]", "", re.sub(r"\s*\(.*?\)\s*", " ", it["name"]).strip().lower())
        hit = pm.get(key)
        if not hit:  # 去品牌词再试
            bare = re.sub(r"(geforce|radeon|intel|core|ultra)", "", key)
            cands = [v for k, v in pm.items() if bare and bare in k]
            hit = cands[0] if len(cands) == 1 else None
        if hit:
            it[score_field] = hit["score"]
            it["passmark_price_usd"] = hit["price_usd"]


# ---------- 主流程 ----------

def main() -> None:
    OUT.mkdir(exist_ok=True)
    gpu_nvidia = extract_gpu("wikipedia_nvidia_gpu_list.html", "NVIDIA")
    gpu_amd = extract_gpu("wikipedia_amd_gpu_list.html", "AMD")
    cpu_intel = extract_cpu_intel()

    merge_passmark(gpu_nvidia, parse_passmark("passmark_gpu_list.html"), "passmark_g3d")
    merge_passmark(gpu_amd, parse_passmark("passmark_gpu_list.html"), "passmark_g3d")
    merge_passmark(cpu_intel, parse_passmark("passmark_cpu_list.html"), "passmark_cpu_mark")

    for fname, data in (("gpu_nvidia.json", gpu_nvidia), ("gpu_amd.json", gpu_amd), ("cpu_intel.json", cpu_intel)):
        (OUT / fname).write_text(json.dumps(sorted(data, key=lambda x: -x["release_year"]), ensure_ascii=False, indent=1), encoding="utf-8")

    filled = lambda xs, f: sum(1 for x in xs if x.get(f))
    print(f"gpu_nvidia: {len(gpu_nvidia)} 条（TDP {filled(gpu_nvidia,'tdp_w')} / 显存 {filled(gpu_nvidia,'vram_gb')}/{filled(gpu_nvidia,'vram_type')} / PCIe {filled(gpu_nvidia,'pcie_gen')} / passmark {filled(gpu_nvidia,'passmark_g3d')}）")
    print(f"gpu_amd   : {len(gpu_amd)} 条（TDP {filled(gpu_amd,'tdp_w')} / 显存 {filled(gpu_amd,'vram_gb')}/{filled(gpu_amd,'vram_type')} / PCIe {filled(gpu_amd,'pcie_gen')} / passmark {filled(gpu_amd,'passmark_g3d')}）")
    print(f"cpu_intel : {len(cpu_intel)} 条（TDP {filled(cpu_intel,'tdp_w')} / socket {filled(cpu_intel,'socket')} / passmark {filled(cpu_intel,'passmark_cpu_mark')}）")
    sockets: dict[str, int] = {}
    for x in cpu_intel:
        sockets[x["socket"] or "unknown"] = sockets.get(x["socket"] or "unknown", 0) + 1
    print(f"cpu sockets: {dict(sorted(sockets.items(), key=lambda kv: -kv[1]))}")
    for probe, pool in (("GeForce RTX 4090", gpu_nvidia), ("GeForce RTX 4070", gpu_nvidia),
                        ("Radeon RX 7900 XTX", gpu_amd), ("Radeon RX 7800 XT", gpu_amd)):
        hit = [x for x in pool if x["name"].startswith(probe)]
        print(f"probe {probe}: {hit[0] if hit else 'MISS'}")
    for probe in ("Intel Core i9-14900K", "Intel Core i5-13600K", "Intel Core Ultra 9 285K"):
        hit = [x for x in cpu_intel if x["name"] == probe]
        print(f"probe {probe}: {hit[0] if hit else 'MISS'}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
