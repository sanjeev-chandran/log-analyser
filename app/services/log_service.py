"""Service layer for log entry business logic."""

from typing import Optional, Tuple
from uuid import UUID

from app.core.logger import get_logger
from app.models.log_entry import LogEntry
from app.core.exceptions import DuplicateLogError, LogNotFoundError
from app.repositories.log_repository import LogRepository
from app.services.log_parser import LogParser, ParsedLog

logger = get_logger(__name__)


class LogService:
    """Business logic for log entries. Owns parsing and persistence."""

    def __init__(self, log_parser: LogParser):
        self._parser = log_parser
        self._repo = LogRepository()

    def parse(self, log_data: dict) -> ParsedLog:
        """Parse and validate raw log data."""
        return self._parser.parse(log_data)

    async def parse_and_deduplicate(self, log_data: dict) -> Tuple[ParsedLog, Optional[LogEntry]]:
        """
        Parse log data and check for duplicates.

        Returns:
            (parsed_log, existing_entry) — existing_entry is None if new.

        Raises:
            LogParseError, DuplicateLogError (if exists without analysis)
        """
        parsed_log = self._parser.parse(log_data)
        logger.debug(
            "Log parsed successfully",
            extra={"log_hash": parsed_log.log_hash, "service": parsed_log.service},
        )

        existing = await self._repo.find_by_hash(parsed_log.log_hash)
        if existing is not None:
            if existing.has_analysis and existing.analysis:
                logger.info(
                    "Duplicate log with existing analysis",
                    extra={"log_hash": parsed_log.log_hash},
                )
                return parsed_log, existing
            logger.warning(
                "Duplicate log without completed analysis",
                extra={"log_hash": parsed_log.log_hash},
            )
            raise DuplicateLogError(parsed_log.log_hash)

        return parsed_log, None

    async def create(self, parsed_log: ParsedLog) -> LogEntry:
        """Insert a log entry (joins existing transaction if one is active)."""
        log_entry = await self._repo.create(parsed_log)
        logger.debug(
            "Log entry created",
            extra={"log_id": str(log_entry.id), "source": log_entry.source},
        )
        return log_entry

    async def find_by_hash(self, log_hash: str) -> Optional[LogEntry]:
        """Look up a log entry by content hash."""
        return await self._repo.find_by_hash(log_hash)

    async def find_by_id(self, log_id: UUID) -> LogEntry:
        """
        Get a log entry by primary key.

        Raises:
            LogNotFoundError: If no entry exists for the given ID.
        """
        entry = await self._repo.find_by_id(log_id)
        if entry is None:
            raise LogNotFoundError(str(log_id))
        return entry
