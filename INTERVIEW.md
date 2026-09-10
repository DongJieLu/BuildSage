# INTERVIEW.md — 高频追问与回答要点

围绕 BuildSage 设计决策的高频追问及回答要点（面试/答辩自述参考）。

## 1. 为什么把硬件参数也纳入纯 RAG？

**要点**：为了让系统的问答链路统一，硬件参数也被整理成带有型号、字段和值的知识文档，和选购攻略一起切分、向量化并建立 BM25 索引。这样参数查询不再依赖独立短答或专用直查分支，而是统一经过召回、重排、引用和生成；规格库仍服务于配置器和独立浏览页面。

## 2. 如何区分无关问题和 RAG 问题？

**要点**：规则层只拦截空问题、寒暄和配置器固定入口，其余问题交给 LLM 做相关性判断。相关问题统一进入 RAG，非相关问题返回拒答。这样路由只负责判断“是否值得检索”，不会根据问题类型切换多套答案系统。

## 3. 为什么要做检索策略选择？

**要点**：问题清晰时用 direct；多主题问题拆成 subquery；口语化问题用 HyDE 生成检索假设；带有“它/这个”等指代时结合历史做 rewrite。每个策略最终都只产出 query，不具备工具调用权限，失败统一回退 direct，保证纯 RAG 主链路稳定。

## 4. 为什么用 LangGraph，而不是 LangChain 的 Agent 循环？

**要点**：LangGraph 在这里编排的是**确定性 RAG 管道**：缓存 → 相关性路由 → 策略化检索 → 重排 → 生成，没有自主工具调用和循环。另一个旅行规划项目才使用自主 Agent 循环；两个项目分别体现我对 RAG 质量控制和 Agent 工具编排的理解。

## 5. 混合检索怎么做的？为什么用 RRF？

**要点**：用 LangChain 的 `EnsembleRetriever` 把 `BM25Retriever`（稀疏、关键词）和 Chroma 向量检索（稠密、语义）融合。RRF（Reciprocal Rank Fusion）只按"排名倒数"求和，不看原始分数量纲——向量余弦相似度是 0~1，BM25 分数是无界实数，直接加权会被一方主导。RRF 是社区标准做法，EduRAG 里我手写过一遍，这次用 LangChain 标准组件实现，行为一致但可维护性更好。

## 6. 重排的价值和成本？

**要点**：向量/BM25 是"粗排"，CrossEncoder（bge-reranker-large）把 query 和文档拼在一起逐对打分，是"精排"，能显著提升 Top5 的相关性。成本是 CPU 环境下每对约 100~200ms，召回 50 条就要 5~10 秒。折中是把召回降到 20 条再重排到 5 条——精度损失很小（Recall@5 仍有 85%+），延迟砍掉一半以上。生产环境会上 GPU 或换更小的 reranker，或者用两阶段缓存（同一 query 的重排结果缓存）。

## 7. RAG 怎么评估？怎样证明回答真的来自知识库？

**要点**：我给每个 RAG 问题标注了应命中的文档和回答必含的关键信息点（answer_keys），分别统计 Recall@5 和回答内容准确率；同时用 RAGAS 评估 faithfulness、answer relevancy、context precision，拒答问题统计误答率。这样既验证“检索到了什么”，也验证“模型是否把检索证据答出来”，而不是只看一条主观样例。

## 8. 规格数据从哪来？抽取踩了什么坑？

**要点**：CPU/GPU 从 Wikipedia 公开规格列表抽取（CC BY-SA），PassMark 榜单补性能分，主板/内存/电源/机箱/散热器人工整理与检索校对，共 565 个型号。踩的坑：① Wikipedia 表格大量用 rowspan/colspan（型号跨行、表头跨列），直接按列头取值必然错位——写了个"网格展开器"把表还原成规则二维表再按列头语义取字段；② `find_col(headers, "a") or find_col(headers, "b")` 在返回索引 0 时是 falsy，会错误地走第二个分支，导致 Intel 品牌列丢失；③ 机箱/散热器类没有像 CPU/GPU 那样可抓的结构化页面（TechPowerUp 是 JS 渲染），用搜索代理查 ZOL/厂商官网逐款核对；④ GPU 长度以厂商官网公版数据为准，非公差异大不收录。

## 9. 缓存一致性怎么取舍？

**要点**：答案缓存 TTL 1 小时、拒答 10 分钟，容许多端短暂不一致换响应速度；文档增删后按 category 清理对应前缀缓存，属于最终一致。缓存 key 是 `qa:ans:{category}:{md5(question)}`，Redis 不可用时降级进程内存。要注意的取舍：相同问题在不同会话里会命中同一缓存，多轮上下文（rewrite 后的 query）不参与缓存 key——这是为了命中率牺牲了一点上下文相关性，因为装机问答多数是独立问题。

## 10. QPS 上来之后瓶颈在哪？

**要点**：① 重排是 CPU 密集的串行环节，解法是 GPU、小模型或重排结果缓存；② 策略决策和生成会带来额外 LLM 延迟，可按问题复杂度只对 subquery / rewrite 启用策略模型；③ BM25 索引目前在进程内存，文档量大时要换 Elasticsearch/OpenSearch 或 MySQL 全文索引；④ 多 query 检索可以并发；⑤ 答案缓存已经能挡掉重复问题。

## 11. 开发中印象最深的问题？

**要点**：① DeepSeek 不支持 OpenAI 的 `json_schema` 响应格式，`with_structured_output` 默认方法报 400，改成 `method="function_calling"` 才通——说明"OpenAI 兼容"并不等于全兼容；② langchain-huggingface 1.x 移除了 `HuggingFaceCrossEncoder`，我自己写了个 `BaseCrossEncoder` 适配器包住 sentence-transformers 的 CrossEncoder，15 行代码接回标准重排管道；③ MySQL 里 `memory_types` 存的是逗号分隔字符串，规则引擎里迭代字符串变成了逐字符 `D,D,R,5`，导致内存代数误判——这类"类型假设"的 bug 只能靠端到端测试发现。

## 12. 和另一个 Agent 项目怎么区分？

**要点**：BuildSage 打的是 **RAG 工程**牌（结构化+非结构化混合、评估驱动、延迟优化），TripAgent 打的是 **Agent 编排**牌（多工具自主决策、多轮澄清、外部 API 集成）。技术上两者都用了 LangGraph，但一个是确定性管道、一个是自主循环；框架栈上 BuildSage 用 LangChain 标准组件，另一个项目用 LangGraph + 自研工具层。面试里这两个项目回答的是不同问题："你会不会做检索质量与评估"和"你会不会做工具编排与状态管理"。
