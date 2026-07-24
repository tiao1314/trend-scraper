"""
Offline tests. No network required.

Run: python test_offline.py
"""

import sys
import urllib.robotparser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import scoring

FAILURES = []


def check(name, condition, detail=""):
    if condition:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name} {detail}")
        FAILURES.append(name)


print("\nscoring.normalise")
check("flat input maps to 50",
      scoring.normalise({"a": 5, "b": 5}) == {"a": 50.0, "b": 50.0})
n = scoring.normalise({"a": 0, "b": 50, "c": 100})
check("min maps to 0", n["a"] == 0.0)
check("max maps to 100", n["c"] == 100.0)
check("midpoint maps to 50", n["b"] == 50.0)
check("empty input is safe", scoring.normalise({}) == {})

print("\nscoring.scarcity_signal (inverted: fewer listings = higher score)")
s = scoring.scarcity_signal({"scarce": 0, "mid": 50, "flooded": 100})
check("zero listings scores 100", s["scarce"] == 100.0)
check("most listings scores 0", s["flooded"] == 0.0)
check("scarcity is monotonically decreasing", s["scarce"] > s["mid"] > s["flooded"])

print("\nscoring.band boundaries")
check("80 -> band 5", scoring.band(80) == 5)
check("79.9 -> band 4", scoring.band(79.9) == 4)
check("62 -> band 4", scoring.band(62) == 4)
check("41 -> band 2", scoring.band(41) == 2)
check("0 -> band 1", scoring.band(0) == 1)

print("\nscoring.verdict")
check("climbing + thin supply = STRONG BUY",
      scoring.verdict(50, 5, 0).startswith("STRONG BUY"))
check("falling demand = AVOID",
      scoring.verdict(-40, 5, 0).startswith("AVOID"))
check("heavy supply = CROWDED",
      scoring.verdict(0, 500, 0).startswith("CROWDED"))
check("flat = HOLD", scoring.verdict(0, 50, 0).startswith("HOLD"))

print("\nscoring.blend")
rows = scoring.blend(
    trends={"hot": {"level": 90, "momentum": 150}, "cold": {"level": 10, "momentum": -30}},
    ebay={"hot": {"listings": 2, "median_price": 500}, "cold": {"listings": 300, "median_price": 80}},
    news={"hot": {"mentions": 9}, "cold": {"mentions": 0}},
)
check("returns one row per product", len(rows) == 2)
check("sorted by heat descending", rows[0].heat_score >= rows[1].heat_score)
check("hot product ranks first", rows[0].product == "hot")
check("missing source does not crash",
      len(scoring.blend({"x": {"level": 5, "momentum": 5}}, {}, {})) == 1)

print("\nrobots.txt parsing")
parser = urllib.robotparser.RobotFileParser()
parser.parse([
    "User-agent: *",
    "Disallow: /private/",
    "Crawl-delay: 7",
    "Allow: /public/",
])
check("disallowed path is blocked",
      not parser.can_fetch("TrendResearchBot/1.0", "https://x.com/private/a"))
check("allowed path is permitted",
      parser.can_fetch("TrendResearchBot/1.0", "https://x.com/public/a"))
check("crawl-delay is read", parser.crawl_delay("TrendResearchBot/1.0") == 7)

print("\ngeneric_html parsing (against a local HTML fixture)")
SAMPLE = """
<html><body>
<article class="product_pod">
  <h3><a href="/a.html" title="A Light in the Attic">A Light...</a></h3>
  <p class="price_color">&pound;51.77</p>
  <p class="instock availability">In stock</p>
  <p class="star-rating Three"></p>
</article>
<article class="product_pod">
  <h3><a href="/b.html" title="Tipping the Velvet">Tipping...</a></h3>
  <p class="price_color">&pound;53.74</p>
  <p class="instock availability">In stock</p>
  <p class="star-rating One"></p>
</article>
<li class="next"><a href="page-2.html">next</a></li>
</body></html>
"""


class StubFetcher:
    """Stands in for Fetcher so the parser can be tested without a network."""
    def __init__(self, html):
        self.html = html
        self.calls = 0

    def get(self, url, use_cache=True):
        self.calls += 1
        return self.html


from sources import generic_html  # noqa: E402

stub = StubFetcher(SAMPLE)
records = generic_html.scrape("books_sandbox", stub, max_pages=1)
check("extracted both items", len(records) == 2)
check("title pulled from attribute", records[0]["title"] == "A Light in the Attic")
check("price pulled from text", "51.77" in records[0]["price"])
check("availability parsed", records[0]["availability"] == "In stock")
check("rating class captured", "Three" in records[0]["rating"])
check("source stamped", records[0]["_source"] == "books.toscrape.com")

stub2 = StubFetcher(SAMPLE)
multi = generic_html.scrape("books_sandbox", stub2, max_pages=3)
check("pagination followed", stub2.calls == 3 and len(multi) == 6)

stub3 = StubFetcher("<html><body>nothing here</body></html>")
check("stale selectors return empty, no crash",
      generic_html.scrape("books_sandbox", stub3, max_pages=2) == [])

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILURES: {', '.join(FAILURES)}")
    raise SystemExit(1)
print("All tests passed.")
