import os
from dotenv import load_dotenv
from tinyfish import TinyFish
from urllib.parse import urlparse

# Load the key from your .env file
load_dotenv()

# Initialize the client
client = TinyFish(
    api_key=os.getenv("TINYFISH_API_KEY")
)

APPROVED_DOMAINS = [
    # Crypto news
    "coindesk.com",
    "cointelegraph.com",
    "theblock.co",
    "decrypt.co",
    "bitcoinmagazine.com",
    "blockworks.co",
    "cryptoslate.com",
    "dlnews.com",
    "cryptobriefing.com",
    "beincrypto.com",
    "cryptopotato.com",
    "cryptopolitan.com",
    "u.today",
    "dailyhodl.com",
    "protos.com",
    "bitcoin.com",
    "ambcrypto.com",
    "cryptonews.com",
    "coinpedia.org",

    # Market data and derivatives
    "coingecko.com",
    "coinmarketcap.com",
    "coinglass.com",
    "cryptoquant.com",
    "glassnode.com",
    "messari.io",
    "defillama.com",
    "coinalyze.net",
    "farside.co.uk",
    "sosovalue.com",

    # Security and on-chain investigations
    "chainalysis.com",
    "slowmist.com",
    "peckshield.com",
    "certik.com",
    "trmlabs.com",

    # Exchanges and official announcements
    "binance.com",
    "coinbase.com",
    "kraken.com",
    "okx.com",
    "ethereum.org",
    "blog.ethereum.org",
    "solana.com",
    "ripple.com",
    "blog.chain.link",
    "circle.com",
    "tether.to",

    # Regulation and broader financial news
    "sec.gov",
    "cftc.gov",
    "reuters.com",
    "cnbc.com",
    "finance.yahoo.com",
]




FOREIGN_PATHS = [
    "/pl/", "/ja/", "/kr/", "/ko/", "/id/", "/uz/",
    "/es/", "/fr/", "/de/", "/pt/", "/pt-br/",
    "/it/", "/ru/", "/tr/", "/vi/", "/zh/",
    "/th/", "/nl/", "/ar/",
]

CRYPTO_TERMS = [
    "bitcoin", "btc", "ethereum", "crypto", "cryptocurrency",
    "blockchain", "defi", "web3", "solana", "xrp",
    "dogecoin", "altcoin", "stablecoin", "token",
    "coinbase", "binance", "okx", "crypto exchange",
    "digital asset", "on-chain", "liquidation",
    "crypto etf", "bitcoin etf", "ethereum etf",
    "crypto hack", "wallet", "mining", "staking",
]


JUNK_WORDS=["stock", "earnings", "transcript", "bancorp", "inc.", "corp."]
def is_approved_domain(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == domain or host.endswith("." + domain) for domain in APPROVED_DOMAINS)


def tiny_fish_serched(query, max_results=60):
    try:
        response = client.search.query(
            query=query,
            purpose="find recent, relevant crypto market news for me",
           # include_domains=",".join(sorted(APPROVED_DOMAINS)),
           recency_minutes=60,
            # Restrict results to news sources/content rather than other page types.
            domain_type="news",
            language="en",
        )
        print("Total results reported:", getattr(response, "total_results", "unknown"))
        print("Results on this page:", len(response.results))
      #  print("Current page:", getattr(response, "page", "not provided"))



        
      ##  if response.results:
        ##     print("RESULT TYPE:", type(response.results[0]))
          ##   print("RESULT FIELDS:", response.results[0])
      #  else:
       #     print("NP SERCHED RESULTED")

        

        results = []
        for i, r in enumerate(response.results, start=1):

            title = getattr(r, "title", "Unknown")
            url = getattr(r, "url", "")
            ##content = getattr(r, "content", "") or getattr(r, "snippet", "")
            content = (getattr(r, "content", "") or getattr(r, "snippet", "") or getattr(r, "description", ""))
            print("DEBUGGING RESULT OBJECT:", r)



            if not is_approved_domain(url):
                print(f"reject (bad Doamin){title}")
                continue
            path = urlparse(url).path.lower()

            if any(word in title.lower() for word in JUNK_WORDS):
                print(f"REJECT(Junk):{title}")
                continue

            if any(prefix in path for prefix in  FOREIGN_PATHS):



                print(f"REJECT(FOREIGH Languge):{title}")
                continue

            text = f"{title} {content}".lower()
            if not any(term in text for term in CRYPTO_TERMS):
                print(f"Reject (NON): {title}")
                continue

            print(f"Keep: {title}")
            results.append(
                f"{i}. {title}\n"
                f"URL: {url}\n"
                f"Content: {content}"
            )

        return "\n\n".join(results)
    except Exception as e:
        print(f"Search failed: {e}")
        return ""
