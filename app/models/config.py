"""
Engine configuration SQLModel table.
Stores all tunable parameters that the Settings page can update.
"""
from datetime import datetime, timezone
from typing import Optional
from sqlmodel import Field, SQLModel


class EngineConfig(SQLModel, table=True):
    __tablename__ = "engine_config"

    id: Optional[int] = Field(default=None, primary_key=True)
    # Position sizing
    account_balance_equiv: float = Field(default=500.0)   # treat demo as this $ amount
    max_risk_percent: float = Field(default=1.0)          # % risk per trade

    # Trade gates
    confidence_threshold: int = Field(default=70)         # minimum Claude confidence to trade
    min_atr_percentile: int = Field(default=20)           # ATR must exceed this percentile
    min_rr_ratio: float = Field(default=1.5)              # minimum risk:reward

    # Limits
    max_trades_per_day: int = Field(default=2)
    max_open_trades: int = Field(default=1)
    consecutive_loss_pause: int = Field(default=3)        # losses before 24hr pause

    # Session windows (EST hours)
    london_start_hour: int = Field(default=3)             # 3am EST
    london_end_hour: int = Field(default=12)              # 12pm EST
    ny_start_hour: int = Field(default=8)                 # 8am EST
    ny_end_hour: int = Field(default=17)                  # 5pm EST

    # News blackout
    news_blackout_minutes: int = Field(default=15)        # ± minutes around red events

    # Scheduler
    engine_interval_minutes: int = Field(default=15)      # how often engine runs

    # Broker
    broker: str = Field(default="MT5", max_length=20)
    broker_environment: str = Field(default="practice", max_length=20)  # practice / live

    # Notifications
    telegram_enabled: bool = Field(default=True)

    # Meta
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_by: str = Field(default="system", max_length=50)
    is_active: bool = Field(default=True)                 # only one active config row
