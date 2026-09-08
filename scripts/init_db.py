"""初始化数据库：规格库五表 + 知识库 + 问答日志（幂等，可重复执行）。

用法：python scripts/init_db.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy import text

from app.db.mysql import get_engine

DDL_STATEMENTS = [
    # --- 规格库（结构化 RAG 通道）---
    """CREATE TABLE IF NOT EXISTS cpu (
      cpu_id       BIGINT PRIMARY KEY AUTO_INCREMENT,
      name         VARCHAR(150) NOT NULL UNIQUE,
      brand        VARCHAR(50) NOT NULL,
      socket       VARCHAR(30),
      cores        INT,
      threads      INT,
      tdp_w        INT,
      tdp_max_w    INT,
      boost_ghz    DECIMAL(4,2),
      memory_types VARCHAR(100),
      pcie_gen     INT,
      release_year INT,
      price_usd    DECIMAL(10,2),
      passmark_cpu_mark INT,
      source       VARCHAR(30) DEFAULT 'manual',
      KEY idx_socket (socket)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS gpu (
      gpu_id      BIGINT PRIMARY KEY AUTO_INCREMENT,
      name        VARCHAR(150) NOT NULL UNIQUE,
      brand       VARCHAR(50) NOT NULL,
      vram_gb     INT,
      vram_type   VARCHAR(30),
      tdp_w       INT,
      length_mm   INT,
      recommended_psu_w INT,
      pcie_gen    INT,
      release_year INT,
      msrp_usd    DECIMAL(10,2),
      passmark_g3d INT,
      source      VARCHAR(30) DEFAULT 'manual',
      KEY idx_vram (vram_gb)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS motherboard (
      mb_id        BIGINT PRIMARY KEY AUTO_INCREMENT,
      name         VARCHAR(150) NOT NULL UNIQUE,
      brand        VARCHAR(50) NOT NULL,
      chipset      VARCHAR(50),
      socket       VARCHAR(30),
      memory_types VARCHAR(100),
      form_factor  VARCHAR(20),
      pcie_gen     INT,
      release_year INT,
      source       VARCHAR(30) DEFAULT 'manual',
      KEY idx_socket (socket)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS memory (
      mem_id      BIGINT PRIMARY KEY AUTO_INCREMENT,
      name        VARCHAR(150) NOT NULL UNIQUE,
      brand       VARCHAR(50) NOT NULL,
      mem_type    VARCHAR(20),
      capacity_gb INT,
      speed_mhz   INT,
      modules     INT,
      source      VARCHAR(30) DEFAULT 'manual',
      KEY idx_type (mem_type)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS psu (
      psu_id        BIGINT PRIMARY KEY AUTO_INCREMENT,
      name          VARCHAR(150) NOT NULL UNIQUE,
      brand         VARCHAR(50) NOT NULL,
      rated_w       INT,
      certification VARCHAR(50),
      modularity    VARCHAR(30),
      atx3          TINYINT DEFAULT 0,
      source        VARCHAR(30) DEFAULT 'manual',
      KEY idx_watt (rated_w)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    # --- 知识库（非结构化 RAG 通道元数据）---
    """CREATE TABLE IF NOT EXISTS knowledge_doc (
      doc_id       BIGINT PRIMARY KEY AUTO_INCREMENT,
      file_name    VARCHAR(255) NOT NULL,
      category     VARCHAR(50) NOT NULL,
      file_type    VARCHAR(20) NOT NULL,
      chunk_count  INT DEFAULT 0,
      status       TINYINT DEFAULT 1,
      created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
      KEY idx_category (category)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS knowledge_chunk (
      chunk_id    BIGINT PRIMARY KEY AUTO_INCREMENT,
      doc_id      BIGINT NOT NULL,
      doc_name    VARCHAR(255) NOT NULL,
      category    VARCHAR(50) NOT NULL,
      title       VARCHAR(255),
      page_no     INT,
      chunk_text  MEDIUMTEXT NOT NULL,
      milvus_id   VARCHAR(64),
      created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
      KEY idx_doc (doc_id),
      KEY idx_category (category)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    # --- 问答日志（可观测性）---
    """CREATE TABLE IF NOT EXISTS qa_log (
      log_id       BIGINT PRIMARY KEY AUTO_INCREMENT,
      session_id   VARCHAR(64),
      question     TEXT NOT NULL,
      intent       VARCHAR(20),
      strategy     VARCHAR(30),
      route_detail JSON,
      evidence_ids JSON,
      answer       MEDIUMTEXT,
      latency_ms   INT,
      cache_hit    TINYINT DEFAULT 0,
      created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
      KEY idx_created (created_at),
      KEY idx_intent (intent)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
]


def main() -> None:
    engine = get_engine()
    with engine.begin() as conn:
        for ddl in DDL_STATEMENTS:
            conn.execute(text(ddl))
    print(f"建表完成：{len(DDL_STATEMENTS)} 张表")


if __name__ == "__main__":
    main()
