import sys
from datetime import datetime, date
sys.path.insert(0, "c:/Users/HP/OneDrive/Desktop/tb/backend")
from engine.db import get_session
from app.models.trades import Trade, TradeOutcome
from app.models.signals import Signal
from sqlmodel import select

def get_daily_stats():
    session = get_session()
    from datetime import datetime, timedelta
    today = datetime.now()
    yesterday = today - timedelta(hours=24)
    
    outcomes = session.exec(select(TradeOutcome)).all()
    
    systems = {}
    target_pips = 0.0
    
    for outcome in outcomes:
        if outcome.closed_at and outcome.closed_at >= yesterday:
            t = session.get(Trade, outcome.trade_id)
            if not t: continue
            
            if t.signal_id:
                sig = session.get(Signal, t.signal_id)
                system_name = sig.session if sig else "Unknown"
            elif t.system:
                system_name = t.system.replace("Sys #", "")
            else:
                system_name = "Manual/Orphan"
                
            if "Magic#0" in system_name or system_name == "Unknown":
                system_name = "Manual/Orphan (Pre-Fix Bug)"
                
            # Rename SCALP to GI1 (SCALP)
            if system_name == "SCALP":
                system_name = "GI1 (SCALP)"
                
            if system_name not in systems:
                systems[system_name] = {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0, "pips": 0.0}
                
            systems[system_name]["trades"] += 1
            
            pips = float(outcome.pnl_pips) if outcome.pnl_pips else 0.0
            pnl = float(outcome.pnl_dollars) if outcome.pnl_dollars else 0.0
            
            systems[system_name]["pips"] += pips
            systems[system_name]["pnl"] += pnl
            
            if pnl > 0 or pips > 0:
                systems[system_name]["wins"] += 1
            else:
                systems[system_name]["losses"] += 1
                
            # Accumulate targeted pips
            if system_name in ["GI1 (SCALP)", "EUSDI6"]:
                target_pips += pips

    print(f"=== Trading Analysis for {today} ===")
    for sys_name, stats in sorted(systems.items()):
        winrate = (stats['wins'] / stats['trades']) * 100 if stats['trades'] > 0 else 0
        print(f"System: {sys_name}")
        print(f"  Trades: {stats['trades']}")
        print(f"  Wins: {stats['wins']}")
        print(f"  Losses: {stats['losses']}")
        print(f"  Win Rate: {winrate:.1f}%")
        print(f"  Net Pips: {stats['pips']:.1f}")
        print(f"  Actual PnL: ${stats['pnl']:.2f}")
        print()
    
    print(f"\n--- $10 CENT ACCOUNT PROJECTIONS (GI1 + EUSDI6 ONLY) ---")
    print(f"Based on {target_pips:.1f} net pips captured today by GI1 and EUSDI6:")
    print("1. Very Safe (0.1 Cent Lots / 1 cent per pip):")
    print(f"   Profit: ${(target_pips * 0.01):.2f} (Account grows to ${(10 + target_pips * 0.01):.2f})")
    
    print("2. Moderate (0.5 Cent Lots / 5 cents per pip):")
    print(f"   Profit: ${(target_pips * 0.05):.2f} (Account grows to ${(10 + target_pips * 0.05):.2f})")
    
    print("3. Aggressive (1.0 Cent Lots / 10 cents per pip):")
    print(f"   Profit: ${(target_pips * 0.10):.2f} (Account grows to ${(10 + target_pips * 0.10):.2f})")

if __name__ == "__main__":
    get_daily_stats()
