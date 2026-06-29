import logging
from datetime import datetime, timezone
import pandas as pd
import numpy as np
import MetaTrader5 as mt5

from engine import broker_executor, telegram_notifier

logger = logging.getLogger(__name__)

SYMBOL = "XAUUSD"
LOT_SIZE = 0.05
DEAD_ZONE_START = 21
DEAD_ZONE_END = 0

def is_dead_zone(hour: int) -> bool:
    """Returns True if hour is between 21:00 and 00:00 UTC"""
    return hour >= DEAD_ZONE_START or hour == DEAD_ZONE_END

def _has_open_position(comment_prefix: str) -> bool:
    """Check if we already have an open position for this strategy."""
    positions = broker_executor.get_open_positions()
    # broker_executor.get_open_positions returns dicts, wait, no, it returns dicts without comments?
    # Let's query mt5 directly since we import it
    try:
        raw_positions = mt5.positions_get(symbol=SYMBOL)
        if raw_positions:
            for p in raw_positions:
                # MT5 position objects have a comment field
                if hasattr(p, "comment") and p.comment and comment_prefix in p.comment:
                    return True
    except Exception as e:
        logger.error(f"Error checking open positions: {e}")
    return False

def get_recent_m5_data(days=1):
    utc_to = datetime.now(timezone.utc)
    utc_from = utc_to - pd.Timedelta(days=days)
    rates = mt5.copy_rates_range(SYMBOL, mt5.TIMEFRAME_M5, utc_from, utc_to)
    if rates is None or len(rates) == 0:
        return pd.DataFrame()
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df['date'] = df['time'].dt.date
    return df

def get_recent_m15_data(candles=30):
    rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M15, 0, candles)
    if rates is None or len(rates) == 0:
        return pd.DataFrame()
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    return df

def run_vwap_reversion_cycle():
    """
    M5 VWAP Reversion
    Trades back to the daily VWAP if price extends more than $8 from it.
    """
    try:
        logger.info("[GI3-VWAP] Cycle starting...")
        now = datetime.now(timezone.utc)
        if is_dead_zone(now.hour):
            return

        if _has_open_position("GI3_VWAP"):
            return

        df = get_recent_m5_data(days=1)
        if df.empty or len(df) < 5:
            return

        # Calculate daily cumulative VWAP
        df['typical_price'] = (df['high'] + df['low'] + df['close']) / 3
        df['vol_price'] = df['typical_price'] * df['tick_volume']
        
        vwap_vals = []
        for date, group in df.groupby('date'):
            cum_vp = group['vol_price'].cumsum()
            cum_v = group['tick_volume'].cumsum()
            # Avoid division by zero
            group_vwap = np.where(cum_v > 0, cum_vp / cum_v, group['typical_price'])
            vwap_vals.extend(group_vwap)
            
        df['vwap'] = vwap_vals

        c = df['close'].iloc[-1]
        v = df['vwap'].iloc[-1]
        if np.isnan(v):
            return

        direction = None
        sl = 0.0
        tp = 0.0

        if c - v > 8.0:
            # Overextended up, fade short
            direction = "SELL"
            sl = c + 4.0
            tp = v
        elif v - c > 8.0:
            # Overextended down, fade long
            direction = "BUY"
            sl = c - 4.0
            tp = v

        if direction:
            logger.info(f"[{SYMBOL}] GI3 VWAP Trigger: {direction} | Price: {c:.2f} | VWAP: {v:.2f}")
            res = broker_executor.place_order(
                direction=direction,
                lot_size=LOT_SIZE,
                entry_price=c,
                stop_loss=sl,
                take_profit=tp,
                comment="GI3_VWAP"
            )
            if res.get("success"):
                telegram_notifier.notify_info(
                    "GI3 VWAP Reversion Trigger",
                    f"{direction} {SYMBOL} @ {c:.2f}\nTarget VWAP: {v:.2f}\nStop Loss: {sl:.2f}"
                )
            
    except Exception as e:
        logger.error(f"Error in GI3 VWAP cycle: {e}")

def run_rsi_divergence_cycle():
    """
    M15 RSI Divergence
    Checks for structural trend exhaustion using RSI(14) over the last 15 candles.
    """
    try:
        logger.info("[GI3-RSI-DIV] Cycle starting...")
        now = datetime.now(timezone.utc)
        if is_dead_zone(now.hour):
            return

        if _has_open_position("GI3_RSI_DIV"):
            return

        df = get_recent_m15_data(candles=30)
        if len(df) < 20:
            return

        # Calculate RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))

        lows = df['low'].values
        highs = df['high'].values
        rsis = df['rsi'].values
        closes = df['close'].values

        curr_l = lows[-1]
        curr_h = highs[-1]
        curr_c = closes[-1]
        curr_rsi = rsis[-1]

        if np.isnan(curr_rsi):
            return

        direction = None
        sl = 0.0
        tp = 0.0

        # Bullish Divergence
        past_l = np.min(lows[-16:-2])
        past_l_idx = np.argmin(lows[-16:-2]) + (len(lows)-16)
        past_l_rsi = rsis[past_l_idx]

        if not np.isnan(past_l_rsi) and curr_l < past_l and curr_rsi > past_l_rsi and curr_rsi < 40:
            direction = "BUY"
            sl = curr_c - 3.0
            tp = curr_c + 6.0

        # Bearish Divergence
        past_h = np.max(highs[-16:-2])
        past_h_idx = np.argmax(highs[-16:-2]) + (len(highs)-16)
        past_h_rsi = rsis[past_h_idx]

        if direction is None and not np.isnan(past_h_rsi) and curr_h > past_h and curr_rsi < past_h_rsi and curr_rsi > 60:
            direction = "SELL"
            sl = curr_c + 3.0
            tp = curr_c - 6.0

        if direction:
            logger.info(f"[{SYMBOL}] GI3 RSI Div Trigger: {direction} | Price: {curr_c:.2f} | RSI: {curr_rsi:.1f}")
            res = broker_executor.place_order(
                direction=direction,
                lot_size=LOT_SIZE,
                entry_price=curr_c,
                stop_loss=sl,
                take_profit=tp,
                comment="GI3_RSI_DIV"
            )
            if res.get("success"):
                telegram_notifier.notify_info(
                    "GI3 RSI Divergence Trigger",
                    f"{direction} {SYMBOL} @ {curr_c:.2f}\nRSI: {curr_rsi:.1f}\nStop Loss: {sl:.2f}"
                )

    except Exception as e:
        logger.error(f"Error in GI3 RSI Divergence cycle: {e}")
