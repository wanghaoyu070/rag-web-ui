"""Shared splitters. Character ranges always refer to the parsed source text."""
import re
from pathlib import Path
from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader, TextLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from app.schemas.knowledge import ChunkConfig

PROCESSOR_VERSION = "characters-v2"


def heading_sections(text):
    """Preserve exact ATX heading offsets; do not interpret fenced code as headings."""
    sections, stack = [], []
    start, position, path, fence = 0, 0, "", None
    for line in text.splitlines(keepends=True):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line.rstrip("\r\n"))
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= fence[1] and not marker[2].strip():
                fence = None
        elif marker:
            fence = (marker[1][0], len(marker[1]))
        else:
            header = re.match(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?)|[ \t]*)$", line.rstrip("\r\n"))
            if header:
                if position > start:
                    sections.append((start, position, path))
                level = len(header[1])
                title = re.sub(r"[ \t]+#+[ \t]*$", "", header[2] or "").strip()
                stack = [(depth, name) for depth, name in stack if depth < level] + [(level, title)]
                path = " / ".join(name for _, name in stack if name)
                start = position
        position += len(line)
    if position > start:
        sections.append((start, position, path))
    return sections


def split_text(text, source_name, config, metadata=None):
    metadata = {**(metadata or {}), "source": source_name}
    chunks = []
    if config.strategy == "fixed":
        stride = config.chunk_size - config.chunk_overlap
        for start in range(0, len(text), stride):
            content = text[start:start + config.chunk_size]
            if content.strip():
                chunks.append(Document(page_content=content, metadata={**metadata, "start_index": start, "end_index": start + len(content)}))
            if start + config.chunk_size >= len(text):
                break
    else:
        sections = heading_sections(text) if config.strategy == "heading" else [(0, len(text), "")]
        splitter = RecursiveCharacterTextSplitter(chunk_size=config.chunk_size, chunk_overlap=config.chunk_overlap, add_start_index=True)
        for start, end, heading in sections:
            for chunk in splitter.create_documents([text[start:end]], [metadata]):
                local_start = chunk.metadata["start_index"]
                if local_start < 0:
                    raise ValueError("无法定位片段在原文中的位置")
                chunk.metadata.update(start_index=start + local_start, end_index=start + local_start + len(chunk.page_content))
                if config.strategy == "heading":
                    chunk.metadata["heading_path"] = heading
                chunks.append(chunk)
    if not chunks:
        raise ValueError("文件未提取到可用文本，请检查是否为空文件或扫描件")
    return chunks


def load_and_split(local_path: str, source_name: str, config: ChunkConfig):
    extension = Path(source_name).suffix.lower()
    if config.strategy != "recursive" and extension not in (".txt", ".md"):
        raise ValueError("固定字符与标题策略目前仅支持 TXT、Markdown")
    if extension in (".txt", ".md"):
        documents = TextLoader(local_path, encoding="utf-8").load()
    elif extension == ".pdf":
        documents = PyPDFLoader(local_path).load()
    elif extension == ".docx":
        documents = Docx2txtLoader(local_path).load()
    else:
        raise ValueError("仅支持 PDF、DOCX、Markdown 和 TXT")
    chunks = []
    for document in documents:
        if document.page_content.strip():
            chunks.extend(split_text(document.page_content, source_name, config, document.metadata))
    if not chunks:
        raise ValueError("文件未提取到可用文本，请检查是否为空文件或扫描件")
    return chunks


def chunk_statistics(chunks):
    lengths = [len(chunk.page_content) for chunk in chunks]
    covered, right = 0, 0
    for chunk in sorted(chunks, key=lambda item: item.metadata["start_index"]):
        start, end = chunk.metadata["start_index"], chunk.metadata["end_index"]
        covered += max(0, end - max(start, right))
        right = max(right, end)
    total = sum(lengths)
    return {"count": len(chunks), "average_length": round(total / len(chunks), 1),
            "min_length": min(lengths), "max_length": max(lengths),
            "overlap_ratio": round((total - covered) / total, 4)}
