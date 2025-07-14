import boto3
import asyncio
from botocore.config import Config
from botocore.exceptions import ClientError
from .config import settings
from .logging import get_logger

logger = get_logger(__name__)

def get_s3_client():
    """Get configured S3 client"""
    config = Config(
        retries={'max_attempts': 3},
        max_pool_connections=50
    )
    
    return boto3.client(
        's3',
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        region_name=settings.aws_region,
        endpoint_url=settings.aws_endpoint_url,
        config=config
    )

def get_s3_resource():
    """Get configured S3 resource"""
    return boto3.resource(
        's3',
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        region_name=settings.aws_region,
        endpoint_url=settings.aws_endpoint_url
    )

async def ensure_bucket_exists(bucket_name: str) -> bool:
    """
    Check if bucket exists and create it if it doesn't.
    
    Args:
        bucket_name: Name of the S3 bucket
        
    Returns:
        True if bucket exists or was successfully created, False otherwise
    """
    s3_client = get_s3_client()
    loop = asyncio.get_event_loop()
    
    try:
        # Check if bucket exists
        await loop.run_in_executor(
            None,
            lambda: s3_client.head_bucket(Bucket=bucket_name)
        )
        logger.info(f"Bucket exists: {bucket_name}")
        return True
        
    except ClientError as e:
        error_code = e.response['Error']['Code']
        
        if error_code == '404':
            # Bucket doesn't exist, try to create it
            logger.info(f"Bucket does not exist, creating: {bucket_name}")
            
            try:
                # For LocalStack and regions other than us-east-1, we need to specify location constraint
                if settings.aws_region != 'us-east-1':
                    await loop.run_in_executor(
                        None,
                        lambda: s3_client.create_bucket(
                            Bucket=bucket_name,
                            CreateBucketConfiguration={'LocationConstraint': settings.aws_region}
                        )
                    )
                else:
                    await loop.run_in_executor(
                        None,
                        lambda: s3_client.create_bucket(Bucket=bucket_name)
                    )
                
                logger.info(f"Successfully created bucket: {bucket_name}")
                return True
                
            except ClientError as create_error:
                logger.error(f"Failed to create bucket {bucket_name}: {create_error}")
                return False
                
        elif error_code == '403':
            # Access denied - bucket might exist but we don't have permission
            logger.error(f"Access denied for bucket {bucket_name}. Check permissions.")
            return False
            
        else:
            # Other error
            logger.error(f"Error checking bucket {bucket_name}: {e}")
            return False
            
    except Exception as e:
        logger.error(f"Unexpected error checking/creating bucket {bucket_name}: {e}")
        return False 
