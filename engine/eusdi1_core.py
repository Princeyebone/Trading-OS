import logging
from datetime import datetime, timezone, timedelta
import pandas as pd
import numpy as np
import MetaTrader5 as mt5

from engine import broker_executor, telegram_notifier

logger = logging.getLogger(__name__)

SYMBOL = "EURUSD"
LOT_SIZE = 0.10  # Standard risk
SL_PIPS = 20.0
TP_PIPS = 40.0
SPREAD_MAX = 2.0  # Max spread we are willing to pay (in pips)

def _has_traded_today(direction: str) -> bool:
    """
    Check MT5 history and open positions to see if we already traded this side today.
    direction: "LONG" or "SHORT"
    """
    comment_tag = f"EUSDI1_{direction}"
    
    # 1. Check open positions
    if not broker_executor._init_mt5():
        return True # fail safe
        
    try:
        positions = mt5.positions_get(symbol=SYMBOL)
        if positions:
            for p in positions:
                if hasattr(p, "comment") and p.comment and comment_tag in p.comment:
                    return True
    except Exception as e:
        logger.error(f"Error checking open positions: {e}")
        return True # fail safe
        
    # 2. Check history for today
    try:
        utc_to = datetime.now(timezone.utc)
        # Start of current UTC day
        utc_from = datetime(utc_to.year, utc_to.month, utc_to.day, tzinfo=timezone.utc)
        
        deals = mt5.history_deals_get(utc_from, utc_to, group=f"*{SYMBOL}*")
        if deals:
            for d in deals:
                if hasattr(d, "comment") and d.comment and comment_tag in d.comment:
                    return True
    except Exception as e:
        logger.error(f"Error checking history deals: {e}")
        return True
        
    return False

def get_daily_levels():
    """Fetch the previous day's high and low"""
    try:
        utc_to = datetime.now(timezone.utc)
        # We need yesterday's daily candle. 
        rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_D1, 0, 3)
        if rates is None or len(rates) < 2:
            return None, None
            
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        
        # The current running candle is index -1. Yesterday is index -2.
        # However, D1 rollover depends on broker. Best to map exact date.
        df['date'] = df['time'].dt.date
        current_date = utc_to.date()
        
        # Filter out today
        past_df = df[df['date'] < current_date]
        if past_df.empty:
            return None, None
            
        yesterday_row = past_df.iloc[-1]
        return yesterday_row['high'], yesterday_row['low']
        
    except Exception as e:
        logger.error(f"Error fetching daily levels: {e}")
        return None, None

def check_spread() -> float:
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        return 999.0
    return (tick.ask - tick.bid) / 0.0001

def run_daily_breakout():
    """
    EUSDI1: Daily Range Breakout
    Monitors price. If it breaks yesterday's high, buy (once per day).
    If it breaks yesterday's low, sell (once per day).
    """
    try:
        logger.info("[EUSDI1] Daily Breakout cycle starting...")
        if not broker_executor._init_mt5():
            return
            
        pdh, pdl = get_daily_levels()
        if pdh is None or pdl is None:
            return
            
        tick = mt5.symbol_info_tick(SYMBOL)
        if tick is None:
            return
            
        current_bid = tick.bid
        current_ask = tick.ask
        
        logger.info(f"[{SYMBOL}] Monitoring Daily Range | PDH: {pdh:.5f} | PDL: {pdl:.5f} | Current Bid: {current_bid:.5f}")
        
        # Check Long Breakout (Ask > PDH)
        if current_ask > pdh:
            if not _has_traded_today("LONG"):
                spread = check_spread()
                if spread <= SPREAD_MAX:
                    logger.info(f"[{SYMBOL}] EUSDI1 Breakout LONG | Ask: {current_ask} > PDH: {pdh}")
                    res = broker_executor.place_order(
                        direction="LONG",
                        lot_size=LOT_SIZE,
                        entry_price=current_ask,
                        stop_loss=current_ask - (SL_PIPS * 0.0001),
                        take_profit=current_ask + (TP_PIPS * 0.0001),
                        comment="EUSDI1_LONG"
                    )
                    if res.get("success"):
                        telegram_notifier.notify_info(
                            "EUSDI1 Bullish Breakout Triggered",
                            f"LONG {SYMBOL} @ {res.get('actual_entry', current_ask):.5f}\n"
                            f"Target: +{TP_PIPS} pips\n"
                            f"Stop: -{SL_PIPS} pips\n"
                            f"PDH Broken: {pdh:.5f}"
                        )
                else:
                    logger.warning(f"[{SYMBOL}] EUSDI1 Breakout LONG delayed due to high spread: {spread:.1f} pips")
                    
        # Check Short Breakout (Bid < PDL)
        if current_bid < pdl:
            if not _has_traded_today("SHORT"):
                spread = check_spread()
                if spread <= SPREAD_MAX:
                    logger.info(f"[{SYMBOL}] EUSDI1 Breakout SHORT | Bid: {current_bid} < PDL: {pdl}")
                    res = broker_executor.place_order(
                        direction="SHORT",
                        lot_size=LOT_SIZE,
                        entry_price=current_bid,
                        stop_loss=current_bid + (SL_PIPS * 0.0001),
                        take_profit=current_bid - (TP_PIPS * 0.0001),
                        comment="EUSDI1_SHORT"
                    )
                    if res.get("success"):
                        telegram_notifier.notify_info(
                            "EUSDI1 Bearish Breakout Triggered",
                            f"SHORT {SYMBOL} @ {res.get('actual_entry', current_bid):.5f}\n"
                            f"Target: +{TP_PIPS} pips\n"
                            f"Stop: -{SL_PIPS} pips\n"
                            f"PDL Broken: {pdl:.5f}"
                        )
                else:
                    logger.warning(f"[{SYMBOL}] EUSDI1 Breakout SHORT delayed due to high spread: {spread:.1f} pips")
                    
    except Exception as e:
        logger.error(f"Error in EUSDI1 cycle: {e}")
