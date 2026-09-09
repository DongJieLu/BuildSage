"""生成器单测：LCEL 链结构与拒答解析（FakeListLLM，不依赖外部服务）。"""
from langchain_core.documents import Document
from langchain_core.language_models import FakeListChatModel

from app.rag.generator import Generator


def _docs():
    return [
        Document(page_content="电源功率按 CPU 最大睿频功耗 + 显卡功耗 + 80W 余量估算。",
                 metadata={"doc_name": "电源指南.md", "title": "功率怎么算", "chunk_id": 1}),
    ]


def test_generate_normal_answer():
    llm = FakeListChatModel(responses=["根据资料，功率 = CPU 最大功耗 + 显卡 + 80W 余量 [1]。"], sleep=None)
    gen = Generator(llm=llm)
    result = gen.generate("电源功率怎么算", _docs())
    assert result.rejected is False
    assert "80W" in result.answer
    assert result.citations and result.citations[0]["doc_name"] == "电源指南.md"


def test_generate_rejects_not_found():
    llm = FakeListChatModel(responses=["未在资料中找到相关内容。"], sleep=None)
    gen = Generator(llm=llm)
    result = gen.generate("随便问点别的", _docs())
    assert result.rejected is True
    assert result.citations == []


def test_generate_empty_answer_rejects():
    llm = FakeListChatModel(responses=["   "], sleep=None)
    gen = Generator(llm=llm)
    result = gen.generate("问题", _docs())
    assert result.rejected is True


def test_stream_yields_tokens():
    llm = FakeListChatModel(responses=["第一段 第二段"], sleep=None)
    gen = Generator(llm=llm)
    tokens = list(gen.stream("电源怎么选", _docs()))
    assert "".join(tokens) == "第一段 第二段"
