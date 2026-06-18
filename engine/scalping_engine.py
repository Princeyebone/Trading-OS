"""
engine/scalping_engine.py — Dedicated M5 Gold Scalping System
"""

import pandas as pd
import ta
import logging

logger = logging.getLogger("engine.scalping")

def calculate_rsi(series: pd.Series, window: int = 14) -> pd.Series:
    return ta.momentum.rsi(series, window=window)

def calculate_atr(data: pd.DataFrame, period: int = 14) -> pd.Series:
    high = data['high']
    low = data['low']
    close = data['close']
    tr1 = high - low
    tr2 = abs(high - close.shift())
    tr3 = abs(low - close.shift())
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()

def find_next_resistance(data: pd.DataFrame, current_idx: int, min_distance: float=5.0) -> float | None:
    future_highs = data['high'].iloc[current_idx:current_idx+10]
    current_close = data['close'].iloc[current_idx]
    for high in future_highs:
        if high > current_close + min_distance:
            return float(high)
    return None

def find_next_support(data: pd.DataFrame, current_idx: int, min_distance: float=5.0) -> float | None:
    future_lows = data['low'].iloc[current_idx:current_idx+10]
    current_close = data['close'].iloc[current_idx]
    for low in future_lows:
        if low < current_close - min_distance:
            return float(low)
    return None

def detect_breakout_scalp(m5_data: pd.DataFrame, current_idx: int) -> tuple[str | None, dict | None]:
    """
    Less strict breakout scalping - works with smaller moves.
    """
    if current_idx < 15:
        return None, None
        
    current = m5_data.iloc[current_idx]
    current_price = float(current['close'])
    
    # 1. Identify recent levels (15 candles)
    recent_high = float(m5_data['high'].iloc[current_idx-15:current_idx].max())
    recent_low = float(m5_data['low'].iloc[current_idx-15:current_idx].min())
    
    # 2. BREAKOUT DETECTION (more flexible)
    break_above = current_price > recent_high + 0.3
    break_below = current_price < recent_low - 0.3
    
    # 3. MOMENTUM
    if current_idx >= 5:
        price_change_5 = current_price - float(m5_data['close'].iloc[current_idx-5])
    else:
        price_change_5 = 0.0
        
    # 4. REJECTION CHECK
    candle_range = float(current['high'] - current['low'])
    bullish_rejection = False
    bearish_rejection = False
    if candle_range > 0:
        upper_wick = float(current['high'] - max(current['open'], current['close']))
        lower_wick = float(min(current['open'], current['close']) - current['low'])
        bullish_rejection = lower_wick / candle_range > 0.5
        bearish_rejection = upper_wick / candle_range > 0.5
        
    # 5. RSI (10 period)
    rsi_series = calculate_rsi(m5_data['close'].iloc[:current_idx+1], 10)
    current_rsi = float(rsi_series.iloc[-1]) if len(rsi_series) > 0 else 50.0
    
    # ===== BULLISH BREAKOUT =====
    if break_above and price_change_5 > 0:
        next_resistance = find_next_resistance(m5_data, current_idx, min_distance=5)
        if next_resistance is None or (next_resistance - current_price) > 5.0:
            return 'BULLISH', {
                'breakout_type': 'RESISTANCE_BREAK',
                'level': round(recent_high, 2),
                'rsi': round(current_rsi, 2),
                'momentum': round(price_change_5, 2)
            }
            
    # ===== BEARISH BREAKOUT =====
    if break_below and price_change_5 < 0:
        next_support = find_next_support(m5_data, current_idx, min_distance=5)
        if next_support is None or (current_price - next_support) > 5.0:
            return 'BEARISH', {
                'breakout_type': 'SUPPORT_BREAK',
                'level': round(recent_low, 2),
                'rsi': round(current_rsi, 2),
                'momentum': round(price_change_5, 2)
            }
            
    # ===== PULLBACK SCALP =====
    if not break_above and current_price < recent_high and current_price > (recent_high - 2.0):
        if current_idx >= 5:
            touched_high = float(m5_data['high'].iloc[current_idx-5:current_idx].max()) > recent_high
            if touched_high and bullish_rejection:
                return 'BULLISH', {
                    'breakout_type': 'PULLBACK_TO_BREAK',
                    'level': round(recent_high, 2),
                    'rsi': round(current_rsi, 2),
                    'momentum': round(price_change_5, 2)
                }
                
    if not break_below and current_price > recent_low and current_price < (recent_low + 2.0):
        if current_idx >= 5:
            touched_low = float(m5_data['low'].iloc[current_idx-5:current_idx].min()) < recent_low
            if touched_low and bearish_rejection:
                return 'BEARISH', {
                    'breakout_type': 'PULLBACK_TO_BREAK',
                    'level': round(recent_low, 2),
                    'rsi': round(current_rsi, 2),
                    'momentum': round(price_change_5, 2)
                }

    return None, None

