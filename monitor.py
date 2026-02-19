import os
import requests

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

response = requests.post(url, json={
    "chat_id": CHAT_ID,
    "text": "TEST ✅ Botul funcționează corect."
})

print(response.text)
