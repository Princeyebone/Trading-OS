"""
engine/xagi8_ifvg_reversal.py
IFVG Reversal Strategy for XAUUSD (Gold).
Trades Inversion Fair Value Gaps on the M5 timeframe during London and NY sessions.
Fixed lot size: 0.05
"""
import pandas as pd
from datetime import datetime, timezone
import logging
import MetaTrader5 as mt5

from engine.data_fetcher import fetch_ohlcv
from engine.pattern_detector import detect_inversion_fair_value_gaps
from engine import broker_executor
from app.models.signals import Signal
from engine.db import get_session

logger = logging.getLogger("engine.xagi8_ifvg_reversal")
MAGIC_NUMBER = 202808

class Xagi8IFVGReversal:
    def __init__(self):
        self.signals = []
        self.lot_size = 0.05
        
    def _is_valid_session(self) -> bool:
        """Allow both London (03-12 EST) and NY (08-17 EST). Combined: 03-17 EST."""
        now_est = datetime.now(timezone.utc).astimezone().hour # Assuming server/local time roughly aligns or we use UTC hour offsets
        # More robust: get UTC hour and convert. EST is UTC-5 (or -4 EDT)
        # Assuming system time is used in the rest of the codebase.
        now_utc = datetime.now(timezone.utc).hour
        # London opens ~08:00 UTC, NY closes ~22:00 UTC
        if 8 <= now_utc < 22:
            return True
        return False

    def _has_open_trade(self) -> bool:
        """Check if we already have an open XAGI8 trade."""
        positions = mt5.positions_get(symbol="XAUUSD")
        if positions:
            for p in positions:
                if p.magic == MAGIC_NUMBER:
                    return True
        return False

    def scan_m5(self):
        """Scan M5 data for IFVG setups."""
        m5_data = fetch_ohlcv("M5", use_cache=False)
        if m5_data is None or len(m5_data) < 50:
            logger.warning("[XAUUSD-i8] Insufficient M5 data")
            return []
            
        # Detect IFVGs
        ifvgs = detect_inversion_fair_value_gaps(m5_data)
        
        new_signals = []
        current_price = m5_data['close'].iloc[-1]
        
        for ifvg in ifvgs:
            # Only consider IFVGs formed recently (e.g. within last 10 bars)
            bars_ago = (len(m5_data) - 1) - ifvg["bar_index"]
            if bars_ago > 10:
                continue
                
            gap_size = abs(ifvg["high"] - ifvg["low"])
            if gap_size < 1.0:
                # Less than 1.0 points (10 pips) - skip due to commission/spread drag
                continue
                
            direction = ifvg["direction"]
            
            # Setup 1 & 2: We wait for price to retest the IFVG zone.
            # For BULLISH IFVG, we want price to retrace down into the gap to enter long.
            if direction == "BULLISH":
                # Check if current price is near or inside the IFVG (between high and low of gap)
                # Adding a small buffer for Gold
                if current_price <= (ifvg["high"] + 0.5) and current_price >= (ifvg["low"] - 0.5):
                    # Retest!
                    sl = ifvg["low"] - 1.0 # Stop loss just below the gap
                    entry = current_price
                    risk = entry - sl
                    if risk <= 0: continue # Invalid
                    tp = entry + (risk * 3.0) # 1:3 RR for the runner, scaling out at 1.5
                    
                    new_signals.append({
                        "type": "IFVG_RETEST",
                        "direction": "BULLISH",
                        "entry": float(entry),
                        "sl": float(sl),
                        "tp1": float(tp),
                        "rr": 2.0,
                        "price": float(current_price),
                        "timeframe": "M5",
                        "timestamp": datetime.now(timezone.utc)
                    })
                    
            # For BEARISH IFVG, we want price to retrace up into the gap to enter short.
            elif direction == "BEARISH":
                if current_price >= (ifvg["low"] - 0.5) and current_price <= (ifvg["high"] + 0.5):
                    sl = ifvg["high"] + 1.0 # Stop loss just above the gap
                    entry = current_price
                    risk = sl - entry
                    if risk <= 0: continue
                    tp = entry - (risk * 3.0) # 1:3 RR for the runner, scaling out at 1.5
                    
                    new_signals.append({
                        "type": "IFVG_RETEST",
                        "direction": "BEARISH",
                        "entry": float(entry),
                        "sl": float(sl),
                        "tp1": float(tp),
                        "rr": 2.0,
                        "price": float(current_price),
                        "timeframe": "M5",
                        "timestamp": datetime.now(timezone.utc)
                    })

        return new_signals
        
    def check_and_execute(self, config):
        """Check for new signals and execute them."""
        if not self._is_valid_session():
            logger.info("[XAUUSD-i8] Outside London/NY session, skipping.")
            return []
            
        new_signals = self.scan_m5()
        
        if not new_signals:
            return []
            
        if self._has_open_trade():
            logger.info("[XAUUSD-i8] Max open trades (1) reached.")
            return []
        
        executed = []
        for signal in new_signals:
            if self._is_duplicate(signal, lockout_seconds=1800):
                continue
            
            trade_id, actual_entry, order_id = self._execute_signal(signal, config)
            if trade_id:
                signal['trade_id'] = trade_id
                signal['actual_entry'] = actual_entry
                signal['order_id'] = order_id
                self.signals.append(signal)
                executed.append(signal)
                break # Only 1 trade per cycle
        
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
        
        session_db = get_session()
        
        # Check current spread before executing
        spread = broker_executor.check_spread("XAUUSD")
        if spread > 30:
            logger.warning(f"[XAUUSD-i8] Spread too high ({spread} pts). Rejecting entry.")
            session_db.close()
            return None, None, None
        
        logger.info(f"[XAUUSD-i8] EXECUTION: {direction} {self.lot_size} lots @ ~{entry} (Type={signal['type']})")
        
        order_result = broker_executor.place_order(
            direction=direction,
            lot_size=self.lot_size,
            entry_price=entry,
            stop_loss=sl,
            take_profit=tp1, 
            magic=MAGIC_NUMBER,
            comment="XAUUSD-i8-IFVG",
            symbol="XAUUSD"
        )
        
        if not order_result.get("success"):
            logger.error(f"[XAUUSD-i8] Order failed: {order_result.get('error')}")
            session_db.close()
            return None, None, None
            
        db_sig = Signal(
            timeframe=signal.get('timeframe', 'M5'),
            session="XAGI8",
            verdict="TRADE",
            direction=direction,
            confidence=85,
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
            actual_entry=order_result.get("actual_entry", entry),
            slippage_pips=order_result.get("slippage_pips", 0.0),
            stop_loss=sl,
            take_profit_1=tp1,
            take_profit_2=0.0,
            lot_size=self.lot_size,
            planned_rr=signal['rr'],
            broker_order_id=order_result.get("order_id", "sim_order"),
            status="OPEN",
        )
        session_db.add(trade)
        session_db.commit()
        
        trade_id = trade.id
        session_db.close()
        
        return trade_id, order_result.get("actual_entry", entry), order_result.get("order_id", "sim_order")
