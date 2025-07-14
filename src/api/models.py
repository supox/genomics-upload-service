from pydantic import BaseModel, Field, field_validator
from typing import Optional
from datetime import datetime
import uuid

class CreateUploadRequest(BaseModel):
    upload_id: Optional[str] = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique upload ID (auto-generated if not provided)")
    source_folder: str = Field(..., min_length=1, description="Source folder path")
    destination_bucket: str = Field(..., min_length=1, description="Destination S3 bucket")
    pattern: Optional[str] = Field(default="*", description="File pattern to match")
    
    @field_validator('source_folder')
    @classmethod
    def source_folder_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError('Source folder cannot be empty')
        return v.strip()
    
    @field_validator('destination_bucket')
    @classmethod
    def destination_bucket_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError('Destination bucket cannot be empty')
        return v.strip()

class CreateUploadResponse(BaseModel):
    upload_id: str
    status: str

class UploadProgressResponse(BaseModel):
    upload_id: str
    progress: float
    state: str
    total_files: int
    completed_files: int
    created_at: datetime
    updated_at: datetime

class FileResponse(BaseModel):
    id: int
    path: str
    state: str
    failure_reason: Optional[str] = None
    size: Optional[int] = None
    created_at: datetime
    updated_at: datetime

class ErrorResponse(BaseModel):
    error: str
    message: str 
