from sqlalchemy import Column, Integer, String, DateTime, Text, Enum as SqlEnum
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func
from datetime import datetime, timezone
from enum import Enum

Base = declarative_base()

class UploadJobState(Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class UploadJob(Base):
    __tablename__ = 'upload_jobs'
    
    id = Column(String, primary_key=True)
    source_folder = Column(Text, nullable=False)
    destination_bucket = Column(Text, nullable=False)
    pattern = Column(Text, nullable=True)
    state = Column(SqlEnum(UploadJobState), default=UploadJobState.PENDING, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    # Relationship to Files
    files = relationship("File", back_populates="upload_job")
    
    def __repr__(self):
        return f"<UploadJob(id={self.id}, state={self.state})>" 
