import sys
from sqlmodel import Session, select
from app.database import engine
from app.models.trades import Trade, TradeJournal
from app.models.signals import MarketContext

with Session(engine) as session:
    # Get last 100 trades
    last_100_trades = session.exec(
        select(Trade).order_by(Trade.opened_at.desc()).limit(100)
    ).all()
    
    if not last_100_trades:
        print("No historical trades found.")
        sys.exit(0)
        
    count = 0
    details = []

    for trade in last_100_trades:
        # Check if profitable
        if trade.status != "WIN":
            continue
            
        # Check MarketContext for ATR percentile
        mc = session.exec(
            select(MarketContext).where(MarketContext.signal_id == trade.signal_id)
        ).first()
        
        if not mc or mc.atr_percentile is None:
            continue
            
        if mc.atr_percentile >= 20.0:
            continue
            
        # Check TradeJournal for strategy
        journal = session.exec(
            select(TradeJournal).where(TradeJournal.trade_id == trade.id)
        ).first()
        
        if not journal or not journal.pre_trade_analysis:
            continue
            
        analysis_text = journal.pre_trade_analysis.upper()
        # Look for the strategy tag or keywords
        is_target_strategy = False
        strategy_found = "UNKNOWN"
        for strat in ["TCP", "LSR", "D-FVG"]:
            # Depending on how the strategy is formatted in the journal. 
            # e.g., "[Strategy: TCP]" or just checking if the string is present.
            if f"[STRATEGY: {strat}]" in analysis_text or f"STRATEGY_NAME: {strat}" in analysis_text:
                is_target_strategy = True
                strategy_found = strat
                break
                
        # Fallback if it wasn't formatted properly but mentions the strategy name prominently
        if not is_target_strategy:
            for strat in ["TCP", "LSR", "D-FVG"]:
                if f"STRATEGY: {strat}" in analysis_text or f"STRATEGY {strat}" in analysis_text:
                    is_target_strategy = True
                    strategy_found = strat
                    break
        
        if is_target_strategy:
            count += 1
            details.append(f"Trade #{trade.id} ({strategy_found}), ATR Pct: {mc.atr_percentile:.1f}")

    print(f"Total profitable target setups under 20th ATR percentile: {count}")
    for d in details:
        print(f" - {d}")
