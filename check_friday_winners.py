import MetaTrader5 as mt5
from datetime import datetime, timezone
import pandas as pd

mt5.initialize()

# Friday: 2026-09-18 00:00 to 23:59 UTC
fri_start = datetime(2026, 9, 18, 0, 0, 0, tzinfo=timezone.utc)
fri_end = datetime(2026, 9, 18, 23, 59, 59, tzinfo=timezone.utc)

deals = mt5.history_deals_get(fri_start, fri_end)
in_deals = {d.position_id: d for d in deals if d.entry == 0}
out_deals = [d for d in deals if d.entry == 1]

magic_map = {
    203000: 'EUSDI6_Hyper_Scalper',
    202603: 'M5_MomentumRunner',
    202604: 'M15_MomentumRunner',
    202622: 'GI2_Asian_Short',
    202623: 'GI2_PreLondon_Long',
}

rows = []
for d in out_deals:
    d_in = in_deals.get(d.position_id)
    real_magic = d_in.magic if d_in else d.magic
    real_comment = d_in.comment if d_in else d.comment
    
    if real_magic in magic_map:
        rows.append({
            'ticket': d.ticket,
            'position_id': d.position_id,
            'time': datetime.fromtimestamp(d.time, tz=timezone.utc),
            'strategy': magic_map[real_magic],
            'symbol': d.symbol,
            'profit': round(d.profit, 2),
            'magic': real_magic,
            'in_comment': real_comment,
            'exit_comment': d.comment
        })

df = pd.DataFrame(rows)

print("=================================================================")
print("  FRIDAY (2026-09-18) PERFORMANCE FOR THE TARGET WINNING SYSTEMS")
print("=================================================================")

for strat in ['EUSDI6_Hyper_Scalper', 'M5_MomentumRunner', 'M15_MomentumRunner', 'GI2_Asian_Short', 'GI2_PreLondon_Long']:
    sdf = df[df['strategy'] == strat]
    if not sdf.empty:
        trades = len(sdf)
        wins = len(sdf[sdf['profit'] > 0])
        losses = len(sdf[sdf['profit'] < 0])
        pnl = sdf['profit'].sum()
        wr = (wins / trades * 100)
        print(f"\n[{strat}]")
        print(f"  Trades: {trades} | Wins: {wins} | Losses: {losses} | Win Rate: {wr:.1f}% | Net PnL: ${pnl:+.2f}")
        for idx, r in sdf.iterrows():
            print(f"    - {r['time'].strftime('%H:%M:%S UTC')} | {r['symbol']} | PnL: ${r['profit']:+.2f} | Exit: {r['exit_comment']}")
    else:
        print(f"\n[{strat}]")
        print(f"  No trades executed on Friday (2026-09-18).")
