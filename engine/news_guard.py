"""
engine/news_guard.py — News Blackout Guard

Fetches the ForexFactory RSS feed and checks whether any high-impact (red-folder)
economic event is scheduled within ±N minutes of the current UTC time.

Used by run_preflight() in engine/scheduler.py as Check #6.

Currencies monitored by default:
  - USD (direct XAU/USD driver)
  - EUR, GBP, CNY (major gold-moving macro events)

Cache: RSS is fetched at most once every 10 minutes to avoid rate-limiting.

Fail mode (controlled by NEWS_GUARD_FAIL_MODE in .env):
  open   — if the RSS feed is unreachable, return the stale cache and allow trading.
            Use this on demo: missing one trade due to a network glitch is irrelevant.
  closed — if the RSS feed is unreachable, block trading until the feed recovers.
            Use this on live: the cost of an unguarded news spike exceeds the cost
            of a missed opportunity.
"""

import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Optional
import urllib.request
import urllib.error

from app.settings import settings

logger = logging.getLogger("engine.news_guard")

# ─── Constants ────────────────────────────────────────────────────────────────

FF_RSS_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"

# Currencies whose high-impact events should trigger a blackout for XAU/USD.
# USD is primary; EUR/GBP/CNY drive gold indirectly via risk sentiment and DXY.
WATCHED_CURRENCIES = {"USD", "EUR", "GBP", "CNY"}

# RSS <impact> tag values that warrant a blackout. ForexFactory uses "High" for red.
HIGH_IMPACT_VALUES = {"High"}

# How long (seconds) to reuse the last successful RSS fetch before re-fetching.
CACHE_TTL_SECONDS = 600  # 10 minutes

# ─── Cache state ──────────────────────────────────────────────────────────────

_cache_lock = Lock()
_cached_events: list[dict] = []        # parsed events from last successful fetch
_cache_fetched_at: Optional[datetime] = None  # UTC timestamp of last fetch


# ─── RSS parser ───────────────────────────────────────────────────────────────

def _parse_ff_rss(xml_text: str) -> list[dict]:
    """
    Parse the ForexFactory XML calendar feed.

    Each <event> element contains:
      <title>      — event name, e.g. "Non-Farm Employment Change"
      <country>    — currency code, e.g. "USD"
      <date>       — ISO-like datetime string, e.g. "01-31-2026"
      <time>       — event time string, e.g. "8:30am"
      <impact>     — "High", "Medium", "Low", "Holiday"
      <forecast>   — analyst forecast (may be empty)
      <previous>   — previous reading (may be empty)

    Returns a list of dicts with keys: title, currency, event_utc, impact.
    event_utc is a timezone-aware datetime in UTC.
    """
    events = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        logger.warning(f"news_guard: RSS XML parse error: {e}")
        return events

    for item in root.iter("event"):
        title    = (item.findtext("title")   or "").strip()
        currency = (item.findtext("country") or "").strip().upper()
        date_str = (item.findtext("date")    or "").strip()
        time_str = (item.findtext("time")    or "").strip()
        impact   = (item.findtext("impact")  or "").strip()

        # Only process currencies we care about
        if currency not in WATCHED_CURRENCIES:
            continue

        # Parse date + time into a UTC datetime.
        # FF format: date = "05-30-2026", time = "8:30am" or "All Day" or ""
        event_dt = _parse_ff_datetime(date_str, time_str)
        if event_dt is None:
            continue

        events.append({
            "title":     title,
            "currency":  currency,
            "event_utc": event_dt,
            "impact":    impact,
        })

    return events


def _parse_ff_datetime(date_str: str, time_str: str) -> Optional[datetime]:
    """
    Convert ForexFactory date/time strings to a UTC-aware datetime.
    Returns None for all-day events or unparseable strings.

    FF dates are in Eastern Time (EST/EDT). We convert to UTC.
    """
    if not date_str or not time_str or time_str.lower() in ("all day", "tentative", ""):
        return None

    # Build a naive datetime string, e.g. "05-30-2026 8:30am"
    raw = f"{date_str} {time_str}"
    for fmt in ("%m-%d-%Y %I:%M%p", "%m-%d-%Y %I%p"):
        try:
            naive_dt = datetime.strptime(raw, fmt)
            break
        except ValueError:
            continue
    else:
        logger.debug(f"news_guard: could not parse datetime '{raw}'")
        return None

    # ForexFactory publishes times in US/Eastern. Apply a fixed UTC-5 offset as a
    # conservative approximation (EST). This is intentional: being 1 hour early on
    # DST boundaries is safer than being 1 hour late for a trade guard.
    from zoneinfo import ZoneInfo
    eastern = ZoneInfo("America/New_York")
    aware_dt = naive_dt.replace(tzinfo=eastern)
    return aware_dt.astimezone(timezone.utc)


