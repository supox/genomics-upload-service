"""Test utilities API endpoints - only available in test environments"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Dict, Any
import os

from src.core import get_db, get_logger
from src.models import UploadJob, File, Base
from src.core.database import engine

router = APIRouter()
logger = get_logger(__name__)

def _is_test_environment() -> bool:
    """Check if we're in a test environment"""
    # Check various indicators that we're in test mode
    return (
        os.getenv("TESTING", "false").lower() == "true" or
        os.getenv("PYTEST_CURRENT_TEST") is not None
    )

@router.post("/reset-database", response_model=Dict[str, Any])
async def reset_database(db: Session = Depends(get_db)):
    """Reset the database - only available in test environments"""
    if not _is_test_environment():
        raise HTTPException(
            status_code=403, 
            detail="Database reset is only available in test environments"
        )
    
    try:
        # Drop all tables and recreate them
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        
        logger.info("Database reset successfully")
        
        return {
            "status": "success",
            "message": "Database reset completed",
            "environment": "test"
        }
        
    except Exception as e:
        logger.error(f"Failed to reset database: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to reset database: {str(e)}"
        )

@router.get("/database-stats", response_model=Dict[str, Any])
async def get_database_stats(db: Session = Depends(get_db)):
    """Get database statistics - only available in test environments"""
    if not _is_test_environment():
        raise HTTPException(
            status_code=403, 
            detail="Database stats are only available in test environments"
        )
    
    try:
        upload_jobs_count = db.query(UploadJob).count()
        files_count = db.query(File).count()
        
        # Get recent uploads
        recent_uploads = db.query(UploadJob).order_by(UploadJob.created_at.desc()).limit(5).all()
        
        return {
            "upload_jobs_count": upload_jobs_count,
            "files_count": files_count,
            "recent_uploads": [
                {
                    "id": job.id,
                    "state": job.state,
                    "created_at": job.created_at.isoformat() if job.created_at else None
                }
                for job in recent_uploads
            ]
        }
        
    except Exception as e:
        logger.error(f"Failed to get database stats: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get database stats: {str(e)}"
        )

@router.delete("/cleanup-old-data", response_model=Dict[str, Any])
async def cleanup_old_data(db: Session = Depends(get_db)):
    """Clean up old test data - only available in test environments"""
    if not _is_test_environment():
        raise HTTPException(
            status_code=403, 
            detail="Data cleanup is only available in test environments"
        )
    
    try:
        # Wait for active upload jobs to complete before cleaning up
        import asyncio
        from src.models.upload_job import UploadJobState
        
        max_wait_time = 30  # seconds
        wait_interval = 1   # seconds
        waited_time = 0
        
        while waited_time < max_wait_time:
            # Check for active upload jobs
            active_jobs = db.query(UploadJob).filter(
                UploadJob.state.in_([UploadJobState.PENDING, UploadJobState.IN_PROGRESS])
            ).count()
            
            if active_jobs == 0:
                break
                
            logger.info(f"Waiting for {active_jobs} active upload jobs to complete...")
            await asyncio.sleep(wait_interval)
            waited_time += wait_interval
            
            # Refresh the session to get updated job states
            db.rollback()
        
        # Delete all files first (due to foreign key constraints)
        files_deleted = db.query(File).delete()
        
        # Delete all upload jobs
        jobs_deleted = db.query(UploadJob).delete()
        
        db.commit()
        
        logger.info(f"Cleaned up {jobs_deleted} upload jobs and {files_deleted} files")
        
        return {
            "status": "success",
            "message": "Old data cleaned up",
            "upload_jobs_deleted": jobs_deleted,
            "files_deleted": files_deleted
        }
        
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to cleanup old data: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to cleanup old data: {str(e)}"
        )

@router.post("/trigger-file-monitor/{upload_id}", response_model=Dict[str, Any])
async def trigger_file_monitor(upload_id: str, db: Session = Depends(get_db)):
    """Trigger file monitor check for a specific upload job - only available in test environments"""
    if not _is_test_environment():
        raise HTTPException(
            status_code=403, 
            detail="File monitor trigger is only available in test environments"
        )
    
    try:
        from src.services.file_monitor import file_monitor
        from src.core.config import settings
        
        # Log current settings for debugging
        logger.info(f"Current file_stability_threshold: {getattr(settings, 'file_stability_threshold', 'NOT SET')}")
        
        # Get the upload job from the database
        upload_job = db.query(UploadJob).filter(UploadJob.id == upload_id).first()
        if not upload_job:
            raise HTTPException(
                status_code=404,
                detail=f"Upload job not found: {upload_id}"
            )
        
        # Trigger file monitor check with the upload job object
        result = await file_monitor.check_upload_job(upload_job)
        
        logger.info(f"File monitor check triggered for upload {upload_id}, result: {result}")
        
        return {
            "status": "success",
            "message": f"File monitor check triggered for upload {upload_id}",
            "result": result,
            "upload_id": upload_id,
            "current_threshold": getattr(settings, 'file_stability_threshold', 'NOT SET')
        }
        
    except Exception as e:
        logger.error(f"Failed to trigger file monitor: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to trigger file monitor: {str(e)}"
        )

@router.post("/update-settings", response_model=Dict[str, Any])
async def update_settings(settings_update: Dict[str, Any]):
    """Update application settings - only available in test environments"""
    if not _is_test_environment():
        raise HTTPException(
            status_code=403, 
            detail="Settings update is only available in test environments"
        )
    
    try:
        from src.core.config import settings
        
        updated_settings = {}
        for key, value in settings_update.items():
            if hasattr(settings, key):
                # Update the setting
                setattr(settings, key, value)
                updated_settings[key] = value
                logger.info(f"Updated setting {key} to {value}")
            else:
                logger.warning(f"Setting {key} not found, skipping")
        
        return {
            "status": "success",
            "message": "Settings updated",
            "updated_settings": updated_settings
        }
        
    except Exception as e:
        logger.error(f"Failed to update settings: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update settings: {str(e)}"
        ) 
