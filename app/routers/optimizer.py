"""
Optimizer router.
GET  /api/optimizer/reports         — all weekly reports
GET  /api/optimizer/reports/{id}    — single report detail
POST /api/optimizer/approve/{id}/{n} — approve suggestion n (1,2,3)
POST /api/optimizer/reject/{id}/{n}  — reject suggestion n
POST /api/optimizer/run             — trigger optimizer manually
"""
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select, col
from app.database import get_session
from app.models.optimizer import Improvement

router = APIRouter(prefix="/api/optimizer", tags=["optimizer"])


class RejectBody(BaseModel):
    reason: Optional[str] = None


@router.get("/reports")
def list_reports(session: Session = Depends(get_session)):
    """All optimizer weekly reports, newest first."""
    reports = session.exec(
        select(Improvement).order_by(col(Improvement.week_ending).desc())
    ).all()
    return reports


@router.get("/reports/{report_id}")
def get_report(report_id: int, session: Session = Depends(get_session)):
    report = session.get(Improvement, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


@router.post("/approve/{report_id}/{suggestion_num}")
def approve_suggestion(
    report_id: int,
    suggestion_num: int,
    session: Session = Depends(get_session),
):
    """Approve suggestion 1, 2, or 3 in a report."""
    if suggestion_num not in (1, 2, 3):
        raise HTTPException(status_code=400, detail="suggestion_num must be 1, 2, or 3")

    report = session.get(Improvement, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    setattr(report, f"suggestion_{suggestion_num}_status", "APPROVED")
    setattr(report, f"suggestion_{suggestion_num}_reviewed_at", datetime.now(timezone.utc))
    session.add(report)
    session.commit()
    session.refresh(report)
    return {"message": f"Suggestion {suggestion_num} approved", "report": report}


@router.post("/reject/{report_id}/{suggestion_num}")
def reject_suggestion(
    report_id: int,
    suggestion_num: int,
    body: RejectBody,
    session: Session = Depends(get_session),
):
    """Reject suggestion 1, 2, or 3 with an optional reason."""
    if suggestion_num not in (1, 2, 3):
        raise HTTPException(status_code=400, detail="suggestion_num must be 1, 2, or 3")

    report = session.get(Improvement, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    setattr(report, f"suggestion_{suggestion_num}_status", "REJECTED")
    setattr(report, f"suggestion_{suggestion_num}_reviewed_at", datetime.now(timezone.utc))
    setattr(report, f"suggestion_{suggestion_num}_rejection_reason", body.reason)
    session.add(report)
    session.commit()
    session.refresh(report)
    return {"message": f"Suggestion {suggestion_num} rejected", "report": report}


@router.post("/run")
def trigger_optimizer(session: Session = Depends(get_session)):
    """Manually trigger the optimizer analysis. Runs in background."""
    try:
        import threading
        from optimizer.weekly_scheduler import run_optimizer_now
        thread = threading.Thread(target=run_optimizer_now, daemon=True)
        thread.start()
        return {"message": "Optimizer analysis started in background"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start optimizer: {e}")
