import pandas as pd
from datetime import datetime, timezone
import logging
import MetaTrader5 as mt5
import ta

from engine import broker_executor
from app.models.trades import Trade
from app.models.signals import Signal
from engine.db import get_session
from engine import telegram_notifier

logger = logging.getLogger("engine.eusdi7_momentum_scalper")

MAGIC_NUMBER = 203100
SYMBOL = "EURUSD"
SL_PIPS = 5.0
TP_PIPS = 5.0

class Eusdi7MomentumScalper:
    def __init__(self):
        pass

    def check_and_execute(self, config) -> list:
        # 1. Init MT5
        if not broker_executor._init_mt5():
            logger.error("MT5 not initialized. Cannot fetch EUSDI7 data.")
            return []

        # Check if already in trade (MAX_OPEN_TRADES = 1)
        positions = mt5.positions_get(symbol=SYMBOL)
        if positions:
            for p in positions:
                if p.magic == MAGIC_NUMBER:
                    logger.info(f"[{SYMBOL}-i7] Trade already active, skipping new signals.")
                    return []

        # 2. Fetch M1 and M5 Data
        rates_m1 = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 0, 100)
        rates_m5 = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M5, 0, 100)
        
        if rates_m1 is None or len(rates_m1) < 50 or rates_m5 is None or len(rates_m5) < 50:
            logger.warning("Insufficient data for EUSDI7 scalping")
            return []
            
        m1_data = pd.DataFrame(rates_m1)
        m1_data['time_dt'] = pd.to_datetime(m1_data['time'], unit='s')
        
        m5_data = pd.DataFrame(rates_m5)
        m5_data['time_dt'] = pd.to_datetime(m5_data['time'], unit='s')
        
        # 3. Calculate Indicators
        m1_close = m1_data['close']
        m5_close = m5_data['close']
        
        # M5 EMAs for micro-trend direction
        m5_data['ema20'] = ta.trend.ema_indicator(m5_close, window=20)
        m5_data['ema50'] = ta.trend.ema_indicator(m5_close, window=50)
        
        # M1 RSI and ATR for momentum and volatility bursts
        m1_data['rsi'] = ta.momentum.rsi(m1_close, window=14)
        
        # True Range for M1
        high_low = m1_data['high'] - m1_data['low']
        high_close = (m1_data['high'] - m1_data['close'].shift()).abs()
        low_close = (m1_data['low'] - m1_data['close'].shift()).abs()
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = ranges.max(axis=1)
        m1_data['atr'] = true_range.rolling(14).mean()
        m1_data['candle_size'] = true_range

        # Use the fully closed previous M1 candle and current M5 state
        current_m1 = m1_data.iloc[-2]
        current_m5 = m5_data.iloc[-2]
        
        m5_ema20 = float(current_m5['ema20'])
        m5_ema50 = float(current_m5['ema50'])
        
        m1_price = float(current_m1['close'])
        m1_rsi = float(current_m1['rsi'])
        m1_atr = float(current_m1['atr'])
        m1_candle_size = float(current_m1['candle_size'])

        direction = None

        # Logic: Momentum Breakout & Trend Continuation
        # 1. Check M5 Trend
        m5_trend = "NONE"
        if m5_ema20 > m5_ema50:
            m5_trend = "BULLISH"
        elif m5_ema20 < m5_ema50:
            m5_trend = "BEARISH"
            
        # 2. Hyper-Aggressive Momentum Trigger
        # If M5 is trending, just wait for M1 RSI to show momentum in that direction.
        # No more waiting for massive volatility bursts which EURUSD rarely prints.
        if m5_trend == "BULLISH" and m1_rsi > 55:
            direction = "LONG"
        elif m5_trend == "BEARISH" and m1_rsi < 45:
            direction = "SHORT"

        logger.info(f"[EUSDI7 Debug] Price: {m1_price:.5f}, M5 Trend: {m5_trend}, RSI: {m1_rsi:.1f}, Dir: {direction}")

        if not direction:
            return []

        # 4. Calculate precise stops and targets (5 pips = 0.00050)
        pip_size = 0.0001
        lot_size = 0.1 # Hardcoded for EURUSD
        
        if direction == "LONG":
            sl_price = round(m1_price - (SL_PIPS * pip_size), 5)
            tp_price = round(m1_price + (TP_PIPS * pip_size), 5)
        else:
            sl_price = round(m1_price + (SL_PIPS * pip_size), 5)
            tp_price = round(m1_price - (TP_PIPS * pip_size), 5)

        logger.info(f"[{SYMBOL}-i7-v1] Firing {direction} Momentum Scalp | Price: {m1_price} | SL: {sl_price} | TP: {tp_price}")

        success = broker_executor.place_order(
            direction=direction,
            lot_size=lot_size,
            entry_price=m1_price,
            stop_loss=sl_price,
            take_profit=tp_price,
            comment="EURUSD-i7",
            symbol=SYMBOL,
            magic=MAGIC_NUMBER
        )

        executed_signals = []
        if success.get("success"):
            actual_entry = success.get("actual_entry", m1_price)
            order_id = success.get("order_id", 0)
            logger.info(f"Successfully placed {direction} order for {SYMBOL} [i7]")
            
            # Save signal and trade to DB
            session = get_session()
            try:
                sig = Signal(
                    timeframe="M1",
                    session="EUSDI7",
                    verdict="TRADE",
                    direction=direction,
                    confidence=95,
                    price_at_signal=m1_price,
                    prompt_version=0
                )
                session.add(sig)
                session.flush()

                new_trade = Trade(
                    signal_id=sig.id,
                    direction=direction,
                    planned_entry=m1_price,
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
                logger.error(f"Failed to save {SYMBOL} i7 trade to DB: {e}")
                session.rollback()
            finally:
                session.close()
                
            executed_signals.append({
                "type": "Momentum Breakout",
                "direction": direction,
                "price": actual_entry,
                "sl": sl_price,
                "tp": tp_price
            })
            
            order_id_str = str(order_id)
            telegram_notifier.notify_trade_executed(
                direction=direction,
                entry=actual_entry,
                stop_loss=sl_price,
                tp1=tp_price,
                tp2=0.0,
                lot_size=lot_size,
                confidence=95,
                order_id=order_id_str,
                reasoning=f"EUSDI7 M1+M5 Momentum Scalp",
                symbol=SYMBOL,
                system="EUSDI7"
            )
        else:
            logger.error(f"Failed to place {direction} order for {SYMBOL} [i7]")

        return executed_signals
