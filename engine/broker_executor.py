"""
engine/broker_executor.py — MT5 demo broker integration.

Sends market orders to MetaTrader 5 demo account.
Set BROKER_STUB_MODE=true in .env to skip real broker connection.
"""
import logging
import os
import time
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
    symbol: str = 'XAUUSD',
    magic: int = 202600,
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

        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return {"success": False, "error": f"Cannot get tick for {symbol}", "order_id": None, "actual_entry": None, "slippage_pips": None}

        price = tick.ask if direction == "LONG" else tick.bid

        filling_mode = mt5.ORDER_FILLING_IOC
        if tick and mt5.symbol_info(symbol):
            allowed_modes = mt5.symbol_info(symbol).filling_mode
            if allowed_modes == 1:
                filling_mode = mt5.ORDER_FILLING_FOK

        request = {
            "action": action,
            "symbol": symbol,
            "volume": lot_size,
            "type": order_type,
            "price": round(price, 5),
            "sl": round(stop_loss, 5) if stop_loss > 0 else 0.0,
            "tp": round(take_profit, 5) if take_profit > 0 else 0.0,
            "deviation": 20,
            "magic": magic,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": filling_mode,
        }

        result = mt5.order_send(request)

        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            if result and result.retcode == 10018:
                error_msg = "Order failed: MARKET_CLOSED (Daily 1-hour settlement break or weekend)"
            else:
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

def place_limit_order(
    direction: str,
    lot_size: float,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    magic: int = 202600,
    comment: str = "TradingOS",
    symbol: str = 'XAUUSD',
) -> dict:
    """Place a pending Limit Order."""
    if STUB_MODE:
        logger.info(f"[STUB] Would place LIMIT {direction} {lot_size} lots @ {entry_price} SL={stop_loss} TP={take_profit}")
        return {"success": True, "order_id": f"STUB-LMT-{int(__import__('time').time())}", "error": None}
        
    try:
        import MetaTrader5 as mt5
        if not _init_mt5():
            return {"success": False, "error": "MT5 not connected", "order_id": None}
            
        action = mt5.TRADE_ACTION_PENDING
        order_type = mt5.ORDER_TYPE_BUY_LIMIT if direction == "LONG" else mt5.ORDER_TYPE_SELL_LIMIT
        
        filling_mode = mt5.ORDER_FILLING_IOC
        if mt5.symbol_info(symbol):
            allowed_modes = mt5.symbol_info(symbol).filling_mode
            if allowed_modes == 1:
                filling_mode = mt5.ORDER_FILLING_FOK
                
        request = {
            "action": action,
            "symbol": symbol,
            "volume": lot_size,
            "type": order_type,
            "price": round(entry_price, 5),
            "sl": round(stop_loss, 5) if stop_loss > 0 else 0.0,
            "tp": round(take_profit, 5) if take_profit > 0 else 0.0,
            "deviation": 20,
            "magic": magic,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": filling_mode,
        }
        
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            error_msg = f"Limit Order failed: retcode={result.retcode if result else 'None'} ({result.comment if result else ''})"
            logger.error(error_msg)
            return {"success": False, "error": error_msg, "order_id": None}
            
        logger.info(f"Limit Order placed: #{result.order} {direction} {lot_size} lots @ {entry_price}")
        return {
            "success": True,
            "order_id": str(result.order),
            "error": None
        }
    except Exception as e:
        logger.error(f"place_limit_order exception: {e}")
        return {"success": False, "error": str(e), "order_id": None}


def get_open_positions(symbol: str = 'XAUUSD') -> list:
    """Return list of open MT5 positions for XAUUSD."""
    if STUB_MODE:
        return []
    try:
        import MetaTrader5 as mt5
        if not _init_mt5():
            return []
        positions = mt5.positions_get(symbol=symbol)
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


def close_position(ticket: int, symbol: str = 'XAUUSD') -> bool:
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
        # Dynamically use the real symbol from the position
        symbol = pos.symbol
        order_type = mt5.ORDER_TYPE_SELL if pos.type == 0 else mt5.ORDER_TYPE_BUY
        tick = mt5.symbol_info_tick(symbol)
        price = tick.bid if pos.type == 0 else tick.ask
        
        filling_mode = mt5.ORDER_FILLING_IOC
        if tick and mt5.symbol_info(symbol):
            allowed_modes = mt5.symbol_info(symbol).filling_mode
            if allowed_modes == 1:
                filling_mode = mt5.ORDER_FILLING_FOK

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": pos.volume,
            "type": order_type,
            "position": ticket,
            "price": price,
            "deviation": 20,
            "magic": 202600,
            "comment": "TradingOS-close",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": filling_mode,
        }
        result = mt5.order_send(request)
        return result is not None and result.retcode == mt5.TRADE_RETCODE_DONE
    except Exception as e:
        logger.error(f"close_position error: {e}")
        return False


