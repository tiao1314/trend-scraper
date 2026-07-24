"""
Auto-discovery of new trending products.

The watchlist is a fixed buy-list. This module grows it automatically: for each
seed category it asks Google Trends for the 'rising' related queries (the same
signal behind `run.py --discover`), cleans them up, throws away anything you
already track or that is obviously noise, and returns new watchlist rows.

Seeds are gendered on purpose. Google Trends 'related queries' are personalised
to the seed phrase, so "designer handbag" surfaces women's models and
"mens designer bag" surfaces men's - if you only seed women's phrases you only
ever discover women's products, which is exactly what happened to this list.

Nothing here needs API keys. pytrends hits a public endpoint (rate-limited, so
seeds are paced out). On any failure it degrades to "no new rows" rather than
crashing a live run.
"""

from __future__ import annotations

import logging
import re
import time

log = logging.getLogger(__name__)

PAUSE_BETWEEN = 8.0  # seconds between seeds - pytrends 429s below this

# (seed phrase, gender, category, tier) - gender: W women, M men, U unisex.
# Add or remove seeds freely; this is the only place discovery scope is defined.
SEEDS: list[tuple[str, str, str, str]] = [
    # --- women (broadens the existing list) ---
    ("designer handbag", "W", "Bag", "Luxury"),
    ("luxury tote bag", "W", "Bag", "Luxury"),
    ("designer heels", "W", "Shoes", "Luxury"),
    ("ballet flats designer", "W", "Shoes", "Luxury"),
    # --- men (new coverage) ---
    ("mens designer bag", "M", "Bag", "Luxury"),
    ("mens luxury sneakers", "M", "Shoes", "Luxury"),
    ("mens designer loafers", "M", "Shoes", "Luxury"),
    ("mens leather sneakers", "M", "Shoes", "Contemporary"),
    ("mens designer belt", "M", "Accessory", "Luxury"),
    ("mens luxury watch", "M", "Accessory", "Ultra-luxury"),
    ("mens crossbody bag designer", "M", "Bag", "Luxury"),
    # --- unisex ---
    ("designer sunglasses", "U", "Accessory", "Luxury"),
]

# Rising queries that are searches-about-buying rather than products.
_NOISE = re.compile(
    r"\b(cheap|replica|dupe|fake|used|sale|outlet|amazon|ebay|vinted|"
    r"price|near me|store|shop|website|reddit|review|worth it)\b",
    re.IGNORECASE,
)


def _clean(query: str) -> str:
    query = re.sub(r"\s+", " ", query).strip()
    return query.title() if query.islower() else query


def expand(existing_terms: list[str], geo: str = "",
           per_seed: int = 5, seeds: list | None = None) -> list[dict]:
    """
    Return new watchlist rows discovered from trends, deduped against
    existing_terms. Each row: {search_term, category, brand, model, tier, gender}.
    """
    try:
        from sources import google_trends
    except ImportError:  # pragma: no cover
        return []

    seeds = seeds if seeds is not None else SEEDS
    seen = {t.strip().lower() for t in existing_terms}
    new_rows: list[dict] = []

    for i, (seed, gender, category, tier) in enumerate(seeds):
        try:
            rising = google_trends.rising_queries(seed, geo=geo)
        except Exception as exc:
            log.warning("discover seed '%s' failed: %s", seed, exc)
            rising = []

        kept = 0
        for raw in rising:
            if kept >= per_seed:
                break
            term = _clean(str(raw))
            key = term.lower()
            if not term or key in seen or _NOISE.search(term):
                continue
            seen.add(key)
            new_rows.append({
                "search_term": term,
                "category": category,
                "brand": "",          # unknown at discovery time
                "model": term,
                "tier": tier,
                "gender": gender,
            })
            kept += 1
            log.info("discovered [%s] %s", gender, term)

        if i < len(seeds) - 1:
            time.sleep(PAUSE_BETWEEN)

    log.info("auto-discovery added %d new terms", len(new_rows))
    return new_rows
