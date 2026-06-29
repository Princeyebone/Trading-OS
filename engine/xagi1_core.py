import logging
import pandas as pd
import numpy as np
import MetaTrader5 as mt5

from engine import broker_executor, telegram_notifier

logger = logging.getLogger(__name__)

SYMBOL = "XAGUSD"
LOT_SIZE = 0.50  # Adjust as needed for Silver. Silver pip values are different.

def get_h1_macd() -> tuple[float, float, float]:
    """
    Fetches the last 300 H1 candles, calculates MACD (12, 26), 
    and returns the MACD value for the last two closed candles and current price.
    Returns (macd_prev, macd_curr, current_price)
    """
    try:
        rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_H1, 0, 300)
        if rates is None or len(rates) < 30:
            return 0.0, 0.0, 0.0
            
        df = pd.DataFrame(rates)
        c = df['close']
        
        # Calculate MACD (12, 26)
        ema12 = c.ewm(span=12, adjust=False).mean()
        ema26 = c.ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        
        # Index -1 is the current forming candle. Index -2 is the last closed candle. Index -3 is the one before that.
        # For a signal to trigger on candle close, we check if the closed candle (-2) crossed the zero line
        # relative to the candle before it (-3).
        macd_curr = macd.iloc[-2]
        macd_prev = macd.iloc[-3]
        current_price = c.iloc[-1]
        
        return macd_prev, macd_curr, current_price
        
    except Exception as e:
        logger.error(f"Error calculating XAGI1 MACD: {e}")
        return 0.0, 0.0, 0.0

def _get_current_position_direction() -> str | None:
    """Returns 'LONG', 'SHORT', or None for the XAGI1 strategy."""
    positions = mt5.positions_get(symbol=SYMBOL)
    if not positions:
        return None
        
    for p in positions:
        if hasattr(p, "comment") and p.comment and "XAGI1" in p.comment:
            if p.type == mt5.POSITION_TYPE_BUY:
                return "LONG"
            elif p.type == mt5.POSITION_TYPE_SELL:
                return "SHORT"
    return None

def _close_xagi1_positions():
    """Closes any open XAGI1 positions to facilitate stop-and-reverse."""
    positions = mt5.positions_get(symbol=SYMBOL)
    if not positions:
        return
        
    for p in positions:
        if hasattr(p, "comment") and p.comment and "XAGI1" in p.comment:
            broker_executor.close_position(
                ticket=p.ticket,
                symbol=SYMBOL,
                position_type=p.type,
                volume=p.volume
            )
            logger.info(f"[{SYMBOL}] Closed XAGI1 position {p.ticket} for reversal.")

def run_macd_trend():
    """
    XAGI1: Silver MACD Trend Runner (Stop and Reverse)
    Evaluated hourly.
    """
    try:
        logger.info("[XAGI1-MACD] Cycle starting...")
        if not broker_executor._init_mt5():
            return
            
        macd_prev, macd_curr, current_price = get_h1_macd()
        if macd_curr == 0.0 and macd_prev == 0.0:
            return # Data error
            
        current_dir = _get_current_position_direction()
        
        # Check Long Breakout (MACD crosses ABOVE 0)
        if macd_prev <= 0 and macd_curr > 0:
            if current_dir != "LONG":
                logger.info(f"[{SYMBOL}] XAGI1 MACD Bullish Cross (Prev: {macd_prev:.3f}, Curr: {macd_curr:.3f})")
                
                # Close short if exists
                if current_dir == "SHORT":
                    _close_xagi1_positions()
                    
                # Enter Long
                res = broker_executor.place_order(
                    direction="LONG",
                    lot_size=LOT_SIZE,
                    entry_price=current_price,
                    stop_loss=0.0,  # Pure SAR system, no fixed SL/TP
                    take_profit=0.0,
                    comment="XAGI1_LONG"
                )
                if res.get("success"):
                    telegram_notifier.notify_info(
                        "XAGI1 Bullish Trend Triggered",
                        f"LONG {SYMBOL} @ {res.get('actual_entry', current_price):.3f}\n"
                        f"MACD Zero Cross: {macd_prev:.3f} -> {macd_curr:.3f}\n"
                        f"Strategy: Stop & Reverse"
                    )

        # Check Short Breakout (MACD crosses BELOW 0)
        elif macd_prev >= 0 and macd_curr < 0:
            if current_dir != "SHORT":
                logger.info(f"[{SYMBOL}] XAGI1 MACD Bearish Cross (Prev: {macd_prev:.3f}, Curr: {macd_curr:.3f})")
                
                # Close long if exists
                if current_dir == "LONG":
                    _close_xagi1_positions()
                    
                # Enter Short
                res = broker_executor.place_order(
                    direction="SHORT",
                    lot_size=LOT_SIZE,
                    entry_price=current_price,
                    stop_loss=0.0,  # Pure SAR system
                    take_profit=0.0,
                    comment="XAGI1_SHORT"
                )
                if res.get("success"):
                    telegram_notifier.notify_info(
                        "XAGI1 Bearish Trend Triggered",
                        f"SHORT {SYMBOL} @ {res.get('actual_entry', current_price):.3f}\n"
                        f"MACD Zero Cross: {macd_prev:.3f} -> {macd_curr:.3f}\n"
                        f"Strategy: Stop & Reverse"
                    )
                    
    except Exception as e:
        logger.error(f"Error in XAGI1 cycle: {e}")
