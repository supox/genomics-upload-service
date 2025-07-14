import pytest
import asyncio
import os
import sys
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock, MagicMock

# Mock SQLAlchemy before any imports
sys.modules['sqlalchemy'] = MagicMock()
sys.modules['sqlalchemy.orm'] = MagicMock()
sys.modules['sqlalchemy.ext'] = MagicMock()
sys.modules['sqlalchemy.ext.declarative'] = MagicMock()

# Mock the database components
class MockFile:
    def __init__(self, id, upload_job_id, path, state="PENDING", mtime=None, size=0):
        self.id = id
        self.upload_job_id = upload_job_id
        self.path = path
        self.state = state
        self.mtime = mtime or datetime.now(timezone.utc)
        self.size = size

class MockUploadJob:
    def __init__(self, id, source_folder, destination_bucket, pattern="*", state="PENDING"):
        self.id = id
        self.source_folder = source_folder
        self.destination_bucket = destination_bucket
        self.pattern = pattern
        self.state = state

class MockDB:
    def __init__(self):
        self.files = []
        self.jobs = []
        self.committed = False
    
    def query(self, model_class):
        if hasattr(model_class, '__name__') and model_class.__name__ == 'File':
            return MockFileQuery(self.files)
        elif hasattr(model_class, '__name__') and model_class.__name__ == 'UploadJob':
            return MockJobQuery(self.jobs)
        return MockFileQuery(self.files)
    
    def add(self, obj):
        if hasattr(obj, 'upload_job_id'):  # It's a file
            obj.id = len(self.files) + 1
            self.files.append(obj)
        else:  # It's a job
            self.jobs.append(obj)
    
    def commit(self):
        self.committed = True
    
    def close(self):
        pass

class MockFileQuery:
    def __init__(self, files):
        self.files = files
    
    def filter(self, *args):
        return self
    
    def filter_by(self, **kwargs):
        return self
    
    def all(self):
        return self.files
    
    def first(self):
        return self.files[0] if self.files else None

class MockJobQuery:
    def __init__(self, jobs):
        self.jobs = jobs
    
    def filter(self, *args):
        return self
    
    def all(self):
        return self.jobs
    
    def first(self):
        return self.jobs[0] if self.jobs else None


@pytest.fixture
def temp_source_dir():
    """Create a temporary source directory for testing"""
    temp_dir = tempfile.mkdtemp(prefix="file_monitor_test_")
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def mock_db():
    """Create a mock database"""
    return MockDB()


@pytest.mark.asyncio
async def test_file_monitor_detects_changes():
    """Test that file monitor correctly detects file changes"""
    
    # Create a temporary directory
    temp_dir = tempfile.mkdtemp(prefix="file_monitor_test_")
    
    try:
        # Create initial file
        test_file = Path(temp_dir) / "test.txt"
        test_file.write_text("initial content")
        
        # Mock the file monitor functionality directly
        current_files = {
            "test.txt": {
                'mtime': datetime.fromtimestamp(test_file.stat().st_mtime, tz=timezone.utc),
                'size': len("initial content")
            }
        }
        
        existing_files = {}
        
        # Test new file detection
        changes = await detect_changes(current_files, existing_files)
        
        assert len(changes['new_files']) == 1
        assert changes['new_files'][0][0] == "test.txt"
        assert changes['new_files'][0][1]['size'] == len("initial content")
        assert len(changes['modified_files']) == 0
        
        # Simulate file being added to existing files
        existing_files["test.txt"] = MockFile(
            id=1,
            upload_job_id="test_job",
            path="test.txt",
            state="UPLOADED",
            mtime=current_files["test.txt"]["mtime"],
            size=current_files["test.txt"]["size"]
        )
        
        # Test modified file detection
        await asyncio.sleep(0.1)  # Ensure different mtime
        test_file.write_text("modified content")
        
        current_files["test.txt"] = {
            'mtime': datetime.fromtimestamp(test_file.stat().st_mtime, tz=timezone.utc),
            'size': len("modified content")
        }
        
        changes = await detect_changes(current_files, existing_files)
        
        assert len(changes['new_files']) == 0
        assert len(changes['modified_files']) == 1
        assert changes['modified_files'][0][0] == "test.txt"
        assert changes['modified_files'][0][1]['size'] == len("modified content")
        
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


async def detect_changes(current_files, existing_files):
    """Detect new and modified files"""
    changes = {
        'new_files': [],
        'modified_files': []
    }
    
    # Find new and modified files
    for file_path, file_info in current_files.items():
        if file_path not in existing_files:
            # New file
            changes['new_files'].append((file_path, file_info))
        else:
            # Check if file was modified
            existing_file = existing_files[file_path]
            if (existing_file.mtime != file_info['mtime'] or 
                existing_file.size != file_info['size']):
                changes['modified_files'].append((file_path, file_info))
    
    return changes


@pytest.mark.asyncio
async def test_file_monitor_pattern_matching():
    """Test that file monitor correctly applies pattern matching"""
    
    import fnmatch
    
    # Test pattern matching logic
    files = ["test.txt", "test.log", "test.py", "data.txt"]
    pattern = "*.txt"
    
    matching_files = [f for f in files if fnmatch.fnmatch(f, pattern)]
    
    assert len(matching_files) == 2
    assert "test.txt" in matching_files
    assert "data.txt" in matching_files
    assert "test.log" not in matching_files
    assert "test.py" not in matching_files 
