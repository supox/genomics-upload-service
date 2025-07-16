import asyncio
import time
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from concurrent.futures import ThreadPoolExecutor

from src.core import get_db_session, get_logger, settings, ensure_bucket_exists
from src.models import UploadJob, File
from src.models.file import FileState
from src.models.upload_job import UploadJobState
from .upload_worker import upload_worker
from .file_utils import find_matching_files

logger = get_logger(__name__)

class Orchestrator:
    def __init__(self):
        self.max_workers = settings.worker_concurrency
        self.semaphore = asyncio.Semaphore(self.max_workers)
    
    async def process_upload_job(self, upload_id: str, filter_files_recently_changed: bool = False) -> bool:
        """
        Unified method to process upload jobs for all use cases:
        - New upload job: scans files, uploads all
        - Resync upload job: scans files, uploads only new/modified ones
        
        Args:
            upload_id: The upload job ID to process
            filter_files_recently_changed: True to filter out recently changed files (for monitoring), False for initial uploads
        """
        db = get_db_session()
        
        try:
            # Get upload job
            upload_job = db.query(UploadJob).filter(UploadJob.id == upload_id).first()
            if not upload_job:
                logger.error(f"Upload job not found: {upload_id}")
                return False
            
            # Set job to IN_PROGRESS
            upload_job.state = UploadJobState.IN_PROGRESS
            db.commit()
            
            logger.info(f"Processing upload job", extra={
                "upload_id": upload_id,
                "source_folder": upload_job.source_folder,
                "destination_bucket": upload_job.destination_bucket,
                "pattern": upload_job.pattern
            })
            
            # Ensure the destination bucket exists
            bucket_ready = await ensure_bucket_exists(upload_job.destination_bucket)
            if not bucket_ready:
                logger.error(f"Failed to ensure bucket exists: {upload_job.destination_bucket}")
                upload_job.state = UploadJobState.FAILED
                db.commit()
                return False
            
            # Always scan for current files
            current_files = await self._scan_files(upload_job)
            if not current_files:
                logger.info(f"No files found for upload job", extra={"upload_id": upload_id})
                upload_job.state = UploadJobState.COMPLETED
                db.commit()
                return True
            
            # Filter files that need uploading
            files_to_upload = await self._filter_files_to_upload(upload_id, current_files, db, filter_files_recently_changed=filter_files_recently_changed)
            
            # Upload filtered files
            await self._upload_files_concurrently(upload_id, files_to_upload)
            
            # Update final job state
            await self._update_job_state_after_upload(upload_id)
            
            return True
            
        except Exception as e:
            logger.error(f"Error processing upload job: {str(e)}", extra={"upload_id": upload_id})
            # Mark job as failed
            try:
                upload_job = db.query(UploadJob).filter(UploadJob.id == upload_id).first()
                if upload_job:
                    upload_job.state = UploadJobState.FAILED
                    db.commit()
            except Exception as update_error:
                logger.error(f"Error updating job state to FAILED: {update_error}")
            return False
        finally:
            db.close()

    async def retry_job(self, upload_id: str) -> bool:
        """
        Retry an upload job by removing non-completed files and reprocessing
        """
        db = get_db_session()
        
        try:
            logger.info(f"Retrying upload job", extra={"upload_id": upload_id})
            
            # Remove all non-completed files to start fresh
            deleted_count = db.query(File).filter(
                File.upload_job_id == upload_id,
                File.state.in_([FileState.PENDING, FileState.FAILED, FileState.IN_PROGRESS])
            ).delete()
            
            db.commit()
            
            logger.info(f"Removed {deleted_count} non-completed files for retry", extra={
                "upload_id": upload_id
            })
            
            # Process the job with clean state
            return await self.process_upload_job(upload_id)
            
        except Exception as e:
            logger.error(f"Error retrying upload job: {str(e)}", extra={"upload_id": upload_id})
            return False
        finally:
            db.close()
    
    async def _scan_files(self, upload_job: UploadJob) -> Dict[str, Dict[str, Any]]:
        """Scan for all files matching the upload job pattern"""
        try:
            source_folder = upload_job.source_folder
            pattern = upload_job.pattern or "*"
            
            files = await find_matching_files(source_folder, pattern)
            
            logger.info(f"Found {len(files)} matching files", extra={
                "upload_id": upload_job.id,
                "pattern": pattern
            })
            
            return files
            
        except Exception as e:
            logger.error(f"Error scanning files: {str(e)}", extra={
                "upload_id": upload_job.id,
                "source_folder": upload_job.source_folder
            })
            return {}
    
    async def _filter_files_to_upload(self, upload_id: str, current_files: Dict[str, Dict[str, Any]], db: Session, filter_files_recently_changed: bool) -> List[File]:
        """Filter files that need to be uploaded based on current state"""
        files_to_upload = []
        
        # Get current time once for stability checks
        current_time = time.time()
        
        def is_file_stable(file_info: Dict[str, Any]) -> bool:
            """Check if file is stable (not modified within the stability threshold)"""
            if not filter_files_recently_changed:
                return True
            
            time_since_modification = current_time - file_info['mtime']
            return time_since_modification >= settings.file_stability_threshold
        
        # Get existing file records
        
        db_files = db.query(File).filter(File.upload_job_id == upload_id).all()
        existing_files = {file_record.path: file_record for file_record in db_files}
        
        # Process each current file
        for file_path, file_info in current_files.items():
            if not is_file_stable(file_info):
                logger.debug(f"File modified too recently, skipping upload", extra={
                    "upload_id": upload_id,
                    "file_path": file_path,
                    "time_since_modification": current_time - file_info['mtime']
                })
                continue

            existing_file = existing_files.get(file_path)
            
            if existing_file:
                # File exists in DB - check if it needs re-uploading
                if existing_file.state == FileState.UPLOADED:
                    # Check if file was modified
                    if existing_file.mtime == file_info['mtime'] and existing_file.size == file_info['size']:
                        # file unchanged, skip
                        continue
                        
                    existing_file.mtime = file_info['mtime']
                    existing_file.size = file_info['size']
                    existing_file.state = FileState.PENDING
                    existing_file.failure_reason = None
                    files_to_upload.append(existing_file)
                    logger.info(f"File modified, marked for re-upload", extra={
                        "upload_id": upload_id,
                        "file_path": file_path,
                        "old_mtime": existing_file.mtime,
                        "new_mtime": file_info['mtime'],
                        "old_size": existing_file.size,
                        "new_size": file_info['size']
                    })
                else:
                    # File exists but not uploaded (PENDING/FAILED/IN_PROGRESS) - upload it
                    existing_file.state = FileState.PENDING
                    existing_file.failure_reason = None
                    files_to_upload.append(existing_file)
            else:
                file_record = File(
                    upload_job_id=upload_id,
                    path=file_path,
                    mtime=file_info['mtime'],
                    size=file_info['size'],
                    state=FileState.PENDING
                )
                db.add(file_record)
                files_to_upload.append(file_record)
                logger.info(f"New file found, marked for upload", extra={
                    "upload_id": upload_id,
                    "file_path": file_path
                })
        
        db.commit()
        
        # Refresh file records to get IDs for new files
        for file_record in files_to_upload:
            if file_record.id is None:
                db.refresh(file_record)
        
        logger.info(f"Filtered {len(files_to_upload)} files for upload", extra={
            "upload_id": upload_id,
            "total_files": len(current_files)
        })
        
        return files_to_upload
    
    async def _upload_files_concurrently(self, upload_id: str, file_records: List[File]):
        """Upload files with controlled concurrency"""
        if not file_records:
            return
        
        logger.info(f"Starting concurrent upload of {len(file_records)} files", extra={
            "upload_id": upload_id,
            "max_workers": self.max_workers
        })
        
        async def upload_with_semaphore(file_record: File):
            async with self.semaphore:
                return await upload_worker.upload_file(file_record.id)
        
        # Upload files concurrently
        tasks = [upload_with_semaphore(file_record) for file_record in file_records]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Log final results
        successful = sum(1 for r in results if r is True)
        failed = len(results) - successful
        
        logger.info(f"Upload batch completed", extra={
            "upload_id": upload_id,
            "successful": successful,
            "failed": failed,
            "total": len(results)
        })
    
    async def _update_job_state_after_upload(self, upload_id: str):
        """Update job state after upload batch completion"""
        db = get_db_session()
        try:
            upload_job = db.query(UploadJob).filter(UploadJob.id == upload_id).first()
            if not upload_job:
                logger.error(f"Upload job not found for state update: {upload_id}")
                return
            
            # Check if all files are either uploaded or failed
            total_files = db.query(File).filter(File.upload_job_id == upload_id).count()
            uploaded_files = db.query(File).filter(
                File.upload_job_id == upload_id,
                File.state == FileState.UPLOADED
            ).count()
            failed_files = db.query(File).filter(
                File.upload_job_id == upload_id,
                File.state == FileState.FAILED
            ).count()
            
            # Mark job as completed if all files are processed
            if uploaded_files + failed_files == total_files:
                if failed_files == 0:
                    upload_job.state = UploadJobState.COMPLETED
                    logger.info(f"Upload job completed successfully", extra={
                        "upload_id": upload_id,
                        "total_files": total_files,
                        "uploaded_files": uploaded_files
                    })
                else:
                    upload_job.state = UploadJobState.FAILED
                    logger.warning(f"Upload job failed - some files failed to upload", extra={
                        "upload_id": upload_id,
                        "total_files": total_files,
                        "uploaded_files": uploaded_files,
                        "failed_files": failed_files
                    })
                db.commit()
        except Exception as e:
            logger.error(f"Error updating job state after upload: {str(e)}", extra={"upload_id": upload_id})
        finally:
            db.close()


