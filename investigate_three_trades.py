import MetaTrader5 as mt5
from datetime import datetime, timezone
import pandas as pd

mt5.initialize()

# Target strategies:
# M15_MomentumRunner: Magic 202604
# GI2_PreLondon_Long: Magic 202623
# GI2_Asian_Short: Magic 202622

now = datetime.now(timezone.utc)
start_of_today = datetime(now.year, now.month, now.day, 0, 0, 0, tzinfo=timezone.utc)

deals = mt5.history_deals_get(start_of_today, now)
in_deals = {d.position_id: d for d in deals if d.entry == 0}
out_deals = [d for d in deals if d.entry == 1]

targets = [202604, 202623, 202622]

print("=== INVESTIGATING M15_MomentumRunner, GI2_PreLondon_Long, GI2_Asian_Short ===")
for d in out_deals:
    d_in = in_deals.get(d.position_id)
    real_magic = d_in.magic if d_in else d.magic
    if real_magic in targets:
        # Get order details
        in_order = mt5.history_orders_get(ticket=d_in.order) if d_in else None
        out_order = mt5.history_orders_get(ticket=d.order)
        
        in_ord_obj = in_order[0] if in_order else None
        out_ord_obj = out_order[0] if out_order else None
        
        print("\n-------------------------------------------------------------")
        print(f"Position ID: {d.position_id}")
        print(f"Strategy Magic: {real_magic}")
        print(f"Symbol: {d.symbol} | Profit: ${d.profit:.2f}")
        
        if in_ord_obj:
            dt_open = datetime.fromtimestamp(in_ord_obj.time_setup, tz=timezone.utc)
            print(f"OPEN ORDER #{in_ord_obj.ticket}:")
            print(f"  Time: {dt_open.strftime('%Y-%m-%d %H:%M:%S UTC')}")
            print(f"  Type: {'BUY' if in_ord_obj.type == 0 else ('SELL' if in_ord_obj.type == 1 else in_ord_obj.type)}")
            print(f"  Volume: {in_ord_obj.volume_initial}")
            print(f"  Open Price: {d_in.price if d_in else in_ord_obj.price_open}")
            print(f"  Planned SL: {in_ord_obj.sl}")
            print(f"  Planned TP: {in_ord_obj.tp}")
            print(f"  Comment: {in_ord_obj.comment}")
            
        if out_ord_obj:
            dt_close = datetime.fromtimestamp(out_ord_obj.time_setup, tz=timezone.utc)
            print(f"CLOSE DEAL / ORDER #{d.ticket}:")
            print(f"  Time: {dt_close.strftime('%Y-%m-%d %H:%M:%S UTC')}")
            print(f"  Exit Price: {d.price}")
            print(f"  Reason Code: {d.reason} (0=Client, 3=Expert/Auto, 4=TP, 5=SL)")
            print(f"  Exit Comment: {d.comment}")
            print(f"  Exit Order Comment: {out_ord_obj.comment}")
