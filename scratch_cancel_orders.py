import sys
import logging
sys.path.insert(0, "c:/Users/HP/OneDrive/Desktop/tb/backend")

from engine.broker_executor import _init_mt5, cancel_order
import MetaTrader5 as mt5

def cancel_all_orders():
    if not _init_mt5():
        print("Failed to init MT5")
        return
        
    orders = mt5.orders_get()
    if orders is None:
        print("Failed to get orders or no orders found.")
        return
        
    print(f"Found {len(orders)} pending orders.")
    for o in orders:
        print(f"Cancelling order #{o.ticket} ({o.type})")
        res = cancel_order(o.ticket)
        if res:
            print("Success")
        else:
            print("Failed")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    cancel_all_orders()
