"""把 data/specs/*.json 转为知识文档并入库 RAG。

规格表仍供配置器和规格浏览页使用；本脚本额外把同一批事实整理为可检索文档，
使聊天中的硬件参数问题也统一走 RAG。
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ingest.service import IngestService

ROOT = Path(__file__).resolve().parent.parent
SPECS_DIR = ROOT / "data" / "specs"

SPEC_FILES = {
    "CPU": ("cpu_intel.json", "cpu_amd.json"),
    "GPU": ("gpu_nvidia.json", "gpu_amd.json"),
    "主板": ("motherboard.json",),
    "内存": ("memory.json",),
    "电源": ("psu.json",),
    "散热器": ("cooler.json",),
    "机箱": ("case.json",),
}

FIELD_LABELS = {
    "brand": "品牌",
    "socket": "插槽",
    "cores": "核心数",
    "threads": "线程数",
    "tdp_w": "TDP",
    "tdp_max_w": "最大功耗",
    "boost_ghz": "最高频率",
    "memory_types": "支持内存",
    "pcie_gen": "PCIe 世代",
    "release_year": "发布年份",
    "vram_gb": "显存容量",
    "vram_type": "显存类型",
    "length_mm": "显卡长度",
    "recommended_psu_w": "推荐电源",
    "chipset": "芯片组",
    "form_factor": "板型",
    "mem_type": "内存类型",
    "capacity_gb": "容量",
    "speed_mhz": "频率",
    "modules": "套条数量",
    "rated_w": "额定功率",
    "certification": "认证",
    "modularity": "模组化",
    "atx3": "ATX 3.0",
    "type": "类型",
    "cooling_capacity_w": "解热能力",
    "sockets": "支持插槽",
    "height_mm": "高度",
    "gpu_limit_mm": "显卡限长",
    "cooler_height_mm": "散热器限高",
    "mb_support": "主板支持",
    "radiator_mm": "冷排尺寸",
}


def load_rows(files: tuple[str, ...]) -> list[dict]:
    rows = []
    for filename in files:
        rows.extend(json.loads((SPECS_DIR / filename).read_text(encoding="utf-8")))
    return rows


def format_value(value) -> str:
    if isinstance(value, list):
        return "、".join(str(item) for item in value)
    if value is True:
        return "是"
    if value is False:
        return "否"
    return str(value)


def build_markdown() -> str:
    sections = [
        "# DIY 装机硬件规格知识库",
        "",
        "以下内容用于回答硬件参数问题，数值来源于项目规格数据。",
        "",
    ]
    for category, files in SPEC_FILES.items():
        sections.extend([f"## {category}规格", ""])
        for row in load_rows(files):
            sections.append(f"### {row.get('name', '未知型号')}")
            for key, value in row.items():
                if key == "name" or value is None or value == "":
                    continue
                sections.append(f"- {FIELD_LABELS.get(key, key)}：{format_value(value)}")
            sections.append("")
    return "\n".join(sections)


def ingest_specs() -> dict:
    content = build_markdown()
    service = IngestService()
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", suffix=".md", delete=False
    ) as temp:
        temp.write(content)
        temp_path = Path(temp.name)
    try:
        return service.ingest_file(
            temp_path,
            category="guide",
            file_name="15_硬件规格知识库.md",
        )
    finally:
        temp_path.unlink(missing_ok=True)


def main() -> None:
    print(f"硬件规格 RAG 文档已入库：{ingest_specs()}")


if __name__ == "__main__":
    main()
