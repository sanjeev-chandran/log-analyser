"""Custom exceptions for the log analysis service."""


class LogAnalysisError(Exception):
    """Base exception for log analysis errors."""
    
    def __init__(self, message: str = None, details: dict = None):
        self.message = message
        self.details = details or {}
        super().__init__(self.message)


class LogParseError(LogAnalysisError):
    """Raised when log parsing fails due to invalid format."""
    
    def __init__(self, message: str = "Invalid log format", details: dict = None):
        super().__init__(message, details)


class AnalysisError(LogAnalysisError):
    """Raised when AI analysis fails."""
    
    def __init__(self, message: str = "Analysis failed", details: dict = None):
        super().__init__(message, details)


class LogNotFoundError(LogAnalysisError):
    """Raised when a log entry is not found."""
    
    def __init__(self, log_id: str = None):
        message = f"Log entry not found" + (f": {log_id}" if log_id else "")
        super().__init__(message, {"log_id": log_id})


class AnalysisNotFoundError(LogAnalysisError):
    """Raised when an analysis result is not found."""
    
    def __init__(self, analysis_id: str = None):
        message = f"Analysis result not found" + (f": {analysis_id}" if analysis_id else "")
        super().__init__(message, {"analysis_id": analysis_id})


class DuplicateLogError(LogAnalysisError):
    """Raised when a log entry with the same hash already exists."""
    
    def __init__(self, log_hash: str = None):
        message = "Duplicate log entry detected" + (f": {log_hash}" if log_hash else "")
        super().__init__(message, {"log_hash": log_hash})
