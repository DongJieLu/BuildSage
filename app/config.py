"""全局配置：全部从 .env / 环境变量读取，禁止硬编码密钥与连接串。"""
import os
from functools import lru_cache

from dotenv import dotenv_values
from pydantic_settings import BaseSettings, SettingsConfigDict

# 仅将 HF 相关变量透传到 os.environ，供 huggingface_hub 读取（需在 import 模型库前生效）。
# 不用 load_dotenv 全量加载，避免污染 os.environ 影响测试隔离。
_hf_env = dotenv_values(".env")
for _key in ("HF_ENDPOINT", "HF_HOME", "HF_HUB_DISABLE_SYMLINKS"):
    if _hf_env.get(_key):
        os.environ.setdefault(_key, _hf_env[_key])


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- LLM ---
    llm_provider: str = "mock"  # deepseek | dashscope | ollama | mock
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    dashscope_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:14b"
    llm_timeout_sec: int = 15

    # --- Embedding / Rerank（本地模型）---
    embed_model_name: str = "BAAI/bge-m3"
    embed_batch_size: int = 64
    rerank_model_name: str = "BAAI/bge-reranker-large"

    # --- MySQL ---
    mysql_host: str = "localhost"
    mysql_port: int = 3308
    mysql_user: str = "buildsage"
    mysql_password: str = "buildsage"
    mysql_db: str = "buildsage"

    # --- Redis ---
    redis_host: str = "localhost"
    redis_port: int = 6380

    # --- 向量库（开发期 Chroma）---
    chroma_persist_dir: str = "./data/chroma"

    # --- 可观测（Langfuse，缺 key 静默降级为不追踪）---
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    # --- 服务 ---
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
