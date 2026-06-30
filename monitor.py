import requests
import os
import json
import time
import math
import tempfile
from datetime import datetime

API_KEY = os.getenv('TWELVE_DATA_API_KEY')

# Tickers are read from symbols.txt so you can change the watchlist
# without touching this code. This list is only a fallback if that
# file is missing.
DEFAULT_SYMBOLS = ['SPY', 'QQQ', 'AAPL', 'NVDA', 'MSFT']

SYMBOLS_FILE = 'symbols.txt'
HISTORY_FILE = 'data.json'
MAX_HISTORY = 50
REQUEST_DELAY = 8  # seconds between API calls (free tier ~8 req/min)
SMA_PERIOD = 200   # 200-day moving average for the long-term trend filter

# ---- Option-modeling assumptions (Black-Scholes) -------------------
# These drive the LEAPS call estimate + Greeks. They are ASSUMPTIONS,
# not live option-market data, so treat the output as a ballpark.
RISK_FREE_RATE = 0.04   # ~ annual risk-free rate
STRIKE_MONEYNESS = 1.0  # 1.0 = at-the-money. 0.90 = a 10%-in-the-money call, etc.
DEFAULT_IV = 0.30       # fallback implied vol when none is given and VIX is unknown
# --------------------------------------------------------------------


class APIError(Exception):
    """Raised when the Twelve Data API returns an error instead of data."""
    pass


# ====================================================================
#  Black-Scholes option pricing + Greeks
# ====================================================================
def _norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x):
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def black_scholes_call(S, K, T, r, sigma):
    """Price + Greeks for a European call (no dividends).
    Returns a dict. Greeks use trader conventions:
      - theta is PER DAY
      - vega is per 1 percentage-point change in IV
      - rho  is per 1 percentage-point change in rates
    """
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return None

    sqrt_t = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t

    price = S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
    delta = _norm_cdf(d1)
    gamma = _norm_pdf(d1) / (S * sigma * sqrt_t)
    vega_annual = S * _norm_pdf(d1) * sqrt_t
    theta_annual = (-(S * _norm_pdf(d1) * sigma) / (2 * sqrt_t)
                    - r * K * math.exp(-r * T) * _norm_cdf(d2))
    rho_annual = K * T * math.exp(-r * T) * _norm_cdf(d2)

    return {
        'price': round(price, 2),
        'delta': round(delta, 3),
        'gamma': round(gamma, 4),
        'theta': round(theta_annual / 365.0, 3),  # per day
        'vega': round(vega_annual / 100.0, 3),    # per 1% IV
        'rho': round(rho_annual / 100.0, 3),      # per 1% rate
    }


def leaps_horizon_months(drop_from_high):
    """Pick a LEAPS expiration (months) to match the drawdown signal."""
    if drop_from_high >= 30:
        return 24
    elif drop_from_high >= 20:
        return 18
    else:
        return 12


def nice_strike(value):
    """Round a strike to a sensible increment based on price magnitude."""
    if value >= 200:
        step = 5
    elif value >= 50:
        step = 1
    else:
        step = 0.5
    return round(round(value / step) * step, 2)


def model_option(current, drop_from_high, iv):
    """Build the LEAPS call estimate for one symbol."""
    months = leaps_horizon_months(drop_from_high)
    T = months / 12.0
    strike = nice_strike(current * STRIKE_MONEYNESS)
    greeks = black_scholes_call(current, strike, T, RISK_FREE_RATE, iv)
    if greeks is None:
        return None
    return {
        'type': f'{months}-month call',
        'strike': strike,
        'expiry_months': months,
        'iv': round(iv, 3),
        **greeks,  # price, delta, gamma, theta, vega, rho
    }


# ====================================================================
#  Watchlist + quotes
# ====================================================================
def load_symbols():
    """Read tickers (and optional IV) from symbols.txt.
    Each line: 'SYMBOL' or 'SYMBOL 0.45' (IV as a decimal, or a whole
    number of percent like 45). '#' comments and blank lines ignored.
    Returns a list of (symbol, iv_or_None)."""
    try:
        with open(SYMBOLS_FILE, 'r') as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"Note: {SYMBOLS_FILE} not found, using default watchlist.")
        return [(s, None) for s in DEFAULT_SYMBOLS]

    symbols = []
    seen = set()
    for line in lines:
        text = line.split('#', 1)[0].strip()
        if not text:
            continue
        parts = text.split()
        ticker = parts[0].upper()
        iv = None
        if len(parts) > 1:
            try:
                iv = float(parts[1])
                if iv > 3:      # someone wrote "45" meaning 45%
                    iv = iv / 100.0
            except ValueError:
                print(f"Warning: bad IV '{parts[1]}' for {ticker}, ignoring it.")
                iv = None
        if ticker and ticker not in seen:
            symbols.append((ticker, iv))
            seen.add(ticker)

    if not symbols:
        print(f"Note: {SYMBOLS_FILE} is empty, using default watchlist.")
        return [(s, None) for s in DEFAULT_SYMBOLS]
    return symbols


