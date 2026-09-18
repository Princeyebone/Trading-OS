"""
engine/xagi6_crash_hunter.py
A dedicated Gold system (Magic: 203000) that includes:
1. H1 Trend Filter (like XAGI4)
2. Anti-Bleed Circuit Breaker (Blocks longs during a 50+ pip waterfall)
3. Waterfall Crash Detection (Fires momentum shorts into the crash, bypassing H1)
4. Tighter max SL via 'CRASH_HUNTER' adaptive params
"""
import pandas as pd
from datetime import datetime, timezone
import logging
import MetaTrader5 as mt5

from engine.data_fetcher import fetch_ohlcv
from engine.scalping_engine import ScalpingEngine, M1HyperEngine, execute_scalp_signal
from engine import broker_executor
from app.models.signals import Signal
from engine.db import get_session
import ta

logger = logging.getLogger("engine.xagi6_crash_hunter")
MAGIC_NUMBER = 202900

class Xagi6CrashHunter:
    def __init__(self):
        self.setup_types = ['BREAKOUT', 'EMA_PULLBACK', 'RANGE_BOUNCE', 'FIBONACCI', 'RANGE_BREAKOUT', 'WATERFALL_CRASH']
        self.signals = []
        
    def _get_h1_trend(self) -> str:
        h1_data = fetch_ohlcv("H1", use_cache=True)
        if h1_data is None or len(h1_data) < 5:
            return "UNKNOWN"
        closes = h1_data['close'].values
        if closes[-1] > closes[-3]:
            return "BULLISH"
        elif closes[-1] < closes[-3]:
            return "BEARISH"
        return "SIDEWAYS"

    def _has_open_trade(self) -> bool:
        """Check if we already have an open XAGI6 trade."""
        positions = mt5.positions_get(symbol="XAUUSD")
        if positions:
            for p in positions:
                if p.magic == MAGIC_NUMBER:
                    return True
        return False

    def _check_circuit_breaker(self, m5_data: pd.DataFrame, current_idx: int) -> bool:
        if current_idx < 10: return False
        
        current_close = m5_data['close'].iloc[current_idx]
        past_close = m5_data['close'].iloc[current_idx-6]
        
        drop = past_close - current_close
        ema20 = m5_data['close'].rolling(20).mean().iloc[current_idx]
        
        if drop > 5.0 and current_close < ema20:
            return True
        return False

    def _detect_waterfall_crash(self, m5_data: pd.DataFrame, current_idx: int):
        if current_idx < 10: return None, None
        
        c0 = m5_data.iloc[current_idx]
        c1 = m5_data.iloc[current_idx-1]
        
        is_bearish = lambda c: c['close'] < c['open']
        
        # Detect 2-candle momentum crash
        if is_bearish(c0) and is_bearish(c1):
            total_drop = (c1['open'] - c0['close'])
            if total_drop >= 4.0: # 40 pips in 10 mins
                avg_vol = m5_data['tick_volume'].iloc[current_idx-20:current_idx].mean()
                if c0['tick_volume'] > avg_vol * 1.2 or c1['tick_volume'] > avg_vol * 1.2:
                    rsi = ta.momentum.rsi(m5_data['close'].iloc[:current_idx+1], 14).iloc[-1]
                    if rsi > 20: 
                        return 'BEARISH', {
                            'setup_type': 'WATERFALL_CRASH',
                            'drop_size': round(float(total_drop), 2),
                            'rsi': round(float(rsi), 2)
                        }
        return None, None

    def scan_m5(self):
        """Scan M5 data for scalping setups + Crash Logic."""
        m5_data = fetch_ohlcv("M5", use_cache=False)
        if m5_data is None or len(m5_data) < 100:
            logger.warning("Insufficient M5 data for scalping")
            return [], "UNKNOWN", False
            
        m15_data = fetch_ohlcv("M15", use_cache=True)
        h4_data = fetch_ohlcv("H4", use_cache=True)
        
        h4_trend = "UNKNOWN"
        if h4_data is not None and len(h4_data) >= 50:
            close_series = h4_data['close'].astype(float)
            ema20 = ta.trend.ema_indicator(close_series, window=20).iloc[-1]
            ema50 = ta.trend.ema_indicator(close_series, window=50).iloc[-1]
            if not pd.isna(ema20) and not pd.isna(ema50):
                if ema20 > ema50: h4_trend = "BULLISH"
                elif ema20 < ema50: h4_trend = "BEARISH"
            
        engine = ScalpingEngine(m5_data, m15_data)
        current_idx = len(m5_data) - 1
        
        new_signals = engine.scan(current_idx, h4_trend=h4_trend)
        h1_trend = self._get_h1_trend()
        
        cb_active = self._check_circuit_breaker(m5_data, current_idx)
        waterfall_dir, waterfall_det = self._detect_waterfall_crash(m5_data, current_idx)
        
        if waterfall_dir:
            sig = {
                'type': 'WATERFALL_CRASH',
                'direction': waterfall_dir,
                'details': waterfall_det,
                'timestamp': m5_data.index[current_idx],
                'price': float(m5_data['close'].iloc[current_idx])
            }
            # Custom parameter calculation for CRASH_HUNTER
            from engine.indicators import get_current_atr
            from engine.adaptive_parameters import AdaptiveParameters
            
            m15_atr = get_current_atr('M15') or 5.0
            adapter = AdaptiveParameters(m15_atr, 'CRASH_HUNTER')
            params = adapter.params
            
            entry = sig['price'] - 0.1
            sl = entry + params['sl']
            tp1 = entry - params['tp']
            
            sig.update({'entry': entry, 'sl': sl, 'tp1': tp1, 'tp2': tp1 - 2.0, 'rr': params['rr'], 'verdict': 'TRADE'})
            new_signals.append(sig)
        else:
            # Need to rebuild adaptive params for normal signals with CRASH_HUNTER caps
            from engine.indicators import get_current_atr
            from engine.adaptive_parameters import AdaptiveParameters
            m15_atr = get_current_atr('M15') or 5.0
            adapter = AdaptiveParameters(m15_atr, 'CRASH_HUNTER')
            params = adapter.params
            for s in new_signals:
                if s['direction'] == 'BULLISH':
                    s['sl'] = s['entry'] - params['sl']
                    s['tp1'] = s['entry'] + params['tp']
                else:
                    s['sl'] = s['entry'] + params['sl']
                    s['tp1'] = s['entry'] - params['tp']
        
        return new_signals, h1_trend, cb_active
        
    def check_and_execute(self, config):
        """Check for new signals and execute them."""
        new_signals, h1_trend, cb_active = self.scan_m5()
        
        if not new_signals:
            return []
            
        if self._has_open_trade():
            logger.info("[XAUUSD-i6] Skipping M5 execution: Max open trades (1) reached.")
            return []
        
        executed = []
        for signal in new_signals:
            if signal.get('verdict') == 'WAIT':
                continue
                
            # ── CIRCUIT BREAKER FILTER ──
            if signal['direction'] == 'BULLISH' and cb_active:
                logger.info(f"[XAUUSD-i6] 🛑 Blocked LONG False Buy! Circuit Breaker ACTIVE.")
                continue
                
            # ── HARD H1 TREND FILTER + BYPASS ──
            if signal['direction'] == 'BULLISH' and h1_trend == 'BEARISH':
                logger.info(f"[XAUUSD-i6] Blocked LONG in BEARISH H1 trend.")
                continue
            if signal['direction'] == 'BEARISH' and h1_trend == 'BULLISH':
                if signal['type'] == 'WATERFALL_CRASH':
                    logger.info(f"[XAUUSD-i6] 🚀 H1 FILTER BYPASS: Executing WATERFALL_CRASH Short!")
                else:
                    logger.info(f"[XAUUSD-i6] Blocked normal SHORT in BULLISH H1 trend.")
                    continue
                
            if self._is_duplicate(signal, lockout_seconds=1800):
                continue
            
            trade_id, actual_entry, order_id = self._execute_signal(signal, config)
            if trade_id:
                signal['trade_id'] = trade_id
                signal['actual_entry'] = actual_entry
                signal['order_id'] = order_id
                self.signals.append(signal)
                executed.append(signal)
                break # Only 1 trade
        
        return executed
    
    def _is_duplicate(self, signal, lockout_seconds=1800):
        now = datetime.now(timezone.utc)
        for prev_signal in reversed(self.signals[-20:]):
            time_diff = (now - prev_signal['timestamp'].replace(tzinfo=timezone.utc)).total_seconds()
            if prev_signal['type'] == signal['type'] and time_diff < lockout_seconds:
                if prev_signal['direction'] == signal['direction']:
                    if abs(prev_signal['entry'] - signal['entry']) < 2.0:
                        return True
        return False
    
    def _execute_signal(self, signal, config):
        direction = "LONG" if signal['direction'] == 'BULLISH' else "SHORT"
        
        entry = signal['entry']
        sl = signal['sl']
        tp1 = signal['tp1']
        
        lot_size = 0.05
        
        session_db = get_session()
        
        logger.info(f"[XAUUSD-i6] EXECUTION: {direction} {lot_size} lots @ ~{entry} (Type={signal['type']})")
        
        order_result = broker_executor.place_order(
            direction=direction,
            lot_size=lot_size,
            entry_price=entry,
            stop_loss=sl,
            take_profit=0.0, 
            magic=MAGIC_NUMBER,
            comment="XAUUSD-i6-CrashHunter",
            symbol="XAUUSD"
        )
        
        if not order_result.get("success"):
            logger.error(f"[XAUUSD-i6] Order failed: {order_result.get('error')}")
            session_db.close()
            return None, None, None
            
        db_sig = Signal(
            timeframe=signal.get('timeframe', 'M5'),
            session="XAGI6",
            verdict="TRADE",
            direction=direction,
            confidence=95,
            skip_reason=None,
            price_at_signal=signal['price'],
            prompt_version=0
        )
        session_db.add(db_sig)
        session_db.flush()
        
        from app.models.trades import Trade
        trade = Trade(
            signal_id=db_sig.id,
            direction=direction,
            planned_entry=entry,
            actual_entry=order_result["actual_entry"],
            slippage_pips=order_result.get("slippage_pips", 0.0),
            stop_loss=sl,
            take_profit_1=tp1,
            take_profit_2=0.0,
            lot_size=lot_size,
            planned_rr=signal['rr'],
            broker_order_id=order_result["order_id"],
            status="OPEN",
        )
        session_db.add(trade)
        session_db.commit()
        
        trade_id = trade.id
        session_db.close()
        
        return trade_id, order_result["actual_entry"], order_result["order_id"]
