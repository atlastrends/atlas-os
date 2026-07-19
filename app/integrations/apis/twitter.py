import os

def get_trends():
    trends = []
    bearer_token = os.getenv("TWITTER_BEARER_TOKEN")
    if not bearer_token:
        return trends

    try:
        import tweepy
        client = tweepy.Client(bearer_token=bearer_token)
        response = client.get_place_trends(23424977)
        if response.data:
            for i, trend in enumerate(response.data[0]['trends'][:5]):
                score = 90.0 - (i * 1.5)
                trends.append({"topic": trend['name'], "score": round(score, 2), "source": "X (Twitter) US"})
    except Exception as e:
        print(f"[TWITTER] Erro: {e}")
        
    return trends
