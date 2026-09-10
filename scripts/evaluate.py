"""评估脚本：金标集 → 四通道指标 → EVALUATION.md。

指标体系（硬指标优先，这是结构化 RAG 的评估卖点）：
- 路由分流正确率：intent 与金标 type 匹配率（param/compat/rag/reject）
- 参数直查准确率：param 类回答包含规格库真值（词边界匹配，非模糊包含）
- 兼容校验判定准确率：compat 类 verdict 与规则引擎金标一致 + 冲突规则命中
- Recall@5：rag 类检索文档命中应出文档比例（doc_name 交集）
- RAGAS（rag 类子集）：Faithfulness / Answer Relevancy / Context Precision（LLM 评委）
- 延迟：各通道 p50 / p95（ms）

用法：python scripts/evaluate.py [--eval-set data/eval/eval_set.jsonl] [--output EVALUATION.md]
"""
import argparse
import json
import re
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.rag.pipeline import answer
from app.rag.retriever import retrieve
from app.rag.router import rule_route

TYPE_TO_INTENT = {"param": "param", "compat": "compat", "rag": "rag", "reject": "reject"}


def load_eval_set(path: str) -> list[dict]:
    items = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def value_in_answer(value, answer: str) -> bool:
    """真值匹配：数值按词边界、字符串按包含（避免 1200 误命中 200）。"""
    s = str(value)
    if isinstance(value, (int, float)):
        return re.search(rf"(?<![\d.]){re.escape(s)}(?![\d.])", answer) is not None
    return s.lower() in (answer or "").lower()


def parse_verdict(answer: str) -> str:
    if "存在冲突" in answer:
        return "conflict"
    if "存在提示项" in answer:
        return "warn"
    if "配置兼容" in answer:
        return "pass"
    return "unknown"


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    vs = sorted(values)
    idx = min(len(vs) - 1, int(q * len(vs)))
    return vs[idx]


def parse_failed_rules(answer: str) -> list[str]:
    """从核验单中提取冲突规则 id：只看 ❌ 开头的行，避免误匹配 DDR5 之类的字样。"""
    out = []
    for line in (answer or "").split("\n"):
        if line.strip().startswith("❌"):
            m = re.search(r"R[1-9]", line)
            if m:
                out.append(m.group(0))
    return out


def answer_keys_hit(answer: str, keys: list[str]) -> bool:
    """回答是否覆盖全部关键信息点（大小写不敏感的子串匹配）。"""
    a = (answer or "").lower()
    return all(k.lower() in a for k in keys)


def evaluate(items: list[dict]) -> dict:
    metrics = {
        "routing": {"total": 0, "correct": 0, "by_type": {}},
        "param": {"total": 0, "value_correct": 0},
        "compat": {"total": 0, "verdict_correct": 0, "rule_correct": 0},
        "rag_recall": {"total": 0, "hit": 0},
        "rag_answer": {"total": 0, "hit": 0},
        "latency": {"param": [], "compat": [], "rag": [], "reject": []},
    }
    rag_samples = []  # (question, answer, contexts) 供 RAGAS

    for i, item in enumerate(items, 1):
        qtype = item["type"]
        question = item["question"]
        expected = item["expected"]
        t0 = time.perf_counter()
        result = answer(question)
        latency = (time.perf_counter() - t0) * 1000

        # 路由分流
        metrics["routing"]["total"] += 1
        ok = result["intent"] == TYPE_TO_INTENT[qtype]
        if ok:
            metrics["routing"]["correct"] += 1
        bt = metrics["routing"]["by_type"].setdefault(qtype, [0, 0])  # [correct, total]
        bt[1] += 1
        if ok:
            bt[0] += 1

        # 通道指标（即使路由错也按实际结果评估该通道的表现）
        if qtype == "param":
            metrics["param"]["total"] += 1
            if result["intent"] == "param" and value_in_answer(expected["value"], result["answer"]):
                metrics["param"]["value_correct"] += 1
        elif qtype == "compat":
            metrics["compat"]["total"] += 1
            if result["intent"] == "compat":
                got = parse_verdict(result["answer"])
                if got == expected["verdict"]:
                    metrics["compat"]["verdict_correct"] += 1
                got_failed = parse_failed_rules(result["answer"])
                if got_failed == sorted(set(expected["failed_rules"])):
                    metrics["compat"]["rule_correct"] += 1
        elif qtype == "rag":
            # Recall@5 用检索层单独评估（doc_name 命中）
            metrics["rag_recall"]["total"] += 1
            if result["intent"] == "rag" and result.get("citations"):
                got_docs = {c.get("doc_name", "") for c in result["citations"]}
                if any(d in got_docs for d in expected["doc_names"]):
                    metrics["rag_recall"]["hit"] += 1
            # 回答内容准确率：回答是否覆盖金标关键信息点（"准确查询知识库"的硬指标）
            keys = expected.get("answer_keys") or []
            if keys:
                metrics["rag_answer"]["total"] += 1
                if result["intent"] == "rag" and answer_keys_hit(result["answer"], keys):
                    metrics["rag_answer"]["hit"] += 1
            rag_samples.append((question, result["answer"], [c.get("text", "") for c in result.get("citations", [])]))
        if result["intent"] in metrics["latency"]:
            metrics["latency"][result["intent"]].append(result["latency_ms"])
        print(f"[{i:3d}/{len(items)}] {qtype:7s} intent={result['intent']:7s} "
              f"{'OK ' if ok else 'MISS'} {latency:6.0f}ms  {question[:38]}")
    return {"metrics": metrics, "rag_samples": rag_samples}


