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

start_time = datetime.now() - timedelta(hours=24)
history_deals = mt5.history_deals_get(start_time, datetime.now() + timedelta(days=1))

if not history_deals:
    print("# No deals found for the past 24 hours.")
    mt5.shutdown()
    sys.exit(0)

trades = {}
for deal in history_deals:
    if deal.entry == 1: 
        magic = deal.magic
        strat = MAGIC_MAP.get(magic, f"UNKNOWN_{magic}")
        profit = deal.profit + deal.commission + deal.swap
        
        if strat not in trades:
            trades[strat] = {"wins": [], "losses": [], "net_pnl": 0.0}
            
        trades[strat]["net_pnl"] += profit
        
        trade_data = {
            "ticket": deal.ticket,
            "symbol": deal.symbol,
            "volume": deal.volume,
            "price": deal.price,
            "profit": profit,
            "time": datetime.fromtimestamp(deal.time, timezone.utc).strftime('%H:%M:%S UTC')
        }
        
        if profit > 0:
            trades[strat]["wins"].append(trade_data)
        else:
            trades[strat]["losses"].append(trade_data)

artifact_path = r"C:\Users\HP\.gemini\antigravity-ide\brain\d8d2e5e9-619b-4391-a247-a11b8ae1fc03\daily_trades_analysis.md"
with open(artifact_path, "w", encoding="utf-8") as f:
    f.write("# Deep Analysis of All Trading Systems (Past 24 Hours)\n\n")
    f.write("This document breaks down every single trade taken by each algorithmic engine, categorized into Wins and Losses.\n\n")

    for strat, data in sorted(trades.items(), key=lambda x: x[1]['net_pnl'], reverse=True):
        total_trades = len(data["wins"]) + len(data["losses"])
        win_rate = (len(data["wins"]) / total_trades) * 100 if total_trades > 0 else 0
        net_pnl = data["net_pnl"]
        
        f.write(f"## {strat}\n")
        f.write(f"**Total Trades:** {total_trades} | **Win Rate:** {win_rate:.1f}% | **Net PnL:** `${net_pnl:.2f}`\n\n")
        
        if data["wins"]:
            f.write("### ✅ Winning Trades\n")
            f.write("| Ticket | Symbol | Volume | Price | PnL | Time (UTC) |\n")
            f.write("|---|---|---|---|---|---|\n")
            for w in data["wins"]:
                f.write(f"| {w['ticket']} | {w['symbol']} | {w['volume']} | {w['price']} | +${w['profit']:.2f} | {w['time']} |\n")
            f.write("\n")
            
        if data["losses"]:
            f.write("### ❌ Losing Trades\n")
            f.write("| Ticket | Symbol | Volume | Price | PnL | Time (UTC) |\n")
            f.write("|---|---|---|---|---|---|\n")
            for l in data["losses"]:
                f.write(f"| {l['ticket']} | {l['symbol']} | {l['volume']} | {l['price']} | -${abs(l['profit']):.2f} | {l['time']} |\n")
            f.write("\n")
            
        f.write("---\n\n")

print("File written successfully!")
mt5.shutdown()
