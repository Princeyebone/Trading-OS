import pandas as pd
from datetime import datetime, timezone
import logging

from engine.data_fetcher import fetch_ohlcv
from engine.scalping_engine import ScalpingEngine
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
        # Fetch M5 data (caching handled by data_fetcher if configured)
        m5_data = fetch_ohlcv("M5", use_cache=False)
        if m5_data is None or len(m5_data) < 100:
            logger.warning("Insufficient M5 data for scalping")
            return []
            
        m15_data = fetch_ohlcv("M15", use_cache=True)
        if m15_data is None:
            return []
            
        # Run the scalping engine
        engine = ScalpingEngine(m5_data, m15_data)
        current_idx = len(m5_data) - 1  # Latest candle
        
        new_signals = engine.scan(current_idx)
        if not new_signals:
            c_price = m5_data['close'].iloc[current_idx]
            logger.info(f"Scan complete: 0 setups found at price {c_price:.2f}. Waiting for criteria...")
        return new_signals
    
    def check_and_execute(self, config):
        """Check for new signals and execute them."""
        new_signals = self.scan_m5()
        
        if not new_signals:
            return []
        
        executed = []
        for signal in new_signals:
            # Skip signals that were adaptively skipped
            if signal.get('verdict') == 'WAIT':
                logger.info(f"Signal skipped: {signal.get('skip_reason')}")
                continue
                
            # Check if this signal was already executed
            if self._is_duplicate(signal):
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
    
    def _is_duplicate(self, signal):
        """Check if signal was already executed recently (last 30 minutes)."""
        now = datetime.now(timezone.utc)
        for prev_signal in reversed(self.signals[-20:]):
            time_diff = (now - prev_signal['timestamp'].replace(tzinfo=timezone.utc)).total_seconds()
            
            # Same type and within 30 minutes (1800 seconds)
            if prev_signal['type'] == signal['type'] and time_diff < 1800:
                # Same direction
                if prev_signal['direction'] == signal['direction']:
                    # Very close price
                    if abs(prev_signal['price'] - signal['price']) < 2.0:
                        return True
        return False
    
    def compute_lot_size(self, config, stop_loss_pips: float) -> float:
        """Calculate lot size using the engine configuration."""
        risk_dollars = config.account_balance_equiv * (config.max_risk_percent / 100)
        # For Scalping, maybe halve the risk? Or use full risk. We will use half risk for scalps.
        risk_dollars = risk_dollars * 0.5 
        
        pip_value_per_micro = 1.0   # $1 per pip per 0.10 lot
        if stop_loss_pips <= 0:
            return 0.01
        raw_lots = risk_dollars / (stop_loss_pips * pip_value_per_micro)
        return max(0.01, round(raw_lots - (raw_lots % 0.01), 2))
    
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
            timeframe="M5",
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
