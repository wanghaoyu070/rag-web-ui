import hashlib
from typing import List, Any, Dict
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks, Query
from sqlalchemy.orm import Session
from langchain_chroma import Chroma
from sqlalchemy import text
import logging
from datetime import datetime, timedelta
from pydantic import BaseModel
from sqlalchemy.orm import selectinload
import time
import asyncio
import uuid
import mimetypes
from pathlib import Path

from app.db.session import get_db
from app.models.user import User
from app.core.security import get_current_user
from app.models.knowledge import KnowledgeBase, Document, ProcessingTask, DocumentChunk, DocumentUpload, DocumentPreview
from app.schemas.knowledge import (
    KnowledgeBaseCreate,
    KnowledgeBaseResponse,
    KnowledgeBaseUpdate,
    DocumentResponse,
    PreviewRequest, ChunkConfig, ProcessPreviewsRequest
)
from app.services.preview_ingestion import create_preview, confirm_previews, ingest_preview, encode_snapshot
from app.core.config import settings
from app.core.minio import get_minio_client
from minio.error import MinioException
from app.services.vector_store import VectorStoreFactory
from app.services.embedding.embedding_factory import EmbeddingsFactory

router = APIRouter()

logger = logging.getLogger(__name__)

class TestRetrievalRequest(BaseModel):
    query: str
    kb_id: int
    top_k: int

