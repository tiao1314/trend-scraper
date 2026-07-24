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
        pattern = re.compile(re.escape(term.lower()))
        hits = [title for title, blob in documents if pattern.search(blob)]
        results[term] = {
            "mentions": len(hits),
            "recent_headline": hits[0][:120] if hits else "",
        }

    return results
