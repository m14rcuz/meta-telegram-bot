import os
import requests

ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN")
AD_ACCOUNT_ID = os.getenv("META_AD_ACCOUNT_ID")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

url = f"https://graph.facebook.com/v19.0/{AD_ACCOUNT_ID}/insights"

params = {
    "level": "ad",
    "fields": "ad_name,spend,cpm,ctr,cpc,actions,purchase_roas,cost_per_action_type",
    "access_token": ACCESS_TOKEN
}

response = requests.get(url, params=params)
data = response.json()

for ad in data["data"]:

    ad_name = ad.get("ad_name")
    spend = float(ad.get("spend", 0))
    cpm = ad.get("cpm", 0)

    ctr = ad.get("ctr", 0)
    cpc = ad.get("cpc", 0)

    purchases = 0
    atc = 0
    cpa = 0
    roas = 0

    if "actions" in ad:
        for action in ad["actions"]:
            if action["action_type"] == "add_to_cart":
                atc = action["value"]
            if action["action_type"] == "purchase":
                purchases = action["value"]

    if "cost_per_action_type" in ad:
        for action in ad["cost_per_action_type"]:
            if action["action_type"] == "purchase":
                cpa = action["value"]

    if "purchase_roas" in ad:
        roas = ad["purchase_roas"][0]["value"]

    if spend >= 0.1:

        message = f"""
🚨 Spend Alert

Ad: {ad_name}

Spend: €{spend}
CTR (link): {ctr}
CPC (link): €{cpc}
CPM: €{cpm}

ATC: {atc}
Purchases: {purchases}
CPA: €{cpa}
ROAS: {roas}
"""

        telegram_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

        requests.post(telegram_url, data={
            "chat_id": CHAT_ID,
            "text": message

        })
