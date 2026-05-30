"""
engine/broker_executor.py — MT5 demo broker integration.

Sends market orders to MetaTrader 5 demo account.
Set BROKER_STUB_MODE=true in .env to skip real broker connection.
"""
import logging
import os
from typing import Optional
from app.settings import settings

logger = logging.getLogger(__name__)

STUB_MODE = settings.broker_stub_mode
MT5_LOGIN    = settings.mt5_login
MT5_PASSWORD = settings.mt5_password
MT5_SERVER   = settings.mt5_server

SYMBOL = "XAUUSD"

_mt5_initialized = False


def _init_mt5() -> bool:
    """Initialize MT5 connection. Returns True if successful."""
    global _mt5_initialized
    if _mt5_initialized:
        return True
    if STUB_MODE:
        logger.info("BROKER_STUB_MODE=true — skipping MT5 init")
        return True
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize(login=MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER):
            logger.error(f"MT5 initialize failed: {mt5.last_error()}")
            return False
        logger.info(f"MT5 connected: {mt5.account_info().server}")
        _mt5_initialized = True
        return True
    except Exception as e:
        logger.error(f"MT5 init exception: {e}")
        return False


def place_order(
    direction: str,        # "LONG" or "SHORT"
    lot_size: float,
    entry_price: float,    # planned entry (for reference)
    stop_loss: float,
    take_profit: float,
    comment: str = "TradingOS",
) -> dict:
    """
    Place a market order on MT5 demo.
    Returns dict with: order_id, actual_entry, slippage_pips, success, error
    """
    if STUB_MODE:
        logger.info(f"[STUB] Would place {direction} {lot_size} lots @ ~{entry_price} SL={stop_loss} TP={take_profit}")
        return {
            "success": True,
            "order_id": f"STUB-{int(__import__('time').time())}",
            "actual_entry": entry_price,
            "slippage_pips": 0.0,
            "error": None,
        }

    try:
        import MetaTrader5 as mt5

        if not _init_mt5():
            return {"success": False, "error": "MT5 not connected", "order_id": None, "actual_entry": None, "slippage_pips": None}

        action = mt5.TRADE_ACTION_DEAL
        order_type = mt5.ORDER_TYPE_BUY if direction == "LONG" else mt5.ORDER_TYPE_SELL

        tick = mt5.symbol_info_tick(SYMBOL)
        if tick is None:
            return {"success": False, "error": f"Cannot get tick for {SYMBOL}", "order_id": None, "actual_entry": None, "slippage_pips": None}

        price = tick.ask if direction == "LONG" else tick.bid

        request = {
            "action": action,
            "symbol": SYMBOL,
            "volume": lot_size,
            "type": order_type,
            "price": price,
            "sl": stop_loss,
            "tp": take_profit,
            "deviation": 20,
            "magic": 202600,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)

        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            error_msg = f"Order failed: retcode={result.retcode if result else 'None'}"
            logger.error(error_msg)
            return {"success": False, "error": error_msg, "order_id": None, "actual_entry": None, "slippage_pips": None}

        actual_entry = result.price
        slippage = abs(actual_entry - entry_price) * 10  # approximate pips

        logger.info(f"Order placed: #{result.order} {direction} {lot_size} lots @ {actual_entry}")
        return {
            "success": True,
            "order_id": str(result.order),
            "actual_entry": actual_entry,
            "slippage_pips": round(slippage, 1),
            "error": None,
        }

    except Exception as e:
        logger.error(f"place_order exception: {e}")
        return {"success": False, "error": str(e), "order_id": None, "actual_entry": None, "slippage_pips": None}


def get_open_positions() -> list:
    """Return list of open MT5 positions for XAUUSD."""
    if STUB_MODE:
        return []
    try:
        import MetaTrader5 as mt5
        if not _init_mt5():
            return []
        positions = mt5.positions_get(symbol=SYMBOL)
        if positions is None:
            return []
        return [
            {
                "ticket": p.ticket,
                "type": "LONG" if p.type == 0 else "SHORT",
                "volume": p.volume,
                "open_price": p.price_open,
                "sl": p.sl,
                "tp": p.tp,
                "profit": p.profit,
                "time": p.time,
            }
            for p in positions
        ]
    except Exception as e:
        logger.error(f"get_open_positions error: {e}")
        return []


def get_account_balance() -> float:
    """Return current demo account balance."""
    if STUB_MODE:
        return settings.account_balance_equiv
    try:
        import MetaTrader5 as mt5
        if not _init_mt5():
            return 500.0
        info = mt5.account_info()
        return float(info.balance) if info else 500.0
    except Exception:
        return 500.0


def close_position(ticket: int) -> bool:
    """Close a specific position by ticket number."""
    if STUB_MODE:
        logger.info(f"[STUB] Would close position #{ticket}")
        return True
    try:
        import MetaTrader5 as mt5
        if not _init_mt5():
            return False
        position = mt5.positions_get(ticket=ticket)
        if not position:
            return False
        pos = position[0]
        order_type = mt5.ORDER_TYPE_SELL if pos.type == 0 else mt5.ORDER_TYPE_BUY
        tick = mt5.symbol_info_tick(SYMBOL)
        price = tick.bid if pos.type == 0 else tick.ask

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": SYMBOL,
            "volume": pos.volume,
            "type": order_type,
            "position": ticket,
            "price": price,
            "deviation": 20,
            "magic": 202600,
            "comment": "TradingOS-close",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        return result is not None and result.retcode == mt5.TRADE_RETCODE_DONE
    except Exception as e:
        logger.error(f"close_position error: {e}")
        return False
