import json
import redis
import requests
import os
import time

print("✅ Jobs API worker starting")

REDIS_URL = os.getenv("REDIS_URL")
N8N_WEBHOOK = "https://n8n.cfpa.sekuirtek.com/webhook/c23ae223-ad7c-4eb5-9523-4365eccd7c03"

r = redis.Redis.from_url(REDIS_URL, decode_responses=True)

print("📥 Listening on Redis queue: jobs")

while True:
    try:
        _, payload = r.brpop("jobs")
        job = json.loads(payload)

        print("🚀 Job received:", job)

        try:
            resp = requests.post(N8N_WEBHOOK, json=job, timeout=5)
            print("✅ Sent job to n8n:", resp.status_code)
        except Exception as e:
            print("❌ Error sending to n8n:", e)

    except Exception as e:
        print("❌ Worker error:", e)
        time.sleep(2)
