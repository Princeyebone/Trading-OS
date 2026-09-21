import MetaTrader5 as mt5
from datetime import datetime, timezone, timedelta
import pandas as pd

mt5.initialize()
now = datetime.now(timezone.utc)
# Start of today (Monday, 2026-09-21 00:00:00 UTC)
start_of_today = datetime(now.year, now.month, now.day, 0, 0, 0, tzinfo=timezone.utc)

magic_map = {
    202600: 'MomentumRunner (Core / M15)',
    202602: 'M15_FVG_Sniper (MomentumRunner)',
    202603: 'M5_MomentumRunner',
    202604: 'M15_MomentumRunner',
    202611: 'XAUUSD-i1-Core (Scalper)',
    202621: 'GI2_Candle_Pullback',
    202622: 'GI2_Asian_Short',
    202623: 'GI2_PreLondon_Long',
    202624: 'GI2_Silver',
    202631: 'GI3_Gold',
    202632: 'GI3_EURUSD',
    202700: 'XAGI3_Tape_Sweep',
    202702: 'XAGI2_Silver_EMA_Trend',
    202710: 'EUSDI1_Core',
    202800: 'XAGI4_Trend_Scalper',
    202804: 'XAGI8_IFVG_Reversal',
    202900: 'XAGI5_Volume_Scalper',
    203000: 'EUSDI6_Hyper_Scalper (EURUSD)',
    203100: 'EUSDI7_Momentum_Scalper (EURUSD)',
    203200: 'XAUI6_Hyper_Scalper (Gold M1)',
}

deals = mt5.history_deals_get(start_of_today, now)
out_deals = [d for d in deals if d.entry == 1]
in_deals = {d.position_id: d for d in deals if d.entry == 0}

rows = []
for d in out_deals:
    d_in = in_deals.get(d.position_id)
    real_magic = d_in.magic if d_in else d.magic
    real_comment = d_in.comment if d_in else d.comment
    
    rows.append({
        'ticket': d.ticket,
        'position_id': d.position_id,
        'close_time': datetime.fromtimestamp(d.time, tz=timezone.utc),
        'symbol': d.symbol,
        'profit': round(d.profit, 2),
        'real_magic': real_magic,
        'strategy': magic_map.get(real_magic, f'Magic_{real_magic}'),
        'in_comment': real_comment,
        'exit_comment': d.comment
    })

df = pd.DataFrame(rows)

acc = mt5.account_info()
print("=================================================================")
print(f"       DAILY PERFORMANCE AUDIT — MONDAY {start_of_today.strftime('%Y-%m-%d')}")
print(f"       Account: {acc.login} | Server: {acc.server}")
print(f"       Balance: ${acc.balance:.2f} | Equity: ${acc.equity:.2f} | Floating: ${acc.profit:.2f}")
print("=================================================================")

total_trades = len(df)
total_pnl = df['profit'].sum() if not df.empty else 0.0
wins = df[df['profit'] > 0] if not df.empty else pd.DataFrame()
losses = df[df['profit'] < 0] if not df.empty else pd.DataFrame()
win_rate = (len(wins) / total_trades * 100) if total_trades > 0 else 0
gross_profit = wins['profit'].sum() if not wins.empty else 0.0
gross_loss = abs(losses['profit'].sum()) if not losses.empty else 0.0
profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)

print(f"Total Closed Positions Today: {total_trades}")
print(f"Net Realized PnL: ${total_pnl:.2f}")
print(f"Win Rate: {win_rate:.1f}% ({len(wins)} Wins / {len(losses)} Losses)")
print(f"Profit Factor: {profit_factor:.2f} (Gross Profit: +${gross_profit:.2f} | Gross Loss: -${gross_loss:.2f})")

print("\n--- PERFORMANCE BY ASSET SYMBOL TODAY ---")
if not df.empty:
    by_sym = df.groupby('symbol').agg(
        trades=('ticket', 'count'),
        net_pnl=('profit', 'sum'),
        wins=('profit', lambda x: (x > 0).sum()),
        losses=('profit', lambda x: (x < 0).sum()),
    )
    by_sym['win_rate%'] = (by_sym['wins'] / by_sym['trades'] * 100).round(1)
    print(by_sym.to_string())

print("\n--- WHO IS WINNING VS WHO IS BLEEDING US TODAY (BY SYSTEM) ---")
if not df.empty:
    by_strat = df.groupby('strategy').agg(
        trades=('ticket', 'count'),
        net_pnl=('profit', 'sum'),
        wins=('profit', lambda x: (x > 0).sum()),
        losses=('profit', lambda x: (x < 0).sum()),
    )
    by_strat['win_rate%'] = (by_strat['wins'] / by_strat['trades'] * 100).round(1)
    by_strat['avg_trade'] = (by_strat['net_pnl'] / by_strat['trades']).round(2)
    print(by_strat.sort_values(by='net_pnl', ascending=True).to_string())

print("\n--- CURRENT FLOATING OPEN POSITIONS IN MT5 ---")
open_pos = mt5.positions_get()
if open_pos:
    for p in open_pos:
        side = "BUY" if p.type == 0 else "SELL"
        s_name = magic_map.get(p.magic, f"Magic_{p.magic}")
        print(f"Pos #{p.ticket} | Sym: {p.symbol} | Dir: {side} | Lots: {p.volume} | Open: {p.price_open} | Cur: {p.price_current} | SL: {p.sl} | TP: {p.tp} | Profit: ${p.profit:.2f} | Sys: {s_name} ({p.comment})")
else:
    print("No open positions floating right now.")
