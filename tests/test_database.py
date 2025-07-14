"""Test database configuration for isolated test environments"""

import os
import tempfile
import uuid
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from src.models import Base

class DatabaseTestManager:
    """Manages test database lifecycle"""
    
    def __init__(self):
        self.engine = None
        self.session_factory = None
        self.temp_db_path = None
    
    def create_test_database(self) -> str:
        """Create a temporary test database"""
        # Create temporary database file
        temp_dir = Path(tempfile.gettempdir()) / "ultima_upload_tests"
        temp_dir.mkdir(exist_ok=True)
        
        # Use unique filename for each test run
        db_name = f"test_uploads_{uuid.uuid4().hex[:8]}.db"
        self.temp_db_path = temp_dir / db_name
        
        # Create database URL
        database_url = f"sqlite:///{self.temp_db_path}"
        
        # Create engine
        self.engine = create_engine(
            database_url,
            connect_args={"check_same_thread": False}
        )
        
        # Create session factory
        self.session_factory = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        
        # Create all tables
        Base.metadata.create_all(bind=self.engine)
        
        return database_url
    
    def get_session(self) -> Session:
        """Get a database session"""
        if not self.session_factory:
            raise RuntimeError("Test database not initialized. Call create_test_database() first.")
        return self.session_factory()
    
    def cleanup_database(self):
        """Clean up the test database"""
        if self.engine:
            self.engine.dispose()
            self.engine = None
        
        if self.temp_db_path and self.temp_db_path.exists():
            try:
                self.temp_db_path.unlink()
            except OSError:
                pass  # File may already be deleted
            self.temp_db_path = None
        
        self.session_factory = None
    
    def reset_database(self):
        """Reset database by dropping and recreating all tables"""
        if not self.engine:
            raise RuntimeError("Test database not initialized")
        
        # Drop all tables
        Base.metadata.drop_all(bind=self.engine)
        
        # Recreate all tables
        Base.metadata.create_all(bind=self.engine)


def create_in_memory_database() -> tuple[str, DatabaseTestManager]:
    """Create an in-memory test database (fastest for tests)"""
    manager = DatabaseTestManager()
    
    # Use in-memory SQLite database
    database_url = "sqlite:///:memory:"
    
    # Create engine
    manager.engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False}
    )
    
    # Create session factory
    manager.session_factory = sessionmaker(autocommit=False, autoflush=False, bind=manager.engine)
    
    # Create all tables
    Base.metadata.create_all(bind=manager.engine)
    
    return database_url, manager


def create_file_based_test_database() -> tuple[str, DatabaseTestManager]:
    """Create a file-based test database (useful for debugging)"""
    manager = DatabaseTestManager()
    database_url = manager.create_test_database()
    return database_url, manager


# Global test database manager for pytest fixtures
_test_db_manager = None

def get_test_db_manager() -> DatabaseTestManager:
    """Get the global test database manager"""
    global _test_db_manager
    if _test_db_manager is None:
        raise RuntimeError("Test database manager not initialized")
    return _test_db_manager

def set_test_db_manager(manager: DatabaseTestManager):
    """Set the global test database manager"""
    global _test_db_manager
    _test_db_manager = manager

def cleanup_test_db_manager():
    """Clean up the global test database manager"""
    global _test_db_manager
    if _test_db_manager:
        _test_db_manager.cleanup_database()
        _test_db_manager = None 
