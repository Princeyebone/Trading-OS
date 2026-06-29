import logging
from datetime import datetime, timezone, timedelta
import pandas as pd
import MetaTrader5 as mt5

from engine import broker_executor, telegram_notifier

logger = logging.getLogger(__name__)

SYMBOL = "EURUSD"
LOT_SIZE = 0.10

def _get_current_atr():
    rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_H1, 0, 15)
    if rates is None or len(rates) < 15:
        return 0.0015
        
    df = pd.DataFrame(rates)
    h = df['high']
    l = df['low']
    c = df['close']
    tr = pd.concat([h - l, abs(h - c.shift()), abs(l - c.shift())], axis=1).max(axis=1)
    atr = tr.mean()
    return atr

def _get_daily_profiling():
    """Returns today's High, Low, Open, and the 14-day Average Daily Range."""
    rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_D1, 0, 15)
    if rates is None or len(rates) < 15:
        return None, None, None, None
        
    df = pd.DataFrame(rates)
    h = df['high']
    l = df['low']
    c = df['close']
    tr = pd.concat([h - l, abs(h - c.shift()), abs(l - c.shift())], axis=1).max(axis=1)
    
    # Calculate 14-day ADR up to yesterday
    adr14 = tr.iloc[:-1].rolling(14).mean().iloc[-1]
    
    today = df.iloc[-1]
    return today['high'], today['low'], today['open'], adr14

def run_adr_exhaustion():
    """
    EUSDI5: ADR Exhaustion.
    Runs every 15 minutes. Checks if today's range has hit exactly 100% of the 14-day ADR.
    If so, it fades the extreme for a mean-reversion trade.
    """
    try:
        logger.info(f"[{SYMBOL}] EUSDI5 ADR Exhaustion cycle starting...")
        if not broker_executor._init_mt5():
            return
            
        today_h, today_l, today_o, adr14 = _get_daily_profiling()
        if adr14 is None or pd.isna(adr14):
            return
            
        curr_tick = mt5.symbol_info_tick(SYMBOL)
        if curr_tick is None:
            return
            
        bid = curr_tick.bid
        ask = curr_tick.ask
        
        # Calculate current daily range
        if bid > today_o:
            today_range = today_h - today_l
            is_bullish_day = True
        else:
            today_range = today_h - today_l
            is_bullish_day = False
            
        # Log active monitoring
        logger.info(f"[{SYMBOL}] EUSDI5 Monitor: Today's Range={today_range:.5f} | 100% ADR limit={adr14:.5f}")
        
        # If range exceeds 100% ADR, fade it
        if today_range >= (adr14 * 1.0):
            atr = _get_current_atr()
            
            if is_bullish_day and bid >= today_h - 0.0005: # Near the high
                sl_price = ask + (atr * 1.0)
                tp_price = bid - (atr * 2.0)
                
                logger.info(f"[{SYMBOL}] EUSDI5 ADR Exhaustion reached ({today_range:.5f} >= {adr14:.5f}). Fading extreme High.")
                res = broker_executor.place_order(
                    symbol=SYMBOL, direction="SHORT", lot_size=LOT_SIZE,
                    entry_price=bid, stop_loss=sl_price, take_profit=tp_price, comment="EUSDI5_ADR_Short"
                )
                if res.get("success"):
                    telegram_notifier.notify_trade("EUSDI5 ADR Exhaustion", "SHORT", SYMBOL, bid, sl_price, tp_price, reason="100% ADR Reached")
                    
            elif not is_bullish_day and ask <= today_l + 0.0005: # Near the low
                sl_price = bid - (atr * 1.0)
                tp_price = ask + (atr * 2.0)
                
                logger.info(f"[{SYMBOL}] EUSDI5 ADR Exhaustion reached ({today_range:.5f} >= {adr14:.5f}). Fading extreme Low.")
                res = broker_executor.place_order(
                    symbol=SYMBOL, direction="LONG", lot_size=LOT_SIZE,
                    entry_price=ask, stop_loss=sl_price, take_profit=tp_price, comment="EUSDI5_ADR_Long"
                )
                if res.get("success"):
                    telegram_notifier.notify_trade("EUSDI5 ADR Exhaustion", "LONG", SYMBOL, ask, sl_price, tp_price, reason="100% ADR Reached")
                    
    except Exception as e:
        logger.error(f"Error in EUSDI5 ADR Exhaustion: {e}")

def run_asian_volatility_squeeze():
    """
    EUSDI5: Asian Volatility Squeeze.
    Runs exactly at 07:05 UTC (London Open).
    If the Asian Session (00:00 to 07:00 UTC) range was < 30% of ADR, it trades the London Breakout.
    """
    try:
        logger.info(f"[{SYMBOL}] EUSDI5 Asian Squeeze checking for explosive breakout...")
        if not broker_executor._init_mt5():
            return
            
        today_h, today_l, today_o, adr14 = _get_daily_profiling()
        if adr14 is None:
            return
            
        # Get Asian session H1 candles (00:00 to 07:00)
        rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_H1, 0, 8)
        if rates is None or len(rates) < 8:
            return
            
        df = pd.DataFrame(rates)
        asian_high = df.iloc[:-1]['high'].max() # Exclude the current 07:00 candle
        asian_low = df.iloc[:-1]['low'].min()
        asian_range = asian_high - asian_low
        
        curr_tick = mt5.symbol_info_tick(SYMBOL)
        if curr_tick is None:
            return
            
        bid = curr_tick.bid
        ask = curr_tick.ask
        
        logger.info(f"[{SYMBOL}] EUSDI5 Asian Range={asian_range:.5f} | 30% ADR Squeeze Limit={adr14 * 0.3:.5f}")
        
        if asian_range < (adr14 * 0.3): # Massive squeeze
            atr = _get_current_atr()
            
            if bid > asian_high: # Breakout UP
                sl_price = ask - (atr * 1.5)
                tp_price = bid + (atr * 2.0)
                
                logger.info(f"[{SYMBOL}] EUSDI5 Massive Asian Squeeze detected. Trading London Breakout LONG.")
                res = broker_executor.place_order(
                    symbol=SYMBOL, direction="LONG", lot_size=LOT_SIZE,
                    entry_price=ask, stop_loss=sl_price, take_profit=tp_price, comment="EUSDI5_Sqz_Long"
                )
                if res.get("success"):
                    telegram_notifier.notify_trade("EUSDI5 Asian Squeeze Breakout", "LONG", SYMBOL, ask, sl_price, tp_price, reason="London Breakout following Asian Squeeze")
                    
            elif ask < asian_low: # Breakout DOWN
                sl_price = bid + (atr * 1.5)
                tp_price = ask - (atr * 2.0)
                
                logger.info(f"[{SYMBOL}] EUSDI5 Massive Asian Squeeze detected. Trading London Breakout SHORT.")
                res = broker_executor.place_order(
                    symbol=SYMBOL, direction="SHORT", lot_size=LOT_SIZE,
                    entry_price=bid, stop_loss=sl_price, take_profit=tp_price, comment="EUSDI5_Sqz_Short"
                )
                if res.get("success"):
                    telegram_notifier.notify_trade("EUSDI5 Asian Squeeze Breakout", "SHORT", SYMBOL, bid, sl_price, tp_price, reason="London Breakout following Asian Squeeze")
        else:
            logger.info(f"[{SYMBOL}] EUSDI5 Normal Asian Range. Squeeze not met.")
            
    except Exception as e:
        logger.error(f"Error in EUSDI5 Volatility Squeeze: {e}")
