"""
engine/gi2_asian_short.py — Gold Implementation 2: Strategy 2
=============================================================
Asian Session Liquidity Trap Short (The Shield)

Discovered via 30-day brute-force pattern discovery engine.
Historical Performance (30 days):
  - Green Days: 19/25 (76% Daily Win Rate)
  - Total Net Pips: +3,007.2

Logic:
  - At exactly 04:00 GMT, enter SHORT on XAUUSD.
  - Exit at exactly 06:00 GMT (close by market order).
  - No TP/SL — time-based exit only (avoids stop hunting).
  - Only ONE trade per day.

Why it works:
  European algorithms systematically drive Gold down in the pre-London
  window (04:00–06:00 GMT) to sweep Asian session lows before reversing.
"""

import logging
from datetime import datetime, timezone

logger = logging.getLogger("engine.gi2_asian_short")

_trade_order_id: str | None = None
_trade_date: str | None = None   # YYYY-MM-DD string to enforce one trade/day


def _already_traded_today() -> bool:
    """Returns True if we already executed the Asian Short today."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return _trade_date == today


def run_gi2_asian_short_entry():
    """
    Entry job — fires at 04:00 GMT.
    Opens a SHORT position tagged 'GI2-ASIAN-SHORT'.
    """
    global _trade_order_id, _trade_date

    if _already_traded_today():
        logger.info("[GI2-ASIAN-SHORT] Already traded today — skipping entry.")
        return

    logger.info("[GI2-ASIAN-SHORT] 04:00 GMT — Entering SHORT...")

    try:
        import MetaTrader5 as mt5
        from engine import broker_executor, telegram_notifier

        mt5.initialize()
        tick = mt5.symbol_info_tick("XAUUSD")
        if tick is None:
            logger.error("[GI2-ASIAN-SHORT] Cannot get live tick — aborting.")
            return

        live_price = tick.bid

        result = broker_executor.place_order(
            direction="SHORT",
            lot_size=0.05,
            entry_price=live_price,
            stop_loss=live_price + 10.0,  # 100 pip emergency SL (should not be hit in 2hrs)
            take_profit=0.0,              # Time-based exit, no fixed TP
            comment="GI2-ASIAN-SHORT",
        )

        if result["success"]:
            _trade_order_id = result["order_id"]
            _trade_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            logger.info(f"[GI2-ASIAN-SHORT] SHORT opened @ {live_price:.2f} | Order: {_trade_order_id}")
            telegram_notifier.notify_info(
                "GI2 Asian Short",
                f"SHORT XAU/USD @ {live_price:.2f}\n"
                f"Asian Liquidity Trap (04:00–06:00 GMT)\n"
                f"Exit at 06:00 GMT (time-based)",
            )
        else:
            logger.error(f"[GI2-ASIAN-SHORT] Entry failed: {result['error']}")

    except Exception as e:
        logger.exception(f"[GI2-ASIAN-SHORT] Entry error: {e}")


def run_gi2_asian_short_exit():
    """
    Exit job — fires at 06:00 GMT.
    Closes all open 'GI2-ASIAN-SHORT' positions by market order.
    """
    global _trade_order_id, _trade_date

    logger.info("[GI2-ASIAN-SHORT] 06:00 GMT — Closing SHORT...")

    try:
        import MetaTrader5 as mt5
        from engine import telegram_notifier

        mt5.initialize()
        positions = mt5.positions_get(symbol="XAUUSD")
        positions = [p for p in positions if p.comment == "GI2-ASIAN-SHORT"] if positions else []

        if not positions:
            logger.info("[GI2-ASIAN-SHORT] No open GI2-ASIAN-SHORT positions to close.")
            return

        for pos in positions:
            tick = mt5.symbol_info_tick("XAUUSD")
            close_price = tick.ask if pos.type == 1 else tick.bid  # buy to close short

            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": "XAUUSD",
                "volume": pos.volume,
                "type": mt5.ORDER_TYPE_BUY if pos.type == 1 else mt5.ORDER_TYPE_SELL,
                "position": pos.ticket,
                "price": close_price,
                "deviation": 20,
                "magic": 20002,
                "comment": "GI2-ASIAN-SHORT-EXIT",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }

            result = mt5.order_send(request)

            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                pips = (pos.price_open - close_price) * 10  # short pips
                pnl = pos.profit
                logger.info(f"[GI2-ASIAN-SHORT] Closed @ {close_price:.2f} | Pips: {pips:.1f} | P&L: ${pnl:.2f}")
                telegram_notifier.notify_info(
                    "GI2 Asian Short — CLOSED",
                    f"SHORT closed @ {close_price:.2f}\n"
                    f"Entry: {pos.price_open:.2f} | P&L: ${pnl:.2f} ({pips:+.1f} pips)\n"
                    f"Time-based exit (06:00 GMT)",
                )
            else:
                err = result.retcode if result else "N/A"
                logger.error(f"[GI2-ASIAN-SHORT] Close failed: retcode={err}")

        _trade_order_id = None

    except Exception as e:
        logger.exception(f"[GI2-ASIAN-SHORT] Exit error: {e}")
