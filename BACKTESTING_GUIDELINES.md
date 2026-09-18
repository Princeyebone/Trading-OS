# Trading OS v2 - Backtesting & Simulation Guidelines

This document outlines the mandatory rules for backtesting and developing new strategies for the Trading OS engine. The purpose of this guide is to prevent the **"Simulation-to-Live Gap"**—the phenomenon where a strategy performs exceptionally well in historical backtests but loses money in live forward-testing.

## 1. Multi-Timeframe Confluence is Mandatory
An algorithmic setup (e.g., an FVG, OB, or IFVG on the 5-minute chart) must never be traded blindly. The system must always check the higher timeframe (HTF) context.
- **Rule**: If a 5M signal is generated to go LONG, the engine MUST verify that the H1 or H4 trend is BULLISH or that a major sell-side liquidity pool was just swept. 
- **Why?** Setups are triggers; the higher timeframe is the permission. Trading against the HTF trend often leads to getting chopped up by algorithmic volatility.

## 2. Walk-Forward Optimization (Out-of-Sample Testing)
Do not "curve fit" or over-optimize variables (like EMA lengths, stop-loss pip amounts, or strict time windows) on the entire dataset.
- **Rule**: Optimize your strategy on a set period (e.g., January 1st to June 30th). Lock the variables. Then, run a blind test on a completely unseen period (e.g., July 1st to December 31st).
- **Why?** If the strategy fails on the unseen data, it means the algorithm merely memorized the past (overfitting) rather than learning a robust market behavior.

## 3. Strict Slippage and Spread Penalization
Python backtesters typically assume perfect fills at exact prices. Real MT5 execution, particularly on volatile assets like XAU/USD (Gold), suffers from variable spreads and slippage during volume spikes.
- **Rule**: When running historical simulations (`simulate_*.py`), artificially penalize every winning trade by subtracting 2-3 pips from the profit, and add 2-3 pips of loss to every losing trade. 
- **Implementation**: Ensure `broker_executor.py` has a `MAX_SPREAD` guard so trades aren't placed during news spikes or session rollovers when spreads widen massively.

## 4. Market Regime Filtering
Markets transition between Trending, Ranging, and Choppy regimes. A breakout strategy thrives in a trend but is destroyed in a range.
- **Rule**: Implement regime filters (e.g., ADX > 25 for trending, or monitoring Daily ATR) in the strategy files. If the market compresses and volatility drops below a certain threshold, the strategy should automatically reduce lot sizes or halt trading until volume returns.

## 5. Minimum Risk-to-Reward & Trade Limits
- Ensure that the programmed Take Profit (TP) always offers a mathematically sound Risk-to-Reward ratio (ideally > 1:1.5) accounting for slippage.
- Respect the `MAX_OPEN_TRADES` limit to avoid overexposure to a single sudden market movement.

*By adhering to these guidelines, any strategy that looks profitable in backtesting will have a high mathematical probability of mirroring that profitability in live markets.*
