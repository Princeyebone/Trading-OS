import MetaTrader5 as mt5
from datetime import datetime, timedelta, timezone
import json

def analyze():
    if not mt5.initialize():
        print(json.dumps({"error": "MT5 initialization failed"}))
        return

    # Fetch history for the last 3.5 hours
    from_date = datetime.now() - timedelta(hours=3, minutes=30)
    to_date = datetime.now() + timedelta(hours=1)
    
    deals = mt5.history_deals_get(from_date, to_date)
    if deals is None:
        print(json.dumps({"error": "No deals"}))
        mt5.shutdown()
        return
        
    trades = {}
    for deal in deals:
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
                'direction': None
            }
            
        t = trades[deal.position_id]
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
                
    result = []
    for pos_id, t in trades.items():
        if t['in_time_mt5'] is None:
            continue
            
        in_dt = datetime.fromtimestamp(t['in_time_mt5'])
        
        # Format times
        t['in_mt5_str'] = in_dt.strftime('%H:%M:%S')
        t['in_local_str'] = (in_dt - timedelta(hours=2)).strftime('%H:%M:%S')
        
        if t['out_time_mt5']:
            out_dt = datetime.fromtimestamp(t['out_time_mt5'])
            t['out_mt5_str'] = out_dt.strftime('%H:%M:%S')
            t['out_local_str'] = (out_dt - timedelta(hours=2)).strftime('%H:%M:%S')
            t['duration_sec'] = (out_dt - in_dt).total_seconds()
        else:
            t['out_mt5_str'] = "OPEN"
            t['out_local_str'] = "OPEN"
            t['duration_sec'] = 0
            
        t['net_profit'] = t['profit'] + t['commission'] + t['swap']
        result.append(t)
        
    print(json.dumps(result))
    mt5.shutdown()

if __name__ == "__main__":
    analyze()
