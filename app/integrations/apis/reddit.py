import requests

def get_trends():
    trends = []
    try:
        url = "https://www.reddit.com/r/artificial+technology+Entrepreneur/hot.json?limit=10"
        headers = {"User-Agent": "AtlasOS/1.0"}
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            for post in data['data']['children']:
                post_data = post['data']
                if not post_data['stickied']: 
                    upvotes = post_data['ups']
                    score = min(70 + (upvotes / 500), 99.0)
                    trends.append({
                        "topic": post_data['title'][:100],
                        "score": round(score, 2),
                        "source": f"Reddit (r/{post_data['subreddit']})"
                    })
    except Exception as e:
        print(f"[REDDIT] Erro: {e}")
        
    return trends
