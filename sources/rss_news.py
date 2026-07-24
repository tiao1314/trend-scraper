"""
Editorial mention signal, via RSS.

RSS feeds are published specifically to be consumed by software, so this is the
one "scraping-shaped" source with no ambiguity at all about whether you are
welcome.

Why it is useful: fashion press runs roughly one quarter ahead of search
volume. A model that starts appearing in Who What Wear and WWD in July is
usually what people are googling in October. Treat this as your leading
indicator and Google Trends as your confirming one.

Counts are mentions across all fetched feed entries within the lookback window,
matched case-insensitively on the model name.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)

DEFAULT_FEEDS = [
    "https://www.whowhatwear.com/rss",
    "https://wwd.com/feed/",
    "https://www.harpersbazaar.com/rss/all.xml/",
    "https://www.elle.com/rss/all.xml/",
    "https://www.purseblog.com/feed/",
    "https://www.vogue.com/feed/rss",
]


# Words that describe a category, not a product - matching on these would count
# every handbag article as a hit, so they never form a keyword on their own.
GENERIC = {
    "bag", "bags", "tote", "clutch", "pouch", "wallet", "cardholder", "backpack",
    "crossbody", "barrel", "shoulder", "top", "handle", "shoe", "shoes",
    "sneaker", "sneakers", "trainer", "loafer", "loafers", "pump", "pumps",
    "mule", "mules", "flat", "flats", "ballet", "slingback", "slingbacks",
    "wedge", "slide", "slides", "sandal", "boot", "belt", "watch", "sunglasses",
    "bracelet", "mens", "men", "women", "womens", "the", "and", "collab",
    "edition", "reissue", "revival", "vintage", "print", "leather", "nylon",
    "raffia", "woven", "mesh", "studded", "crystal", "chain", "two", "tone",
    "small", "large", "mini", "maxi", "classic", "various", "style", "styles",
    "retro", "recovery", "lace", "up", "doll", "heels", "jelly", "era",
    # common English / seasonal / marketing words that are not model names
    "summer", "winter", "spring", "autumn", "fall", "walk", "new", "back",
    "best", "favorite", "favourite", "everything", "season", "day", "way",
    "canvas", "white", "black", "brown", "gold", "silver", "resilience",
}

# Known makers. A brand token gives context but is not specific enough to count
# on its own (Chanel appears in fashion press daily) - we require a model word.
BRANDS = {
    "chanel", "dior", "hermes", "row", "miu", "prada", "bottega", "veneta",
    "balenciaga", "chloe", "gucci", "fendi", "loewe", "saint", "laurent",
    "louis", "vuitton", "coach", "goyard", "manu", "atelier", "celine",
    "alaia", "loro", "piana", "khaite", "adidas", "balance", "nike", "jordan",
    "onitsuka", "tiger", "puma", "village", "isabel", "marant", "paraboot",
    "dries", "van", "noten", "larroude", "steve", "madden", "ferragamo",
    "cartier", "rolex", "omega", "salomon", "common", "projects", "maison",
    "margiela", "ray", "ban", "goyard", "loro",
}


def keywords_for(term: str) -> list[str]:
    """Distinctive model tokens to search headlines for (e.g. 'birkin',
    'jackie', 'samba'), dropping brand-only and category-only words."""
    tokens = re.findall(r"[a-z0-9]+", term.lower())
    model = [t for t in tokens
             if len(t) >= 4 and t not in GENERIC and t not in BRANDS
             and not t.isdigit()]
    # Only distinctive model words count. If a term has none (e.g. a bare brand
    # like "Chanel Classic"), we return nothing rather than matching the brand
    # alone, which would count unrelated "Chanel Beauty" articles as hits.
    return model


def _entry_date(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, key, None)
        if parsed:
            return datetime(*parsed[:6], tzinfo=timezone.utc)
    return None


def collect(terms: list[str], feeds: list[str] | None = None,
            lookback_days: int = 90) -> dict[str, dict]:
    """Return {term: {"mentions": int, "recent_headline": str}}."""
    try:
        import feedparser
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("feedparser is not installed. Run: pip install feedparser") from exc

    feeds = feeds or DEFAULT_FEEDS
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)

    documents: list[tuple[str, str]] = []  # (title, blob)
    for url in feeds:
        try:
            parsed = feedparser.parse(url)
        except Exception as exc:
            log.warning("feed failed %s: %s", url, exc)
            continue

        if getattr(parsed, "bozo", 0) and not parsed.entries:
            log.warning("feed unreadable: %s", url)
            continue

        for entry in parsed.entries:
            stamp = _entry_date(entry)
            if stamp and stamp < cutoff:
                continue
            title = getattr(entry, "title", "")
            summary = getattr(entry, "summary", "")
            documents.append((title, f"{title} {summary}".lower()))

        log.info("feed %-45s entries=%d", url.split("//")[-1][:45], len(parsed.entries))

    results: dict[str, dict] = {}
    for term in terms:
        keys = keywords_for(term)
        # A document counts once if any distinctive model keyword appears in it,
        # matched on word boundaries so "indy" doesn't fire inside "india".
        patterns = [re.compile(r"\b" + re.escape(k) + r"\b") for k in keys]
        hits = [title for title, blob in documents
                if any(p.search(blob) for p in patterns)]
        results[term] = {
            "mentions": len(hits),
            "recent_headline": hits[0][:120] if hits else "",
        }

    return results
