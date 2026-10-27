
import os
import hashlib
from datetime import datetime, timezone
from urllib.parse import urlparse

from dotenv import load_dotenv
from tinyfish import TinyFish


load_dotenv()

API_KEY = os.getenv("TINYFISH_API_KEY")
if not API_KEY:
    raise ValueError("TINYFISH_API_KEY is missing from .env")

client = TinyFish(api_key=API_KEY)



APPROVED_DOMAINS = [
    # Crypto news
    "coindesk.com", "cointelegraph.com", "theblock.co", "decrypt.co",
    "bitcoinmagazine.com", "blockworks.co", "cryptoslate.com", "dlnews.com",
    "cryptobriefing.com", "beincrypto.com", "cryptopotato.com",
    "cryptopolitan.com", "u.today", "dailyhodl.com", "protos.com",
    "bitcoin.com", "ambcrypto.com", "cryptonews.com", "cryptonews.net",
    "crypto.news", "coinpedia.org", "cryptoticker.io", "cryptorank.io",
    "cryptotimes.io",               # <--- ADD THIS
    "bitcoinfoundation.org",        # <--- ADD THIS

    # Market data and derivatives
    "coingecko.com", "coinmarketcap.com", "coinglass.com",
    # ... rest of your list ...
]
FOREIGN_PATHS = [
    "/pl/", "/ja/", "/kr/", "/ko/", "/id/", "/uz/",
    "/es/", "/fr/", "/de/", "/pt/", "/pt-br/", "/it/",
    "/ru/", "/tr/", "/vi/", "/zh/", "/th/", "/nl/", "/ar/",
]

JUNK_WORDS = [
    "stock", "earnings", "transcript", "bancorp", "inc.", "corp."
]

CRYPTO_TERMS = [
    "bitcoin", "btc", "ethereum", "crypto", "cryptocurrency",
    "blockchain", "defi", "web3", "solana", "xrp", "dogecoin",
    "altcoin", "stablecoin", "token", "coinbase", "binance",
    "crypto exchange", "digital asset", "on-chain", "liquidation",
    "crypto etf", "bitcoin etf", "ethereum etf", "crypto hack",
    "wallet", "mining", "staking",
]


def is_approved_domain(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()

    return any(
        host == domain or host.endswith("." + domain)
        for domain in APPROVED_DOMAINS
    )

def tiny_fish_serched(query, max_results=60):
    """Search TinyFish and return structured article dictionaries.

    Returns:
        list: Successful search results, possibly empty.
        None: Search failed.
    """

    # Make one API request only.
    try:
        response = client.search.query(
            query=query,
            purpose="Find recent, relevant cryptocurrency market news.",
            recency_minutes=60,
            domain_type="news",
            language="en",
        )
    except Exception as error:
        print(f"TinyFish search failed: {error}")
        return None

    search_results = getattr(response, "results", []) or []

    print(
        "Total results reported:",
        getattr(response, "total_results", "unknown"),
    )
    print("Results on this page:", len(search_results))

    results = []

    for r in search_results[:max_results]:
        title = (
            getattr(r, "title", "")
            or getattr(r, "headline", "")
            or ""
        ).strip()

        url = (getattr(r, "url", "") or "").strip()

        content = (
            getattr(r, "content", "")
            or getattr(r, "snippet", "")
            or getattr(r, "description", "")
            or ""
        ).strip()

        if not title or not url:
            print("Reject: missing title or URL")
            continue

        if not is_approved_domain(url):
            print(f"Reject (unapproved domain): {title} | URL: {url}")
            continue

        path = urlparse(url).path.lower()

        if any(prefix in path for prefix in FOREIGN_PATHS):
            print(f"Reject (foreign-language path): {title}")
            continue

        if any(word in title.casefold() for word in JUNK_WORDS):
            print(f"Reject (junk title): {title}")
            continue

        # Keep publication time only when the provider supplies a datetime.
        published_at = getattr(r, "published_at", None)

        if isinstance(published_at, datetime):
            if published_at.tzinfo is None:
                published_at = published_at.replace(
                    tzinfo=timezone.utc
                )
        else:
            published_at = None

        article = {
            "source": urlparse(url).hostname or "unknown",
            "headline": title,
            "url": url,
            "url_hash": hashlib.sha256(
                url.encode("utf-8")
            ).hexdigest(),
            "published_at": published_at,
            "description": content[:500],
            "fetched_at": datetime.now(timezone.utc),
        }

        results.append(article)
        print(f"Keep: {title}")

    # An empty list means the API request succeeded but
    # no results passed the filters.
    return results


   