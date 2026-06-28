import requests
import os
import json
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
       return "30%+ DROP — MAJOR opportunity. Buy 2-year LEAPS."
   elif abs(drop_pct) >= 20:
       return "20%+ DROP — Strong entry. 18-month LEAPS."
   elif abs(drop_pct) >= 10:
       return "10%+ DROP — Sweet spot. 12-month LEAPS."
   elif abs(drop_pct) >= 5:
       return "5%+ DROP — Quick trade. 6-month LEAPS."
   return None

def save_data(current, change_pct, alert):
   try:
       with open('data.json', 'r') as f:
           history = json.load(f)
   except:
       history = []

   history.insert(0, {
       'time': datetime.now().strftime('%Y-%m-%d %H:%M'),
       'price': round(current, 2),
       'change_pct': round(change_pct, 2),
       'alert': alert
   })

   history = history[:50]

   with open('data.json', 'w') as f:
       json.dump(history, f)

def run():
   current, prev_close, change_pct = get_quote()
   now = datetime.now().strftime('%Y-%m-%d %H:%M')
   print(f"[{now}] SPY: ${current:.2f} | Change: {change_pct:.2f}%")

   alert = None
   if change_pct < 0:
       alert = analyze_leaps(change_pct)

   if alert:
       print(f"ALERT: {alert}")

   save_data(current, change_pct, alert)

run()
