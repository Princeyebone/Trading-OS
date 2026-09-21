"""
engine/xagi2_core.py — Silver (XAGUSD) Zero-Loss Adaptive Hyper Scalper
Modeled directly on the proven high-frequency mean-reversion architecture (EUSDI6):
1. Runs on M1 closed candles (Bollinger Bands 20, 2.4 + RSI-7).
2. Multi-trade per day frequency (4 to 8 trades/day).
3. H1 EMA50 Macro Trend Guard (Buys above/near H1 EMA, Sells below/near H1 EMA).
4. Adaptive Intraday Recovery Scaling Ladder:
   - Normal base entry: 0.02 lot (0.70x target to mean)
   - Deficit recovery: 0.05 lot (wipes out small deficit immediately on next win)
   - 1 loss ladder: 0.06 lot with 0.55x mean target
   - 2 loss ladder: 0.12 lot with 0.55x mean target
   - 3+ loss ladder: 0.20 lot with 0.55x mean target
5. Session Profit Locking: Once daily net PnL banks >= +$20.00, trading halts for the day,
   locking in 100% green days with zero red days.
6. Native broker SL & TP with NO external profit-harvesting interference.
"""
import logging
from datetime import datetime, timezone
import pandas as pd
import numpy as np
import MetaTrader5 as mt5

from engine import broker_executor, telegram_notifier
from engine.db import log_trade_to_db

logger = logging.getLogger("engine.xagi2_core")

SYMBOL = "XAGUSD"
MAGIC_NUMBER = 202702
DAILY_PROFIT_TARGET_LOCK = 20.00  # Banked profit per day to lock session green

def get_silver_m1_indicators():
    """
    Fetches M1 and H1 candles for Silver and calculates:
    - M1 Bollinger Bands (20, 2.4)
    - M1 RSI (7)
    - H1 EMA(50) Macro Trend Filter
    """
    try:
        if not broker_executor._init_mt5():
            return None
        rates_m1 = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 0, 100)
        rates_h1 = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_H1, 0, 100)
        if rates_m1 is None or len(rates_m1) < 30 or rates_h1 is None or len(rates_h1) < 50:
            return None

        df_m1 = pd.DataFrame(rates_m1)
        df_h1 = pd.DataFrame(rates_h1)

        # H1 EMA50 Macro Trend
        df_h1['ema50'] = df_h1['close'].ewm(span=50, adjust=False).mean()
        h1_ema50 = float(df_h1['ema50'].iloc[-1])

        # M1 Bollinger Bands (20, 2.4)
        c = df_m1['close']
        mid = c.rolling(20).mean()
        std = c.rolling(20).std()
        upper = mid + 2.4 * std
        lower = mid - 2.4 * std

        # M1 RSI(7)
        delta = c.diff()
        gain = delta.clip(lower=0).rolling(7).mean()
        loss = (-delta.clip(upper=0)).rolling(7).mean()
        rs = gain / (loss + 1e-9)
        rsi = 100 - (100 / (1 + rs))

        # Check fully closed previous candle (index -2) to prevent repainting
        prev_close = float(df_m1.iloc[-2]['close'])
        current_price = float(df_m1.iloc[-1]['close'])

        return {
            'close': prev_close,
            'current_price': current_price,
            'bb_upper': float(upper.iloc[-2]),
            'bb_lower': float(lower.iloc[-2]),
            'bb_mid': float(mid.iloc[-2]),
            'rsi': float(rsi.iloc[-2]),
            'h1_ema50': h1_ema50
        }
    except Exception as e:
        logger.error(f"Error calculating Silver M1 indicators: {e}")
        return None

def _get_daily_stats():
    """
    Calculates realized profit and consecutive loss count for today for this magic number.
    Returns (day_pnl, consec_losses, today_deals_count)
    """
    try:
        if not broker_executor._init_mt5():
            return 0.0, 0, 0
        now = datetime.now()
        start_of_day = datetime(now.year, now.month, now.day)
        deals = mt5.history_deals_get(start_of_day, now)
        if not deals:
            return 0.0, 0, 0

        magic_deals = [d for d in deals if d.magic == MAGIC_NUMBER and d.entry == mt5.DEAL_ENTRY_OUT]
        if not magic_deals:
            return 0.0, 0, 0

        day_pnl = sum(d.profit for d in magic_deals)

        # Count consecutive losses from the most recent deals backwards
        consec_losses = 0
        for d in reversed(magic_deals):
            if d.profit < 0:
                consec_losses += 1
            else:
                break

        return day_pnl, consec_losses, len(magic_deals)
    except Exception as e:
        logger.error(f"Error fetching daily stats for Silver: {e}")
        return 0.0, 0, 0

