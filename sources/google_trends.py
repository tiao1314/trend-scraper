"""
Google Trends signal.

This is the closest thing to ground truth on "what are people actually
searching for". Two numbers per product:

  momentum  - mean interest over the last 4 weeks vs the prior 12 weeks,
              expressed as a percentage change. This is the signal that
              matters for a reseller: absolute volume tells you what is
              already big, momentum tells you what to buy now.
  level     - mean interest over the last 4 weeks (0-100, relative to the
              term's own peak over the window).

Notes on pytrends: it is an unofficial client for a public endpoint. Google
rate-limits it aggressively, so terms are batched (max 5 per request, a hard
Google limit) with a pause between batches. Expect occasional 429s; the retry
loop handles them.
"""

from __future__ import annotations

import logging
import time

log = logging.getLogger(__name__)

BATCH_SIZE = 5          # Google's hard limit per comparison request
PAUSE_BETWEEN = 8.0     # seconds; lower than this and you will get 429s


def collect(terms: list[str], geo: str = "", timeframe: str = "today 12-m",
            max_retries: int = 3) -> dict[str, dict]:
    """
    Return {term: {"level": float, "momentum": float}}.

    geo: "" for worldwide, or an ISO country code such as "IE", "GB", "US".
    """
    try:
        from pytrends.request import TrendReq
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "pytrends is not installed. Run: pip install pytrends"
        ) from exc

    pytrends = TrendReq(hl="en-US", tz=0)
    results: dict[str, dict] = {}

    for i in range(0, len(terms), BATCH_SIZE):
        batch = terms[i:i + BATCH_SIZE]
        frame = None

        for attempt in range(1, max_retries + 1):
            try:
                pytrends.build_payload(batch, timeframe=timeframe, geo=geo)
                frame = pytrends.interest_over_time()
                break
            except Exception as exc:
                wait = PAUSE_BETWEEN * attempt
                log.warning("trends batch failed (%d/%d): %s - waiting %.0fs",
                            attempt, max_retries, exc, wait)
                time.sleep(wait)

        if frame is None or frame.empty:
            log.warning("no trends data for batch: %s", batch)
            for term in batch:
                results[term] = {"level": 0.0, "momentum": 0.0}
            continue

        if "isPartial" in frame.columns:
            frame = frame.drop(columns=["isPartial"])

        for term in batch:
            if term not in frame.columns:
                results[term] = {"level": 0.0, "momentum": 0.0}
                continue

            series = frame[term]
            recent = series.tail(4)
            baseline = series.tail(16).head(12)

            level = float(recent.mean()) if len(recent) else 0.0
            base_mean = float(baseline.mean()) if len(baseline) else 0.0
            momentum = ((level - base_mean) / base_mean * 100.0) if base_mean > 0 else 0.0

            results[term] = {"level": round(level, 1), "momentum": round(momentum, 1)}
            log.info("trends %-45s level=%5.1f momentum=%+7.1f%%", term, level, momentum)

        time.sleep(PAUSE_BETWEEN)

    return results


def rising_queries(seed: str, geo: str = "") -> list[str]:
    """
    Related queries marked 'rising' for a seed term. Useful for discovering
    model names you are not tracking yet - e.g. seed "Coach bag" and see which
    specific model is climbing.
    """
    from pytrends.request import TrendReq

    pytrends = TrendReq(hl="en-US", tz=0)
    pytrends.build_payload([seed], timeframe="today 3-m", geo=geo)
    related = pytrends.related_queries().get(seed, {})
    rising = related.get("rising")
    if rising is None or rising.empty:
        return []
    return rising["query"].tolist()
