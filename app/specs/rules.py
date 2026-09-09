"""装机兼容性规则引擎（纯 Python，无外部依赖，可独立单测）。

输入为已解析的规格 dict（字段与 data/specs/*.json 一致），输出逐条核验结果。
每条结果引用规则编号（R1~R5）与证据数值，保证"结论可溯源"：
- R1 CPU 插槽 ↔ 主板插槽
- R2 内存代数 ↔ 主板支持（及 CPU 支持）
- R3 功耗预算：CPU 最大功耗 + GPU TDP + 80W 余量 ≤ 电源额定功率
- R4 显卡长度 ↔ 机箱限长（长度未知时降级为提示）
- R5 PCIe 世代向下兼容提示（显卡代数 > 主板代数时带宽降级）

状态：pass 通过 / conflict 冲突 / warn 可用但有提示 / skip 缺少数据无法校验。
"""
from __future__ import annotations

from dataclasses import dataclass, field

POWER_HEADROOM_W = 80   # R3：整机余量（主板/硬盘/风扇/超频冗余）


@dataclass
class CheckResult:
    rule_id: str
    status: str          # pass | conflict | warn | skip
    message: str
    evidence: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"rule_id": self.rule_id, "status": self.status,
                "message": self.message, "evidence": self.evidence}


def check_compat(
    cpu: dict | None = None,
    motherboard: dict | None = None,
    memory: dict | None = None,
    gpu: dict | None = None,
    psu: dict | None = None,
    case_limit_mm: int | None = None,
) -> list[CheckResult]:
    """对一套配置执行 R1~R5 校验。缺件不报错，对应规则返回 skip 并说明原因。"""
    return [
        _r1_socket(cpu, motherboard),
        _r2_memory(memory, motherboard, cpu),
        _r3_power(cpu, gpu, psu),
        _r4_length(gpu, case_limit_mm),
        _r5_pcie(gpu, motherboard),
    ]


def verdict(results: list[CheckResult]) -> str:
    """总体结论：有 conflict 即不通过；有 warn 即可用有提示；有 pass 即通过；
    全部 skip（信息不足）时返回 unknown —— 不能默认成"兼容"。"""
    statuses = {r.status for r in results}
    if "conflict" in statuses:
        return "conflict"
    if "warn" in statuses:
        return "warn"
    if "pass" in statuses:
        return "pass"
    return "unknown"


def _r1_socket(cpu: dict | None, mb: dict | None) -> CheckResult:
    if not cpu or not mb:
        return CheckResult("R1", "skip", "缺少 CPU 或主板，无法校验插槽")
    c, m = (cpu.get("socket") or "").upper(), (mb.get("socket") or "").upper()
    if not c or not m:
        return CheckResult("R1", "skip", "插槽信息缺失", {"cpu_socket": c, "mb_socket": m})
    ok = c == m
    return CheckResult(
        "R1", "pass" if ok else "conflict",
        f"插槽匹配：{c} ↔ {m}" if ok else f"插槽不匹配：CPU 为 {c}，主板为 {m}",
        {"cpu_socket": c, "mb_socket": m},
    )


def _r2_memory(memory: dict | None, mb: dict | None, cpu: dict | None) -> CheckResult:
    if not memory:
        return CheckResult("R2", "skip", "缺少内存，无法校验内存代数")
    mem_type = (memory.get("mem_type") or "").upper()
    cpu_types = [t.upper() for t in (cpu.get("memory_types") or [])] if cpu else []
    # 没提供主板时，若 CPU 有内存代信息，CPU 侧仍足以判断（如 AM4 只支持 DDR4）
    if not mb:
        if not mem_type or not cpu_types:
            return CheckResult("R2", "skip", "缺少主板，且 CPU 内存代信息缺失，无法校验内存代数")
        if mem_type not in cpu_types:
            return CheckResult(
                "R2", "conflict",
                f"CPU 不支持 {mem_type}：{cpu.get('name')} 仅支持 {','.join(cpu_types)}",
                {"mem_type": mem_type, "cpu_types": cpu_types},
            )
        return CheckResult(
            "R2", "pass", f"内存代数与 CPU 匹配：{mem_type}（CPU 支持 {','.join(cpu_types)}；未提供主板，未校验主板侧）",
            {"mem_type": mem_type, "cpu_types": cpu_types},
        )
    mb_types = [t.upper() for t in (mb.get("memory_types") or [])]
    if not mem_type or not mb_types:
        return CheckResult("R2", "skip", "内存代数信息缺失", {"mem_type": mem_type, "mb_types": mb_types})
    if mem_type not in mb_types:
        return CheckResult(
            "R2", "conflict",
            f"主板不支持 {mem_type}：{mb.get('name')} 支持 {','.join(mb_types)}",
            {"mem_type": mem_type, "mb_types": mb_types},
        )
    if cpu_types and mem_type not in cpu_types:
        return CheckResult(
            "R2", "conflict",
            f"CPU 不支持 {mem_type}：{cpu.get('name')} 支持 {','.join(cpu_types)}",
            {"mem_type": mem_type, "cpu_types": cpu_types, "mb_types": mb_types},
        )
    return CheckResult(
        "R2", "pass", f"内存代数匹配：{mem_type}（主板支持 {','.join(mb_types)}）",
        {"mem_type": mem_type, "mb_types": mb_types, "cpu_types": cpu_types},
    )