def detect_fibonacci_scalp(m5_data: pd.DataFrame, current_idx: int, lookback: int=30) -> tuple[str | None, dict | None]:
    """
    Detect Fibonacci retracement scalping setups.
    """
    if current_idx < lookback:
        return None, None
        
    current = m5_data.iloc[current_idx]
    current_price = float(current['close'])
    
    swing_high = float(m5_data['high'].iloc[current_idx-lookback:current_idx].max())
    swing_low = float(m5_data['low'].iloc[current_idx-lookback:current_idx].min())
    
    fib_range = swing_high - swing_low
    if fib_range < 3.0:
        return None, None
        
    fib_382 = swing_low + fib_range * 0.382
    fib_500 = swing_low + fib_range * 0.500
    fib_618 = swing_low + fib_range * 0.618
    
    at_fib_382 = abs(current_price - fib_382) < 0.5
    at_fib_500 = abs(current_price - fib_500) < 0.5
    at_fib_618 = abs(current_price - fib_618) < 0.5
    
    if current_idx >= 15:
        m15_trend = float(m5_data['close'].iloc[current_idx]) > float(m5_data['close'].iloc[current_idx-15])
    else:
        m15_trend = True
        
    candle_range = float(current['high'] - current['low'])
    bullish_rejection = False
    bearish_rejection = False
    if candle_range > 0:
        upper_wick = float(current['high'] - max(current['open'], current['close']))
        lower_wick = float(min(current['open'], current['close']) - current['low'])
        bullish_rejection = lower_wick / candle_range > 0.5
        bearish_rejection = upper_wick / candle_range > 0.5
        
    rsi_series = calculate_rsi(m5_data['close'].iloc[:current_idx+1], 14)
    rsi = float(rsi_series.iloc[-1]) if len(rsi_series) > 0 else 50.0
    
    # BULLISH FIB
    if (at_fib_382 or at_fib_618) and m15_trend:
        if bullish_rejection and rsi < 50:
            fib_level = fib_382 if at_fib_382 else fib_618
            return 'BULLISH', {
                'setup_type': 'FIBONACCI',
                'level': round(fib_level, 2),
                'rsi': round(rsi, 2),
                'trend': 'UP'
            }
            
    # BEARISH FIB
    if (at_fib_382 or at_fib_618) and not m15_trend:
        if bearish_rejection and rsi > 50:
            fib_level = fib_382 if at_fib_382 else fib_618
            return 'BEARISH', {
                'setup_type': 'FIBONACCI',
                'level': round(fib_level, 2),
                'rsi': round(rsi, 2),
                'trend': 'DOWN'
            }
            
    return None, None

