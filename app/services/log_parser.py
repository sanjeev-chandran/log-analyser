"""Log parsing service for extracting and validating log data."""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional, Union
from dateutil import parser as date_parser

from app.core.logger import get_logger
from app.core.exceptions import LogParseError

logger = get_logger(__name__)


@dataclass
class ParsedLog:
    """Parsed log data structure."""
    
    timestamp: datetime
    level: str
    service: str
    message: str
    trace_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    log_hash: Optional[str] = None
    message_preview: Optional[str] = None


class LogParser:
    """Parser for log entries."""
    
    # Maximum length for message preview
    PREVIEW_LENGTH = 500
    
    # Valid log levels
    VALID_LEVELS = {"ERROR", "WARN", "INFO", "DEBUG"}
    
    def parse(self, log_data: Dict[str, Any]) -> ParsedLog:
        """
        Parse and validate log data.
        
        Args:
            log_data: Dictionary containing log fields
            
        Returns:
            ParsedLog object with validated and extracted data
            
        Raises:
            LogParseError: If log data is invalid
        """
        # Validate required fields
        required_fields = ["timestamp", "level", "service", "message"]
        missing_fields = [f for f in required_fields if f not in log_data]
        
        if missing_fields:
            logger.warning(
                "Log parse failed: missing fields",
                extra={"missing_fields": missing_fields},
            )
            raise LogParseError(
                f"Missing required fields: {', '.join(missing_fields)}",
                {"missing_fields": missing_fields}
            )
        
        # Extract and validate fields
        timestamp = self.normalize_timestamp(log_data["timestamp"])
        level = self._validate_level(log_data["level"])
        service = self._validate_service(log_data["service"])
        message = self._validate_message(log_data["message"])
        trace_id = log_data.get("trace_id")
        metadata = log_data.get("metadata", {})
        
        # Generate hash for deduplication
        log_hash = self.generate_hash(log_data)
        
        # Create message preview
        message_preview = self._create_preview(message)
        
        return ParsedLog(
            timestamp=timestamp,
            level=level,
            service=service,
            message=message,
            trace_id=trace_id,
            metadata=metadata,
            log_hash=log_hash,
            message_preview=message_preview
        )
    
    def generate_hash(self, log_data: Dict[str, Any]) -> str:
        """
        Generate SHA256 hash of log data for deduplication.
        
        Note: Timestamp is intentionally excluded to allow deduplication
        of identical errors occurring at different times.
        
        Args:
            log_data: Dictionary containing log fields
            
        Returns:
            Hex string of SHA256 hash
        """
        # Create a canonical representation for hashing
        # Exclude timestamp to deduplicate identical errors at different times
        canonical_data = {
            "level": str(log_data.get("level", "")).upper(),
            "service": str(log_data.get("service", "")),
            "message": str(log_data.get("message", "")),
        }
        
        # Serialize to JSON string with sorted keys for consistency
        canonical_json = json.dumps(canonical_data, sort_keys=True, separators=(',', ':'))
        
        # Generate SHA256 hash
        return hashlib.sha256(canonical_json.encode('utf-8')).hexdigest()
    
    def normalize_timestamp(self, timestamp: Union[str, datetime]) -> datetime:
        """
        Normalize timestamp to datetime object.
        
        Args:
            timestamp: Timestamp as string or datetime object
            
        Returns:
            Normalized datetime object
            
        Raises:
            LogParseError: If timestamp cannot be parsed
        """
        if isinstance(timestamp, datetime):
            return timestamp
        
        if isinstance(timestamp, str):
            try:
                # Use dateutil parser for flexible parsing
                parsed = date_parser.parse(timestamp)
                # Ensure timezone aware if not already
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=None)
                return parsed
            except Exception as e:
                logger.warning(
                    "Invalid timestamp format: %s",
                    timestamp,
                    extra={"error": str(e)},
                )
                raise LogParseError(
                    f"Invalid timestamp format: {timestamp}",
                    {"original_value": timestamp, "error": str(e)}
                )
        
        raise LogParseError(
            f"Timestamp must be string or datetime, got {type(timestamp).__name__}",
            {"original_value": str(timestamp)}
        )
    
    def _validate_level(self, level: Any) -> str:
        """Validate and normalize log level."""
        if not isinstance(level, str):
            raise LogParseError(
                f"Level must be a string, got {type(level).__name__}",
                {"level": level}
            )
        
        upper_level = level.upper()
        if upper_level not in self.VALID_LEVELS:
            raise LogParseError(
                f"Invalid level: {level}. Must be one of {self.VALID_LEVELS}",
                {"level": level, "valid_levels": list(self.VALID_LEVELS)}
            )
        
        return upper_level
    
    def _validate_service(self, service: Any) -> str:
        """Validate service name."""
        if not isinstance(service, str):
            raise LogParseError(
                f"Service must be a string, got {type(service).__name__}",
                {"service": service}
            )
        
        stripped = service.strip()
        if not stripped:
            raise LogParseError(
                "Service name cannot be empty",
                {"service": service}
            )
        
        if len(stripped) > 100:
            raise LogParseError(
                f"Service name too long (max 100 chars, got {len(stripped)})",
                {"service": stripped[:50] + "..."}
            )
        
        return stripped
    
    def _validate_message(self, message: Any) -> str:
        """Validate log message."""
        if not isinstance(message, str):
            raise LogParseError(
                f"Message must be a string, got {type(message).__name__}",
                {"message": message}
            )
        
        stripped = message.strip()
        if not stripped:
            raise LogParseError(
                "Message cannot be empty",
                {"message": message}
            )
        
        return stripped
    
    def _create_preview(self, message: str) -> str:
        """Create a preview of the message (first N characters)."""
        if len(message) <= self.PREVIEW_LENGTH:
            return message
        return message[:self.PREVIEW_LENGTH] + "..."
