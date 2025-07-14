import os
from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import ConfigDict

class Settings(BaseSettings):
    model_config = ConfigDict(
        env_file=".env",
        env_file_encoding="utf-8"
    )
    
    # Database
    database_url: str = "sqlite:///./data/uploads.db"
    
    # AWS S3 Configuration
    aws_access_key_id: str = "test"
    aws_secret_access_key: str = "test"
    aws_region: str = "us-east-1"
    aws_endpoint_url: Optional[str] = "http://localhost:4566"  # LocalStack
    
    # Upload Configuration
    chunk_size: int = 5 * 1024 * 1024  # 5MB chunks
    worker_concurrency: int = 5
    chunks_concurrency: int = 10
    
    # Monitoring
    file_monitor_interval: int = 60  # seconds
    file_stability_threshold: int = 30  # seconds
    
    # Logging
    log_level: str = "INFO"

settings = Settings() 
