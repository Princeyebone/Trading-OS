import sys
import os
import logging
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set up logging for stdout
logging.basicConfig(level=logging.INFO, stream=sys.stdout)

# Mock fetch_high_impact_events
from engine import news_engine_runner

def mock_fetch(window_minutes):
    return [
        {
            "title": "US NFP (MOCK)",
            "currency": "USD",
            "event_utc": datetime.now(timezone.utc),
            "impact": "High",
            "minutes_away": 1.0 # 1 minute away -> Should trigger Straddle
        },
        {
            "title": "US CPI (MOCK)",
            "currency": "USD",
            "event_utc": datetime.now(timezone.utc),
            "impact": "High",
            "minutes_away": -10.0 # 10 minutes passed -> Should trigger Fade
        }
    ]

# Override the function
news_engine_runner.fetch_high_impact_events = mock_fetch

# Run the cycle
print("Running News Engine Cycle (Mocking NFP 1 min away, CPI 10 mins ago)...")
news_engine_runner.run_news_engine_cycle()
print("Cycle Complete.")
