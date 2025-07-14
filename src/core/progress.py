"""Progress computation utilities for upload jobs"""

from sqlalchemy.orm import Session
from src.models import UploadJob, File
from src.models.file import FileState
from src.models.upload_job import UploadJobState


def compute_job_progress(upload_job_id: str, db: Session) -> dict:
    """
    Compute upload job progress based on file states.
    
    Args:
        upload_job_id: The upload job ID
        db: Database session
        
    Returns:
        dict with progress (float), total_files (int), completed_files (int), failed_files (int)
    """
    # Get file counts
    total_files = db.query(File).filter(File.upload_job_id == upload_job_id).count()
    uploaded_files = db.query(File).filter(
        File.upload_job_id == upload_job_id,
        File.state == FileState.UPLOADED
    ).count()
    failed_files = db.query(File).filter(
        File.upload_job_id == upload_job_id,
        File.state == FileState.FAILED
    ).count()
    
    if total_files == 0:
        progress = 1.0
    else:
        progress = uploaded_files / total_files
    
    return {
        "progress": progress,
        "total_files": total_files,
        "completed_files": uploaded_files,
        "failed_files": failed_files
    }


def compute_job_state(upload_job_id: str, db: Session) -> UploadJobState:
    """
    Compute upload job state based on file states without persisting it.
    
    Args:
        upload_job_id: The upload job ID
        db: Database session
        
    Returns:
        The computed job state
    """
    upload_job = db.query(UploadJob).filter(UploadJob.id == upload_job_id).first()
    if not upload_job:
        return None
    
    progress_info = compute_job_progress(upload_job_id, db)
    total_files = progress_info["total_files"]
    uploaded_files = progress_info["completed_files"]
    failed_files = progress_info["failed_files"]
    
    if total_files == 0:
        return UploadJobState.COMPLETED
    elif uploaded_files == total_files:
        return UploadJobState.COMPLETED
    elif failed_files > 0 and (uploaded_files + failed_files) == total_files:
        return UploadJobState.FAILED
    else:
        # Return current state if still in progress, or IN_PROGRESS if files exist
        if upload_job.state in [UploadJobState.PENDING, UploadJobState.IN_PROGRESS]:
            return upload_job.state
        else:
            return UploadJobState.IN_PROGRESS 