def fetch_quote(symbol):
    """Fetch a quote and return parsed JSON, raising APIError on any problem."""
    if not API_KEY:
        raise APIError("TWELVE_DATA_API_KEY environment variable is not set.")

    url = f'https://api.twelvedata.com/quote?symbol={symbol}&apikey={API_KEY}'
    try:
        r = requests.get(url, timeout=15)
    except requests.RequestException as e:
        raise APIError(f"Network error fetching {symbol}: {e}")

    if r.status_code != 200:
        raise APIError(f"HTTP {r.status_code} fetching {symbol}: {r.text[:200]}")

    try:
        data = r.json()
    except ValueError:
        raise APIError(f"Non-JSON response fetching {symbol}: {r.text[:200]}")

    if isinstance(data, dict) and data.get('status') == 'error':
        raise APIError(f"API error fetching {symbol}: {data.get('message', data)}")
    if 'close' not in data:
        raise APIError(f"Unexpected response fetching {symbol}: {data}")

    return data


def get_quote(symbol):
    """Return key metrics for a symbol as a dict."""
    data = fetch_quote(symbol)

    current = float(data['close'])
    prev_close = float(data['previous_close'])
    fifty_two_week_high = float(data['fifty_two_week']['high'])
    change_pct = ((current - prev_close) / prev_close) * 100
    drop_from_high = ((fifty_two_week_high - current) / fifty_two_week_high) * 100

    return {
        'current': current,
        'prev_close': prev_close,
        'change_pct': change_pct,
        'high_52w': fifty_two_week_high,
        'drop_from_high': drop_from_high,
    }


def get_sma(symbol, period=SMA_PERIOD):
    """Fetch the N-day simple moving average from Twelve Data's /sma endpoint.
    Returns a float, or None if unavailable (e.g. a young stock without
    enough history). Never raises — the trend filter is optional context."""
    if not API_KEY:
        return None
    url = (f'https://api.twelvedata.com/sma?symbol={symbol}'
           f'&interval=1day&time_period={period}&apikey={API_KEY}')
    try:
        r = requests.get(url, timeout=15)
        data = r.json()
    except (requests.RequestException, ValueError) as e:
        print(f"Warning: could not fetch {period}-day SMA for {symbol}: {e}")
        return None

    if isinstance(data, dict) and data.get('status') == 'error':
        print(f"Warning: SMA error for {symbol}: {data.get('message', data)}")
        return None

    try:
        return float(data['values'][0]['sma'])
    except (KeyError, IndexError, TypeError, ValueError):
        print(f"Warning: no {period}-day SMA data for {symbol}.")
        return None


def trend_status(current, sma):
    """Compare price to the 200-day SMA. Returns a dict describing the
    long-term trend, or None if the SMA is unavailable."""
    if sma is None or sma <= 0:
        return None
    pct_vs_sma = ((current - sma) / sma) * 100
    if current >= sma:
        label = f"✅ UPTREND — {pct_vs_sma:+.1f}% above 200-day avg. Dips are buyable."
        ok = True
    else:
        label = f"⛔ BELOW 200-DAY ({pct_vs_sma:+.1f}%) — trend may be broken. Higher risk."
        ok = False
    return {
        'sma200': round(sma, 2),
        'pct_vs_sma200': round(pct_vs_sma, 1),
        'above_sma200': ok,
        'label': label,
    }


def get_vix():
    """Return (vix_level, signal_text). Returns (None, None) on failure."""
    try:
        data = fetch_quote('VIX')
        vix = float(data['close'])
    except (APIError, KeyError, ValueError) as e:
        print(f"Warning: could not fetch VIX: {e}")
        return None, None

    if vix >= 30:
        return vix, "🔥 VIX HIGH — Premiums expensive, size down"
    elif vix >= 20:
        return vix, "⚠️ VIX ELEVATED — Good volatility for LEAPS entry"
    else:
        return vix, "✅ VIX LOW — Premiums cheap, good time to buy"


