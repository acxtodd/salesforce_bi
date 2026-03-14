import requests
import json
import sys

API_URL = "https://kuspjg7e7e.execute-api.us-west-2.amazonaws.com/prod/answer"
API_KEY = "M3L9GKMhRs2j5e9KvD3Et6upEWtHUQHy7SgrvCSQ"
USER_ID = "005fk0000006rG9AAI"

payload = {
    "sessionId": "debug-session",
    "query": "Tell me about the big deal",
    "salesforceUserId": USER_ID,
    "topK": 8,
    "policy": {
        "require_citations": True,
        "max_tokens": 600,
        "temperature": 0.3
    }
}

headers = {
    "x-api-key": API_KEY,
    "Content-Type": "application/json"
}

print(f"Sending request to {API_URL}...")
try:
    response = requests.post(API_URL, json=payload, headers=headers, stream=True, timeout=30)
    print(f"Status Code: {response.status_code}")
    print(f"Headers: {response.headers}")
    
    print("\n--- Raw Response Body ---")
    # Read chunks and print them
    for chunk in response.iter_content(chunk_size=1024):
        if chunk:
            print(chunk.decode('utf-8'), end='')
    print("\n--- End of Response ---")

except Exception as e:
    print(f"Error: {e}")
