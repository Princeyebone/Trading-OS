import MetaTrader5 as mt5
from datetime import datetime, timedelta, timezone

def analyze():
    if not mt5.initialize():
        print("MT5 initialization failed")
        return

    # User requested window: 05:36 Local to 08:30 Local
    # Since MT5 is Local + 3 hours, we query: 08:36:00 MT5 to 11:30:00 MT5 today
    year, month, day = 2026, 6, 30
    
    from_date_mt5 = datetime(year, month, day, 8, 36, 0)
    to_date_mt5 = datetime(year, month, day, 11, 30, 0)
    
    deals = mt5.history_deals_get(from_date_mt5, to_date_mt5)
    if deals is None:
        print("No deals")
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
            
        # deal.time from MT5 is a POSIX timestamp where formatting it as UTC yields EXACT MT5 Server Time
        in_mt5_dt = datetime.fromtimestamp(t['in_time_mt5'], tz=timezone.utc)
        
        # Local time is exactly 3 hours behind MT5 Server Time
        in_local_dt = in_mt5_dt - timedelta(hours=3)
        
        t['in_mt5_str'] = in_mt5_dt.strftime('%H:%M:%S')
        t['in_local_str'] = in_local_dt.strftime('%H:%M:%S')
        
        if t['out_time_mt5']:
            out_mt5_dt = datetime.fromtimestamp(t['out_time_mt5'], tz=timezone.utc)
            out_local_dt = out_mt5_dt - timedelta(hours=3)
            
            t['out_mt5_str'] = out_mt5_dt.strftime('%H:%M:%S')
            t['out_local_str'] = out_local_dt.strftime('%H:%M:%S')
            t['duration_sec'] = (out_mt5_dt - in_mt5_dt).total_seconds()
        else:
            t['out_mt5_str'] = "OPEN"
            t['out_local_str'] = "OPEN"
            t['duration_sec'] = 0
            
        t['net_profit'] = t['profit'] + t['commission'] + t['swap']
        result.append(t)
        
    mt5.shutdown()
    
    # Structure into markdown
    engines = {}
    total_profit = 0
    total_wins = 0
    total_losses = 0
    
    # Sort by time
    result.sort(key=lambda x: x['in_time_mt5'])
    
    for t in result:
        magic = t['magic']
        comment = t['comment'] if t['comment'] else "Unknown"
        engine_id = f"{magic} ({comment})"
        
        if engine_id not in engines:
            engines[engine_id] = {'profit': 0, 'wins': 0, 'losses': 0, 'trades': []}
            
        engines[engine_id]['trades'].append(t)
        
        profit = t['net_profit']
        engines[engine_id]['profit'] += profit
        total_profit += profit
        if profit > 0:
            engines[engine_id]['wins'] += 1
            total_wins += 1
        elif profit < 0:
            engines[engine_id]['losses'] += 1
            total_losses += 1
            
    md = ["# Trade Analysis Report (Last 3 Hours)\n"]
    md.append(f"**Total Net Profit**: ${total_profit:.2f}")
    md.append(f"**Win/Loss Record**: {total_wins} Wins / {total_losses} Losses\n")
    
    md.append("## Breakdown by Engine\n")
    
    # Sort engines by profit
    sorted_engines = sorted(engines.items(), key=lambda item: item[1]['profit'], reverse=True)
    
    for eng, stats in sorted_engines:
        md.append(f"### Engine: {eng}")
        md.append(f"- **Net PnL**: ${stats['profit']:.2f}")
        md.append(f"- **Win/Loss**: {stats['wins']}W / {stats['losses']}L")
        md.append("\n**Trade Log:**")
        
        for t in stats['trades']:
            profit_str = f"+${t['net_profit']:.2f}" if t['net_profit'] > 0 else f"-${abs(t['net_profit']):.2f}"
            md.append(f"- `[{t['ticket']}]` **{t['direction']}** {t['symbol']} | In: {t['in_local_str']} Local ({t['in_mt5_str']} MT5) | Out: {t['out_local_str']} Local ({t['out_mt5_str']} MT5) | PnL: **{profit_str}**")
            
        md.append("\n---\n")
        
    with open('C:\\Users\\HP\\.gemini\\antigravity-ide\\brain\\cc73fafe-f098-45f8-bdba-b67dd45c5980\\artifacts\\trade_analysis_3h.md', 'w', encoding='utf-8') as f:
        f.write("\n".join(md))
        
    print("Markdown artifact generated.")

if __name__ == "__main__":
    analyze()
