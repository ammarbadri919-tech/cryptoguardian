import re
import time
import requests
import feedparser

from calendar import timegm
from tools.web_search import RSS_FEEDS

HEADERS = {"User-Agent": "CryptoGuardian/1.0"}
LOOKBACK_MINUTES = 1440
coin_name = input("Enter coin name (e.g. Bitcoin): ").strip()
coin_symbol = input("Enter coin symbol (e.g. BTC): ").strip()

if not coin_name or not coin_symbol:
    raise SystemExit("Please enter both the coin name and symbol.")

patterns = [
    re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)
    for term in (coin_name, coin_symbol)
]

articles = []
seen_urls = set()

for source, url in RSS_FEEDS.items():
    now = time.time()
    cutoff = now - (LOOKBACK_MINUTES * 60)
    
    
    print(f"\nTesting {source}...")

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=(10,20),
        )
        response.raise_for_status()

        feed = feedparser.parse(response.content)
        print(f"HTTP: {response.status_code} | Feed entries: {len(feed.entries)}")

        for entry in feed.entries:
            title = entry.get("title", "")
            summary = entry.get("summary", "")
            text = f"{title} {summary}"

            if not any(pattern.search(text) for pattern in patterns):
                continue

            article_url = entry.get("link", "").strip()

            if not article_url or article_url in seen_urls:
                continue

            published = (
                entry.get("published_parsed")
                or entry.get("updated_parsed")
            )
            if not published:
                continue
            timestamp = timegm(published)

            if timestamp< cutoff  or timestamp > now +300:
                continue

            seen_urls.add(article_url)
            articles.append({
                "source": source,
                "title": title,
                "url": article_url,
                "timestamp": timestamp,
            })

    except Exception as error:
        print(f"FAILED: {error}")

articles.sort(key=lambda article: article["timestamp"], reverse=True)

print(f"\n{'=' * 60}")
print(
    f"TOP 10 ARTICLES FROM LAST {LOOKBACK_MINUTES} MINUTES: "
    f"{coin_name} ({coin_symbol})"
)
print(f"Matching articles found: {len(articles)}")
print("=" * 60)

for index, article in enumerate(articles[:50], start=1):
    published = (
        time.strftime(
            "%Y-%m-%d %H:%M UTC",
            time.gmtime(article["timestamp"]),
        )
        if article["timestamp"]
        else "Publication time unavailable"
    )

    print(f"\n{index}. {article['title']}")
    print(f"Source: {article['source']}")
    print(f"Published: {published}")
    print(f"URL: {article['url']}")

if not articles:
    print("No matching news found in the available RSS feeds.")