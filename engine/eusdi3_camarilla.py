import logging
from datetime import datetime, timezone, timedelta
import pandas as pd
import MetaTrader5 as mt5

from engine import broker_executor, telegram_notifier

logger = logging.getLogger(__name__)

SYMBOL = "EURUSD"
LOT_SIZE = 0.10
ATR_SL_MULT = 1.0
ATR_TP_MULT = 2.0

def _get_daily_camarilla():
    """Fetch previous day's H, L, C and calculate Camarilla R3/S3 bounds."""
    # Fetch 2 daily candles to get yesterday's completed candle
    rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_D1, 0, 2)
    if rates is None or len(rates) < 2:
        return None, None
        
    yesterday = rates[0] # Index 0 is yesterday, index 1 is today (incomplete)
    
    h = yesterday['high']
    l = yesterday['low']
    c = yesterday['close']
    
    range_dl = h - l
    r3 = c + (range_dl * 1.1 / 4)
    s3 = c - (range_dl * 1.1 / 4)
    
    return r3, s3

def _get_current_atr():
    """Calculate current ATR(14) using H1 candles to size SL/TP dynamically."""
    rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_H1, 0, 15)
    if rates is None or len(rates) < 15:
        return 0.0015 # default 15 pips
        
    df = pd.DataFrame(rates)
    h = df['high']
    l = df['low']
    c = df['close']
    tr = pd.concat([h - l, abs(h - c.shift()), abs(l - c.shift())], axis=1).max(axis=1)
    atr = tr.mean()
    return atr

def _has_traded_recently(direction: str) -> bool:
    """Ensure we don't spam multiple trades in the same zone within the last 4 hours."""
    utc_to = datetime.now(timezone.utc)
    utc_from = utc_to - timedelta(hours=4)
    
    # Check open positions
    positions = mt5.positions_get(symbol=SYMBOL)
    if positions:
        for p in positions:
            if p.comment and "EUSDI3" in p.comment:
                return True
                
    # Check history deals
    deals = mt5.history_deals_get(utc_from, utc_to, group=f"*{SYMBOL}*")
    if deals:
        for d in deals:
            if d.comment and "EUSDI3" in d.comment:
                return True
                
    return False

def run_camarilla_reversal():
    """
    EUSDI3: Camarilla Pivot Reversal System.
    Checks if price has pierced R3/S3 and is reversing back inside.
    Runs every 5 minutes from the scheduler.
    """
    try:
        logger.info(f"[{SYMBOL}] EUSDI3 Camarilla cycle starting...")
        if not broker_executor._init_mt5():
            return
            
        r3, s3 = _get_daily_camarilla()
        if r3 is None or s3 is None:
            return
            
        # Get latest M15 candles to check for piercing/rejection
        rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M15, 0, 3)
        if rates is None or len(rates) < 3:
            return
            
        prev_candle = rates[1]
        curr_tick = mt5.symbol_info_tick(SYMBOL)
        if curr_tick is None:
            return
            
        bid = curr_tick.bid
        ask = curr_tick.ask
        
        # Log the active monitoring
        logger.info(f"[{SYMBOL}] EUSDI3 Monitor: M15 Close={prev_candle['close']:.5f} | R3 Bound={r3:.5f} | S3 Bound={s3:.5f}")
        
        # 1. Bearish Reversal from R3
        if prev_candle['high'] >= r3 and bid < r3:
            if not _has_traded_recently("SHORT"):
                atr = _get_current_atr()
                sl_price = ask + (atr * ATR_SL_MULT)
                tp_price = bid - (atr * ATR_TP_MULT)
                
                logger.info(f"[{SYMBOL}] EUSDI3 Bearish Reversal at R3 ({r3:.5f}). Placing SHORT.")
                res = broker_executor.place_order(
                    symbol=SYMBOL,
                    direction="SHORT",
                    lot_size=LOT_SIZE,
                    entry_price=bid,
                    stop_loss=sl_price,
                    take_profit=tp_price,
                    comment="EUSDI3_Cam_Short"
                )
                if res.get("success"):
                    telegram_notifier.notify_trade(
                        "EUSDI3 Camarilla Reversal",
                        "SHORT", SYMBOL, bid, sl_price, tp_price,
                        reason=f"Price rejected R3 resistance at {r3:.5f}"
                    )
                    
        # 2. Bullish Reversal from S3
        elif prev_candle['low'] <= s3 and ask > s3:
            if not _has_traded_recently("LONG"):
                atr = _get_current_atr()
                sl_price = bid - (atr * ATR_SL_MULT)
                tp_price = ask + (atr * ATR_TP_MULT)
                
                logger.info(f"[{SYMBOL}] EUSDI3 Bullish Reversal at S3 ({s3:.5f}). Placing LONG.")
                res = broker_executor.place_order(
                    symbol=SYMBOL,
                    direction="LONG",
                    lot_size=LOT_SIZE,
                    entry_price=ask,
                    stop_loss=sl_price,
                    take_profit=tp_price,
                    comment="EUSDI3_Cam_Long"
                )
                if res.get("success"):
                    telegram_notifier.notify_trade(
                        "EUSDI3 Camarilla Reversal",
                        "LONG", SYMBOL, ask, sl_price, tp_price,
                        reason=f"Price rejected S3 support at {s3:.5f}"
                    )
                    
    except Exception as e:
        logger.error(f"Error in EUSDI3 cycle: {e}")
