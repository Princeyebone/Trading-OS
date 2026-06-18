import sys
import os
from datetime import datetime, timezone
import MetaTrader5 as mt5

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine.db import get_session
from app.models.trades import Trade, TradeOutcome, TradeJournal
from engine.outcome_monitor import _compute_pnl, _compute_result, _compute_r_achieved, _generate_post_trade_journal
from sqlmodel import select

def fix_today_trades():
    session = get_session()
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    
    trades = session.exec(
        select(Trade).where(Trade.opened_at >= today_start)
    ).all()
    
    if not mt5.initialize():
        print("MT5 init failed")
        return
        
    fixed_count = 0
    created_count = 0
    
    for trade in trades:
        if not trade.broker_order_id:
            continue
            
        deals = mt5.history_deals_get(position=int(trade.broker_order_id))
        if not deals:
            # Still open or not found
            continue
            
        exit_price = None
        actual_profit = 0.0
        for d in deals:
            if d.entry == 1: # DEAL_ENTRY_OUT
                exit_price = float(d.price)
                actual_profit += float(d.profit)
                
        if exit_price is None:
            continue
            
        # Recompute everything correctly
        result = _compute_result(actual_profit)
        pnl_pips, pnl_dollars = _compute_pnl(trade, exit_price, actual_profit)
        r_achieved = _compute_r_achieved(trade, exit_price)
        
        trade.status = result
        if not trade.closed_at:
            trade.closed_at = datetime.now(timezone.utc)
            
        outcome = session.exec(
            select(TradeOutcome).where(TradeOutcome.trade_id == trade.id)
        ).first()
        
        if outcome:
            outcome.exit_price = exit_price
            outcome.pnl_pips = pnl_pips
            outcome.pnl_dollars = pnl_dollars
            outcome.r_achieved = r_achieved
            if not outcome.closed_at:
                outcome.closed_at = trade.closed_at
            fixed_count += 1
        else:
            # Determine exit reason simplified
            if trade.direction == "LONG":
                exit_reason = "TP1_HIT" if exit_price >= trade.take_profit_1 else "SL_HIT"
            else:
                exit_reason = "TP1_HIT" if exit_price <= trade.take_profit_1 else "SL_HIT"
                
            outcome = TradeOutcome(
                trade_id=trade.id,
                exit_price=exit_price,
                exit_reason=exit_reason,
                pnl_pips=pnl_pips,
                pnl_dollars=pnl_dollars,
                r_achieved=r_achieved,
                duration_mins=int((trade.closed_at.replace(tzinfo=timezone.utc) - trade.opened_at.replace(tzinfo=timezone.utc)).total_seconds() / 60),
                closed_at=trade.closed_at
            )
            session.add(outcome)
            
            # Generate missing journal
            journal_data = _generate_post_trade_journal(trade, outcome)
            existing_journal = session.exec(
                select(TradeJournal).where(TradeJournal.trade_id == trade.id)
            ).first()
            if existing_journal:
                for k, v in journal_data.items():
                    setattr(existing_journal, k, v)
                session.add(existing_journal)
            else:
                session.add(TradeJournal(trade_id=trade.id, **journal_data))
            created_count += 1
            
        session.add(trade)
        session.add(outcome)
        
    session.commit()
    print(f"Fixed {fixed_count} existing outcomes and created {created_count} missing outcomes.")

if __name__ == "__main__":
    fix_today_trades()
