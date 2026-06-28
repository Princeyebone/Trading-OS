"""
engine/gi3_eurusd.py — Gold Implementation 3: EURUSD Portfolio
=============================================================
Three time-of-day strategies discovered via 30-day brute-force
pattern mining on EURUSD.

30-Day Historical Performance (combined portfolio):
  - Green Days: 15/25 (60% Daily Win Rate)
  - Total Net Pips: +382.9
  - Avg/Day: +15.3 pips

Strategies:
  A. Short @19:00 GMT, Exit @23:00 GMT  (79.2% daily win rate)
  B. Short @16:00 GMT, Exit @20:00 GMT  (72.0% daily win rate, highest pips)
  C. Long  @00:00 GMT, Exit @01:00 GMT  (76.0% daily win rate)
"""

import logging
from datetime import datetime, timezone

logger = logging.getLogger("engine.gi3_eurusd")

SYMBOL   = "EURUSD"
LOT_SIZE = 0.05

# Track one trade per strategy per day
_trades_today: dict[str, str] = {}  # strategy_id -> date string


def _today_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _already_traded(strategy_id: str) -> bool:
    return _trades_today.get(strategy_id) == _today_str()


def _mark_traded(strategy_id: str):
    _trades_today[strategy_id] = _today_str()


def _get_live_price(direction: str) -> float | None:
    try:
        import MetaTrader5 as mt5
        mt5.initialize()
        tick = mt5.symbol_info_tick(SYMBOL)
        if tick is None:
            return None
        return tick.ask if direction == "LONG" else tick.bid
    except Exception as e:
        logger.error(f"[GI3-EURUSD] tick error: {e}")
        return None


def _open_trade(strategy_id: str, direction: str, sl_pips: float, tp_pips: float, comment: str):
    """Open a market order on EURUSD."""
    if _already_traded(strategy_id):
        logger.info(f"[GI3-EURUSD] {strategy_id} already traded today — skipping.")
        return

    live_price = _get_live_price(direction)
    if live_price is None:
        logger.error(f"[GI3-EURUSD] {strategy_id}: Cannot get price — aborting.")
        return

    # EURUSD pip = 0.0001
    sl_dist = sl_pips * 0.0001
    tp_dist = tp_pips * 0.0001

    sl = (live_price - sl_dist) if direction == "LONG" else (live_price + sl_dist)
    tp = 0.0  # time-based exit, no hard TP

    logger.info(f"[GI3-EURUSD] {strategy_id}: {direction} @ {live_price:.5f} | SL={sl:.5f} ({sl_pips}p)")

    try:
        from engine import broker_executor, telegram_notifier
        result = broker_executor.place_order(
            direction=direction,
            lot_size=LOT_SIZE,
            entry_price=live_price,
            stop_loss=sl,
            take_profit=tp,
            comment=comment,
        )
        if result["success"]:
            _mark_traded(strategy_id)
            logger.info(f"[GI3-EURUSD] {strategy_id} opened: {result['order_id']}")
            telegram_notifier.notify_info(
                f"GI2 EURUSD — {comment}",
                f"{'LONG' if direction == 'LONG' else 'SHORT'} {SYMBOL} @ {live_price:.5f}\n"
                f"Emergency SL: {sl:.5f} ({sl_pips}p) | Time-based exit",
            )
        else:
            logger.error(f"[GI3-EURUSD] {strategy_id} failed: {result['error']}")
    except Exception as e:
        logger.exception(f"[GI3-EURUSD] {strategy_id} execution error: {e}")


def _close_trades(comment: str, strategy_label: str):
    """Close all open positions matching the given comment."""
    try:
        import MetaTrader5 as mt5
        from engine import telegram_notifier
        mt5.initialize()

        positions = mt5.positions_get(symbol=SYMBOL)
        positions = [p for p in positions if p.comment == comment] if positions else []

        if not positions:
            logger.info(f"[GI3-EURUSD] {strategy_label}: No open positions to close.")
            return

        for pos in positions:
            tick = mt5.symbol_info_tick(SYMBOL)
            close_price = tick.ask if pos.type == 1 else tick.bid

            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": SYMBOL,
                "volume": pos.volume,
                "type": mt5.ORDER_TYPE_BUY if pos.type == 1 else mt5.ORDER_TYPE_SELL,
                "position": pos.ticket,
                "price": close_price,
                "deviation": 20,
                "magic": 30001,
                "comment": f"{comment}-EXIT",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }

            result = mt5.order_send(request)
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                pips = ((pos.price_open - close_price) if pos.type == 1 else (close_price - pos.price_open)) / 0.0001 * (-1 if pos.type == 0 else 1)
                # For short (type=1): profit = open - close. For long (type=0): profit = close - open.
                if pos.type == 0:
                    pips = (close_price - pos.price_open) / 0.0001
                else:
                    pips = (pos.price_open - close_price) / 0.0001

                logger.info(f"[GI3-EURUSD] {strategy_label} closed @ {close_price:.5f} | P&L: {pips:+.1f}p")
                telegram_notifier.notify_info(
                    f"GI2 EURUSD — {strategy_label} CLOSED",
                    f"Closed @ {close_price:.5f} | Entry: {pos.price_open:.5f}\n"
                    f"P&L: {pips:+.1f} pips | Time-based exit",
                )
            else:
                err = result.retcode if result else "N/A"
                logger.error(f"[GI3-EURUSD] {strategy_label} close failed: retcode={err}")

    except Exception as e:
        logger.exception(f"[GI3-EURUSD] {strategy_label} close error: {e}")


# ─── Strategy A: Short @ 19:00, Exit @ 23:00 ──────────────────────────────────
def run_eurusd_a_entry():
    """Short EURUSD at 19:00 GMT."""
    _open_trade("A", "SHORT", sl_pips=30, tp_pips=0, comment="GI3-EUR-A")

def run_eurusd_a_exit():
    """Close at 23:00 GMT."""
    _close_trades("GI3-EUR-A", "Short@19-23")


# ─── Strategy B: Short @ 16:00, Exit @ 20:00 ──────────────────────────────────
def run_eurusd_b_entry():
    """Short EURUSD at 16:00 GMT."""
    _open_trade("B", "SHORT", sl_pips=30, tp_pips=0, comment="GI3-EUR-B")

def run_eurusd_b_exit():
    """Close at 20:00 GMT."""
    _close_trades("GI3-EUR-B", "Short@16-20")


# ─── Strategy C: Long @ 00:00, Exit @ 01:00 ───────────────────────────────────
def run_eurusd_c_entry():
    """Long EURUSD at 00:00 GMT (midnight)."""
    _open_trade("C", "LONG", sl_pips=20, tp_pips=0, comment="GI3-EUR-C")

def run_eurusd_c_exit():
    """Close at 01:00 GMT."""
    _close_trades("GI3-EUR-C", "Long@00-01")
