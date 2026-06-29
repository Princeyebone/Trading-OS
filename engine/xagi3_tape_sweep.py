"""
engine/xagi3_tape_sweep.py — Gold Tape Reading Liquidity Sweep Engine
XAGI3: Institutional Liquidity Sweep Scalper for XAUUSD

Strategy:
- Builds rolling liquidity levels from swing highs/lows (equal highs = resistance, equal lows = support)
- Waits for a Liquidity Sweep candle: price violently pierces a level, then CLOSES back on the correct side
- Entry: on close of sweep candle
- Stop Loss: 0.30 pts below the wick tip (structural SL — very tight, ~$10–$15 per trade)
- Take Profit: 3x SL distance (1:3 Risk-to-Reward)
- Session Filter: London/NY only (07:00–17:00 MT5 server time)
- HTF Filter: H1 trend must align with sweep direction
- Cooldown: same level cannot trigger again for 10 bars
- Max concurrent XAGI3 trades: 1

Magic Number: 202700
"""

import logging
import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime, timezone, timedelta
from sqlmodel import Session, select

from engine import broker_executor, telegram_notifier
from engine.db import get_session
from app.models.signals import Signal
from app.models.trades import Trade

logger = logging.getLogger("engine.xagi3_tape_sweep")

SYMBOL       = "XAUUSD"
MAGIC_NUMBER = 202700
LOT_SIZE     = 0.05

# Session filter: MT5 server time (they're typically on UTC+3 EET)
# London open is ~07:00, NY close ~21:00 on MT5 servers. 
# We use a conservative 07:00–17:00 window (London + early NY).
SESSION_START = 7   # 07:00 MT5 server time
SESSION_END   = 17  # 17:00 MT5 server time

LOOKBACK_BARS    = 200   # M1 bars to build liquidity levels from
TP_MULTIPLIER    = 3.0   # 1:3 RR
MIN_WICK_PCT     = 0.55  # Sweep wick must be >= 55% of candle body
SWEEP_BUFFER     = 0.20  # Price must pierce level by at least 0.20 pts
SL_BUFFER        = 0.30  # SL placed 0.30 pts beyond the wick tip
COOLDOWN_BARS    = 10    # Minimum bars before same level can trigger again
LEVEL_TOLERANCE  = 0.80  # Points: two swing points within this range = same level
SWING_LOOKBACK   = 3     # Bars each side to confirm a swing high/low

# In-process cooldown tracking
_level_cooldown: dict = {}  # {rounded_level: bar_index}
_bar_counter: int = 0


def _fetch_m1_data(count: int = LOOKBACK_BARS + 50) -> pd.DataFrame | None:
    """Fetch recent M1 candles from MT5."""
    rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 0, count)
    if rates is None or len(rates) == 0:
        return None
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df.set_index('time', inplace=True)
    return df


def _fetch_h1_data(count: int = 20) -> pd.DataFrame | None:
    """Fetch recent H1 candles for trend context."""
    rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_H1, 0, count)
    if rates is None or len(rates) == 0:
        return None
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df.set_index('time', inplace=True)
    return df


def _get_h1_trend(h1_df: pd.DataFrame) -> str:
    """Determine H1 trend using 3-bar comparison."""
    if h1_df is None or len(h1_df) < 5:
        return "UNKNOWN"
    closes = h1_df['close'].values
    if closes[-1] > closes[-3]:
        return "BULLISH"
    elif closes[-1] < closes[-3]:
        return "BEARISH"
    return "SIDEWAYS"


def _find_swing_points(df: pd.DataFrame) -> tuple[dict, dict]:
    """Find swing highs and lows in the data."""
    highs_map, lows_map = {}, {}
    highs = df['high'].values
    lows  = df['low'].values
    lb = SWING_LOOKBACK

    for i in range(lb, len(df) - lb):
        if all(highs[i] >= highs[i-k] for k in range(1, lb+1)) and \
           all(highs[i] >= highs[i+k] for k in range(1, lb+1)):
            highs_map[df.index[i]] = highs[i]
        if all(lows[i] <= lows[i-k] for k in range(1, lb+1)) and \
           all(lows[i] <= lows[i+k] for k in range(1, lb+1)):
            lows_map[df.index[i]] = lows[i]

    return highs_map, lows_map


