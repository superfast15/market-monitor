import requests
import os
from datetime import datetime

API_KEY = os.getenv('TWELVE_DATA_API_KEY')
SYMBOL = 'SPY'

def get_quote():
    url = f'https://api.twelvedata.com/quote?symbol={SYMBOL}&apikey={API_KEY}'
    r = requests.get(url)
    data = r.json()
    current = float(data['close'])
    prev_close = float(data['previous_close'])
    change_pct = ((current - prev_close) / prev_close) * 100
    return current, prev_close, change_pct

def analyze_leaps(drop_pct):
    if abs(drop_pct) >= 30:
        return "30%+ DROP — MAJOR opportunity. Buy 2-year LEAPS. Watch IV carefully."
    elif abs(drop_pct) >= 20:
        return "20%+ DROP — Strong entry. 18-month LEAPS. Fast bounce likely."
    elif abs(drop_pct) >= 10:
        return "10%+ DROP — Sweet spot. 12-month LEAPS. High probability bounce."
    elif abs(drop_pct) >= 5:
        return "5%+ DROP — Quick trade. 6-month LEAPS. Watch for fast premium pop."
    return None

def run():
    current, prev_close, change_pct = get_quote()
    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    print(f"\n[{now}] SPY: ${current:.2f} | Change: {change_pct:.2f}%")
    analysis = analyze_leaps(change_pct)
    if analysis and change_pct < 0:
        print(f"ALERT: {analysis}")
        with open('alerts.log', 'a') as f:
            f.write(f"[{now}] SPY ${current:.2f} | {change_pct:.2f}% | {analysis}\n")
    else:
        print("No action needed. Market stable.")

run()