def pick_iv(symbol_iv, vix_level):
    """Choose the implied vol to model with: explicit > VIX proxy > default."""
    if symbol_iv is not None:
        return symbol_iv
    if vix_level is not None:
        return vix_level / 100.0
    return DEFAULT_IV


def analyze_leaps(daily_pct, drop_from_high):
    signals = []

    if daily_pct <= -10:
        signals.append(f"🚨 SINGLE DAY -{abs(daily_pct):.1f}% — MAJOR daily drop. Strong LEAPS entry.")
    elif daily_pct <= -5:
        signals.append(f"🚨 SINGLE DAY -{abs(daily_pct):.1f}% — Big daily drop. Watch for continuation.")
    elif daily_pct <= -3:
        signals.append(f"⚠️ DAILY -{abs(daily_pct):.1f}% — Notable drop. Monitor closely.")

    if drop_from_high >= 30:
        signals.append(f"🚨 DOWN {drop_from_high:.1f}% FROM HIGH — MAJOR opportunity. 2-year LEAPS.")
    elif drop_from_high >= 20:
        signals.append(f"🚨 DOWN {drop_from_high:.1f}% FROM HIGH — Strong entry. 18-month LEAPS.")
    elif drop_from_high >= 10:
        signals.append(f"⚠️ DOWN {drop_from_high:.1f}% FROM HIGH — Sweet spot. 12-month LEAPS.")
    elif drop_from_high >= 5:
        signals.append(f"📊 DOWN {drop_from_high:.1f}% FROM HIGH — Watch for more weakness.")

    return signals


# ====================================================================
#  Persistence
# ====================================================================
def load_history():
    try:
        with open(HISTORY_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return []
    except (json.JSONDecodeError, OSError) as e:
        print(f"Warning: could not read {HISTORY_FILE} ({e}). Starting fresh.")
        try:
            os.replace(HISTORY_FILE, HISTORY_FILE + '.corrupt')
        except OSError:
            pass
        return []


def save_data(entry):
    """Prepend an entry to history and write atomically."""
    history = load_history()
    history.insert(0, entry)
    history = history[:MAX_HISTORY]

    dir_name = os.path.dirname(os.path.abspath(HISTORY_FILE))
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(history, f, indent=2)
        os.replace(tmp_path, HISTORY_FILE)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


# ====================================================================
#  Main
# ====================================================================
def run():
    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    print(f"\n=== Market Check {now} ===")

    symbols = load_symbols()
    print(f"Watching: {', '.join(s for s, _ in symbols)}")

    vix_level, vix_signal = get_vix()
    print(f"VIX: {vix_level} — {vix_signal}")
    time.sleep(REQUEST_DELAY)

    results = []
    for symbol, symbol_iv in symbols:
        try:
            q = get_quote(symbol)
            time.sleep(REQUEST_DELAY)  # space the next call (SMA) under the limit
            sma = get_sma(symbol)
            trend = trend_status(q['current'], sma)

            signals = analyze_leaps(q['change_pct'], q['drop_from_high'])
            iv = pick_iv(symbol_iv, vix_level)
            option = model_option(q['current'], q['drop_from_high'], iv)

            print(f"\n{symbol}: ${q['current']:.2f} | Day: {q['change_pct']:.2f}% "
                  f"| From 52w High: -{q['drop_from_high']:.1f}%")
            if trend:
                print(f"  {trend['label']}")
            if option:
                print(f"  LEAPS {option['type']} @ ${option['strike']} "
                      f"(IV {option['iv']*100:.0f}%): est ${option['price']} | "
                      f"Δ{option['delta']} Γ{option['gamma']} "
                      f"Θ{option['theta']} V{option['vega']}")
            for s in signals:
                print(f"  {s}")

            results.append({
                'symbol': symbol,
                'price': round(q['current'], 2),
                'change_pct': round(q['change_pct'], 2),
                'drop_from_high': round(q['drop_from_high'], 1),
                'high_52w': round(q['high_52w'], 2),
                'signals': signals,
                'option': option,
                'trend': trend,
            })
        except APIError as e:
            print(f"Error fetching {symbol}: {e}")
        except (KeyError, ValueError, ZeroDivisionError) as e:
            print(f"Error parsing data for {symbol}: {e}")

        time.sleep(REQUEST_DELAY)

    entry = {
        'time': now,
        'vix': vix_level,
        'vix_signal': vix_signal,
        'data': results,
    }
    save_data(entry)
    print("\nDone.")


if __name__ == '__main__':
    run()
