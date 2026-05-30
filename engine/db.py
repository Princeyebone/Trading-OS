"""
engine/db.py — Engine-side database session helpers.
Uses synchronous SQLModel session (engine runs in a single process).
"""
from sqlmodel import SQLModel, create_engine, Session
from app.settings import settings

DATABASE_URL = settings.database_url

engine = create_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)


def get_session() -> Session:
    """Return a new SQLModel session. Caller must close it."""
    return Session(engine)


def is_db_alive() -> bool:
    """Pre-flight check — True if PostgreSQL is reachable."""
    try:
        with Session(engine) as s:
            from sqlmodel import text
            s.exec(text("SELECT 1"))
        return True
    except Exception as e:
        return False
