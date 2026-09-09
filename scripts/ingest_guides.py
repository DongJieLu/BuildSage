"""把 data/docs/*.md 选购攻略入库（LangChain 管线 → Chroma + MySQL）。

用法：python scripts/ingest_guides.py [--rebuild]
--rebuild：清空 knowledge_doc/chunk 与 Chroma 后重灌（幂等）。
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.ingest.pipeline import get_vectorstore
from app.ingest.repository import KnowledgeRepository
from app.ingest.service import IngestService

DOCS_DIR = Path(__file__).resolve().parent.parent / "data" / "docs"
CATEGORY = "guide"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rebuild", action="store_true", help="清空知识库后重灌")
    args = parser.parse_args()

    if args.rebuild:
        repo = KnowledgeRepository()
        docs = repo.list_documents()
        with repo._engine.begin() as conn:
            from sqlalchemy import text

            conn.execute(text("DELETE FROM knowledge_chunk"))
            conn.execute(text("DELETE FROM knowledge_doc"))
        try:
            get_vectorstore()._collection.delete(where={"category": CATEGORY})
        except Exception:  # noqa: BLE001
            pass
        print(f"已清空 {len(docs)} 篇旧文档")

    svc = IngestService()
    md_files = sorted(DOCS_DIR.glob("*.md"))
    total_chunks = 0
    for f in md_files:
        try:
            r = svc.ingest_file(f, CATEGORY)
            total_chunks += r["chunk_count"]
            print(f"{f.name:42s} doc_id={r['doc_id']:3d} chunks={r['chunk_count']}")
        except Exception as exc:  # noqa: BLE001
            print(f"{f.name:42s} FAILED: {exc}")
    print(f"共入库 {len(md_files)} 篇 / {total_chunks} chunks")


if __name__ == "__main__":
    main()
