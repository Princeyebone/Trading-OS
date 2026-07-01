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
    except Exception:
        return False


def log_trade_to_db(
    system: str,
    direction: str,
    symbol: str,
    actual_entry: float,
    stop_loss: float,
    take_profit: float,
    lot_size: float,
    broker_order_id: str,
    timeframe: str = "M15",
    broker: str = "MT5",
) -> int:
    """Log a broker-executed trade to the engine database."""
    from app.models.trades import Trade

    trade = Trade(
        direction=direction.upper() if isinstance(direction, str) else direction,
        planned_entry=actual_entry,
        actual_entry=actual_entry,
        stop_loss=stop_loss,
        take_profit_1=take_profit,
        take_profit_2=None,
        lot_size=lot_size,
        broker_order_id=broker_order_id,
        broker=broker,
        status="OPEN",
    )
    with Session(engine) as session:
        session.add(trade)
        session.commit()
        session.refresh(trade)
    return trade.id
