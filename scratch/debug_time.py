import MetaTrader5 as mt5
from datetime import datetime, timezone

def debug_time():
    if not mt5.initialize():
        return
        
    # Get the latest deal to check exact timestamps
    deals = mt5.history_deals_get(datetime(2026, 6, 29), datetime.now())
    if not deals:
        print("No deals")
        return
        
    # Get last deal
    last_deal = deals[-1]
    raw_time = last_deal.time
    
    # 1. As naive local timestamp
    dt_local = datetime.fromtimestamp(raw_time)
    
    # 2. As raw UTC (this is the true MT5 Server Time)
    dt_utc = datetime.fromtimestamp(raw_time, tz=timezone.utc)
    
    print(f"Deal ID: {last_deal.ticket}")
    print(f"Raw MT5 time integer: {raw_time}")
    print(f"Python naive fromtimestamp (Wrong due to double offset): {dt_local}")
    print(f"Python UTC fromtimestamp (True MT5 Server Time): {dt_utc}")
    
    # 3. Calculate Local Time (True MT5 Server Time - 3 hours)
    from datetime import timedelta
    dt_user_local = dt_utc - timedelta(hours=3)
    print(f"Calculated User Local Time: {dt_user_local}")

if __name__ == "__main__":
    debug_time()
