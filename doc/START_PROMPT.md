# File Upload Service - Fresh Implementation

## Project Overview
Build a simple, robust file upload service that monitors directories and uploads files to AWS S3 with resumable capabilities and progress tracking.

## Core Requirements

### 1. API Layer (FastAPI)
- **POST /uploads/** - Create new upload job
  - Request: `{"source_folder": str, "destination_bucket": str, "pattern": str (optional)}`
  - Response: `{"upload_id": str, "status": "created"}`
- **GET /uploads/{upload_id}** - Get upload progress
  - Response: `{"upload_id": str, "progress": float, "state": str, "total_files": int, "completed_files": int}`

### 2. Database Schema (SQLite)
```sql
UploadJob:
- id (PRIMARY KEY)
- source_folder (TEXT)
- destination_bucket (TEXT) 
- pattern (TEXT)
- progress (REAL) -- 0.0 to 1.0
- state (TEXT) -- PENDING, IN_PROGRESS, COMPLETED, FAILED
- created_at (TIMESTAMP)
- updated_at (TIMESTAMP)

File:
- id (PRIMARY KEY)
- upload_job_id (FOREIGN KEY)
- path (TEXT) -- relative to source_folder
- state (TEXT) -- PENDING, IN_PROGRESS, UPLOADED, FAILED
- mtime (TIMESTAMP)
- size (INTEGER)
- created_at (TIMESTAMP)
- updated_at (TIMESTAMP)
```

### 3. Core Components

**Worker**:
- Take a File record and upload it using S3 multipart upload
- Split file into in-memory chunks (e.g., 5MB each)
- Upload to `s3://{bucket}/{upload_id}/{file_path}`
- If any chunk fails → mark File as FAILED
- If all chunks succeed → verify upload and mark as UPLOADED
- Update File state throughout process

**Orchestrator**:
- Process UploadJob by finding all matching files
- Create File records for each file
- Submit File upload tasks to worker pool (limited parallelism, e.g., 5 concurrent)
- Update UploadJob progress as files complete
- Mark UploadJob as COMPLETED when all files finish

**FileMonitor**:
- Function: `check_upload_job(upload_id)` - scan source folder, compare mtime/size with DB, re-enqueue changed files
- Background cron: scan all active UploadJobs every N minutes (configurable)
- Only track files that match the job's pattern

### 4. Infrastructure
- **Docker Compose**: FastAPI service + LocalStack S3 for development
- **Dependencies**: FastAPI, SQLAlchemy, boto3, aiofiles, asyncio
- **Python environment**: Use .venv for dependency management

### 5. Configuration
- Environment variables for:
  - AWS credentials and region
  - Database path
  - Chunk size for uploads
  - Worker concurrency limit
  - FileMonitor scan interval
  - Logging level

## Implementation Guidelines

1. **Keep it simple**: Implement only what's needed, avoid over-engineering
2. **Error handling**: Proper exception handling with clear error messages
3. **Logging**: Simple structured logging (JSON format recommended)
4. **State management**: All state in database, no in-memory persistence
5. **Async operations**: Use async/await for I/O operations
6. **Testing**: Unit tests for core logic, integration tests for end-to-end flow

## File Structure
```
src/
├── api/           # FastAPI endpoints
├── models/        # SQLAlchemy models
├── services/      # Core business logic (Worker, Orchestrator, FileMonitor)
├── core/          # Database, logging, config
└── main.py        # FastAPI app entry point
```

## Key Decisions to Validate
1. **Chunk size**: 5MB chunks reasonable for multipart uploads?
2. **Concurrency**: What's appropriate worker pool size?
3. **Monitoring interval**: How often should FileMonitor scan?
4. **Error recovery**: Should failed files be retried automatically?
5. **API authentication**: Do we need auth for the endpoints?

## Success Criteria
- Start upload job via API
- Files upload to S3 with proper directory structure
- Progress tracking works correctly
- Service recovers gracefully from crashes
- File changes are detected and re-uploaded
- Clean, maintainable codebase

**Focus on getting the core upload workflow working first, then add monitoring capabilities.** 
