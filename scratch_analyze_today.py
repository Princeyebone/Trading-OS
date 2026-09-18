import sys
import os
from datetime import datetime, timezone, timedelta
import MetaTrader5 as mt5
from dotenv import load_dotenv

load_dotenv(dotenv_path="c:/Users/HP/OneDrive/Desktop/tb/backend/.env")

login = int(os.getenv("MT5_LOGIN", 0))
password = os.getenv("MT5_PASSWORD", "")
server = os.getenv("MT5_SERVER", "")

if not mt5.initialize(login=login, password=password, server=server):
    print("MT5 Init Failed:", mt5.last_error())
    sys.exit(1)

MAGIC_MAP = {
    202600: "XAGI1",  202601: "XAGI1-Swing",
    202602: "XAGI2",  202603: "XAGI3",
    202604: "XAGI4",  202700: "XAGI3",
    202800: "XAGI5",  202900: "XAGI6",
    202808: "XAGI8-IFVG", 202809: "XAGI9-3Candle",
    203000: "EUSDI6", 203100: "EUSDI7",
    203200: "GI2",    203300: "GI3",
}

# Fetch the last 24 hours of deals
start_time = datetime.now() - timedelta(hours=24) 
history_deals = mt5.history_deals_get(start_time, datetime.now() + timedelta(days=1))

if not history_deals:
    print("No deals found for the past 24 hours.")
    mt5.shutdown()
    sys.exit(0)

# Filter out non-trading deals (deposits/withdrawals)
trades = {}
for deal in history_deals:
    # Deal entry types: 0 (IN), 1 (OUT), 2 (INOUT), 3 (OUT_BY)
    # We only care about OUT deals (closing a position) to evaluate PnL of completed trades
    if deal.entry == 1: 
        magic = deal.magic
        strat = MAGIC_MAP.get(magic, f"UNKNOWN_{magic}")
        profit = deal.profit + deal.commission + deal.swap
        
        if strat not in trades:
            trades[strat] = {"count": 0, "wins": 0, "losses": 0, "pnl": 0.0, "details": []}
            
        trades[strat]["count"] += 1
        trades[strat]["pnl"] += profit
        if profit > 0:
            trades[strat]["wins"] += 1
        else:
            trades[strat]["losses"] += 1
            
        trades[strat]["details"].append({
            "ticket": deal.ticket,
            "symbol": deal.symbol,
            "profit": profit,
            "time": datetime.fromtimestamp(deal.time, timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        })

print("STRATEGY_PERFORMANCE_SUMMARY")
for strat, stats in trades.items():
    win_rate = (stats['wins'] / stats['count']) * 100 if stats['count'] > 0 else 0
    print(f"Strat: {strat} | Trades: {stats['count']} | Win Rate: {win_rate:.1f}% | Net PnL: ${stats['pnl']:.2f}")

print("\n--- DETAILED DEALS ---")
for strat, stats in trades.items():
    for d in stats["details"]:
        print(f"{strat} | Ticket: {d['ticket']} | Symbol: {d['symbol']} | PnL: ${d['profit']:.2f} | Time: {d['time']}")

mt5.shutdown()
