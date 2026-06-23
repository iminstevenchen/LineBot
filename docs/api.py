import requests
resp = requests.post(
    "https://vatican-westminster-author-april.trycloudflare.com/api/chat",
    json={"message": "你好"},
    timeout=180,
)
print(resp.json()["answer"])
