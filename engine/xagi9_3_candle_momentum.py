"""
engine/xagi9_3_candle_momentum.py
M5 3-Candle Momentum Continuation Strategy for XAUUSD.
Enters precisely when a third candle opens in the direction of two previous valid momentum candles.
"""
import pandas as pd
from datetime import datetime, timezone
import logging
import MetaTrader5 as mt5

from engine.data_fetcher import fetch_ohlcv
from engine import broker_executor
from app.models.signals import Signal
from engine.db import get_session

logger = logging.getLogger("engine.xagi9_3_candle")
MAGIC_NUMBER = 202809
SYMBOL = "XAUUSD"

class Xagi9ThreeCandleMomentum:
    def __init__(self):
        self.lot_size = 0.05
        # Optimum Parameters found via backtesting
        self.min_body_size = 0.5 # 5 pips minimum body for c1 and c2
        self.sl_buffer = 1.0 # 10 pips buffer behind c2
        self.trail_activation = 20.0 # 20 pips trailing

    def _has_open_trade(self) -> bool:
        """Check if we already have an open XAGI9 trade."""
        positions = mt5.positions_get(symbol=SYMBOL)
        if positions:
            for p in positions:
                if p.magic == MAGIC_NUMBER:
                    return True
        return False

    def scan_m5(self):
        """Scan M5 data for the 3-candle momentum setup."""
        m5_data = fetch_ohlcv("M5", use_cache=False)
        if m5_data is None or len(m5_data) < 5:
            logger.warning("[XAUUSD-i9] Insufficient M5 data")
            return []
            
        # c1 = index -3 (closed 2 periods ago)
        # c2 = index -2 (closed 1 period ago)
        # c3 = index -1 (currently active, just opened)
        c1 = m5_data.iloc[-3]
        c2 = m5_data.iloc[-2]
        c3 = m5_data.iloc[-1]
        
        c1_body = c1['close'] - c1['open']
        c2_body = c2['close'] - c2['open']
        
        # We need both c1 and c2 to be bullish, or both bearish, with a minimum body size
        is_bullish_momentum = (c1_body >= self.min_body_size) and (c2_body >= self.min_body_size)
        is_bearish_momentum = (c1_body <= -self.min_body_size) and (c2_body <= -self.min_body_size)
        
        current_price = mt5.symbol_info_tick(SYMBOL).ask if is_bullish_momentum else mt5.symbol_info_tick(SYMBOL).bid
        if not current_price:
            return []
            
        new_signals = []
        
        # Check if C3 has opened in the same direction
        # Since we run this every minute, C3 could be up to 60 seconds old. 
        # We ensure it is moving in our direction relative to its open.
        if is_bullish_momentum and current_price > c3['open']:
            sl = c2['low'] - self.sl_buffer
            risk = current_price - sl
            if risk > 0 and risk < 5.0: # Max 50 pips risk
                # TP is managed by trailing stop, but we set a high virtual TP
                tp = current_price + 100.0 
                
                new_signals.append({
                    "type": "3_CANDLE_BULLISH",
                    "direction": "LONG",
                    "entry": float(current_price),
                    "sl": float(sl),
                    "tp1": float(tp),
                    "rr": 0, # Managed
                    "price": float(current_price),
                    "timeframe": "M5",
                    "timestamp": datetime.now(timezone.utc)
                })
                
        elif is_bearish_momentum and current_price < c3['open']:
            sl = c2['high'] + self.sl_buffer
            risk = sl - current_price
            if risk > 0 and risk < 5.0:
                tp = current_price - 100.0
                
                new_signals.append({
                    "type": "3_CANDLE_BEARISH",
                    "direction": "SHORT",
                    "entry": float(current_price),
                    "sl": float(sl),
                    "tp1": float(tp),
                    "rr": 0,
                    "price": float(current_price),
                    "timeframe": "M5",
                    "timestamp": datetime.now(timezone.utc)
                })
                
        return new_signals
        
    def _is_duplicate(self, signal, lockout_seconds=300):
        session = get_session()
        try:
            from sqlmodel import select
            from app.models.trades import Trade
            recent = session.exec(
                select(Trade)
                .where(Trade.direction == signal['direction'])
                .order_by(Trade.id.desc())
                .limit(5)
            ).all()
            
            now = datetime.now(timezone.utc)
            for t in recent:
                trade_time = t.opened_at.replace(tzinfo=timezone.utc) if t.opened_at.tzinfo is None else t.opened_at
                if (now - trade_time).total_seconds() < lockout_seconds:
                    return True
            return False
        except Exception:
            return False
        finally:
            session.close()
            
    def _execute_signal(self, sig, config) -> tuple:
        success = broker_executor.place_order(
            direction=sig['direction'],
            lot_size=self.lot_size,
            entry_price=sig['entry'],
            stop_loss=sig['sl'],
            take_profit=sig['tp1'],
            comment="XAUUSD-i9-3Candle",
            symbol=SYMBOL,
            magic=MAGIC_NUMBER
        )
        
        if success.get("success"):
            order_id = success.get("order_id", 0)
            actual_entry = success.get("actual_entry", sig['entry'])
            
            session = get_session()
            try:
                from app.models.trades import Trade
                sig_record = Signal(
                    timeframe=sig['timeframe'],
                    session="XAGI9",
                    verdict="TRADE",
                    direction=sig['direction'],
                    confidence=90,
                    price_at_signal=sig['price'],
                    prompt_version=0
                )
                session.add(sig_record)
                session.flush()

                new_trade = Trade(
                    signal_id=sig_record.id,
                    direction=sig['direction'],
                    planned_entry=sig['entry'],
                    actual_entry=actual_entry,
                    stop_loss=sig['sl'],
                    take_profit_1=sig['tp1'],
                    lot_size=self.lot_size,
                    status="OPEN",
                    broker_order_id=order_id
                )
                session.add(new_trade)
                session.commit()
                return new_trade.id, actual_entry, order_id
            except Exception as e:
                logger.error(f"DB Error saving XAGI9 trade: {e}")
                session.rollback()
            finally:
                session.close()
                
        return None, None, None

    def check_and_execute(self, config):
        """Check for new signals and execute them."""
        new_signals = self.scan_m5()
        
        if not new_signals:
            return []
            
        if self._has_open_trade():
            return []
        
        executed = []
        for signal in new_signals:
            # Prevent entering multiple times on the same candle (300s lockout)
            if self._is_duplicate(signal, lockout_seconds=300):
                continue
            
            trade_id, actual_entry, order_id = self._execute_signal(signal, config)
            if trade_id:
                signal['trade_id'] = trade_id
                signal['actual_entry'] = actual_entry
                signal['order_id'] = order_id
                executed.append(signal)
                break
        
        return executed
