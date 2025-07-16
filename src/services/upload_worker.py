import os
import asyncio
import aiofiles
from typing import List, Dict, Any
from botocore.exceptions import ClientError
from sqlalchemy.orm import Session

from src.core import get_s3_client, get_db_session, get_logger, settings
from src.models import File, UploadJob
from src.models.file import FileState

logger = get_logger(__name__)

# Global semaphore for limiting concurrent part uploads across all files
_upload_semaphore = asyncio.Semaphore(settings.chunks_concurrency)

class UploadWorker:
    def __init__(self):
        self.s3_client = get_s3_client()
        self.chunk_size = settings.chunk_size
    
    async def upload_file(self, file_id: int) -> bool:
        """Upload a single file using S3 multipart upload"""
        db = get_db_session()
        
        try:
            # Get file record
            file_record = db.query(File).filter(File.id == file_id).first()
            if not file_record:
                logger.error(f"File record not found: {file_id}")
                return False
            
            # Get upload job
            upload_job = db.query(UploadJob).filter(UploadJob.id == file_record.upload_job_id).first()
            if not upload_job:
                logger.error(f"Upload job not found: {file_record.upload_job_id}")
                return False
            
            file_record.state = FileState.IN_PROGRESS
            db.commit()
            
            # Construct full file path
            source_path = os.path.join(upload_job.source_folder, file_record.path)
            
            # Check if file exists
            if not os.path.exists(source_path):
                logger.error(f"Source file not found: {source_path}")
                file_record.state = FileState.FAILED
                file_record.failure_reason = f"Source file not found: {source_path}"
                db.commit()
                return False
            
            file_size = os.path.getsize(source_path)
            s3_key = os.path.join(str(upload_job.id), file_record.path)
            
            logger.info(f"Starting upload", extra={
                "file_id": file_id,
                "source_path": source_path,
                "s3_key": s3_key,
                "file_size": file_size
            })
            
            success = await self._upload_file_to_s3(
                source_path, 
                upload_job.destination_bucket, 
                s3_key, 
                file_size
            )
            
            if success:
                # Verify upload
                if await self._verify_upload(upload_job.destination_bucket, s3_key, file_size):
                    file_record.state = FileState.UPLOADED
                    logger.info(f"File uploaded successfully", extra={
                        "file_id": file_id,
                        "s3_key": s3_key
                    })
                else:
                    file_record.state = FileState.FAILED
                    file_record.failure_reason = f"Upload verification failed for S3 key: {s3_key}"
                    logger.error(f"Upload verification failed", extra={
                        "file_id": file_id,
                        "s3_key": s3_key
                    })
                    success = False
            else:
                file_record.state = FileState.FAILED
                file_record.failure_reason = f"File upload failed for S3 key: {s3_key}"
                logger.error(f"File upload failed", extra={
                    "file_id": file_id,
                    "s3_key": s3_key
                })
            
            db.commit()
            return success
            
        except Exception as e:
            logger.error(f"Error uploading file: {str(e)}", extra={"file_id": file_id})
            if 'file_record' in locals():
                file_record.state = FileState.FAILED
                file_record.failure_reason = f"Exception during upload: {str(e)}"
                db.commit()
            return False
        finally:
            db.close()
    
    async def _upload_file_to_s3(self, source_path: str, bucket: str, key: str, file_size: int) -> bool:
        """Upload file to S3 using multipart upload for large files"""
        try:
            # For small files, use simple upload
            if file_size <= self.chunk_size:
                return await self._simple_upload(source_path, bucket, key)
            else:
                return await self._multipart_upload(source_path, bucket, key, file_size)
        except Exception as e:
            logger.error(f"S3 upload error: {str(e)}", extra={
                "source_path": source_path,
                "bucket": bucket,
                "key": key
            })
            return False
    
    async def _simple_upload(self, source_path: str, bucket: str, key: str) -> bool:
        """Simple upload for small files"""
        async with aiofiles.open(source_path, 'rb') as f:
            data = await f.read()
        
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: self.s3_client.put_object(Bucket=bucket, Key=key, Body=data)
        )
        return True
    
    async def _upload_part(self, source_path: str, bucket: str, key: str, part_number: int, upload_id: str, offset: int, size: int) -> Dict[str, Any]:
        """Upload a single part with semaphore control"""
        async with _upload_semaphore:
            try:
                # Read chunk from file
                async with aiofiles.open(source_path, 'rb') as f:
                    await f.seek(offset)
                    chunk = await f.read(size)
                
                # Upload part
                loop = asyncio.get_event_loop()
                part_response = await loop.run_in_executor(
                    None,
                    lambda: self.s3_client.upload_part(
                        Bucket=bucket,
                        Key=key,
                        PartNumber=part_number,
                        UploadId=upload_id,
                        Body=chunk
                    )
                )
                
                logger.debug(f"Uploaded part {part_number}", extra={
                    "upload_id": upload_id,
                    "part_number": part_number,
                    "chunk_size": len(chunk)
                })
                
                return {
                    'ETag': part_response['ETag'],
                    'PartNumber': part_number
                }
            except Exception as e:
                logger.error(f"Failed to upload part {part_number}: {str(e)}", extra={
                    "upload_id": upload_id,
                    "part_number": part_number
                })
                raise
    
    async def _multipart_upload(self, source_path: str, bucket: str, key: str, file_size: int) -> bool:
        """Multipart upload for large files with parallel part uploads"""
        upload_id = None
        try:
            # Create multipart upload
            loop = asyncio.get_event_loop()
            
            response = await loop.run_in_executor(
                None,
                lambda: self.s3_client.create_multipart_upload(Bucket=bucket, Key=key)
            )
            upload_id = response['UploadId']
            
            logger.info(f"Started multipart upload", extra={
                "upload_id": upload_id,
                "bucket": bucket,
                "key": key
            })
            
            # Calculate part information
            part_info = []
            offset = 0
            part_number = 1
            
            while offset < file_size:
                size = min(self.chunk_size, file_size - offset)
                part_info.append((part_number, offset, size))
                offset += size
                part_number += 1
            
            # Create upload tasks for all parts
            upload_tasks = []
            for part_number, offset, size in part_info:
                task = self._upload_part(source_path, bucket, key, part_number, upload_id, offset, size)
                upload_tasks.append(task)
            
            logger.info(f"Uploading {len(upload_tasks)} parts in parallel", extra={
                "upload_id": upload_id,
                "total_parts": len(upload_tasks)
            })
            
            # Upload all parts in parallel
            parts = await asyncio.gather(*upload_tasks)
            
            # Complete multipart upload
            await loop.run_in_executor(
                None,
                lambda: self.s3_client.complete_multipart_upload(
                    Bucket=bucket,
                    Key=key,
                    UploadId=upload_id,
                    MultipartUpload={"Parts": parts}
                )
            )
            
            logger.info(f"Completed multipart upload", extra={
                "upload_id": upload_id,
                "total_parts": len(parts)
            })
            
            return True
            
        except Exception as e:
            logger.error(f"Multipart upload failed: {str(e)}")
            # Try to abort multipart upload
            if upload_id:
                try:
                    await loop.run_in_executor(
                        None,
                        lambda: self.s3_client.abort_multipart_upload(
                            Bucket=bucket, 
                            Key=key, 
                            UploadId=upload_id
                        )
                    )
                except Exception as abort_error:
                    logger.error(f"Failed to abort multipart upload: {str(abort_error)}")
            raise
    
    async def _verify_upload(self, bucket: str, key: str, expected_size: int) -> bool:
        """Verify that file was uploaded correctly"""
        try:
            loop = asyncio.get_event_loop()
            
            response = await loop.run_in_executor(
                None,
                lambda: self.s3_client.head_object(Bucket=bucket, Key=key)
            )
            
            actual_size = response['ContentLength']
            
            if actual_size == expected_size:
                logger.debug(f"Upload verification successful", extra={
                    "bucket": bucket,
                    "key": key,
                    "size": actual_size
                })
                return True
            else:
                logger.error(f"Size mismatch in upload verification", extra={
                    "bucket": bucket,
                    "key": key,
                    "expected_size": expected_size,
                    "actual_size": actual_size
                })
                return False
                
        except Exception as e:
            logger.error(f"Upload verification failed: {str(e)}", extra={
                "bucket": bucket,
                "key": key
            })
            return False

# Global upload worker instance
upload_worker = UploadWorker() 
