
import os
import csv
import re
import hashlib
from pathlib import Path
from datetime import datetime, timezone, timedelta

import psycopg
from dotenv import load_dotenv

from tools.web_search import fetch_rss_news
from tools.tinyfish import tiny_fish_serched



load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

BASE_DIR = Path(__file__).resolve().parent.parent
COINS_FILE = BASE_DIR / "selected_coins.csv"

RETENTION_HOURS = 3


def get_connection():
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL is missing from .env")

    return psycopg.connect(
        DATABASE_URL,
        sslmode="require",
    )


def setup_database():
    print("Checking database connection...")

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS news_articles (
                    id SERIAL PRIMARY KEY,
                    source VARCHAR(100),
                    headline TEXT,
                    url TEXT,
                    url_hash VARCHAR(64) UNIQUE,
                    published_at TIMESTAMPTZ,
                    description TEXT,
                    fetched_at TIMESTAMPTZ
                );
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS coin_search_status (
                    coin_name TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    last_tinyfish_search TIMESTAMPTZ,
                    PRIMARY KEY (coin_name, symbol)
                );
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS news_article_coins (
                    article_id INTEGER NOT NULL
                        REFERENCES news_articles(id)
                        ON DELETE CASCADE,
                    coin_name TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    PRIMARY KEY (article_id, coin_name, symbol)
                );
            """)

            cur.execute("""
                CREATE INDEX IF NOT EXISTS
                    idx_news_article_coins_coin
                ON news_article_coins (coin_name, symbol);
            """)

    print("Database is ready.")


# --------------------------------------------------
# LOAD SELECTED COINS FROM CSV
# --------------------------------------------------

def load_coins():
    if not COINS_FILE.exists():
        raise FileNotFoundError(
            f"Coin file not found: {COINS_FILE}"
        )

    coins = []
    seen = set()

    with open(
        COINS_FILE,
        "r",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        reader = csv.DictReader(file)

        required = {"coin_name", "symbol"}

        if (
            not reader.fieldnames
            or not required.issubset(reader.fieldnames)
        ):
            raise ValueError(
                "CSV must contain coin_name and symbol columns."
            )

        for row in reader:
            name = (row.get("coin_name") or "").strip()
            symbol = (row.get("symbol") or "").strip().upper()

            if not name or not symbol:
                continue

            key = (name.casefold(), symbol)

            if key not in seen:
                seen.add(key)
                coins.append({
                    "coin_name": name,
                    "symbol": symbol,
                })

    print(f"Loaded {len(coins)} selected coins.")
    return coins



def article_mentions_coin(
    headline,
    description,
    name,
    symbol,
):
    headline_text = (headline or "").casefold()
    description_text = (description or "").casefold()
    text = f"{headline_text} {description_text}"

    # Match the full coin name in headline or description.
    name_pattern = (
        r"(?<!\w)" + re.escape(name.casefold()) + r"(?!\w)"
    )

    if re.search(name_pattern, text):
        return True

    # Match the ticker symbol in the headline only.
    symbol_pattern = (
        r"(?<!\w)" + re.escape(symbol.casefold()) + r"(?!\w)"
    )

    return bool(re.search(symbol_pattern, headline_text))


def filter_relevant_articles(articles, name, symbol):
    """Keep valid article dictionaries relevant to this coin."""

    relevant = []

    for article in articles or []:
        if not isinstance(article, dict):
            continue

        headline = article.get("headline", "")
        description = article.get("description", "")
        url = (article.get("url") or "").strip()

        if not url or not headline:
            continue

        if article_mentions_coin(
            headline,
            description,
            name,
            symbol,
        ):
            relevant.append(article)

    return relevant


# --------------------------------------------------
# SAVE ARTICLES TO POSTGRESQL
# --------------------------------------------------

def save_articles(articles, coin_name, symbol):
    """Save articles and associate them with the selected coin."""

    if not articles:
        return 0

    added = 0

    with get_connection() as conn:
        with conn.cursor() as cur:
            for article in articles:
                if not isinstance(article, dict):
                    continue

                url = (article.get("url") or "").strip()

                if not url:
                    continue

                now = datetime.now(timezone.utc)

                url_hash = article.get("url_hash") or hashlib.sha256(
                    url.encode("utf-8")
                ).hexdigest()

                cur.execute("""
                    INSERT INTO news_articles (
                        source,
                        headline,
                        url,
                        url_hash,
                        published_at,
                        description,
                        fetched_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (url_hash) DO NOTHING
                    RETURNING id;
                """, (
                    article.get("source", "unknown"),
                    article.get("headline", ""),
                    url,
                    url_hash,
                    article.get("published_at"),
                    article.get("description", ""),
                    article.get("fetched_at") or now,
                ))

                row = cur.fetchone()

                if row:
                    article_id = row[0]
                    added += 1
                else:
                    # Reuse an existing article instead of duplicating it.
                    cur.execute("""
                        SELECT id
                        FROM news_articles
                        WHERE url_hash = %s;
                    """, (url_hash,))

                    existing = cur.fetchone()

                    if not existing:
                        continue

                    article_id = existing[0]

                # Map the article to this coin, including when
                # the article already existed in the database.
                cur.execute("""
                    INSERT INTO news_article_coins (
                        article_id,
                        coin_name,
                        symbol
                    )
                    VALUES (%s, %s, %s)
                    ON CONFLICT DO NOTHING;
                """, (
                    article_id,
                    coin_name.strip().casefold(),
                    symbol.strip().upper(),
                ))

    # Counts new article rows, not new coin mappings.
    return added


# --------------------------------------------------

def has_fresh_news(coin_name, symbol, minutes=60):
    """Check whether this coin has published news in the time window."""

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT EXISTS (
                    SELECT 1
                    FROM news_article_coins AS nac
                    JOIN news_articles AS na
                        ON na.id = nac.article_id
                    WHERE LOWER(nac.coin_name) = LOWER(%s)
                      AND UPPER(nac.symbol) = UPPER(%s)
                      AND na.published_at IS NOT NULL
                      AND na.published_at >=
                          NOW() - (%s * INTERVAL '1 minute')
                );
            """, (coin_name, symbol, minutes))

            return cur.fetchone()[0]


