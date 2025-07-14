import asyncio
import os
from sqlalchemy.orm import Session

from src.core import get_db_session, get_logger, settings
from src.models import UploadJob
from src.models.upload_job import UploadJobState
from src.services.orchestrator import start_upload_job

logger = get_logger(__name__)

class FileMonitor:
    def __init__(self):
        self.is_running = False
        self.scan_interval = getattr(settings, 'file_monitor_interval', 60)
        self.monitor_task = None
        
    async def start(self):
        """Start the file monitor"""
        if self.is_running:
            logger.warning("File monitor is already running")
            return
        
        self.is_running = True
        self.monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info("File monitor started")
    
    async def stop(self):
        """Stop the file monitor"""
        if not self.is_running:
            logger.warning("File monitor is not running")
            return
        
        self.is_running = False
        if self.monitor_task:
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                pass
        logger.info("File monitor stopped")
    
    async def _monitor_loop(self):
        """Main monitoring loop"""
        logger.info("Starting file monitor loop")
        
        while self.is_running:
            try:
                await self._scan_active_jobs()
                await asyncio.sleep(self.scan_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in monitor loop: {str(e)}")
                await asyncio.sleep(self.scan_interval)
    
    async def _scan_active_jobs(self):
        """Scan all active upload jobs for file changes"""
        db = get_db_session()
        
        try:
            active_jobs = db.query(UploadJob).filter(
                UploadJob.state.in_([UploadJobState.COMPLETED])
            ).all()
            
            if not active_jobs:
                logger.debug("No active upload jobs to monitor")
                return
            
            logger.debug(f"Monitoring {len(active_jobs)} active upload jobs")
            
            # Check each job for file changes
            for job in active_jobs:
                try:
                    await self.check_upload_job(job)
                except Exception as e:
                    logger.error(f"Error checking upload job {job.id}: {str(e)}")
                    
        except Exception as e:
            logger.error(f"Error scanning active jobs: {str(e)}")
        finally:
            db.close()
    
    async def check_upload_job(self, upload_job: UploadJob) -> bool:
        try:
            # Check if source folder still exists
            if not os.path.exists(upload_job.source_folder):
                logger.warning(f"Source folder no longer exists: {upload_job.source_folder}")
                return False
            
            logger.debug(f"Checking upload job for changes", extra={"upload_id": upload_job.id})
            
            # Let orchestrator handle all file detection and filtering
            await start_upload_job(upload_job.id, filter_files_recently_changed=True)
            
            return True
            
        except Exception as e:
            logger.error(f"Error checking upload job: {str(e)}", extra={"upload_id": upload_job.id})
            return False


# Global file monitor instance
file_monitor = FileMonitor()

async def start_file_monitor():
    """Start the file monitor service"""
    await file_monitor.start()

async def stop_file_monitor():
    """Stop the file monitor service"""
    await file_monitor.stop()

def check_upload_job(upload_id: str) -> bool:
    """Synchronous wrapper for checking upload job"""
    return asyncio.run(file_monitor.check_upload_job(upload_id)) 
