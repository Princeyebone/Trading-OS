# Trading OS v2 Backend

This is the core engine for the Trading OS. 

## Architecture

The backend operates on a strict schedule driven by `APScheduler` in `engine/scheduler.py`.

It utilizes a robust **Deterministic Rule Engine** running zero-latency mathematical and structural algorithms to make trading decisions, completely bypassing the unpredictable latency and hallucinations of LLMs.

### Core Pipelines
- **Data Layer:** Fetches OHLCV data from MT5 or Yahoo Finance across multiple timeframes (M1, M5, M15, H1, H4, D1).
- **Indicator Engine:** Computes EMAs, VWAP, RSI, MACD, and ATR metrics in real-time.
- **Pattern Detector:** Scans for Smart Money Concepts (SMC) like Order Blocks, Fair Value Gaps, and Liquidity Pools.
- **Pre-flight & Risk Guard:** Prevents trades during news blackout periods, low-volatility zones, out-of-session hours, or if maximum drawdown limits are reached.
- **Execution Manager:** Routes signals directly to MT5, handles step-trailing stops, and ratchets take-profit orders as trades move into profit.

### Active Strategies
The scheduler concurrently runs multiple autonomous implementations:

1. **Momentum Runners (M1, M5, M15)**: Follows short-term intraday order flow.
2. **Gold Implementation 2 (GI2)**: Bespoke Gold strategies including the 2-Candle Pullback, Asian Short, and Pre-London Long.
3. **Gold Implementation 3 (GI3)**: Statistical mean-reversion via VWAP Reversion and RSI Divergence.
4. **EUSDI1 (EURUSD)**: Daily Range Breakout targeting previous day's high/low sweeps.
5. **XAGI1/XAGI2 (Silver)**: MACD and EMA trend riders (currently monitored/toggled based on macro volatility).
6. **Scalping Engine**: Tick-level executions exploiting micro-inefficiencies within the spread.

## Execution
To run the primary scheduler loop:
```bash
uv run python -m engine.scheduler
```

For safe logging without real money execution:
```bash
uv run python -m engine.scheduler --dry-run
```

To run a single cycle explicitly:
```bash
uv run python -m engine.scheduler --once
```
