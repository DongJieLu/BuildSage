# 装机参谋 BuildSage

一个面向 DIY 装机的问答系统：**参数直查 + 装机兼容性校验 + 选购攻略问答**。
后端 FastAPI + LangChain/LangGraph，前端 Vue 3，规格数据从公开规格页抽取，攻略文档自写。

![对话问答](docs/screenshots/01_chat.png)

## 为什么做这个

装机场景里的问题其实分三类，性质完全不同：

- **参数类**（"RTX 4070 的 TDP 是多少"）——答案唯一，是查表题，用向量检索去猜没道理；
- **兼容类**（"i9-14900K 配 650W 电源够吗"）——是几个硬约束的联合判断，交给 LLM 自由发挥就是主动引入幻觉；
- **选购类**（"5000 元怎么配"）——开放问题，才需要检索 + 生成。

所以这个项目没有做"一个大 RAG 包打天下"，而是把三类问题分流到三条链路：参数查 MySQL，兼容走规则引擎，选购走混合检索 + 重排 + 生成。这也是它和一般 RAG Demo 最大的区别。

## 效果

**对话页**——每条回答带路由徽章，一眼能看出走了哪条通道：参数直查秒回参数卡片，兼容校验出逐条核验单并引用规则编号，深度问答流式输出带引用溯源。

![装机配置器](docs/screenshots/02_builder.png)

装机配置器是不打字也能用的入口：下拉选件 → 点校验 → 出核验单。这条链路完全不经过 LLM，纯规则引擎。

![规格库](docs/screenshots/03_specs.png)

规格库共 511 个型号，可搜索、按类别浏览，来源标注了是"公开规格页抽取"还是"人工整理"。

![统计看板](docs/screenshots/04_stats.png)

统计看板从 `qa_log` 聚合意图分布、策略分布、延迟和热点问题。

## 架构

```
用户问题
   │
   ├─ Redis 答案缓存命中 ──────────────── 直接返回
   │
   ├─ router_node（L1 规则词 + L2 LLM 结构化分类）
   │     ├─ param   → 槽位抽取 → 参数化 SQL 查规格库 → 参数卡片
   │     ├─ compat  → 配置清单抽取 → 规则引擎 R1~R5 → 核验单
   │     ├─ rag     → 混合检索（BM25 + 向量 RRF）→ bge-reranker 精排 → LCEL 生成
   │     └─ reject  → 拒答模板
   │
   └─ 写回缓存 + qa_log 落库
```

用 LangGraph 编排的是**确定性管道**（每个节点单一职责、无循环），不是自主 Agent 循环——参数和兼容是确定性问题，不需要 LLM 自己决定调什么工具。

**兼容规则**（`app/specs/rules.py`，纯 Python 可单测）：

| 规则 | 内容 |
|---|---|
| R1 | CPU 插槽 ↔ 主板插槽 |
| R2 | 内存代数 ↔ 主板/CPU 支持 |
| R3 | CPU 最大功耗 + GPU TDP + 80W 余量 ≤ 电源额定 |
| R4 | 显卡长度 ↔ 机箱限长 |
| R5 | PCIe 世代向下兼容提示 |

## 技术栈

| 组件 | 选型 |
|---|---|
| 编排 | LangChain 1.x + LangGraph |
| LLM | DeepSeek（langchain-openai，结构化输出走 function calling） |
| Embedding | BAAI/bge-m3（langchain-huggingface） |
| 重排 | BAAI/bge-reranker-large（CrossEncoderReranker） |
| 向量库 | Chroma（langchain-chroma） |
| 混合检索 | BM25Retriever + 向量 → EnsembleRetriever（RRF） |
| 规格库 | MySQL 8（cpu / gpu / motherboard / memory / psu 五表） |
| 缓存 | Redis（答案缓存 / 会话历史 / 并发锁） |
| 评估 | RAGAS + 自研硬指标 |
| 可观测 | Langfuse（可选，不配 key 自动降级） |
| 服务 | FastAPI（REST + SSE）· Vue 3 + Element Plus + ECharts |

## 快速开始

```bash
# 依赖
pip install -r requirements.txt

# MySQL + Redis
docker compose up -d

# 配置（填 DEEPSEEK_API_KEY，不填会降级成 Fake LLM）
cp .env.example .env

# 建表 + 导入规格库
python scripts/init_db.py
python scripts/extract_specs.py      # 可选，产物已随仓库提供
python scripts/load_specs.py

# 攻略语料入库（首次会下载 BGE-M3 权重）
python scripts/ingest_guides.py --rebuild

# 启动
uvicorn app.api.main:app --host 127.0.0.1 --port 8000
cd frontend && npm install && npm run dev
```

前端 http://127.0.0.1:5173 ，接口文档 http://127.0.0.1:8000/docs 。

## 评估

金标集是脚本自动生成的（`scripts/gen_eval_set.py --seed 42`），103 条，可复现。参数类的真值直接来自规格库字段，兼容类的真值来自规则引擎判定——同一份结构化数据既产题又产答案，不需要人工标注。

| 指标 | 结果 |
|---|---|
| 路由分流正确率 | 100%（103/103） |
| 参数直查准确率 | 94.44%（34/36） |
| 兼容判定准确率 | 96.88%，冲突规则命中 100% |
| Recall@5 | 100%（27/27） |
| RAGAS | faithfulness 0.82 / answer relevancy 0.94 / context utilization 0.66 |
| 延迟 p50 | param 1.1s · compat 1.2s · rag 12s |

完整报告见 [EVALUATION.md](EVALUATION.md)，复现命令在里面。rag 的 12s 是 CPU 上重排的串行开销，流式首字延迟约 9~13s，优化方向写在 [INTERVIEW.md](INTERVIEW.md) 里。

```bash
python -m pytest tests/ -q      # 35 项单测
```

## 目录结构

```
app/
  api/           FastAPI 服务（REST + SSE）
  config.py      配置（pydantic-settings）
  db/            MySQL / Redis 客户端与仓储
  ingest/        LangChain 入库管线（loaders → splitters → 向量化）
  llm/           ChatOpenAI 封装（DeepSeek）
  observability/ Langfuse 追踪
  rag/           路由 / 检索 / 重排 / 生成 / 缓存 / 会话 / LangGraph 管道
  rerank/        bge-reranker 适配器
  specs/         规格库仓储 / 槽位抽取 / 兼容规则引擎
frontend/        Vue 3 前端（对话 / 配置器 / 规格库 / 看板）
scripts/         抽取 / 建库 / 导库 / 入库 / 评估
tests/           单元测试
data/
  specs/         规格数据（JSON，入库源）
  docs/          选购攻略（自写）
  eval/          金标集
  SOURCES.md     数据来源与许可
```

## 数据来源

- **规格数据**：CPU/GPU 从 Wikipedia 公开规格列表抽取（CC BY-SA），PassMark 榜单补性能分；主板/内存/电源人工整理。抓取页面的原始 HTML 不入仓库，只保留抽取产物 JSON。
- **攻略文档**：14 篇自写选购指南，不含第三方版权内容。

详见 [data/SOURCES.md](data/SOURCES.md)。

## 已知限制

- CPU 数据里有少数型号插槽缺失，兼容校验时对应规则会返回"无法校验"而不是误报冲突。
- 显卡长度字段大部分没收录，R4 规则通常跳过，需要手动填机箱限长才能生效。
- 重排在 CPU 上较慢，是当前延迟的主要来源；生产环境需要 GPU 或换更小的模型。
- 价格数据是抓取时的快照，会随行情变化。
