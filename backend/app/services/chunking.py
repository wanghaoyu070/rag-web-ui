"""One parsing/splitting entry point for previews and document processing."""
from pathlib import Path
from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader, UnstructuredMarkdownLoader, TextLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from app.schemas.knowledge import ChunkConfig

PROCESSOR_VERSION = "recursive-characters-v1"


def load_and_split(local_path: str, source_name: str, config: ChunkConfig):
    extension = Path(source_name).suffix.lower()
    loaders = {".pdf": PyPDFLoader, ".docx": Docx2txtLoader, ".md": UnstructuredMarkdownLoader}
    if extension == ".txt":
        loader = TextLoader(local_path, encoding="utf-8")
    elif extension in loaders:
        loader = loaders[extension](local_path)
    else:
        raise ValueError("仅支持 PDF、DOCX、Markdown 和 TXT")
    documents = loader.load()
    for document in documents:
        document.metadata["source"] = source_name
    chunks = RecursiveCharacterTextSplitter(
        chunk_size=config.chunk_size, chunk_overlap=config.chunk_overlap
    ).split_documents(documents)
    if not chunks:
        raise ValueError("文件未提取到可用文本，请检查是否为空文件或扫描件")
    return chunks
