import os
import sqlite3
import requests

ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN")
AD_ACCOUNT_ID = os.getenv("META_AD_ACCOUNT_ID")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

THRESHOLDS = [10, 20, 30]
DB_FILE = "alerts.db"


def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sent_alerts (
            ad_id TEXT NOT NULL,
            threshold INTEGER NOT NULL,
            PRIMARY KEY (ad_id, threshold)
        )
    """)
    conn.commit()
    conn.close()


def alert_already_sent(ad_id, threshold):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM sent_alerts WHERE ad_id = ? AND threshold = ?",
        (ad_id, threshold)
    )
    row = cur.fetchone()
    conn.close()
    return row is not None


def mark_alert_sent(ad_id, threshold):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO sent_alerts (ad_id, threshold) VALUES (?, ?)",
        (ad_id, threshold)
    )
    conn.commit()
    conn.close()


def get_action_value(actions, action_type):
    if not actions:
        return 0.0
    for action in actions:
        if action.get("action_type") == action_type:
            try:
                return float(action.get("value", 0))
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def get_roas_value(purchase_roas):
    if not purchase_roas:
        return 0.0
    try:
        return float(purchase_roas[0].get("value", 0))
    except (TypeError, ValueError, IndexError, KeyError):
        return 0.0


def get_cost_value(costs, action_type):
    if not costs:
        return 0.0
    for item in costs:
        if item.get("action_type") == action_type:
            try:
                return float(item.get("value", 0))
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def format_money(value):
    if not value:
        return "-"
    return f"€{value:.2f}"


def format_percent(value):
    return f"{value:.2f}%"


def get_ctr_status(ctr):
    if ctr < 1.5:
        return "🔴"
    if ctr < 2.5:
        return "🟠"
    return "🟢"


def get_cpc_status(cpc):
    if cpc >= 0.75:
        return "🔴"
    if cpc > 0.45:
        return "🟠"
    return "🟢"


def get_cpm_status(cpm):
    if cpm >= 10:
        return "🔴"
    if cpm > 6:
        return "🟠"
    return "🟢"


def get_advice(threshold, ctr, cpc, cpm, atc, purchases):
    if threshold == 10:
        if ctr < 1.5:
            return "❌ KILL", "❌ Advice: KILL", "Reason: CTR below 1.5% after ~€10 spend"
        if cpc >= 0.75:
            return "❌ KILL", "❌ Advice: KILL", "Reason: CPC is €0.75+"
        if cpm >= 10 and ctr < 1.5:
            return "❌ KILL", "❌ Advice: KILL", "Reason: high CPM and low CTR"
        if ctr >= 4:
            return "🔥 WINNER", "✅ Advice: KEEP RUNNING", "Reason: CTR above 4%"
        if ctr >= 2.5 and cpc <= 0.45 and cpm <= 6:
            return "🔥 WINNER", "✅ Advice: KEEP RUNNING", "Reason: strong early metrics"
        return "👀 WATCH", "👀 Advice: WATCH", "Reason: mixed early metrics"

    if threshold == 20:
        if atc == 0:
            return "❌ KILL", "❌ Advice: KILL", "Reason: €20 spend and no ATC"
        return "👀 WATCH", "✅ Advice: KEEP RUNNING", "Reason: ATC found before €20"

    if threshold == 30:
        if purchases == 0:
            return "❌ KILL", "❌ Advice: KILL", "Reason: €30 spend and no Purchase"
        return "🔥 WINNER", "✅ Advice: KEEP RUNNING", "Reason: Purchase found before €30"

    return "👀 WATCH", "👀 Advice: WATCH", "Reason: no clear signal"


def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message
    }
    response = requests.post(url, data=payload, timeout=30)
    response.raise_for_status()


def fetch_ads():
    url = f"https://graph.facebook.com/v19.0/{AD_ACCOUNT_ID}/insights"
    params = {
        "level": "ad",
        "fields": "ad_id,ad_name,spend,cpm,ctr,cpc,actions,purchase_roas,cost_per_action_type",
        "access_token": ACCESS_TOKEN
    }

    response = requests.get(url, params=params, timeout=60)
    print("REQUEST URL:", response.url)
    print("STATUS CODE:", response.status_code)
    print("RAW RESPONSE:", response.text)

    response.raise_for_status()

    data = response.json()
    if "error" in data:
        raise Exception(data["error"])

    return data.get("data", [])


def build_message(ad, threshold):
    ad_name = ad.get("ad_name", "Unknown ad")
    spend = float(ad.get("spend", 0) or 0)
    cpm = float(ad.get("cpm", 0) or 0)
    ctr_link = float(ad.get("ctr", 0) or 0)
    cpc_link = float(ad.get("cpc", 0) or 0)

    actions = ad.get("actions", [])
    costs = ad.get("cost_per_action_type", [])
    purchase_roas = ad.get("purchase_roas", [])

    atc = int(get_action_value(actions, "add_to_cart"))
    purchases = int(get_action_value(actions, "purchase"))
    cpa = get_cost_value(costs, "purchase")
    roas = get_roas_value(purchase_roas)

    ctr_icon = get_ctr_status(ctr_link)
    cpc_icon = get_cpc_status(cpc_link)
    cpm_icon = get_cpm_status(cpm)

    signal, advice_title, advice_reason = get_advice(
        threshold, ctr_link, cpc_link, cpm, atc, purchases
    )

    message = (
        f"🚨 €{threshold} SPEND ALERT\n\n"
        f"{signal}\n\n"
        f"📦 {ad_name}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Spend: €{spend:.2f}\n\n"
        f"{ctr_icon} CTR (link): {format_percent(ctr_link)}\n"
        f"{cpc_icon} CPC (link): {format_money(cpc_link)}\n"
        f"{cpm_icon} CPM: {format_money(cpm)}\n\n"
        f"🛒 ATC: {atc}\n"
        f"🛍️ Purchases: {purchases}\n"
        f"💸 CPA: {format_money(cpa)}\n"
        f"📊 ROAS: {'-' if roas == 0 else f'{roas:.2f}'}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{advice_title}\n"
        f"{advice_reason}"
    )

    return message


def main():
    if not all([ACCESS_TOKEN, AD_ACCOUNT_ID, TELEGRAM_TOKEN, CHAT_ID]):
        raise ValueError("One or more environment variables are missing.")

    init_db()
    ads = fetch_ads()

    for ad in ads:
        ad_id = ad.get("ad_id")
        if not ad_id:
            continue

        spend = float(ad.get("spend", 0) or 0)

        for threshold in THRESHOLDS:
            if spend >= threshold and not alert_already_sent(ad_id, threshold):
                message = build_message(ad, threshold)
                send_telegram_message(message)
                mark_alert_sent(ad_id, threshold)

    print("Script klaar.")


if __name__ == "__main__":
    main()
