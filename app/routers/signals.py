"""
Signals router — GET /api/signals
"""
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select, col
from app.database import get_session
from app.models.signals import Signal

router = APIRouter(prefix="/api/signals", tags=["signals"])


@router.get("")
def list_signals(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    verdict: Optional[str] = None,       # TRADE or WAIT
    session_filter: Optional[str] = Query(default=None, alias="session"),
    min_confidence: Optional[int] = None,
    session: Session = Depends(get_session),
):
    """All signals (TRADE + WAIT) with pagination and filters."""
    query = select(Signal)
    if verdict:
        query = query.where(Signal.verdict == verdict.upper())
    if session_filter:
        query = query.where(Signal.session == session_filter.upper())
    if min_confidence is not None:
        query = query.where(Signal.confidence >= min_confidence)
    query = query.order_by(col(Signal.created_at).desc())

    all_signals = session.exec(query).all()
    total = len(all_signals)
    offset = (page - 1) * page_size
    signals = all_signals[offset : offset + page_size]

    # Confidence histogram data
    confidence_dist = {}
    for sig in all_signals:
        if sig.confidence is not None:
            bucket = (sig.confidence // 5) * 5  # group into 5-point buckets
            confidence_dist[bucket] = confidence_dist.get(bucket, 0) + 1

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
        "items": signals,
        "confidence_distribution": confidence_dist,
    }
