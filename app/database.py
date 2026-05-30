"""
Database configuration for Trading OS v2.
Uses SQLModel (SQLAlchemy + Pydantic unified).
Connects to PostgreSQL via DATABASE_URL from .env
"""
from sqlmodel import SQLModel, create_engine, Session
from app.settings import settings

DATABASE_URL = settings.database_url

# SQLModel engine (sync — used by FastAPI + Engine)
engine = create_engine(
    DATABASE_URL,
    echo=False,  # set True for SQL debug logging
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)


def get_session():
    """FastAPI dependency — yields a DB session per request."""
    with Session(engine) as session:
        yield session




def check_db_connection() -> bool:
    """Engine pre-flight check — returns True if DB is reachable."""
    try:
        with Session(engine) as session:
            session.exec(__import__("sqlmodel").select(1))  # type: ignore
        return True
    except Exception:
        return False
