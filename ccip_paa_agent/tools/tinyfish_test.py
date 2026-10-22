from tools.tinyfish import tiny_fish_serched

QUERIES = [
    "Bitcoin latest news and ETF flows",
    "Ethereum and Solana latest news",
    "Crypto market liquidations and funding rates",
    "Crypto hacks and DeFi security incidents",
    "Crypto regulation and ETF approvals",
    "Stablecoin and institutional crypto news",
]

seen_urls = set()
total = 0

for query in QUERIES:
    print(f"\n{'=' * 50}")
    print(f"SEARCHING: {query}")
    print("=" * 50)

    results = tiny_fish_serched(query, max_results=20)

    if not results.strip():
        print("No matching results for this query.")
        continue

    for article in results.split("\n\n"):
        if not article.strip():
            continue

        url_line = next(
            (
                line for line in article.splitlines()
                if line.startswith("URL: ")
            ),
            None,
        )

        if not url_line:
            continue

        url = url_line.removeprefix("URL: ").strip()

        if url in seen_urls:
            continue

        seen_urls.add(url)
        total += 1
        print(article)

print(f"\nUnique articles collected: {total}")