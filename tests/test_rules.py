"""兼容性规则引擎单测：R1~R5 全分支（纯 Python，无需数据库）。"""
from app.specs.rules import check_compat, verdict

CPU_LGA1700 = {"name": "Intel Core i9-14900K", "socket": "LGA1700", "tdp_w": 125, "tdp_max_w": 253, "memory_types": ["DDR4", "DDR5"]}
CPU_AM5 = {"name": "AMD Ryzen 7 7800X3D", "socket": "AM5", "tdp_w": 120, "memory_types": ["DDR5"]}
MB_LGA1700_DDR5 = {"name": "MSI MAG Z790 TOMAHAWK MAX WIFI", "socket": "LGA1700", "memory_types": ["DDR5"], "pcie_gen": 5}
MB_LGA1700_DDR4 = {"name": "ASUS PRIME B760-PLUS D4", "socket": "LGA1700", "memory_types": ["DDR4"], "pcie_gen": 4}
MEM_DDR5 = {"name": "G.Skill Flare X5 DDR5 6000 32GB", "mem_type": "DDR5"}
MEM_DDR4 = {"name": "Corsair Vengeance LPX DDR4 3200 32GB", "mem_type": "DDR4"}
GPU_4090 = {"name": "GeForce RTX 4090", "tdp_w": 450, "pcie_gen": 4, "length_mm": 336}
GPU_50_GEN5 = {"name": "GeForce RTX 5080", "tdp_w": 360, "pcie_gen": 5, "length_mm": 304}
PSU_650 = {"name": "MSI MAG A650BN", "rated_w": 650}
PSU_850 = {"name": "Corsair RM850e", "rated_w": 850}


def by_rule(results, rule_id):
    return next(r for r in results if r.rule_id == rule_id)


def test_r1_pass():
    r = by_rule(check_compat(cpu=CPU_LGA1700, motherboard=MB_LGA1700_DDR5), "R1")
    assert r.status == "pass"


def test_r1_conflict():
    r = by_rule(check_compat(cpu=CPU_AM5, motherboard=MB_LGA1700_DDR5), "R1")
    assert r.status == "conflict"
    assert "AM5" in r.message and "LGA1700" in r.message


def test_r1_skip_when_missing():
    r = by_rule(check_compat(cpu=CPU_AM5), "R1")
    assert r.status == "skip"


def test_r2_pass():
    r = by_rule(check_compat(cpu=CPU_LGA1700, motherboard=MB_LGA1700_DDR5, memory=MEM_DDR5), "R2")
    assert r.status == "pass"


def test_r2_conflict_mb_not_support():
    r = by_rule(check_compat(cpu=CPU_LGA1700, motherboard=MB_LGA1700_DDR5, memory=MEM_DDR4), "R2")
    assert r.status == "conflict"


def test_r2_conflict_cpu_not_support():
    # AM4 CPU 只支持 DDR4，插 DDR5 内存（主板为 DDR4 板则 R2 先冲突主板侧，这里给 DDR5 板）
    am4_cpu = {"name": "AMD Ryzen 5 5600X", "socket": "AM4", "tdp_w": 65, "memory_types": ["DDR4"]}
    mb_am5 = {"name": "MSI PRO B650M-A WIFI", "socket": "AM5", "memory_types": ["DDR5"], "pcie_gen": 4}
    r = by_rule(check_compat(cpu=am4_cpu, motherboard=mb_am5, memory=MEM_DDR5), "R2")
    assert r.status == "conflict"
    assert "CPU" in r.message


def test_r3_pass_with_headroom():
    r = by_rule(check_compat(cpu=CPU_LGA1700, gpu=GPU_4090, psu=PSU_850), "R3")
    # 253 + 450 + 80 = 783 ≤ 850
    assert r.status == "pass"
    assert r.evidence["required_w"] == 783


def test_r3_conflict_and_suggest():
    r = by_rule(check_compat(cpu=CPU_LGA1700, gpu=GPU_4090, psu=PSU_650), "R3")
    assert r.status == "conflict"
    assert r.evidence["required_w"] == 783
    assert r.evidence["suggest_w"] == 850


def test_r3_uses_tdp_max():
    # 无独立显卡时：125 + 0 + 80 = 205 ≤ 650
    r = by_rule(check_compat(cpu=CPU_LGA1700, psu=PSU_650), "R3")
    assert r.status == "pass"
    assert r.evidence["cpu_w"] == 253  # 用 tdp_max_w 而非基础 125


def test_r3_skip_without_cpu():
    r = by_rule(check_compat(gpu=GPU_4090, psu=PSU_850), "R3")
    assert r.status == "skip"


def test_r4_pass_and_conflict():
    r = by_rule(check_compat(gpu=GPU_4090, case_limit_mm=355), "R4")
    assert r.status == "pass"
    r = by_rule(check_compat(gpu=GPU_4090, case_limit_mm=300), "R4")
    assert r.status == "conflict"


