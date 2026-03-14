import os
import sqlite3
import requests

ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN")
AD_ACCOUNT_ID = os.getenv("META_AD_ACCOUNT_ID")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
CHANNEL_CHAT_ID = os.getenv("CHANNEL_CHAT_ID")

os.makedirs("/data", exist_ok=True)

THRESHOLDS = [10, 20, 30]
DB_FILE = "/data/alerts.db"


def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS sent_campaign_alerts (
            campaign_name TEXT NOT NULL,
            threshold INTEGER NOT NULL,
            PRIMARY KEY (campaign_name, threshold)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS ctr_history (
            ad_id TEXT PRIMARY KEY,
            ctr REAL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS sent_fatigue_alerts (
            ad_id TEXT PRIMARY KEY,
            last_drop REAL
        )
    """)

    conn.commit()
    conn.close()


def get_previous_ctr(ad_id):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT ctr FROM ctr_history WHERE ad_id = ?", (ad_id,))
    row = cur.fetchone()
    conn.close()
    return float(row[0]) if row else None


def save_ctr(ad_id, ctr):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO ctr_history (ad_id, ctr) VALUES (?, ?)",
        (ad_id, ctr)
    )
    conn.commit()
    conn.close()


def campaign_alert_already_sent(campaign_name, threshold):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM sent_campaign_alerts WHERE campaign_name = ? AND threshold = ?",
        (campaign_name, threshold)
    )
    row = cur.fetchone()
    conn.close()
    return row is not None


def mark_campaign_alert_sent(campaign_name, threshold):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO sent_campaign_alerts (campaign_name, threshold) VALUES (?, ?)",
        (campaign_name, threshold)
    )
    conn.commit()
    conn.close()


def fatigue_alert_already_sent(ad_id):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM sent_fatigue_alerts WHERE ad_id = ?",
        (ad_id,)
    )
    row = cur.fetchone()
    conn.close()
    return row is not None


def mark_fatigue_alert_sent(ad_id, drop):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO sent_fatigue_alerts (ad_id, last_drop) VALUES (?, ?)",
        (ad_id, drop)
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

    private_payload = {
        "chat_id": CHAT_ID,
        "text": message
    }
    requests.post(url, data=private_payload, timeout=30)

    if CHANNEL_CHAT_ID:
        channel_payload = {
            "chat_id": CHANNEL_CHAT_ID,
            "text": message
        }
        requests.post(url, data=channel_payload, timeout=30)


def fetch_campaigns():
    url = f"https://graph.facebook.com/v19.0/{AD_ACCOUNT_ID}/insights"
    params = {
        "level": "campaign",
        "date_preset": "today",
        "fields": "campaign_name,spend,cpm,ctr,cpc,actions,purchase_roas,cost_per_action_type",
        "access_token": ACCESS_TOKEN
    }

    response = requests.get(url, params=params, timeout=60)
    print("CAMPAIGN REQUEST URL:", response.url)
    print("CAMPAIGN STATUS CODE:", response.status_code)
    print("CAMPAIGN RAW RESPONSE:", response.text)

    response.raise_for_status()

    data = response.json()
    if "error" in data:
        raise Exception(data["error"])

    return data.get("data", [])


def fetch_ads():
    url = f"https://graph.facebook.com/v19.0/{AD_ACCOUNT_ID}/insights"
    params = {
        "level": "ad",
        "date_preset": "today",
        "fields": "campaign_name,ad_id,ad_name,spend,cpm,ctr,cpc,frequency,actions,purchase_roas,cost_per_action_type",
        "access_token": ACCESS_TOKEN
    }

    response = requests.get(url, params=params, timeout=60)
    print("AD REQUEST URL:", response.url)
    print("AD STATUS CODE:", response.status_code)
    print("AD RAW RESPONSE:", response.text)

    response.raise_for_status()

    data = response.json()
    if "error" in data:
        raise Exception(data["error"])

    return data.get("data", [])


def build_campaign_message(campaign, threshold):
    campaign_name = campaign.get("campaign_name", "Unknown campaign")
    spend = float(campaign.get("spend", 0) or 0)
    cpm = float(campaign.get("cpm", 0) or 0)
    ctr = float(campaign.get("ctr", 0) or 0)
    cpc = float(campaign.get("cpc", 0) or 0)

    actions = campaign.get("actions", [])
    costs = campaign.get("cost_per_action_type", [])
    purchase_roas = campaign.get("purchase_roas", [])

    atc = int(get_action_value(actions, "add_to_cart"))
    purchases = int(get_action_value(actions, "purchase"))
    cpa = get_cost_value(costs, "purchase")
    roas = get_roas_value(purchase_roas)

    ctr_icon = get_ctr_status(ctr)
    cpc_icon = get_cpc_status(cpc)
    cpm_icon = get_cpm_status(cpm)

    signal, advice_title, advice_reason = get_advice(
        threshold, ctr, cpc, cpm, atc, purchases
    )

    message = (
        f"🚨 €{threshold} CAMPAIGN SPEND ALERT\n\n"
        f"{signal}\n\n"
        f"📣 {campaign_name}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Spend: €{spend:.2f}\n\n"
        f"{ctr_icon} CTR (link): {format_percent(ctr)}\n"
        f"{cpc_icon} CPC (link): {format_money(cpc)}\n"
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


def build_fatigue_message(ad, drop):
    campaign_name = ad.get("campaign_name", "Unknown campaign")
    ad_name = ad.get("ad_name", "Unknown ad")
    frequency = float(ad.get("frequency", 0) or 0)

    return (
        f"⚠️ CREATIVE FATIGUE\n\n"
        f"📣 {campaign_name}\n"
        f"Creative: {ad_name}\n"
        f"CTR dropped {drop:.0f}%\n"
        f"Frequency: {frequency:.1f}\n"
        f"Recommendation: refresh creative"
    )


def main():
    if not all([ACCESS_TOKEN, AD_ACCOUNT_ID, TELEGRAM_TOKEN, CHAT_ID]):
        raise ValueError("One or more environment variables are missing.")

    init_db()

    campaigns = fetch_campaigns()
    ads = fetch_ads()

    # Campaign spend alerts
    for campaign in campaigns:
        print("CAMPAIGN FOUND:", campaign.get("campaign_name"), "| spend:", campaign.get("spend"))

        campaign_name = campaign.get("campaign_name")
        if not campaign_name:
            continue

        spend = float(campaign.get("spend", 0) or 0)

        for threshold in THRESHOLDS:
            if spend >= threshold and not campaign_alert_already_sent(campaign_name, threshold):
                message = build_campaign_message(campaign, threshold)
                send_telegram_message(message)
                mark_campaign_alert_sent(campaign_name, threshold)

    # Ad-level fatigue alerts
    for ad in ads:
        print("AD FOUND:", ad.get("campaign_name"), "|", ad.get("ad_name"), "| ad_id:", ad.get("ad_id"), "| spend:", ad.get("spend"))

        ad_id = ad.get("ad_id")
        if not ad_id:
            continue

        ctr_link = float(ad.get("ctr", 0) or 0)
        frequency = float(ad.get("frequency", 0) or 0)
        previous_ctr = get_previous_ctr(ad_id)

        if previous_ctr and previous_ctr > 0:
            drop = ((previous_ctr - ctr_link) / previous_ctr) * 100

            if drop >= 40 and frequency >= 2 and not fatigue_alert_already_sent(ad_id):
                fatigue_message = build_fatigue_message(ad, drop)
                send_telegram_message(fatigue_message)
                mark_fatigue_alert_sent(ad_id, drop)

        save_ctr(ad_id, ctr_link)

    print("Script klaar.")


if __name__ == "__main__":
    main()