def _build_liquidity_clusters(highs_map: dict, lows_map: dict) -> list[tuple]:
    """
    Group nearby swing points into liquidity clusters.
    Returns list of (level_price, 'RESISTANCE'|'SUPPORT', num_touches)
    """
    clusters = []
    seen = set()

    for ts1, h1 in highs_map.items():
        if ts1 in seen: continue
        group = [h1]
        for ts2, h2 in highs_map.items():
            if ts1 != ts2 and ts2 not in seen and abs(h1 - h2) <= LEVEL_TOLERANCE:
                group.append(h2)
                seen.add(ts2)
        if len(group) >= 2:
            clusters.append((round(sum(group)/len(group), 2), 'RESISTANCE', len(group)))
        seen.add(ts1)

    seen = set()
    for ts1, l1 in lows_map.items():
        if ts1 in seen: continue
        group = [l1]
        for ts2, l2 in lows_map.items():
            if ts1 != ts2 and ts2 not in seen and abs(l1 - l2) <= LEVEL_TOLERANCE:
                group.append(l2)
                seen.add(ts2)
        if len(group) >= 2:
            clusters.append((round(sum(group)/len(group), 2), 'SUPPORT', len(group)))
        seen.add(ts1)

    return sorted(clusters, key=lambda x: -x[2])


def _detect_sweep_signal(candle: pd.Series, level: float, level_type: str, h1_trend: str) -> dict | None:
    """
    Detect a Liquidity Sweep signal on the given candle.
    Returns signal dict or None.
    """
    candle_range = candle['high'] - candle['low']
    if candle_range < 0.5:
        return None  # ignore doji / micro-candles

    if level_type == 'SUPPORT':
        # Only take BULLISH sweeps when H1 is not actively bearish
        if h1_trend == 'BEARISH':
            return None
        swept_below  = candle['low'] < (level - SWEEP_BUFFER)
        closed_above = candle['close'] > level
        lower_wick   = min(candle['open'], candle['close']) - candle['low']
        wick_pct     = lower_wick / candle_range
        if swept_below and closed_above and wick_pct >= MIN_WICK_PCT:
            entry    = round(candle['close'], 2)
            sl       = round(candle['low'] - SL_BUFFER, 2)
            sl_dist  = round(entry - sl, 2)
            tp       = round(entry + sl_dist * TP_MULTIPLIER, 2)
            return {
                'direction': 'BULLISH',
                'entry': entry, 'sl': sl, 'tp': tp,
                'sl_dist': sl_dist,
                'level': level, 'level_type': level_type,
                'wick_pct': round(wick_pct * 100, 1),
            }

    elif level_type == 'RESISTANCE':
        # Only take BEARISH sweeps when H1 is not actively bullish
        if h1_trend == 'BULLISH':
            return None
        swept_above  = candle['high'] > (level + SWEEP_BUFFER)
        closed_below = candle['close'] < level
        upper_wick   = candle['high'] - max(candle['open'], candle['close'])
        wick_pct     = upper_wick / candle_range
        if swept_above and closed_below and wick_pct >= MIN_WICK_PCT:
            entry    = round(candle['close'], 2)
            sl       = round(candle['high'] + SL_BUFFER, 2)
            sl_dist  = round(sl - entry, 2)
            tp       = round(entry - sl_dist * TP_MULTIPLIER, 2)
            return {
                'direction': 'BEARISH',
                'entry': entry, 'sl': sl, 'tp': tp,
                'sl_dist': sl_dist,
                'level': level, 'level_type': level_type,
                'wick_pct': round(wick_pct * 100, 1),
            }

    return None


def _has_active_xagi3_trade() -> bool:
    """Check if there's already an open XAGI3 trade in MT5."""
    positions = mt5.positions_get(symbol=SYMBOL)
    if positions:
        for p in positions:
            if p.magic == MAGIC_NUMBER:
                return True
    return False


