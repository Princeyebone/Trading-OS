"""
optimizer/weekly_scheduler.py — APScheduler cron for Sunday 18:00 optimizer run.

Also exposes run_optimizer_now() for the FastAPI manual trigger endpoint.

Usage:
    python -m optimizer.weekly_scheduler          # run as standalone process
    python -m optimizer.weekly_scheduler --once   # run one analysis now
"""
import argparse
import logging
import os
import sys

from apscheduler.schedulers.blocking import BlockingScheduler
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger("optimizer.weekly_scheduler")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
)


def run_optimizer_now():
    """Entry point for both scheduled and manual runs."""
    from optimizer.report_generator import run_full_optimizer
    try:
        report = run_full_optimizer()
        if report:
            logger.info(f"Weekly optimizer complete — report ID {report.id}")
        else:
            logger.error("Optimizer run produced no report")
    except Exception as e:
        logger.exception(f"Optimizer run failed: {e}")
        from engine import telegram_notifier
        telegram_notifier.notify_error("Optimizer", str(e))


def main():
    parser = argparse.ArgumentParser(description="Trading OS Weekly Optimizer Scheduler")
    parser.add_argument("--once", action="store_true", help="Run optimizer once now and exit")
    args = parser.parse_args()

    if args.once:
        logger.info("Running optimizer immediately (--once flag)")
        run_optimizer_now()
        return

    scheduler = BlockingScheduler(timezone="America/New_York")
    # Every Sunday at 18:00 EST
    scheduler.add_job(
        run_optimizer_now,
        "cron",
        day_of_week="sun",
        hour=18,
        minute=0,
        id="weekly_optimizer",
    )

    logger.info("📊 Optimizer scheduler started — will run every Sunday at 18:00 EST")
    logger.info("   Press Ctrl+C to stop")

    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Optimizer scheduler stopped")


if __name__ == "__main__":
    main()
