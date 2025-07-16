from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, BigInteger, Enum as SqlEnum, Float
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from enum import Enum
from .upload_job import Base

class FileState(Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    UPLOADED = "UPLOADED"
    FAILED = "FAILED"

class File(Base):
    __tablename__ = 'files'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    upload_job_id = Column(String, ForeignKey('upload_jobs.id'), nullable=False)
    path = Column(Text, nullable=False)  # relative to source_folder
    state = Column(SqlEnum(FileState), default=FileState.PENDING, nullable=False)
    failure_reason = Column(Text, nullable=True)  # reason for failure when state is FAILED
    mtime = Column(Float, nullable=True)  # Unix timestamp
    size = Column(BigInteger, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    # Relationship to UploadJob
    upload_job = relationship("UploadJob", back_populates="files")
    
    def __repr__(self):
        return f"<File(id={self.id}, path={self.path}, state={self.state}, failure_reason={self.failure_reason})>" 
