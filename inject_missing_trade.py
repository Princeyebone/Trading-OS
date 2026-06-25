from sqlmodel import select
from engine.db import get_session
from app.models.trades import Trade
from datetime import datetime, timezone

def inject():
    session = get_session()
    
    # Check if it already exists
    t = session.exec(select(Trade).where(Trade.broker_order_id == "152256672691")).first()
    if t:
        print("Already exists")
        return
        
    t = Trade(
        direction="SHORT",
        status="OPEN",
        planned_entry=4011.86,
        actual_entry=4011.86,
        stop_loss=4015.00, # Estimated SL
        take_profit_1=3980.00,
        take_profit_2=0.0,
        lot_size=0.01,
        broker_order_id="152256672691",
        broker="MT5",
        locked_profit_pips=0.0,
        highest_profit_pips=0.0
    )
    
    session.add(t)
    session.commit()
    print("Trade 152256672691 injected successfully!")

inject()
