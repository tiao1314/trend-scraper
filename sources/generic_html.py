"""
Generic, config-driven HTML scraper.

You give it a site profile - a URL template and a set of CSS selectors - and it
returns structured records. Everything goes through Fetcher, so robots.txt,
rate limiting and caching are applied automatically.

--------------------------------------------------------------------------
TESTING TARGETS
--------------------------------------------------------------------------
Two sites exist specifically so people can practise scraping without bothering
anyone: books.toscrape.com and quotes.toscrape.com. They are run by the Scrapy
maintainers, they permit automated access, and they are structurally similar to
a real product listing page - pagination, prices, stock status, per-item detail
pages. Point this module at them while you are getting your selectors and
pagination logic right.

--------------------------------------------------------------------------
WHY THE OBVIOUS TARGETS ARE NOT IN HERE
--------------------------------------------------------------------------
It is worth understanding this rather than discovering it at 2am:

  StockX, GOAT, Farfetch, Mytheresa, TikTok  - all serve their catalogue from
  JavaScript against an internal JSON API, behind Cloudflare or PerimeterX.
  requests + BeautifulSoup gets a 403 or an empty shell. You would need a
  headless browser plus residential proxies plus fingerprint evasion to get
  past it, and at that point you are not writing a scraper, you are writing
  circumvention tooling against a site actively refusing you - which is both a
  terms-of-service breach and, if you are trading as a registered business, an
  unnecessary legal exposure for data you can get legitimately elsewhere.

  Where they offer an API, use it. eBay's is free and better than anything you
  could scrape. For StockX-style resale pricing, licensed data resellers exist.

If you have written permission from a site, add a profile below and it will
work. The machinery is agnostic about the target.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urljoin

log = logging.getLogger(__name__)


@dataclass
class SiteProfile:
    name: str
    url_template: str        # {query} and {page} are substituted
    item_selector: str
    field_selectors: dict[str, str]
    next_page_selector: str | None = None
    attribute_map: dict[str, str] | None = None  # field -> html attribute


PROFILES: dict[str, SiteProfile] = {
    # Sandbox target #1 - a paginated catalogue with prices and stock.
    "books_sandbox": SiteProfile(
        name="books.toscrape.com",
        url_template="https://books.toscrape.com/catalogue/page-{page}.html",
        item_selector="article.product_pod",
        field_selectors={
            "title": "h3 a",
            "price": "p.price_color",
            "availability": "p.instock.availability",
            "rating": "p.star-rating",
        },
        next_page_selector="li.next a",
        attribute_map={"title": "title", "rating": "class"},
    ),
    # Sandbox target #2 - simpler, good for a first smoke test.
    "quotes_sandbox": SiteProfile(
        name="quotes.toscrape.com",
        url_template="https://quotes.toscrape.com/page/{page}/",
        item_selector="div.quote",
        field_selectors={"text": "span.text", "author": "small.author"},
        next_page_selector="li.next a",
    ),
}


def _extract(element, selector: str, attribute: str | None):
    found = element.select_one(selector)
    if found is None:
        return ""
    if attribute:
        value = found.get(attribute, "")
        return " ".join(value) if isinstance(value, list) else value
    return found.get_text(strip=True)


def scrape(profile_key: str, fetcher, *, query: str = "",
           max_pages: int = 3) -> list[dict]:
    """Walk a site profile and return a list of record dicts."""
    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("beautifulsoup4 is not installed. Run: pip install beautifulsoup4") from exc

    profile = PROFILES[profile_key]
    attribute_map = profile.attribute_map or {}
    records: list[dict] = []

    url = profile.url_template.format(query=query, page=1)
    for page_number in range(1, max_pages + 1):
        log.info("scrape %s page %d: %s", profile.name, page_number, url)
        html = fetcher.get(url)
        soup = BeautifulSoup(html, "html.parser")

        items = soup.select(profile.item_selector)
        if not items:
            log.warning("no items matched '%s' - selectors are probably stale",
                        profile.item_selector)
            break

        for item in items:
            record = {
                field: _extract(item, selector, attribute_map.get(field))
                for field, selector in profile.field_selectors.items()
            }
            record["_source"] = profile.name
            record["_page"] = page_number
            records.append(record)

        if not profile.next_page_selector or page_number == max_pages:
            break
        next_link = soup.select_one(profile.next_page_selector)
        if not next_link or not next_link.get("href"):
            break
        url = urljoin(url, next_link["href"])

    log.info("scraped %d records from %s", len(records), profile.name)
    return records
