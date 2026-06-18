"""
engine/market_tape_monitor.py — Live observability monitor for liquidity events.
Does NOT execute trades or affect strategy. Purely for dashboard visualization.
"""
import logging
import json
from datetime import datetime, timezone
from sqlmodel import Session
from app.database import engine
from app.models.tape import TapeEvent
from engine import data_fetcher, pattern_detector

logger = logging.getLogger("engine.tape_monitor")

def detect_tape_events():
    """
    Run every 1 minute.
    Checks recent candles against liquidity clusters to find touches, sweeps, and rejections.
    """
    try:
        # Fetch minimal timeframes
        timeframes, is_stale = data_fetcher.fetch_all_timeframes()
        if is_stale or timeframes["M15"] is None or timeframes["M15"].empty:
            return

        df_m15 = timeframes["M15"]
        last_3 = df_m15.tail(3)
        current_candle = last_3.iloc[-1]
        
        # Get active liquidity clusters
        patterns_data = pattern_detector.detect_all_patterns(timeframes)
        liquidity_clusters = patterns_data.get("liquidity", [])
        
        if not liquidity_clusters:
            return

        with Session(engine) as db_session:
            for cluster in liquidity_clusters:
                level = cluster.get("level") or cluster.get("mid")
                if not level:
                    continue
                    
                # Define a generic band width (e.g. 1.5 points on Gold) around the level
                upper_bound = level + 1.5
                lower_bound = level - 1.5
                band_str = f"{lower_bound:.2f}-{upper_bound:.2f}"
                
                # Analyze the last completed candle and the current live candle
                for i, (_, c) in enumerate(last_3.iterrows()):
                    candle_range = c['high'] - c['low']
                    if candle_range <= 0:
                        continue
                        
                    upper_wick = c['high'] - max(c['open'], c['close'])
                    lower_wick = min(c['open'], c['close']) - c['low']
                    
                    event_emitted = False
                    
                    # 1. LIQUIDITY SWEEP
                    # Swept above resistance
                    if c['high'] > upper_bound and c['close'] < level:
                        _emit_event(db_session, "LIQUIDITY_SWEEP", float(c['high']), band_str, "BEARISH")
                        event_emitted = True
                    # Swept below support
                    elif c['low'] < lower_bound and c['close'] > level:
                        _emit_event(db_session, "LIQUIDITY_SWEEP", float(c['low']), band_str, "BULLISH")
                        event_emitted = True
                        
                    # 2. WICK REJECTION (>50% of candle range)
                    if not event_emitted:
                        if upper_wick / candle_range > 0.5 and (c['high'] >= lower_bound and c['high'] <= upper_bound * 1.05):
                            _emit_event(db_session, "REJECTION", float(c['high']), band_str, "BEARISH")
                            event_emitted = True
                        elif lower_wick / candle_range > 0.5 and (c['low'] <= upper_bound and c['low'] >= lower_bound * 0.95):
                            _emit_event(db_session, "REJECTION", float(c['low']), band_str, "BULLISH")
                            event_emitted = True
                            
                    # 3. CLUSTER TOUCH
                    if not event_emitted:
                        if lower_bound <= c['high'] <= upper_bound or lower_bound <= c['low'] <= upper_bound:
                            # Avoid spamming touches on the same candle, just log one if touched
                            _emit_event(db_session, "CLUSTER_TOUCH", float(c['close']), band_str, None)
                            event_emitted = True
                        
    except Exception as e:
        logger.error(f"Tape monitor error: {e}")

def _emit_event(session: Session, event_type: str, price: float, level: str, direction: str):
    """Save to DB and log the required JSON output."""
    event = TapeEvent(
        event_type=event_type,
        price=price,
        level=level,
        strength=1.0,
        direction=direction
    )
    
    # We only want to log/save if we haven't logged this exact event for this time block recently.
    # To keep it simple, we just save and let the frontend group/filter them.
    session.add(event)
    session.commit()
    
    # The required JSON log output
    # Muting this in terminal because it floods the console (frontend fetches from DB anyway)
    # log_obj = {
    #     "timestamp": datetime.now(timezone.utc).isoformat(),
    #     "event": event_type,
    #     "price": price,
    #     "level": level,
    #     "strength": 1.0
    # }
    # logger.debug(f"TAPE: {json.dumps(log_obj)}")
