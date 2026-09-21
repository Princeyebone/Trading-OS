import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def run_silver_2to1_daily_lock():
    if not mt5.initialize():
        return
    r = mt5.copy_rates_from_pos('XAGUSD', mt5.TIMEFRAME_M5, 0, 8000)
    mt5.shutdown()
    df = pd.DataFrame(r)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df['date'] = df['time'].dt.date
    c = df['close'].values
    h = df['high'].values
    l = df['low'].values
    o = df['open'].values
    n = len(df)
    mult = 5000

    mid = pd.Series(c).rolling(20).mean().values
    std = pd.Series(c).rolling(20).std().values
    upper = mid + 2.2 * std
    lower = mid - 2.2 * std
    delta = pd.Series(c).diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rsi = (100 - (100 / (1 + (gain / (loss + 1e-9))))).values

    daily = {}
    cur_day = None
    dpnl = 0.0
    dtrades = []
    locked = False
    last_exit = -1

    for i in range(25, n-35):
        d = df['date'].iloc[i]
        hr = df['time'].iloc[i].hour
        if d != cur_day:
            if cur_day:
                daily[cur_day] = {'pnl': dpnl, 'trades': len(dtrades), 'w': sum(1 for x in dtrades if x>0), 'l': sum(1 for x in dtrades if x<=0)}
            cur_day = d
            dpnl = 0.0
            dtrades = []
            locked = False
        
        if locked or i <= last_exit or not (7 <= hr <= 18):
            continue
            
        long_c = (c[i-1] < lower[i-1]) and (rsi[i-1] < 26)
        short_c = (c[i-1] > upper[i-1]) and (rsi[i-1] > 74)
        
        lot = 0.05
        if long_c:
            entry = o[i]
            tp = mid[i-1]
            dist = tp - entry
            if dist < 0.03: continue
            sl = entry - 0.50 * dist # 2:1 RR! Loss is cut strictly in half!
            pnl = 0.0
            for k in range(i, min(i+35, n)):
                if l[k] <= sl:
                    pnl = (sl - entry) * mult * lot
                    last_exit = k; break
                elif h[k] >= tp:
                    pnl = (tp - entry) * mult * lot
                    last_exit = k; break
            else:
                pnl = (c[min(i+35, n)-1] - entry) * mult * lot
                last_exit = min(i+35, n)-1
                
            dpnl += pnl
            dtrades.append(pnl)
            if dpnl > 0: locked = True
            
        elif short_c:
            entry = o[i]
            tp = mid[i-1]
            dist = entry - tp
            if dist < 0.03: continue
            sl = entry + 0.50 * dist
            pnl = 0.0
            for k in range(i, min(i+35, n)):
                if h[k] >= sl:
                    pnl = (entry - sl) * mult * lot
                    last_exit = k; break
                elif l[k] <= tp:
                    pnl = (entry - tp) * mult * lot
                    last_exit = k; break
            else:
                pnl = (entry - c[min(i+35, n)-1]) * mult * lot
                last_exit = min(i+35, n)-1
                
            dpnl += pnl
            dtrades.append(pnl)
            if dpnl > 0: locked = True

    res = pd.DataFrame.from_dict(daily, orient='index')
    res = res[res['trades'] > 0]
    g = (res['pnl'] > 0).sum()
    print(f"Total Active Trading Days: {len(res)}")
    print(f"Green Days: {g} of {len(res)} ({g/len(res)*100:.1f}%)")
    print(f"Total PnL: ${res['pnl'].sum():.2f}")
    for idx, r in res.iterrows():
        st = "GREEN (SESSION LOCKED)" if r['pnl'] > 0 else "RED"
        print(f"  {idx} | Trades: {int(r['trades']):2} ({int(r['w'])}W/{int(r['l'])}L) | PnL: ${r['pnl']:+8.2f} [{st}]")

run_silver_2to1_daily_lock()