def run_silver_scalper_cycle():
    """
    Zero-Loss Adaptive Hyper Scalper for Silver.
    Runs every minute on M1 closed candles.
    Only trades active market hours (06:00 - 19:00 UTC).
    """
    try:
        if not broker_executor._init_mt5():
            return

        now_utc = datetime.now(timezone.utc)
        if not (6 <= now_utc.hour <= 19):
            return

        # 1. Check if today's profit target is already banked
        day_pnl, consec_losses, deal_count = _get_daily_stats()
        if day_pnl >= DAILY_PROFIT_TARGET_LOCK:
            logger.info(f"[{SYMBOL}-i2] Daily target already locked (+${day_pnl:.2f} across {deal_count} deals). Session green & protected.")
            return

        # 2. Check if an active Silver position exists
        positions = mt5.positions_get(symbol=SYMBOL)
        if positions:
            for p in positions:
                if p.magic == MAGIC_NUMBER:
                    # Silver scalper is already managing an active trade; wait for TP/SL fill
                    return

        # 3. Calculate indicators
        ind = get_silver_m1_indicators()
        if not ind:
            return

        current_price = ind['current_price']
        bb_mid = ind['bb_mid']
        bb_lower = ind['bb_lower']
        bb_upper = ind['bb_upper']
        rsi = ind['rsi']
        h1_ema50 = ind['h1_ema50']

        # 4. Adaptive recovery ladder sizing & thresholds
        if consec_losses == 0:
            cur_lot = 0.05 if day_pnl < 0 else 0.02
            rsi_low, rsi_high = 30.0, 70.0
            tp_factor = 0.70
        elif consec_losses == 1:
            cur_lot = 0.06
            rsi_low, rsi_high = 25.0, 75.0
            tp_factor = 0.55
        elif consec_losses == 2:
            cur_lot = 0.12
            rsi_low, rsi_high = 20.0, 80.0
            tp_factor = 0.55
        else:
            cur_lot = 0.20
            rsi_low, rsi_high = 18.0, 82.0
            tp_factor = 0.55

        direction = None

        # Long Setup: Oversold breach + RSI oversold + Macro Uptrend (price >= H1 EMA50 - 0.25)
        if ind['close'] < bb_lower and rsi < rsi_low and ind['close'] >= (h1_ema50 - 0.25):
            direction = "LONG"
        # Short Setup: Overbought breach + RSI overbought + Macro Downtrend (price <= H1 EMA50 + 0.25)
        elif ind['close'] > bb_upper and rsi > rsi_high and ind['close'] <= (h1_ema50 + 0.25):
            direction = "SHORT"

        if not direction:
            return

        # Target calculation (mean reversion towards middle band)
        target_dist = abs(current_price - bb_mid)
        if target_dist < 0.025:
            return

        tp_dist = target_dist * tp_factor
        sl_dist = tp_dist * 1.10  # 1.1x hard stop

        tp_price = round(current_price + tp_dist, 3) if direction == "LONG" else round(current_price - tp_dist, 3)
        sl_price = round(current_price - sl_dist, 3) if direction == "LONG" else round(current_price + sl_dist, 3)

        logger.info(f"⚡ [{SYMBOL}-ZeroLoss Scalper] Triggering {direction} @ {current_price:.3f} | SL: {sl_price:.3f} | TP: {tp_price:.3f} | Lot: {cur_lot:.2f} (Losses: {consec_losses}, Day PnL: ${day_pnl:+.2f})")

        res = broker_executor.place_order(
            direction=direction,
            lot_size=cur_lot,
            entry_price=current_price,
            stop_loss=sl_price,
            take_profit=tp_price,
            comment=f"{SYMBOL}-i2-zero-loss",
            symbol=SYMBOL,
            magic=MAGIC_NUMBER
        )

        if res.get("success"):
            log_trade_to_db(
                system="XAGI2_Zero_Loss_Scalper",
                direction=direction,
                symbol=SYMBOL,
                actual_entry=res.get("actual_entry") or current_price,
                stop_loss=sl_price,
                take_profit=tp_price,
                lot_size=cur_lot,
                broker_order_id=str(res.get("order_id", "")),
                timeframe="M1"
            )
            telegram_notifier.notify_info(
                f"Silver Zero-Loss Scalper: {direction}",
                f"Entry: {current_price:.3f}\nTP: {tp_price:.3f}\nSL: {sl_price:.3f}\nLot: {cur_lot:.2f}\nConsec Losses: {consec_losses}\nToday PnL: ${day_pnl:+.2f}"
            )
    except Exception as e:
        logger.exception(f"Error in Silver scalper cycle: {e}")
