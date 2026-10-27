"""Preview immutable chunks once; ingest those exact chunks with retry-safe identity."""
import hashlib
import json
import logging
import tempfile
import uuid
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from fastapi import HTTPException
from langchain_core.documents import Document as VectorDocument
from minio.commonconfig import CopySource
from app.core.config import settings
from app.core.minio import get_minio_client
from app.db.session import SessionLocal
from app.models.knowledge import KnowledgeBase, DocumentUpload, DocumentPreview, ProcessingTask, Document, DocumentChunk
from app.services.chunking import load_and_split, PROCESSOR_VERSION
from app.services.embedding.embedding_factory import EmbeddingsFactory
from app.services.vector_store import VectorStoreFactory

logger = logging.getLogger(__name__)


def encode_snapshot(payload):
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def owned_upload(db, kb_id, user_id, upload_id):
    if not db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id, KnowledgeBase.user_id == user_id).first():
        raise HTTPException(404, "知识库不存在")
    upload = db.query(DocumentUpload).filter(
        DocumentUpload.id == upload_id, DocumentUpload.knowledge_base_id == kb_id,
    ).with_for_update().first()
    if not upload:
        raise HTTPException(404, "上传文件不存在")
    return upload


def read_snapshot(client, preview):
    response = client.get_object(settings.MINIO_BUCKET_NAME, preview.snapshot_path)
    try:
        raw = response.read()
    finally:
        response.close()
        response.release_conn()
    if hashlib.sha256(raw).hexdigest() != preview.snapshot_hash:
        raise ValueError("预览快照完整性校验失败")
    payload = json.loads(raw)
    if (payload["file_hash"] != preview.file_hash or payload["config"] != preview.config
            or payload["version"] != preview.processor_version
            or len(payload["chunks"]) != preview.chunk_count):
        raise ValueError("预览快照配置或数量不匹配")
    return payload


def create_preview(db, kb_id, user_id, upload_id, config):
    upload = owned_upload(db, kb_id, user_id, upload_id)
    if upload.status in ("processing", "completed", "expired"):
        raise HTTPException(409, "文件正在处理、已入库或已过期，请重新上传需要处理的文件")
    client = get_minio_client()
    with tempfile.TemporaryDirectory() as directory:
        path = str(Path(directory) / ("source" + Path(upload.file_name).suffix))
        client.fget_object(settings.MINIO_BUCKET_NAME, upload.temp_path, path)
        if digest_file(path) != upload.file_hash:
            raise HTTPException(409, "原文件内容与上传记录不一致，请重新上传")
        try:
            chunks = load_and_split(path, upload.file_name, config)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
    payload = {"file_hash": upload.file_hash, "version": PROCESSOR_VERSION,
               "config": config.model_dump(), "chunks": [
                   {"content": chunk.page_content, "metadata": chunk.metadata} for chunk in chunks]}
    raw = encode_snapshot(payload)
    preview_id = str(uuid.uuid4())
    snapshot_path = f"kb_{kb_id}/previews/{preview_id}.json"
    client.put_object(settings.MINIO_BUCKET_NAME, snapshot_path, BytesIO(raw), len(raw), content_type="application/json")
    if upload.current_preview_id:
        old = db.get(DocumentPreview, upload.current_preview_id)
        if old and old.status == "ready":
            old.status = "superseded"
    preview = DocumentPreview(id=preview_id, upload_id=upload.id, file_hash=upload.file_hash,
        snapshot_path=snapshot_path, snapshot_hash=hashlib.sha256(raw).hexdigest(),
        config=config.model_dump(), processor_version=PROCESSOR_VERSION,
        chunk_count=len(chunks), status="ready", expires_at=datetime.utcnow()+timedelta(hours=24))
    upload.current_preview_id = preview_id
    db.add(preview)
    try:
        db.commit()
    except Exception:
        db.rollback()
        client.remove_object(settings.MINIO_BUCKET_NAME, snapshot_path)
        raise
    return {"preview_id": preview_id, "upload_id": upload.id, "file_name": upload.file_name,
            "total_chunks": len(chunks), "chunks": payload["chunks"], "config": preview.config,
            "snapshot_hash": preview.snapshot_hash, "expires_at": preview.expires_at.isoformat()+"Z"}


