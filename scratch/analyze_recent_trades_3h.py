import MetaTrader5 as mt5
from datetime import datetime, timedelta, timezone

def analyze():
    if not mt5.initialize():
        print("MT5 initialization failed")
        return

    # User local time is UTC+1. MT5 server time is usually UTC+3.
    # We will get the current MT5 time directly from the server.
    terminal_info = mt5.terminal_info()
    if terminal_info is None:
        print("Failed to get terminal info")
        return
        
    print(f"MT5 Connected: {terminal_info.company}")
    
    # We can get the last tick to figure out MT5 time
    tick = mt5.symbol_info_tick("EURUSD")
    if not tick:
        tick = mt5.symbol_info_tick("XAUUSD")
        
    if tick:
        mt5_now = datetime.fromtimestamp(tick.time, tz=timezone.utc)
    else:
        mt5_now = datetime.now(timezone.utc) + timedelta(hours=2) # Guessing
        
    print(f"Estimated MT5 Now: {mt5_now}")
    
    # Fetch history for the last 4 hours just to be safe
    from_date = datetime.now(timezone.utc) - timedelta(hours=4)
    to_date = datetime.now(timezone.utc) + timedelta(hours=1)
    
    deals = mt5.history_deals_get(from_date, to_date)
    if deals is None:
        print("No deals found or failed to fetch deals")
        mt5.shutdown()
        return
        
    print(f"Total deals found: {len(deals)}")
    
    trades = {}
    
    for deal in deals:
        # deal.entry == 0 is IN, 1 is OUT, 2 is INOUT, 3 is OUT_BY
        # deal.profit is the profit
        # deal.magic is the magic number
        # deal.comment is the comment
        if deal.position_id not in trades:
            trades[deal.position_id] = {
                'ticket': deal.position_id,
                'symbol': deal.symbol,
                'magic': deal.magic,
                'comment': deal.comment,
                'in_time_mt5': None,
                'out_time_mt5': None,
                'profit': 0.0,
                'commission': 0.0,
                'swap': 0.0,
                'volume': 0.0,
                'direction': None,
                'deals': 0
            }
            
        t = trades[deal.position_id]
        t['deals'] += 1
        
        if deal.entry == 0: # IN
            t['in_time_mt5'] = deal.time
            t['volume'] = deal.volume
            t['direction'] = "LONG" if deal.type == 0 else "SHORT"
            if not t['comment'] and deal.comment:
                t['comment'] = deal.comment
        elif deal.entry == 1: # OUT
            t['out_time_mt5'] = deal.time
            t['profit'] += deal.profit
            t['commission'] += deal.commission
            t['swap'] += deal.swap
            if deal.comment and not t['comment']:
                t['comment'] = deal.comment
                
    # Format and print
    print("-" * 80)
    for pos_id, t in trades.items():
        if t['in_time_mt5'] is None:
            continue
            
        # Convert MT5 timestamp directly
        in_dt = datetime.fromtimestamp(t['in_time_mt5'])
        
        in_mt5_str = in_dt.strftime('%H:%M:%S')
        in_local_str = (in_dt - timedelta(hours=2)).strftime('%H:%M:%S')
        
        out_mt5_str = "OPEN"
        out_local_str = "OPEN"
        if t['out_time_mt5']:
            out_dt = datetime.fromtimestamp(t['out_time_mt5'])
            out_mt5_str = out_dt.strftime('%H:%M:%S')
            out_local_str = (out_dt - timedelta(hours=2)).strftime('%H:%M:%S')
            
        net_profit = t['profit'] + t['commission'] + t['swap']
        
        print(f"Ticket: {t['ticket']} | Symbol: {t['symbol']} | Dir: {t['direction']} | Vol: {t['volume']}")
        print(f"Magic: {t['magic']} | Comment: {t['comment']}")
        print(f"Time IN: MT5 {in_mt5_str} (Local ~{in_local_str}) | OUT: MT5 {out_mt5_str} (Local ~{out_local_str})")
        print(f"Net Profit: ${net_profit:.2f}")
        print("-" * 80)
        
    mt5.shutdown()

if __name__ == "__main__":
    analyze()
