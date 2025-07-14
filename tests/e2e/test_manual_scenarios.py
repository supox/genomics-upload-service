import os
import time
import asyncio
import tempfile
import shutil
from pathlib import Path
from typing import Dict, Any, List

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


class TestManualScenarios:
    """Test cases converted from manual test scenarios"""
    
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
        
        # Create test files with specific sizes (matching manual test)
        test_files = {
            "small_file.txt": 10 * 1024,      # 10KB
            "medium_file.txt": 1024 * 1024,   # 1MB
            "large_file.txt": 2 * 1024 * 1024, # 2MB
            "xlarge_file.txt": 5 * 1024 * 1024 # 5MB
        }
        
        # Create files with random data (matching manual test approach)
        chunk_size = 1024 * 1024  # 1MB
        
        for filename, size in test_files.items():
            file_path = test_dir / filename
            
            with open(file_path, 'wb') as f:
                written = 0
                while written < size:
                    remaining = size - written
                    write_size = min(chunk_size, remaining)
                    # Generate random data directly - much faster than pattern repetition
                    f.write(os.urandom(write_size))
                    written += write_size
        
        yield str(test_dir)
        
        # Cleanup
        shutil.rmtree(test_dir, ignore_errors=True)
    
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
    @pytest.mark.smoke
    @pytest.mark.health
    async def test_service_health_check(self):
        """Test service health check endpoint"""
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.get(f"{TEST_BASE_URL}/health")
            
            assert response.status_code == 200, f"Health check failed: {response.text}"
            
            health_data = response.json()
            assert health_data["status"] == "healthy", f"Service not healthy: {health_data}"
            
            print("✅ Service is healthy")
    
    @pytest.mark.asyncio
    @pytest.mark.api
    @pytest.mark.manual
    async def test_create_upload_job(self, test_files_dir, ensure_bucket):
        """Test creating an upload job"""
        job_data = {
            "source_folder": test_files_dir,
            "destination_bucket": TEST_BUCKET,
            "pattern": "*.txt"
        }
        
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{TEST_BASE_URL}/api/v1/uploads/",
                json=job_data,
                timeout=120
            )
            
            assert response.status_code == 200, f"Failed to create upload job: {response.text}"
            
            result = response.json()
            upload_id = result["upload_id"]
            
            assert upload_id is not None, "Upload ID should not be None"
            assert isinstance(upload_id, str), "Upload ID should be a string"
            
            print(f"✅ Upload job created: {upload_id}")
            return upload_id
    
    @pytest.mark.asyncio
    @pytest.mark.e2e
    @pytest.mark.manual
    @pytest.mark.slow
    async def test_poll_upload_status(self, test_files_dir, ensure_bucket):
        """Test polling upload status until completion"""
        # Create upload job
        upload_id = await self._create_upload_job(test_files_dir)
        
        # Poll for completion
        final_status = await self._poll_upload_status(upload_id)
        
        # Verify completion
        assert final_status["state"] == "COMPLETED", f"Upload failed with state: {final_status['state']}"
        assert final_status["progress"] == 1.0, f"Upload progress not 100%: {final_status['progress']}"
        assert final_status["total_files"] == 4, f"Expected 4 files, got {final_status['total_files']}"
        assert final_status["completed_files"] == 4, f"Expected 4 completed files, got {final_status['completed_files']}"
        
        print(f"✅ Upload completed successfully: {upload_id}")
    
    @pytest.mark.asyncio
    @pytest.mark.e2e
    @pytest.mark.manual
    @pytest.mark.slow
    async def test_verify_s3_files(self, test_files_dir, s3_client, ensure_bucket):
        """Test verifying files were uploaded to S3 correctly"""
        # Create upload job and wait for completion
        upload_id = await self._create_upload_job(test_files_dir)
        final_status = await self._poll_upload_status(upload_id)
        
        assert final_status["state"] == "COMPLETED", "Upload must complete before verification"
        
        # Verify files in S3
        source_path = Path(test_files_dir)
        
        # List objects in S3 bucket
        response = s3_client.list_objects_v2(Bucket=TEST_BUCKET, Prefix=upload_id)
        
        assert 'Contents' in response, "No files found in S3 bucket"
        
        s3_objects = {obj['Key']: obj for obj in response['Contents']}
        
        # Check each expected file
        expected_files = ["small_file.txt", "medium_file.txt", "large_file.txt", "xlarge_file.txt"]
        
        for filename in expected_files:
            s3_key = f"{upload_id}/{filename}"
            
            assert s3_key in s3_objects, f"File {filename} not found in S3"
            
            # Compare file sizes
            local_file = source_path / filename
            local_size = local_file.stat().st_size
            s3_size = s3_objects[s3_key]['Size']
            
            assert local_size == s3_size, f"Size mismatch for {filename}: local={local_size}, s3={s3_size}"
            
            print(f"✅ Verified {filename}: {local_size:,} bytes")
        
        print("✅ All files verified successfully in S3")
    
    @pytest.mark.asyncio
    @pytest.mark.api
    @pytest.mark.manual
    async def test_list_upload_jobs(self, test_files_dir, ensure_bucket, clean_api_database):
        """Test listing upload jobs"""
        # Create multiple upload jobs
        upload_id1 = await self._create_upload_job(test_files_dir)
        upload_id2 = await self._create_upload_job(test_files_dir)
        
        # List upload jobs
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.get(f"{TEST_BASE_URL}/api/v1/uploads/")
            
            assert response.status_code == 200, f"Failed to list uploads: {response.text}"
            
            result = response.json()
            uploads = result["uploads"]
            
            assert len(uploads) >= 2, f"Expected at least 2 uploads, got {len(uploads)}"
            
            # Check that our uploads are in the list
            upload_ids = [upload["upload_id"] for upload in uploads]
            assert upload_id1 in upload_ids, f"Upload {upload_id1} not found in list"
            assert upload_id2 in upload_ids, f"Upload {upload_id2} not found in list"
            
            print(f"✅ Found {len(uploads)} upload jobs in list")
            
            # Verify each upload has required fields
            for upload in uploads:
                assert "upload_id" in upload, "Upload missing upload_id"
                assert "state" in upload, "Upload missing state"
                assert "progress" in upload, "Upload missing progress"
                assert "total_files" in upload, "Upload missing total_files"
                assert "completed_files" in upload, "Upload missing completed_files"
                
                print(f"📦 {upload['upload_id'][:8]}... - {upload['state']} - {upload['progress']:.1%}")
    
    @pytest.mark.asyncio
    @pytest.mark.e2e
    @pytest.mark.manual
    @pytest.mark.slow
    async def test_complete_manual_workflow(self, test_files_dir, s3_client, ensure_bucket):
        """Test complete manual workflow as described in manual_test.py"""
        print("🧪 Running complete manual workflow test")
        
        # Step 1: Check service health
        await self.test_service_health_check()
        
        # Step 2: Create upload job
        upload_id = await self._create_upload_job(test_files_dir)
        assert upload_id is not None, "Failed to create upload job"
        
        # Step 3: Poll for completion
        final_status = await self._poll_upload_status(upload_id)
        assert final_status["state"] == "COMPLETED", f"Upload failed with state: {final_status['state']}"
        
        # Step 4: Verify files in S3
        await self._verify_s3_files(s3_client, upload_id, test_files_dir)
        
        # Step 5: List all uploads
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.get(f"{TEST_BASE_URL}/api/v1/uploads/")
            assert response.status_code == 200, "Failed to list uploads"
            
            result = response.json()
            uploads = result["uploads"]
            
            # Find our upload in the list
            our_upload = next((u for u in uploads if u["upload_id"] == upload_id), None)
            assert our_upload is not None, "Our upload not found in list"
            assert our_upload["state"] == "COMPLETED", "Upload not marked as completed in list"
            
            print(f"✅ Upload {upload_id} found in list with COMPLETED state")
        
        print("🎉 Complete manual workflow test completed successfully!")
    
    @pytest.mark.asyncio
    @pytest.mark.validation
    @pytest.mark.manual
    async def test_error_handling(self):
        """Test error handling scenarios"""
        
        # Test invalid source folder
        job_data = {
            "source_folder": "/nonexistent/path",
            "destination_bucket": TEST_BUCKET,
            "pattern": "*.txt"
        }
        
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{TEST_BASE_URL}/api/v1/uploads/",
                json=job_data,
                timeout=120
            )
            
            # Should either fail immediately or create job that fails
            if response.status_code == 200:
                result = response.json()
                upload_id = result["upload_id"]
                
                # Poll for a bit to see if it fails
                start_time = time.time()
                while time.time() - start_time < 30:
                    status_response = await client.get(f"{TEST_BASE_URL}/api/v1/uploads/{upload_id}")
                    if status_response.status_code == 200:
                        status = status_response.json()
                        if status["state"] == "FAILED":
                            print("✅ Upload correctly failed for invalid source folder")
                            break
                    await asyncio.sleep(1)
                else:
                    pytest.fail("Upload should have failed for invalid source folder")
            else:
                print("✅ API correctly rejected invalid source folder")
    
    async def _create_upload_job(self, source_folder: str) -> str:
        """Create upload job and return upload ID"""
        # Convert host path to container path
        # The data directory is mounted from ./data to /app/data in the container
        if source_folder.startswith("./data/"):
            container_path = source_folder.replace("./data/", "/app/data/")
        elif source_folder.startswith("data/"):
            container_path = source_folder.replace("data/", "/app/data/")
        else:
            container_path = source_folder
            
        job_data = {
            "source_folder": container_path,
            "destination_bucket": TEST_BUCKET,
            "pattern": "*.txt"
        }
        
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{TEST_BASE_URL}/api/v1/uploads/",
                json=job_data,
                timeout=120
            )
            
            assert response.status_code == 200, f"Failed to create upload job: {response.text}"
            
            result = response.json()
            upload_id = result["upload_id"]
            
            print(f"✅ Created upload job: {upload_id}")
            return upload_id
    
    async def _poll_upload_status(self, upload_id: str, timeout: int = 120) -> Dict[str, Any]:
        """Poll upload status until completion"""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.get(f"{TEST_BASE_URL}/api/v1/uploads/{upload_id}")
                
                assert response.status_code == 200, f"Failed to get upload status: {response.text}"
                
                status = response.json()
                state = status["state"]
                progress = status["progress"]
                completed = status["completed_files"]
                total = status["total_files"]
                
                print(f"📈 Status: {state} - Progress: {progress:.1%} - Files: {completed}/{total}")
                
                if state in ["COMPLETED", "FAILED"]:
                    return status
                
                await asyncio.sleep(2)
        
        raise TimeoutError(f"Upload did not complete within {timeout} seconds")
    
    async def _verify_s3_files(self, s3_client, upload_id: str, source_dir: str):
        """Verify files were uploaded to S3"""
        source_path = Path(source_dir)
        
        # List objects in bucket
        response = s3_client.list_objects_v2(Bucket=TEST_BUCKET, Prefix=upload_id)
        
        assert 'Contents' in response, "No files found in S3 bucket"
        
        s3_objects = {obj['Key']: obj for obj in response['Contents']}
        
        # Check each expected file
        expected_files = ["small_file.txt", "medium_file.txt", "large_file.txt", "xlarge_file.txt"]
        
        for filename in expected_files:
            s3_key = f"{upload_id}/{filename}"
            
            assert s3_key in s3_objects, f"File {filename} not found in S3"
            
            # Compare file sizes
            local_file = source_path / filename
            local_size = local_file.stat().st_size
            s3_size = s3_objects[s3_key]['Size']
            
            assert local_size == s3_size, f"Size mismatch for {filename}: local={local_size}, s3={s3_size}"
            
            print(f"✅ {filename}: {local_size:,} bytes")
        
        print("✅ All files verified successfully") 
