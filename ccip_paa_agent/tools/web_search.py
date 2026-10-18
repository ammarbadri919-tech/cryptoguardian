
import os
import re
import html
import hashlib
import logging
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from zoneinfo import ZoneInfo
import feedparser
import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)
RSS_FEEDS = {
    # Original sources
    "CoinDesk": (
        "https://www.coindesk.com/arc/outboundfeeds/rss/"
        "?outputType=xml"
    ),
    "Cointelegraph": "https://cointelegraph.com/rss",
    "The Block": "https://www.theblock.co/rss.xml",
    "Decrypt": "https://decrypt.co/feed",

    # Additional crypto news sources
    "Bitcoin Magazine": "https://bitcoinmagazine.com/feed",
    "CryptoSlate": "https://cryptoslate.com/feed/",

    # Correct feed domains to test
    "Blockworks": "https://blockworks.co/feed",
    "The Defiant": "https://thedefiant.io/feed/",
}

APPROVED_DOMAINS = [
    "coindesk.com",
    "cointelegraph.com",
    "theblock.co",
    "decrypt.co",
    "bitcoinmagazine.com",
    "cryptoslate.com",
    "blockworks.co",
    "thedefiant.io",
]

TRACKING_PARAMS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
}
def clean_news_text(text):
    """Remove HTML, common clutter, and extra whitespace."""
    if not text:
        return ""

    text = html.unescape(str(text))
    text = re.sub(
        r"(?is)<(script|style).*?>.*?</\1>",
        " ",
        text,
    )
    text = re.sub(r"(?s)<[^>]+>", " ", text)

    text = re.sub(r"(?im)^By\s+.+$", "", text)
    text = re.sub(r"(?im)^Published\s+.+$", "", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()




def normalize_url(url):
    if not url:
        return ""

    parts = urlsplit(url.strip())

    query = [
        (key, value)
        for key, value in parse_qsl(parts.query)
        if not key.lower().startswith("utm_")
        and key.lower() not in TRACKING_PARAMS
    ]

    return urlunsplit((
        parts.scheme,
        parts.netloc.lower(),
        parts.path,
        urlencode(query),
        "",
    ))

def make_hash(url):
    if  not url:
        return""
    return hashlib.sha256(
        normalize_url(url).encode("utf-8")
    ).hexdigest()


from calendar import timegm

def get_published_at(entry):
    parsed = entry.get("published_parsed")

    if not parsed:
        return None

    timestamp = timegm(parsed)

    return datetime.fromtimestamp(
        timestamp,
        tz=timezone.utc
 
    ).isoformat()



def fetch_rss_news(limit_per_feed=15):
    articles =[]
    seen_hashes = set()
   
    for source, feed_url in RSS_FEEDS.items():
        try:
            response = requests.get(
            feed_url,
            headers={"User-Agent": "CryptoGuardian/1.0"},
            timeout=20,
            
            )
            response.raise_for_status()
            #response.rise_status()
            feed = feedparser.parse(response.content)
        except requests.RequestException as exc:
            logger.warning("RSS request failed for %s: %s", source, exc)
            continue

        for entry in feed.entries[:limit_per_feed]:
            headline = clean_news_text(entry.get("title", ""))
            url = normalize_url(entry.get("link", ""))

            if not headline or not url:
                continue

        
            published_at = get_published_at(entry)

            if not published_at:
                continue


            published_time= datetime.fromisoformat(published_at)
            now = datetime.now(timezone.utc)
            cutoff = now -timedelta(hoours=24)


            if not cutoff <= published_time <= now:
              continue
    

            

      
            
            url_hash = make_hash(url)


            if url_hash in seen_hashes:
                continue

            seen_hashes.add(url_hash)
            description = clean_news_text(
                    entry.get("summary", "") or entry.get("description", "")

            )
            articles.append({
                   "source": source,
                    "headline": headline,
                    "url": url,
                    "url_hash": url_hash,
                    "published_at": published_at,
                    "description": description[:800],
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                })
    return articles
   