# File Upload Service Architecture

## Overview

The File Upload Service is a robust, containerized solution for uploading files to S3 with progress tracking, file monitoring, and recovery capabilities. The system uses a single-container architecture with FastAPI and SQLite for simplicity while maintaining reliability.

## Container Architecture

### Main Application Container
- **Base**: Python 3.13 with FastAPI
- **Database**: SQLite (single file database)
- **Purpose**: Handles all upload operations, API endpoints, and file monitoring
- **Ports**: 8000 (HTTP API)

### LocalStack Container (Development/Testing)
- **Base**: LocalStack 2.3
- **Purpose**: Provides local S3-compatible storage for testing
- **Ports**: 4566 (S3 API), 4510-4559 (service ports)

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    FastAPI Application                          │
│                                                                 │
│  ┌──────────────────────┐    ┌──────────────────────┐           │
│  │ REST API Endpoints   │    │ Web HTTP Endpoints   │           │
│  └──────────────────────┘    └──────────────────────┘           │
│           │                                     │               │
│           └─────────────────────────────────────┘               │
│                            │                                    │
│  ┌─────────────────────────┼─────────────────────────────────┐  │
│  │                  Core Services                            │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌──────────────┐       │  │
│  │  │Orchestrator │  │Upload Worker│  │ File Monitor │       │  │
│  │  └─────────────┘  └─────────────┘  └──────────────┘       │  │
│  └───────────────────────────────────────────────────────────┘  │
│                            │                                    │
│  ┌─────────────────────────┼─────────────────────────────────┐  │ 
│  │                     Data Layer                            │  │ 
│  │           ┌─────────────┐              ┌─────────────┐    │  │
│  │           │   SQLite    │              │    S3       │    │  │
│  │           │  Database   │              │  Storage    │    │  │
│  │           └─────────────┘              └─────────────┘    │  │ 
│  └───────────────────────────────────────────────────────────┘  │ 
└─────────────────────────────────────────────────────────────────┘
```

## Main Components Flow

### 1. Orchestrator
**Purpose**: Manages upload jobs and coordinates file uploads

**Flow**:
```
1. Receives upload job from API
2. Scans source folder for matching files
3. Creates file records in database
4. Submits files to upload worker pool
5. Handles job completion/failure
```

**Key Features**:
- Concurrent file processing (configurable workers)
- Progress tracking and state management
- Error handling and recovery
- File filtering by glob patterns

### 2. Upload Worker
**Purpose**: Handles individual file uploads to S3

**Flow**:
```
1. Receives file upload task
2. Determines upload strategy (simple/multipart)
3. Uploads file in chunks if large
4. Verifies upload integrity
5. Updates file state in database
```

**Key Features**:
- Multipart upload for large files (>5MB)
- Parallel chunk uploads
- Upload verification
- Retry logic for failed uploads

### 3. File Monitor
**Purpose**: Continuously monitors source folders of completed jobs for file changes

**Flow**:
```
1. Scans completed upload jobs periodically
2. Checks for new/modified files in source folders
3. Triggers orchestrator to sync changed files
4. Maintains file state consistency
```

**Key Features**:
- Configurable scan intervals (default: 60s)
- File change detection (mtime/size)
- Triggers orchestrator for sync operations
- Stability threshold to avoid partial writes

## FastAPI REST API

The service exposes a clean REST API for upload management:

### Core Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/uploads/` | Create new upload job |
| `GET` | `/api/v1/uploads/{upload_id}` | Get upload job status |
| `GET` | `/api/v1/uploads/` | List all upload jobs |
| `GET` | `/api/v1/uploads/{upload_id}/files` | List files in upload job |
| `GET` | `/health` | Health check endpoint |

### Request/Response Examples

**Create Upload Job**:
```json
POST /api/v1/uploads/
{
  "upload_id": "optional-custom-id",
  "source_folder": "/path/to/source",
  "destination_bucket": "my-s3-bucket",
  "pattern": "*.txt"
}

Response:
{
  "upload_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "created"
}
```

**Check Progress**:
```json
GET /api/v1/uploads/{upload_id}
{
  "upload_id": "550e8400-e29b-41d4-a716-446655440000",
  "progress": 0.75,
  "state": "IN_PROGRESS",
  "total_files": 100,
  "completed_files": 75,
  "created_at": "2023-12-01T10:00:00Z",
  "updated_at": "2023-12-01T10:15:00Z"
}
```