def detect_ema_pullback_scalp(m5_data: pd.DataFrame, current_idx: int, lookback: int=20) -> tuple[str | None, dict | None]:
    """
    EMA Pullback Scalp Setup.
    Catches price pulling back to EMA20 and bouncing, scaled by ATR.
    """
    if current_idx < 50:
        return None, None
        
    current = m5_data.iloc[current_idx]
    current_price = float(current['close'])
    
    # 1. Calculate EMAs and ATR
    ema20 = float(m5_data['close'].rolling(20).mean().iloc[current_idx])
    ema50 = float(m5_data['close'].rolling(50).mean().iloc[current_idx])
    atr = float(calculate_atr(m5_data.iloc[:current_idx+1], 14).iloc[-1])
    
    # 2. Distance to EMA20 using ATR context
    dist_to_ema20 = abs(current_price - ema20)
    near_ema20 = dist_to_ema20 < max(0.5, atr * 0.5)
    
    if not near_ema20:
        return None, None
        
    # 4. Trend detection (M15 trend via EMA alignment)
    m15_trend = ema20 > ema50 if current_price > ema20 else ema20 < ema50
    
    # 5. Rejection candle
    candle_range = float(current['high'] - current['low'])
    bullish_rejection = False
    bearish_rejection = False
    if candle_range > 0:
        upper_wick = float(current['high'] - max(current['open'], current['close']))
        lower_wick = float(min(current['open'], current['close']) - current['low'])
        bullish_rejection = lower_wick / candle_range > 0.5
        bearish_rejection = upper_wick / candle_range > 0.5
        
    # 6. RSI
    rsi_series = calculate_rsi(m5_data['close'].iloc[:current_idx+1], 14)
    rsi = float(rsi_series.iloc[-1]) if len(rsi_series) > 0 else 50.0
    
    # ===== BULLISH EMA SCALP =====
    if m15_trend and ema20 > ema50:
        if bullish_rejection and rsi < 60:
            price_bounce = current_price > float(m5_data['close'].iloc[current_idx-1])
            if price_bounce:
                return 'BULLISH', {
                    'setup_type': 'EMA_PULLBACK',
                    'level': round(ema20, 2),
                    'rsi': round(rsi, 2),
                    'trend': 'UP'
                }
                
    # ===== BEARISH EMA SCALP =====
    if m15_trend and ema20 < ema50:
        if bearish_rejection and rsi > 40:
            price_drop = current_price < float(m5_data['close'].iloc[current_idx-1])
            if price_drop:
                return 'BEARISH', {
                    'setup_type': 'EMA_PULLBACK',
                    'level': round(ema20, 2),
                    'rsi': round(rsi, 2),
                    'trend': 'DOWN'
                }
                
    return None, None

