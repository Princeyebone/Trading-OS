from sqlmodel import select
from engine.db import get_session
from app.models.trades import Trade

def inject():
    session = get_session()
    
    # Check if it already exists
    t = session.exec(select(Trade).where(Trade.broker_order_id == "152257042645")).first()
    if t:
        print("Already exists")
        return
        
    t = Trade(
        direction="LONG", # Or short, doesn't matter, we can look at MT5 pos
        status="OPEN",
        planned_entry=4015.00,
        actual_entry=4015.00,
        stop_loss=4010.00,
        take_profit_1=4045.00,
        take_profit_2=0.0,
        lot_size=0.01,
        broker_order_id="152257042645",
        broker="MT5",
        locked_profit_pips=0.0,
        highest_profit_pips=0.0
    )
    
    session.add(t)
    session.commit()
    print("Trade 152257042645 injected successfully!")
    
    # Also fix the stuck pending one
    stuck = session.exec(select(Trade).where(Trade.broker_order_id == "152257042632")).first()
    if stuck:
        stuck.status = "CANCELLED"
        session.add(stuck)
        session.commit()
        print("Stuck trade 152257042632 marked CANCELLED")

inject()
