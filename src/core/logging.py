import logging
import json
from datetime import datetime, timezone
from enum import Enum
from .config import settings

class JSONFormatter(logging.Formatter):
    """JSON formatter for structured logging"""
    
    def _serialize_value(self, value):
        """Convert non-JSON serializable values to serializable format"""
        if isinstance(value, Enum):
            return value.value
        elif hasattr(value, '__dict__'):
            # For objects with attributes, convert to dict
            return str(value)
        else:
            return value
    
    def format(self, record):
        log_entry = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
        }
        
        # Add exception info if present
        if record.exc_info:
            log_entry['exception'] = self.formatException(record.exc_info)
        
        # Add extra fields
        for key, value in record.__dict__.items():
            if key not in ['name', 'msg', 'args', 'levelname', 'levelno', 'pathname', 'filename',
                          'module', 'exc_info', 'exc_text', 'stack_info', 'lineno', 'funcName',
                          'created', 'msecs', 'relativeCreated', 'thread', 'threadName',
                          'processName', 'process', 'message']:
                log_entry[key] = self._serialize_value(value)
        
        return json.dumps(log_entry)

def setup_logging():
    """Setup structured logging"""
    # Create root logger
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, settings.log_level.upper()))
    
    # Remove existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    # Create console handler with JSON formatter
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(JSONFormatter())
    logger.addHandler(console_handler)
    
    return logger

def get_logger(name: str) -> logging.Logger:
    """Get logger with the given name"""
    return logging.getLogger(name) 