## Recovery Flow

The system implements a comprehensive recovery mechanism to handle failures gracefully:

### Startup Recovery
1. **Database Scan**: On startup, scans database for incomplete jobs
2. **State Assessment**: Identifies jobs in `PENDING` or `IN_PROGRESS` states
3. **Resume Processing**: Continues upload from where it left off

### Recovery Components
- **Job Recovery**: Resumes incomplete upload jobs
- **File Recovery**: Skips already uploaded files
- **Error Handling**: Marks failed jobs appropriately

### Recovery Flow Diagram
```
Service Startup
       │
       ▼
┌─────────────────┐
│ Scan Database   │
│ for Incomplete  │
│ Jobs            │
└─────────────────┘
       │
       ▼
┌─────────────────┐
│ For Each Job:   │
│ - Check S3      │
│ - Update States │
│ - Resume Upload │
└─────────────────┘
       │
       ▼
┌─────────────────┐
│ Start Normal    │
│ Operations      │
└─────────────────┘
```

## Database Tables

### UploadJob Table
```sql
CREATE TABLE upload_jobs (
    id VARCHAR PRIMARY KEY,              -- Unique upload job identifier
    source_folder TEXT NOT NULL,        -- Source directory path
    destination_bucket TEXT NOT NULL,   -- S3 bucket name
    pattern TEXT,                       -- File glob pattern (optional)
    state ENUM NOT NULL DEFAULT 'PENDING', -- PENDING, IN_PROGRESS, COMPLETED, FAILED
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### File Table
```sql
CREATE TABLE files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    upload_job_id VARCHAR NOT NULL,     -- Foreign key to upload_jobs.id
    path TEXT NOT NULL,                 -- Relative path from source_folder
    state ENUM NOT NULL DEFAULT 'PENDING', -- PENDING, IN_PROGRESS, UPLOADED, FAILED
    failure_reason TEXT,                -- Error message for failed uploads
    mtime TIMESTAMP,                    -- File modification time
    size BIGINT,                        -- File size in bytes
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (upload_job_id) REFERENCES upload_jobs(id)
);
```

### State Transitions

**Upload Job States**:
- `PENDING` → `IN_PROGRESS` → `COMPLETED`
- `PENDING` → `IN_PROGRESS` → `FAILED`

**File States**:
- `PENDING` → `IN_PROGRESS` → `UPLOADED`
- `PENDING` → `IN_PROGRESS` → `FAILED`

## Configuration

The system supports flexible configuration through environment variables:

| Variable               | Default                      | Description                  |
|------------------------|-----------------------------|------------------------------|
| `DATABASE_URL`         | `sqlite:///./data/uploads.db`| Database connection          |
| `CHUNK_SIZE`           | `5242880`                   | Upload chunk size (5MB)      |
| `WORKER_CONCURRENCY`   | `5`                         | Concurrent upload workers    |
| `FILE_MONITOR_INTERVAL`| `60`                        | File scan interval (seconds) |
| `AWS_ENDPOINT_URL`     | `http://localhost:4566`     | S3 endpoint (LocalStack)     |

## Deployment

### Docker Compose
```yaml
services:
  upload-service:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - "./data:/app/data"
      - "~/Desktop:/userdata/Desktop"
    depends_on:
      - localstack
      
  localstack:
    image: localstack/localstack:2.3
    ports:
      - "4566:4566"
```

### Production Considerations
- Replace SQLite with PostgreSQL for production
- Use IAM roles instead of access keys
- Implement proper authentication/authorization
- Add monitoring and alerting
- Configure proper backup strategies

## Performance Characteristics

- **Concurrent Uploads**: 5 workers by default (configurable)
- **Chunk Size**: 5MB for multipart uploads
- **File Monitoring**: 60-second intervals
- **Database**: SQLite for development, PostgreSQL recommended for production
- **Recovery**: Automatic on startup, minimal downtime

## Error Handling

The system implements comprehensive error handling:
- **Network Failures**: Automatic retry with exponential backoff
- **File System Errors**: Graceful handling of missing files
- **S3 Errors**: Proper error reporting and cleanup
- **Database Errors**: Transaction rollbacks and consistency checks 
