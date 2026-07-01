"""
engine/gi2_prelondon_long.py — Gold Implementation 2: Strategy 3
================================================================
Pre-London Session Long (The Spear)

Discovered via 30-day brute-force pattern discovery engine.
Historical Performance (30 days):
  - Green Days: 18/25 (72% Daily Win Rate)
  - Total Net Pips: +2,198.5

Logic:
  - At exactly 01:00 GMT, enter LONG on XAUUSD.
  - Exit at exactly 04:00 GMT (close by market order before Asian Short starts).
  - No TP/SL — time-based exit only.
  - Only ONE trade per day.

Why it works:
  Asian algorithmic market makers push Gold up in the 01:00–04:00 GMT
  window as they position for the European pre-market. This creates a
  consistent short-term directional drift that the data confirms over
  18 of the last 25 trading days.
"""

import logging
from datetime import datetime, timezone

logger = logging.getLogger("engine.gi2_prelondon_long")

_trade_order_id: str | None = None
_trade_date: str | None = None


def _already_traded_today() -> bool:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return _trade_date == today


def run_gi2_prelondon_long_entry():
    """
    Entry job — fires at 01:00 GMT.
    Opens a LONG position tagged 'GI2-PRELON-LONG'.
    """
    global _trade_order_id, _trade_date

    if _already_traded_today():
        logger.info("[GI2-PRELON-LONG] Already traded today — skipping entry.")
        return

    logger.info("[GI2-PRELON-LONG] 01:00 GMT — Entering LONG...")

    try:
        import MetaTrader5 as mt5
        from engine import broker_executor, telegram_notifier
        from engine.db import log_trade_to_db

        mt5.initialize()
        tick = mt5.symbol_info_tick("XAUUSD")
        if tick is None:
            logger.error("[GI2-PRELON-LONG] Cannot get live tick — aborting.")
            return

        live_price = tick.ask

        result = broker_executor.place_order(
            direction="LONG",
            lot_size=0.05,
            entry_price=live_price,
            stop_loss=live_price - 10.0,  # 100 pip emergency SL
            take_profit=0.0,              # Time-based exit, no fixed TP
            comment="GI2-PRELON-LONG",
        )

        if result["success"]:
            _trade_order_id = result["order_id"]
            _trade_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            logger.info(f"[GI2-PRELON-LONG] LONG opened @ {live_price:.2f} | Order: {_trade_order_id}")
            telegram_notifier.notify_info(
                "GI2 Pre-London Long",
                f"LONG XAU/USD @ {live_price:.2f}\n"
                f"Pre-London Drift (01:00–04:00 GMT)\n"
                f"Exit at 04:00 GMT (time-based)",
            )
        else:
            logger.error(f"[GI2-PRELON-LONG] Entry failed: {result['error']}")

    except Exception as e:
        logger.exception(f"[GI2-PRELON-LONG] Entry error: {e}")


def run_gi2_prelondon_long_exit():
    """
    Exit job — fires at 04:00 GMT.
    Closes all open 'GI2-PRELON-LONG' positions by market order.
    """
    global _trade_order_id, _trade_date

    logger.info("[GI2-PRELON-LONG] 04:00 GMT — Closing LONG...")

    try:
        import MetaTrader5 as mt5
        from engine import telegram_notifier

        mt5.initialize()
        positions = mt5.positions_get(symbol="XAUUSD")
        positions = [p for p in positions if p.comment == "GI2-PRELON-LONG"] if positions else []

        if not positions:
            logger.info("[GI2-PRELON-LONG] No open GI2-PRELON-LONG positions to close.")
            return

        for pos in positions:
            tick = mt5.symbol_info_tick("XAUUSD")
            close_price = tick.bid  # sell to close long

            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": "XAUUSD",
                "volume": pos.volume,
                "type": mt5.ORDER_TYPE_SELL,
                "position": pos.ticket,
                "price": close_price,
                "deviation": 20,
                "magic": 20003,
                "comment": "GI2-PRELON-LONG-EXIT",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }

            result = mt5.order_send(request)

            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                pips = (close_price - pos.price_open) * 10
                pnl = pos.profit
                logger.info(f"[GI2-PRELON-LONG] Closed @ {close_price:.2f} | Pips: {pips:.1f} | P&L: ${pnl:.2f}")
                telegram_notifier.notify_info(
                    "GI2 Pre-London Long — CLOSED",
                    f"LONG closed @ {close_price:.2f}\n"
                    f"Entry: {pos.price_open:.2f} | P&L: ${pnl:.2f} ({pips:+.1f} pips)\n"
                    f"Time-based exit (04:00 GMT)",
                )
            else:
                err = result.retcode if result else "N/A"
                logger.error(f"[GI2-PRELON-LONG] Close failed: retcode={err}")

        _trade_order_id = None

    except Exception as e:
        logger.exception(f"[GI2-PRELON-LONG] Exit error: {e}")