@router.post("", response_model=KnowledgeBaseResponse)
def create_knowledge_base(
    *,
    db: Session = Depends(get_db),
    kb_in: KnowledgeBaseCreate,
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Create new knowledge base.
    """
    kb = KnowledgeBase(
        name=kb_in.name,
        description=kb_in.description,
        user_id=current_user.id
    )
    db.add(kb)
    db.commit()
    db.refresh(kb)
    logger.info(f"Knowledge base created: {kb.name} for user {current_user.id}")
    return kb

@router.get("", response_model=List[KnowledgeBaseResponse])
def get_knowledge_bases(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    skip: int = 0,
    limit: int = 100
) -> Any:
    """
    Retrieve knowledge bases.
    """
    knowledge_bases = (
        db.query(KnowledgeBase)
        .filter(KnowledgeBase.user_id == current_user.id)
        .offset(skip)
        .limit(limit)
        .all()
    )
    return knowledge_bases

@router.get("/{kb_id}", response_model=KnowledgeBaseResponse)
def get_knowledge_base(
    *,
    db: Session = Depends(get_db),
    kb_id: int,
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Get knowledge base by ID.
    """
    from sqlalchemy.orm import joinedload
    
    kb = (
        db.query(KnowledgeBase)
        .options(
            joinedload(KnowledgeBase.documents)
            .joinedload(Document.processing_tasks)
        )
        .filter(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.user_id == current_user.id
        )
        .first()
    )

    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    
    return kb

@router.put("/{kb_id}", response_model=KnowledgeBaseResponse)
def update_knowledge_base(
    *,
    db: Session = Depends(get_db),
    kb_id: int,
    kb_in: KnowledgeBaseUpdate,
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Update knowledge base.
    """
    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == kb_id,
        KnowledgeBase.user_id == current_user.id
    ).first()
    
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    for field, value in kb_in.dict(exclude_unset=True).items():
        setattr(kb, field, value)

    db.add(kb)
    db.commit()
    db.refresh(kb)
    logger.info(f"Knowledge base updated: {kb.name} for user {current_user.id}")
    return kb

@router.delete("/{kb_id}")
async def delete_knowledge_base(
    *,
    db: Session = Depends(get_db),
    kb_id: int,
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Delete knowledge base and all associated resources.
    """
    logger = logging.getLogger(__name__)
    
    kb = (
        db.query(KnowledgeBase)
        .filter(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.user_id == current_user.id
        )
        .first()
    )
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    
    try:
        # Get all document file paths before deletion
        document_paths = [doc.file_path for doc in kb.documents]
        
        # Initialize services
        minio_client = get_minio_client()
        embeddings = EmbeddingsFactory.create()

        vector_store = VectorStoreFactory.create(
            store_type=settings.VECTOR_STORE_TYPE,
            collection_name=f"kb_{kb_id}",
            embedding_function=embeddings,
        )
        
        # Clean up external resources first
        cleanup_errors = []
        
        # 1. Clean up MinIO files
        try:
            # Delete all objects with prefix kb_{kb_id}/
            objects = minio_client.list_objects(settings.MINIO_BUCKET_NAME, prefix=f"kb_{kb_id}/")
            for obj in objects:
                minio_client.remove_object(settings.MINIO_BUCKET_NAME, obj.object_name)
            logger.info(f"Cleaned up MinIO files for knowledge base {kb_id}")
        except MinioException as e:
            cleanup_errors.append(f"Failed to clean up MinIO files: {str(e)}")
            logger.error(f"MinIO cleanup error for kb {kb_id}: {str(e)}")
        
        # 2. Clean up vector store
        try:
            vector_store._store.delete_collection(f"kb_{kb_id}")
            logger.info(f"Cleaned up vector store for knowledge base {kb_id}")
        except Exception as e:
            cleanup_errors.append(f"Failed to clean up vector store: {str(e)}")
            logger.error(f"Vector store cleanup error for kb {kb_id}: {str(e)}")
        
        # Finally, delete database records in a single transaction
        db.delete(kb)
        db.commit()
        
        # Report any cleanup errors in the response
        if cleanup_errors:
            return {
                "message": "Knowledge base deleted with cleanup warnings",
                "warnings": cleanup_errors
            }
        
        return {"message": "Knowledge base and all associated resources deleted successfully"}
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to delete knowledge base {kb_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to delete knowledge base: {str(e)}")

# Batch upload documents
@router.post("/{kb_id}/documents/upload")
async def upload_kb_documents(
    kb_id: int,
    files: List[UploadFile],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Upload multiple documents to MinIO.
    """
    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == kb_id,
        KnowledgeBase.user_id == current_user.id
    ).first()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    
    results = []
    for file in files:
        file_name = Path((file.filename or "").replace("\\", "/")).name
        if len(file_name) > 180 or Path(file_name).suffix.lower() not in (".txt", ".md", ".pdf", ".docx"):
            raise HTTPException(422, "文件名过长或格式不支持")
        # 1. 计算文件 hash
        file_content = await file.read()
        file_hash = hashlib.sha256(file_content).hexdigest()
        
        # 2. 检查是否存在完全相同的文件（名称和hash都相同）
        existing_document = db.query(Document).filter(
            Document.file_name == file_name,
            Document.file_hash == file_hash,
            Document.knowledge_base_id == kb_id
        ).first()
        
        if existing_document:
            # 完全相同的文件，直接返回
            results.append({
                "document_id": existing_document.id,
                "file_name": existing_document.file_name,
                "status": "exists",
                "message": "文件已存在且已处理完成",
                "skip_processing": True
            })
            continue
        
        same_name = db.query(Document).filter(Document.file_name == file_name, Document.knowledge_base_id == kb_id).first()
        if same_name:
            raise HTTPException(409, f"{file_name} 已存在不同版本，请使用不同文件名；不会自动覆盖或重切旧文档")
        # Unique object paths bind each upload record to immutable file bytes.
        temp_path = f"kb_{kb_id}/temp/{uuid.uuid4()}/{file_name}"
        await file.seek(0)
        try:
            minio_client = get_minio_client()
            file_size = len(file_content)  # 使用之前读取的文件内容长度
            minio_client.put_object(
                bucket_name=settings.MINIO_BUCKET_NAME,
                object_name=temp_path,
                data=file.file,
                length=file_size,  # 指定文件大小
                content_type=file.content_type or mimetypes.guess_type(file_name)[0] or "application/octet-stream"
            )
        except MinioException as e:
            logger.error(f"Failed to upload file to MinIO: {str(e)}")
            raise HTTPException(status_code=500, detail="Failed to upload file")
        
        # 4. 创建上传记录
        upload = DocumentUpload(
            knowledge_base_id=kb_id,
            file_name=file_name,
            file_hash=file_hash,
            file_size=len(file_content),
            content_type=file.content_type or mimetypes.guess_type(file_name)[0] or "application/octet-stream",
            temp_path=temp_path
        )
        db.add(upload)
        db.commit()
        db.refresh(upload)
        
        results.append({
            "upload_id": upload.id,
            "file_name": file_name,
            "temp_path": temp_path,
            "status": "pending",
            "skip_processing": False
        })
    
    return results

@router.post("/{kb_id}/documents/preview")
def preview_kb_documents(
    kb_id: int,
    preview_request: PreviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # These IDs identify uploads only; document IDs are a different namespace.
    return {upload_id: create_preview(db, kb_id, current_user.id, upload_id,
                ChunkConfig(chunk_size=preview_request.chunk_size, chunk_overlap=preview_request.chunk_overlap))
            for upload_id in dict.fromkeys(preview_request.upload_ids)}


@router.post("/{kb_id}/documents/process")
def process_kb_documents(
    kb_id: int,
    request: ProcessPreviewsRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    tasks, scheduled = confirm_previews(db, kb_id, current_user.id, request.preview_ids)
    for task_id in scheduled:
        background_tasks.add_task(ingest_preview, task_id)
    return {"tasks": tasks}


@router.post("/cleanup")
def cleanup_temp_files(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    now = datetime.utcnow()
    uploads = db.query(DocumentUpload).join(KnowledgeBase).filter(
        KnowledgeBase.user_id == current_user.id,
        DocumentUpload.created_at < now - timedelta(hours=24),
        DocumentUpload.status != "completed",
    ).all()
    client = get_minio_client()
    cleaned = 0
    for upload in uploads:
        # Serialize with confirmation so a cleanup cannot race a newly accepted job.
        db.refresh(upload, with_for_update=True)
        running = db.query(ProcessingTask).filter(
            ProcessingTask.document_upload_id == upload.id,
            ProcessingTask.status.in_(["pending", "processing"]),
        ).with_for_update().first()
        if running:
            db.commit()
            continue
        previews = db.query(DocumentPreview).filter(DocumentPreview.upload_id == upload.id).with_for_update().all()
        if any(p.expires_at > now for p in previews):
            db.commit()
            continue
        for preview in previews:
            client.remove_object(settings.MINIO_BUCKET_NAME, preview.snapshot_path)
            client.remove_object(settings.MINIO_BUCKET_NAME, f"kb_{upload.knowledge_base_id}/documents/{preview.id}/{upload.file_name}")
            preview.status = "expired"
        client.remove_object(settings.MINIO_BUCKET_NAME, upload.temp_path)
        upload.status = "expired"
        db.commit()
        cleaned += 1
    return {"message": f"已清理 {cleaned} 个过期上传；正在处理的快照不清理"}


@router.get("/{kb_id}/documents/tasks")
async def get_processing_tasks(
    kb_id: int,
    task_ids: str = Query(..., description="Comma-separated list of task IDs to check status for"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get status of multiple processing tasks.
    """
    try:
        task_id_list = [int(value.strip()) for value in task_ids.split(",")]
        if not 1 <= len(task_id_list) <= 50:
            raise ValueError()
    except ValueError:
        raise HTTPException(422, "任务ID必须为1至50个整数")
    
    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == kb_id,
        KnowledgeBase.user_id == current_user.id
    ).first()
    
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
        
    tasks = (
        db.query(ProcessingTask)
        .options(
            selectinload(ProcessingTask.document_upload)
        )
        .filter(
            ProcessingTask.id.in_(task_id_list),
            ProcessingTask.knowledge_base_id == kb_id
        )
        .all()
    )
    
    return {
        task.id: {
            "document_id": task.document_id,
            "preview_id": task.preview_id,
            "chunk_count": task.document.chunk_count if task.document else None,
            "status": task.status,
            "error_message": task.error_message,
            "upload_id": task.document_upload_id,
            "file_name": task.document_upload.file_name if task.document_upload else None
        }
        for task in tasks
    }

@router.get("/{kb_id}/documents/{doc_id}", response_model=DocumentResponse)
async def get_document(
    *,
    db: Session = Depends(get_db),
    kb_id: int,
    doc_id: int,
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Get document details by ID.
    """
    document = (
        db.query(Document)
        .join(KnowledgeBase)
        .filter(
            Document.id == doc_id,
            Document.knowledge_base_id == kb_id,
            KnowledgeBase.user_id == current_user.id
        )
        .first()
    )

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    
    return document

@router.get("/{kb_id}/documents/{doc_id}/chunks")
def get_document_chunks(
    kb_id: int, doc_id: int, db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    document = db.query(Document).join(KnowledgeBase).filter(
        Document.id == doc_id, Document.knowledge_base_id == kb_id,
        KnowledgeBase.user_id == current_user.id,
    ).first()
    if not document:
        raise HTTPException(404, "文档不存在")
    records = db.query(DocumentChunk).filter(DocumentChunk.document_id == doc_id).order_by(
        DocumentChunk.chunk_index, DocumentChunk.id
    ).all()
    chunks = [{"content": (row.chunk_metadata or {}).get("page_content", ""),
               "metadata": (row.chunk_metadata or {}).get("preview_metadata", {
                   k: v for k, v in (row.chunk_metadata or {}).items() if k != "page_content"})}
              for row in records]
    matches = None
    if document.preview_id:
        preview = db.get(DocumentPreview, document.preview_id)
        if preview:
            payload = {"file_hash": preview.file_hash, "config": preview.config,
                       "version": preview.processor_version, "chunks": chunks}
            matches = hashlib.sha256(encode_snapshot(payload)).hexdigest() == preview.snapshot_hash
    return {"document_id": doc_id, "file_name": document.file_name,
            "config": document.chunk_config, "preview_id": document.preview_id,
            "total_chunks": len(chunks), "snapshot_matches": matches,
            "order_known": all(row.chunk_index is not None for row in records), "chunks": chunks}


@router.post("/test-retrieval")
async def test_retrieval(
    request: TestRetrievalRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Test retrieval quality for a given query against a knowledge base.
    """
    try:
        kb = db.query(KnowledgeBase).filter(
            KnowledgeBase.id == request.kb_id,
            KnowledgeBase.user_id == current_user.id
        ).first()
        
        if not kb:
            raise HTTPException(
                status_code=404,
                detail=f"Knowledge base {request.kb_id} not found",
            )
        
        embeddings = EmbeddingsFactory.create()
        
        vector_store = VectorStoreFactory.create(
            store_type=settings.VECTOR_STORE_TYPE,
            collection_name=f"kb_{request.kb_id}",
            embedding_function=embeddings,
        )
        
        results = vector_store.similarity_search_with_score(request.query, k=request.top_k)
        
        response = []
        for doc, score in results:
            response.append({
                "content": doc.page_content,
                "metadata": doc.metadata,
                "score": float(score)
            })
            
        return {"results": response}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