def _execute_trade(signal: dict) -> bool:
    """Place the XAGI3 market order and log it to the DB."""
    direction_mt5 = "LONG" if signal['direction'] == 'BULLISH' else "SHORT"
    logger.info(
        f"[XAGI3] Placing {direction_mt5} | Entry ~{signal['entry']:.2f} | "
        f"SL: {signal['sl']:.2f} ({signal['sl_dist']:.1f} pts) | TP: {signal['tp']:.2f} | "
        f"Level: {signal['level']:.2f} | Wick: {signal['wick_pct']}%"
    )

    result = broker_executor.place_order(
        direction=direction_mt5,
        lot_size=LOT_SIZE,
        entry_price=signal['entry'],
        stop_loss=signal['sl'],
        take_profit=signal['tp'],
        magic=MAGIC_NUMBER,
        comment="XAGI3-TapeSweep",
        symbol=SYMBOL,
    )

    if not result.get("success"):
        logger.error(f"[XAGI3] Order failed: {result.get('error')}")
        return False

    session_db = get_session()
    try:
        db_signal = Signal(
            timeframe="M1",
            session="XAGI3",
            verdict="TRADE",
            direction=direction_mt5,
            confidence=88,
            skip_reason=None,
            price_at_signal=signal['entry'],
            prompt_version=0,
        )
        session_db.add(db_signal)
        session_db.flush()

        trade = Trade(
            signal_id=db_signal.id,
            direction=direction_mt5,
            planned_entry=signal['entry'],
            actual_entry=result.get("actual_entry", signal['entry']),
            slippage_pips=result.get("slippage_pips", 0.0),
            stop_loss=signal['sl'],
            take_profit_1=signal['tp'],
            take_profit_2=0.0,
            lot_size=LOT_SIZE,
            planned_rr=TP_MULTIPLIER,
            broker_order_id=result.get("order_id"),
            status="OPEN",
        )
        session_db.add(trade)
        session_db.commit()
        logger.info(f"[XAGI3] Trade #{trade.id} logged to DB.")
    except Exception as e:
        logger.error(f"[XAGI3] DB logging failed: {e}")
    finally:
        session_db.close()

    telegram_notifier.notify_trade_executed(
        direction=direction_mt5,
        entry=result.get("actual_entry", signal['entry']),
        stop_loss=signal['sl'],
        tp1=signal['tp'],
        tp2=0.0,
        lot_size=LOT_SIZE,
        confidence=88,
        order_id=result.get("order_id"),
        reasoning=(
            f"XAGI3 Liquidity Sweep | Level {signal['level']:.2f} ({signal['level_type']}) | "
            f"Wick {signal['wick_pct']}% | SL {signal['sl_dist']:.1f} pts | RR 1:{TP_MULTIPLIER:.0f}"
        )
    )
    return True


def run_xagi3_cycle():
    """
    Main entry point — called by scheduler every minute.
    Scans for Liquidity Sweep signals and executes if conditions are met.
    """
    global _bar_counter

    logger.info("[XAGI3] Cycle starting...")

    if not broker_executor._init_mt5():
        logger.warning("[XAGI3] MT5 not initialized, skipping.")
        return

    # ── Session Gate ──
    server_info = mt5.symbol_info(SYMBOL)
    if server_info:
        server_dt = datetime.fromtimestamp(server_info.time)
        hour = server_dt.hour
        if not (SESSION_START <= hour < SESSION_END):
            logger.info(f"[XAGI3] Outside trading session ({hour:02d}:00 MT5 time). Sleeping.")
            return
    
    # ── Position Gate ──
    if _has_active_xagi3_trade():
        logger.info("[XAGI3] Active XAGI3 trade open. Skipping scan.")
        return

    # ── Fetch Data ──
    m1_df = _fetch_m1_data()
    if m1_df is None or len(m1_df) < LOOKBACK_BARS + 5:
        logger.warning("[XAGI3] Insufficient M1 data.")
        return

    h1_df = _fetch_h1_data()
    h1_trend = _get_h1_trend(h1_df)

    _bar_counter += 1

    # ── Build Liquidity Levels ──
    lookback_slice = m1_df.iloc[-(LOOKBACK_BARS + 1): -1]  # exclude current forming bar
    highs_map, lows_map = _find_swing_points(lookback_slice)
    clusters = _build_liquidity_clusters(highs_map, lows_map)

    if not clusters:
        logger.info("[XAGI3] No liquidity clusters found. Waiting...")
        return

    # ── Get Latest Completed Candle ──
    latest = m1_df.iloc[-2]  # last COMPLETED M1 bar (-1 is forming)
    ts = m1_df.index[-2]

    logger.info(
        f"[XAGI3] Scanning | H1 Trend: {h1_trend} | Price: {latest['close']:.2f} | "
        f"Clusters: {len(clusters)} | Bar: {ts.strftime('%H:%M')}"
    )

    # ── Scan Clusters for Sweep ──
    for level_price, level_type, touches in clusters:
        level_key = round(level_price, 0)
        last_trigger = _level_cooldown.get(level_key, -COOLDOWN_BARS - 1)
        if _bar_counter - last_trigger < COOLDOWN_BARS:
            continue

        signal = _detect_sweep_signal(latest, level_price, level_type, h1_trend)
        if signal is None:
            continue

        logger.info(
            f"[XAGI3] SWEEP DETECTED on {level_type} @ {level_price:.2f} | "
            f"Direction: {signal['direction']} | Wick: {signal['wick_pct']}%"
        )
        _level_cooldown[level_key] = _bar_counter

        success = _execute_trade(signal)
        if success:
            logger.info(f"[XAGI3] Trade executed successfully!")
        break  # One trade per cycle

    else:
        logger.info("[XAGI3] No sweep signals this bar. Monitoring...")
