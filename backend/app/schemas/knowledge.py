from typing import Optional, List, Literal
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
    preview_id: Optional[str] = None
    chunk_config: Optional[dict] = None
    chunk_count: Optional[int] = None
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
    strategy: Literal["recursive", "fixed", "heading"] = "recursive"
    chunk_size: int = Field(default=1000, strict=True, ge=1, le=20000)
    chunk_overlap: int = Field(default=200, strict=True, ge=0)

    @model_validator(mode="after")
    def validate_overlap(self):
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("重叠字符数必须小于片段长度")
        return self


class PreviewRequest(ChunkConfig):
    upload_ids: List[int] = Field(min_length=1, max_length=50)


class ProcessPreviewsRequest(BaseModel):
    preview_ids: List[str] = Field(min_length=1, max_length=50)


class LabCompareRequest(BaseModel):
    upload_id: Optional[int] = None
    document_id: Optional[int] = None
    configs: List[ChunkConfig] = Field(min_length=2, max_length=3)

    @model_validator(mode="after")
    def validate_source(self):
        if (self.upload_id is None) == (self.document_id is None):
            raise ValueError("请选择一个上传文件或已入库文档")
        if len({c.strategy for c in self.configs}) != len(self.configs):
            raise ValueError("同一策略只可选择一次")
        return self


class LabProcessRequest(BaseModel):
    preview_id: str