def detect_range_scalp(m5_data: pd.DataFrame, current_idx: int, lookback: int=80) -> tuple[str | None, dict | None]:
    """
    Range Scalp Setup - More Flexible Version.
    Catches bounces between support and resistance in a defined range.
    """
    if current_idx < lookback:
        return None, None
        
    current = m5_data.iloc[current_idx]
    current_price = float(current['close'])
    
    # 1. Identify the range
    range_high = float(m5_data['high'].iloc[current_idx-lookback:current_idx].max())
    range_low = float(m5_data['low'].iloc[current_idx-lookback:current_idx].min())
    range_size = range_high - range_low
    
    # Only trade ranges at least 3 points wide
    if range_size < 3.0:
        return None, None
        
    # 2. Check if price is near support or resistance (within 1 point)
    near_support = abs(current_price - range_low) < 1.0
    near_resistance = abs(current_price - range_high) < 1.0
    
    # 3. Count touches
    support_touches = 0
    resistance_touches = 0
    
    for i in range(current_idx-lookback, current_idx):
        if abs(float(m5_data['low'].iloc[i]) - range_low) < 0.5:
            support_touches += 1
        if abs(float(m5_data['high'].iloc[i]) - range_high) < 0.5:
            resistance_touches += 1
            
    has_valid_range = support_touches >= 1 and resistance_touches >= 1
    if not has_valid_range:
        return None, None
        
    # 5. Rejection candle (more flexible - 0.4 instead of 0.5)
    candle_range = float(current['high'] - current['low'])
    bullish_rejection = False
    bearish_rejection = False
    weak_bullish_rejection = False
    weak_bearish_rejection = False
    
    if candle_range > 0:
        upper_wick = float(current['high'] - max(current['open'], current['close']))
        lower_wick = float(min(current['open'], current['close']) - current['low'])
        
        bullish_rejection = lower_wick / candle_range > 0.4
        bearish_rejection = upper_wick / candle_range > 0.4
        
        weak_bullish_rejection = lower_wick / candle_range > 0.3
        weak_bearish_rejection = upper_wick / candle_range > 0.3
        
    # 6. RSI
    rsi_series = calculate_rsi(m5_data['close'].iloc[:current_idx+1], 14)
    rsi = float(rsi_series.iloc[-1]) if len(rsi_series) > 0 else 50.0
    
    # 7. Price action check
    price_move = current_price - float(m5_data['close'].iloc[current_idx-1]) if current_idx > 0 else 0.0
    
    # 8. Removed Volume check to avoid tick_volume dependency
    
    # ===== BULLISH RANGE SCALP =====
    if near_support and support_touches >= 1:
        bounce_signal = (bullish_rejection or 
                        (price_move > 0 and rsi < 55) or 
                        (weak_bullish_rejection))
        if bounce_signal:
            return 'BULLISH', {
                'setup_type': 'RANGE_BOUNCE',
                'support': round(range_low, 2),
                'resistance': round(range_high, 2),
                'range_size': round(range_size, 2),
                'touches': support_touches,
                'rsi': round(rsi, 2),
                'strength': 'STRONG' if bullish_rejection else 'WEAK'
            }
            
    # ===== BEARISH RANGE SCALP =====
    if near_resistance and resistance_touches >= 1:
        bounce_signal = (bearish_rejection or 
                        (price_move < 0 and rsi > 45) or 
                        (weak_bearish_rejection))
        if bounce_signal:
            return 'BEARISH', {
                'setup_type': 'RANGE_BOUNCE',
                'support': round(range_low, 2),
                'resistance': round(range_high, 2),
                'range_size': round(range_size, 2),
                'touches': resistance_touches,
                'rsi': round(rsi, 2),
                'strength': 'STRONG' if bearish_rejection else 'WEAK'
            }
            
    return None, None

def detect_range_breakout_scalp(m5_data: pd.DataFrame, current_idx: int, lookback: int=80) -> tuple[str | None, dict | None]:
    """
    Range Breakout Scalp Setup.
    Catches when price breaks out of an established range.
    """
    if current_idx < lookback:
        return None, None
        
    current = m5_data.iloc[current_idx]
    current_price = float(current['close'])
    
    # 1. Identify the range
    range_high = float(m5_data['high'].iloc[current_idx-lookback:current_idx].max())
    range_low = float(m5_data['low'].iloc[current_idx-lookback:current_idx].min())
    range_size = range_high - range_low
    
    if range_size < 3.0:
        return None, None
        
    # 2. Check for breakout
    break_above = current_price > (range_high + 0.5)
    break_below = current_price < (range_low - 0.5)
    
    if not break_above and not break_below:
        return None, None
        
    # 3. Check for range validity (at least 2 touches)
    support_touches = 0
    resistance_touches = 0
    
    for i in range(current_idx-lookback, current_idx):
        if abs(float(m5_data['low'].iloc[i]) - range_low) < 0.5:
            support_touches += 1
        if abs(float(m5_data['high'].iloc[i]) - range_high) < 0.5:
            resistance_touches += 1
            
    if support_touches < 2 or resistance_touches < 2:
        return None, None
        
    # 4. Momentum check
    momentum = current_price - float(m5_data['close'].iloc[current_idx-3]) if current_idx >= 3 else 0.0
    
    # 5. Removed Volume confirmation to avoid tick_volume dependency
        
    # 6. RSI
    rsi_series = calculate_rsi(m5_data['close'].iloc[:current_idx+1], 14)
    rsi = float(rsi_series.iloc[-1]) if len(rsi_series) > 0 else 50.0
    
    # ===== BULLISH RANGE BREAKOUT =====
    if break_above and momentum > 0:
        if rsi > 60:
            return 'BULLISH', {
                'setup_type': 'RANGE_BREAKOUT',
                'level': round(range_high, 2),
                'range_size': round(range_size, 2),
                'momentum': round(momentum, 2),
                'rsi': round(rsi, 2)
            }
            
    # ===== BEARISH RANGE BREAKOUT =====
    if break_below and momentum < 0:
        if rsi < 40:
            return 'BEARISH', {
                'setup_type': 'RANGE_BREAKOUT',
                'level': round(range_low, 2),
                'range_size': round(range_size, 2),
                'momentum': round(momentum, 2),
                'rsi': round(rsi, 2)
            }
            
    return None, None