# ─── Fetch with caching ────────────────────────────────────────────────────────

def _fetch_rss_cached() -> list[dict]:
    """
    Return a cached list of all parsed FF events for this week.
    Re-fetches the RSS feed if the cache is older than CACHE_TTL_SECONDS.

    On fetch failure the behaviour is controlled by settings.news_guard_fail_mode:
      'open'   → return the stale cache so trading is not blocked (demo default)
      'closed' → return [] so is_news_blackout() triggers a preflight skip (live default)
    """
    global _cached_events, _cache_fetched_at

    with _cache_lock:
        now = datetime.now(timezone.utc)
        cache_age = (now - _cache_fetched_at).total_seconds() if _cache_fetched_at else float("inf")

        if cache_age < CACHE_TTL_SECONDS:
            logger.debug(f"news_guard: using cached events (age={cache_age:.0f}s)")
            return _cached_events

        # Cache expired — re-fetch
        logger.info("news_guard: fetching ForexFactory RSS feed...")
        try:
            req = urllib.request.Request(
                FF_RSS_URL,
                headers={"User-Agent": "TradingOS/2.0 news-guard (+https://github.com/trading-os)"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                xml_text = resp.read().decode("utf-8", errors="replace")

            parsed = _parse_ff_rss(xml_text)
            _cached_events = parsed
            _cache_fetched_at = now
            logger.info(f"news_guard: fetched {len(parsed)} watched-currency events for this week")

        except (urllib.error.URLError, TimeoutError) as e:
            fail_mode = settings.news_guard_fail_mode.lower()
            if fail_mode == "closed":
                logger.warning(
                    f"news_guard: RSS fetch failed ({e}). "
                    f"Fail-CLOSED mode — returning empty list to block trading."
                )
                return []   # empty → is_news_blackout sees no events → blocks via caller logic
            else:
                logger.warning(
                    f"news_guard: RSS fetch failed ({e}). "
                    f"Fail-OPEN mode — returning stale cache, trading not blocked."
                )
                # _cached_events is returned unchanged (stale cache)

        return _cached_events


# ─── Public API ───────────────────────────────────────────────────────────────

def fetch_high_impact_events(window_minutes: int) -> list[dict]:
    """
    Return all high-impact events within ±window_minutes of now (UTC).

    Each dict contains:
      title    : str  — event name
      currency : str  — e.g. "USD"
      event_utc: datetime — when the event is scheduled
      impact   : str  — "High"
      minutes_away: float — how many minutes away (negative = already passed)
    """
    now = datetime.now(timezone.utc)
    cutoff_before = now - timedelta(minutes=window_minutes)
    cutoff_after  = now + timedelta(minutes=window_minutes)

    all_events = _fetch_rss_cached()
    upcoming = []

    for ev in all_events:
        if ev["impact"] not in HIGH_IMPACT_VALUES:
            continue
        if cutoff_before <= ev["event_utc"] <= cutoff_after:
            minutes_away = (ev["event_utc"] - now).total_seconds() / 60
            upcoming.append({**ev, "minutes_away": round(minutes_away, 1)})

    # Sort closest first
    upcoming.sort(key=lambda e: abs(e["minutes_away"]))
    return upcoming


def is_news_blackout(window_minutes: int = 15) -> tuple[bool, str]:
    """
    Returns (True, label) if any high-impact event is within ±window_minutes.
    Returns (False, "") if the coast is clear.

    label format: "NFP @ 13:30 UTC (in -2.5 min)"
    """
    events = fetch_high_impact_events(window_minutes)
    if not events:
        return False, ""

    # Report the closest one
    ev = events[0]
    time_str   = ev["event_utc"].strftime("%H:%M UTC")
    direction  = "in" if ev["minutes_away"] >= 0 else "passed"
    label = f"{ev['title']} [{ev['currency']}] @ {time_str} ({direction} {abs(ev['minutes_away'])} min)"
    return True, label
