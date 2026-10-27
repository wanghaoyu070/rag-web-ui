"""Read-only comparisons for stored documents; saved choices for new uploads."""
import hashlib
from pathlib import Path
from fastapi import HTTPException
from app.core.config import settings
from app.core.minio import get_minio_client
from app.models.knowledge import KnowledgeBase, Document
from app.services.chunking import split_text, chunk_statistics
from app.services.preview_ingestion import owned_upload, create_preview


def compare(db, kb_id, user_id, request):
    client = get_minio_client()
    if request.upload_id is not None:
        source = owned_upload(db, kb_id, user_id, request.upload_id)
        if source.status in ("processing", "completed", "expired"):
            raise HTTPException(409, "该上传文件正在处理、已入库或已过期，请重新选择文件")
        object_path = source.temp_path
    else:
        source = db.query(Document).join(KnowledgeBase).filter(
            Document.id == request.document_id, Document.knowledge_base_id == kb_id,
            KnowledgeBase.user_id == user_id).first()
        if not source:
            raise HTTPException(404, "文档不存在")
        object_path = source.file_path
    if Path(source.file_name).suffix.lower() not in (".txt", ".md"):
        raise HTTPException(422, "分块实验室目前支持 TXT、Markdown，请选择其他文档")
    response = client.get_object(settings.MINIO_BUCKET_NAME, object_path)
    try:
        raw = response.read(800001)
    finally:
        response.close()
        response.release_conn()
    if len(raw) > 800000:
        raise HTTPException(422, "实验文档请控制在800KB以内")
    if hashlib.sha256(raw).hexdigest() != source.file_hash:
        raise HTTPException(409, "原文件哈希不匹配，请检查文件存储")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise HTTPException(422, "请使用UTF-8编码的文本") from error
    # Match TextLoader universal newline decoding, including CRLF documents.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if len(text) > 200000:
        raise HTTPException(422, "实验文档请控制在20万字符以内")
    prepared = []
    try:
        for config in request.configs:
            chunks = split_text(text, source.file_name, config)
            if len(chunks) > 2000:
                raise HTTPException(422, "单种策略最多展示2000个片段，请增加片段长度")
            prepared.append((config, chunks))
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    results = []
    for config, chunks in prepared:
        preview = create_preview(db, kb_id, user_id, source.id, config, experimental=True) if request.upload_id is not None else None
        serialized = [{"content": c.page_content, "metadata": c.metadata} for c in chunks]
        if preview and preview["chunks"] != serialized:
            raise HTTPException(409, "实验结果与保存快照不一致，请重新生成")
        results.append({"config": config.model_dump(), "statistics": chunk_statistics(chunks),
                        "chunks": serialized, "preview_id": preview["preview_id"] if preview else None,
                        "expires_at": preview["expires_at"] if preview else None})
    db.commit()
    return {"file_name": source.file_name, "source_text": text, "results": results,
            "can_ingest": request.upload_id is not None}
