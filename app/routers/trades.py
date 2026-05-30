"""
Trades router — GET /api/trades, GET /api/trades/{id}
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select, col
from app.database import get_session
from app.models.trades import Trade, TradeOutcome, TradeJournal
from app.models.signals import Signal

router = APIRouter(prefix="/api/trades", tags=["trades"])


@router.get("")
def list_trades(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: Optional[str] = None,        # OPEN, WIN, LOSS, BE, CANCELLED
    direction: Optional[str] = None,     # LONG, SHORT
    session: Session = Depends(get_session),
):
    """Paginated list of all trades with optional filters."""
    query = select(Trade)
    if status:
        query = query.where(Trade.status == status.upper())
    if direction:
        query = query.where(Trade.direction == direction.upper())
    query = query.order_by(col(Trade.opened_at).desc())

    # Count total for pagination
    all_trades = session.exec(query).all()
    total = len(all_trades)
    offset = (page - 1) * page_size
    trades = all_trades[offset : offset + page_size]

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
        "items": trades,
    }


@router.get("/{trade_id}")
def get_trade_detail(trade_id: int, session: Session = Depends(get_session)):
    """Full trade detail — trade + outcome + journal + linked signal."""
    trade = session.get(Trade, trade_id)
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")

    outcome = session.exec(
        select(TradeOutcome).where(TradeOutcome.trade_id == trade_id)
    ).first()

    journal = session.exec(
        select(TradeJournal).where(TradeJournal.trade_id == trade_id)
    ).first()

    signal = None
    if trade.signal_id:
        signal = session.get(Signal, trade.signal_id)

    return {
        "trade": trade,
        "outcome": outcome,
        "journal": journal,
        "signal": signal,
    }


@router.patch("/{trade_id}/notes")
def update_trade_notes(
    trade_id: int,
    notes: str,
    session: Session = Depends(get_session),
):
    """Update manual notes on a trade journal entry."""
    journal = session.exec(
        select(TradeJournal).where(TradeJournal.trade_id == trade_id)
    ).first()
    if not journal:
        raise HTTPException(status_code=404, detail="Journal entry not found")
    journal.manual_notes = notes
    session.add(journal)
    session.commit()
    session.refresh(journal)
    return journal
