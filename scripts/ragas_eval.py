"""RAGAS 单独评估：复用答案缓存快速收集 rag 样本 → DeepSeek 评委打分 → 回填 EVALUATION.md。

用法：python scripts/ragas_eval.py [--eval-set data/eval/eval_set.jsonl] [--output EVALUATION.md] [--limit 12]
说明：先跑过 scripts/evaluate.py 后，rag 答案仍在 Redis 缓存中，本脚本几乎瞬时完成采样。
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.rag.pipeline import answer
from scripts.evaluate import load_eval_set, run_ragas


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval-set", default="data/eval/eval_set.jsonl")
    parser.add_argument("--output", default="EVALUATION.md")
    parser.add_argument("--limit", type=int, default=12)
    args = parser.parse_args()

    items = [i for i in load_eval_set(args.eval_set) if i["type"] == "rag"]
    samples = []
    for i, item in enumerate(items, 1):
        r = answer(item["question"])
        if r.get("intent") == "rag" and r.get("citations"):
            samples.append((item["question"], r["answer"], [c.get("text", "") for c in r["citations"]]))
        print(f"[{i:2d}/{len(items)}] {item['question'][:40]} cache={r.get('cache_hit')}")

    ragas = run_ragas(samples, limit=args.limit)
    if not ragas:
        print("RAGAS 未产出结果，EVALUATION.md 保持不变")
        return
    print("RAGAS:", ragas)

    path = Path(args.output)
    text = path.read_text(encoding="utf-8")
    block = "\n".join(f"- {k}: **{v}**" for k, v in ragas.items())
    text = re.sub(
        r"(### RAGAS（rag 类子集，DeepSeek 评委）\n\n)(?:- .*\n)+",
        lambda m: m.group(1) + block + "\n",
        text,
    )
    path.write_text(text, encoding="utf-8")
    print(f"已回填 {args.output}")


if __name__ == "__main__":
    main()
