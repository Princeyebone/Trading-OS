import logging
from datetime import datetime, timezone, timedelta
import pandas as pd
import MetaTrader5 as mt5

from engine import broker_executor, telegram_notifier

logger = logging.getLogger(__name__)

SYMBOL = "EURUSD"
LOT_SIZE = 0.10
SL_PIPS = 15.0
TP_PIPS = 20.0
MAX_RANGE_PIPS = 30.0

def _has_orders_today() -> bool:
    """Check if we already placed EUSDI2 orders today."""
    if not broker_executor._init_mt5():
        return True
        
    utc_to = datetime.now(timezone.utc)
    utc_from = datetime(utc_to.year, utc_to.month, utc_to.day, tzinfo=timezone.utc)
    
    # Check current pending orders
    orders = mt5.orders_get(symbol=SYMBOL)
    if orders:
        for o in orders:
            if o.comment and "EUSDI2" in o.comment:
                return True
                
    # Check open positions
    positions = mt5.positions_get(symbol=SYMBOL)
    if positions:
        for p in positions:
            if p.comment and "EUSDI2" in p.comment:
                return True
                
    # Check history deals
    deals = mt5.history_deals_get(utc_from, utc_to, group=f"*{SYMBOL}*")
    if deals:
        for d in deals:
            if d.comment and "EUSDI2" in d.comment:
                return True
                
    return False

def cancel_pending_orders():
    """Cancel any un-triggered EUSDI2 orders."""
    if not broker_executor._init_mt5():
        return
        
    orders = mt5.orders_get(symbol=SYMBOL)
    if orders:
        for o in orders:
            if o.comment and "EUSDI2" in o.comment:
                logger.info(f"[{SYMBOL}] Canceling expired EUSDI2 order #{o.ticket}")
                broker_executor.cancel_order(o.ticket)
                telegram_notifier.notify_info(
                    "EUSDI2 Orders Cancelled",
                    f"London/NY overlap ended. Pending orders for {SYMBOL} have been cancelled."
                )

def get_asian_range():
    """Fetch M15 candles from 00:00 UTC to 07:00 UTC for today."""
    utc_to = datetime.now(timezone.utc)
    
    # We just need enough candles to cover today
    rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M15, 0, 96)
    if rates is None or len(rates) == 0:
        return None, None
        
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    
    # Filter for today's date
    today_date = utc_to.date()
    df['date'] = df['time'].dt.date
    today_df = df[df['date'] == today_date]
    
    # Filter for Asian hours (00:00 to 06:45 inclusive)
    asian_df = today_df[(today_df['time'].dt.hour >= 0) & (today_df['time'].dt.hour < 7)]
    
    if asian_df.empty:
        return None, None
        
    asian_high = asian_df['high'].max()
    asian_low = asian_df['low'].min()
    return asian_high, asian_low

def run_asian_breakout():
    """
    EUSDI2: Asian Range Breakout
    Runs at 07:00 UTC. Places straddle orders if range is tight.
    Runs at 16:00 UTC. Cancels orders if untriggered.
    """
    try:
        now = datetime.now(timezone.utc)
        hour = now.hour
        minute = now.minute
        
        if not broker_executor._init_mt5():
            return
            
        # 1. Setup Phase: 07:00 to 07:05 UTC
        if hour == 7 and minute < 5:
            if _has_orders_today():
                return
                
            asian_high, asian_low = get_asian_range()
            if asian_high is None or asian_low is None:
                return
                
            range_pips = (asian_high - asian_low) * 10000
            logger.info(f"[{SYMBOL}] EUSDI2 Setup Check | Asian High: {asian_high:.5f} | Low: {asian_low:.5f} | Range: {range_pips:.1f} pips")
            
            if range_pips <= MAX_RANGE_PIPS:
                logger.info(f"[{SYMBOL}] Tight Asian Range detected. Placing EUSDI2 Straddle Orders.")
                
                # Add 2 pips buffer to High/Low
                buy_stop_price = asian_high + 0.0002
                sell_stop_price = asian_low - 0.0002
                
                # Place Straddle using updated broker_executor
                res = broker_executor.place_straddle_orders(
                    symbol=SYMBOL,
                    buy_stop_price=buy_stop_price,
                    sell_stop_price=sell_stop_price,
                    lot_size=LOT_SIZE,
                    sl_dist=SL_PIPS * 0.0001,
                    tp1_dist=TP_PIPS * 0.0001,
                    expiration_hours=9 # Valid until 16:00
                )
                
                if res.get("success"):
                    telegram_notifier.notify_info(
                        "EUSDI2 Asian Breakout Set",
                        f"Range: {range_pips:.1f} pips (Very Tight)\n"
                        f"Buy Stop @ {buy_stop_price:.5f}\n"
                        f"Sell Stop @ {sell_stop_price:.5f}\n"
                        f"Target: {TP_PIPS} pips | Stop: {SL_PIPS} pips"
                    )
            else:
                logger.info(f"[{SYMBOL}] Asian Range ({range_pips:.1f} pips) > Max ({MAX_RANGE_PIPS} pips). Skipping today.")
                
        # 2. Cleanup Phase: 16:00 UTC (End of London/NY overlap)
        if hour == 16 and minute < 5:
            cancel_pending_orders()
            
    except Exception as e:
        logger.error(f"Error in EUSDI2 cycle: {e}")