def _suggest_watt(required: int) -> int:
    """向上取整到常见电源瓦数档位。"""
    for w in (450, 550, 650, 750, 850, 1000, 1200, 1500):
        if required <= w:
            return w
    return 1600


def _r3_power(cpu: dict | None, gpu: dict | None, psu: dict | None) -> CheckResult:
    if not cpu or not psu:
        return CheckResult("R3", "skip", "缺少 CPU 或电源，无法核算功耗预算")
    cpu_w = cpu.get("tdp_max_w") or cpu.get("tdp_w")
    gpu_w = (gpu or {}).get("tdp_w") or 0
    if not cpu_w or not psu.get("rated_w"):
        return CheckResult("R3", "skip", "功耗信息缺失")
    required = int(cpu_w) + int(gpu_w) + POWER_HEADROOM_W
    rated = int(psu["rated_w"])
    ok = rated >= required
    return CheckResult(
        "R3", "pass" if ok else "conflict",
        (f"功耗预算通过：CPU {cpu_w}W + GPU {gpu_w}W + 余量 {POWER_HEADROOM_W}W = {required}W ≤ 电源 {rated}W"
         if ok else
         f"功耗不足：CPU {cpu_w}W + GPU {gpu_w}W + 余量 {POWER_HEADROOM_W}W = {required}W ＞ 电源 {rated}W，建议 {_suggest_watt(required)}W 及以上"),
        {"cpu_w": cpu_w, "gpu_w": gpu_w, "headroom_w": POWER_HEADROOM_W,
         "required_w": required, "psu_rated_w": rated, "suggest_w": _suggest_watt(required)},
    )


def _r4_length(gpu: dict | None, case_limit_mm: int | None) -> CheckResult:
    if not gpu:
        return CheckResult("R4", "skip", "缺少显卡，无法校验长度")
    length = gpu.get("length_mm")
    if not length:
        return CheckResult("R4", "skip", "显卡长度未知（该型号未收录长度）", {"gpu": gpu.get("name")})
    if not case_limit_mm:
        return CheckResult("R4", "skip", "未提供机箱限长，跳过长度校验", {"gpu_length_mm": length})
    ok = int(length) <= int(case_limit_mm)
    return CheckResult(
        "R4", "pass" if ok else "conflict",
        f"显卡长度 {length}mm {'≤' if ok else '＞'} 机箱限长 {case_limit_mm}mm",
        {"gpu_length_mm": int(length), "case_limit_mm": int(case_limit_mm)},
    )


def _r5_pcie(gpu: dict | None, mb: dict | None) -> CheckResult:
    if not gpu or not mb:
        return CheckResult("R5", "skip", "缺少显卡或主板，无法校验 PCIe 世代")
    g, m = gpu.get("pcie_gen"), mb.get("pcie_gen")
    if g is None or m is None:
        return CheckResult("R5", "skip", "PCIe 世代信息缺失", {"gpu_gen": g, "mb_gen": m})
    g, m = int(float(g)), int(float(m))
    if g > m:
        return CheckResult(
            "R5", "warn",
            f"显卡为 PCIe {g}.0、主板插槽为 PCIe {m}.0：可安装（向下兼容）但带宽受限",
            {"gpu_gen": g, "mb_gen": m},
        )
    return CheckResult(
        "R5", "pass", f"PCIe 世代匹配：显卡 {g}.0 ≤ 主板 {m}.0",
        {"gpu_gen": g, "mb_gen": m},
    )
