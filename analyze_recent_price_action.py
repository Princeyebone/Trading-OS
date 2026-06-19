import pandas as pd
from engine.db import get_session
from app.models.trades import Trade, TradeOutcome
from sqlmodel import select
import MetaTrader5 as mt5

def run():
    if not mt5.initialize():
        print("MT5 Init Failed")
        return
        
    print("--- PRICE ACTION (Last 10 M1 Candles) ---")
    rates_m1 = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_M1, 0, 10)
    if rates_m1 is not None and len(rates_m1) > 0:
        df1 = pd.DataFrame(rates_m1)
        df1['time'] = pd.to_datetime(df1['time'], unit='s')
        for _, row in df1.iterrows():
            print(f"Time: {row['time'].strftime('%H:%M')} | O: {row['open']:.2f} | H: {row['high']:.2f} | L: {row['low']:.2f} | C: {row['close']:.2f} | Spread: {row['spread']}")
            
    print("\n--- RECENT TRADES (Last 5) ---")
    session = get_session()
    trades = session.exec(select(Trade).order_by(Trade.id.desc()).limit(5)).all()
    
    for t in trades:
        outcome = session.exec(select(TradeOutcome).where(TradeOutcome.trade_id == t.id)).first()
        print(f"Trade {t.id} [{t.direction}] Entry: {t.actual_entry}")
        print(f"  Status: {t.status} | Locked Profit: {t.locked_profit_pips/10:.1f} pts | Highest reached: {t.highest_profit_pips/10:.1f} pts")
        if outcome:
            print(f"  Exit: {outcome.exit_price} | PnL: {outcome.pnl_dollars} | Reason: {outcome.exit_reason}")
        print("-" * 50)
        
    session.close()
    mt5.shutdown()

if __name__ == "__main__":
    run()