def modify_position_sl(ticket: int, new_sl: float, symbol: str = 'XAUUSD') -> bool:
    """Update Stop Loss for a specific position."""
    if STUB_MODE:
        logger.info(f"[STUB] Would modify position #{ticket} SL to {new_sl}")
        return True
    try:
        import MetaTrader5 as mt5
        if not _init_mt5(): return False
        
        position = mt5.positions_get(ticket=ticket)
        if not position: return False
        pos = position[0]
        symbol = pos.symbol
        digits = 2
        sinfo = mt5.symbol_info(symbol)
        if sinfo:
            digits = sinfo.digits
        
        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "symbol": symbol,
            "sl": round(new_sl, digits),
            "tp": pos.tp,
            "magic": 202600
        }
        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            logger.info(f"Modified SL for #{ticket} to {round(new_sl, 2):.2f}")
            return True
        else:
            logger.error(f"Failed to modify SL for #{ticket}: {result.comment if result else 'Unknown'}")
            return False
    except Exception as e:
        logger.error(f"modify_position_sl error: {e}")
        return False


def close_partial_position(ticket: int, percent: float = 50.0, symbol: str = 'XAUUSD') -> bool:
    """Close a percentage of an open position."""
    if STUB_MODE:
        logger.info(f"[STUB] Would close {percent}% of position #{ticket}")
        return True
    try:
        import MetaTrader5 as mt5
        if not _init_mt5(): return False
        
        position = mt5.positions_get(ticket=ticket)
        if not position: return False
        pos = position[0]
        
        symbol_info = mt5.symbol_info(symbol)
        if not symbol_info:
            logger.error(f"Failed to get symbol info for {symbol}")
            return False
            
        vol_step = symbol_info.volume_step
        vol_min = symbol_info.volume_min
        
        # Calculate exactly how much to close and round to step
        raw_close_volume = pos.volume * (percent / 100.0)
        # Round to nearest vol_step
        close_volume = round(raw_close_volume / vol_step) * vol_step
        
        if close_volume < vol_min:
            logger.warning(f"Partial close volume {close_volume} too small for #{ticket}, fully closing instead.")
            return close_position(ticket)
            
        order_type = mt5.ORDER_TYPE_SELL if pos.type == 0 else mt5.ORDER_TYPE_BUY
        tick = mt5.symbol_info_tick(symbol)
        price = tick.bid if pos.type == 0 else tick.ask

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": close_volume,
            "type": order_type,
            "position": ticket,
            "price": price,
            "deviation": 20,
            "magic": 202600,
            "comment": f"Partial {percent}%",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            logger.info(f"Partially closed {close_volume} lots for #{ticket}")
            return True
        else:
            logger.error(f"Failed partial close for #{ticket}: {result.comment if result else 'Unknown'}")
            return False
    except Exception as e:
        logger.error(f"close_partial_position error: {e}")
        return False

def check_spread(symbol: str = 'XAUUSD') -> float:
    """Returns the current spread in points."""
    if STUB_MODE:
        return 10.0
    try:
        import MetaTrader5 as mt5
        if not _init_mt5(): return 999.0
        info = mt5.symbol_info(symbol)
        if not info: return 999.0
        return float(info.spread)
    except Exception as e:
        logger.error(f"check_spread error: {e}")
        return 999.0

