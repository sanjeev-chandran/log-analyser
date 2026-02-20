"""Database configuration and session management.

Uses a ``ContextVar`` to implement Hibernate-style session reuse:
- If no session exists in the current context -> create a new one (owner).
- If a session already exists -> yield it (join the existing transaction).
- Only the owner commits/closes the session.
"""

import logging
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import NullPool

from app.config import DATABASE_URL, DEBUG

# Use stdlib logging directly — this module is imported before
# app.core.logger is available (logger.py imports app.config which
# is fine, but database.py is imported by models which are imported
# everywhere, so we keep it dependency-free).
logger = logging.getLogger(__name__)

# Base class for models
Base = declarative_base()

# Context variable — async-safe equivalent of Java's ThreadLocal
_current_session: ContextVar[AsyncSession | None] = ContextVar(
    "_current_session", default=None
)


class Database:
    """Static database accessor.

    ``Database.session()`` behaves like Hibernate's ``getCurrentSession()``:
    - First caller creates and owns the session.
    - Nested callers join the existing session (same transaction).
    """

    _engine = create_async_engine(
        DATABASE_URL,
        echo=DEBUG,
        poolclass=NullPool if DEBUG else None,
        future=True,
    )

    _session_factory = sessionmaker(
        _engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    @classmethod
    @asynccontextmanager
    async def session(cls) -> AsyncGenerator[AsyncSession, None]:
        """Provide a scoped async session.

        If a session already exists in the current context, yield it
        (joining the existing transaction).  Otherwise create a new one
        and register it in the context so nested calls can join.
        """
        existing = _current_session.get()

        if existing is not None:
            logger.debug("Joining existing database session")
            yield existing
        else:
            logger.debug("Creating new database session")
            async with cls._session_factory() as session:
                token = _current_session.set(session)
                try:
                    yield session
                finally:
                    _current_session.reset(token)
                    logger.debug("Database session closed")
