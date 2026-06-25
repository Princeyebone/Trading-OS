import pandas as pd
from datetime import datetime, timezone, timedelta
from engine.db import get_session
from app.models.trades import Trade, TradeOutcome
from sqlmodel import select
import MetaTrader5 as mt5

def run():
    if not mt5.initialize():
        print("MT5 Init Failed")
        return

    session = get_session()
    
    # Get all trades from today (or last 20 trades)
    trades = session.exec(select(Trade).order_by(Trade.id.desc()).limit(20)).all()
    
    print("--- HYPOTHETICAL SCALE-OUT SIMULATION ---\n")
    
    total_actual_pnl = 0.0
    total_sim_pnl = 0.0
    
    for t in reversed(trades):
        # We only care about long directional moves today
        if not t.actual_entry:
            continue
            
        outcome = session.exec(select(TradeOutcome).where(TradeOutcome.trade_id == t.id)).first()
        
        # Get M1 data from entry to close (or now)
        start_time = t.opened_at
        end_time = outcome.closed_at if outcome else datetime.now(timezone.utc)
        
        # Convert to MT5 server time (assume GMT+3/4 approx, we can just grab from position using unix)
        # But wait, mt5.copy_rates_range requires timestamps. 
        # Safer: just grab the 1000 candles before end_time and filter.
        
        rates = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_M1, 0, 500)
        if rates is None or len(rates) == 0:
            continue
            
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        
        # Simulation State
        half_closed = False
        runner_active = False
        runner_sl = t.actual_entry if t.direction == "LONG" else (t.actual_entry + 100) # Arbitrary
        runner_highest = 0.0
        
        sim_pnl_pips = 0.0
        
        # Simplistic M1 simulation
        entry = t.actual_entry
        dir_mult = 1 if t.direction == "LONG" else -1
        
        # We find the index where trade started
        # For simplicity, let's just use the max excursion directly if it's already recorded
        # The db has t.highest_profit_pips.
        
        # Let's do a fast mathematical simulation using the exact M1 candles
        for _, row in df.iterrows():
            # If the candle is before our entry, skip
            # We don't have exact timezone mapping easily, so we match price instead
            pass
            
        # Instead of iterating candles (which can be misaligned), we know:
        # 1. The trade reached `t.highest_profit_pips`.
        # 2. Did it hit 10 pips?
        if t.highest_profit_pips >= 10.0:
            # Under new logic, 50% is closed at exactly +10 pips
            sim_pnl_pips += (10.0 * 0.5)
            
            # The runner (remaining 50%)
            # The runner reached highest_profit_pips. 
            # With a 30-pip trailing stop, the runner would be stopped out at (highest_profit_pips - 30)
            # OR if it's currently open, it's still running.
            
            if t.status == "OPEN":
                # It's still running right now!
                runner_current = t.highest_profit_pips # or current profit
                # Let's assume it closes at max drawdown from peak, bounded by BE
                # For an OPEN trade, let's just use its locked profit for now
                current_profit = t.locked_profit_pips # rough estimate
                runner_pnl = current_profit
                sim_pnl_pips += (runner_pnl * 0.5)
                status_text = "Runner still OPEN"
            else:
                # Trade is closed.
                # It trailed by 30 pips. So it stopped out at highest - 30.
                # But it cannot stop out worse than Break-Even (0 pips)
                runner_stop_out = max(0.0, t.highest_profit_pips - 30.0)
                sim_pnl_pips += (runner_stop_out * 0.5)
                status_text = f"Runner Stopped @ +{runner_stop_out:.1f} pips"
                
        else:
            # Never reached 10 pips. Took the full loss.
            # Assuming SL hit.
            if outcome and outcome.pnl_pips:
                sim_pnl_pips = outcome.pnl_pips
            else:
                sim_pnl_pips = -120.0 # Full stop loss
            status_text = "Full SL Hit"

        actual_pips = outcome.pnl_pips if outcome else t.locked_profit_pips
        
        # Calculate $ amounts roughly (assuming 0.1 lots = $1 per pip)
        # We will just print pips for accuracy.
        print(f"Trade #{t.id} [{t.direction}]")
        print(f"  Max Excursion: +{t.highest_profit_pips:.1f} pips")
        print(f"  Actual PnL:    {actual_pips:+.1f} pips")
        print(f"  Simulated PnL: {sim_pnl_pips:+.1f} pips ({status_text})")
        print(f"  Difference:    {sim_pnl_pips - actual_pips:+.1f} pips")
        print("-" * 40)
        
        total_actual_pnl += actual_pips
        total_sim_pnl += sim_pnl_pips

    print(f"\n--- SUMMARY OF LAST 20 TRADES ---")
    print(f"Total ACTUAL Profit:    +{total_actual_pnl:.1f} pips")
    print(f"Total SIMULATED Profit: +{total_sim_pnl:.1f} pips")
    print(f"NET GAIN FROM NEW LOGIC: +{total_sim_pnl - total_actual_pnl:.1f} pips")

    session.close()
    mt5.shutdown()

if __name__ == "__main__":
    run()
