import sys
from sqlmodel import select, Session
from app.database import engine
from app.models.trades import Trade
from app.models.signals import Signal

def check_recent_trades():
    with Session(engine) as session:
        print("Checking recent XAGI8 (IFVG) and XAGI9 (3-Candle) trades...")
        
        # Get recent XAGI8/9 signals
        signals = session.exec(
            select(Signal)
            .where(Signal.session.in_(["XAGI8", "XAGI9"]))
            .order_by(Signal.id.desc())
            .limit(10)
        ).all()
        
        if not signals:
            print("No signals found in DB for XAGI8 or XAGI9.")
            return
            
        print(f"Found {len(signals)} recent signals for XAGI8/XAGI9:\n")
        
        for sig in signals:
            trade = session.exec(select(Trade).where(Trade.signal_id == sig.id)).first()
            status = trade.status if trade else "NO TRADE"
            print(f"[{sig.timestamp}] {sig.session} -> {sig.direction} @ {sig.price_at_signal} (Status: {status})")

if __name__ == "__main__":
    check_recent_trades()
