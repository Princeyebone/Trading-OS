import sys
import os
import MetaTrader5 as mt5

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine import broker_executor

def main():
    if not broker_executor._init_mt5(): return
    ticket = 58121431357
    pos = mt5.positions_get(ticket=ticket)
    if not pos:
        print("Not found")
        return
    pos = pos[0]
    symbol = pos.symbol
    order_type = mt5.ORDER_TYPE_SELL if pos.type == 0 else mt5.ORDER_TYPE_BUY
    tick = mt5.symbol_info_tick(symbol)
    price = tick.bid if pos.type == 0 else tick.ask
    
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
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    res = mt5.order_send(request)
    if res:
        print(f"Retcode: {res.retcode}, Comment: {res.comment}")
    else:
        print(f"order_send failed, last error: {mt5.last_error()}")

if __name__ == "__main__":
    main()
