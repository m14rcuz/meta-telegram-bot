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

# Debug naar logs
print("META RESPONSE:", data)

# Stop netjes als Meta een error terugstuurt
if "error" in data:
    print("META ERROR:", data["error"])
    raise Exception(data["error"])

ads = data.get("data", [])

for ad in ads:
    ad_name = ad.get("ad_name", "Unknown")
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
            if action.get("action_type") == "add_to_cart":
                atc = action.get("value", 0)
            if action.get("action_type") == "purchase":
                purchases = action.get("value", 0)

    if "cost_per_action_type" in ad:
        for action in ad["cost_per_action_type"]:
            if action.get("action_type") == "purchase":
                cpa = action.get("value", 0)

    if "purchase_roas" in ad and len(ad["purchase_roas"]) > 0:
        roas = ad["purchase_roas"][0].get("value", 0)

    if spend >= 0.1:
        message = f"""🚨 Spend Alert

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

print("Script klaar zonder crash.")
