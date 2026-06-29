import logging
from datetime import datetime, timezone, timedelta
import pandas as pd
import MetaTrader5 as mt5

from engine import broker_executor, telegram_notifier

logger = logging.getLogger(__name__)

SYMBOL = "EURUSD"
LOT_SIZE = 0.10

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

def run_weekly_gap_close():
    """
    EUSDI4: Weekly Gap Close.
    Runs on Monday morning. Detects if there is a massive gap from Friday's close.
    If gap > 1 ATR, it fades the gap (trades to close it).
    """
    try:
        if not broker_executor._init_mt5():
            return
            
        logger.info(f"[{SYMBOL}] EUSDI4 checking for Weekly Gap...")
        
        # We need Friday's close and Monday's open
        # We fetch last 3 Daily candles. Index 2 = Today (Mon), Index 1 = Friday (usually)
        rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_D1, 0, 3)
        if rates is None or len(rates) < 2:
            return
            
        friday_candle = rates[1]
        monday_candle = rates[2]
        
        friday_close = friday_candle['close']
        monday_open = monday_candle['open']
        
        atr = _get_current_atr()
        
        gap_size = monday_open - friday_close
        
        curr_tick = mt5.symbol_info_tick(SYMBOL)
        if curr_tick is None:
            return
            
        bid = curr_tick.bid
        ask = curr_tick.ask
        
        if gap_size > atr:
            # Huge Gap UP -> Fade it (SHORT)
            sl_price = ask + (atr * 2.0)
            tp_price = ask - (atr * 2.0)
            
            logger.info(f"[{SYMBOL}] EUSDI4 Detected massive GAP UP. Placing SHORT to fill gap.")
            res = broker_executor.place_order(
                symbol=SYMBOL, direction="SHORT", lot_size=LOT_SIZE,
                entry_price=bid, stop_loss=sl_price, take_profit=tp_price, comment="EUSDI4_Gap_Short"
            )
            if res.get("success"):
                telegram_notifier.notify_trade("EUSDI4 Weekly Gap Close", "SHORT", SYMBOL, bid, sl_price, tp_price, reason="Fading massive Monday Gap UP")
                
        elif gap_size < -atr:
            # Huge Gap DOWN -> Fade it (LONG)
            sl_price = bid - (atr * 2.0)
            tp_price = bid + (atr * 2.0)
            
            logger.info(f"[{SYMBOL}] EUSDI4 Detected massive GAP DOWN. Placing LONG to fill gap.")
            res = broker_executor.place_order(
                symbol=SYMBOL, direction="LONG", lot_size=LOT_SIZE,
                entry_price=ask, stop_loss=sl_price, take_profit=tp_price, comment="EUSDI4_Gap_Long"
            )
            if res.get("success"):
                telegram_notifier.notify_trade("EUSDI4 Weekly Gap Close", "LONG", SYMBOL, ask, sl_price, tp_price, reason="Fading massive Monday Gap DOWN")
        else:
            logger.info(f"[{SYMBOL}] EUSDI4 No significant gap detected today.")
            
    except Exception as e:
        logger.error(f"Error in EUSDI4 Gap Close cycle: {e}")

def run_london_fix_fade():
    """
    EUSDI4: London Fix Reversal.
    Runs at 17:00 UTC (End of the 16:00 UTC candle).
    Checks if the 16:00 candle had massive momentum (> 1 ATR), and fades it.
    """
    try:
        if not broker_executor._init_mt5():
            return
            
        logger.info(f"[{SYMBOL}] EUSDI4 checking 16:00 UTC London Fix momentum...")
        
        # Fetch the completed 16:00 H1 candle (index 1) and the previous candle (index 0)
        rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_H1, 0, 3)
        if rates is None or len(rates) < 3:
            return
            
        fix_candle = rates[1] # The one that just closed
        prev_candle = rates[0]
        
        atr = _get_current_atr()
        
        curr_tick = mt5.symbol_info_tick(SYMBOL)
        if curr_tick is None:
            return
            
        bid = curr_tick.bid
        ask = curr_tick.ask
        
        # Bullish Spike during the fix
        if fix_candle['close'] > prev_candle['close'] + atr:
            sl_price = ask + (atr * 1.0)
            tp_price = bid - (atr * 2.0)
            
            logger.info(f"[{SYMBOL}] EUSDI4 Detected Bullish Fix Spike. Fading SHORT.")
            res = broker_executor.place_order(
                symbol=SYMBOL, direction="SHORT", lot_size=LOT_SIZE,
                entry_price=bid, stop_loss=sl_price, take_profit=tp_price, comment="EUSDI4_Fix_Short"
            )
            if res.get("success"):
                telegram_notifier.notify_trade("EUSDI4 London Fix Reversal", "SHORT", SYMBOL, bid, sl_price, tp_price, reason="Fading 16:00 UTC Bullish Momentum Spike")
                
        # Bearish Spike during the fix
        elif fix_candle['close'] < prev_candle['close'] - atr:
            sl_price = bid - (atr * 1.0)
            tp_price = ask + (atr * 2.0)
            
            logger.info(f"[{SYMBOL}] EUSDI4 Detected Bearish Fix Spike. Fading LONG.")
            res = broker_executor.place_order(
                symbol=SYMBOL, direction="LONG", lot_size=LOT_SIZE,
                entry_price=ask, stop_loss=sl_price, take_profit=tp_price, comment="EUSDI4_Fix_Long"
            )
            if res.get("success"):
                telegram_notifier.notify_trade("EUSDI4 London Fix Reversal", "LONG", SYMBOL, ask, sl_price, tp_price, reason="Fading 16:00 UTC Bearish Momentum Spike")
        else:
            logger.info(f"[{SYMBOL}] EUSDI4 No massive volatility detected during London Fix.")
            
    except Exception as e:
        logger.error(f"Error in EUSDI4 London Fix cycle: {e}")
