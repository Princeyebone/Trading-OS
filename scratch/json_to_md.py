import json

def process():
    try:
        with open('scratch/3h_trades.json', 'r', encoding='utf-16le') as f:
            data = json.load(f)
    except Exception:
        with open('scratch/3h_trades.json', 'r', encoding='utf-8-sig') as f:
            data = json.load(f)
            
    if "error" in data:
        print("Error:", data)
        return
        
    engines = {}
    total_profit = 0
    total_wins = 0
    total_losses = 0
    
    for t in data:
        magic = t['magic']
        comment = t['comment']
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
            
    # Build markdown
    md = ["# Last 3 Hours Trade Analysis\n"]
    md.append(f"**Total Net Profit**: ${total_profit:.2f}")
    md.append(f"**Win/Loss Record**: {total_wins} Wins / {total_losses} Losses\n")
    
    md.append("## Engine Performance\n")
    for eng, stats in engines.items():
        md.append(f"### {eng}")
        md.append(f"- **Net Profit**: ${stats['profit']:.2f}")
        md.append(f"- **Win/Loss**: {stats['wins']}W / {stats['losses']}L")
        md.append("\n**Trades:**")
        
        for t in stats['trades']:
            profit_str = f"+${t['net_profit']:.2f}" if t['net_profit'] > 0 else f"-${abs(t['net_profit']):.2f}"
            md.append(f"- `[{t['ticket']}]` **{t['direction']}** {t['symbol']} | In: {t['in_local_str']} Local ({t['in_mt5_str']} MT5) | Out: {t['out_local_str']} Local ({t['out_mt5_str']} MT5) | PnL: **{profit_str}**")
            
        md.append("\n---\n")
        
    with open('artifacts/trade_analysis_3h.md', 'w', encoding='utf-8') as f:
        f.write("\n".join(md))
        
    print("Done")

if __name__ == "__main__":
    process()
