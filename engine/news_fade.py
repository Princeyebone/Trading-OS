"""
engine/news_fade.py
Executes a Mean Reversion (Fade) strategy 5 to 15 minutes after a high-impact news event.
Scans for a massive exhaustion wick on the M5 chart.
"""
import logging
import MetaTrader5 as mt5
import pandas as pd
from engine.data_fetcher import fetch_ohlcv
from engine import broker_executor, telegram_notifier
from app.models.signals import Signal
from engine.db import get_session, log_trade_to_db

logger = logging.getLogger("engine.news_fade")

MAGIC_NUMBER_FADE = 209001

def run_news_fade(event_title: str):
    """
    Scans the M5 chart for an exhaustion wick on the most recently closed candle.
    If a massive wick is detected, it fades the spike.
    """
    logger.info(f"[NEWS FADE] Scanning for post-news exhaustion: {event_title}")
    
    if not broker_executor._init_mt5():
        return
        
    m5_data = fetch_ohlcv("M5", use_cache=False)
    if m5_data is None or len(m5_data) < 2:
        return
        
    # We want the most recently CLOSED candle
    closed_candle = m5_data.iloc[-2]
    
    _open = closed_candle['open']
    _high = closed_candle['high']
    _low = closed_candle['low']
    _close = closed_candle['close']
    
    candle_range = _high - _low
    if candle_range < 3.0: # Minimum 30 pips (3.0 points) range to qualify as a "news spike"
        logger.info(f"[NEWS FADE] Candle range too small ({candle_range:.1f} pts). No fade setup.")
        return
        
    body_top = max(_open, _close)
    body_bottom = min(_open, _close)
    
    upper_wick = _high - body_top
    lower_wick = body_bottom - _low
    
    direction = None
    sl = 0.0
    tp = 0.0
    entry = (mt5.symbol_info_tick("XAUUSD").bid + mt5.symbol_info_tick("XAUUSD").ask) / 2.0
    
    # 1. Bearish Exhaustion (Spiked up, rejected) => Short
    if upper_wick / candle_range > 0.60:
        logger.info(f"[NEWS FADE] Bearish Exhaustion Wick Detected. Wick: {upper_wick/candle_range*100:.1f}%")
        direction = "SHORT"
        sl = _high + 1.0 # Stop loss 10 pips above the wick high
        risk = sl - entry
        tp = entry - (risk * 2.0) # 1:2 RR target
        
    # 2. Bullish Exhaustion (Spiked down, rejected) => Long
    elif lower_wick / candle_range > 0.60:
        logger.info(f"[NEWS FADE] Bullish Exhaustion Wick Detected. Wick: {lower_wick/candle_range*100:.1f}%")
        direction = "LONG"
        sl = _low - 1.0 # Stop loss 10 pips below the wick low
        risk = entry - sl
        tp = entry + (risk * 2.0) # 1:2 RR target
        
    if direction:
        # Check if we already have a fade trade open
        positions = mt5.positions_get(symbol="XAUUSD")
        if positions:
            for p in positions:
                if p.magic == MAGIC_NUMBER_FADE:
                    logger.info("[NEWS FADE] Fade trade already active. Skipping.")
                    return
                    
        lot_size = 0.05
        
        order_result = broker_executor.place_order(
            direction=direction,
            lot_size=lot_size,
            entry_price=entry,
            stop_loss=sl,
            take_profit=tp,
            magic=MAGIC_NUMBER_FADE,
            comment="News-Fade-v1",
            symbol="XAUUSD"
        )
        
        if order_result.get("success"):
            telegram_notifier.notify_success(
                "News Fade Triggered",
                f"Faded {event_title} volatility.\n"
                f"Direction: {direction}\n"
                f"Entry: {order_result['actual_entry']:.2f}\n"
                f"SL: {sl:.2f} | TP: {tp:.2f}\n"
                f"Candle Range: {candle_range:.1f} pts"
            )
