"""
optimizer/qwen_optimizer.py — Build optimizer prompt and call Qwen.

Generates 3 ranked improvement suggestions from the weekly stats.
"""
import json
import logging
import time
from typing import Optional

import openai

from app.settings import settings

logger = logging.getLogger(__name__)

QWEN_API_KEY = settings.qwen_api_key
DASHSCOPE_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
OPTIMIZER_MODEL = "qwen-max"  # Use a stronger model for optimizer

OPTIMIZER_SYSTEM = """You are an expert trading system analyst reviewing weekly performance data for an XAU/USD (Gold) AI trading system.

Your job is to:
1. Identify the TOP 3 most impactful improvements, ranked by expected accuracy improvement.
2. Every suggestion MUST be backed by specific numeric evidence from the data.
3. Be specific — vague suggestions like "improve entries" are NOT acceptable.
4. Focus on changes that can be implemented in the trading engine's rules or parameters.

Return ONLY valid JSON with this exact structure:
{
  "suggestions": [
    {
      "rank": 1,
      "impact": "HIGH",
      "finding": "Specific data finding with numbers",
      "recommendation": "Specific, actionable change with exact parameter values",
      "expected_impact": "Quantified expected improvement",
      "verify_by": "How to verify this worked after 1 week"
    },
    ... (2 more suggestions)
  ]
}
impact must be: "HIGH", "MEDIUM", or "LOW"
"""


def build_optimizer_prompt(stats: dict) -> str:
    """Build the user prompt from aggregated stats."""
    return f"""WEEKLY PERFORMANCE REPORT — XAU/USD TRADING SYSTEM
Period: {stats['period_start']} to {stats['period_end']}

OVERVIEW:
  Total Signals: {stats['total_signals']} | TRADE: {stats['trade_signals']} | WAIT: {stats['wait_signals']}
  Trades Taken: {stats['total_trades']} | Wins: {stats['wins']} | Losses: {stats['losses']}
  Win Rate: {stats['win_rate']}% | Average R: {stats['avg_r_achieved']}R

BY SESSION:
{json.dumps(stats['by_session'], indent=2)}

BY PATTERN TYPE:
{json.dumps(stats['by_pattern'], indent=2)}

CONFIDENCE CALIBRATION (confidence % → actual win rate):
{json.dumps(stats['confidence_calibration'], indent=2)}

RSI ANALYSIS:
  Average RSI at entry (winners): {stats['rsi_analysis']['avg_rsi_at_entry_winners']}
  Average RSI at entry (losers):  {stats['rsi_analysis']['avg_rsi_at_entry_losers']}
  Differential: {stats['rsi_analysis']['rsi_differential']}

TP ACHIEVEMENT:
  TP1 hit rate: {stats['tp_achievement']['tp1_rate']}% of winners
  TP2 hit rate: {stats['tp_achievement']['tp2_rate']}% of winners

JOURNAL IMPROVEMENT HINTS (from post-trade AI analysis):
{json.dumps(stats['journal_hints'], indent=2)}

COMMON FAILURE PATTERNS:
{json.dumps(stats['common_failure_patterns'], indent=2)}

Based on this data, provide your top 3 ranked improvement suggestions."""


def run_optimizer_analysis(stats: dict) -> Optional[dict]:
    """Call Qwen with optimizer prompt. Returns parsed suggestions or None."""
    if not QWEN_API_KEY:
        logger.warning("QWEN_API_KEY not set — returning mock optimizer response")
        return _mock_suggestions(stats)

    client = openai.OpenAI(
        api_key=QWEN_API_KEY,
        base_url=DASHSCOPE_BASE_URL,
    )
    user_prompt = build_optimizer_prompt(stats)

    try:
        start = time.time()
        completion = client.chat.completions.create(
            model=OPTIMIZER_MODEL,
            messages=[
                {"role": "system", "content": OPTIMIZER_SYSTEM},
                {"role": "user", "content": user_prompt}
            ],
        )
        latency = round(time.time() - start, 1)
        raw_text = completion.choices[0].message.content
        output_tokens = completion.usage.completion_tokens if completion.usage else 0
        logger.info(f"Optimizer Qwen call: {latency}s | {output_tokens} tokens")

        # Parse JSON
        text = raw_text.strip()
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
            
        if text.endswith("```"):
            text = text[:-3]
            
        text = text.strip()
        return json.loads(text)

    except Exception as e:
        logger.error(f"Optimizer Qwen error: {e}")
        return None


def _mock_suggestions(stats: dict) -> dict:
    """Return mock suggestions when API key not available."""
    return {
        "suggestions": [
            {
                "rank": 1,
                "impact": "HIGH",
                "finding": f"Win rate is {stats['win_rate']}% this week. Insufficient data for detailed analysis (no API key).",
                "recommendation": "Set QWEN_API_KEY in .env to enable AI-powered suggestions.",
                "expected_impact": "Unlocks full optimizer capability.",
                "verify_by": "Run optimizer again after setting API key.",
            },
            {
                "rank": 2,
                "impact": "MEDIUM",
                "finding": "Demo mode — no real suggestions generated.",
                "recommendation": "Configure Qwen API key.",
                "expected_impact": "N/A",
                "verify_by": "N/A",
            },
            {
                "rank": 3,
                "impact": "LOW",
                "finding": "Continue collecting trade data for meaningful analysis.",
                "recommendation": "Run engine for at least 2 weeks before optimizing.",
                "expected_impact": "Better data → better suggestions.",
                "verify_by": "After 14+ trades, run optimizer again.",
            },
        ]
    }
