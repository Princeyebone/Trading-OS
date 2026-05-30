"""
engine/db.py — Engine-side database session helpers.
Uses synchronous SQLModel session (engine runs in a single process).
"""
import os
from sqlmodel import SQLModel, create_engine, Session
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://trading_user:password@localhost:5432/trading_os")

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
