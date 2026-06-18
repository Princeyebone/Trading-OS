"""
Charts router — GET /api/charts/data
Provides unified data for the TradingView Lightweight Charts component.
"""
from datetime import datetime, timezone
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select, col

from app.database import get_session
from app.models.signals import Signal, MarketContext, PatternEvent
from app.models.tape import TapeEvent
from engine.data_fetcher import fetch_ohlcv

router = APIRouter(prefix="/api/charts", tags=["charts"])

@router.get("/data")
def get_chart_data(session: Session = Depends(get_session)):
    """
    Returns unified chart data:
    1. candles (M15)
    2. regimes (LOW_VOL areas)
    3. structures (Liquidity, OB, FVG)
    4. markers (Signals)
    """
    # 1. Fetch Candles
    df = fetch_ohlcv("M15", use_cache=False)
    if df is None or df.empty:
        raise HTTPException(status_code=503, detail="Market data unavailable")

    # Limit to the last 1500 candles (approx 15 days) to keep response fast
    df = df.tail(1500)
    
    candles = []
    for dt, row in df.iterrows():
        # dt is typically timezone aware, convert to unix timestamp
        timestamp = int(dt.timestamp())
        candles.append({
            "time": timestamp,
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"])
        })
        
    start_time_ts = candles[0]["time"]
    start_time_dt = datetime.fromtimestamp(start_time_ts, tz=timezone.utc)

    # 2. Fetch Signals (Markers)
    signals = session.exec(
        select(Signal).where(Signal.created_at >= start_time_dt)
    ).all()
    
    markers = []
    for sig in signals:
        if not sig.price_at_signal:
            continue
            
        color = "gray"
        shape = "circle"
        if sig.direction == "LONG":
            color = "#22c55e" # green
            shape = "arrowUp"
        elif sig.direction == "SHORT":
            color = "#ef4444" # red
            shape = "arrowDown"
            
        markers.append({
            "time": int(sig.created_at.timestamp()),
            "position": "belowBar" if sig.direction == "LONG" else ("aboveBar" if sig.direction == "SHORT" else "inBar"),
            "color": color,
            "shape": shape,
            "text": f"{sig.verdict} ({sig.direction or 'NONE'})",
            "signal_id": sig.id
        })

    # 3. Fetch Regime zones (LOW_VOLATILITY)
    # MarketContext does not have created_at, we join with Signal
    mc_history = session.exec(
        select(MarketContext, Signal)
        .join(Signal, MarketContext.signal_id == Signal.id)
        .where(Signal.created_at >= start_time_dt)
        .order_by(Signal.created_at.asc())
    ).all()
    
    regime_zones = []
    current_zone = None

    for mc, sig in mc_history:
        is_low_vol = mc.atr_percentile is not None and mc.atr_percentile < 20
        ts = int(sig.created_at.timestamp())
        
        if is_low_vol and not current_zone:
            current_zone = {"startTime": ts, "endTime": ts, "type": "LOW_VOL"}
        elif is_low_vol and current_zone:
            current_zone["endTime"] = ts
        elif not is_low_vol and current_zone:
            regime_zones.append(current_zone)
            current_zone = None
            
    if current_zone:
        # Extend to the last candle if still in low vol
        current_zone["endTime"] = candles[-1]["time"]
        regime_zones.append(current_zone)

    # 4. Fetch Structures (from PatternEvent)
    patterns_db = session.exec(
        select(PatternEvent, Signal)
        .join(Signal, PatternEvent.signal_id == Signal.id)
        .where(Signal.created_at >= start_time_dt)
    ).all()
    
    structures = []
    for pe, sig in patterns_db:
        ts = int(sig.created_at.timestamp())
        pe_type = pe.pattern_type.lower()
        if pe_type in ['compression', 'liquidity', 'fvg', 'ob']:
            # For simplicity in visual truth layer, we just mark the level as a line
            # Advanced boxes could be added by passing startTime and endTime if stored
            structures.append({
                "type": pe_type,
                "time": ts,
                "upper": pe.price_level,
                "lower": pe.price_level,  # Fallback if no specific lower bound is available
                "strengthScore": pe.confidence or 0
            })
        elif "COMPRESSION" in pe.pattern_type.upper() or "OB" in pe.pattern_type.upper() or "FVG" in pe.pattern_type.upper():
            # Try to extract upper/lower from details if it's a zone
            # This is a simplification; we'll assume the engine logs them as text in `details` or we fall back to price_level
            structures.append({
                "type": "zone",
                "label": pe.pattern_type,
                "startTime": ts - (4 * 3600),
                "endTime": ts,
                "upper": pe.price_level + 2.0 if pe.price_level else 0, # Approximate bounds if not available natively
                "lower": pe.price_level - 2.0 if pe.price_level else 0,
                "strengthScore": pe.confidence or 0
            })

    # 5. Fetch Tape Events
    tape_events_db = session.exec(
        select(TapeEvent).where(TapeEvent.created_at >= start_time_dt)
    ).all()
    
    tape_events = []
    for te in tape_events_db:
        tape_events.append({
            "time": int(te.created_at.timestamp()),
            "event": te.event_type,
            "price": float(te.price),
            "level": te.level,
            "direction": te.direction
        })

    return {
        "candles": candles,
        "regimes": regime_zones,
        "markers": markers,
        "structures": structures,
        "tape_events": tape_events
    }
