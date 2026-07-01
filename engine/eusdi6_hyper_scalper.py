import pandas as pd
from datetime import datetime, timezone
import logging
import MetaTrader5 as mt5
import ta

from engine import broker_executor
from app.models.signals import Signal
from engine.db import get_session

logger = logging.getLogger("engine.eusdi6_hyper_scalper")

MAGIC_NUMBER = 203000
SYMBOL = "EURUSD"
SL_PIPS = 10.0

class Eusdi6HyperScalper:
    def __init__(self):
        pass

    def check_and_execute(self, config) -> list:
        # 1. Init MT5
        if not broker_executor._init_mt5():
            logger.error("MT5 not initialized. Cannot fetch EUSDI6 data.")
            return []

        # 2. Fetch M1 Data directly
        rates_m1 = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 0, 100)
        if rates_m1 is None or len(rates_m1) < 50:
            logger.warning("Insufficient M1 data for EUSDI6 scalping")
            return []
            
        m1_data = pd.DataFrame(rates_m1)
        m1_data['time_dt'] = pd.to_datetime(m1_data['time'], unit='s')
        
        # 3. Calculate Indicators
        close_series = m1_data['close']
        bb = ta.volatility.BollingerBands(close_series, window=20, window_dev=2.0)
        m1_data['bb_upper'] = bb.bollinger_hband()
        m1_data['bb_lower'] = bb.bollinger_lband()
        m1_data['bb_mid'] = bb.bollinger_mavg()
        m1_data['rsi'] = ta.momentum.rsi(close_series, window=14)

        # Use the fully closed previous candle, not the unformed current candle
        current = m1_data.iloc[-2]
        current_price = float(current['close'])
        bb_upper = float(current['bb_upper'])
        bb_lower = float(current['bb_lower'])
        bb_mid = float(current['bb_mid'])
        rsi = float(current['rsi'])

        direction = None

        # Mean Reversion Logic
        if current_price < bb_lower and rsi < 40:
            direction = "LONG"
        elif current_price > bb_upper and rsi > 60:
            direction = "SHORT"
            
        logger.info(f"[EUSDI6 Debug] Price: {current_price:.5f}, BB_Lower: {bb_lower:.5f}, BB_Upper: {bb_upper:.5f}, RSI: {rsi:.1f}, Dir: {direction}")

        if not direction:
            return []

        # Target is the middle of the Bollinger Band
        target_price = bb_mid
        target_pips = abs(current_price - target_price) * 10000
        # Ensure target is minimum 3 pips, max 10 pips
        target_pips = max(3.0, min(10.0, target_pips))

        # Check if already in trade to prevent pyramiding in the exact same chop zone
        positions = mt5.positions_get(symbol=SYMBOL)
        if positions:
            for p in positions:
                if p.magic == MAGIC_NUMBER:
                    logger.info(f"[{SYMBOL}-i6] Trade already active, skipping new {direction} signal.")
                    return []

        executed = []
        try:
            lot_size = 0.1 # Hardcoded for EURUSD
            
            sl_price = current_price - (SL_PIPS / 10000.0) if direction == "LONG" else current_price + (SL_PIPS / 10000.0)
            tp_price = current_price + (target_pips / 10000.0) if direction == "LONG" else current_price - (target_pips / 10000.0)
            
            # Place Order
            order_result = broker_executor.place_order(
                direction=direction,
                lot_size=lot_size,
                entry_price=current_price,
                stop_loss=sl_price,
                take_profit=tp_price,
                comment=f"{SYMBOL}-i6-v2",
                symbol=SYMBOL,
                magic=MAGIC_NUMBER
            )

            if order_result.get("success"):
                # Save signal
                session = get_session()
                try:
                    sig = Signal(
                        timeframe="M1",
                        session="EUSDI6",
                        verdict="TRADE",
                        direction=direction,
                        confidence=90,
                        skip_reason=None,
                        price_at_signal=current_price,
                        prompt_version=0
                    )
                    session.add(sig)
                    session.flush()
                    
                    from app.models.trades import Trade
                    trade = Trade(
                        signal_id=sig.id,
                        direction=direction,
                        planned_entry=current_price,
                        actual_entry=order_result["actual_entry"],
                        slippage_pips=order_result.get("slippage_pips", 0.0),
                        stop_loss=sl_price,
                        take_profit_1=tp_price,
                        take_profit_2=0.0,
                        lot_size=lot_size,
                        planned_rr=1.0,
                        broker_order_id=order_result["order_id"],
                        status="OPEN"
                    )
                    session.add(trade)
                    session.commit()
                except Exception as e:
                    logger.error(f"Failed to save signal/trade: {e}")
                finally:
                    session.close()

                executed.append({
                    'direction': direction,
                    'type': 'MR_SCALP',
                    'price': current_price
                })
        except Exception as e:
            logger.exception(f"Execution failed: {e}")

        return executed