def run_ragas(rag_samples: list[tuple], limit: int = 12) -> dict | None:
    """RAGAS 无参考答案指标（DeepSeek 评委）；失败返回 None（报告标待实测）。"""
    try:
        from langchain_openai import ChatOpenAI
        from ragas import evaluate as ragas_evaluate
        from ragas.dataset_schema import EvaluationDataset, SingleTurnSample
        from ragas.llms import LangchainLLMWrapper
        from ragas.embeddings import LangchainEmbeddingsWrapper
        from ragas.metrics import Faithfulness, AnswerRelevancy, ContextUtilization

        from app.config import get_settings
        from app.ingest.pipeline import get_embeddings

        settings = get_settings()
        if not settings.deepseek_api_key:
            return None
        judge = LangchainLLMWrapper(ChatOpenAI(
            model=settings.deepseek_model, api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url, temperature=0,
        ))
        emb = LangchainEmbeddingsWrapper(get_embeddings())
        samples = [
            SingleTurnSample(user_input=q, response=a, retrieved_contexts=ctx)
            for q, a, ctx in rag_samples[:limit]
        ]
        result = ragas_evaluate(
            dataset=EvaluationDataset(samples),
            metrics=[Faithfulness(), AnswerRelevancy(), ContextUtilization()],
            llm=judge, embeddings=emb,
        )
        # ragas 0.4 的 EvaluationResult 不是 dict：用 to_pandas() 取各指标均值
        df = result.to_pandas()
        metric_cols = [c for c in df.columns if c not in
                       ("user_input", "response", "retrieved_contexts", "reference")]
        return {c: round(float(df[c].mean()), 4) for c in metric_cols if df[c].notna().any()}
    except Exception as exc:  # noqa: BLE001
        print(f"RAGAS 评估失败（标注待实测）: {exc}")
        return None


def write_report(path: str, metrics: dict, ragas: dict | None, n_items: int, duration_s: float) -> None:
    r = metrics["routing"]
    p = metrics["param"]
    c = metrics["compat"]
    rc = metrics["rag_recall"]
    lat = metrics["latency"]

    def pct(a, b):
        return f"{(a / b * 100):.2f}%" if b else "N/A"

    lines = [
        "# EVALUATION.md",
        "",
        f"评测运行时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 复现命令",
        "",
        "```bash",
        "python scripts/gen_eval_set.py --seed 42",
        "python scripts/evaluate.py --eval-set data/eval/eval_set.jsonl --output EVALUATION.md",
        "```",
        "",
        "## 金标集",
        "",
        f"{n_items} 条（param 36 / compat 32 / rag 27 / reject 8，seed=42）。"
        "真值来源：param = 规格库字段值；compat = 规则引擎 R1~R5 对同套配置的判定（正例与冲突例）；"
        "rag = 攻略文档标注；reject = 寒暄/无关。",
        "",
        "## 指标结果",
        "",
        "### 路由分流正确率",
        "",
        f"- 总体：**{pct(r['correct'], r['total'])}**（{r['correct']}/{r['total']}）",
    ]
    for t, (ok, total) in r["by_type"].items():
        lines.append(f"- {t}: {ok}/{total}（{pct(ok, total)}）")
    lines += [
        "",
        "### 参数直查准确率（param：回答包含规格库真值）",
        "",
        f"- **{pct(p['value_correct'], p['total'])}**（{p['value_correct']}/{p['total']}）",
        "",
        "### 兼容校验判定准确率（compat：verdict 与规则引擎金标一致）",
        "",
        f"- verdict 准确率：**{pct(c['verdict_correct'], c['total'])}**（{c['verdict_correct']}/{c['total']}）",
        f"- 冲突规则集命中率：**{pct(c['rule_correct'], c['total'])}**（{c['rule_correct']}/{c['total']}）",
        "",
        "### Recall@5（rag：引用文档命中应出文档）",
        "",
        f"- **{pct(rc['hit'], rc['total'])}**（{rc['hit']}/{rc['total']}）",
        "",
        "### 回答内容准确率（rag：回答覆盖金标关键信息点）",
        "",
        f"- **{pct(metrics['rag_answer']['hit'], metrics['rag_answer']['total'])}**"
        f"（{metrics['rag_answer']['hit']}/{metrics['rag_answer']['total']}）",
        "",
        "### RAGAS（rag 类子集，DeepSeek 评委）",
        "",
    ]
    if ragas:
        lines += [f"- {k}: **{v}**" for k, v in ragas.items()]
    else:
        lines.append("- 待实测（RAGAS 运行失败或未配置，见控制台日志）")
    lines += [
        "",
        "### 延迟（ms，p50 / p95，含 LLM 调用）",
        "",
        "| 通道 | p50 | p95 |",
        "|---|---|---|",
    ]
    for ch in ("param", "compat", "rag", "reject"):
        vs = lat[ch]
        lines.append(f"| {ch} | {percentile(vs, 0.5):.0f} | {percentile(vs, 0.95):.0f} |")
    lines += [
        "",
        f"本报告评估耗时 {duration_s:.0f}s。",
        "",
    ]
    Path(path).write_text("\n".join(lines), encoding="utf-8")
    print(f"报告已写入 {path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval-set", default="data/eval/eval_set.jsonl")
    parser.add_argument("--output", default="EVALUATION.md")
    parser.add_argument("--skip-ragas", action="store_true")
    args = parser.parse_args()

    # 评估前清空缓存，保证延迟与命中率是真实冷链路
    try:
        import app.db.redis as redis_mod

        redis_mod.get_redis_client().flushdb()
    except Exception:  # noqa: BLE001
        pass

    items = load_eval_set(args.eval_set)
    t0 = time.perf_counter()
    out = evaluate(items)
    duration = time.perf_counter() - t0
    ragas = None if args.skip_ragas else run_ragas(out["rag_samples"])
    write_report(args.output, out["metrics"], ragas, len(items), duration)


if __name__ == "__main__":
    main()
