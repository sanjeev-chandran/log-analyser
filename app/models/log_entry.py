"""LogEntry SQLAlchemy model."""

from sqlalchemy import Column, String, DateTime, Boolean, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from uuid import uuid4

from app.database import Base


class LogEntry(Base):
    """Model for storing log metadata."""
    
    __tablename__ = "log_entries"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    log_hash = Column(String(64), unique=True, nullable=False, index=True)
    source = Column(String(100), nullable=False)
    level = Column(String(20), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    message_preview = Column(String(500), nullable=True)
    has_analysis = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    # Relationship to analysis_results
    analysis = relationship("AnalysisResult", back_populates="log_entry", uselist=False)
    
    __table_args__ = (
        Index('idx_log_entries_created_at', 'created_at'),
    )
    
    def __repr__(self):
        return f"<LogEntry(id={self.id}, source={self.source}, level={self.level})>"
