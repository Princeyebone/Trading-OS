"""
Tape Events DB Model
"""
from typing import Optional
from datetime import datetime, timezone
from sqlmodel import Field, SQLModel

class TapeEvent(SQLModel, table=True):
    __tablename__ = "tape_events"
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    event_type: str  # LIQUIDITY_SWEEP, REJECTION, CLUSTER_TOUCH
    price: float
    level: str       # Description of the liquidity band it interacted with
    strength: float
    direction: Optional[str] = None # BULLISH / BEARISH context
