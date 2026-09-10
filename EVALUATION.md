# EVALUATION.md

评测运行时间：2026-09-10 18:08:45

## 复现命令

```bash
python scripts/gen_eval_set.py --seed 42
python scripts/evaluate.py --eval-set data/eval/eval_set.jsonl --output EVALUATION.md
```

## 金标集

103 条（param 36 / compat 32 / rag 27 / reject 8，seed=42）。真值来源：param = 规格库字段值；compat = 规则引擎 R1~R5 对同套配置的判定（正例与冲突例）；rag = 攻略文档标注；reject = 寒暄/无关。

## 指标结果

### 应答分流正确率（param/rag 题进入 RAG 回答，reject 题被拒答）

- 总体：**98.59%**（70/71）
- param: 35/36（97.22%）
- rag: 27/27（100.00%）
- reject: 8/8（100.00%）

### 参数问题回答准确率（param：经 RAG 检索规格知识文档后，回答包含规格库真值）

- **97.22%**（35/36）

### 兼容校验判定准确率（compat：配置器规则引擎入口，verdict 与金标一致）

- verdict 准确率：**100.00%**（32/32）
- 冲突规则集命中率：**100.00%**（32/32）

### Recall@5（rag：引用文档命中应出文档）

- **85.19%**（23/27）

### 回答内容准确率（rag：回答覆盖金标关键信息点）

- **85.19%**（23/27）

### RAGAS（rag 类子集，DeepSeek 评委）

- faithfulness: **0.6094**
- answer_relevancy: **0.8107**
- context_utilization: **0.2731**

### 延迟（ms，p50 / p95，含 LLM 调用）

| 通道 | p50 | p95 |
|---|---|---|
| param | 0 | 0 |
| compat | 1047 | 1649 |
| rag | 16830 | 124826 |
| reject | 1005 | 1456 |

本报告评估耗时 2931s。
