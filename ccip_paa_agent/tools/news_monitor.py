
import time
import threading
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


# 
def load_coins(csv_path=None):
    """Load coins from an uploaded CSV or the default CSV."""

    file_path = Path(csv_path) if csv_path else COINS_FILE

    if not file_path.exists():
        raise FileNotFoundError(
            f"Coin CSV file not found: {file_path}"
        )

    coins = []
    seen = set()

    with open(
        file_path,
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

    if not coins:
        raise ValueError("No valid coins found in CSV.")

    print(f"Loaded {len(coins)} selected coins from {file_path.name}.")
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

    # Match the full coin name.
    name_pattern = (
        r"(?<!\w)" + re.escape(name.casefold()) + r"(?!\w)"
    )

    if re.search(name_pattern, text):
        return True

    # Match ticker only when crypto context is present.
    symbol_pattern = (
        r"(?<!\w)" + re.escape(symbol.casefold()) + r"(?!\w)"
    )

    crypto_context = [
        "crypto", "cryptocurrency", "token", "blockchain",
        "coin", "defi", "exchange", "trading",
        "digital asset", "wallet",
    ]

    has_symbol = bool(re.search(symbol_pattern, headline_text))
    has_crypto_context = any(
        term in text for term in crypto_context
    )

    return has_symbol and has_crypto_context



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

def run_rss_job(csv_path=None):
    """Collect RSS news and return coins for which RSS found relevant news."""

    print("\nStarting RSS job...")
    coins_with_rss_news = set()

    try:
        coins = load_coins(csv_path)
        rss_articles = fetch_rss_news() or []
        print(f"RSS articles received: {len(rss_articles)}")

    except Exception as error:
        print(f"RSS job failed: {error}")
        return coins_with_rss_news

    for coin in coins:
        name = coin["coin_name"]
        symbol = coin["symbol"]
        coin_key = (name.casefold(), symbol.upper())

        try:
            relevant = filter_relevant_articles(
                rss_articles,
                name,
                symbol,
            )

            # If RSS found relevant news for this coin during the window,
            # TinyFish can skip it even when the article was already saved.
            # Duplicate protection is handled by the database URL hash.
            if relevant:
                coins_with_rss_news.add(coin_key)

            saved = save_articles(relevant, name, symbol)

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
    return coins_with_rss_news


# --------------------------------------------------
# TINYFISH FALLBACK JOB
# --------------------------------------------------


def run_tinyfish_job(coins_with_rss_news, csv_path=None):
    """Search with TinyFish only for coins RSS did not cover."""

    print("\nStarting TinyFish fallback job...")

    try:
        
        coins = load_coins(csv_path)
    except Exception as error:
        print(f"Could not load coins: {error}")
        return

    for coin in coins:
        name = coin["coin_name"]
        symbol = coin["symbol"]
        coin_key = (name.casefold(), symbol.upper())

        if coin_key in coins_with_rss_news:
            print(
                f"{name} ({symbol}): RSS already found news; "
                "skipping TinyFish."
            )
            continue

        try:
            print(
                f"{name} ({symbol}): RSS found no relevant news; "
                "searching with TinyFish."
            )

           

            query = (
              f'"{name}" "{symbol}" cryptocurrency news '
              f'price OR market OR token OR exchange '
              f'-stocks -gaming -calculator')

            results = tiny_fish_serched(query, max_results=10)

            # None means the search failed; an empty list means
            # the search worked but found no results.


            if results is None:
                print(
                    f"{name} ({symbol}): TinyFish search failed."
                )
                continue

            relevant = filter_relevant_articles(results, name, symbol)
            saved = save_articles(relevant, name, symbol)

            record_tinyfish_search(name, symbol)
            if relevant:

              print(
                f"{name} ({symbol}): "
                f"{len(relevant)} relevant TinyFish articles; "
                f"{saved} new articles saved."
             )
            else:
                 print(f"{name} ({symbol}): No relevant news found.")

             

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

def run_news_collection(csv_path):
    """Collect news for coins supplied through an uploaded CSV."""

    print("\n========== UPLOADED CSV NEWS COLLECTION ==========")

    # Step 1: Ensure database tables exist
    setup_database()

    # Step 2: Collect news using RSS
    coins_with_rss_news = run_rss_job(csv_path)

    # Step 3: Use TinyFish for coins RSS did not cover
    run_tinyfish_job(coins_with_rss_news, csv_path)

    print("\nUploaded CSV news collection completed.")



# --------------------------------------------------
# CONTINUOUS NEWS MONITOR
# --------------------------------------------------

RSS_INTERVAL = 30                 # Check RSS every 30 seconds
TINYFISH_INTERVAL = 15 * 60       # Run TinyFish every 15 minutes

# RSS and TinyFish run independently. This lets RSS keep checking
# while a TinyFish search is still in progress.
rss_news_lock = threading.Lock()
rss_coins_with_news = set()



def rss_worker(csv_path=None):
    """Keep checking RSS for coins in the uploaded CSV."""

    while True:
        started = time.monotonic()

        print("\n========== RSS CHECK ==========")

        found_coins = run_rss_job(csv_path)

        with rss_news_lock:
            rss_coins_with_news.update(found_coins)

        elapsed = time.monotonic() - started
        time.sleep(max(0, RSS_INTERVAL - elapsed))




def tinyfish_worker(csv_path=None):
    """Run TinyFish fallback every 15 minutes for uploaded coins."""

    while True:
        time.sleep(TINYFISH_INTERVAL)

        with rss_news_lock:
            found_coins = set(rss_coins_with_news)
            rss_coins_with_news.clear()

        print("\n========== TINYFISH CHECK ==========")

        run_tinyfish_job(found_coins, csv_path)




def run_miner(csv_path=None):
    """Run RSS and TinyFish continuously for the supplied CSV."""

    setup_database()

    # Clear previous RSS results when starting a new monitoring session.
    with rss_news_lock:
        rss_coins_with_news.clear()

    print("\nCryptoGuardian News Monitor is running...")
    print(f"Monitoring CSV: {csv_path or COINS_FILE}")
    print("RSS checks every 30 seconds.")
    print("TinyFish fallback checks every 15 minutes.")
    print("Articles are retained for 3 hours after fetching.")
    print("Press CTRL+C to stop.")

    rss_thread = threading.Thread(
        target=rss_worker,
        args=(csv_path,),
        name="RSS-Worker",
        daemon=True,
    )

    tinyfish_thread = threading.Thread(
        target=tinyfish_worker,
        args=(csv_path,),
        name="TinyFish-Worker",
        daemon=True,
    )

    rss_thread.start()
    tinyfish_thread.start()

    while True:
        time.sleep(1)

        time.sleep(1)


if __name__ == "__main__":
    try:
        run_miner()
    except KeyboardInterrupt:
        print("\nNews monitor stopped by user.")
