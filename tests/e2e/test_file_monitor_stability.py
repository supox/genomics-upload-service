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


class TestFileMonitorStability:
    """End-to-end test for file monitor stability threshold"""
    
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
        """Create test directory with initial test files"""
        # Use data directory that's mounted in container
        base_data_dir = Path("./data")
        base_data_dir.mkdir(exist_ok=True)
        
        # Create unique test directory
        import uuid
        test_dir = base_data_dir / f"stability_test_{uuid.uuid4().hex[:8]}"
        test_dir.mkdir(exist_ok=True)
        
        # Create initial test file
        initial_file = test_dir / "initial_file.txt"
        initial_file.write_text("Initial file content")
        
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
    @pytest.mark.e2e
    @pytest.mark.slow
    async def test_file_monitor_stability_threshold(self, test_files_dir, s3_client, ensure_bucket):
        """Test that file monitor respects stability threshold and defers processing of recent files"""
        
        # Step 1: Create upload job via API
        upload_job_data = {
            "source_folder": test_files_dir,
            "destination_bucket": TEST_BUCKET,
            "pattern": "*.txt"
        }
        
        upload_id = await self._create_upload_job(upload_job_data)
        assert upload_id is not None, "Failed to create upload job"
        
        # Step 2: Poll until upload job completes
        final_status = await self._poll_upload_status(upload_id)
        assert final_status["state"] == "COMPLETED", f"Upload failed with state: {final_status['state']}"
        
        # Verify initial file was uploaded
        initial_s3_objects = await self._list_s3_objects(s3_client, upload_id)
        assert len(initial_s3_objects) == 1, "Initial file should be uploaded"
        
        print(f"✅ Initial upload completed with {len(initial_s3_objects)} files")
        
        # Step 3: Create new file under the source folder
        new_file_path = Path(test_files_dir) / "new_file.txt"
        new_file_path.write_text("New file content")
        
        print(f"✅ Created new file: {new_file_path}")
        
        # Step 4: Sleep 3 seconds
        await asyncio.sleep(3)
        
        # Step 5: Manually trigger file monitor check - should skip due to stability threshold
        await self._trigger_file_monitor_check(upload_id)
        
        # Assert the file is NOT copied to destination (due to default 30s threshold)
        current_s3_objects = await self._list_s3_objects(s3_client, upload_id)
        assert len(current_s3_objects) == 1, "New file should NOT be uploaded due to stability threshold"
        
        print(f"✅ New file correctly deferred due to stability threshold")
        
        # Step 6: Change file_stability_threshold setting to 3 seconds
        await self._update_stability_threshold(3)
        
        print(f"✅ Updated stability threshold to 3 seconds")
        
        # Step 7: Trigger file monitor check again - should now process the stable file
        await self._trigger_file_monitor_check(upload_id)
        
        # Poll for a few seconds for the upload to complete
        uploaded = False
        for attempt in range(10):  # Poll for up to 10 seconds
            await asyncio.sleep(1)
            
            current_s3_objects = await self._list_s3_objects(s3_client, upload_id)
            if len(current_s3_objects) == 2:
                # Verify the new file is there
                s3_keys = [obj['Key'] for obj in current_s3_objects]
                expected_new_key = f"{upload_id}/new_file.txt"
                if expected_new_key in s3_keys:
                    uploaded = True
                    print(f"✅ New file uploaded after stability threshold: {expected_new_key}")
                    break
        
        assert uploaded, "New file should be uploaded after stability threshold change"
        
        print(f"🎉 File monitor stability threshold test completed successfully!")
    
    async def _create_upload_job(self, job_data: Dict[str, Any]) -> str:
        """Create upload job and return upload_id"""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(f"{TEST_BASE_URL}/api/v1/uploads/", json=job_data)
            
            if response.status_code != 200:
                raise Exception(f"Failed to create upload job: {response.status_code} - {response.text}")
            
            result = response.json()
            return result["upload_id"]
    
    async def _poll_upload_status(self, upload_id: str, timeout: int = 60) -> Dict[str, Any]:
        """Poll upload status until completion or timeout"""
        start_time = time.time()
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            while time.time() - start_time < timeout:
                response = await client.get(f"{TEST_BASE_URL}/api/v1/uploads/{upload_id}")
                
                if response.status_code != 200:
                    raise Exception(f"Failed to get upload status: {response.status_code} - {response.text}")
                
                status = response.json()
                
                if status["state"] in ["COMPLETED", "FAILED"]:
                    return status
                
                await asyncio.sleep(1)
        
        raise Exception(f"Upload job {upload_id} did not complete within {timeout} seconds")
    
    async def _list_s3_objects(self, s3_client, upload_id: str) -> list:
        """List S3 objects for the upload"""
        try:
            response = s3_client.list_objects_v2(Bucket=TEST_BUCKET, Prefix=upload_id)
            return response.get('Contents', [])
        except ClientError:
            return []
    
    async def _update_stability_threshold(self, threshold_seconds: int):
        """Update the file stability threshold setting via API"""
        async with httpx.AsyncClient(timeout=30.0) as client:
            settings_update = {
                "file_stability_threshold": threshold_seconds
            }
            
            response = await client.post(f"{TEST_BASE_URL}/api/v1/test/update-settings", json=settings_update)
            
            if response.status_code != 200:
                raise Exception(f"Failed to update settings: {response.status_code} - {response.text}")
            
            result = response.json()
            print(f"Updated file_stability_threshold to {threshold_seconds} seconds: {result['message']}")
    
    async def _trigger_file_monitor_check(self, upload_id: str):
        """Manually trigger file monitor check for a specific upload job via API"""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(f"{TEST_BASE_URL}/api/v1/test/trigger-file-monitor/{upload_id}")
            
            if response.status_code != 200:
                raise Exception(f"Failed to trigger file monitor: {response.status_code} - {response.text}")
            
            result = response.json()
            print(f"File monitor check result for {upload_id}: {result['result']}")
            return result["result"] 
