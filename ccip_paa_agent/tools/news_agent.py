import os
import psycopg
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from tools.tinyfish import tiny_fish_serched
from tools.web_search import fetch_rss_news
from groq import Groq

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

groq_client = Groq(api_key=GROQ_API_KEY)
def save_to_database(articles):
    if not articles:
        return
    try:
        conn = psycopg.connect(DATABASE_URL, sslmode="require")
        cur = conn.cursor()
        for article in articles:
            cur.execute("""
       INSERT INTO news_articles (source, headline, url, url_hash, published_at, description, fetched_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (url_hash) DO NOTHING;
            """, (
                article["source"], article["headline"], article["url"],
                article["url_hash"], article["published_at"],
                article["description"], article["fetched_at"]
            ))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f" Failed to save: {e}")
        
def get_news_for_coin(coin: str):
    print(f" Searching database for news about {coin}...")
    conn = psycopg.connect(DATABASE_URL, sslmode="require")
    cur = conn.cursor()
    
    cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=60)
    if not rows:
         print(f"NO news Found in DATA base{coin}.Triggering TinyFish....")
    query = """
        SELECT headline, description, source ,url
        FROM news_articles 
        WHERE (headline ILIKE %s OR description ILIKE %s)
        AND published_at >= %s
        ORDER BY published_at DESC 
        LIMIT 10;
    """
    search_term = f"%{coin}%"
    
    cur.execute(query, (search_term, search_term, cutoff_time))
    rows = cur.fetchall()
    
    cur.close()
    conn.close()
    
    return rows

def explain_market_move(coin: str, price_change: float):
    news_items = get_news_for_coin(coin)
    
    if not news_items:
        return f"{coin} moved {price_change}%, but we found no specific news in the last 60 minutes."

    news_text = ""
    for item in news_items:
        headline, description, source = item
        news_text += f"- Source: {source} | Headline: {headline}\n  Summary: {description}\n"

    print(f"Asking Groq AI to analyze {len(news_items)} articles...")
    
    prompt = f"""
    You are CryptoGuardian, an expert crypto analyst.
    The coin {coin} just moved {price_change}%.
    Here is ALL the news from the last 60 minutes:
    
    {news_text}
    
    Read through all the news above. Write a short, 2-sentence explanation 
    for the user explaining WHY {coin} likely moved based on the overall context.
    If the news doesn't clearly explain the move, be honest and say it might be general market volatility.
    """

    response = groq_client.chat.completions.create(
        messages=[
            {"role": "system", "content": "You are a concise, professional crypto market analyst."},
            {"role": "user", "content": prompt}
        ],
        model="llama3-8b-8192", 
        temperature=0.3,
        max_tokens=200 
    )
    
    return response.choices[0].message.content

if __name__ == "__main__":
    coin = input("Enter a coin name to test (e.g., Bitcoin): ")
    explanation = explain_market_move(coin, price_change=-3.5)
    print("\n" + "="*50)
    print(explanation)
    print("="*50)