import os
import psycopg
from dotenv import load_dotenv
from datetime import datetime, timezone, timedelta
from tools.web_search import fetch_rss_news
from tools.tinyfish import tiny_fish_serched
load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")


def get_connection():
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL is missing from .env")
    return psycopg.connect(DATABASE_URL, sslmode="require")

def setup_database():
    print("Checking database connection...")
    with get_connection() as conn:

      with conn.cursor() as cur:
          cur.execute("""
              CREATE TABLE  IF NOT EXISTS  news_articles(
                        id SERIAL PRIMARY KEY,
                        source VARCHAR(100),
                        headline TEXT,
                        url TEXT,
                        url_hash VARCHAR(64) UNIQUE,
                        published_at TIMESTAMPTZ,
                        description TEXT,
                        fetched_at TIMESTAMPTZ
                    ); 
                """ )
          print("DATABASE IS REDAY")
def cleanup_old_news():
        print("Cleaning articles older than 12 hours...")
        cutoff = datetime.now(timezone.utc) - timedelta(hours=12)
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                DELETE FROM news_articles
                WHERE published_at < %s;
            """, (cutoff,))
            deleted = cur.rowcount
        print(f"Old articles deleted: {deleted}")

def check_fresh_news():
    print("Checking database for news from the last 60 minutes...")
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=60)
    
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM news_articles WHERE published_at >= %s;", (cutoff,))
            count = cur.fetchone()[0]
            
    if count > 0:
        print(f" Database has {count} fresh articles. TinyFish is NOT needed.")
        return True
    else:
        print(" No fresh news in database. TinyFish search is required.")
        return False
def run_miner():
    print("STARTING ............")
    try:
        articles = fetch_rss_news()
        print(f"Aritcles REcived from  RSSS: {len(articles)} articles")
        added = 0
        if articles:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    for article in articles:
                        cur.execute("""
                            INSERT INTO news_articles
                                (source, headline, url, url_hash,
                                 published_at, description, fetched_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (url_hash) DO NOTHING;
                        """, (
                            article["source"],
                            article["headline"],
                            article["url"],
                            article["url_hash"],
                            article["published_at"],
                            article["description"],
                            article["fetched_at"],
                        ))
                        added += cur.rowcount

        print(f"New articles added: {added}")

    except Exception as error:
        print(f"Error fetching news: {error}")




            # --- TRIGGER TINYFISH IF NEEDED ---
    try:
        has_fresh_news = check_fresh_news()
        
        if not has_fresh_news:
            print(" Triggering TinyFish Search...")
            tinyfish_articles = tiny_fish_serched("crypto news", max_results=10)
            
            if tinyfish_articles:
                added_tf = 0
                with get_connection() as conn:
                    with conn.cursor() as cur:
                        for article in tinyfish_articles:
                            cur.execute("""
                                INSERT INTO news_articles
                                    (source, headline, url, url_hash, published_at, description, fetched_at)
                                VALUES (%s, %s, %s, %s, %s, %s, %s)
                                ON CONFLICT (url_hash) DO NOTHING;
                            """, (
                                article["source"], article["headline"], article["url"],
                                article["url_hash"], article["published_at"],
                                article["description"], article["fetched_at"],
                            ))
                            added_tf += cur.rowcount
                print(f"TinyFish added {added_tf} new articles to the database.")
            else:
                print(" TinyFish found no new articles.")
    except Exception as error:
        print(f"TinyFish fallback failed: {error}")
    try:
        cleanup_old_news()
       


        with get_connection() as conn:
             
             with conn.cursor() as cur:
                     cur.execute("SELECT COUNT(*) FROM news_articles;")
                     total = cur.fetchone()[0]
        print(f"Articles remaining in database: {total}")
    except Exception as error:
        print(f"Cleanup or database check failed: {error}")


if __name__ == "__main__":
    setup_database()
    run_miner()

