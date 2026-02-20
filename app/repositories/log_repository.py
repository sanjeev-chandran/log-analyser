"""Repository for log_entries table operations."""

from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.logger import get_logger
from app.database import Database
from app.models.log_entry import LogEntry
from app.services.log_parser import ParsedLog

logger = get_logger(__name__)


class LogRepository:
    """Data-access layer for log entries."""

    async def find_by_hash(self, log_hash: str) -> Optional[LogEntry]:
        """Return the log entry matching *log_hash*, or ``None``.

        Eagerly loads the ``analysis`` relationship so the caller can
        access ``entry.analysis`` after the session closes (avoids
        lazy-load detached-instance errors).
        """
        async with Database.session() as session:
            result = await session.execute(
                select(LogEntry)
                .where(LogEntry.log_hash == log_hash)
                .options(selectinload(LogEntry.analysis))
            )
            return result.scalar_one_or_none()

    async def find_by_id(self, log_id: UUID) -> Optional[LogEntry]:
        """Return the log entry with *log_id*, or ``None``."""
        async with Database.session() as session:
            result = await session.execute(
                select(LogEntry).where(LogEntry.id == log_id)
            )
            return result.scalar_one_or_none()

    async def create(self, parsed_log: ParsedLog) -> LogEntry:
        """Insert a log entry (uses current session if one exists)."""
        async with Database.session() as session:
            log_entry = LogEntry(
                log_hash=parsed_log.log_hash,
                source=parsed_log.service,
                level=parsed_log.level,
                timestamp=parsed_log.timestamp,
                message_preview=parsed_log.message_preview,
                has_analysis=True,
            )
            session.add(log_entry)
            await session.flush()
            logger.debug(
                "Log entry inserted",
                extra={"log_id": str(log_entry.id), "log_hash": parsed_log.log_hash},
            )
            return log_entry
