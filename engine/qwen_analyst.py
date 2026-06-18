"""
engine/qwen_analyst.py — Qwen API integration for trade analysis.

Builds the structured prompt, calls Alibaba Qwen via OpenAI compatible API,
and parses the JSON response. Stores raw response to claude_responses
(reusing the table for now) for full audit trail.
"""
import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional
import openai
from sqlmodel import Session, select

from engine.db import get_session
from app.models.signals import ClaudeResponse
from app.models.optimizer import PromptVersion
from app.settings import settings

logger = logging.getLogger(__name__)

QWEN_API_KEY = settings.qwen_api_key
DEFAULT_MODEL = "qwen-max"
DASHSCOPE_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"

_client: Optional[openai.OpenAI] = None


def _get_client() -> openai.OpenAI:
    global _client
    if _client is None:
        _client = openai.OpenAI(
            api_key=QWEN_API_KEY,
            base_url=DASHSCOPE_BASE_URL,
            timeout=45.0,
        )
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
    tape_metrics: dict = None,
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
        atr_pct=f"H4: {snap.get('h4_atr_percentile', 'N/A')}% | H1: {snap.get('h1_atr_percentile', 'N/A')}%",
        volatility_regime=snap.get("volatility_regime", "UNKNOWN"),
        regime_constraint=snap.get("regime_constraint", ""),
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
        tape_metrics_json=json.dumps(tape_metrics or {}, indent=2),
    )

    return active_prompt.system_prompt, user_prompt, active_prompt.version


def call_qwen(
    system_prompt: str,
    user_prompt: str,
    prompt_version: int,
    signal_id: Optional[int] = None,
    model: str = DEFAULT_MODEL,
) -> dict:
    """
    Call Qwen API and return parsed response dict.
    Stores raw response to DB for audit trail.
    """
    if not QWEN_API_KEY:
        logger.warning("QWEN_API_KEY not set — returning mock WAIT response")
        return _mock_wait_response()

    client = _get_client()
    start_ms = int(time.time() * 1000)

    try:
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
        )
        latency_ms = int(time.time() * 1000) - start_ms
        raw_text = completion.choices[0].message.content
        
        # Depending on DashScope API version, token usage might be structured slightly differently, 
        # but the standard openai format is supported.
        input_tokens = completion.usage.prompt_tokens if completion.usage else 0
        output_tokens = completion.usage.completion_tokens if completion.usage else 0

    except Exception as e:
        logger.error(f"Qwen API error: {e}")
        return _mock_wait_response(reason=f"API error: {e}")

    # Parse JSON from response
    logger.info(f"Qwen raw response preview: {raw_text[:300] if raw_text else 'EMPTY'}")
    parsed = _parse_response(raw_text)

    # Store to DB (reusing ClaudeResponse table for simplicity, maybe rename later)
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
    """Extract JSON from Qwen's response text."""
    if not raw_text:
        return _mock_wait_response(reason="Empty response")
        
    try:
        # Qwen should return pure JSON, but strip markdown code fences if present
        text = raw_text.strip()
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
            
        if text.endswith("```"):
            text = text[:-3]
            
        text = text.strip()
        return json.loads(text)
    except (json.JSONDecodeError, ValueError) as e:
        logger.error(f"Failed to parse Qwen JSON: {e}\nRaw: {raw_text[:500]}")
        return _mock_wait_response(reason="JSON parse error")


def _store_response(
    signal_id, prompt_version, model, raw_text, parsed, input_tokens, output_tokens, latency_ms
):
    """Save response to DB."""
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
        logger.error(f"Failed to store Qwen response: {e}")
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
    tape_metrics: dict = None,
) -> dict:
    """
    Full analysis pipeline: build prompt → call Qwen → return parsed verdict.
    """
    try:
        system_prompt, user_prompt, prompt_version = build_prompt(
            indicator_snapshot, patterns, session_name, account_state, tape_metrics
        )
        return call_qwen(system_prompt, user_prompt, prompt_version)
    except Exception as e:
        logger.error(f"analyse_market failed: {e}")
        return _mock_wait_response(reason=str(e))