def confirm_previews(db, kb_id, user_id, preview_ids):
    results, scheduled = [], []
    try:
        for preview_id in sorted(set(preview_ids)):
            preview = db.get(DocumentPreview, preview_id)
            if not preview:
                raise HTTPException(404, "预览不存在")
            upload = owned_upload(db, kb_id, user_id, preview.upload_id)
            db.refresh(preview, with_for_update=True)
            task = db.query(ProcessingTask).filter(ProcessingTask.preview_id == preview.id).with_for_update().first()
            if task and task.status in ("pending", "processing", "completed"):
                results.append({"upload_id": upload.id, "task_id": task.id, "preview_id": preview.id})
                continue
            if preview.expires_at <= datetime.utcnow():
                raise HTTPException(410, "预览已过期，请重新生成预览")
            if upload.current_preview_id != preview.id or preview.status not in ("ready", "failed"):
                raise HTTPException(409, "预览已被替换或不可用，请重新预览")
            if preview.file_hash != upload.file_hash or preview.processor_version != PROCESSOR_VERSION:
                raise HTTPException(409, "文件版本或分块版本已变化，请重新预览")
            if upload.status == "completed":
                raise HTTPException(409, "文件已入库")
            # Validate the saved payload before accepting any work; never fall back to defaults.
            try:
                read_snapshot(get_minio_client(), preview)
            except Exception as error:
                raise HTTPException(409, "预览快照无法校验，请重新生成预览") from error
            if task is None:
                task = ProcessingTask(document_upload_id=upload.id, knowledge_base_id=kb_id,
                                      preview_id=preview.id, status="pending")
                db.add(task)
            else:
                task.status, task.error_message = "pending", None
            upload.status, upload.error_message = "processing", None
            preview.status = "processing"
            db.flush()
            results.append({"upload_id": upload.id, "task_id": task.id, "preview_id": preview.id})
            scheduled.append(task.id)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return results, scheduled


def vector_ids(preview_id, count):
    return [str(uuid.uuid5(uuid.NAMESPACE_URL, f"rag-preview:{preview_id}:{index}")) for index in range(count)]


