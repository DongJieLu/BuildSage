# 数据来源与许可

本项目语料分两类：**结构化规格数据**与**非结构化攻略文档**。原始抓取页面（`data/docs/*.html`）不进入版本库，仓库仅保留抽取产物与自建内容。

## 结构化规格（data/specs/*.json）

| 文件 | 内容 | 来源 | 许可/说明 |
|---|---|---|---|
| `cpu_intel.json` | Intel CPU 227 条（Skylake 起，含 Core Ultra） | 英文 Wikipedia "List of Intel processors" 系列页面，`scripts/extract_specs.py` 自动抽取 | 事实数据；页面内容 CC BY-SA 4.0，抽取产物注明来源 |
| `gpu_nvidia.json` | NVIDIA GPU 89 条（GTX 10 系起） | 英文 Wikipedia "List of Nvidia graphics processing units" | 同上 |
| `gpu_amd.json` | AMD GPU 76 条（RX 400 系起） | 英文 Wikipedia "List of AMD graphics processing units" | 同上 |
| `cpu_amd.json` | AMD 桌面 CPU 24 条（锐龙 3000~9000 系） | 人工整理（厂商公开规格） | 事实数据 |
| `motherboard.json` | 主板 32 款 | 人工整理（厂商公开规格） | 事实数据 |
| `memory.json` | 内存 24 款 | 人工整理（厂商公开规格） | 事实数据 |
| `psu.json` | 电源 28 款 | 人工整理（厂商公开规格） | 事实数据 |

- PassMark 榜单（`passmark_cpu_list.html` / `passmark_gpu_list.html`）仅用于抽取**性能分数**，原始页面与数据不随仓库分发；PassMark 数据库条款限制再分发，产物中仅保留分数值并在 `source` 字段标注。
- 所有型号的**规格参数（如 TDP、插槽、显存）属于事实信息**，不受版权保护；抓取页面的**排版与文字**受版权保护，故不入库。
- 数据为 2026-09 时点的公开规格，价格与在售状态会变化，仅供学习与演示。

## 非结构化攻略（data/docs/*.md）

14 篇选购攻略均为**项目自写**，不含第三方受版权保护内容：

| 文件 | 主题 |
|---|---|
| 01_电源选购与功率计算.md | 功率估算公式、瓦数档位、80PLUS 认证、ATX 3.0 |
| 02_DDR4与DDR5怎么选.md | 平台代数、甜点频率、容量选择 |
| 03_CPU选购指南.md | 游戏/生产力分水岭、Intel/AMD 平台速览 |
| 04_显卡选购指南.md | 分辨率档位、显存、A/N 卡、功耗匹配 |
| 05_主板选购指南.md | 插槽/内存代/芯片组/供电 |
| 06_内存容量与频率指南.md | 容量分界、双通道、频率时序 |
| 07_5000元装机配置.md | 1080P 配置清单与思路 |
| 08_8000元装机配置.md | 2K 配置清单与思路 |
| 09_15000元装机配置.md | 4K/生产力配置清单与思路 |
| 10_散热器选购指南.md | 风冷/水冷、按功耗选散热 |
| 11_机箱与风道指南.md | 风道原理、兼容性核对 |
| 12_PCIe世代与带宽科普.md | 世代带宽、向下兼容、实际影响 |
| 13_装机兼容性避坑清单.md | R1~R5 对应的自查流程 |
| 14_固态硬盘选购指南.md | 接口协议、容量、颗粒主控 |

## 评估数据（data/eval/eval_set.jsonl）

由 `scripts/gen_eval_set.py --seed 42` 自动生成（103 条）：参数类真值来自规格库字段、兼容类真值来自规则引擎判定、攻略类为文档标注、拒答类为固定寒暄集。可复现，不含人工标注漂移。
