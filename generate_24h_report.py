import MetaTrader5 as mt5
from datetime import datetime, timezone, timedelta
import pandas as pd

mt5.initialize()
now = datetime.now(timezone.utc)
since = now - timedelta(hours=24)

magic_map = {
    202600: 'MomentumRunner (Core / M15)',
    202602: 'M5_MomentumRunner',
    202603: 'M1_MomentumRunner',
    202604: 'M15_MomentumRunner',
    202611: 'XAGI1_Core',
    202621: 'GI2_Candle_Pullback',
    202622: 'GI2_Asian_Short',
    202623: 'GI2_PreLondon_Long',
    202624: 'GI2_Silver',
    202631: 'GI3_Gold',
    202632: 'GI3_EURUSD',
    202710: 'EUSDI1_Core',
    202800: 'XAGI4_Trend_Scalper',
    202804: 'XAGI8_IFVG_Reversal',
    203000: 'EUSDI6_Hyper_Scalper',
    203100: 'EUSDI7_Momentum_Scalper',
}

deals = mt5.history_deals_get(since, now)
out_deals = [d for d in deals if d.entry == 1]

rows = []
for d in out_deals:
    rows.append({
        'ticket': d.ticket,
        'order': d.order,
        'position_id': d.position_id,
        'close_time': datetime.fromtimestamp(d.time, tz=timezone.utc),
        'symbol': d.symbol,
        'type': 'BUY' if d.type == 0 else 'SELL',
        'volume': d.volume,
        'price': d.price,
        'profit': round(d.profit, 2),
        'magic': d.magic,
        'strategy': magic_map.get(d.magic, f'Magic_{d.magic}'),
        'comment': d.comment
    })

df = pd.DataFrame(rows)

print('=== TOTAL METRICS (LAST 24 HOURS) ===')
total_pnl = df['profit'].sum()
wins = df[df['profit'] > 0]
losses = df[df['profit'] < 0]
win_rate = len(wins) / len(df) * 100 if len(df) > 0 else 0
profit_factor = abs(wins['profit'].sum() / losses['profit'].sum()) if abs(losses['profit'].sum()) > 0 else 0

print(f'Total Closed Deals: {len(df)}')
print(f'Total Net Profit: ${total_pnl:.2f}')
print(f'Wins: {len(wins)} (${wins["profit"].sum():.2f})')
print(f'Losses: {len(losses)} (${losses["profit"].sum():.2f})')
print(f'Win Rate: {win_rate:.1f}%')
print(f'Profit Factor: {profit_factor:.2f}')

print('\n=== PERFORMANCE BY ASSET SYMBOL ===')
by_symbol = df.groupby('symbol').agg(
    trades=('ticket', 'count'),
    net_pnl=('profit', 'sum'),
    wins=('profit', lambda x: (x > 0).sum()),
    losses=('profit', lambda x: (x < 0).sum()),
)
by_symbol['win_rate%'] = (by_symbol['wins'] / by_symbol['trades'] * 100).round(1)
print(by_symbol)

print('\n=== PERFORMANCE BY SYSTEM (WHO TOOK WHAT) ===')
by_sys = df.groupby('strategy').agg(
    trades=('ticket', 'count'),
    net_pnl=('profit', 'sum'),
    wins=('profit', lambda x: (x > 0).sum()),
    losses=('profit', lambda x: (x < 0).sum()),
)
by_sys['win_rate%'] = (by_sys['wins'] / by_sys['trades'] * 100).round(1)
by_sys['avg_trade'] = (by_sys['net_pnl'] / by_sys['trades']).round(2)
print(by_sys.sort_values(by='net_pnl', ascending=False))

print('\n=== TIMELINE (REVERSE CHRONOLOGICAL) ===')
for idx, r in df.sort_values(by='close_time', ascending=False).iterrows():
    print(f"[{r['close_time'].strftime('%Y-%m-%d %H:%M:%S')}] {r['strategy']} | {r['symbol']} {r['type']} {r['volume']} lot | Exit: {r['price']} | PnL: ${r['profit']:+.2f} | Comment: {r['comment']}")

print('\n=== CURRENT OPEN POSITIONS ===')
open_positions = mt5.positions_get()
if open_positions:
    print(f'Currently open positions: {len(open_positions)}')
    for p in open_positions:
        d_type = 'BUY' if p.type == 0 else 'SELL'
        s_name = magic_map.get(p.magic, f'Magic_{p.magic}')
        print(f'Ticket: {p.ticket} | Sym: {p.symbol} | Dir: {d_type} | Vol: {p.volume} | Open: {p.price_open} | Cur: {p.price_current} | SL: {p.sl} | TP: {p.tp} | PnL: ${p.profit:.2f} | Sys: {s_name} | Comment: {p.comment}')
else:
    print('No positions currently open.')
