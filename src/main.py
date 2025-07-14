import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request, Form, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from typing import Optional

from src.core import setup_logging, create_tables, get_logger, get_db
from src.core.templates import render_template, render_error_template, render_success_template
from src.api.uploads import router as uploads_router
from src.services import start_file_monitor, stop_file_monitor
from src.services.orchestrator import resume_incomplete_jobs
from src.models import UploadJob, File
from src.models.file import FileState
from src.models.upload_job import UploadJobState
import os

# Setup logging
setup_logging()
logger = get_logger(__name__)

# Import test environment check from test_utils
from tests.test_utils import _is_test_environment

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    logger.info("Starting File Upload Service")
    
    # Create database tables
    try:
        create_tables()
        logger.info("Database tables created successfully")
    except Exception as e:
        logger.error(f"Failed to create database tables: {str(e)}")
        raise
    
    # Resume incomplete upload jobs from previous runs
    try:
        await resume_incomplete_jobs()
        logger.info("Job recovery completed successfully")
    except Exception as e:
        logger.error(f"Error during job recovery: {str(e)}")
        # Don't fail startup if job recovery fails
    
    # Start file monitor in background
    monitor_task = asyncio.create_task(start_file_monitor())
    
    # Application startup complete
    logger.info("File Upload Service started successfully")
    
    yield
    
    # Application shutdown
    logger.info("Shutting down File Upload Service")
    
    # Stop file monitor
    try:
        await stop_file_monitor()
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass
    except Exception as e:
        logger.error(f"Error stopping file monitor: {str(e)}")
    
    logger.info("File Upload Service stopped")

# Create FastAPI application
app = FastAPI(
    title="File Upload Service",
    description="A service for uploading files to S3 with progress tracking and file monitoring",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(uploads_router, prefix="/api/v1", tags=["uploads"])

# Only include test utils router in test environments
if _is_test_environment():
    from tests.test_utils import router as test_utils_router
    app.include_router(test_utils_router, prefix="/api/v1/test", tags=["test-utils"])
    logger.info("Test utilities router enabled")

# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "file-upload-service"}

# Root endpoint with HTML form and upload list
@app.get("/", response_class=HTMLResponse)
async def root(db: Session = Depends(get_db)):
    """Root endpoint with HTML form and upload list"""
    # Get first 10 upload jobs
    upload_jobs = db.query(UploadJob).limit(10).all()
    
    # Build upload jobs table rows
    jobs_html = ""
    for job in upload_jobs:
        total_files = db.query(File).filter(File.upload_job_id == job.id).count()
        completed_files = db.query(File).filter(
            File.upload_job_id == job.id,
            File.state == FileState.UPLOADED
        ).count()
        
        state_badge = f'<span class="badge {get_state_class(job.state)}">{job.state.value if hasattr(job.state, "value") else job.state}</span>'
        
        jobs_html += f"""
        <tr>
            <td><a href="/job/{job.id}">{job.id}</a></td>
            <td>{job.source_folder}</td>
            <td>{job.destination_bucket}</td>
            <td>{state_badge}</td>
            <td>{completed_files}/{total_files}</td>
            <td>{job.created_at.strftime('%Y-%m-%d %H:%M:%S')}</td>
        </tr>
        """
    
    if not jobs_html:
        jobs_html = '<tr><td colspan="6" class="text-center">No upload jobs found</td></tr>'
    
    return render_template("index", jobs_html=jobs_html)

def get_state_class(state) -> str:
    """Get CSS class for state badge"""
    # Handle enum objects by getting their value
    if hasattr(state, 'value'):
        state_value = state.value
    else:
        state_value = str(state)
    
    state_lower = state_value.lower()
    if state_lower == 'pending':
        return 'pending'
    elif state_lower == 'in_progress':
        return 'in-progress'
    elif state_lower == 'completed':
        return 'completed'
    elif state_lower == 'failed':
        return 'failed'
    else:
        return 'pending'

# Form submission endpoint
@app.post("/create-upload", response_class=HTMLResponse)
async def create_upload_form(
    upload_id: str = Form(...),
    source_folder: str = Form(...),
    destination_bucket: str = Form(...),
    pattern: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """Handle form submission for creating upload"""
    try:
        # Import here to avoid circular imports
        from src.services.orchestrator import start_upload_job
        import os
        
        # Validate source folder exists
        if not os.path.exists(source_folder):
            return render_error_template("Error", f"Source folder does not exist: {source_folder}")
        
        # Check if upload_id already exists
        existing_job = db.query(UploadJob).filter(UploadJob.id == upload_id).first()
        if existing_job:
            return render_error_template("Error", f"Upload job with ID {upload_id} already exists")
        
        # Create upload job in database
        upload_job = UploadJob(
            id=upload_id,
            source_folder=source_folder,
            destination_bucket=destination_bucket,
            pattern=pattern or None,
            state=UploadJobState.PENDING
        )
        
        db.add(upload_job)
        db.commit()
        db.refresh(upload_job)
        
        # Start upload process in background
        import asyncio
        asyncio.create_task(start_upload_job(upload_id))
        
        logger.info(f"Created upload job", extra={"upload_id": upload_id, "source_folder": source_folder})
        
        return render_success_template(
            "Upload Created Successfully",
            f"Upload ID: {upload_id}",
            "Status: Created",
            {"url": f"/job/{upload_id}", "text": "View Upload Details"}
        )
        
    except Exception as e:
        logger.error(f"Error creating upload job: {str(e)}")
        return render_error_template("Error", f"Failed to create upload job: {str(e)}")

# Job details endpoint
@app.get("/job/{job_id}", response_class=HTMLResponse)
async def get_job_details(job_id: str, db: Session = Depends(get_db)):
    """Show job details and files"""
    try:
        from src.core import compute_job_progress, compute_job_state
        
        # Get upload job
        upload_job = db.query(UploadJob).filter(UploadJob.id == job_id).first()
        
        if not upload_job:
            return render_error_template("Job Not Found", f"Upload job not found: {job_id}")
        
        # Get files for this job
        files = db.query(File).filter(File.upload_job_id == job_id).all()
        
        # Build files table
        files_html = ""
        for file in files:
            state_badge = f'<span class="badge {get_state_class(file.state)}">{file.state.value if hasattr(file.state, "value") else file.state}</span>'
            size_mb = round(file.size / (1024 * 1024), 2) if file.size else 0
            failure_reason = file.failure_reason if file.failure_reason else '-'
            files_html += f"""
            <tr>
                <td>{file.path}</td>
                <td>{state_badge}</td>
                <td>{size_mb} MB</td>
                <td>{failure_reason}</td>
                <td>{file.created_at.strftime('%Y-%m-%d %H:%M:%S')}</td>
            </tr>
            """
        
        if not files_html:
            files_html = '<tr><td colspan="5" class="text-center">No files found</td></tr>'
        
        # Compute progress dynamically
        progress_info = compute_job_progress(job_id, db)
        progress_percent = round(progress_info["progress"] * 100, 1)
        
        # Compute current job state
        current_state = compute_job_state(job_id, db)
        state_badge = f'<span class="badge {get_state_class(current_state)}">{current_state.value if hasattr(current_state, "value") else current_state}</span>'
        
        return render_template("job_details", 
                             job_id=job_id,
                             upload_job=upload_job,
                             state_badge=state_badge,
                             progress_percent=progress_percent,
                             files_count=len(files),
                             files_html=files_html)
        
    except Exception as e:
        logger.error(f"Error getting job details: {str(e)}", extra={"job_id": job_id})
        return render_error_template("Error", f"Failed to get job details: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    ) 