def test_r4_skip_unknown_length():
    gpu = {"name": "某显卡", "tdp_w": 200, "length_mm": None}
    r = by_rule(check_compat(gpu=gpu, case_limit_mm=355), "R4")
    assert r.status == "skip"


def test_r5_warn_downgrade():
    r = by_rule(check_compat(gpu=GPU_50_GEN5, motherboard=MB_LGA1700_DDR4), "R5")
    assert r.status == "warn"


def test_r5_pass():
    r = by_rule(check_compat(gpu=GPU_4090, motherboard=MB_LGA1700_DDR5), "R5")
    assert r.status == "pass"


def test_verdict_priority():
    full = check_compat(cpu=CPU_AM5, motherboard=MB_LGA1700_DDR5, memory=MEM_DDR5, gpu=GPU_4090, psu=PSU_650)
    assert verdict(full) == "conflict"          # R1/R3 冲突
    warn_case = check_compat(cpu=CPU_LGA1700, motherboard=MB_LGA1700_DDR4, memory=MEM_DDR4, gpu=GPU_50_GEN5, psu=PSU_850)
    assert verdict(warn_case) == "warn"         # 仅 R5 提示
    ok_case = check_compat(cpu=CPU_LGA1700, motherboard=MB_LGA1700_DDR5, memory=MEM_DDR5, gpu=GPU_4090, psu=PSU_850, case_limit_mm=355)
    assert verdict(ok_case) == "pass"


def test_verdict_unknown_when_all_skip():
    """全部规则跳过（信息不足）不能默认判成"兼容"。"""
    assert verdict(check_compat()) == "unknown"
    assert verdict(check_compat(cpu={"name": "某 CPU"})) == "unknown"


def test_r2_cpu_only_catches_wrong_memory_gen():
    """只给 CPU + 内存、没给主板时，CPU 侧内存代仍应能判否（5500X3D 是 AM4/DDR4）。"""
    cpu_5500x3d = {"name": "AMD Ryzen 5 5500X3D", "socket": "AM4", "tdp_w": 105, "memory_types": ["DDR4"]}
    r = by_rule(check_compat(cpu=cpu_5500x3d, memory=MEM_DDR5), "R2")
    assert r.status == "conflict"
    assert "DDR4" in r.message


def test_r2_cpu_only_pass_when_matching():
    cpu_5500x3d = {"name": "AMD Ryzen 5 5500X3D", "socket": "AM4", "tdp_w": 105, "memory_types": ["DDR4"]}
    r = by_rule(check_compat(cpu=cpu_5500x3d, memory=MEM_DDR4), "R2")
    assert r.status == "pass"


# ---- 平台级内存代兜底规则（数据缺 memory_types 时按插槽推断）----

def test_platform_rule_am5_rejects_ddr4():
    """AM5 CPU 数据里没写内存代时，平台规则仍应判 DDR4 冲突。"""
    cpu = {"name": "某 AM5 CPU", "socket": "AM5", "tdp_w": 65}
    r = by_rule(check_compat(cpu=cpu, memory=MEM_DDR4), "R2")
    assert r.status == "conflict"
    assert "DDR5" in r.message and "平台规则" in r.message


def test_platform_rule_am4_rejects_ddr5():
    cpu = {"name": "某 AM4 CPU", "socket": "AM4", "tdp_w": 65}
    r = by_rule(check_compat(cpu=cpu, memory=MEM_DDR5), "R2")
    assert r.status == "conflict"


def test_platform_rule_am5_motherboard_rejects_ddr4():
    mb = {"name": "某 B650 主板", "socket": "AM5", "pcie_gen": 4}
    r = by_rule(check_compat(motherboard=mb, memory=MEM_DDR4), "R2")
    assert r.status == "conflict"


def test_platform_rule_does_not_cover_lga1700():
    """LGA1700 同一插槽有 DDR4/DDR5 两种主板，不能按平台一刀切。"""
    cpu = {"name": "某 LGA1700 CPU", "socket": "LGA1700", "tdp_w": 65}
    for mem in (MEM_DDR4, MEM_DDR5):
        r = by_rule(check_compat(cpu=cpu, memory=mem), "R2")
        assert r.status == "skip", mem


def test_platform_rule_lga2066_rejects_ddr5():
    """LGA2066 是 DDR4 平台，数据缺内存代时按平台规则兜底。"""
    cpu = {"name": "Intel Core i9-7900X", "socket": "LGA2066", "tdp_w": 140}
    r = by_rule(check_compat(cpu=cpu, memory=MEM_DDR5), "R2")
    assert r.status == "conflict"


def test_data_beats_platform_rule():
    """规格数据里的 memory_types 优先于平台规则。"""
    cpu = {"name": "特殊 CPU", "socket": "AM5", "tdp_w": 65, "memory_types": ["DDR4", "DDR5"]}
    r = by_rule(check_compat(cpu=cpu, memory=MEM_DDR4), "R2")
    assert r.status == "pass"
    assert "平台规则" not in r.message
