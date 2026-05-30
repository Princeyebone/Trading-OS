"""
Signal-related SQLModel table definitions.
Tables: signals, market_context, pattern_events, claude_responses
"""
from datetime import datetime, timezone
from typing import Optional
from sqlmodel import Field, SQLModel, Column, JSON, Text


# ─── signals ──────────────────────────────────────────────────────────────────
class Signal(SQLModel, table=True):
    __tablename__ = "signals"

    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    symbol: str = Field(default="XAUUSD", max_length=10)
    timeframe: str = Field(max_length=5)           # e.g. "M15"
    session: str = Field(max_length=20)            # "LONDON", "NY", "OVERLAP"
    verdict: str = Field(max_length=10)            # "TRADE" or "WAIT"
    direction: Optional[str] = Field(default=None, max_length=10)  # "LONG", "SHORT"
    confidence: Optional[int] = Field(default=None)  # 0–100
    skip_reason: Optional[str] = Field(default=None, max_length=200)
    prompt_version: int = Field(default=1)
    price_at_signal: Optional[float] = Field(default=None)


# ─── market_context ────────────────────────────────────────────────────────────
class MarketContext(SQLModel, table=True):
    __tablename__ = "market_context"

    id: Optional[int] = Field(default=None, primary_key=True)
    signal_id: int = Field(foreign_key="signals.id", unique=True)
    session: str = Field(max_length=20)
    atr: Optional[float] = None
    atr_percentile: Optional[float] = None
    rsi_m15: Optional[float] = None
    rsi_h1: Optional[float] = None
    macd_hist_h1: Optional[float] = None
    h4_ema20: Optional[float] = None
    h4_ema50: Optional[float] = None
    h4_ema200: Optional[float] = None
    h4_alignment: Optional[str] = Field(default=None, max_length=20)  # "BULLISH", "BEARISH", "MIXED"
    h1_ema20: Optional[float] = None
    stoch_m15: Optional[float] = None
    volume_ratio: Optional[float] = None


# ─── pattern_events ────────────────────────────────────────────────────────────
class PatternEvent(SQLModel, table=True):
    __tablename__ = "pattern_events"

    id: Optional[int] = Field(default=None, primary_key=True)
    signal_id: int = Field(foreign_key="signals.id")
    pattern_type: str = Field(max_length=50)       # "ORDER_BLOCK", "FVG", "BOS", "LIQUIDITY"
    timeframe: str = Field(max_length=5)
    direction: Optional[str] = Field(default=None, max_length=10)
    confidence: Optional[int] = None               # pattern-specific confidence 0–100
    price_level: Optional[float] = None
    details: Optional[str] = Field(default=None, sa_column=Column(Text))


# ─── claude_responses ──────────────────────────────────────────────────────────
class ClaudeResponse(SQLModel, table=True):
    __tablename__ = "claude_responses"

    id: Optional[int] = Field(default=None, primary_key=True)
    signal_id: Optional[int] = Field(default=None, foreign_key="signals.id")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    prompt_version: int = Field(default=1)
    model_used: str = Field(default="claude-haiku-4-5", max_length=50)
    raw_response: Optional[str] = Field(default=None, sa_column=Column(Text))
    parsed_verdict: Optional[str] = Field(default=None, max_length=10)
    parsed_confidence: Optional[int] = None
    parsed_direction: Optional[str] = Field(default=None, max_length=10)
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    latency_ms: Optional[int] = None
