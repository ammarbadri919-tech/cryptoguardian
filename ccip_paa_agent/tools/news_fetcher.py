import calendar
import hashlib
import html
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

import feedparser
import requests

logger = logging.getLogger(__name__)

RSS_FEEDS = {
    "CoinDesk": (
        "https://www.coindesk.com/arc/outboundfeeds/rss/"
        "?outputType=xml"
    ),
    "Cointelegraph": "https://cointelegraph.com/rss",
    "The Block": "https://www.theblock.co/rss.xml",
    "Decrypt": "https://decrypt.co/feed",
}


def clean_text(text):
    """Remove HTML markup and normalize whitespace."""
    if not text:
        return ""

    text = re.sub(
        r"(?is)<(script|style).*?>.*?</\1>", " ", text
    )
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_url(url):
    """Remove tracking parameters while preserving useful URL data."""
    if not url:
        return ""

    parts = urlsplit(url.strip())

    tracking_keys = {
        "fbclid", "gclid", "mc_cid", "mc_eid"
    }

    query = [
        (key, value)
        for key, value in parse_qsl(
            parts.query, keep_blank_values=True
        )
        if not key.lower().startswith("utm_")
        and key.lower() not in tracking_keys
    ]

    return urlunsplit((
        parts.scheme.lower(),
        parts.netloc.lower(),
        parts.path,
        urlencode(query, doseq=True),
        "",  # Drop URL fragment
    ))


def make_url_hash(url):
    """Create a stable fingerprint for duplicate detection."""
    return hashlib.sha256(
        normalize_url(url).encode("utf-8")
    ).hexdigest()


def get_published_at(entry):
    """Return publication time in UTC, or None if unavailable."""
    for field in ("published_parsed", "updated_parsed"):
        parsed = entry.get(field)

        if parsed:
            timestamp = calendar.timegm(parsed)
            return datetime.fromtimestamp(
                timestamp, tz=timezone.utc
            )

    return None


def fetch_rss_feed(limit_per_feed=10):
    