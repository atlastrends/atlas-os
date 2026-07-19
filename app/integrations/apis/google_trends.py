import feedparser

def get_trends():
    trends = []
    try:
        url = "https://trends.google.com/trends/trendingsearches/daily/rss?geo=US"
        feed = feedparser.parse(url)
        
        for i, entry in enumerate(feed.entries[:5]):
            score = 95.0 - (i * 2.0)
            trends.append({
                "topic": entry.title,
                "score": score,
                "source": "Google Trends US"
            })
    except Exception as e:
        print(f"[GOOGLE TRENDS] Erro: {e}")
    
    return trends