# --------------------------------------------------
# RECORD SUCCESSFUL TINYFISH SEARCH
# --------------------------------------------------

def record_tinyfish_search(name, symbol):
    """Record a completed TinyFish search."""

    now = datetime.now(timezone.utc)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO coin_search_status (
                    coin_name,
                    symbol,
                    last_tinyfish_search
                )
                VALUES (%s, %s, %s)
                ON CONFLICT (coin_name, symbol)
                DO UPDATE SET
                    last_tinyfish_search =
                        EXCLUDED.last_tinyfish_search;
            """, (
                name.casefold(),
                symbol.upper(),
                now,
            ))


# --------------------------------------------------
# REMOVE OLD ARTICLES
# --------------------------------------------------

def cleanup_old_news():
    """Delete articles older than the configured retention period."""

    cutoff = datetime.now(timezone.utc) - timedelta(
        hours=RETENTION_HOURS
    )

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                DELETE FROM news_articles
                WHERE fetched_at < %s;
            """, (cutoff,))

            print(f"Old articles deleted: {cur.rowcount}")


# --------------------------------------------------
# RSS JOB
# --------------------------------------------------

def run_rss_job():
    """Collect RSS news only. Never call TinyFish here."""

    print("\nStarting RSS job...")

    try:
        coins = load_coins()
        rss_articles = fetch_rss_news() or []

        print(f"RSS articles received: {len(rss_articles)}")

    except Exception as error:
        print(f"RSS job failed: {error}")
        return

    for coin in coins:
        name = coin["coin_name"]
        symbol = coin["symbol"]

        try:
            relevant = filter_relevant_articles(
                rss_articles,
                name,
                symbol,
            )

            saved = save_articles(
                relevant,
                name,
                symbol,
            )

            print(
                f"{name} ({symbol}): "
                f"{len(relevant)} relevant RSS articles; "
                f"{saved} new articles saved."
            )

        except Exception as error:
            print(
                f"RSS processing failed for "
                f"{name} ({symbol}): {error}"
            )

    try:
        cleanup_old_news()
    except Exception as error:
        print(f"RSS cleanup failed: {error}")

    print("RSS job complete.")


# --------------------------------------------------
# TINYFISH FALLBACK JOB
# --------------------------------------------------

def run_tinyfish_job():
    print("\nStarting TinyFish job...")

    try:
        coins = load_coins()

    except Exception as error:
        print(f"Could not load coins: {error}")
        return

    for coin in coins:
        name = coin["coin_name"]
        symbol = coin["symbol"]

        try:
            if has_fresh_news(name, symbol, minutes=60):
                print(
                    f"{name} ({symbol}): fresh news exists; "
                    "skipping TinyFish."
                )
                continue

            print(
                f"{name} ({symbol}): no fresh news; "
                "searching with TinyFish."
            )

            query = (
                f'"{name}" ({symbol}) '
                f'"{name} price" OR "{name} news" OR '
                f'"{name} market" OR "{symbol} token"'
            )

            results = tiny_fish_serched(
                query,
                max_results=10,
            )

            # None means the search raised an exception.
            # Do not mark this failed search as completed.
            if results is None:
                print(
                    f"{name} ({symbol}): TinyFish search failed; "
                    "search status not updated."
                )
                continue

            # An empty list is a successful search with no results.
            relevant = filter_relevant_articles(
                results,
                name,
                symbol,
            )
            print(
                    f"DEBUG {name} ({symbol}): "
                    f"{len(results)} candidates -> "
                     f"{len(relevant)} relevant"
)

            saved = save_articles(
                relevant,
                name,
                symbol,
            )

            # Update status after a successful search and processing.
            record_tinyfish_search(name, symbol)

            print(
                f"{name} ({symbol}): "
                f"{len(relevant)} relevant articles; "
                f"{saved} new articles saved."
            )

        except Exception as error:
            print(
                f"TinyFish processing failed for "
                f"{name} ({symbol}): {error}"
            )

    try:
        cleanup_old_news()
    except Exception as error:
        print(f"TinyFish cleanup failed: {error}")

    print("TinyFish job complete.")


# --------------------------------------------------
# MANUAL ONE-SHOT RUN
# --------------------------------------------------

def run_miner():
    """Run setup, RSS collection, and TinyFish fallback once."""

    setup_database()
    run_rss_job()
    run_tinyfish_job()


if __name__ == "__main__":
    run_miner()