def detect_base_momentum_scalp(m5_data: pd.DataFrame, current_idx: int) -> tuple[str | None, dict | None]:
    """
    Base Momentum Setup:
    Previous candle was BEARISH (close < open).
    Current candle is BEARISH (close < open).
    Current candle opened AT or BELOW the previous candle's close (the 'base').
    => BEARISH momentum continuation scalp.
    """
    if current_idx < 1:
        return None, None
        
    current = m5_data.iloc[current_idx]
    prev = m5_data.iloc[current_idx - 1]
    
    # Prev candle must be BEARISH
    if float(prev['close']) >= float(prev['open']):
        return None, None
        
    # Current candle opened at or below previous close (allow 0.09 pt micro-gap tolerance)
    if float(current['open']) > float(prev['close']) + 0.09:
        return None, None
        
    return 'BEARISH', {
        'setup_type': 'BASE_MOMENTUM',
        'prev_close': round(float(prev['close']), 2),
        'curr_open': round(float(current['open']), 2),
        'curr_close': round(float(current['close']), 2)
    }

def detect_crown_momentum_scalp(m5_data: pd.DataFrame, current_idx: int) -> tuple[str | None, dict | None]:
    """
    Crown Momentum Setup:
    Previous candle was BULLISH (close > open).
    Current candle is BULLISH (close > open).
    Current candle opened AT or ABOVE the previous candle's close (the 'crown').
    => BULLISH momentum continuation scalp.
    """
    if current_idx < 1:
        return None, None
        
    current = m5_data.iloc[current_idx]
    prev = m5_data.iloc[current_idx - 1]
    
    # Prev candle must be BULLISH
    if float(prev['close']) <= float(prev['open']):
        return None, None
        
    # Current candle opened at or above previous close (allow 0.09 pt micro-gap tolerance)
    if float(current['open']) < float(prev['close']) - 0.09:
        return None, None
        
    return 'BULLISH', {
        'setup_type': 'CROWN_MOMENTUM',
        'prev_close': round(float(prev['close']), 2),
        'curr_open': round(float(current['open']), 2),
        'curr_close': round(float(current['close']), 2)
    }

def execute_scalp_signal(signal: dict) -> dict:
    price = signal['price']
    direction = signal['direction']
    
    from engine.indicators import get_current_atr
    from engine.adaptive_parameters import AdaptiveParameters
    
    m15_atr = get_current_atr('M15') or 5.0
    adapter = AdaptiveParameters(m15_atr, 'SCALP')
    params = adapter.params
    
    if not params['should_trade']:
        signal['verdict'] = 'WAIT'
        signal['skip_reason'] = f"ADAPTIVE_SKIP: {params['reason']}"
        return signal
        
    sl_dist = params['sl']
    tp_dist = params['tp']
    
    if direction == 'BULLISH':
        entry = price + 0.1
        sl = entry - sl_dist
        tp1 = entry + tp_dist
        tp2 = entry + (tp_dist * 1.5)
    else:
        entry = price - 0.1
        sl = entry + sl_dist
        tp1 = entry - tp_dist
        tp2 = entry - (tp_dist * 1.5)
        
    rr = (tp1 - entry) / (entry - sl) if direction == 'BULLISH' else (entry - tp1) / (sl - entry)
    
    logger.info(adapter.get_summary())
    
    signal.update({
        'entry': round(entry, 2),
        'sl': round(sl, 2),
        'tp1': round(tp1, 2),
        'tp2': round(tp2, 2),
        'rr': round(rr, 2)
    })
    return signal

