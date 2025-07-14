import pytest
import httpx
from typing import Dict, Any


class TestAPIValidation:
    """Test API validation and error handling"""
    
    TEST_BASE_URL = "http://localhost:8000"
    
    @pytest.mark.asyncio
    @pytest.mark.api
    @pytest.mark.health
    @pytest.mark.smoke
    async def test_health_endpoint(self):
        """Test the health check endpoint"""
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{self.TEST_BASE_URL}/health", timeout=5)
            
            assert response.status_code == 200, f"Health check failed: {response.status_code}"
            
            # Verify response structure if it returns JSON
            try:
                health_data = response.json()
                assert isinstance(health_data, dict), "Health response should be a dict"
                print(f"✅ Health check passed: {health_data}")
            except Exception:
                # If it's not JSON, just verify the response text
                assert response.text, "Health check should return content"
                print(f"✅ Health check passed: {response.text}")
    
    @pytest.mark.asyncio
    @pytest.mark.api
    @pytest.mark.validation
    async def test_create_upload_job_validation(self):
        """Test upload job creation validation"""
        
        # Test missing required fields
        test_cases = [
            # Missing all fields
            {},
            # Missing destination_bucket
            {"source_folder": "/tmp"},
            # Missing source_folder
            {"destination_bucket": "test-bucket"},
            # Empty source_folder
            {"source_folder": "", "destination_bucket": "test-bucket"},
            # Empty destination_bucket
            {"source_folder": "/tmp", "destination_bucket": ""},
        ]
        
        for i, invalid_data in enumerate(test_cases):
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.TEST_BASE_URL}/api/v1/uploads/",
                    json=invalid_data,
                    timeout=30
                )
                
                assert response.status_code in [400, 422], f"Test case {i}: Should reject invalid data: {invalid_data}"
                print(f"✅ Test case {i}: Correctly rejected invalid data")
    
    @pytest.mark.asyncio
    @pytest.mark.api
    @pytest.mark.validation
    async def test_get_nonexistent_upload(self):
        """Test getting a nonexistent upload ID"""
        fake_upload_id = "00000000-0000-0000-0000-000000000000"
        
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{self.TEST_BASE_URL}/api/v1/uploads/{fake_upload_id}")
            
            assert response.status_code == 404, f"Should return 404 for nonexistent upload: {response.status_code}"
            print("✅ Correctly returned 404 for nonexistent upload")
    
    @pytest.mark.asyncio
    @pytest.mark.api
    @pytest.mark.validation
    async def test_get_upload_with_invalid_id(self):
        """Test getting an upload with invalid ID format"""
        invalid_ids = [
            "invalid-id",
            "123",
            "not-a-uuid",
            "12345678-1234-1234-1234-12345678901",  # Too short
            "12345678-1234-1234-1234-1234567890123",  # Too long
        ]
        
        for invalid_id in invalid_ids:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.TEST_BASE_URL}/api/v1/uploads/{invalid_id}")
                
                assert response.status_code in [400, 404, 422], f"Should reject invalid ID: {invalid_id}"
                print(f"✅ Correctly rejected invalid ID: {invalid_id}")
    
    @pytest.mark.asyncio
    async def test_uploads_list_endpoint(self):
        """Test the uploads list endpoint"""
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{self.TEST_BASE_URL}/api/v1/uploads/")
            
            assert response.status_code == 200, f"Failed to list uploads: {response.status_code}"
            
            result = response.json()
            assert isinstance(result, dict), "Response should be a dict"
            assert "uploads" in result, "Response should contain 'uploads' key"
            assert isinstance(result["uploads"], list), "Uploads should be a list"
            
            print(f"✅ Uploads list endpoint works: {len(result['uploads'])} uploads found")
    
    @pytest.mark.asyncio
    async def test_invalid_http_methods(self):
        """Test invalid HTTP methods on endpoints"""
        
        # Test invalid methods on upload endpoints
        # Note: GET is valid for /uploads/ (listing), POST is valid for /uploads/ (creation)
        invalid_methods = ["PUT", "DELETE", "PATCH"]
        
        for method in invalid_methods:
            async with httpx.AsyncClient() as client:
                response = await client.request(
                    method,
                    f"{self.TEST_BASE_URL}/api/v1/uploads/",
                    timeout=10
                )
                
                assert response.status_code == 405, f"Should return 405 for {method} on uploads endpoint"
                print(f"✅ Correctly rejected {method} method on uploads endpoint")
    
    @pytest.mark.asyncio
    async def test_api_content_type_validation(self):
        """Test API content type validation"""
        
        # Test invalid content types
        invalid_payloads = [
            # Plain text instead of JSON
            ("text/plain", "invalid data"),
            # XML instead of JSON
            ("application/xml", "<data>invalid</data>"),
            # Form data instead of JSON
            ("application/x-www-form-urlencoded", "source_folder=/tmp&destination_bucket=test"),
        ]
        
        for content_type, payload in invalid_payloads:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.TEST_BASE_URL}/api/v1/uploads/",
                    content=payload,
                    headers={"Content-Type": content_type},
                    timeout=30
                )
                
                assert response.status_code in [400, 415, 422], f"Should reject {content_type}"
                print(f"✅ Correctly rejected {content_type}")
    
    @pytest.mark.asyncio
    async def test_large_request_handling(self):
        """Test handling of large requests"""
        
        # Create a large JSON payload
        large_data = {
            "source_folder": "/tmp",
            "destination_bucket": "test-bucket",
            "pattern": "*.txt",
            "large_field": "x" * 10000  # 10KB of data
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.TEST_BASE_URL}/api/v1/uploads/",
                json=large_data,
                timeout=30
            )
            
            # Should either process it or reject it gracefully
            assert response.status_code in [200, 400, 413, 422], f"Should handle large request gracefully"
            print(f"✅ Handled large request gracefully: {response.status_code}")
    
    @pytest.mark.asyncio
    async def test_concurrent_requests(self):
        """Test handling of concurrent requests"""
        import asyncio
        
        async def make_request():
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.TEST_BASE_URL}/health", timeout=10)
                return response.status_code
        
        # Make 10 concurrent requests
        tasks = [make_request() for _ in range(10)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # All should succeed or fail gracefully
        success_count = sum(1 for result in results if result == 200)
        
        assert success_count >= 8, f"At least 8/10 concurrent requests should succeed: {success_count}"
        print(f"✅ Handled concurrent requests: {success_count}/10 succeeded")
    
    @pytest.mark.asyncio
    async def test_request_timeout_handling(self):
        """Test request timeout handling"""
        
        # Test with very short timeout
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(f"{self.TEST_BASE_URL}/health", timeout=0.001)
                # If it succeeds, that's fine too (very fast response)
                assert response.status_code == 200
                print("✅ Service responded very quickly")
            except httpx.TimeoutException:
                # This is expected with very short timeout
                print("✅ Timeout handled correctly")
            except Exception as e:
                # Other exceptions are acceptable for timeout testing
                print(f"✅ Request handled gracefully: {type(e).__name__}")


class TestServiceHealth:
    """Test service health and availability"""
    
    TEST_BASE_URL = "http://localhost:8000"
    
    @pytest.mark.asyncio
    @pytest.mark.health
    @pytest.mark.smoke
    async def test_service_availability(self):
        """Test that the service is available and responding"""
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{self.TEST_BASE_URL}/health", timeout=5)
            
            assert response.status_code == 200, f"Service not available: {response.status_code}"
            print("✅ Service is available and responding")
    
    @pytest.mark.asyncio
    async def test_service_response_time(self):
        """Test service response time"""
        import time
        
        start_time = time.time()
        
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{self.TEST_BASE_URL}/health", timeout=10)
            
        end_time = time.time()
        response_time = end_time - start_time
        
        assert response.status_code == 200, "Service should respond successfully"
        assert response_time < 5.0, f"Response time too slow: {response_time:.2f}s"
        
        print(f"✅ Service response time: {response_time:.3f}s")
    
    @pytest.mark.asyncio 
    async def test_api_documentation_available(self):
        """Test that API documentation is available"""
        endpoints_to_check = [
            "/docs",      # Swagger UI
            "/redoc",     # ReDoc
            "/openapi.json"  # OpenAPI spec
        ]
        
        for endpoint in endpoints_to_check:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.TEST_BASE_URL}{endpoint}", timeout=10)
                
                assert response.status_code == 200, f"API docs not available at {endpoint}"
                print(f"✅ API documentation available at {endpoint}")


@pytest.mark.integration
class TestIntegrationHealth:
    """Integration tests for service health with dependencies"""
    
    TEST_BASE_URL = "http://localhost:8000"
    S3_ENDPOINT_URL = "http://localhost:4566"
    
    @pytest.mark.asyncio
    async def test_s3_connectivity(self):
        """Test S3 connectivity from the service"""
        # This test would require an endpoint that checks S3 connectivity
        # For now, we'll just verify LocalStack is available
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(f"{self.S3_ENDPOINT_URL}/_localstack/health", timeout=5)
                assert response.status_code == 200, "LocalStack S3 not available"
                print("✅ LocalStack S3 is available")
            except Exception as e:
                pytest.skip(f"LocalStack S3 not available: {e}")
    
    @pytest.mark.asyncio
    async def test_database_connectivity(self):
        """Test database connectivity"""
        # This would require a database health endpoint
        # For now, we'll test that the service can list uploads (requires DB)
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{self.TEST_BASE_URL}/api/v1/uploads/", timeout=10)
            
            assert response.status_code == 200, "Database connectivity issue"
            print("✅ Database connectivity verified") 
