"""
engine/telegram_notifier.py — Send trade execution and outcome alerts via Telegram.

Set TELEGRAM_STUB_MODE=true to skip sending (useful for testing).
"""
import logging
import os
import asyncio
from app.settings import settings

logger = logging.getLogger(__name__)

BOT_TOKEN = settings.telegram_bot_token
CHAT_ID   = settings.telegram_chat_id
STUB_MODE = settings.telegram_stub_mode


def _send(message: str):
    """Send a Telegram message synchronously."""
    if STUB_MODE or not BOT_TOKEN or not CHAT_ID:
        safe_msg = message.encode('ascii', 'ignore').decode('ascii')
        logger.info(f"[TELEGRAM STUB] {safe_msg[:100]}...")
        return
    try:
        from engine.db import get_session
        from app.models.config import EngineConfig
        from sqlmodel import select
        
        session = get_session()
        config = session.exec(select(EngineConfig).order_by(EngineConfig.id.desc())).first()
        session.close()
        
        if config and not config.telegram_enabled:
            logger.info("Telegram notification skipped (Disabled in frontend settings).")
            return
    except Exception as e:
        logger.warning(f"Could not check DB config for telegram_enabled: {e}")
    try:
        import requests
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }
        # Use a short timeout so it doesn't block the engine thread if Telegram is down
        response = requests.post(url, json=payload, timeout=5)
        if response.status_code != 200:
            logger.error(f"Telegram API Error: {response.status_code} - {response.text}")
    except Exception as e:
        logger.error(f"Telegram send error: {e}")


def notify_trade_executed(
    direction: str,
    entry: float,
    stop_loss: float,
    tp1: float,
    tp2: float,
    lot_size: float,
    confidence: int,
    order_id: str,
    reasoning: str = "",
):
    msg = (
        f"🟢 <b>TRADE EXECUTED — XAU/USD</b>\n"
        f"{'🔼 LONG' if direction == 'LONG' else '🔽 SHORT'} | {lot_size} lots\n\n"
        f"📍 Entry:      <b>{entry}</b>\n"
        f"🛑 Stop Loss:  <b>{stop_loss}</b>\n"
        f"🎯 TP1:        <b>{tp1}</b>\n"
        f"🎯 TP2:        <b>{tp2 or 'N/A'}</b>\n\n"
        f"🤖 Confidence: <b>{confidence}%</b>\n"
        f"🔖 Order ID:   {order_id}\n\n"
        f"💡 {reasoning[:200] if reasoning else 'See journal for full analysis'}"
    )
    _send(msg)


def notify_trade_outcome(
    direction: str,
    entry: float,
    exit_price: float,
    result: str,          # WIN, LOSS, BE
    pnl_dollars: float,
    r_achieved: float,
    exit_reason: str,
    duration_mins: int,
):
    emoji = "✅" if result == "WIN" else ("❌" if result == "LOSS" else "⚖️")
    pnl_sign = "+" if pnl_dollars >= 0 else ""
    msg = (
        f"{emoji} <b>TRADE CLOSED — {result}</b>\n"
        f"{'🔼 LONG' if direction == 'LONG' else '🔽 SHORT'} XAU/USD\n\n"
        f"📍 Entry:    {entry} → {exit_price}\n"
        f"💰 P&L:     <b>{pnl_sign}{pnl_dollars:.2f}</b>\n"
        f"📊 R:       <b>{r_achieved:.2f}R</b>\n"
        f"🔚 Reason:  {exit_reason}\n"
        f"⏱ Duration: {duration_mins} min"
    )
    _send(msg)


def notify_daily_limit():
    _send("⚠️ <b>Daily trade limit reached</b> — Engine paused until midnight EST.")


def notify_consecutive_loss_pause(loss_count: int):
    msg = (
        f"🚨 <b>CONSECUTIVE LOSS PAUSE</b>\n"
        f"{loss_count} consecutive losses detected.\n"
        f"Engine paused for 24 hours. Check journal for patterns."
    )
    _send(msg)


def notify_engine_skip(reason: str):
    logger.info(f"Engine skip: {reason}")
    # Don't spam Telegram on routine skips


def notify_optimizer_ready():
    _send("📊 <b>Weekly Optimizer Report Ready</b> — Open your journal dashboard to review suggestions.")


def notify_error(component: str, error: str):
    msg = f"⚠️ <b>Engine Error [{component}]</b>\n<code>{error[:500]}</code>"
    _send(msg)

def notify_info(title: str, message: str):
    msg = f"ℹ️ <b>{title}</b>\n{message}"
    _send(msg)

def notify_success(title: str, message: str):
    msg = f"🎉 <b>{title}</b>\n{message}"
    _send(msg)
