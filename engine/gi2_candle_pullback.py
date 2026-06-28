"""
engine/gi2_candle_pullback.py — Gold Implementation 2: Strategy 1
=================================================================
2-Candle EMA200 Macro Pullback (The Hammer)

Discovered via 30-day brute-force pattern discovery engine.
Historical Performance (30 days):
  - Green Days: 20/25 (80% Daily Win Rate)
  - Total Net Pips: +6,434.3

Logic:
  - If 2 consecutive BEARISH (red) candles appear on M5 AND price is ABOVE EMA200
    → Buy the reversal (pullback into an uptrend)
  - If 2 consecutive BULLISH (green) candles appear on M5 AND price is BELOW EMA200
    → Short the reversal (pullback into a downtrend)
  - Stop Loss: 1x ATR (dynamic, volatility-adjusted)
  - Take Profit: 3x ATR (1:3 Risk/Reward)
"""

import logging
from datetime import datetime, timezone

import numpy as np
import pandas as pd

logger = logging.getLogger("engine.gi2_candle_pullback")


def _get_m5_data() -> pd.DataFrame:
    """Fetch last 100 M5 candles from MT5."""
    try:
        import MetaTrader5 as mt5

        if not mt5.initialize():
            logger.error("GI2 CandlePullback: MT5 initialization failed")
            return pd.DataFrame()

        rates = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_M5, 0, 220)
        if rates is None or len(rates) == 0:
            logger.warning("GI2 CandlePullback: No M5 data returned")
            return pd.DataFrame()

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")

        # Direction
        df["dir"] = 0
        df.loc[df["close"] > df["open"], "dir"] = 1
        df.loc[df["close"] < df["open"], "dir"] = -1

        # EMA 200 (macro trend filter)
        df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()

        # ATR (dynamic stop loss)
        hl = df["high"] - df["low"]
        hc = np.abs(df["high"] - df["close"].shift())
        lc = np.abs(df["low"] - df["close"].shift())
        df["atr"] = pd.concat([hl, hc, lc], axis=1).max(axis=1).rolling(14).mean()

        return df

    except Exception as e:
        logger.exception(f"GI2 CandlePullback: data fetch error: {e}")
        return pd.DataFrame()


def _is_already_in_trade() -> bool:
    """Check if GI2 CandlePullback already has an open trade."""
    try:
        import MetaTrader5 as mt5
        mt5.initialize()
        positions = mt5.positions_get(symbol="XAUUSD")
        if not positions:
            return False
        return any(p.comment == "GI2-PULLBACK" for p in positions)
    except Exception:
        return False


def run_gi2_candle_pullback_cycle():
    """
    Main cycle — runs every 5 minutes.
    Detects 2-candle pullback setups and executes if confirmed.
    """
    logger.info("[GI2-PULLBACK] Cycle starting...")

    # Avoid stacking positions
    if _is_already_in_trade():
        logger.info("[GI2-PULLBACK] Already in trade — skipping.")
        return

    df = _get_m5_data()
    if df.empty or len(df) < 205:
        logger.warning("[GI2-PULLBACK] Insufficient data — skipping.")
        return

    # We look at the last 3 confirmed candles (i-1, i-2 are complete; i is forming)
    last = df.iloc[-2]   # most recently closed candle
    prev = df.iloc[-3]   # candle before that

    last_dir = last["dir"]
    prev_dir = prev["dir"]
    ema200 = last["ema200"]
    close = last["close"]
    atr = last["atr"]

    if np.isnan(atr) or np.isnan(ema200) or atr <= 0:
        logger.info("[GI2-PULLBACK] ATR/EMA not ready — skipping.")
        return

    sl_dist = atr  # 1x ATR stop loss in price units
    tp_dist = atr * 3.0  # 1:3 RR

    direction = None

    # LONG: 2 consecutive bearish candles + price above EMA200
    if last_dir == -1 and prev_dir == -1 and close > ema200:
        direction = "LONG"
        entry = close
        sl = entry - sl_dist
        tp = entry + tp_dist

    # SHORT: 2 consecutive bullish candles + price below EMA200
    elif last_dir == 1 and prev_dir == 1 and close < ema200:
        direction = "SHORT"
        entry = close
        sl = entry + sl_dist
        tp = entry - tp_dist

    if not direction:
        logger.info(f"[GI2-PULLBACK] No setup — last_dir={last_dir}, prev_dir={prev_dir}, price={'above' if close > ema200 else 'below'} EMA200")
        return

    sl_pips = sl_dist * 10
    tp_pips = tp_dist * 10

    logger.info(
        f"[GI2-PULLBACK] SETUP: {direction} @ {entry:.2f} | "
        f"SL={sl:.2f} ({sl_pips:.1f}p) | TP={tp:.2f} ({tp_pips:.1f}p)"
    )

    # Execute
    try:
        from engine import broker_executor, telegram_notifier

        result = broker_executor.place_order(
            direction=direction,
            lot_size=0.05,
            entry_price=entry,
            stop_loss=sl,
            take_profit=tp,
            comment="GI2-PULLBACK",
        )

        if result["success"]:
            logger.info(f"[GI2-PULLBACK] Order placed: {result['order_id']}")
            telegram_notifier.notify_info(
                "GI2 Candle Pullback",
                f"{'LONG' if direction == 'LONG' else 'SHORT'} XAU/USD\n"
                f"Entry: {entry:.2f} | SL: {sl:.2f} ({sl_pips:.1f}p) | TP: {tp:.2f} ({tp_pips:.1f}p)\n"
                f"2-Candle EMA200 Macro Pullback (1:3 RR)",
            )
        else:
            logger.error(f"[GI2-PULLBACK] Order failed: {result['error']}")

    except Exception as e:
        logger.exception(f"[GI2-PULLBACK] Execution error: {e}")
