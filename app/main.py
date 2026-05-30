"""
Trading OS v2 — FastAPI Application Entry Point
"""
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

from app.database import create_db_and_tables
from app.routers import trades, signals, performance, optimizer, prompts, config
from app.models import (  # noqa: F401 — import all models so SQLModel registers them
    Signal, MarketContext, PatternEvent, ClaudeResponse,
    Trade, TradeOutcome, TradeJournal,
    Improvement, PromptVersion, PerformanceStat,
    EngineConfig,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create DB tables on startup (idempotent — safe to run every time)."""
    create_db_and_tables()
    # Seed default engine config if none exists
    _seed_defaults()
    yield


def _seed_defaults():
    """Ensure at least one active EngineConfig and one PromptVersion exist."""
    from sqlmodel import Session, select
    from app.database import engine
    from app.models.config import EngineConfig
    from app.models.optimizer import PromptVersion

    with Session(engine) as session:
        # Default config
        existing_config = session.exec(
            select(EngineConfig).where(EngineConfig.is_active == True)
        ).first()
        if not existing_config:
            session.add(EngineConfig())
            session.commit()

        # Default prompt v1
        existing_prompt = session.exec(select(PromptVersion)).first()
        if not existing_prompt:
            default_system = """You are a professional XAU/USD quantitative trader. You analyse market data across five dimensions: trend structure, price action patterns, momentum indicators, macro sentiment, and risk assessment.

You MUST follow these rules unconditionally:
1. Return ONLY valid JSON — no prose, no markdown, no explanation outside the JSON.
2. If you cannot reach 70% confidence, return WAIT unconditionally.
3. Every dimension must cite specific numeric evidence from the data provided.
4. Do NOT recommend LONG if H4 EMA alignment is bearish, even if M15 pattern looks strong.
5. Do NOT recommend TRADE if ATR is in the bottom 20th percentile (ranging conditions).
6. List all warning_flags honestly — a TRADE verdict with flags is acceptable; hidden flags are not.
7. WAIT is always the correct answer when evidence is mixed or marginal."""

            default_template = """MARKET DATA — XAU/USD — {timestamp} — {session} session
Current Price: {price} | ATR(14): {atr} | ATR Percentile: {atr_pct}

INDICATOR STATE:
  H4 — EMA20: {h4_ema20} | EMA50: {h4_ema50} | EMA200: {h4_ema200} | Alignment: {h4_alignment}
  H1 — EMA20: {h1_ema20} | RSI: {h1_rsi} | MACD hist: {h1_macd}
  M15 — RSI: {m15_rsi} | Stoch: {m15_stoch} | Volume vs MA: {vol_ratio}

PATTERNS DETECTED: {patterns_json}
LIQUIDITY LEVELS: {liquidity_json}
MACRO CONTEXT: {macro_context}
ACCOUNT STATE: Balance: {balance} | Open trades: {open_trades} | Daily trades: {daily_trades}

Analyse all five dimensions. Return JSON with keys:
verdict, direction, confidence, entry, stop_loss, tp1, tp2, lot_size, rr_ratio,
trend_analysis, pattern_analysis, momentum_analysis, sentiment_analysis, risk_analysis,
reasoning, warning_flags"""

            session.add(PromptVersion(
                version=1,
                system_prompt=default_system,
                user_template=default_template,
                is_active=True,
                notes="Initial default prompt — Trading OS v2",
            ))
            session.commit()


app = FastAPI(
    title="Trading OS v2 API",
    description="REST API for the Trading OS Journal, Optimizer, and Engine configuration",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS — allow React dev server
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL, "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register all routers
app.include_router(trades.router)
app.include_router(signals.router)
app.include_router(performance.router)
app.include_router(optimizer.router)
app.include_router(prompts.router)
app.include_router(config.router)


@app.get("/")
def root():
    return {
        "name": "Trading OS v2 API",
        "version": "2.0.0",
        "docs": "/docs",
        "status": "running",
    }


@app.get("/health")
def health():
    from app.database import check_db_connection
    db_ok = check_db_connection()
    return {
        "api": "ok",
        "database": "ok" if db_ok else "error",
    }
