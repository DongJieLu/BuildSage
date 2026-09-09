# EVALUATION.md

评测运行时间：2026-09-09 13:46:57

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

- **100.00%**（27/27）

### RAGAS（rag 类子集，DeepSeek 评委）

- faithfulness: **0.8203**
- answer_relevancy: **0.9352**
- context_utilization: **0.663**

### 延迟（ms，p50 / p95，含 LLM 调用）

| 通道 | p50 | p95 |
|---|---|---|
| param | 1079 | 2159 |
| compat | 1159 | 1714 |
| rag | 11963 | 15977 |
| reject | 893 | 1076 |

> rag 通道为非流式端到端（含完整生成）。前端使用 SSE 流式，实测 CPU 环境首字延迟约 9~13s
> （检索+重排 5~8s，其余为生成首 token）；瓶颈在 CPU 上的 bge-reranker 逐对打分，
> 优化方向见 INTERVIEW.md 第 6/10 条（GPU、更小 reranker、重排结果缓存）。

本报告评估耗时 443s。