class ScalpingEngine:
    def __init__(self, m5_data: pd.DataFrame, m15_data: pd.DataFrame):
        self.m5_data = m5_data
        self.m15_data = m15_data
        
    def scan(self, current_idx: int) -> list[dict]:
        signals = []
        
        # 1. Breakout
        direction, details = detect_breakout_scalp(self.m5_data, current_idx)
        if direction:
            base_sig = {
                'type': 'BREAKOUT',
                'direction': direction,
                'details': details,
                'timestamp': self.m5_data.index[current_idx],
                'price': float(self.m5_data['close'].iloc[current_idx])
            }
            signals.append(execute_scalp_signal(base_sig))
            
        # 2. Fibonacci
        f_dir, f_det = detect_fibonacci_scalp(self.m5_data, current_idx)
        if f_dir:
            f_sig = {
                'type': 'FIBONACCI',
                'direction': f_dir,
                'details': f_det,
                'timestamp': self.m5_data.index[current_idx],
                'price': float(self.m5_data['close'].iloc[current_idx])
            }
            signals.append(execute_scalp_signal(f_sig))
            
        # 3. EMA Pullback
        v_dir, v_det = detect_ema_pullback_scalp(self.m5_data, current_idx)
        if v_dir:
            v_sig = {
                'type': 'EMA_PULLBACK',
                'direction': v_dir,
                'details': v_det,
                'timestamp': self.m5_data.index[current_idx],
                'price': float(self.m5_data['close'].iloc[current_idx])
            }
            signals.append(execute_scalp_signal(v_sig))
            
        # 4. Range Scalp
        r_dir, r_det = detect_range_scalp(self.m5_data, current_idx)
        if r_dir:
            r_sig = {
                'type': 'RANGE_BOUNCE',
                'direction': r_dir,
                'details': r_det,
                'timestamp': self.m5_data.index[current_idx],
                'price': float(self.m5_data['close'].iloc[current_idx])
            }
            signals.append(execute_scalp_signal(r_sig))
            
        # 5. Range Breakout
        rb_dir, rb_det = detect_range_breakout_scalp(self.m5_data, current_idx)
        if rb_dir:
            rb_sig = {
                'type': 'RANGE_BREAKOUT',
                'direction': rb_dir,
                'details': rb_det,
                'timestamp': self.m5_data.index[current_idx],
                'price': float(self.m5_data['close'].iloc[current_idx])
            }
            signals.append(execute_scalp_signal(rb_sig))
            
        # 6. Base Momentum
        bm_dir, bm_det = detect_base_momentum_scalp(self.m5_data, current_idx)
        if bm_dir:
            bm_sig = {
                'type': 'BASE_MOMENTUM',
                'direction': bm_dir,
                'details': bm_det,
                'timestamp': self.m5_data.index[current_idx],
                'price': float(self.m5_data['close'].iloc[current_idx])
            }
            signals.append(execute_scalp_signal(bm_sig))
            
        # 7. Crown Momentum
        cm_dir, cm_det = detect_crown_momentum_scalp(self.m5_data, current_idx)
        if cm_dir:
            cm_sig = {
                'type': 'CROWN_MOMENTUM',
                'direction': cm_dir,
                'details': cm_det,
                'timestamp': self.m5_data.index[current_idx],
                'price': float(self.m5_data['close'].iloc[current_idx])
            }
            signals.append(execute_scalp_signal(cm_sig))
            
        return signals
        
    def backtest(self, start_idx: int = 100) -> list[dict]:
        all_signals = []
        for i in range(start_idx, len(self.m5_data)):
            signals = self.scan(i)
            if signals:
                all_signals.extend(signals)
        return all_signals
