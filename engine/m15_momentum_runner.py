"""
engine/m15_momentum_runner.py — M15 2-Candle Momentum Pullback Runner
Runs every 15 minutes to find a sudden shift in momentum (engulfing/impulse).
Places a Limit Order at the 50% retracement of the impulse candle.
Magic Number: 202604.
"""
import logging
from datetime import datetime, timezone
import MetaTrader5 as mt5

from engine.db import get_session
from app.models.trades import Trade
from app.models.config import EngineConfig
from engine.broker_executor import _init_mt5, place_limit_order
from engine.data_fetcher import fetch_ohlcv
from engine.telegram_notifier import notify_info

logger = logging.getLogger("engine.m15_momentum_runner")

MAGIC_NUMBER = 202604

def run_m15_momentum_cycle():
    """
    Main loop for the M15 Two-Candle Pullback Runner.
    1. Fetch last few M15 candles.
    2. Check for 2-candle engulfing/momentum shift (>= 20 pips).
    3. Place Limit Order at the 50% retracement.
    """
    logger.info("="*60)
    logger.info("M15 Momentum Sibling cycle starting...")
    
    if not _init_mt5():
        logger.error("MT5 not initialized.")
        return

    # 1. Fetch M15 Data
    m15_df = fetch_ohlcv("M15", use_cache=False)

    if m15_df is None or len(m15_df) < 3:
        logger.warning("Insufficient M15 data for Momentum Runner.")
        return

    # We evaluate the two most recently CLOSED candles.
    c1 = m15_df.iloc[-3]
    c2 = m15_df.iloc[-2]
    
    is_c1_bearish = c1['close'] < c1['open']
    is_c2_bullish = c2['close'] > c2['open']
    
    is_c1_bullish = c1['close'] > c1['open']
    is_c2_bearish = c2['close'] < c2['open']
    
    c2_range = c2['high'] - c2['low']
    
    direction_filter = None
    limit_price = 0.0
    sl_price = 0.0
    
    # Check Bullish Shift (20 pips = 2.0 pts threshold for M15)
    if is_c1_bearish and is_c2_bullish and c2['close'] > c1['high'] and c2_range >= 2.0:
        direction_filter = "LONG"
        limit_price = c2['low'] + (c2_range * 0.5)
        sl_price = c2['low'] - 1.0 # 10 pip buffer below the impulse candle
        
    # Check Bearish Shift
    elif is_c1_bullish and is_c2_bearish and c2['close'] < c1['low'] and c2_range >= 2.0:
        direction_filter = "SHORT"
        limit_price = c2['high'] - (c2_range * 0.5)
        sl_price = c2['high'] + 1.0 # 10 pip buffer above the impulse candle

    if not direction_filter:
        logger.info("⏭️ [M15 Momentum] No 2-candle momentum shift detected. Skipping.")
        return

    # Calculate stop loss distance for lot sizing
    sl_dist_pips = abs(limit_price - sl_price) * 10.0
    sl_dist_pips = max(10.0, min(50.0, sl_dist_pips))

    # Check for existing pending orders to avoid duplicates
    session = get_session()
    try:
        active_runner_trades = session.query(Trade).filter(
            Trade.status.in_(["OPEN", "PENDING"])
        ).all()
        
        for t in active_runner_trades:
            if t.broker_order_id:
                mt5_pos = mt5.positions_get(ticket=int(t.broker_order_id))
                if mt5_pos and mt5_pos[0].magic == MAGIC_NUMBER:
                    if t.locked_profit_pips > 0:
                        logger.info(f"🔼 [M15 Momentum] Active trade #{t.id} is Risk-Free (Locked: {t.locked_profit_pips} pips)! Allowing new Pyramiding setup.")
                        continue
                    else:
                        logger.info("⏭️ [M15 Momentum] Active M15 trade is NOT Risk-Free yet. Skipping new setup.")
                        return
                mt5_order = mt5.orders_get(ticket=int(t.broker_order_id))
                if mt5_order and mt5_order[0].magic == MAGIC_NUMBER:
                    logger.info("♻️ [M15 Momentum] A pending M15 limit order exists. Cancelling the old one to replace.")
                    from engine.broker_executor import cancel_order
                    cancel_order(int(t.broker_order_id))
                    t.status = "CANCELLED"
                    session.add(t)
                    session.commit()

        # Place Limit Order
        tp_price = limit_price + 3.0 if direction_filter == "LONG" else limit_price - 3.0
        
        config = session.query(EngineConfig).filter(EngineConfig.is_active == True).first()
        if not config: config = EngineConfig()
        
        risk_dollars = config.account_balance_equiv * (config.max_risk_percent / 100)
        raw_lots = risk_dollars / (sl_dist_pips * 10.0)
        lot_size = max(0.01, round(raw_lots - (raw_lots % 0.01), 2))
            
        logger.info(f"✅ [M15 Momentum] Placing {direction_filter} Limit Order at {limit_price:.2f} | SL: {sl_price:.2f} | Lots: {lot_size}")
        
        ticket = place_limit_order(
            direction=direction_filter,
            lot_size=lot_size,
            entry_price=limit_price,
            stop_loss=sl_price,
            take_profit=tp_price,
            magic=MAGIC_NUMBER,
            comment="M15MomRunner"
        )
        
        if ticket and ticket.get("success"):
            new_trade = Trade(
                direction=direction_filter,
                status="PENDING",
                planned_entry=float(limit_price),
                stop_loss=float(sl_price),
                take_profit_1=float(tp_price),
                take_profit_2=0.0,
                lot_size=float(lot_size),
                planned_rr=float(round((abs(tp_price - limit_price)) / (abs(limit_price - sl_price) + 0.0001), 2) if tp_price else 0.0),
                broker_order_id=str(ticket["order_id"]),
                locked_profit_pips=0.0,
                highest_profit_pips=0.0
            )
            session.add(new_trade)
            session.commit()
            notify_info("M15 Momentum Sibling", f"🚀 Placed {direction_filter} Limit at {limit_price:.2f}\nSL: {sl_price:.2f}")
        else:
            logger.error("Failed to place M15 Momentum Sibling limit order.")
            
    except Exception as e:
        logger.exception(f"M15 Momentum loop error: {e}")
    finally:
        session.close()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_m15_momentum_cycle()
