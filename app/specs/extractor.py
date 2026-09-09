"""槽位与配置抽取（with_structured_output）：

- SlotExtraction：param 通道，从问题中抽出硬件类别 + 型号 + 感兴趣的字段
- BuildConfig：compat 通道，从口语化描述中抽出五类硬件型号 + 机箱限长
抽取失败/缺件时字段留空，由调用方按"未识别"处理。
"""
from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from app.llm.models import get_chat_model

logger = logging.getLogger(__name__)


class SlotExtraction(BaseModel):
    """param 通道槽位。"""

    category: str = Field(description="cpu | gpu | motherboard | memory | psu 之一；无法判断留空")
    model_name: str = Field(description="用户提到的硬件型号原文，如「RTX 4070」「i9-14900K」；未提到留空")
    fields: list[str] = Field(
        default_factory=list,
        description="用户感兴趣的参数字段英文小写，可选值：tdp_w, vram_gb, vram_type, socket, cores, "
        "threads, boost_ghz, memory_types, pcie_gen, rated_w, certification, capacity_gb, speed_mhz, "
        "chipset, form_factor, length_mm, release_year, price。未指明则留空列表",
    )


SLOT_SYSTEM_PROMPT = (
    "你是装机硬件参数的槽位抽取器。从用户问题中抽取：硬件类别（cpu/gpu/motherboard/memory/psu）、"
"型号名称（保留用户写法，可补全常见缩写如 4070→RTX 4070）、感兴趣的参数字段。"
"只输出结构化结果，不编造问题中不存在的信息。"
)


class BuildConfig(BaseModel):
    """compat 通道的配置清单。"""

    cpu: str = Field(default="", description="CPU 型号，如 i9-14900K；未提及留空")
    gpu: str = Field(default="", description="显卡型号，如 RTX 4090；未提及留空")
    motherboard: str = Field(default="", description="主板型号或芯片组，如 Z790；未提及留空")
    memory: str = Field(default="", description="内存，如「DDR5 6000 32GB」；未提及留空")
    psu: str = Field(default="", description="电源，如「650W」；未提及留空")
    cooler: str = Field(default="", description="散热器型号，如「利民PA120」「360水冷」；未提及留空")
    case: str = Field(default="", description="机箱型号，如「先马趣造」；未提及留空")
    case_limit_mm: int | None = Field(default=None, description="机箱显卡限长毫米数；未提及为 null")


CONFIG_SYSTEM_PROMPT = (
    "你是装机配置清单抽取器。从用户的口语化描述中抽出 CPU、显卡、主板、内存、电源、散热器、机箱的型号，"
    "以及机箱显卡限长（毫米）。用户没提到的部件留空字符串，限长留 null。"
    "电源若只提到瓦数（如 650W），就填「650W」。型号保留用户原文，不要自行改写。"
)


def extract_slots(question: str, llm=None) -> SlotExtraction:
    try:
        model = llm or get_chat_model()
        return model.with_structured_output(SlotExtraction, method="function_calling").invoke(
            [{"role": "system", "content": SLOT_SYSTEM_PROMPT}, {"role": "user", "content": question}]
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("槽位抽取失败: %s", exc)
        return SlotExtraction(category="", model_name="", fields=[])


def extract_config(question: str, history: list | None = None, llm=None) -> BuildConfig:
    try:
        model = llm or get_chat_model()
        return model.with_structured_output(BuildConfig, method="function_calling").invoke(
            [
                {"role": "system", "content": CONFIG_SYSTEM_PROMPT},
                {"role": "user", "content": _with_history(question, history)},
            ]
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("配置清单抽取失败: %s", exc)
        return BuildConfig()


def _with_history(question: str, history: list | None) -> str:
    if not history:
        return question
    lines = []
    for m in history[-6:]:
        role = "用户" if getattr(m, "type", "") == "human" else "助手"
        lines.append(f"{role}: {m.content}")
    lines.append(f"当前问题: {question}")
    return "\n".join(lines)
