
from ddgs import DDGS
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse




APPROVED_DOMAINS = {
    "coindesk.com",
    "cointelegraph.com",
    "theblock.co",
    "decrypt.co",
    "bitcoinmagazine.com",
    "cryptoslate.com",
    "blockworks.co",
    "thedefiant.io",
    "finance.yahoo.com",
    "benzinga.com",
}

def is_approved_domain(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()

    return any(
        host == domain or host.endswith("." + domain)
        for domain in APPROVED_DOMAINS
    )

def search_crypto_news(coin: str, max_results: int = 5):
    query =f"{coin} Lastes NES"

    try:
        with DDGS() as search:
            results = search.news(
       
                 query,
                 max_results=max_results,

                 timelimit ="d"

             )
        ##print("Raw search results:", results)
        cutoff = datetime.now(timezone.utc) - timedelta(hours= 30)

        filtered_results = []
        for item in results:
            title  = item.get("title","No Title")
            date_str = item.get("date")

            if not date_str:
                print(f"Rejected(NO DATA){title}")
                continue
            try:
                pub_date = datetime.fromisoformat(
                    date_str.replace("Z", "+00:00"
                    ))
                if pub_date.tzinfo is None:
                     pub_date = pub_date.replace(tzinfo=timezone.utc)
            except (ValueError ,TypeError):
                print(f"Reject (Invalid Date):{title}")
                continue
            if pub_date < cutoff:
                print(f" Reject(TOO  OLADER):{title}")
                print(f"Article date: {pub_date}")
                print(f"Cutoff date: {cutoff}")
                
                continue
            filtered_results.append(item
                                    )
        results = filtered_results
  
        results = [
            item for item in results
            if is_approved_domain(item.get("url", ""))
        ]
    

        return [
            {
                "title": item.get("title"),
                "url": item.get("url"),
                "source": item.get("source"),
                "date": item.get("date"),
                "body": item.get("body"),
            }
            for item in results
        ]

    except Exception as error:
        print(f"Search failed: {error}")
        return []

if __name__== "__main__":
    coin = input("Enter coin name (e.g. Bitcoin): ").strip()

    for article in search_crypto_news(coin):
        print(f"\nTitle: {article['title']}")
        print(f"Source: {article['source']}")
        print(f"Date: {article['date']}")
        print(f"URL: {article['url']}")
        print(f"Summary: {article['body']}")


    