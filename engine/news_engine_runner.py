"""
engine/news_engine_runner.py
Coordinator for the News Strategies.
Runs every minute. Polls news_guard for upcoming or recently passed high-impact events.
Triggers Straddle 1 minute before.
Triggers Fade 5-15 minutes after.
"""
import logging
from engine.news_guard import fetch_high_impact_events
from engine.news_straddle import run_news_straddle, MAGIC_NUMBER_STRADDLE
from engine.news_fade import run_news_fade
from engine import broker_executor
import MetaTrader5 as mt5

logger = logging.getLogger("engine.news_engine_runner")

_straddled_events = set() # Store event timestamps so we only straddle once per event

def enforce_straddle_oco():
    """
    One Cancels Other (OCO) logic for the News Straddle.
    If one pending order triggers (becomes a position), delete the remaining pending order.
    """
    if not broker_executor._init_mt5():
        return
        
    positions = mt5.positions_get(symbol="XAUUSD")
    straddle_active = False
    if positions:
        for p in positions:
            if p.magic == MAGIC_NUMBER_STRADDLE:
                straddle_active = True
                break
                
    if straddle_active:
        # One side triggered. Cancel the other pending orders.
        orders = mt5.orders_get(symbol="XAUUSD")
        if orders:
            for o in orders:
                if o.magic == MAGIC_NUMBER_STRADDLE:
                    req = {
                        "action": mt5.TRADE_ACTION_REMOVE,
                        "order": o.ticket,
                    }
                    res = mt5.order_send(req)
                    if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                        logger.info(f"OCO: Cancelled pending straddle order {o.ticket} because the other side triggered.")

def run_news_engine_cycle():
    """
    Evaluated every minute by the main scheduler.
    """
    enforce_straddle_oco()
    try:
        # Fetch events within ±20 minutes
        events = fetch_high_impact_events(window_minutes=20)
        
        for ev in events:
            mins_away = ev['minutes_away']
            title = ev['title']
            event_id = f"{title}_{ev['event_utc'].timestamp()}"
            
            # 1. Trigger Straddle (between 0.5 and 1.5 minutes away)
            if 0.5 <= mins_away <= 1.5:
                if event_id not in _straddled_events:
                    logger.info(f"[NEWS ENGINE] Straddle condition met for {title} ({mins_away:.1f} mins away).")
                    run_news_straddle(title)
                    _straddled_events.add(event_id)
            
            # 2. Trigger Fade (between 5.0 and 15.0 minutes passed)
            # mins_away is negative if the event has passed
            if -15.0 <= mins_away <= -5.0:
                logger.info(f"[NEWS ENGINE] Fade window active for {title} (Passed {abs(mins_away):.1f} mins ago). Scanning...")
                run_news_fade(title)
                
    except Exception as e:
        logger.exception(f"[NEWS ENGINE] Cycle error: {e}")
