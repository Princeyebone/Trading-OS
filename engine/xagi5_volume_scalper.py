"""
engine/xagi5_volume_scalper.py
Scalper with a Volume Anomaly filter.
Only enters trades if M5 tick volume is > 1.2x the 20-period moving average.
Magic number: 202900
"""
import pandas as pd
from datetime import datetime, timezone
import logging
import MetaTrader5 as mt5

from engine.data_fetcher import fetch_ohlcv
from engine.scalping_engine import ScalpingEngine, M1HyperEngine
from engine import broker_executor
from app.models.signals import Signal
from engine.db import get_session

logger = logging.getLogger("engine.xagi5_volume_scalper")
MAGIC_NUMBER = 202900

class Xagi5VolumeScalper:
    def __init__(self):
        self.setup_types = ['BREAKOUT', 'EMA_PULLBACK', 'RANGE_BOUNCE', 'FIBONACCI', 'RANGE_BREAKOUT']
        self.signals = []
        
    def _check_volume_anomaly(self, df: pd.DataFrame) -> bool:
        if len(df) < 21:
            return False
        
        # Calculate 20-period SMA of volume
        vol_sma = df['volume'].rolling(20).mean().iloc[-2]
        if vol_sma <= 0:
            return False
            
        current_vol = df['volume'].iloc[-2] # Check the last closed candle
        ratio = current_vol / vol_sma
        
        return ratio > 1.2

    def scan_m5(self):
        """Scan M5 data for scalping setups."""
        m5_data = fetch_ohlcv("M5", use_cache=False)
        if m5_data is None or len(m5_data) < 100:
            logger.warning("Insufficient M5 data for scalping")
            return [], False
            
        m15_data = fetch_ohlcv("M15", use_cache=True)
        h4_data = fetch_ohlcv("H4", use_cache=True)
        
        h4_trend = "UNKNOWN"
        if h4_data is not None and len(h4_data) >= 50:
            import ta
            close_series = h4_data['close'].astype(float)
            ema20 = ta.trend.ema_indicator(close_series, window=20).iloc[-1]
            ema50 = ta.trend.ema_indicator(close_series, window=50).iloc[-1]
            if not pd.isna(ema20) and not pd.isna(ema50):
                if ema20 > ema50: h4_trend = "BULLISH"
                elif ema20 < ema50: h4_trend = "BEARISH"
            
        # Run the scalping engine
        engine = ScalpingEngine(m5_data, m15_data)
        current_idx = len(m5_data) - 1
        
        new_signals = engine.scan(current_idx, h4_trend=h4_trend)
        has_volume = self._check_volume_anomaly(m5_data)
        
        return new_signals, has_volume
        
    def scan_m1(self):
        """Scan M1 data for hyper-scalping setups."""
        m1_data = fetch_ohlcv("M1", use_cache=False)
        if m1_data is None or len(m1_data) < 100:
            return [], False
            
        h4_data = fetch_ohlcv("H4", use_cache=True)
        h4_trend = "UNKNOWN"
        if h4_data is not None and len(h4_data) >= 50:
            import ta
            close_series = h4_data['close'].astype(float)
            ema20 = ta.trend.ema_indicator(close_series, window=20).iloc[-1]
            ema50 = ta.trend.ema_indicator(close_series, window=50).iloc[-1]
            if not pd.isna(ema20) and not pd.isna(ema50):
                if ema20 > ema50: h4_trend = "BULLISH"
                elif ema20 < ema50: h4_trend = "BEARISH"
                
        engine = M1HyperEngine(m1_data, h4_trend)
        current_idx = len(m1_data) - 1
        
        new_signals = engine.scan(current_idx)
        
        # M1 still uses the M5 volume anomaly for context
        m5_data = fetch_ohlcv("M5", use_cache=True)
        has_volume = False
        if m5_data is not None:
            has_volume = self._check_volume_anomaly(m5_data)
        
        return new_signals, has_volume
    
    def _has_open_trade(self) -> bool:
        """Check if we already have an open XAGI5 trade."""
        positions = mt5.positions_get(symbol="XAUUSD")
        if positions:
            for p in positions:
                if p.magic == MAGIC_NUMBER:
                    return True
        return False
        
    def check_and_execute(self, config):
        """Check for new signals and execute them."""
        if self._has_open_trade():
            return []
            
        new_signals, has_volume = self.scan_m5()
        
        if not new_signals:
            return []
            
        if not has_volume:
            logger.info("[XAUUSD-i5] Skipping M5 execution: Low Volume Chop (Ratio < 1.2)")
            return []
        
        executed = []
        for signal in new_signals:
            if signal.get('verdict') == 'WAIT':
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
        
        return executed
        
    def check_and_execute_m1(self, config):
        """Check for new M1 signals and execute them."""
        if self._has_open_trade():
            return []
            
        new_signals, has_volume = self.scan_m1()
        
        if not new_signals:
            return []
            
        if not has_volume:
            logger.info("[XAUUSD-i5] Skipping M1 execution: Low Volume Chop (Ratio < 1.2)")
            return []
            
        executed = []
        for signal in new_signals:
            if signal.get('verdict') == 'WAIT':
                continue
                    
            if self._is_duplicate(signal, lockout_seconds=900): # 15 min lockout for M1
                continue
                
            trade_id, actual_entry, order_id = self._execute_signal(signal, config)
            if trade_id:
                signal['trade_id'] = trade_id
                signal['actual_entry'] = actual_entry
                signal['order_id'] = order_id
                self.signals.append(signal)
                executed.append(signal)
                
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
        
        logger.info(f"[XAUUSD-i5] EXECUTION: {direction} {lot_size} lots @ ~{entry} (Type={signal['type']})")
        
        order_result = broker_executor.place_order(
            direction=direction,
            lot_size=lot_size,
            entry_price=entry,
            stop_loss=sl,
            take_profit=0.0, 
            magic=MAGIC_NUMBER,
            comment="XAUUSD-i5-v2",
            symbol="XAUUSD"
        )
        
        if not order_result.get("success"):
            logger.error(f"[XAUUSD-i5] Order failed: {order_result.get('error')}")
            session_db.close()
            return None, None, None
            
        db_sig = Signal(
            timeframe=signal.get('timeframe', 'M5'),
            session="XAGI5",
            verdict="TRADE",
            direction=direction,
            confidence=98,
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
