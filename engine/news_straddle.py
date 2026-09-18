"""
engine/news_straddle.py
Executes a Bracket Breakout (Straddle) exactly 1 minute before high-impact news.
Places pending BUY STOP and SELL STOP orders.
"""
import logging
import MetaTrader5 as mt5
from engine import broker_executor, telegram_notifier

logger = logging.getLogger("engine.news_straddle")

MAGIC_NUMBER_STRADDLE = 209000

def run_news_straddle(event_title: str):
    """
    Executes a straddle for Gold (XAUUSD).
    Places pending orders 30 pips away from current price.
    """
    logger.info(f"[NEWS STRADDLE] Initiating Straddle for {event_title}")
    
    if not broker_executor._init_mt5():
        logger.error("[NEWS STRADDLE] MT5 not connected.")
        return
        
    symbol = "XAUUSD"
    lot_size = 0.05
    pip_distance = 30.0 # 30 pips = 3.0 points
    sl_distance = 15.0 # 15 pips = 1.5 points
    
    # 1. Get current price
    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        logger.error(f"[NEWS STRADDLE] Failed to get tick for {symbol}")
        return
        
    current_price = (tick.bid + tick.ask) / 2.0
    
    buy_stop_price = current_price + (pip_distance / 10.0)
    sell_stop_price = current_price - (pip_distance / 10.0)
    
    sl_points = sl_distance / 10.0
    
    # 2. Place Straddle
    # We use a custom request to bypass the hardcoded 25 spread limit in place_straddle_orders, 
    # because spreads often widen to 30-40 right before the news hits.
    
    # BUY STOP
    buy_request = {
        "action": mt5.TRADE_ACTION_PENDING,
        "symbol": symbol,
        "volume": lot_size,
        "type": mt5.ORDER_TYPE_BUY_STOP,
        "price": round(buy_stop_price, 2),
        "sl": round(buy_stop_price - sl_points, 2),
        "tp": 0.0, # Open TP, trailed by trade manager
        "deviation": 50, # allow slippage on entry
        "magic": MAGIC_NUMBER_STRADDLE,
        "comment": "News-Straddle-B",
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
        "sl": round(sell_stop_price + sl_points, 2),
        "tp": 0.0,
        "deviation": 50,
        "magic": MAGIC_NUMBER_STRADDLE,
        "comment": "News-Straddle-S",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    
    buy_res = mt5.order_send(buy_request)
    sell_res = mt5.order_send(sell_request)
    
    if buy_res and buy_res.retcode == mt5.TRADE_RETCODE_DONE:
        logger.info(f"[NEWS STRADDLE] BUY STOP placed @ {buy_stop_price}")
    else:
        err = buy_res.retcode if buy_res else "None"
        logger.error(f"[NEWS STRADDLE] BUY STOP failed. Retcode: {err}")
        
    if sell_res and sell_res.retcode == mt5.TRADE_RETCODE_DONE:
        logger.info(f"[NEWS STRADDLE] SELL STOP placed @ {sell_stop_price}")
    else:
        err = sell_res.retcode if sell_res else "None"
        logger.error(f"[NEWS STRADDLE] SELL STOP failed. Retcode: {err}")
        
    if (buy_res and buy_res.retcode == mt5.TRADE_RETCODE_DONE) or (sell_res and sell_res.retcode == mt5.TRADE_RETCODE_DONE):
        telegram_notifier.notify_info(
            "News Straddle Armed", 
            f"Event: {event_title}\n"
            f"Buy Stop: {buy_stop_price:.2f}\n"
            f"Sell Stop: {sell_stop_price:.2f}\n"
            f"Lot Size: {lot_size}"
        )
