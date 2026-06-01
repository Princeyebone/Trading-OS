"""
optimizer/report_generator.py — Format optimizer suggestions and store to improvements table.
"""
import logging
from datetime import date, timedelta
from sqlmodel import Session

from engine.db import get_session
from app.models.optimizer import Improvement
from engine import telegram_notifier

logger = logging.getLogger(__name__)


def save_report(stats: dict, suggestions_data: dict) -> Improvement:
    """
    Store optimizer report to improvements table.
    suggestions_data: the parsed JSON from claude_optimizer.run_optimizer_analysis()
    """
    suggestions = suggestions_data.get("suggestions", [])

    def _s(n: int, field: str):
        if n <= len(suggestions):
            return suggestions[n - 1].get(field)
        return None

    period_end   = date.fromisoformat(stats["period_end"])
    period_start = date.fromisoformat(stats["period_start"])

    report = Improvement(
        week_ending=period_end,
        period_start=period_start,
        period_end=period_end,
        total_trades=stats["total_trades"],
        win_rate=stats["win_rate"],
        avg_r=stats["avg_r_achieved"],
        # Suggestion 1
        suggestion_1_impact=_s(1, "impact"),
        suggestion_1_finding=_s(1, "finding"),
        suggestion_1_recommendation=_s(1, "recommendation"),
        suggestion_1_expected_impact=_s(1, "expected_impact"),
        suggestion_1_verify_by=_s(1, "verify_by"),
        suggestion_1_status="PENDING",
        # Suggestion 2
        suggestion_2_impact=_s(2, "impact"),
        suggestion_2_finding=_s(2, "finding"),
        suggestion_2_recommendation=_s(2, "recommendation"),
        suggestion_2_expected_impact=_s(2, "expected_impact"),
        suggestion_2_verify_by=_s(2, "verify_by"),
        suggestion_2_status="PENDING",
        # Suggestion 3
        suggestion_3_impact=_s(3, "impact"),
        suggestion_3_finding=_s(3, "finding"),
        suggestion_3_recommendation=_s(3, "recommendation"),
        suggestion_3_expected_impact=_s(3, "expected_impact"),
        suggestion_3_verify_by=_s(3, "verify_by"),
        suggestion_3_status="PENDING",
        raw_optimizer_response=str(suggestions_data),
    )

    session = get_session()
    try:
        session.add(report)
        session.commit()
        session.refresh(report)
        logger.info(f"Optimizer report saved: ID={report.id} | Week ending {period_end}")
        return report
    finally:
        session.close()


def run_full_optimizer(period_start=None, period_end=None):
    """
    Full optimizer pipeline:
    1. Aggregate weekly stats
    2. Call Claude optimizer
    3. Save report to DB
    4. Send Telegram notification
    """
    from optimizer.data_aggregator import aggregate_weekly_stats
    from optimizer.claude_optimizer import run_optimizer_analysis as claude_run
    from optimizer.qwen_optimizer import run_optimizer_analysis as qwen_run
    from app.models.config import EngineConfig
    from sqlmodel import select

    logger.info("Optimizer starting...")

    stats = aggregate_weekly_stats(period_start, period_end)
    logger.info(f"Stats aggregated: {stats['total_trades']} trades | {stats['win_rate']}% win rate")

    session = get_session()
    config = session.exec(select(EngineConfig).where(EngineConfig.is_active == True)).first()
    session.close()

    provider = config.ai_provider.lower() if config else "claude"
    logger.info(f"Using optimizer provider: {provider.upper()}")

    if provider == "qwen":
        suggestions = qwen_run(stats)
    else:
        suggestions = claude_run(stats)

    if not suggestions:
        logger.error("Optimizer analysis failed — no suggestions generated")
        return None

    report = save_report(stats, suggestions)
    telegram_notifier.notify_optimizer_ready()

    logger.info("Optimizer complete ✓")
    return report
