"""
Engine configuration router.
GET /api/config  — current active engine config
PUT /api/config  — update config
POST /api/config/reset — reset to defaults
"""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from sqlmodel import Session, select
from app.database import get_session
from app.models.config import EngineConfig

router = APIRouter(prefix="/api/config", tags=["config"])


class ConfigUpdate(BaseModel):
    account_balance_equiv: Optional[float] = None
    max_risk_percent: Optional[float] = None
    confidence_threshold: Optional[int] = None
    min_atr_percentile: Optional[int] = None
    min_rr_ratio: Optional[float] = None
    max_trades_per_day: Optional[int] = None
    max_open_trades: Optional[int] = None
    consecutive_loss_pause: Optional[int] = None
    london_start_hour: Optional[int] = None
    london_end_hour: Optional[int] = None
    ny_start_hour: Optional[int] = None
    ny_end_hour: Optional[int] = None
    news_blackout_minutes: Optional[int] = None
    engine_interval_minutes: Optional[int] = None
    telegram_enabled: Optional[bool] = None


def _get_or_create_config(session: Session) -> EngineConfig:
    """Return the active config, or create defaults if none exists."""
    config = session.exec(
        select(EngineConfig).where(EngineConfig.is_active == True)
    ).first()
    if not config:
        config = EngineConfig()
        session.add(config)
        session.commit()
        session.refresh(config)
    return config


@router.get("")
def get_config(session: Session = Depends(get_session)):
    return _get_or_create_config(session)


@router.put("")
def update_config(body: ConfigUpdate, session: Session = Depends(get_session)):
    config = _get_or_create_config(session)
    update_data = body.model_dump(exclude_none=True)

    # Enforce hard limits from design doc
    if "confidence_threshold" in update_data:
        update_data["confidence_threshold"] = max(65, update_data["confidence_threshold"])

    for key, value in update_data.items():
        setattr(config, key, value)
    config.updated_at = datetime.now(timezone.utc)
    config.updated_by = "dashboard"

    session.add(config)
    session.commit()
    session.refresh(config)
    return config


@router.post("/reset")
def reset_config(session: Session = Depends(get_session)):
    """Reset all config values to system defaults."""
    config = _get_or_create_config(session)
    defaults = EngineConfig()
    for field in EngineConfig.model_fields:
        if field not in ("id", "is_active"):
            setattr(config, field, getattr(defaults, field))
    config.updated_at = datetime.now(timezone.utc)
    config.updated_by = "reset"
    session.add(config)
    session.commit()
    session.refresh(config)
    return config
