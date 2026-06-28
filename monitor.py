import requests
import os
import json
from datetime import datetime

API_KEY = os.getenv('TWELVE_DATA_API_KEY')
SYMBOLS = ['SPY', 'QQQ', 'AAPL', 'NVDA', 'MSFT', 'ORLY', 'SPYM', 'SMH', 'NEE', 'LLY', 'CAT' ]

def get_quote(symbol):
   url = f'https://api.twelvedata.com/quote?symbol={symbol}&apikey={API_KEY}'
   r = requests.get(url)
   data = r.json()
   current = float(data['close'])
   prev_close = float(data['previous_close'])
   fifty_two_week_high = float(data['fifty_two_week']['high'])
   change_pct = ((current - prev_close) / prev_close) * 100
   drop_from_high = ((fifty_two_week_high - current) / fifty_two_week_high) * 100
   return current, prev_close, change_pct, fifty_two_week_high, drop_from_high

def get_iv(symbol):
   # Use VIX as IV proxy for SPY, flag when elevated
   if symbol == 'SPY':
       url = f'https://api.twelvedata.com/quote?symbol=VIX&apikey={API_KEY}'
       r = requests.get(url)
       data = r.json()
       vix = float(data['close'])
       if vix >= 30:
           return vix, "🔥 VIX HIGH — Premiums expensive, size down"
       elif vix >= 20:
           return vix, "⚠️ VIX ELEVATED — Good volatility for LEAPS entry"
       else:
           return vix, "✅ VIX LOW — Premiums cheap, good time to buy"
   return None, None

def analyze_leaps(daily_pct, drop_from_high):
   signals = []

   # Daily drop signals
   if daily_pct <= -10:
       signals.append(f"🚨 SINGLE DAY -{abs(daily_pct):.1f}% — MAJOR daily drop. Strong LEAPS entry.")
   elif daily_pct <= -5:
       signals.append(f"🚨 SINGLE DAY -{abs(daily_pct):.1f}% — Big daily drop. Watch for continuation.")
   elif daily_pct <= -3:
       signals.append(f"⚠️ DAILY -{abs(daily_pct):.1f}% — Notable drop. Monitor closely.")

   # Cumulative drop from 52-week high signals
   if drop_from_high >= 30:
       signals.append(f"🚨 DOWN {drop_from_high:.1f}% FROM HIGH — MAJOR opportunity. 2-year LEAPS.")
   elif drop_from_high >= 20:
       signals.append(f"🚨 DOWN {drop_from_high:.1f}% FROM HIGH — Strong entry. 18-month LEAPS.")
   elif drop_from_high >= 10:
       signals.append(f"⚠️ DOWN {drop_from_high:.1f}% FROM HIGH — Sweet spot. 12-month LEAPS.")
   elif drop_from_high >= 5:
       signals.append(f"📊 DOWN {drop_from_high:.1f}% FROM HIGH — Watch for more weakness.")

   return signals

def load_history():
   try:
       with open('data.json', 'r') as f:
           return json.load(f)
   except:
       return []

def save_data(results):
   history = load_history()
   history.insert(0, {
       'time': datetime.now().strftime('%Y-%m-%d %H:%M'),
       'data': results
   })
   history = history[:50]
   with open('data.json', 'w') as f:
       json.dump(history, f)

def run():
   now = datetime.now().strftime('%Y-%m-%d %H:%M')
   print(f"\n=== Market Check {now} ===")

   results = []

   # Get VIX first
   vix_level, vix_signal = get_iv('SPY')
   print(f"VIX: {vix_level} — {vix_signal}")

   for symbol in SYMBOLS:
       try:
           current, prev_close, change_pct, high_52w, drop_from_high = get_quote(symbol)
           signals = analyze_leaps(change_pct, drop_from_high)

           print(f"\n{symbol}: ${current:.2f} | Day: {change_pct:.2f}% | From 52w High: -{drop_from_high:.1f}%")
           for s in signals:
               print(f"  {s}")

           results.append({
               'symbol': symbol,
               'price': round(current, 2),
               'change_pct': round(change_pct, 2),
               'drop_from_high': round(drop_from_high, 1),
               'high_52w': round(high_52w, 2),
               'signals': signals,
               'vix': vix_level,
               'vix_signal': vix_signal
           })
       except Exception as e:
           print(f"Error fetching {symbol}: {e}")

   save_data(results)
   print("\nDone.")

run()
