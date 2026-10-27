from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field, model_validator

class KnowledgeBaseBase(BaseModel):
    name: str
    description: Optional[str] = None

class KnowledgeBaseCreate(KnowledgeBaseBase):
    pass

class KnowledgeBaseUpdate(KnowledgeBaseBase):
    pass

class DocumentBase(BaseModel):
    file_name: str
    file_path: str
    file_hash: str
    file_size: int
    content_type: str

class DocumentCreate(DocumentBase):
    knowledge_base_id: int

class DocumentUploadBase(BaseModel):
    file_name: str
    file_hash: str
    file_size: int
    content_type: str
    temp_path: str
    status: str = "pending"
    error_message: Optional[str] = None

class DocumentUploadCreate(DocumentUploadBase):
    knowledge_base_id: int

class DocumentUploadResponse(DocumentUploadBase):
    id: int
    created_at: datetime
    
    class Config:
        from_attributes = True

class ProcessingTaskBase(BaseModel):
    status: str
    error_message: Optional[str] = None

class ProcessingTaskCreate(ProcessingTaskBase):
    document_id: int
    knowledge_base_id: int

class ProcessingTask(ProcessingTaskBase):
    id: int
    document_id: int
    knowledge_base_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class DocumentResponse(DocumentBase):
    id: int
    knowledge_base_id: int
    created_at: datetime
    updated_at: datetime
    processing_tasks: List[ProcessingTask] = []

    class Config:
        from_attributes = True

class KnowledgeBaseResponse(KnowledgeBaseBase):
    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime
    documents: List[DocumentResponse] = []

    class Config:
        from_attributes = True

class ChunkConfig(BaseModel):
    chunk_size: int = Field(default=1000, strict=True, ge=1, le=20000)
    chunk_overlap: int = Field(default=200, strict=True, ge=0)

    @model_validator(mode="after")
    def validate_overlap(self):
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("重叠字符数必须小于片段长度")
        return self


class PreviewRequest(ChunkConfig):
    document_ids: List[int] = Field(min_length=1, max_length=50)
