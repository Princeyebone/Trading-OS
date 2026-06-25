"""
engine/momentum_runner.py — M15 FVG Sniper Runner
Runs every 15 minutes to find high-probability M15 Order Blocks with FVGs in the direction of the H1 EMA50.
Places limit orders at the OB zone with Magic Number 202602.
"""
import logging
from datetime import datetime, timezone
import ta
import MetaTrader5 as mt5

from app.settings import settings
from engine.db import get_session
from app.models.trades import Trade
from engine.broker_executor import _init_mt5, SYMBOL, place_limit_order
from engine.data_fetcher import fetch_ohlcv
from engine.pattern_detector import detect_fvg_order_blocks
from engine.telegram_notifier import notify_info

logger = logging.getLogger("engine.momentum_runner")

MAGIC_NUMBER = 202602

def run_momentum_cycle():
    """
    Main loop for the M15 Momentum Runner.
    1. Check H1 EMA50 trend.
    2. Scan M15 for valid Order Blocks.
    3. Place Limit Order at the latest valid OB.
    """
    logger.info("="*60)
    logger.info("M15 FVG Sniper cycle starting...")
    
    if not _init_mt5():
        logger.error("MT5 not initialized.")
        return

    # 1. Fetch Data
    h1_df = fetch_ohlcv("H1", use_cache=False)
    m15_df = fetch_ohlcv("M15", use_cache=False)

    if h1_df is None or m15_df is None or h1_df.empty or m15_df.empty:
        logger.warning("Insufficient data for Momentum Runner.")
        return

    # 2. Determine H1 Trend
    h1_df['ema50'] = ta.trend.ema_indicator(h1_df['close'], window=50)
    if h1_df['ema50'].isna().iloc[-1]:
        logger.warning("Not enough H1 data to compute EMA50.")
        return

    h1_close = h1_df['close'].iloc[-1]
    h1_ema50 = h1_df['ema50'].iloc[-1]
    
    is_bullish_trend = h1_close > h1_ema50
    direction_filter = "long" if is_bullish_trend else "short"
    
    logger.info(f"H1 Trend is {'BULLISH' if is_bullish_trend else 'BEARISH'} (Close: {h1_close:.2f}, EMA50: {h1_ema50:.2f})")

    # 3. Detect M15 Order Blocks
    # Use the last 40 candles of M15 for detection
    window_df = m15_df.iloc[-40:].reset_index(drop=True)
    obs = detect_fvg_order_blocks(window_df, direction=direction_filter)

    # Filter to match trend
    target_dir = 'BULLISH' if is_bullish_trend else 'BEARISH'
    valid_obs = [ob for ob in obs if ob['direction'] == target_dir]

    if not valid_obs:
        logger.info(f"⏭️ [M15 FVG Sniper] No {target_dir} M15 FVG Order Blocks found matching the H1 trend. Skipping.")
        return

    # Get the most recent valid OB
    latest_ob = valid_obs[0]
    ob_high = latest_ob['high']
    ob_low = latest_ob['low']
    
    current_m15_close = m15_df['close'].iloc[-1]
    
    # 4. Check for existing pending orders to avoid duplicates
    session = get_session()
    try:
        # Check active trades with this magic number
        active_runner_trades = session.query(Trade).filter(
            Trade.status.in_(["OPEN", "PENDING"])
        ).all()
        
        for t in active_runner_trades:
            if t.broker_order_id:
                mt5_pos = mt5.positions_get(ticket=int(t.broker_order_id))
                if mt5_pos and mt5_pos[0].magic == MAGIC_NUMBER:
                    if t.locked_profit_pips > 0:
                        logger.info(f"🔼 [M15 FVG Sniper] Active trade #{t.id} is Risk-Free (Locked: {t.locked_profit_pips} pips)! Allowing new Pyramiding setup.")
                        continue
                    else:
                        logger.info("⏭️ [M15 FVG Sniper] Active M15 trade is NOT Risk-Free yet. Skipping new setup.")
                        return
                mt5_order = mt5.orders_get(ticket=int(t.broker_order_id))
                if mt5_order and mt5_order[0].magic == MAGIC_NUMBER:
                    logger.info("♻️ [M15 FVG Sniper] A pending limit order exists. Cancelling the old one to favor the new FVG OB.")
                    from engine.broker_executor import cancel_order
                    cancel_order(int(t.broker_order_id))
                    t.status = "CANCELLED"
                    session.add(t)
                    session.commit()

        # 5. Place Limit Order
        limit_price = ob_high if is_bullish_trend else ob_low
        
        # Calculate SL buffer
        sl_dist_pips = (ob_high - ob_low) * 10 + 30.0 # 30 pip buffer
        sl_dist_pips = max(20.0, min(80.0, sl_dist_pips))
        
        if is_bullish_trend:
            sl_price = limit_price - (sl_dist_pips / 10.0)
            tp_price = limit_price + 5.0 # 50-pip TP
        else:
            sl_price = limit_price + (sl_dist_pips / 10.0)
            tp_price = limit_price - 5.0 # 50-pip TP
        from app.models.config import EngineConfig
        config = session.query(EngineConfig).filter(EngineConfig.is_active == True).first()
        if not config: config = EngineConfig()
        
        risk_dollars = config.account_balance_equiv * (config.max_risk_percent / 100)
        raw_lots = risk_dollars / (sl_dist_pips * 10.0)
        lot_size = max(0.01, round(raw_lots - (raw_lots % 0.01), 2))
            
        logger.info(f"✅ [M15 FVG Sniper] Placing {direction_filter.upper()} Limit Order at {limit_price:.2f} | SL: {sl_price:.2f} | Lots: {lot_size}")
        
        ticket = place_limit_order(
            direction=direction_filter.upper(),
            lot_size=lot_size,
            entry_price=limit_price,
            stop_loss=sl_price,
            take_profit=tp_price,
            magic=MAGIC_NUMBER,
            comment="MomentumRunner"
        )
        
        if ticket and ticket.get("success"):
            new_trade = Trade(
                direction=direction_filter.upper(),
                status="PENDING",
                planned_entry=float(limit_price),
                stop_loss=float(sl_price),
                take_profit_1=float(tp_price),
                take_profit_2=float(tp_price),
                lot_size=float(lot_size),
                planned_rr=float(round((abs(tp_price - limit_price)) / (abs(limit_price - sl_price) + 0.0001), 2)),
                broker_order_id=str(ticket["order_id"]),
                locked_profit_pips=0.0,
                highest_profit_pips=0.0
            )
            session.add(new_trade)
            session.commit()
            notify_info("M15 FVG Sniper", f"🚀 Placed {direction_filter.upper()} Limit at {limit_price:.2f}\nSL: {sl_price:.2f}")
        else:
            logger.error("Failed to place FVG Sniper limit order.")
            
    except Exception as e:
        logger.exception(f"FVG Sniper loop error: {e}")
    finally:
        session.close()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_momentum_cycle()
