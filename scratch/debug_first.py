import MetaTrader5 as mt5
from datetime import datetime, timezone

def test():
    mt5.initialize()
    deals = mt5.history_deals_get(datetime(2026, 6, 30), datetime.now())
    if deals:
        first = deals[0]
        t_utc = datetime.fromtimestamp(first.time, tz=timezone.utc)
        print(f"First trade today MT5 raw: {first.time} -> UTC tz: {t_utc}")
        
    mt5.shutdown()

if __name__ == "__main__":
    test()
