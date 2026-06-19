import sys
from sqlmodel import select
from engine.db import get_session
from app.models.signals import Signal
from app.models.trades import Trade

def run():
    session = get_session()
    
    statement = select(Trade, Signal).join(Signal)
    results = session.exec(statement).all()
    
    if not results:
        print("No trades found in the database.")
        session.close()
        return
        
    stats = {}
    
    for trade, signal in results:
        setup = signal.type if signal.type else "UNKNOWN"
        if setup not in stats:
            stats[setup] = {"taken": 0, "wins": 0, "losses": 0, "be": 0, "open": 0}
            
        stats[setup]["taken"] += 1
        
        status = trade.status
        if status == "WIN":
            stats[setup]["wins"] += 1
        elif status == "LOSS":
            stats[setup]["losses"] += 1
        elif status == "BE" or status == "SCRATCH":
            stats[setup]["be"] += 1
        else:
            stats[setup]["open"] += 1
            
    print("="*60)
    print(f"{'SETUP TYPE':<25} | {'TAKEN':<5} | {'WINS':<4} | {'LOSS':<4} | {'BE':<3} | {'WIN %':<6}")
    print("="*60)
    
    for setup, data in sorted(stats.items(), key=lambda x: x[1]["taken"], reverse=True):
        taken = data["taken"]
        wins = data["wins"]
        losses = data["losses"]
        be = data["be"]
        
        resolved = wins + losses
        win_rate = (wins / resolved * 100) if resolved > 0 else 0.0
        
        print(f"{setup:<25} | {taken:<5} | {wins:<4} | {losses:<4} | {be:<3} | {win_rate:.1f}%")
        
    print("="*60)
    session.close()

if __name__ == "__main__":
    run()
