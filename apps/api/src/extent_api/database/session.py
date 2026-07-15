"""Synchronous Postgres engine construction for explicit API dependencies."""

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def create_database_engine(database_url: str) -> Engine:
    """Create a bounded, pre-pinged engine without opening a connection."""

    return create_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        pool_timeout=10,
        pool_recycle=1_800,
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Build the transaction boundary used by repositories and routes."""

    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
