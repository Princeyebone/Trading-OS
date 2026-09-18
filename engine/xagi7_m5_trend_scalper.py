import pandas as pd
from datetime import datetime, timezone
import logging
import MetaTrader5 as mt5
import ta
import time

from engine import broker_executor
from app.models.trades import Trade
from app.models.signals import Signal
from engine.db import get_session
from engine import telegram_notifier
from engine.scalping_engine import ScalpingEngine, M1HyperEngine

logger = logging.getLogger("engine.xagi7_m5_trend_scalper")

MAGIC_NUMBER = 203400
SYMBOL = "XAUUSD"

class Xagi7M5TrendScalper:
    def __init__(self):
        # Prevent overtrading
        self.last_trade_time = 0.0
        self.trade_cooldown = 1800  # 30-minute cooldown
        
    def _is_cooling_down(self):
        return (time.time() - self.last_trade_time) < self.trade_cooldown

    def check_and_execute(self, config) -> list:
        """Runs the M5 Trend analysis and executes M5 Scalping signals."""
        if self._is_cooling_down():
            return []
            
        if not broker_executor._init_mt5():
            return []

        # Check for open trades from this system
        positions = mt5.positions_get(symbol=SYMBOL)
        if positions:
            for p in positions:
                if p.magic == MAGIC_NUMBER:
                    logger.info(f"[{SYMBOL}-i7] Trade already active, skipping new signals.")
                    return []

        rates_m5 = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M5, 0, 100)
        if rates_m5 is None or len(rates_m5) < 50:
            return []
            
        m5_data = pd.DataFrame(rates_m5)
        m5_data['time_dt'] = pd.to_datetime(m5_data['time'], unit='s')
        
        # Calculate M5 EMAs
        m5_data['ema_fast'] = ta.trend.ema_indicator(m5_data['close'], window=20)
        m5_data['ema_slow'] = ta.trend.ema_indicator(m5_data['close'], window=50)
        
        current_m5 = m5_data.iloc[-2]  # Fully closed candle
        
        if current_m5['ema_fast'] > current_m5['ema_slow']:
            m5_trend = "BULLISH"
        elif current_m5['ema_fast'] < current_m5['ema_slow']:
            m5_trend = "BEARISH"
        else:
            m5_trend = "SIDEWAYS"
            
        if m5_trend == "SIDEWAYS":
            return []
            
        # Scan for M5 Setups using ScalpingEngine
        engine = ScalpingEngine(m5_data, m5_data)
        signals = engine.scan(len(m5_data)-2, h4_trend=m5_trend)
        
        # Filter signals to only match the M5 Trend
        valid_signals = [s for s in signals if s['direction'] == m5_trend]
        
        if not valid_signals:
            return []
            
        # Execute the first valid signal
        return self._execute_signal(valid_signals[0], "M5", config)
        
    def check_and_execute_m1(self, config) -> list:
        """Runs the M1 analysis, ensuring alignment with M5 Trend."""
        if self._is_cooling_down():
            return []
            
        if not broker_executor._init_mt5():
            return []
            
        positions = mt5.positions_get(symbol=SYMBOL)
        if positions:
            for p in positions:
                if p.magic == MAGIC_NUMBER:
                    return []

        rates_m1 = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 0, 100)
        rates_m5 = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M5, 0, 100)
        if rates_m1 is None or len(rates_m1) < 50 or rates_m5 is None or len(rates_m5) < 50:
            return []
            
        m5_data = pd.DataFrame(rates_m5)
        m5_data['ema_fast'] = ta.trend.ema_indicator(m5_data['close'], window=20)
        m5_data['ema_slow'] = ta.trend.ema_indicator(m5_data['close'], window=50)
        current_m5 = m5_data.iloc[-2]
        
        if current_m5['ema_fast'] > current_m5['ema_slow']: m5_trend = "BULLISH"
        elif current_m5['ema_fast'] < current_m5['ema_slow']: m5_trend = "BEARISH"
        else: return []
        
        m1_data = pd.DataFrame(rates_m1)
        m1_data['time_dt'] = pd.to_datetime(m1_data['time'], unit='s')
        
        engine = M1HyperEngine(m1_data, h4_trend=m5_trend)
        signals = engine.scan(len(m1_data)-2)
        
        valid_signals = [s for s in signals if s['direction'] == m5_trend]
        
        if not valid_signals:
            return []
            
        return self._execute_signal(valid_signals[0], "M1", config)
        
    def _execute_signal(self, sig, timeframe, config) -> list:
        # Scalping engines return BULLISH/BEARISH, map them to LONG/SHORT for MT5 and DB
        raw_dir = sig['direction']
        direction = "LONG" if raw_dir == "BULLISH" else "SHORT"
        
        entry_price = float(mt5.symbol_info_tick(SYMBOL).ask if direction == "LONG" else mt5.symbol_info_tick(SYMBOL).bid)
        
        # Widen SL to 50 pips to avoid tight whip-saws in Gold
        sl_pips = 50.0
        pip_size = 0.01  # Gold
        
        if direction == "LONG":
            sl_price = round(entry_price - (sl_pips * pip_size * 10), 2)
            tp_price = round(entry_price + (100.0 * pip_size * 10), 2) # Open TP, managed by trailing
        else:
            sl_price = round(entry_price + (sl_pips * pip_size * 10), 2)
            tp_price = round(entry_price - (100.0 * pip_size * 10), 2)
            
        lot_size = 0.1
        
        success = broker_executor.place_order(
            direction=direction,
            lot_size=lot_size,
            entry_price=entry_price,
            stop_loss=sl_price,
            take_profit=tp_price,
            comment="XAUUSD-i7",
            symbol=SYMBOL,
            magic=MAGIC_NUMBER
        )
        
        if success.get("success"):
            self.last_trade_time = time.time()
            order_id = success.get("order_id", 0)
            actual_entry = success.get("actual_entry", entry_price)
            
            session = get_session()
            try:
                sig_record = Signal(
                    timeframe=timeframe,
                    session="XAGI7",
                    verdict="TRADE",
                    direction=direction,
                    confidence=95,
                    price_at_signal=entry_price,
                    prompt_version=0
                )
                session.add(sig_record)
                session.flush()

                new_trade = Trade(
                    signal_id=sig_record.id,
                    direction=direction,
                    planned_entry=entry_price,
                    actual_entry=actual_entry,
                    stop_loss=sl_price,
                    take_profit_1=tp_price,
                    lot_size=lot_size,
                    status="OPEN",
                    broker_order_id=order_id
                )
                session.add(new_trade)
                session.commit()
            except Exception as e:
                logger.error(f"DB Error saving XAGI7 trade: {e}")
                session.rollback()
            finally:
                session.close()
                
            return [sig]
        return []
