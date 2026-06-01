"""
Trading OS v2 — FastAPI Application Entry Point
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session
from app.settings import settings

from alembic.config import Config
from alembic import command
from app.routers import trades, signals, performance, optimizer, prompts, config, system
from app.models import (  # noqa: F401 — import all models so SQLModel registers them
    Signal, MarketContext, PatternEvent, ClaudeResponse,
    Trade, TradeOutcome, TradeJournal,
    Improvement, PromptVersion, PerformanceStat,
    EngineConfig,
)


from engine.scheduler import start_background_scheduler

_scheduler = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run database migrations on startup using Alembic."""
    global _scheduler
    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")
    # Seed default engine config if none exists
    _seed_defaults()
    
    _scheduler = start_background_scheduler()
    yield
    
    if _scheduler:
        _scheduler.shutdown()


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
            default_system = """You are a professional XAU/USD quantitative trader acting as a strict Strategy Classifier.
Do NOT "guess" if a trade is good. You must classify the market into EXACTLY ONE of the 4 defined strategies below, or output NONE (WAIT).

STRATEGY 1: Liquidity Sweep Reversal (LSR)
- Regime: Consolidation or weak trend.
- Setup: Price swept equal highs/lows (Liquidity). Strong rejection (displacement) back into range. M15 structure shift (BOS).
- Invalid if: Strong H4 trend expansion candle recently, or extremely low ATR with no volatility spike.
- Trigger: Break of minor structure on M15 after sweep.

STRATEGY 2: Trend Continuation Pullback (TCP)
- Regime: Clear H4 EMA alignment (Bullish or Bearish).
- Setup: Pullback into EMA20/50 zone or previous order block. M15 momentum cooling.
- Invalid if: H4 is mixed/flat, or price is in a major liquidity zone.
- Trigger: M15 BOS in direction of trend after pullback rejection.

STRATEGY 3: Displacement + Fair Value Gap Fill (D-FVG)
- Regime: Post-impulse.
- Setup: Strong displacement leaves a Fair Value Gap. Price retraces into FVG zone with weakening momentum.
- Invalid if: Choppy market (no displacement) or FVG mitigated multiple times.
- Trigger: Reaction inside FVG + micro BOS confirmation.

STRATEGY 4: Accumulation Breakout Expansion (ABE)
- Regime: Tight range, low ATR percentile.
- Setup: Clear consolidation box, equal highs/lows compression. Volatility squeeze.
- Invalid if: Already trending strongly, or repeated fakeouts.
- Trigger: Clean breakout + retest or breakout + continuation.

RULES:
1. Return ONLY valid JSON.
2. If the market does not clearly match all REQUIRED conditions for a strategy, or has major invalid conditions, return verdict: "WAIT".
3. Include a JSON key "strategy_name" (e.g., "LSR", "TCP", "D-FVG", "ABE", or "NONE").
4. Entry, SL, TP must be derived strictly from the selected strategy's structure and recent swing levels."""

            default_template = """MARKET DATA — XAU/USD — {timestamp} — {session} session
Current Price: {price} | ATR(14): {atr} | ATR Percentile: {atr_pct}

INDICATOR STATE:
  H4 — EMA20: {h4_ema20} | EMA50: {h4_ema50} | EMA200: {h4_ema200} | Alignment: {h4_alignment}
  H1 — EMA20: {h1_ema20} | RSI: {h1_rsi} | MACD hist: {h1_macd}
  M15 — RSI: {m15_rsi} | Stoch: {m15_stoch} | Volume vs MA: {vol_ratio}

PATTERNS DETECTED: {patterns_json}
LIQUIDITY LEVELS: {liquidity_json}

Analyse the data and map it against the 4 allowed strategies.
Return JSON with keys:
verdict (TRADE/WAIT), strategy_name (LSR/TCP/D-FVG/ABE/NONE), direction, confidence, entry, stop_loss, tp1, tp2, lot_size, rr_ratio, reasoning, warning_flags"""

            session.add(PromptVersion(
                version=2,
                system_prompt=default_system,
                user_template=default_template,
                is_active=True,
                notes="V2 Strategy Classifier (LSR, TCP, D-FVG, ABE)",
            ))
            session.commit()


app = FastAPI(
    title="Trading OS v2 API",
    description="REST API for the Trading OS Journal, Optimizer, and Engine configuration",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS — allow React dev server
FRONTEND_URL = settings.frontend_url
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL, "http://localhost:5173", "http://127.0.0.1:5173"],
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
app.include_router(system.router)

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
