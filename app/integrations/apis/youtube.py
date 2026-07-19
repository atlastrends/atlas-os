import os

def get_trends():
    trends = []
    api_key = os.getenv("YOUTUBE_API_KEY")
    if not api_key:
        return trends

    try:
        from googleapiclient.discovery import build
        youtube = build('youtube', 'v3', developerKey=api_key)
        request = youtube.videos().list(part="snippet,statistics", chart="mostPopular", regionCode="US", videoCategoryId="28", maxResults=5)
        response = request.execute()
        
        for item in response.get('items', []):
            views = int(item['statistics'].get('viewCount', 0))
            score = min(75 + (views / 100000), 99.0)
            trends.append({"topic": item['snippet']['title'], "score": round(score, 2), "source": "YouTube Trending"})
    except Exception as e:
        print(f"[YOUTUBE] Erro: {e}")
        
    return trends
