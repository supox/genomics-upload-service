"""
Pytest configuration and shared fixtures for the file upload service tests.
"""

import pytest
import asyncio
import tempfile
import shutil
import subprocess
import time
import os
from pathlib import Path
from typing import Generator, Dict, Any
import boto3
from botocore.exceptions import ClientError
import httpx


# Set test environment variables
os.environ["TESTING"] = "true"
os.environ["DATABASE_URL"] = "sqlite:///./test_uploads.db"
os.environ["FILE_MONITOR_INTERVAL"] = "999999"  # Disable file monitor during tests

# Test configuration constants
TEST_BASE_URL = "http://localhost:8000"
S3_ENDPOINT_URL = "http://localhost:4566"
TEST_BUCKET = "test-upload-bucket"
AWS_ACCESS_KEY_ID = "test"
AWS_SECRET_ACCESS_KEY = "test"
AWS_REGION = "us-east-1"


def check_docker_available():
    """Check if Docker and Docker Compose are available"""
    try:
        subprocess.run(["docker", "--version"], check=True, capture_output=True)
        subprocess.run(["docker-compose", "--version"], check=True, capture_output=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def start_docker_services():
    """Start docker-compose services and wait for them to be healthy"""
    print("🚀 Starting Docker services...")
    
    # Check if docker is available
    if not check_docker_available():
        raise RuntimeError("Docker or Docker Compose not available. Please install Docker.")
    
    try:
        # Start services in detached mode with test configuration
        result = subprocess.run(
            ["docker-compose", "-f", "docker-compose.yml", "-f", "docker-compose.test.yml", "up", "-d", "--build"],
            cwd=Path(__file__).parent,
            check=True,
            capture_output=True,
            text=True
        )
        print("✅ Docker services started")
        
        # Wait for services to be healthy
        wait_for_docker_services()
        
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to start Docker services: {e}")
        print(f"stdout: {e.stdout}")
        print(f"stderr: {e.stderr}")
        raise RuntimeError("Failed to start Docker services") from e


def wait_for_docker_services():
    """Wait for all services to be healthy"""
    print("⏳ Waiting for services to be healthy...")
    
    services = {
        "LocalStack S3": "http://localhost:4566/_localstack/health",
        "Upload Service": f"{TEST_BASE_URL}/health"
    }
    
    max_wait = 180  # 3 minutes
    start_time = time.time()
    
    for service_name, health_url in services.items():
        print(f"  Checking {service_name}...")
        
        while time.time() - start_time < max_wait:
            try:
                import requests
                response = requests.get(health_url, timeout=5)
                if response.status_code == 200:
                    print(f"  ✅ {service_name} is healthy")
                    break
            except requests.RequestException:
                pass
            
            time.sleep(2)
        else:
            raise RuntimeError(f"{service_name} did not become healthy within {max_wait} seconds")
    
    print("✅ All services are healthy and ready")


def stop_docker_services():
    """Stop docker-compose services (optional cleanup)"""
    # Note: We might want to leave services running for faster subsequent test runs
    # Uncomment the following lines if you want to stop services after tests
    
    # try:
    #     subprocess.run(
    #         ["docker-compose", "-f", "docker-compose.yml", "-f", "docker-compose.test.yml", "down"],
    #         cwd=Path(__file__).parent,
    #         check=True,
    #         capture_output=True
    #     )
    #     print("✅ Docker services stopped")
    # except subprocess.CalledProcessError:
    #     print("⚠️  Warning: Failed to stop Docker services")
    pass


@pytest.fixture(scope="session", autouse=True)
def docker_services():
    """Automatically start and manage Docker services for the test session"""
    # Only start services for tests that need them (e2e, api, integration tests)
    # Unit tests can run without services
    
    # Check if we're running tests that need services
    import sys
    needs_services = any(
        marker in ' '.join(sys.argv) for marker in 
        ['e2e', 'api', 'integration', 'manual', 'health']
    ) or not any(
        marker in ' '.join(sys.argv) for marker in 
        ['unit', '-m unit']
    )
    
    if not needs_services:
        print("🔧 Running unit tests only - skipping service startup")
        yield
        return
    
    # Start services
    try:
        start_docker_services()
        yield
    except Exception as e:
        print(f"💥 Failed to start services: {e}")
        print("🔧 Tests require Docker services to be running.")
        print("   Make sure Docker is installed and running.")
        raise pytest.UsageError(f"Service startup failed: {e}")
    finally:
        # Optional cleanup
        stop_docker_services()


# Removed custom event_loop fixture as it's deprecated in pytest-asyncio 0.23+
# Use pytest.mark.asyncio(scope="session") on test classes instead


@pytest.fixture(scope="session")
def s3_client():
    """Create S3 client for testing (session-scoped)."""
    return boto3.client(
        's3',
        endpoint_url=S3_ENDPOINT_URL,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        region_name=AWS_REGION
    )


@pytest.fixture(scope="session")
def ensure_test_bucket(s3_client):
    """Ensure test bucket exists (session-scoped)."""
    try:
        s3_client.head_bucket(Bucket=TEST_BUCKET)
    except ClientError:
        s3_client.create_bucket(Bucket=TEST_BUCKET)
    
    yield TEST_BUCKET


@pytest.fixture
def test_files_dir() -> Generator[str, None, None]:
    """Create temporary directory with test files."""
    temp_dir = tempfile.mkdtemp(prefix="upload_test_")
    
    # Create test files with specific sizes
    test_files = {
        "small_file.txt": 10 * 1024,      # 10KB
        "medium_file.txt": 1024 * 1024,   # 1MB
        "large_file.txt": 2 * 1024 * 1024, # 2MB
        "xlarge_file.txt": 5 * 1024 * 1024 # 5MB
    }
    
    # Create files with random data
    chunk_size = 1024 * 1024  # 1MB
    
    for filename, size in test_files.items():
        file_path = Path(temp_dir) / filename
        
        with open(file_path, 'wb') as f:
            written = 0
            while written < size:
                remaining = size - written
                write_size = min(chunk_size, remaining)
                # Use pattern data instead of random for easier debugging
                pattern = b"Test data for upload service - " * (write_size // 32 + 1)
                f.write(pattern[:write_size])
                written += write_size
    
    yield temp_dir
    
    # Cleanup
    shutil.rmtree(temp_dir)


@pytest.fixture
def clean_s3_bucket(s3_client, ensure_test_bucket):
    """Clean S3 bucket before test."""
    # Clean before test
    try:
        response = s3_client.list_objects_v2(Bucket=TEST_BUCKET)
        if 'Contents' in response:
            objects = [{'Key': obj['Key']} for obj in response['Contents']]
            s3_client.delete_objects(
                Bucket=TEST_BUCKET,
                Delete={'Objects': objects}
            )
    except ClientError:
        pass
    
    yield
    
    # Clean after test
    try:
        response = s3_client.list_objects_v2(Bucket=TEST_BUCKET)
        if 'Contents' in response:
            objects = [{'Key': obj['Key']} for obj in response['Contents']]
            s3_client.delete_objects(
                Bucket=TEST_BUCKET,
                Delete={'Objects': objects}
            )
    except ClientError:
        pass


@pytest.fixture
async def http_client():
    """Create HTTP client for API testing."""
    async with httpx.AsyncClient(base_url=TEST_BASE_URL, timeout=30.0) as client:
        yield client


@pytest.fixture
async def wait_for_service():
    """Wait for service to be available."""
    import time
    
    start_time = time.time()
    timeout = 60
    
    while time.time() - start_time < timeout:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{TEST_BASE_URL}/health", timeout=5)
                if response.status_code == 200:
                    return
        except Exception:
            pass
        
        await asyncio.sleep(1)
    
    raise TimeoutError("Service did not become available within timeout")


@pytest.fixture
def upload_job_data(test_files_dir) -> Dict[str, Any]:
    """Create standard upload job data."""
    return {
        "source_folder": test_files_dir,
        "destination_bucket": TEST_BUCKET,
        "pattern": "*.txt"
    }


# Note: Test database fixtures removed to avoid SQLAlchemy import conflicts.
# Using API-based database cleanup instead.


@pytest.fixture(scope="function")
async def reset_api_database():
    """Reset the database via API call before each test"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Wait for service to be ready
            await wait_for_service_ready(client)
            
            # Try to reset the database
            response = await client.post(f"{TEST_BASE_URL}/api/v1/test/reset-database")
            if response.status_code == 200:
                result = response.json()
                print(f"✅ Database reset: {result['message']}")
                return True
            else:
                print(f"⚠️  Database reset failed: {response.status_code} - {response.text}")
                return False
    except Exception as e:
        print(f"⚠️  Database reset unavailable: {e}")
        return False


@pytest.fixture(scope="function", autouse=True)
async def clean_api_database():
    """Clean up old data via API call before and after each test"""
    # Only clean for tests that need it
    import sys
    needs_cleanup = any(
        marker in ' '.join(sys.argv) for marker in 
        ['e2e', 'api', 'integration', 'manual', 'health']
    ) or not any(
        marker in ' '.join(sys.argv) for marker in 
        ['unit', '-m unit']
    )
    
    if not needs_cleanup:
        yield
        return
    
    async def cleanup():
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Wait for service to be ready
                await wait_for_service_ready(client)
                
                # Clean up old data
                response = await client.delete(f"{TEST_BASE_URL}/api/v1/test/cleanup-old-data")
                if response.status_code == 200:
                    result = response.json()
                    print(f"✅ Database cleaned: {result['message']}")
                    return True
                else:
                    print(f"⚠️  Database cleanup failed: {response.status_code} - {response.text}")
                    return False
        except Exception as e:
            print(f"⚠️  Database cleanup unavailable: {e}")
            return False
    
    # Clean before test
    await cleanup()
    yield
    # Clean after test
    await cleanup()


async def wait_for_service_ready(client: httpx.AsyncClient, timeout: int = 30):
    """Wait for service to be ready"""
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            response = await client.get(f"{TEST_BASE_URL}/health")
            if response.status_code == 200:
                return
        except Exception:
            pass
        await asyncio.sleep(0.5)
    raise TimeoutError("Service not ready within timeout")


# Test configuration functions
def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line(
        "markers", 
        "smoke: marks tests as smoke tests (quick verification)"
    )
    config.addinivalue_line(
        "markers", 
        "slow: marks tests as slow running (may take more than 30 seconds)"
    )
    config.addinivalue_line(
        "markers", 
        "e2e: marks tests as end-to-end integration tests"
    )
    config.addinivalue_line(
        "markers", 
        "api: marks tests as API-focused tests"
    )
    config.addinivalue_line(
        "markers", 
        "unit: marks tests as unit tests"
    )
    config.addinivalue_line(
        "markers", 
        "validation: marks tests as validation/error handling tests"
    )
    config.addinivalue_line(
        "markers", 
        "health: marks tests as health check tests"
    )
    config.addinivalue_line(
        "markers", 
        "manual: marks tests converted from manual testing"
    )
    config.addinivalue_line(
        "markers", 
        "integration: marks tests as integration tests"
    )


def pytest_collection_modifyitems(config, items):
    """Modify test collection to add markers based on test names and paths."""
    for item in items:
        # Add markers based on test file paths
        if "test_api" in str(item.fspath):
            item.add_marker(pytest.mark.api)
        
        if "test_health" in str(item.fspath):
            item.add_marker(pytest.mark.health)
        
        if "e2e" in str(item.fspath):
            item.add_marker(pytest.mark.e2e)
        
        # Add markers based on test names
        if "health" in item.name:
            item.add_marker(pytest.mark.health)
            item.add_marker(pytest.mark.smoke)
        
        if "validation" in item.name:
            item.add_marker(pytest.mark.validation)
        
        if "error" in item.name:
            item.add_marker(pytest.mark.validation)
        
        if "slow" in item.name or "complete" in item.name:
            item.add_marker(pytest.mark.slow)


# Helper functions for tests
async def create_upload_job(client: httpx.AsyncClient, job_data: Dict[str, Any]) -> str:
    """Helper function to create upload job."""
    response = await client.post("/api/v1/uploads/", json=job_data)
    assert response.status_code == 200, f"Failed to create upload job: {response.text}"
    
    result = response.json()
    return result["upload_id"]


async def poll_upload_status(client: httpx.AsyncClient, upload_id: str, timeout: int = 120) -> Dict[str, Any]:
    """Helper function to poll upload status."""
    import time
    
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        response = await client.get(f"/api/v1/uploads/{upload_id}")
        assert response.status_code == 200, f"Failed to get upload status: {response.text}"
        
        status = response.json()
        if status["state"] in ["COMPLETED", "FAILED"]:
            return status
        
        await asyncio.sleep(2)
    
    raise TimeoutError(f"Upload did not complete within {timeout} seconds")


def verify_s3_files(s3_client, upload_id: str, source_dir: str, expected_files: list = None):
    """Helper function to verify S3 files."""
    if expected_files is None:
        expected_files = ["small_file.txt", "medium_file.txt", "large_file.txt", "xlarge_file.txt"]
    
    source_path = Path(source_dir)
    
    # List objects in bucket
    response = s3_client.list_objects_v2(Bucket=TEST_BUCKET, Prefix=upload_id)
    assert 'Contents' in response, "No files found in S3 bucket"
    
    s3_objects = {obj['Key']: obj for obj in response['Contents']}
    
    # Check each expected file
    for filename in expected_files:
        s3_key = f"{upload_id}/{filename}"
        assert s3_key in s3_objects, f"File {filename} not found in S3"
        
        # Compare file sizes
        local_file = source_path / filename
        local_size = local_file.stat().st_size
        s3_size = s3_objects[s3_key]['Size']
        
        assert local_size == s3_size, f"Size mismatch for {filename}: local={local_size}, s3={s3_size}"
    
    return True 