def ingest_preview(task_id):
    db = SessionLocal()
    store = None
    ids = []
    try:
        task = db.query(ProcessingTask).filter(ProcessingTask.id == task_id).with_for_update().first()
        if not task or task.status != "pending":
            return
        task.status = "processing"
        db.commit()
        preview = db.get(DocumentPreview, task.preview_id)
        upload = db.get(DocumentUpload, task.document_upload_id)
        client = get_minio_client()
        payload = read_snapshot(client, preview)
        if upload.file_hash != preview.file_hash:
            raise ValueError("文件版本已变化")
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory)/"original")
            client.fget_object(settings.MINIO_BUCKET_NAME, upload.temp_path, path)
            if digest_file(path) != preview.file_hash:
                raise ValueError("原文件哈希不匹配，请重新上传")
        # Keep originals at a unique path; no destructive move or same-name overwrite.
        permanent_path = f"kb_{upload.knowledge_base_id}/documents/{preview.id}/{upload.file_name}"
        client.copy_object(settings.MINIO_BUCKET_NAME, permanent_path,
                           CopySource(settings.MINIO_BUCKET_NAME, upload.temp_path))
        document = Document(file_name=upload.file_name, file_path=permanent_path,
            file_hash=upload.file_hash, file_size=upload.file_size, content_type=upload.content_type,
            knowledge_base_id=upload.knowledge_base_id, preview_id=preview.id,
            chunk_config={**preview.config, "strategy": "recursive", "unit": "characters", "version": preview.processor_version},
            chunk_count=preview.chunk_count)
        db.add(document)
        db.flush()
        ids = vector_ids(preview.id, preview.chunk_count)
        vectors = []
        for index, (chunk, chunk_id) in enumerate(zip(payload["chunks"], ids)):
            metadata = {**chunk["metadata"], "chunk_id": chunk_id, "document_id": document.id,
                        "kb_id": upload.knowledge_base_id, "file_name": upload.file_name,
                        "preview_id": preview.id, "chunk_index": index}
            vectors.append(VectorDocument(page_content=chunk["content"], metadata=metadata))
            db.add(DocumentChunk(id=chunk_id, document_id=document.id, kb_id=upload.knowledge_base_id,
                file_name=upload.file_name, chunk_index=index,
                chunk_metadata={"page_content": chunk["content"], "preview_metadata": chunk["metadata"], **metadata},
                hash=hashlib.sha256(encode_snapshot(chunk)).hexdigest()))
        store = VectorStoreFactory.create(store_type=settings.VECTOR_STORE_TYPE,
            collection_name=f"kb_{upload.knowledge_base_id}", embedding_function=EmbeddingsFactory.create())
        # Idempotent even after partial vector writes or a lost worker response.
        store.delete(ids)
        store.add_documents(vectors, ids=ids)
        saved = store.get_documents(ids)
        if len(saved) != len(vectors) or any(
            saved[key].page_content != vector.page_content or saved[key].metadata != vector.metadata
            for key, vector in zip(ids, vectors)
        ):
            raise ValueError("向量库片段内容、来源或数量校验失败")
        db.flush()
        if db.query(DocumentChunk).filter(DocumentChunk.document_id == document.id).count() != preview.chunk_count:
            raise ValueError("数据库片段数量校验失败")
        task.status, task.document_id = "completed", document.id
        upload.status, preview.status = "completed", "completed"
        db.commit()
        try:
            client.remove_object(settings.MINIO_BUCKET_NAME, upload.temp_path)
        except Exception as cleanup_error:
            logger.warning("Completed upload temp cleanup deferred (%s)", type(cleanup_error).__name__)
    except Exception as error:
        db.rollback()
        task = db.get(ProcessingTask, task_id)
        if task and task.status == "completed":
            # A commit acknowledgement can be lost after the transaction succeeded.
            return
        cleanup_failed = False
        if store is not None and ids:
            try:
                store.delete(ids)
            except Exception as cleanup_error:
                cleanup_failed = True
                logger.error("Task %s vector cleanup failed (%s); retry uses stable IDs", task_id, type(cleanup_error).__name__)
        task = db.get(ProcessingTask, task_id)
        if task:
            task.status = "failed"
            task.error_message = f"处理失败（{type(error).__name__}），可重试；请检查原文件或服务连接。" + ("部分向量待重试清理。" if cleanup_failed else "")
            upload = db.get(DocumentUpload, task.document_upload_id)
            preview = db.get(DocumentPreview, task.preview_id)
            if upload:
                upload.status, upload.error_message = "failed", task.error_message
            if preview:
                preview.status = "failed"
            db.commit()
        logger.error("Snapshot ingestion task %s failed (%s)", task_id, type(error).__name__)
    finally:
        db.close()


def recover_interrupted_ingestions():
    """The deployed service runs one worker; mark abandoned jobs retryable on startup."""
    with SessionLocal() as db:
        tasks = db.query(ProcessingTask).filter(
            ProcessingTask.preview_id.isnot(None), ProcessingTask.status.in_(["pending", "processing"])
        ).all()
        for task in tasks:
            task.status = "failed"
            task.error_message = "服务重启中断了处理，请重试同一预览。"
            upload = db.get(DocumentUpload, task.document_upload_id)
            preview = db.get(DocumentPreview, task.preview_id)
            if upload:
                upload.status = "failed"
            if preview:
                preview.status = "failed"
        db.commit()
