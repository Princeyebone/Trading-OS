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

    # Strategy Activation Toggles (Default: True/On)
    enable_xau_zero_loss: bool = Field(default=True)   # Gold Zero-Loss Scalper (XAU-i6)
    enable_xag_zero_loss: bool = Field(default=True)   # Silver Zero-Loss Scalper (XAG-i2)
    enable_eurusd_i6: bool = Field(default=True)       # EURUSD Mean Reversion (EUSDI6)
    enable_eurusd_i7: bool = Field(default=True)       # EURUSD Momentum Scalper (EUSDI7)
    enable_xau_i1: bool = Field(default=True)          # Gold Core Scalper (XAU-i1)
    enable_xau_i4: bool = Field(default=True)          # Gold Trend Scalper (XAU-i4)
    enable_xau_i5: bool = Field(default=True)          # Gold Volume Scalper (XAU-i5)
    enable_gi2_pullback: bool = Field(default=True)    # Gold 2-Candle Pullback (GI2)
    enable_xagi1_core: bool = Field(default=True)      # Silver Trend Scalper (XAGI1)

    # AI
    ai_provider: str = Field(default="claude", max_length=20)

    # Meta
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_by: str = Field(default="system", max_length=50)
    is_active: bool = Field(default=True)                 # only one active config row
