import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import logging
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger("Simulation")

def tcp_lock(profit_pips):
    profit_pts = profit_pips / 10.0
    if profit_pts >= 1.0:
        step = 1.0 + float(int((profit_pts - 1.0) // 2.0)) * 2.0
        if step == 1.0: return 10.0
        elif step == 3.0: return 20.0
        elif step == 5.0: return 40.0
        else: return (step - 2.0) * 10.0
    return 0.0

def scalp_lock(profit_pips):
    if profit_pips >= 20.0:
        steps = int((profit_pips - 20.0) // 10.0)
        return 20.0 + (steps * 10.0)
    return 0.0

def hybrid_lock(profit_pips):
    # A proposed balanced approach: Lock 10 at 20, lock 20 at 30, lock 30 at 40 (Always keep a 10 pip buffer)
    if profit_pips >= 20.0:
        steps = int((profit_pips - 20.0) // 10.0)
        return 10.0 + (steps * 10.0)
    return 0.0

def simulate_trade(df, entry_idx, direction, sl_pips, strategy_fn):
    entry_price = df.iloc[entry_idx]['close']
    locked_profit = 0.0
    
    # Static SL price
    sl_price = entry_price - (sl_pips * 0.1) if direction == 'LONG' else entry_price + (sl_pips * 0.1)
    
    for i in range(entry_idx + 1, len(df)):
        row = df.iloc[i]
        
        # Check SL hit first
        if direction == 'LONG':
            if row['low'] <= sl_price:
                return -sl_pips, "SL_HIT"
            
            # Max profit reached in this candle
            max_profit = (row['high'] - entry_price) * 10.0
            
            # Did it hit our current lock during the pullback of this candle?
            # A bit tricky with just M1. Let's assume if it hits max profit then pulls back, we check lock.
            # To be rigorous, we just look at the high. If high triggers a lock, we update lock.
            current_lock = strategy_fn(max_profit)
            if current_lock > locked_profit:
                locked_profit = current_lock
                # Update SL price natively
                sl_price = entry_price + (locked_profit * 0.1)
                
            # If low of the candle hits the trailing stop
            if row['low'] <= sl_price:
                return locked_profit, "TRAIL_HIT"
                
        else: # SHORT
            if row['high'] >= sl_price:
                return -sl_pips, "SL_HIT"
                
            max_profit = (entry_price - row['low']) * 10.0
            
            current_lock = strategy_fn(max_profit)
            if current_lock > locked_profit:
                locked_profit = current_lock
                sl_price = entry_price - (locked_profit * 0.1)
                
            if row['high'] >= sl_price:
                return locked_profit, "TRAIL_HIT"
                
    return locked_profit, "OPEN"

def run_simulation():
    if not mt5.initialize():
        logger.error("MT5 initialization failed")
        return

    symbol = "XAUUSD"
    # Get 10,000 M1 candles (~1 week of data)
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, 10000)
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    
    np.random.seed(42)
    # Pick 1000 random entry points
    entry_indices = np.random.choice(range(0, len(df) - 500), size=1000, replace=False)
    
    results = {
        "TCP (Lock 10@10)": {"pnl": 0.0, "wins": 0, "losses": 0, "avg_win": 0.0, "win_trades": []},
        "SCALP (Lock 20@20)": {"pnl": 0.0, "wins": 0, "losses": 0, "avg_win": 0.0, "win_trades": []},
        "BUFFERED (Lock 10@20)": {"pnl": 0.0, "wins": 0, "losses": 0, "avg_win": 0.0, "win_trades": []}
    }
    
    sl_pips = 30.0 # Standard SL
    
    for idx in entry_indices:
        direction = 'LONG' if np.random.rand() > 0.5 else 'SHORT'
        
        # Test TCP
        pnl_tcp, _ = simulate_trade(df, idx, direction, sl_pips, tcp_lock)
        results["TCP (Lock 10@10)"]["pnl"] += pnl_tcp
        if pnl_tcp > 0:
            results["TCP (Lock 10@10)"]["wins"] += 1
            results["TCP (Lock 10@10)"]["win_trades"].append(pnl_tcp)
        else:
            results["TCP (Lock 10@10)"]["losses"] += 1
            
        # Test SCALP
        pnl_scalp, _ = simulate_trade(df, idx, direction, sl_pips, scalp_lock)
        results["SCALP (Lock 20@20)"]["pnl"] += pnl_scalp
        if pnl_scalp > 0:
            results["SCALP (Lock 20@20)"]["wins"] += 1
            results["SCALP (Lock 20@20)"]["win_trades"].append(pnl_scalp)
        else:
            results["SCALP (Lock 20@20)"]["losses"] += 1
            
        # Test BUFFERED
        pnl_buf, _ = simulate_trade(df, idx, direction, sl_pips, hybrid_lock)
        results["BUFFERED (Lock 10@20)"]["pnl"] += pnl_buf
        if pnl_buf > 0:
            results["BUFFERED (Lock 10@20)"]["wins"] += 1
            results["BUFFERED (Lock 10@20)"]["win_trades"].append(pnl_buf)
        else:
            results["BUFFERED (Lock 10@20)"]["losses"] += 1

    logger.info("===== SIMULATION RESULTS (1000 Random Trades) =====")
    for name, stat in results.items():
        avg_win = np.mean(stat["win_trades"]) if stat["win_trades"] else 0
        wr = stat["wins"] / 1000.0 * 100
        logger.info(f"\nStrategy: {name}")
        logger.info(f"Total PnL: {stat['pnl']:.1f} pips")
        logger.info(f"Win Rate: {wr:.1f}% ({stat['wins']}W / {stat['losses']}L)")
        logger.info(f"Average Win: +{avg_win:.1f} pips")

if __name__ == "__main__":
    run_simulation()
