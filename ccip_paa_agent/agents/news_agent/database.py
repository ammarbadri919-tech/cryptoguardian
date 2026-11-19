
import os
import psycopg

from dotenv import load_dotenv
from agents.news_agent.schemas import NewsArticle

load_dotenv()


class NewsDatabase:

    def __init__(self):
        self.database_url = os.getenv("DATABASE_URL")

        if not self.database_url:
            raise ValueError("DATABASE_URL missing from .env")

    def fetch_latest_news(self, limit=50):

        query = """
            SELECT
                id,
                source,
                headline,
                url,
                published_at,
                description,
                fetched_at
            FROM news_articles
            ORDER BY fetched_at DESC
            LIMIT %s;
        """

        with psycopg.connect(
            self.database_url,
            sslmode="require"
        ) as conn:

            with conn.cursor() as cursor:
                cursor.execute(query, (limit,))
                rows = cursor.fetchall()

        return [NewsArticle(*row) for row in rows]

    def fetch_news_by_coin(self, coin_name, symbol, limit=20):

        query = """
            SELECT
                na.id,
                na.source,
                na.headline,
                na.url,
                na.published_at,
                na.description,
                na.fetched_at
            FROM news_articles AS na
            JOIN news_article_coins AS nac
                ON na.id = nac.article_id
            WHERE LOWER(nac.coin_name) = LOWER(%s)
              AND UPPER(nac.symbol) = UPPER(%s)
            ORDER BY na.published_at DESC NULLS LAST,
                     na.fetched_at DESC
            LIMIT %s;
        """

        with psycopg.connect(
            self.database_url,
            sslmode="require"
        ) as conn:

            with conn.cursor() as cursor:
                cursor.execute(
                    query,
                    (coin_name, symbol, limit)
                )
                rows = cursor.fetchall()

        return [NewsArticle(*row) for row in rows]
