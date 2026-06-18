"""
Trade-related SQLModel table definitions.
Tables: trades, trade_outcomes, trade_journal
"""
from datetime import datetime, timezone
from typing import Optional, List
from sqlmodel import Field, SQLModel, Column, Text
from sqlalchemy import ARRAY, String


# ─── trades ────────────────────────────────────────────────────────────────────
class Trade(SQLModel, table=True):
    __tablename__ = "trades"

    id: Optional[int] = Field(default=None, primary_key=True)
    signal_id: Optional[int] = Field(default=None, foreign_key="signals.id")
    opened_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    closed_at: Optional[datetime] = None
    direction: str = Field(max_length=5)           # "LONG" or "SHORT"
    planned_entry: float
    actual_entry: Optional[float] = None           # actual fill from broker
    slippage_pips: Optional[float] = None
    stop_loss: float
    take_profit_1: float
    take_profit_2: Optional[float] = None
    lot_size: float
    planned_rr: Optional[float] = None
    tp1_hit: bool = Field(default=False)
    break_even_moved: bool = Field(default=False)
    highest_profit_pips: float = Field(default=0.0)
    locked_profit_pips: float = Field(default=0.0)
    status: str = Field(default="OPEN", max_length=20)  # OPEN, WIN, LOSS, BE, CANCELLED
    broker_order_id: Optional[str] = Field(default=None, max_length=100)
    broker: str = Field(default="MT5", max_length=20)


# ─── trade_outcomes ────────────────────────────────────────────────────────────
class TradeOutcome(SQLModel, table=True):
    __tablename__ = "trade_outcomes"

    id: Optional[int] = Field(default=None, primary_key=True)
    trade_id: int = Field(foreign_key="trades.id", unique=True)
    exit_price: float
    exit_reason: Optional[str] = Field(default=None, max_length=30)  # SL_HIT, TP1_HIT, TP2_HIT, MANUAL_CLOSE
    pnl_pips: Optional[float] = None
    pnl_dollars: Optional[float] = None
    r_achieved: Optional[float] = None            # e.g. 2.3 = won 2.3R
    duration_mins: Optional[int] = None
    max_adverse_excursion: Optional[float] = None  # MAE — max drawdown during trade
    max_favorable_excursion: Optional[float] = None  # MFE — max profit reached
    closed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ─── trade_journal ─────────────────────────────────────────────────────────────
class TradeJournal(SQLModel, table=True):
    __tablename__ = "trade_journal"

    id: Optional[int] = Field(default=None, primary_key=True)
    trade_id: int = Field(foreign_key="trades.id", unique=True)
    pre_trade_analysis: Optional[str] = Field(default=None, sa_column=Column(Text))
    post_trade_analysis: Optional[str] = Field(default=None, sa_column=Column(Text))
    what_went_right: Optional[str] = Field(default=None, sa_column=Column(Text))
    what_went_wrong: Optional[str] = Field(default=None, sa_column=Column(Text))
    improvement_hint: Optional[str] = Field(default=None, sa_column=Column(Text))
    pattern_quality: Optional[int] = None         # AI-rated 1–10
    execution_quality: Optional[int] = None       # AI-rated 1–10
    market_conditions: Optional[str] = Field(default=None, sa_column=Column(Text))
    manual_notes: Optional[str] = Field(default=None, sa_column=Column(Text))
    tags: Optional[str] = Field(default=None, max_length=500)  # comma-separated tags
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

# ─── straddle_pairs ────────────────────────────────────────────────────────────
class StraddlePair(SQLModel, table=True):
    __tablename__ = "straddle_pairs"

    id: Optional[int] = Field(default=None, primary_key=True)
    signal_id: Optional[int] = Field(default=None, foreign_key="signals.id")
    buy_order_id: str = Field(max_length=100)
    sell_order_id: str = Field(max_length=100)
    buy_entry: float
    sell_entry: float
    status: str = Field(default="ACTIVE", max_length=20) # ACTIVE, EXPIRED, FILLED, ERROR
    cancellation_confirmed: bool = Field(default=False)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
