from tavily import TavilyClient
import os
from dotenv import load_dotenv
load_dotenv()

import re
from tavily import TavilyClient
import os
import re
import feedparser
import hashlib
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

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
def clean_news_text(text):
    # Remove common website clutter
    text = re.sub(r"(?im)^By\s+.+$", "", text)
    text = re.sub(r"(?im)^Published\s+.+$", "", text)
    text = re.sub(r"(?im)^The Crypto Desk.*$", "", text)
    text = re.sub(r"(?im)^This post may contain links.*$", "", text)

    # Remove repeated whitespace and blank lines
    text = re.sub(r"\n{2,}", "\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)

    return text.strip()


client = TavilyClient(
    api_key=os.getenv("TAVILY_API_KEY")) 

def  tavily_serch(query):
    response = client.search(
        query=query,
        topic ="news", 
        days=1,
        include_domans=[  "coindesk.com",
    "cointelegraph.com",
    "theblock.co",
    "decrypt.co", ],
        include_answer=False,
        max_results = 10
    )
    results = []
    for i, r in enumerate(response.get("results", []), start=1):
        title = r.get("title", "")
        url = r.get("url", "")
        snippet = r.get("content","")
        published_at = (r.get("published_date") or r.get("published_at") or "Time unavailable")
        

        if len(snippet) > 400:
            snippet = snippet[:400].rsplit(" ", 1)[0] + "..."
        results.append(f"{i}._ {title}\nURL: {url}\n published_at: {published_at}\n {snippet}\n") 
    return "\n".join(results)                                                


def read_article(url):
    response = client.extract(urls=[url])

    for article in response.get("results",[]):
        content = article.get("raw_content", "")

        if content:
            return content
    return "Article content not found."