import pandas as pd
from datetime import datetime, timezone
import logging

from engine.data_fetcher import fetch_ohlcv
from engine.scalping_engine import ScalpingEngine, M1HyperEngine
from engine import broker_executor
from app.models.signals import Signal
from engine.db import get_session

logger = logging.getLogger("engine.scalping.integration")

class ScalpingIntegration:
    def __init__(self):
        self.setup_types = ['BREAKOUT', 'EMA_PULLBACK', 'RANGE_BOUNCE', 'FIBONACCI', 'RANGE_BREAKOUT']
        self.signals = []
        
    def scan_m5(self):
        """Scan M5 data for scalping setups."""
        m5_data = fetch_ohlcv("M5", use_cache=False)
        if m5_data is None or len(m5_data) < 100:
            logger.warning("Insufficient M5 data for scalping")
            return [], "UNKNOWN"
            
        m15_data = fetch_ohlcv("M15", use_cache=True)
        m15_trend = "UNKNOWN"
        if m15_data is not None and len(m15_data) >= 50:
            import ta
            close_series = m15_data['close'].astype(float)
            ema20 = ta.trend.ema_indicator(close_series, window=20).iloc[-1]
            ema50 = ta.trend.ema_indicator(close_series, window=50).iloc[-1]
            if not pd.isna(ema20) and not pd.isna(ema50):
                if ema20 > ema50: m15_trend = "BULLISH"
                elif ema20 < ema50: m15_trend = "BEARISH"
            
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
        current_idx = len(m5_data) - 1  # Latest candle
        
        new_signals = engine.scan(current_idx, h4_trend=h4_trend)
        if not new_signals:
            c_price = m5_data['close'].iloc[current_idx]
            logger.info(f"Scan M5 complete: 0 setups found at price {c_price:.2f}. Waiting for criteria...")
        return new_signals, h4_trend, m15_trend
        
    def scan_m1(self):
        """Scan M1 data for hyper-scalping setups."""
        m1_data = fetch_ohlcv("M1", use_cache=False)
        if m1_data is None or len(m1_data) < 100:
            return [], "UNKNOWN", "UNKNOWN"
            
        m15_data = fetch_ohlcv("M15", use_cache=True)
        m15_trend = "UNKNOWN"
        if m15_data is not None and len(m15_data) >= 50:
            import ta
            close_series = m15_data['close'].astype(float)
            ema20 = ta.trend.ema_indicator(close_series, window=20).iloc[-1]
            ema50 = ta.trend.ema_indicator(close_series, window=50).iloc[-1]
            if not pd.isna(ema20) and not pd.isna(ema50):
                if ema20 > ema50: m15_trend = "BULLISH"
                elif ema20 < ema50: m15_trend = "BEARISH"
            
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
        if not new_signals:
            c_price = m1_data['close'].iloc[current_idx]
            logger.info(f"Scan M1 complete: 0 hyper-scalps found at price {c_price:.2f}. Monitoring...")
        return new_signals, h4_trend, m15_trend
    
    def check_and_execute(self, config):
        """Check for new signals and execute them."""
        new_signals, h4_trend, m15_trend = self.scan_m5()
        
        if not new_signals:
            return []
        
        executed = []
        for signal in new_signals:
            # Skip signals that were adaptively skipped
            if signal.get('verdict') == 'WAIT':
                logger.info(f"Signal skipped: {signal.get('skip_reason')}")
                continue
                
            # ── RELAXED TREND FILTER ──
            # Signal must align with either the H4 Trend OR the M15 Trend
            # DISABLED: The H4/M15 macro filters cause too much lag during V-shape reversals.
            # if h4_trend != "UNKNOWN" and m15_trend != "UNKNOWN":
            #     if signal['direction'] == 'BULLISH' and h4_trend == 'BEARISH' and m15_trend == 'BEARISH':
            #         logger.info(f"Signal skipped: TREND_FILTER (Blocked LONG in BEARISH H4/M15 trend)")
            #         continue
            #     if signal['direction'] == 'BEARISH' and h4_trend == 'BULLISH' and m15_trend == 'BULLISH':
            #         logger.info(f"Signal skipped: TREND_FILTER (Blocked SHORT in BULLISH H4/M15 trend)")
            #         continue
                
            # Check if this signal was already executed
            if self._is_duplicate(signal, lockout_seconds=1800):
                continue
            
            # Execute the trade
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
        new_signals, h4_trend, m15_trend = self.scan_m1()
        
        if not new_signals:
            return []
            
        executed = []
        for signal in new_signals:
            if signal.get('verdict') == 'WAIT':
                logger.info(f"M1 Signal skipped: {signal.get('skip_reason')}")
                continue
                
            # ── RELAXED TREND FILTER ──
            # DISABLED: The H4/M15 macro filters cause too much lag during V-shape reversals.
            # if h4_trend != "UNKNOWN" and m15_trend != "UNKNOWN":
            #     if signal['direction'] == 'BULLISH' and h4_trend == 'BEARISH' and m15_trend == 'BEARISH':
            #         logger.info(f"M1 Signal skipped: TREND_FILTER (Blocked LONG in BEARISH H4/M15 trend)")
            #         continue
            #     if signal['direction'] == 'BEARISH' and h4_trend == 'BULLISH' and m15_trend == 'BULLISH':
            #         logger.info(f"M1 Signal skipped: TREND_FILTER (Blocked SHORT in BULLISH H4/M15 trend)")
            #         continue
                    
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
        """Check if signal was already executed recently."""
        now = datetime.now(timezone.utc)
        
        # Check in-memory first (fast)
        for prev_signal in reversed(self.signals[-20:]):
            time_diff = (now - prev_signal['timestamp'].replace(tzinfo=timezone.utc)).total_seconds()
            if prev_signal['type'] == signal['type'] and time_diff < lockout_seconds:
                if prev_signal['direction'] == signal['direction']:
                    if abs(prev_signal['entry'] - signal['entry']) < 2.0:
                        return True
                        
        # Check database (persistent across Uvicorn reloads)
        try:
            from app.database import get_session
            from app.models.trades import Trade
            from app.models.signals import Signal
            from sqlmodel import select
            
            session = get_session()
            recent_trades = session.exec(
                select(Trade, Signal)
                .join(Signal, Trade.signal_id == Signal.id)
                .where(Trade.direction == ("LONG" if signal['direction'] == 'BULLISH' else "SHORT"))
                .order_by(Trade.id.desc())
                .limit(5)
            ).all()
            session.close()
            
            for t, s in recent_trades:
                # If trade was opened within the lockout period
                if t.opened_at.tzinfo is None:
                    trade_time = t.opened_at.replace(tzinfo=timezone.utc) # fallback
                else:
                    trade_time = t.opened_at
                    
                if (now - trade_time).total_seconds() < lockout_seconds:
                    if abs(t.planned_entry - signal['entry']) < 2.0:
                        logger.info(f"DB Duplicate detected: {signal['direction']} @ {signal['entry']}")
                        return True
        except Exception as e:
            logger.warning(f"Failed to check DB for duplicates: {e}")
            
        return False
    
    def compute_lot_size(self, config, stop_loss_pips: float) -> float:
        """Calculate lot size using the engine configuration."""
        return 0.05
    
    def _execute_signal(self, signal, config):
        """Execute a scalping trade."""
        direction = "LONG" if signal['direction'] == 'BULLISH' else "SHORT"
        
        entry = signal['entry']
        sl = signal['sl']
        tp1 = signal['tp1']
        
        sl_pips = abs(entry - sl) * 10
        lot_size = self.compute_lot_size(config, sl_pips)
        
        # We need a session to log
        session_db = get_session()
        
        logger.info(f"SCALP EXECUTION: {direction} {lot_size} lots @ ~{entry} (Type={signal['type']} Step-Trailing TP)")
        
        order_result = broker_executor.place_order(
            direction=direction,
            lot_size=lot_size,
            entry_price=entry,
            stop_loss=sl,
            take_profit=0.0, # TP is managed by Step-Trailing system
        )
        
        if not order_result["success"]:
            logger.error(f"Scalp Order failed: {order_result['error']}")
            session_db.close()
            return None, None, None
            
        # Log Signal
        db_sig = Signal(
            timeframe=signal.get('timeframe', 'M5'),
            session="SCALP",
            verdict="TRADE",
            direction=direction,
            confidence=90, # Hardcoded high confidence for scalping
            skip_reason=None,
            price_at_signal=signal['price'],
            prompt_version=0
        )
        session_db.add(db_sig)
        session_db.flush()
        
        # Log Trade
        from app.models.trades import Trade
        trade = Trade(
            signal_id=db_sig.id,
            direction=direction,
            planned_entry=entry,
            actual_entry=order_result["actual_entry"],
            slippage_pips=order_result["slippage_pips"],
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
