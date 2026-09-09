# EVALUATION.md

评测运行时间：2026-09-09 13:24:01

## 复现命令

```bash
python scripts/gen_eval_set.py --seed 42
python scripts/evaluate.py --eval-set data/eval/eval_set.jsonl --output EVALUATION.md
```

## 金标集

103 条（param 36 / compat 32 / rag 27 / reject 8，seed=42）。真值来源：param = 规格库字段值；compat = 规则引擎 R1~R5 对同套配置的判定（正例与冲突例）；rag = 攻略文档标注；reject = 寒暄/无关。

## 指标结果

### 路由分流正确率

- 总体：**100.00%**（103/103）
- compat: 32/32（100.00%）
- param: 36/36（100.00%）
- rag: 27/27（100.00%）
- reject: 8/8（100.00%）

### 参数直查准确率（param：回答包含规格库真值）

- **94.44%**（34/36）

### 兼容校验判定准确率（compat：verdict 与规则引擎金标一致）

- verdict 准确率：**96.88%**（31/32）
- 冲突规则集命中率：**100.00%**（32/32）

### Recall@5（rag：引用文档命中应出文档）

- **92.59%**（25/27）

### RAGAS（rag 类子集，DeepSeek 评委）

- faithfulness: **0.9191**
- answer_relevancy: **0.9199**
- context_utilization: **0.65**

### 延迟（ms，p50 / p95，含 LLM 调用）

| 通道 | p50 | p95 |
|---|---|---|
| param | 1032 | 2216 |
| compat | 951 | 1377 |
| rag | 27647 | 39413 |
| reject | 775 | 1019 |

本报告评估耗时 882s。
