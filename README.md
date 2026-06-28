# Market Monitor

A lightweight LEAPS-signal monitor. It checks a watchlist of stocks/ETFs a few
times each trading day, flags meaningful pullbacks (single-day drops and drops
from the 52-week high), estimates a long-dated call option for each name with
its Greeks, and publishes everything to a simple web dashboard. It runs for free
on GitHub Actions and GitHub Pages — no server to maintain.

> **Not financial advice.** The signals are fixed rules of thumb, and the option
> numbers are *modeled estimates*, not live market quotes. See
> [Limitations](#limitations--honest-caveats) before relying on any of it.

---

## What's in the repo

| File | What it does |
|------|--------------|
| `monitor.py` | The script. Reads the watchlist, fetches quotes, builds signals + option estimates, writes `data.json`. |
| `symbols.txt` | **The file you edit.** Your watchlist, one ticker per line (with optional implied volatility). |
| `index.html` | The dashboard. Reads `data.json` and displays each ticker, its signals, and its option/Greeks. |
| `.github/workflows/market-monitor.yml` | The schedule. Runs `monitor.py` automatically and commits the new `data.json`. |
| `data.json` | Created automatically on the first run. The rolling history (latest 50 checks). |

---

## One-time setup

### 1. Add the files
Place them in this structure (the workflow **must** live in `.github/workflows/`):

```
market-monitor/
├── monitor.py
├── symbols.txt
├── index.html
└── .github/
    └── workflows/
        └── market-monitor.yml
```

> If you already pushed an older `monitor.py`/`index.html`, replace them with the
> current versions and add `symbols.txt`. Delete any leftover `market_check.py`.

### 2. Add your API key as a secret
The script reads your [Twelve Data](https://twelvedata.com) key from a GitHub
secret so it's never in the code.

**Settings → Secrets and variables → Actions → New repository secret**

Name it exactly:

```
TWELVE_DATA_API_KEY
```

Paste your key as the value and save.

### 3. Allow the workflow to save data
The job commits `data.json` back to the repo, so it needs write access.

**Settings → Actions → General → Workflow permissions → Read and write permissions → Save**

### 4. Run it once by hand
**Actions tab → Market Monitor → Run workflow.** When it finishes green, a
`data.json` file should appear in the repo. After this it runs automatically on
the schedule. If a step fails, click it to read the error (usually a secret-name
typo or write permission not enabled).

### 5. Turn on the dashboard (GitHub Pages)
**Settings → Pages → Source: Deploy from a branch → `main` / `/ (root)` → Save.**

Your dashboard goes live at:

```
https://<your-username>.github.io/<repo-name>/
```

(For this repo that's `https://superfast15.github.io/market-monitor/`.)

> Pages is free for **public** repos. The dashboard shows "waiting for first run"
> until `data.json` exists, so do step 4 first.

---

## Changing what it watches — `symbols.txt`

This is the only file you need to touch day to day. One ticker per line:

```
SPY
QQQ
AAPL  0.28
NVDA  0.50
```

- **Add a stock:** type its ticker on a new line.
- **Remove one:** delete the line, or put `#` in front of it.
- **Blank lines and `#` comments** are ignored.
- Tickers are not case-sensitive.

### The optional IV number
The number after a ticker (e.g. `NVDA 0.50`) is the **implied volatility** used to
price that name's option, as a decimal (`0.50` = 50%). It's optional — leave it off
and the script falls back to the current VIX level, then to a 30% default.

Because IV is the biggest driver of the option estimate, it's worth setting by
hand for individual stocks (which are more volatile than the index). Rough
ballparks:

| Type | Typical IV |
|------|-----------|
| Broad-market ETFs (SPY, QQQ) | 0.12 – 0.20 |
| Large, stable stocks | 0.20 – 0.30 |
| Hot / volatile names | 0.40 – 0.70 |

---

## How the signals work

For each ticker the script compares today's price to the previous close and to
the 52-week high, and emits plain-language flags:

**Single-day drop:** −3% (monitor), −5% (watch for continuation), −10% (major).

**Drop from 52-week high:** −5% (watch), −10% (12-month LEAPS), −20% (18-month),
−30% (24-month).

It also pulls the **VIX** once per run as a market-wide volatility gauge
(low / elevated / high).

> These thresholds are heuristics, not backtested signals. A stock can be far off
> its high and keep falling. Treat the output as "here's what dropped," not "buy this."

---

## How the option + Greeks work

For each ticker the script models a single **long call LEAPS**:

- **Strike:** at-the-money by default (tunable — see constants below).
- **Expiration:** matched to the drawdown signal — 12, 18, or 24 months out.
- **Pricing:** the [Black-Scholes](https://en.wikipedia.org/wiki/Black%E2%80%93Scholes_model)
  formula, using the live stock price, the chosen strike/expiration, the
  risk-free rate, and the implied volatility from `symbols.txt`.

The dashboard shows the estimated price plus the Greeks:

| Greek | Meaning (for a long call) |
|-------|---------------------------|
| **Delta** | How much the option moves per $1 move in the stock (≈ probability of finishing in-the-money). |
| **Gamma** | How fast Delta changes as the stock moves. |
| **Theta** | Daily time decay — what you lose per day, all else equal. |
| **Vega** | Sensitivity to a 1-point change in implied volatility. |
| **Rho** | Sensitivity to a 1-point change in interest rates. |

### Tunable constants (top of `monitor.py`)
```python
RISK_FREE_RATE  = 0.04   # annual risk-free rate assumption
STRIKE_MONEYNESS = 1.0   # 1.0 = at-the-money; 0.90 = a 10% in-the-money call
DEFAULT_IV      = 0.30   # fallback IV when none is set and VIX is unavailable
```

---

## Schedule

The workflow runs Monday–Friday at four times (cron is in **UTC**):

| Cron (UTC) | Approx. ET (summer / EDT) |
|------------|---------------------------|
| `30 13 * * 1-5` | ~9:30 am — market open |
| `0 16 * * 1-5`  | ~12:00 pm — midday |
| `30 18 * * 1-5` | ~2:30 pm — afternoon |
| `0 20 * * 1-5`  | ~4:00 pm — market close |

You can also trigger a run anytime from **Actions → Market Monitor → Run workflow**.

---

## Limitations & honest caveats

- **Not financial advice.** This is a personal monitoring tool. Do your own
  research and size positions responsibly.
- **The Greeks are estimates, not quotes.** Black-Scholes assumes constant
  volatility, no dividends, and European exercise — none of which hold exactly for
  real LEAPS. The price and Greeks your broker shows *will* differ, especially on
  volatile names or when the IV assumption is off. Use these as a planning sketch.
- **Signal thresholds are heuristics.** They are not backtested and carry no edge
  on their own.
- **Daylight saving drift.** GitHub cron is fixed UTC and does not adjust for US
  daylight saving. The times above line up with the US market in summer (EDT); in
  winter (EST) they fire one hour earlier in ET.
- **Scheduled runs aren't precise.** GitHub may delay scheduled Actions by several
  minutes (or rarely skip one) during heavy load. Fine for periodic checks; don't
  rely on a reading at the exact closing bell.
- **API limits.** The Twelve Data free tier allows ~8 requests/minute and a daily
  cap. The script spaces its calls out to stay under the per-minute limit; if you
  grow the watchlist a lot, keep the daily cap in mind.
- **Invalid tickers** are skipped with an error line in the run log rather than
  crashing the whole run.
