"""Parse supported files and split their text into citable chunks."""

from __future__ import annotations

import io
import re
import unicodedata
from pathlib import Path

from app.knowledge.errors import DocumentParseError, UnsupportedFileType
from app.knowledge.models import ChunkDraft, ParsedDocument, Section

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".markdown"}
MAX_FILENAME_CHARS = 180


def sanitize_filename(filename: str) -> str:
    """Keep only the basename and strip characters that break file handling."""
    name = Path(filename).name.replace("\x00", "").strip()
    name = re.sub(r"[<>:\"/\\|?*]", "_", name)
    if not name:
        name = "document.txt"
    return name[:MAX_FILENAME_CHARS]


def detect_extension(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise UnsupportedFileType(f"unsupported file type {suffix or '(none)'}; allowed: {allowed}")
    return suffix


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise DocumentParseError("无法识别文本编码，请使用 UTF-8 或 GB18030 编码")


def _parse_pdf(data: bytes) -> ParsedDocument:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise DocumentParseError("服务端未安装 pypdf") from exc

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            reader.decrypt("")
        sections: list[Section] = []
        for page_number, page in enumerate(reader.pages, start=1):
            text = normalize_text(page.extract_text() or "")
            if text:
                sections.append(Section(text=text, page=page_number))
        if not sections:
            raise DocumentParseError("PDF 中没有可提取的文本，可能是扫描件")
        return ParsedDocument(sections=tuple(sections), page_count=len(reader.pages))
    except DocumentParseError:
        raise
    except Exception as exc:
        raise DocumentParseError(f"PDF 解析失败：{exc}") from exc


def _parse_docx(data: bytes) -> ParsedDocument:
    try:
        from docx import Document as DocxDocument
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise DocumentParseError("服务端未安装 python-docx") from exc

    try:
        document = DocxDocument(io.BytesIO(data))
        sections: list[Section] = []
        heading: str | None = None
        buffer: list[str] = []

        def flush() -> None:
            nonlocal buffer
            text = normalize_text("\n\n".join(buffer))
            if text:
                sections.append(Section(text=text, heading=heading))
            buffer = []

        for paragraph in document.paragraphs:
            text = normalize_text(paragraph.text)
            if not text:
                continue
            style = (paragraph.style.name or "").lower() if paragraph.style else ""
            if style.startswith("heading"):
                flush()
                heading = text
            else:
                buffer.append(text)

        for table in document.tables:
            rows: list[str] = []
            for row in table.rows:
                cells = [normalize_text(cell.text) for cell in row.cells]
                if any(cells):
                    rows.append(" | ".join(cells))
            if rows:
                buffer.append("\n".join(rows))

        flush()
        if not sections:
            raise DocumentParseError("DOCX 中没有可提取的文本")
        return ParsedDocument(sections=tuple(sections))
    except DocumentParseError:
        raise
    except Exception as exc:
        raise DocumentParseError(f"DOCX 解析失败：{exc}") from exc


def _parse_markdown(text: str) -> ParsedDocument:
    sections: list[Section] = []
    heading: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer
        body = normalize_text("\n\n".join(buffer))
        if body:
            sections.append(Section(text=body, heading=heading))
        buffer = []

    for line in normalize_text(text).splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            flush()
            heading = stripped.lstrip("#").strip() or heading
        else:
            buffer.append(line)
    flush()
    if not sections:
        raise DocumentParseError("Markdown 文档没有可提取的文本")
    return ParsedDocument(sections=tuple(sections))


def parse_document(filename: str, data: bytes) -> ParsedDocument:
    """Turn an uploaded file into page/heading-aware sections."""
    suffix = detect_extension(filename)
    if not data:
        raise DocumentParseError("文件为空")

    if suffix == ".pdf":
        return _parse_pdf(data)
    if suffix == ".docx":
        return _parse_docx(data)

    text = normalize_text(_decode_text(data))
    if not text:
        raise DocumentParseError("文件没有可提取的文本")
    if suffix in {".md", ".markdown"}:
        return _parse_markdown(text)
    return ParsedDocument(sections=(Section(text=text),))


def split_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Split text on paragraph boundaries while respecting a size limit."""
    text = normalize_text(text)
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    overlap = max(0, min(overlap, chunk_size // 2))
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    chunks: list[str] = []
    current = ""

    def push_current() -> None:
        nonlocal current
        if current.strip():
            chunks.append(current.strip())
        current = ""

    for paragraph in paragraphs:
        if len(paragraph) > chunk_size:
            push_current()
            start = 0
            while start < len(paragraph):
                piece = paragraph[start : start + chunk_size].strip()
                if piece:
                    chunks.append(piece)
                if start + chunk_size >= len(paragraph):
                    break
                start += max(1, chunk_size - overlap)
            continue

        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) <= chunk_size:
            current = candidate
            continue

        push_current()
        if overlap:
            tail = chunks[-1][-overlap:] if chunks else ""
            candidate = f"{tail}\n\n{paragraph}".strip()
            current = candidate if len(candidate) <= chunk_size else paragraph
        else:
            current = paragraph

    push_current()
    return chunks


def build_chunks(
    parsed: ParsedDocument,
    chunk_size: int,
    overlap: int,
) -> list[ChunkDraft]:
    chunks: list[ChunkDraft] = []
    index = 0
    for section in parsed.sections:
        text = section.text
        if section.heading and not text.startswith(section.heading):
            text = f"{section.heading}\n\n{text}"
        for part in split_text(text, chunk_size=chunk_size, overlap=overlap):
            if not part.strip():
                continue
            chunks.append(
                ChunkDraft(
                    index=index,
                    content=part,
                    page=section.page,
                    heading=section.heading,
                )
            )
            index += 1
    if not chunks:
        raise DocumentParseError("文档切分后没有有效内容")
    return chunks
