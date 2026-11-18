from io import BytesIO

import pytest

from app.config import Settings
from app.knowledge import DuplicateDocument, KnowledgeBase, UnsupportedFileType
from app.knowledge.parsing import build_chunks, parse_document, split_text
from app.knowledge.retrieval import tokenize


def make_kb(tmp_path) -> KnowledgeBase:
    return KnowledgeBase(
        Settings(_env_file=None, demo_mode=True, data_dir=tmp_path / "data")
    )


def test_markdown_parser_preserves_headings_and_chunks() -> None:
    content = (
        "# 报销制度\n\n员工需要在费用发生后 30 天内提交发票。\n\n"
        "# 年假制度\n\n入职满一年的员工每年有 10 天带薪年假。"
    )
    parsed = parse_document("员工手册.md", content.encode("utf-8"))
    headings = [section.heading for section in parsed.sections]
    assert headings == ["报销制度", "年假制度"]

    chunks = build_chunks(parsed, chunk_size=500, overlap=80)
    assert len(chunks) == 2
    assert chunks[0].heading == "报销制度"
    assert "30 天" in chunks[0].content


def test_docx_parser_reads_headings() -> None:
    from docx import Document as DocxDocument

    document = DocxDocument()
    document.add_heading("差旅制度", level=1)
    document.add_paragraph("高铁二等座可以报销。")
    buffer = BytesIO()
    document.save(buffer)

    parsed = parse_document("差旅.docx", buffer.getvalue())
    assert any(section.heading == "差旅制度" for section in parsed.sections)
    assert "高铁" in parsed.sections[0].text


def test_split_text_limits_each_chunk() -> None:
    text = "这是一个很长的段落。" * 100
    chunks = split_text(text, chunk_size=200, overlap=40)
    assert len(chunks) > 1
    assert all(len(chunk) <= 200 for chunk in chunks)


def test_chinese_tokenizer_uses_bigrams() -> None:
    tokens = tokenize("报销流程是什么")
    assert "报销" in tokens
    assert "流程" in tokens


def test_unsupported_file_type_is_rejected() -> None:
    with pytest.raises(UnsupportedFileType):
        parse_document("malware.exe", b"not a document")


def test_store_search_is_team_scoped(tmp_path) -> None:
    kb = make_kb(tmp_path)
    team = kb.create_team("产品团队")
    kb.add_document(
        team.id,
        "faq.md",
        "text/markdown",
        "# 退款政策\n\n购买后 7 天内可以无理由退款。".encode("utf-8"),
    )

    hits = kb.search(team.id, "退款期限是几天？")
    assert hits
    assert hits[0].filename == "faq.md"
    assert "7 天" in hits[0].content

    # The default team must not see another team's documents.
    assert kb.search("default", "退款期限是几天？") == []

    documents, chunks = kb.stats(team.id)
    assert documents == 1
    assert chunks == 1


def test_duplicate_and_delete_document(tmp_path) -> None:
    kb = make_kb(tmp_path)
    team = kb.create_team("运营团队")
    payload = "# 值班制度\n\n值班时间为 9:00 到 18:00。".encode("utf-8")
    document = kb.add_document(team.id, "duty.md", "text/markdown", payload)

    with pytest.raises(DuplicateDocument):
        kb.add_document(team.id, "copy.md", "text/markdown", payload)

    kb.delete_document(team.id, document.id)
    assert kb.list_documents(team.id) == []
    assert kb.search(team.id, "值班时间") == []