# Global orchestrator instance
orchestrator = Orchestrator()

async def start_upload_job(upload_id: str, filter_files_recently_changed: bool = False):
    """Process an upload job (called from API, FileMonitor, or other triggers)"""
    await orchestrator.process_upload_job(upload_id, filter_files_recently_changed=filter_files_recently_changed)

async def resume_incomplete_jobs():
    """Resume all non-completed upload jobs on service startup"""
    db = get_db_session()
    
    try:
        # Find all non-completed upload jobs
        non_completed_jobs = db.query(UploadJob).filter(
            UploadJob.state.in_([UploadJobState.PENDING, UploadJobState.IN_PROGRESS])
        ).all()
        
        if not non_completed_jobs:
            logger.info("No incomplete upload jobs found to resume")
            return
        
        logger.info(f"Found {len(non_completed_jobs)} incomplete upload jobs to resume")
        
        # Resume each job
        for job in non_completed_jobs:
            try:
                logger.info(f"Resuming upload job", extra={
                    "upload_id": job.id,
                    "state": job.state.value if hasattr(job.state, 'value') else job.state,
                    "source_folder": job.source_folder,
                    "destination_bucket": job.destination_bucket
                })
                
                # Process the job in the background with retry=True
                asyncio.create_task(orchestrator.retry_job(job.id))
                
            except Exception as e:
                logger.error(f"Error resuming upload job {job.id}: {str(e)}")
                
    except Exception as e:
        logger.error(f"Error during job recovery: {str(e)}")
    finally:
        db.close() 