def place_straddle_orders(
    buy_stop_price: float,
    sell_stop_price: float,
    lot_size: float,
    sl_dist: float,
    tp1_dist: float,
    expiration_hours: int = 4,
    symbol: str = 'XAUUSD',
) -> dict:
    """
    Place a Buy Stop and Sell Stop order simultaneously.
    Returns dict with success and order_ids.
    """
    if STUB_MODE:
        logger.info(f"[STUB] Straddle placed. BuyStop={buy_stop_price}, SellStop={sell_stop_price}")
        return {
            "success": True,
            "buy_order_id": f"BS-{int(time.time())}",
            "sell_order_id": f"SS-{int(time.time())}",
            "error": None
        }
        
    try:
        import MetaTrader5 as mt5
        if not _init_mt5():
            return {"success": False, "error": "MT5 not connected", "buy_order_id": None, "sell_order_id": None}
            
        spread = check_spread(symbol)
        if spread > 25:
            logger.warning(f"STRADDLE_BLOCKED_HIGH_SPREAD: {spread} points")
            return {"success": False, "error": f"STRADDLE_BLOCKED_HIGH_SPREAD ({spread})", "buy_order_id": None, "sell_order_id": None}
            
        # Common params
        exp_time = int(time.time()) + (expiration_hours * 3600)
        
        # BUY STOP
        buy_request = {
            "action": mt5.TRADE_ACTION_PENDING,
            "symbol": symbol,
            "volume": lot_size,
            "type": mt5.ORDER_TYPE_BUY_STOP,
            "price": round(buy_stop_price, 2),
            "sl": round(buy_stop_price - sl_dist, 2),
            "tp": round(buy_stop_price + tp1_dist, 2),
            "deviation": 20,
            "magic": 202600,
            "comment": "ABE-BuyStop",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        
        # SELL STOP
        sell_request = {
            "action": mt5.TRADE_ACTION_PENDING,
            "symbol": symbol,
            "volume": lot_size,
            "type": mt5.ORDER_TYPE_SELL_STOP,
            "price": round(sell_stop_price, 2),
            "sl": round(sell_stop_price + sl_dist, 2),
            "tp": round(sell_stop_price - tp1_dist, 2),
            "deviation": 20,
            "magic": 202600,
            "comment": "ABE-SellStop",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        
        buy_res = mt5.order_send(buy_request)
        if buy_res is None or buy_res.retcode != mt5.TRADE_RETCODE_DONE:
            err = f"Buy Stop failed: {buy_res.comment if buy_res else 'None'}"
            logger.error(err)
            return {"success": False, "error": err, "buy_order_id": None, "sell_order_id": None}
            
        sell_res = mt5.order_send(sell_request)
        if sell_res is None or sell_res.retcode != mt5.TRADE_RETCODE_DONE:
            err = f"Sell Stop failed: {sell_res.comment if sell_res else 'None'}"
            logger.error(err)
            # Need to cancel the buy stop immediately since sell failed!
            cancel_order(buy_res.order)
            return {"success": False, "error": err, "buy_order_id": None, "sell_order_id": None}
            
        return {
            "success": True,
            "buy_order_id": str(buy_res.order),
            "sell_order_id": str(sell_res.order),
            "error": None
        }
        
    except Exception as e:
        logger.error(f"place_straddle_orders exception: {e}")
        return {"success": False, "error": str(e), "buy_order_id": None, "sell_order_id": None}


def cancel_order(ticket: int) -> bool:
    """Cancel a pending order."""
    if STUB_MODE:
        logger.info(f"[STUB] Would cancel order #{ticket}")
        return True
    try:
        import MetaTrader5 as mt5
        if not _init_mt5(): return False
        
        # ticket must be int
        ticket = int(ticket)
        request = {
            "action": mt5.TRADE_ACTION_REMOVE,
            "order": ticket,
        }
        result = mt5.order_send(request)
        return result is not None and result.retcode == mt5.TRADE_RETCODE_DONE
    except Exception as e:
        logger.error(f"cancel_order exception: {e}")
        return False


def verify_cancellation(ticket: int) -> bool:
    """
    Verify MT5 cancellation with a 10-second timeout.
    Returns True if order is successfully removed.
    """
    if STUB_MODE:
        return True
    import MetaTrader5 as mt5
    if not _init_mt5(): return False
    
    ticket = int(ticket)
    for _ in range(5):
        # check if order still exists in pending orders
        orders = mt5.orders_get(ticket=ticket)
        if orders is None or len(orders) == 0:
            return True
        time.sleep(2)
        
    return False

def check_straddle_status(buy_ticket: int, sell_ticket: int, symbol: str = 'XAUUSD') -> dict:
    """
    Returns state of the straddle pair.
    { "buy_filled": bool, "sell_filled": bool, "buy_expired": bool, "sell_expired": bool }
    """
    if STUB_MODE:
        return {"buy_filled": False, "sell_filled": False, "buy_expired": False, "sell_expired": False}
        
    import MetaTrader5 as mt5
    if not _init_mt5(): return {"buy_filled": False, "sell_filled": False, "buy_expired": False, "sell_expired": False}
    
    buy_ticket = int(buy_ticket)
    sell_ticket = int(sell_ticket)
    
    buy_filled = False
    sell_filled = False
    buy_expired = False
    sell_expired = False
    
    positions = mt5.positions_get(symbol=symbol)
    if positions:
        for p in positions:
            if p.identifier == buy_ticket:
                buy_filled = True
            elif p.identifier == sell_ticket:
                sell_filled = True
                
    # If not filled, check if they still exist as pending
    if not buy_filled:
        orders = mt5.orders_get(ticket=buy_ticket)
        if orders is None or len(orders) == 0:
            buy_expired = True # missing from pending and not in positions -> expired/cancelled

    if not sell_filled:
        orders = mt5.orders_get(ticket=sell_ticket)
        if orders is None or len(orders) == 0:
            sell_expired = True

    return {
        "buy_filled": buy_filled, 
        "sell_filled": sell_filled,
        "buy_expired": buy_expired,
        "sell_expired": sell_expired
    }
