from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.declarative import declarative_base
from .config import settings
from src.models import Base

# SQLite database configuration
engine = create_engine(
    settings.database_url,
    connect_args={
        "check_same_thread": False,
        "timeout": 30.0,  # 30 second timeout
    },
    pool_size=20,  # Increase pool size
    max_overflow=30,  # Allow more overflow connections
    pool_timeout=30,  # Pool timeout
    pool_recycle=3600,  # Recycle connections after 1 hour
    pool_pre_ping=True,  # Validate connections
    echo=False  # Set to True for debugging
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def create_tables():
    """Create database tables"""
    Base.metadata.create_all(bind=engine)

def get_db() -> Session:
    """Get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_db_session() -> Session:
    """Get database session for non-FastAPI contexts"""
    return SessionLocal()

def cleanup_database():
    """Clean up database connections"""
    engine.dispose() 
