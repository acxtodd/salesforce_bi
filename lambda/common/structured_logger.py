"""
Structured JSON logging utility for Lambda functions.
Provides consistent logging format with requestId, timing, and metadata.
"""
import json
import logging
import os
import time
from typing import Any, Dict, Optional
from datetime import datetime


class StructuredLogger:
    """Structured JSON logger for Lambda functions."""
    
    def __init__(self, name: str, request_id: Optional[str] = None):
        """Initialize structured logger.
        
        Args:
            name: Logger name (typically __name__)
            request_id: AWS request ID from Lambda context
        """
        self.logger = logging.getLogger(name)
        self.logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))
        self.request_id = request_id
        self.start_time = time.perf_counter()
        
        # Remove existing handlers to avoid duplicates
        self.logger.handlers = []
        
        # Add JSON formatter
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        self.logger.addHandler(handler)
    
    def _build_log_entry(
        self,
        level: str,
        message: str,
        **kwargs: Any
    ) -> Dict[str, Any]:
        """Build structured log entry.
        
        Args:
            level: Log level (INFO, WARNING, ERROR, etc.)
            message: Log message
            **kwargs: Additional metadata fields
        
        Returns:
            Structured log entry dictionary
        """
        entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": level,
            "message": message,
        }
        
        if self.request_id:
            entry["requestId"] = self.request_id
        
        # Add elapsed time since logger initialization
        elapsed_ms = round((time.perf_counter() - self.start_time) * 1000, 2)
        entry["elapsedMs"] = elapsed_ms
        
        # Add any additional metadata
        for key, value in kwargs.items():
            if value is not None:
                entry[key] = value
        
        return entry
    
    def info(self, message: str, **kwargs: Any) -> None:
        """Log INFO level message with structured data."""
        entry = self._build_log_entry("INFO", message, **kwargs)
        self.logger.info(json.dumps(entry))
    
    def warning(self, message: str, **kwargs: Any) -> None:
        """Log WARNING level message with structured data."""
        entry = self._build_log_entry("WARNING", message, **kwargs)
        self.logger.warning(json.dumps(entry))
    
    def error(self, message: str, **kwargs: Any) -> None:
        """Log ERROR level message with structured data."""
        entry = self._build_log_entry("ERROR", message, **kwargs)
        self.logger.error(json.dumps(entry))
    
    def debug(self, message: str, **kwargs: Any) -> None:
        """Log DEBUG level message with structured data."""
        entry = self._build_log_entry("DEBUG", message, **kwargs)
        self.logger.debug(json.dumps(entry))
    
    def exception(self, message: str, exc: Exception, **kwargs: Any) -> None:
        """Log exception with structured data and stack trace.
        
        Args:
            message: Error message
            exc: Exception object
            **kwargs: Additional metadata
        """
        import traceback
        
        entry = self._build_log_entry(
            "ERROR",
            message,
            error=str(exc),
            errorType=type(exc).__name__,
            stackTrace=traceback.format_exc(),
            **kwargs
        )
        self.logger.error(json.dumps(entry))


class JsonFormatter(logging.Formatter):
    """JSON formatter for standard Python logging."""
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON.
        
        Args:
            record: Log record
        
        Returns:
            JSON formatted log string
        """
        # If the message is already JSON, return it as-is
        try:
            json.loads(record.getMessage())
            return record.getMessage()
        except (json.JSONDecodeError, ValueError):
            pass
        
        # Otherwise, create a basic JSON structure
        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }
        
        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        
        return json.dumps(log_entry)


def create_logger(name: str, request_id: Optional[str] = None) -> StructuredLogger:
    """Create a structured logger instance.
    
    Args:
        name: Logger name (typically __name__)
        request_id: AWS request ID from Lambda context
    
    Returns:
        StructuredLogger instance
    """
    return StructuredLogger(name, request_id)
