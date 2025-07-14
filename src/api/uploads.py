from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from typing import Dict, Any
import uuid
import os
from datetime import datetime
import traceback

from src.core import get_db, get_logger
from src.models import UploadJob, File
from src.models.file import FileState
from src.models.upload_job import UploadJobState
from .models import CreateUploadRequest, CreateUploadResponse, UploadProgressResponse, FileResponse, ErrorResponse
from src.services.orchestrator import start_upload_job

router = APIRouter()
logger = get_logger(__name__)

@router.post("/uploads/", response_model=CreateUploadResponse)
async def create_upload(
    request: CreateUploadRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Create a new upload job"""
    logger.info(f"Received upload request", extra={
        "source_folder": request.source_folder,
        "destination_bucket": request.destination_bucket
    })
    
    # Validate source folder exists
    if not os.path.exists(request.source_folder):
        raise HTTPException(status_code=400, detail=f"Source folder does not exist: {request.source_folder}")
    
    # Check if upload_id already exists
    existing_job = db.query(UploadJob).filter(UploadJob.id == request.upload_id).first()
    if existing_job:
        raise HTTPException(status_code=400, detail=f"Upload job with ID {request.upload_id} already exists")
    
    # Create upload job in database
    upload_job = UploadJob(
        id=request.upload_id,
        source_folder=request.source_folder,
        destination_bucket=request.destination_bucket,
        pattern=request.pattern or "*",
        state=UploadJobState.PENDING
    )
    
    db.add(upload_job)
    db.commit()
    db.refresh(upload_job)
    
    # Start upload process in background
    background_tasks.add_task(start_upload_job, request.upload_id)
    
    logger.info(f"Created upload job", extra={"upload_id": request.upload_id, "source_folder": request.source_folder})
    
    return CreateUploadResponse(
        upload_id=request.upload_id,
        status="created"
    )

@router.get("/uploads/{upload_id}", response_model=UploadProgressResponse)
async def get_upload_progress(
    upload_id: str,
    db: Session = Depends(get_db)
):
    """Get upload job progress"""
    from src.core import compute_job_progress, compute_job_state
    
    # Get upload job
    upload_job = db.query(UploadJob).filter(UploadJob.id == upload_id).first()
    
    if not upload_job:
        raise HTTPException(status_code=404, detail=f"Upload job not found: {upload_id}")
    
    # Compute progress dynamically
    progress_info = compute_job_progress(upload_id, db)
    
    # Compute current job state based on file states
    current_state = compute_job_state(upload_id, db)
    
    return UploadProgressResponse(
        upload_id=upload_job.id,
        progress=progress_info["progress"],
        state=current_state,
        total_files=progress_info["total_files"],
        completed_files=progress_info["completed_files"],
        created_at=upload_job.created_at,
        updated_at=upload_job.updated_at
    )

@router.get("/uploads/", response_model=Dict[str, Any])
async def list_uploads(
    db: Session = Depends(get_db),
    limit: int = 10,
    offset: int = 0
):
    """List all upload jobs"""
    from src.core import compute_job_progress, compute_job_state
    
    upload_jobs = db.query(UploadJob).order_by(UploadJob.created_at.desc()).offset(offset).limit(limit).all()
    
    results = []
    for job in upload_jobs:
        # Use the same progress and state computation as the individual endpoint
        progress_info = compute_job_progress(job.id, db)
        current_state = compute_job_state(job.id, db)
        
        results.append({
            "upload_id": job.id,
            "state": current_state,
            "progress": progress_info["progress"],
            "total_files": progress_info["total_files"],
            "completed_files": progress_info["completed_files"],
            "created_at": job.created_at,
            "updated_at": job.updated_at
        })
    
    return {
        "uploads": results,
        "total": len(results),
        "offset": offset,
        "limit": limit
    }

@router.get("/uploads/{upload_id}/files", response_model=Dict[str, Any])
async def get_upload_files(
    upload_id: str,
    db: Session = Depends(get_db),
    limit: int = 100,
    offset: int = 0
):
    """Get detailed file information for an upload job"""
    # Get upload job
    upload_job = db.query(UploadJob).filter(UploadJob.id == upload_id).first()
    
    if not upload_job:
        raise HTTPException(status_code=404, detail=f"Upload job not found: {upload_id}")
    
    # Get files for this upload job
    files = db.query(File).filter(File.upload_job_id == upload_id).order_by(File.created_at.desc()).offset(offset).limit(limit).all()
    
    file_responses = []
    for file in files:
        file_responses.append(FileResponse(
            id=file.id,
            path=file.path,
            state=file.state.value if hasattr(file.state, 'value') else str(file.state),
            failure_reason=file.failure_reason,
            size=file.size,
            created_at=file.created_at,
            updated_at=file.updated_at
        ))
    
    return {
        "upload_id": upload_id,
        "files": file_responses,
        "total": len(file_responses),
        "offset": offset,
        "limit": limit
    } 
