
from pathlib import Path

from tools.news_monitor import (
    run_news_collection,
    load_coins,
)

from agents.news_agent.database import NewsDatabase


class NewsAgent:

    def __init__(self):
        self.database = NewsDatabase()

    def run(self, csv_path):
        """Collect and retrieve news for coins in an uploaded CSV."""

        csv_file = Path(csv_path)

        if not csv_file.is_file():
            raise FileNotFoundError(
                f"Uploaded CSV not found: {csv_file}"
            )

        print("\n========== CRYPTOGUARDIAN NEWS AGENT ==========")

        # 1. Read uploaded coins
        coins = load_coins(csv_file)

        print(f"\nSelected coins: {len(coins)}")

        # 2. Run existing RSS + TinyFish collection pipeline
        run_news_collection(str(csv_file))

        # 3. Retrieve news for each uploaded coin
        results = {}

        for coin in coins:
            name = coin["coin_name"]
            symbol = coin["symbol"]

            articles = self.database.fetch_news_by_coin(
                name,
                symbol,
                limit=20,
            )

            results[symbol] = [
                article.to_dict() for article in articles
            ]

            print(f"\n========== {name} ({symbol}) ==========")

            if not articles:
                print("No news found.")
                continue

            for article in articles:
                print(f"Headline: {article.headline}")
                print(f"Source: {article.source}")
                print(f"Published: {article.published_at}")
                print(f"Original link: {article.url}")
                print("-" * 70)

        return results


if __name__ == "__main__":
    from tools.news_monitor import run_miner

    run_miner("selected_coins.csv")

