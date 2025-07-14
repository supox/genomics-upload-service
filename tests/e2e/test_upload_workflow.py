import os
import time
import asyncio
import tempfile
import shutil
from pathlib import Path
from typing import Dict, Any

import pytest
import httpx
import boto3
from botocore.exceptions import ClientError

# Test configuration
TEST_BASE_URL = "http://localhost:8000"
S3_ENDPOINT_URL = "http://localhost:4566"
TEST_BUCKET = "test-upload-bucket"
AWS_ACCESS_KEY_ID = "test"
AWS_SECRET_ACCESS_KEY = "test"
AWS_REGION = "us-east-1"

class TestUploadWorkflow:
    """End-to-end test for the complete upload workflow"""
    
    @pytest.fixture(scope="class")
    def s3_client(self):
        """Create S3 client for testing"""
        return boto3.client(
            's3',
            endpoint_url=S3_ENDPOINT_URL,
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            region_name=AWS_REGION
        )
    
    @pytest.fixture(scope="class")
    def test_files_dir(self):
        """Create test directory with test files in data directory (accessible from container)"""
        # Use data directory that's mounted in container
        base_data_dir = Path("./data")
        base_data_dir.mkdir(exist_ok=True)
        
        # Create unique test directory
        import uuid
        test_dir = base_data_dir / f"upload_test_{uuid.uuid4().hex[:8]}"
        test_dir.mkdir(exist_ok=True)
        
        # Create test files with specific sizes
        test_files = {
            "small_file.txt": 10 * 1024,      # 10KB
            "medium_file.txt": 1024 * 1024,   # 1MB
            "large_file.txt": 2 * 1024 * 1024, # 2MB
            "xlarge_file.txt": 5 * 1024 * 1024 # 5MB
        }
        
        for filename, size in test_files.items():
            file_path = test_dir / filename
            self._create_test_file(file_path, size)
        
        yield str(test_dir)
        
        # Cleanup
        shutil.rmtree(test_dir, ignore_errors=True)
    
    def _create_test_file(self, file_path: Path, size: int):
        """Create a test file with specific size"""
        with open(file_path, 'wb') as f:
            # Create content with repeating pattern for easier verification
            pattern = b"Test data for upload service - "
            pattern_len = len(pattern)
            
            written = 0
            while written < size:
                remaining = size - written
                if remaining >= pattern_len:
                    f.write(pattern)
                    written += pattern_len
                else:
                    f.write(pattern[:remaining])
                    written += remaining
    
    @pytest.fixture(scope="class")
    def ensure_bucket(self, s3_client):
        """Ensure test bucket exists"""
        try:
            s3_client.head_bucket(Bucket=TEST_BUCKET)
        except ClientError:
            s3_client.create_bucket(Bucket=TEST_BUCKET)
        
        yield
        
        # Cleanup - remove all objects from bucket
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
    
    @pytest.mark.asyncio
    @pytest.mark.e2e
    @pytest.mark.slow
    async def test_complete_upload_workflow(self, test_files_dir, s3_client, ensure_bucket):
        """Test the complete upload workflow end-to-end"""
        
        # Step 1: Create upload job
        upload_job_data = {
            "source_folder": test_files_dir,
            "destination_bucket": TEST_BUCKET,
            "pattern": "*.txt"
        }
        
        upload_id = await self._create_upload_job(upload_job_data)
        assert upload_id is not None, "Failed to create upload job"
        
        # Step 2: Poll for completion
        final_status = await self._poll_upload_status(upload_id)
        
        # Step 3: Verify completion
        assert final_status["state"] == "COMPLETED", f"Upload failed with state: {final_status['state']}"
        assert final_status["progress"] == 1.0, f"Upload progress not 100%: {final_status['progress']}"
        assert final_status["total_files"] == 4, f"Expected 4 files, got {final_status['total_files']}"
        assert final_status["completed_files"] == 4, f"Expected 4 completed files, got {final_status['completed_files']}"
        
        # Step 4: Verify files in S3
        await self._verify_s3_files(s3_client, upload_id, test_files_dir)
        
        print(f"✅ End-to-end test completed successfully!")
        print(f"Upload ID: {upload_id}")
        print(f"Final Status: {final_status}")
    
    async def _wait_for_service(self, timeout: int = 60):
        """Wait for the service to be ready"""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(f"{TEST_BASE_URL}/health")
                    if response.status_code == 200:
                        print("✅ Service is ready")
                        return
            except Exception:
                pass
            
            await asyncio.sleep(1)
        
        raise TimeoutError("Service did not become ready within timeout period")
    
    async def _create_upload_job(self, job_data: Dict[str, Any]) -> str:
        """Create upload job and return upload ID"""
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{TEST_BASE_URL}/api/v1/uploads/",
                json=job_data,
                timeout=120.0
            )
            
            assert response.status_code == 200, f"Failed to create upload job: {response.text}"
            
            result = response.json()
            upload_id = result["upload_id"]
            
            print(f"✅ Created upload job: {upload_id}")
            return upload_id
    
    async def _poll_upload_status(self, upload_id: str, timeout: int = 120) -> Dict[str, Any]:
        """Poll upload status until completion or timeout"""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.get(f"{TEST_BASE_URL}/api/v1/uploads/{upload_id}")
                
                assert response.status_code == 200, f"Failed to get upload status: {response.text}"
                
                status = response.json()
                state = status["state"]
                progress = status["progress"]
                
                print(f"📊 Upload Status: {state} - Progress: {progress:.1%} - Files: {status['completed_files']}/{status['total_files']}")
                
                if state in ["COMPLETED", "FAILED"]:
                    return status
                
                await asyncio.sleep(2)
        
        raise TimeoutError(f"Upload did not complete within {timeout} seconds")
    
    async def _verify_s3_files(self, s3_client, upload_id: str, source_dir: str):
        """Verify that all files were uploaded correctly to S3"""
        source_path = Path(source_dir)
        
        # List objects in S3 bucket with the upload_id prefix
        response = s3_client.list_objects_v2(Bucket=TEST_BUCKET, Prefix=upload_id)
        
        assert 'Contents' in response, "No files found in S3 bucket"
        
        s3_objects = {obj['Key']: obj for obj in response['Contents']}
        
        # Verify each expected file
        expected_files = ["small_file.txt", "medium_file.txt", "large_file.txt", "xlarge_file.txt"]
        
        for filename in expected_files:
            # Expected S3 key
            expected_key = f"{upload_id}/{filename}"
            
            assert expected_key in s3_objects, f"File {filename} not found in S3"
            
            # Verify file size
            local_file = source_path / filename
            local_size = local_file.stat().st_size
            s3_size = s3_objects[expected_key]['Size']
            
            assert local_size == s3_size, f"Size mismatch for {filename}: local={local_size}, s3={s3_size}"
            
            # Verify file content (for smaller files)
            if local_size <= 1024 * 1024:  # Only verify content for files <= 1MB
                await self._verify_file_content(s3_client, expected_key, local_file)
            
            print(f"✅ Verified {filename}: {local_size} bytes")
    
    async def _verify_file_content(self, s3_client, s3_key: str, local_file: Path):
        """Verify file content matches between local and S3"""
        # Read local file
        with open(local_file, 'rb') as f:
            local_content = f.read()
        
        # Read S3 file
        response = s3_client.get_object(Bucket=TEST_BUCKET, Key=s3_key)
        s3_content = response['Body'].read()
        
        assert local_content == s3_content, f"Content mismatch for {s3_key}"
    
    @pytest.mark.asyncio
    @pytest.mark.e2e
    @pytest.mark.slow
    async def test_upload_with_pattern_filter(self, test_files_dir, s3_client, ensure_bucket):
        """Test upload with pattern filtering"""
        
        # Create additional file with different extension
        test_file = Path(test_files_dir) / "test.log"
        self._create_test_file(test_file, 1024)  # 1KB
        
        # Create upload job with pattern filter
        upload_job_data = {
            "source_folder": test_files_dir,
            "destination_bucket": TEST_BUCKET,
            "pattern": "*.txt"  # Only .txt files
        }
        
        upload_id = await self._create_upload_job(upload_job_data)
        final_status = await self._poll_upload_status(upload_id)
        
        # Should only upload .txt files (4 files), not the .log file
        assert final_status["state"] == "COMPLETED"
        assert final_status["total_files"] == 4, f"Expected 4 files with pattern filter, got {final_status['total_files']}"
        
        # Verify .log file was not uploaded
        response = s3_client.list_objects_v2(Bucket=TEST_BUCKET, Prefix=upload_id)
        s3_keys = [obj['Key'] for obj in response.get('Contents', [])]
        log_key = f"{upload_id}/test.log"
        
        assert log_key not in s3_keys, "Log file should not have been uploaded with txt pattern"
        
        print(f"✅ Pattern filtering test completed successfully!")
    
    @pytest.mark.asyncio
    @pytest.mark.e2e
    async def test_upload_job_listing(self, test_files_dir, ensure_bucket):
        """Test listing upload jobs"""
        
        # Create upload job
        upload_job_data = {
            "source_folder": test_files_dir,
            "destination_bucket": TEST_BUCKET,
            "pattern": "small_file.txt"  # Only one file
        }
        
        upload_id = await self._create_upload_job(upload_job_data)
        
        # List upload jobs
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.get(f"{TEST_BASE_URL}/api/v1/uploads/")
            
            assert response.status_code == 200
            
            result = response.json()
            
            assert "uploads" in result
            assert len(result["uploads"]) > 0
            
            # Find our upload job
            our_job = None
            for job in result["uploads"]:
                if job["upload_id"] == upload_id:
                    our_job = job
                    break
            
            assert our_job is not None, "Upload job not found in listing"
            assert "progress" in our_job
            assert "state" in our_job
            assert "total_files" in our_job
            assert "completed_files" in our_job
            
            print(f"✅ Upload job listing test completed successfully!")


# Utility function to run the test with proper setup
async def run_e2e_test():
    """Run the end-to-end test"""
    test_instance = TestUploadWorkflow()
    
    # Create temporary test directory
    with tempfile.TemporaryDirectory(prefix="upload_test_") as temp_dir:
        # Create test files
        test_files = {
            "small_file.txt": 10 * 1024,      # 10KB
            "medium_file.txt": 1024 * 1024,   # 1MB
            "large_file.txt": 2 * 1024 * 1024, # 2MB
            "xlarge_file.txt": 5 * 1024 * 1024 # 5MB
        }
        
        for filename, size in test_files.items():
            file_path = Path(temp_dir) / filename
            test_instance._create_test_file(file_path, size)
        
        # Create S3 client
        s3_client = boto3.client(
            's3',
            endpoint_url=S3_ENDPOINT_URL,
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            region_name=AWS_REGION
        )
        
        # Ensure bucket exists
        try:
            s3_client.head_bucket(Bucket=TEST_BUCKET)
        except ClientError:
            s3_client.create_bucket(Bucket=TEST_BUCKET)
        
        # Run the test
        await test_instance.test_complete_upload_workflow(temp_dir, s3_client, None)

if __name__ == "__main__":
    asyncio.run(run_e2e_test()) 
