"""
engine/claude_analyst.py — Claude API integration for trade analysis.

Builds the structured prompt, calls Claude, parses the JSON response.
Stores raw response to claude_responses table for full audit trail.
"""
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional
import anthropic
from sqlmodel import Session, select

from engine.db import get_session
from app.models.signals import ClaudeResponse
from app.models.optimizer import PromptVersion
from app.settings import settings

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = settings.anthropic_api_key
DEFAULT_MODEL = "claude-haiku-4-5"

_client: Optional[anthropic.Anthropic] = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def _get_active_prompt(session: Session) -> Optional[PromptVersion]:
    """Fetch the currently active prompt version from DB."""
    return session.exec(
        select(PromptVersion).where(PromptVersion.is_active == True)
    ).first()


def build_prompt(
    indicator_snapshot: dict,
    patterns: dict,
    session_name: str,
    account_state: dict,
    macro_context: str = "No major news events in the next 15 minutes.",
) -> tuple[str, str]:
    """
    Build system + user prompt strings from the active template.
    Returns (system_prompt, user_prompt).
    """
    db_session = get_session()
    active_prompt = _get_active_prompt(db_session)
    db_session.close()

    if not active_prompt:
        raise RuntimeError("No active prompt version found. Seed the database first.")

    snap = indicator_snapshot
    user_prompt = active_prompt.user_template.format(
        timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        session=session_name,
        price=snap.get("m15_close", "N/A"),
        atr=snap.get("m15_atr", "N/A"),
        atr_pct=snap.get("atr_percentile", "N/A"),
        h4_ema20=snap.get("h4_ema_20", "N/A"),
        h4_ema50=snap.get("h4_ema_50", "N/A"),
        h4_ema200=snap.get("h4_ema_200", "N/A"),
        h4_alignment=snap.get("h4_alignment", "N/A"),
        h1_ema20=snap.get("h1_ema_20", "N/A"),
        h1_rsi=snap.get("h1_rsi", "N/A"),
        h1_macd=snap.get("h1_macd_hist", "N/A"),
        m15_rsi=snap.get("m15_rsi", "N/A"),
        m15_stoch=snap.get("m15_stoch_k", "N/A"),
        vol_ratio=snap.get("m15_vol_ratio", "N/A"),
        patterns_json=json.dumps(patterns.get("patterns", []), indent=2),
        liquidity_json=json.dumps(patterns.get("liquidity", []), indent=2),
        macro_context=macro_context,
        balance=account_state.get("balance", 500),
        open_trades=account_state.get("open_trades", 0),
        daily_trades=account_state.get("daily_trades", 0),
    )

    return active_prompt.system_prompt, user_prompt, active_prompt.version


def call_claude(
    system_prompt: str,
    user_prompt: str,
    prompt_version: int,
    signal_id: Optional[int] = None,
    model: str = DEFAULT_MODEL,
) -> dict:
    """
    Call Claude API and return parsed response dict.
    Stores raw response to DB for audit trail.
    """
    if not ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY not set — returning mock WAIT response")
        return _mock_wait_response()

    client = _get_client()
    start_ms = int(time.time() * 1000)

    try:
        message = client.messages.create(
            model=model,
            max_tokens=1024,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        latency_ms = int(time.time() * 1000) - start_ms
        raw_text = message.content[0].text
        input_tokens = message.usage.input_tokens
        output_tokens = message.usage.output_tokens

    except anthropic.APIError as e:
        logger.error(f"Claude API error: {e}")
        return _mock_wait_response(reason=f"API error: {e}")

    # Parse JSON from response
    parsed = _parse_response(raw_text)

    # Store to DB
    # Prepend strategy_name to reasoning so it gets saved without schema changes
    strategy = parsed.get("strategy_name", "NONE")
    original_reasoning = parsed.get("reasoning", "")
    parsed["reasoning"] = f"[Strategy: {strategy}] {original_reasoning}"

    _store_response(
        signal_id=signal_id,
        prompt_version=prompt_version,
        model=model,
        raw_text=raw_text,
        parsed=parsed,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=latency_ms,
    )

    return parsed


def _parse_response(raw_text: str) -> dict:
    """Extract JSON from Claude's response text."""
    try:
        # Claude should return pure JSON, but strip markdown code fences if present
        text = raw_text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1])
        return json.loads(text)
    except (json.JSONDecodeError, ValueError) as e:
        logger.error(f"Failed to parse Claude JSON: {e}\nRaw: {raw_text[:500]}")
        return _mock_wait_response(reason="JSON parse error")


def _store_response(
    signal_id, prompt_version, model, raw_text, parsed, input_tokens, output_tokens, latency_ms
):
    """Save Claude response to DB."""
    try:
        db_session = get_session()
        response = ClaudeResponse(
            signal_id=signal_id,
            prompt_version=prompt_version,
            model_used=model,
            raw_response=raw_text,
            parsed_verdict=parsed.get("verdict"),
            parsed_confidence=parsed.get("confidence"),
            parsed_direction=parsed.get("direction"),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
        )
        db_session.add(response)
        db_session.commit()
        db_session.refresh(response)
        db_session.close()
        return response.id
    except Exception as e:
        logger.error(f"Failed to store Claude response: {e}")
        return None


def _mock_wait_response(reason: str = "Stub mode") -> dict:
    """Return a safe WAIT response when API is unavailable."""
    return {
        "verdict": "WAIT",
        "direction": None,
        "confidence": 0,
        "entry": None,
        "stop_loss": None,
        "tp1": None,
        "tp2": None,
        "lot_size": None,
        "rr_ratio": None,
        "trend_analysis": "N/A",
        "pattern_analysis": "N/A",
        "momentum_analysis": "N/A",
        "sentiment_analysis": "N/A",
        "risk_analysis": "N/A",
        "strategy_name": "NONE",
        "reasoning": reason,
        "warning_flags": ["STUB_MODE"],
    }


def analyse_market(
    indicator_snapshot: dict,
    patterns: dict,
    session_name: str,
    account_state: dict,
) -> dict:
    """
    Full analysis pipeline: build prompt → call Claude → return parsed verdict.
    This is the single function the scheduler calls.
    """
    try:
        system_prompt, user_prompt, prompt_version = build_prompt(
            indicator_snapshot, patterns, session_name, account_state
        )
        return call_claude(system_prompt, user_prompt, prompt_version)
    except Exception as e:
        logger.error(f"analyse_market failed: {e}")
        return _mock_wait_response(reason=str(e))
