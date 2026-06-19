import sys
from sqlmodel import select
from engine.db import get_session
from app.models.trades import Trade

def run():
    session = get_session()
    
    trade = session.exec(select(Trade).where(Trade.id == 152)).first()
    if trade:
        print(f"Trade #152: Direction={trade.direction}, Status={trade.status}, Opened={trade.opened_at}, Entry={trade.actual_entry}")
    else:
        print("Trade #152 not found.")
        
    session.close()

if __name__ == "__main__":
    run()
