import logging
import pandas as pd
import numpy as np
import MetaTrader5 as mt5

from engine import broker_executor, telegram_notifier

logger = logging.getLogger(__name__)

SYMBOL = "XAGUSD"
LOT_SIZE = 0.50  # Adjust as needed for Silver.

def get_h1_emas() -> tuple[float, float, float, float, float]:
    """
    Fetches the last 300 H1 candles, calculates EMA(9) and EMA(21), 
    and returns the EMAs for the last two closed candles and current price.
    Returns (ema9_prev, ema21_prev, ema9_curr, ema21_curr, current_price)
    """
    try:
        rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_H1, 0, 300)
        if rates is None or len(rates) < 30:
            return 0.0, 0.0, 0.0, 0.0, 0.0
            
        df = pd.DataFrame(rates)
        c = df['close']
        
        ema9 = c.ewm(span=9, adjust=False).mean()
        ema21 = c.ewm(span=21, adjust=False).mean()
        
        # Index -1 is the current forming candle. 
        # Index -2 is the last closed candle. 
        # Index -3 is the one before that.
        ema9_curr = ema9.iloc[-2]
        ema21_curr = ema21.iloc[-2]
        
        ema9_prev = ema9.iloc[-3]
        ema21_prev = ema21.iloc[-3]
        
        current_price = c.iloc[-1]
        
        return ema9_prev, ema21_prev, ema9_curr, ema21_curr, current_price
        
    except Exception as e:
        logger.error(f"Error calculating XAGI2 EMAs: {e}")
        return 0.0, 0.0, 0.0, 0.0, 0.0

def _get_current_position_direction() -> str | None:
    """Returns 'LONG', 'SHORT', or None for the XAGI2 strategy."""
    positions = mt5.positions_get(symbol=SYMBOL)
    if not positions:
        return None
        
    for p in positions:
        if hasattr(p, "comment") and p.comment and "XAGI2" in p.comment:
            if p.type == mt5.POSITION_TYPE_BUY:
                return "LONG"
            elif p.type == mt5.POSITION_TYPE_SELL:
                return "SHORT"
    return None

def _close_xagi2_positions():
    """Closes any open XAGI2 positions to facilitate stop-and-reverse."""
    positions = mt5.positions_get(symbol=SYMBOL)
    if not positions:
        return
        
    for p in positions:
        if hasattr(p, "comment") and p.comment and "XAGI2" in p.comment:
            broker_executor.close_position(
                ticket=p.ticket,
                symbol=SYMBOL,
                position_type=p.type,
                volume=p.volume
            )
            logger.info(f"[{SYMBOL}] Closed XAGI2 position {p.ticket} for reversal.")

def run_ema_trend():
    """
    XAGI2: Silver EMA (9/21) Trend Runner (Stop and Reverse)
    Evaluated hourly.
    """
    try:
        if not broker_executor._init_mt5():
            return
            
        ema9_prev, ema21_prev, ema9_curr, ema21_curr, current_price = get_h1_emas()
        if ema9_curr == 0.0:
            return # Data error
            
        current_dir = _get_current_position_direction()
        
        # Check Long Breakout (EMA9 crosses ABOVE EMA21)
        if ema9_prev <= ema21_prev and ema9_curr > ema21_curr:
            if current_dir != "LONG":
                logger.info(f"[{SYMBOL}] XAGI2 EMA Bullish Cross (EMA9: {ema9_curr:.3f} > EMA21: {ema21_curr:.3f})")
                
                # Close short if exists
                if current_dir == "SHORT":
                    _close_xagi2_positions()
                    
                # Enter Long
                res = broker_executor.place_order(
                    direction="LONG",
                    lot_size=LOT_SIZE,
                    entry_price=current_price,
                    stop_loss=0.0,  # Pure SAR system
                    take_profit=0.0,
                    comment="XAGI2_LONG"
                )
                if res.get("success"):
                    telegram_notifier.notify_info(
                        "XAGI2 Bullish Trend Triggered",
                        f"LONG {SYMBOL} @ {res.get('actual_entry', current_price):.3f}\n"
                        f"EMA 9/21 Cross: {ema9_curr:.3f} > {ema21_curr:.3f}\n"
                        f"Strategy: Stop & Reverse"
                    )

        # Check Short Breakout (EMA9 crosses BELOW EMA21)
        elif ema9_prev >= ema21_prev and ema9_curr < ema21_curr:
            if current_dir != "SHORT":
                logger.info(f"[{SYMBOL}] XAGI2 EMA Bearish Cross (EMA9: {ema9_curr:.3f} < EMA21: {ema21_curr:.3f})")
                
                # Close long if exists
                if current_dir == "LONG":
                    _close_xagi2_positions()
                    
                # Enter Short
                res = broker_executor.place_order(
                    direction="SHORT",
                    lot_size=LOT_SIZE,
                    entry_price=current_price,
                    stop_loss=0.0,  # Pure SAR system
                    take_profit=0.0,
                    comment="XAGI2_SHORT"
                )
                if res.get("success"):
                    telegram_notifier.notify_info(
                        "XAGI2 Bearish Trend Triggered",
                        f"SHORT {SYMBOL} @ {res.get('actual_entry', current_price):.3f}\n"
                        f"EMA 9/21 Cross: {ema9_curr:.3f} < {ema21_curr:.3f}\n"
                        f"Strategy: Stop & Reverse"
                    )
                    
    except Exception as e:
        logger.error(f"Error in XAGI2 cycle: {e}")
