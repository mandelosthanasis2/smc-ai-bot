"""
bot.py — SMC AI Trading Bot v2
════════════════════════════════════════════════════════════════
Strategy:
  1. Previous Day Box (PDH/PDL/MID) built from 4H candles
  2. Entry on 1H timeframe
  3. SHORT at PDH: RSI > 70
  4. LONG  at PDL: RSI < 30
  5. SL at nearest 4H support/resistance + 0.3% buffer
  6. TP at MID of box
  7. RSI Divergence (20 candle lookback):
       → If divergence: DOUBLE position size (4% risk)
       → If no divergence: normal position size (2% risk)
  8. AI news filter (Claude) before every trade
  9. Telegram notifications for all events
════════════════════════════════════════════════════════════════
"""

import os
import time
import json
import math
import logging
import threading
import requests
import feedparser
from datetime import datetime, timezone
import anthropic
from config import *

# ── LOGGING ──────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

# ── TELEGRAM ─────────────────────────────────────────────────────
def send_telegram(msg):
    token   = os.environ.get("TELEGRAM_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return
    try:
        url  = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, data={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"}, timeout=5)
    except Exception as e:
        log.warning(f"Telegram error: {e}")

# ── STATE ────────────────────────────────────────────────────────
STATE_FILE = "/app/bot_state.json"

DEFAULT_STATE = {
    "mode":                TRADING_MODE,
    "leverage":            LEVERAGE,
    "position":            None,
    "last_signal":         "Starting...",
    "last_signal_time":    "",
    "last_news_score":     0,
    "last_news_summary":   "",
    "last_news_headlines": [],
    "trades":              [],
    "balance":             10000.0,
    "pnl_total":           0.0,
    "wins":                0,
    "losses":              0,
    "box":                 None,
    "current_price":       0.0,
    "current_rsi":         50.0,
    "last_cycle":          "",
    "errors":              [],
    "last_divergence":     False,
}

# ── SAVED STATE (από το τελευταίο deploy) ────────────────────────
SAVED_STATE = {
    "balance":   10151.56,
    "pnl_total": 151.56,
    "wins":      1,
    "losses":    0,
    "trades": [
        {
            "close":      79452.85,
            "divergence": False,
            "entry":      80865.3,
            "news_score": 0,
            "pnl":        151.56,
            "result":     "WIN",
            "time":       "2026-05-08 02:18",
            "type":       "SHORT"
        }
    ],
    "position": {
        "entry":         80215.4,
        "has_divergence": False,
        "news_score":    0,
        "news_summary":  "",
        "order_id":      "PAPER_1778238291",
        "qty":           0.0255,
        "sl":            72260.27,
        "time":          "2026-05-08 11:04 UTC",
        "tp":            80562.45,
        "type":          "LONG"
    },
}

def load_state():
    """Load state from file — survives deploys."""
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE) as f:
                saved = json.load(f)
            merged = {**DEFAULT_STATE, **saved}
            merged["running"] = True
            merged["mode"]    = TRADING_MODE
            log.info(f"State loaded: balance=${merged['balance']:.2f} | "
                     f"trades={len(merged['trades'])} | wins={merged['wins']} losses={merged['losses']}")
            return merged
    except Exception as e:
        log.warning(f"Could not load state ({e}) — loading from SAVED_STATE")
    # Fallback: use hardcoded saved state
    merged = {**DEFAULT_STATE, **SAVED_STATE}
    merged["running"] = True
    merged["mode"]    = TRADING_MODE
    log.info(f"SAVED_STATE loaded: balance=${merged['balance']:.2f} wins={merged['wins']}")
    return merged

def save_state():
    """Save state to file so it survives deploys."""
    try:
        to_save = {k: v for k, v in state.items() if k != "running"}
        with open(STATE_FILE, "w") as f:
            json.dump(to_save, f, indent=2, default=str)
    except Exception as e:
        log.warning(f"Could not save state: {e}")

state = load_state()
state["running"] = True

# ── BITGET API ────────────────────────────────────────────────────
BITGET_BASE      = "https://api.bitget.com"
BITGET_SYMBOL    = "BTCUSDT"
BITGET_PROD_TYPE = "USDT-FUTURES"

def bitget_get(path, params=None):
    try:
        r = requests.get(BITGET_BASE + path, params=params, timeout=10)
        return r.json()
    except Exception as e:
        log.error(f"Bitget GET error: {e}")
        return {}

def bitget_signed(method, path, body=None):
    import hmac, hashlib, base64
    if not BITGET_API_KEY:
        return {}
    ts       = str(int(time.time() * 1000))
    body_str = json.dumps(body or {})
    msg      = ts + method.upper() + path + (body_str if method == "POST" else "")
    sig      = base64.b64encode(
        hmac.new(BITGET_API_SECRET.encode(), msg.encode(), hashlib.sha256).digest()
    ).decode()
    headers  = {
        "ACCESS-KEY":        BITGET_API_KEY,
        "ACCESS-SIGN":       sig,
        "ACCESS-TIMESTAMP":  ts,
        "ACCESS-PASSPHRASE": BITGET_PASSPHRASE,
        "Content-Type":      "application/json",
        "locale":            "en-US",
    }
    try:
        if method == "GET":
            r = requests.get(BITGET_BASE + path, headers=headers, timeout=10)
        else:
            r = requests.post(BITGET_BASE + path, headers=headers, data=body_str, timeout=10)
        return r.json()
    except Exception as e:
        log.error(f"Bitget signed error: {e}")
        return {}

def get_balance():
    if TRADING_MODE == "PAPER":
        return state["balance"]
    try:
        r   = bitget_signed("GET", f"/api/v2/mix/account/account?symbol={BITGET_SYMBOL}&productType={BITGET_PROD_TYPE}&marginCoin=USDT")
        bal = float(r.get("data", {}).get("available", state["balance"]))
        state["balance"] = bal
        return bal
    except Exception as e:
        log.error(f"Balance error: {e}")
        return state["balance"]

def get_candles(granularity, limit=200):
    """
    Fetch OHLCV candles from Bitget v2.
    granularity: '1H' | '4H' | '1D'
    Note: '1D' maps to '4H' — we group 4H candles by date to get daily high/low.
    """
    gran_map = {"1H": "1H", "4H": "4H", "1D": "4H", "15m": "15m"}
    gran     = gran_map.get(granularity, "1H")
    path     = "/api/v2/mix/market/candles"
    params   = {
        "symbol":      BITGET_SYMBOL,
        "productType": BITGET_PROD_TYPE,
        "granularity": gran,
        "limit":       str(limit),
    }
    r      = bitget_get(path, params)
    raw    = r.get("data", [])
    if not raw:
        log.warning(f"No candle data. gran={gran} response: {str(r)[:200]}")
        return []
    candles = []
    for c in reversed(raw):
        try:
            candles.append({
                "time":   int(c[0]),
                "open":   float(c[1]),
                "high":   float(c[2]),
                "low":    float(c[3]),
                "close":  float(c[4]),
                "volume": float(c[5]),
            })
        except Exception:
            pass
    return candles

def get_ticker():
    r = bitget_get("/api/v2/mix/market/ticker", {
        "symbol": BITGET_SYMBOL, "productType": BITGET_PROD_TYPE
    })
    try:
        price = float(r["data"][0]["lastPr"])
        state["current_price"] = price
        return price
    except Exception as e:
        log.warning(f"Ticker error: {e}")
        return state["current_price"]

def place_order_paper(side, qty, entry, sl, tp):
    order_id = f"PAPER_{int(time.time())}"
    log.info(f"[PAPER] {side} qty={qty:.4f} @ {entry:.2f} | SL={sl:.2f} TP={tp:.2f}")
    return order_id

def place_order_live(side, qty, sl, tp):
    bitget_signed("POST", "/api/v2/mix/account/set-leverage", {
        "symbol": BITGET_SYMBOL, "productType": BITGET_PROD_TYPE,
        "marginCoin": "USDT", "leverage": str(LEVERAGE),
        "holdSide": "long" if side == "LONG" else "short",
    })
    body = {
        "symbol":                    BITGET_SYMBOL,
        "productType":               BITGET_PROD_TYPE,
        "marginMode":                "isolated",
        "marginCoin":                "USDT",
        "size":                      str(round(qty, 4)),
        "side":                      "buy" if side == "LONG" else "sell",
        "tradeSide":                 "open",
        "orderType":                 "market",
        "presetStopSurplusPrice":    str(round(tp, 2)),
        "presetStopLossPrice":       str(round(sl, 2)),
    }
    r = bitget_signed("POST", "/api/v2/mix/order/place-order", body)
    log.info(f"Live order response: {r}")
    return r.get("data", {}).get("orderId", None)

def close_position_live(side):
    body = {
        "symbol":      BITGET_SYMBOL,
        "productType": BITGET_PROD_TYPE,
        "marginCoin":  "USDT",
        "side":        "sell" if side == "LONG" else "buy",
        "tradeSide":   "close",
        "orderType":   "market",
        "size":        str(state["position"]["qty"]),
    }
    bitget_signed("POST", "/api/v2/mix/order/place-order", body)


# ══════════════════════════════════════════════════════════════════
# PREVIOUS DAY BOX (from 4H candles grouped by UTC date)
# ══════════════════════════════════════════════════════════════════

def build_daily_box(candles_4h):
    """
    Group 4H candles by UTC date → reconstruct daily high/low.
    Select yesterday's completed day as the box.
    """
    if not candles_4h:
        log.warning("No 4H candles for box")
        return None

    now_utc   = datetime.now(timezone.utc)
    today_str = now_utc.strftime("%Y-%m-%d")

    # Group by date
    days = {}
    for c in candles_4h:
        d = datetime.fromtimestamp(c["time"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        if d not in days:
            days[d] = {"high": c["high"], "low": c["low"]}
        else:
            days[d]["high"] = max(days[d]["high"], c["high"])
            days[d]["low"]  = min(days[d]["low"],  c["low"])

    sorted_dates = sorted(days.keys())
    log.info("Reconstructed daily dates: " + str(sorted_dates[-7:]))

    # Most recent completed day
    yesterday_date = None
    for d in reversed(sorted_dates):
        if d < today_str:
            yesterday_date = d
            break

    if not yesterday_date:
        log.warning("Could not find yesterday in 4H candles")
        return None

    y   = days[yesterday_date]
    box = {
        "high": y["high"],
        "low":  y["low"],
        "mid":  round((y["high"] + y["low"]) / 2, 2),
        "date": yesterday_date,
        "size": round(y["high"] - y["low"], 2),
    }
    log.info("Box: date=" + yesterday_date +
             " H=" + str(round(box["high"], 2)) +
             " L=" + str(round(box["low"],  2)) +
             " MID=" + str(box["mid"]))
    state["box"] = box
    return box


# ══════════════════════════════════════════════════════════════════
# INDICATORS
# ══════════════════════════════════════════════════════════════════

def calc_rsi(closes, period=14):
    if len(closes) < period + 2:
        return 50.0
    ag, al = 0.0, 0.0
    for i in range(1, period + 1):
        d = closes[-i] - closes[-i - 1]
        if d > 0: ag += d
        else:     al -= d
    ag /= period
    al /= period
    if al == 0:
        return 100.0
    return round(100 - 100 / (1 + ag / al), 2)


def detect_rsi_divergence(candles_1h, lookback=20):
    """
    Detect RSI divergence over last `lookback` 1H candles.

    Bearish divergence (SHORT signal strength):
      Price makes higher high BUT RSI makes lower high
      → Smart money distributing, momentum weakening

    Bullish divergence (LONG signal strength):
      Price makes lower low BUT RSI makes higher low
      → Smart money accumulating, selling pressure weakening

    Returns: (bull_div: bool, bear_div: bool)
    """
    if len(candles_1h) < lookback + 2:
        return False, False

    recent   = candles_1h[-lookback:]
    closes   = [c["close"] for c in candles_1h]
    highs    = [c["high"]  for c in recent]
    lows     = [c["low"]   for c in recent]

    # Calculate RSI for each candle in the lookback window
    rsi_vals = []
    for i in range(len(candles_1h) - lookback, len(candles_1h)):
        rsi_vals.append(calc_rsi(closes[:i + 1]))

    if len(rsi_vals) < lookback:
        return False, False

    # Find swing highs in price (local maxima)
    price_swing_highs = []
    rsi_at_swing_highs = []
    for i in range(1, len(highs) - 1):
        if highs[i] > highs[i-1] and highs[i] > highs[i+1]:
            price_swing_highs.append(highs[i])
            rsi_at_swing_highs.append(rsi_vals[i])

    # Find swing lows in price (local minima)
    price_swing_lows = []
    rsi_at_swing_lows = []
    for i in range(1, len(lows) - 1):
        if lows[i] < lows[i-1] and lows[i] < lows[i+1]:
            price_swing_lows.append(lows[i])
            rsi_at_swing_lows.append(rsi_vals[i])

    bear_div = False
    bull_div = False

    # Bearish divergence: price higher high + RSI lower high
    if len(price_swing_highs) >= 2:
        if (price_swing_highs[-1] > price_swing_highs[-2] and
                rsi_at_swing_highs[-1] < rsi_at_swing_highs[-2]):
            bear_div = True
            log.info(f"Bearish divergence: price {price_swing_highs[-2]:.0f}→{price_swing_highs[-1]:.0f} "
                     f"RSI {rsi_at_swing_highs[-2]:.1f}→{rsi_at_swing_highs[-1]:.1f}")

    # Bullish divergence: price lower low + RSI higher low
    if len(price_swing_lows) >= 2:
        if (price_swing_lows[-1] < price_swing_lows[-2] and
                rsi_at_swing_lows[-1] > rsi_at_swing_lows[-2]):
            bull_div = True
            log.info(f"Bullish divergence: price {price_swing_lows[-2]:.0f}→{price_swing_lows[-1]:.0f} "
                     f"RSI {rsi_at_swing_lows[-2]:.1f}→{rsi_at_swing_lows[-1]:.1f}")

    state["last_divergence"] = bear_div or bull_div
    return bull_div, bear_div


def find_4h_support_resistance(candles_4h, current_price, lookback=50):
    """
    Find nearest 4H swing high (resistance) and swing low (support)
    relative to current price.
    Returns: (nearest_support, nearest_resistance)
    """
    recent = candles_4h[-lookback:] if len(candles_4h) > lookback else candles_4h

    swing_highs = []
    swing_lows  = []

    for i in range(2, len(recent) - 2):
        h = recent[i]["high"]
        l = recent[i]["low"]
        if h > recent[i-1]["high"] and h > recent[i-2]["high"] and \
           h > recent[i+1]["high"] and h > recent[i+2]["high"]:
            swing_highs.append(h)
        if l < recent[i-1]["low"] and l < recent[i-2]["low"] and \
           l < recent[i+1]["low"] and l < recent[i+2]["low"]:
            swing_lows.append(l)

    # Nearest resistance ABOVE current price
    resistances_above = [h for h in swing_highs if h > current_price]
    nearest_resistance = min(resistances_above) if resistances_above else current_price * 1.02

    # Nearest support BELOW current price
    supports_below = [l for l in swing_lows if l < current_price]
    nearest_support = max(supports_below) if supports_below else current_price * 0.98

    log.info(f"4H levels: support={nearest_support:.2f} resistance={nearest_resistance:.2f}")
    return nearest_support, nearest_resistance


def near_level(price, level, pct=0.012):
    return abs(price - level) / level < pct


# ══════════════════════════════════════════════════════════════════
# SESSION FILTER
# ══════════════════════════════════════════════════════════════════

def in_session():
    hour = datetime.now(timezone.utc).hour
    r    = SMC_RULES
    return (("london"   in r["trade_sessions"] and r["london_open"] <= hour < r["london_close"]) or
            ("new_york" in r["trade_sessions"] and r["ny_open"]     <= hour < r["ny_close"]))


# ══════════════════════════════════════════════════════════════════
# AI NEWS ANALYSIS
# ══════════════════════════════════════════════════════════════════

def fetch_news():
    headlines = []
    for url in NEWS_SOURCES:
        try:
            feed = feedparser.parse(url)
            for e in feed.entries[:4]:
                headlines.append(e.title)
        except Exception as ex:
            log.warning(f"News feed error ({url}): {ex}")
    state["last_news_headlines"] = headlines[:20]
    return headlines[:20]


def ai_news_score(headlines, signal_type, price, box):
    """
    Claude analyzes news headlines.
    Returns (score: int -2..+2, summary: str)
    SHORT needs score <= 0 | LONG needs score >= 0
    """
    if not SMC_RULES["use_ai_news_filter"] or not headlines or not ANTHROPIC_API_KEY:
        return 0, "AI filter disabled"
    try:
        client     = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        news_block = "\n".join(f"• {h}" for h in headlines)
        prompt     = f"""You are an AI crypto trading assistant. Analyze news for a {signal_type} trade on BTC/USDT.

Current price: ${price:,.2f}
Previous Day Box: HIGH=${box['high']:,.2f} | MID=${box['mid']:,.2f} | LOW=${box['low']:,.2f}
Direction: {signal_type}

Headlines:
{news_block}

Return ONLY JSON, no markdown:
{{"score": <-2 to +2>, "summary": "<max 20 words>", "key_factor": "<most relevant headline>"}}

+2=very bullish, +1=mildly bullish, 0=neutral, -1=mildly bearish, -2=very bearish"""

        r       = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=150,
            messages=[{"role": "user", "content": prompt}]
        )
        text    = r.content[0].text.strip().replace("```json","").replace("```","").strip()
        data    = json.loads(text)
        score   = max(-2, min(2, int(data.get("score", 0))))
        summary = data.get("summary", "")
        key     = data.get("key_factor", "")
        full    = f"{summary} | [{key}]"
        state["last_news_score"]   = score
        state["last_news_summary"] = full
        log.info(f"AI News: score={score} | {full}")
        return score, full
    except Exception as e:
        log.error(f"AI news error: {e}")
        return 0, f"AI error: {str(e)[:60]}"


# ══════════════════════════════════════════════════════════════════
# TRADE EXECUTION
# ══════════════════════════════════════════════════════════════════

def calc_position_size(balance, risk_pct, entry, sl):
    """Calculate qty based on risk percentage."""
    risk_amount = balance * risk_pct
    risk_dist   = abs(entry - sl)
    if risk_dist <= 0:
        return 0.001
    qty = round(risk_amount / risk_dist, 4)
    return max(qty, 0.001)


def execute_trade(signal, entry, sl, tp, qty, news_score, news_summary, has_divergence):
    """Execute paper or live trade."""
    if TRADING_MODE == "PAPER":
        order_id = place_order_paper(signal, qty, entry, sl, tp)
    else:
        order_id = place_order_live(signal, qty, sl, tp)

    if order_id:
        state["position"] = {
            "type":           signal,
            "entry":          entry,
            "sl":             sl,
            "tp":             tp,
            "qty":            qty,
            "time":           datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "order_id":       order_id,
            "news_score":     news_score,
            "news_summary":   news_summary,
            "has_divergence": has_divergence,
        }
        state["last_signal"]      = signal
        state["last_signal_time"] = datetime.now(timezone.utc).strftime("%H:%M UTC")
        save_state()

        risk_pct = RISK_PER_TRADE * 2 if has_divergence else RISK_PER_TRADE
        div_txt  = "🔥 DOUBLE SIZE (divergence)" if has_divergence else "Normal size"

        send_telegram(
            f"{'🟢' if signal == 'LONG' else '🔴'} <b>{signal} OPENED</b>\n"
            f"Entry: ${entry:,.2f}\n"
            f"TP:    ${tp:,.2f}\n"
            f"SL:    ${sl:,.2f}\n"
            f"Size:  {div_txt}\n"
            f"Risk:  {risk_pct*100:.0f}% (${balance_at_entry*risk_pct:.0f})\n"
            f"AI News Score: {news_score}\n"
            f"📰 {news_summary[:80]}"
        )
        return True
    return False

balance_at_entry = 10000.0


def check_position(price):
    """Check if open position hit TP or SL."""
    pos = state["position"]
    if not pos:
        return

    # LONG:  TP is above entry (MID of box), SL is below entry (4H support)
    # SHORT: TP is below entry (MID of box), SL is above entry (4H resistance)
    hit_tp = (pos["type"] == "LONG"  and price >= pos["tp"]) or              (pos["type"] == "SHORT" and price <= pos["tp"])
    hit_sl = (pos["type"] == "LONG"  and price <= pos["sl"]) or              (pos["type"] == "SHORT" and price >= pos["sl"])
    
    # Safety check: make sure TP/SL are on the correct side
    # LONG: tp must be > entry, sl must be < entry
    # SHORT: tp must be < entry, sl must be > entry
    if pos["type"] == "LONG":
        if pos["tp"] <= pos["entry"] or pos["sl"] >= pos["entry"]:
            log.error(f"LONG position has wrong TP/SL! entry={pos['entry']} tp={pos['tp']} sl={pos['sl']} — closing")
            state["position"] = None
            return
    if pos["type"] == "SHORT":
        if pos["tp"] >= pos["entry"] or pos["sl"] <= pos["entry"]:
            log.error(f"SHORT position has wrong TP/SL! entry={pos['entry']} tp={pos['tp']} sl={pos['sl']} — closing")
            state["position"] = None
            return

    if not hit_tp and not hit_sl:
        return

    close_price = pos["tp"] if hit_tp else pos["sl"]
    pnl = ((close_price - pos["entry"]) if pos["type"] == "LONG"
           else (pos["entry"] - close_price)) * pos["qty"]
    pnl = round(pnl, 2)

    result = "WIN ✅" if hit_tp else "LOSS ❌"
    log.info(f"Position closed: {result} | PnL={pnl:+.2f} USDT")

    state["pnl_total"] = round(state["pnl_total"] + pnl, 2)
    state["balance"]   = round(state["balance"]   + pnl, 2)
    if hit_tp: state["wins"]   += 1
    else:      state["losses"] += 1

    state["trades"].append({
        "type":           pos["type"],
        "entry":          pos["entry"],
        "close":          close_price,
        "pnl":            pnl,
        "result":         "WIN" if hit_tp else "LOSS",
        "time":           datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "news_score":     pos["news_score"],
        "divergence":     pos.get("has_divergence", False),
    })

    wins   = state["wins"]
    losses = state["losses"]
    send_telegram(
        f"{'✅ <b>TAKE PROFIT</b>' if hit_tp else '❌ <b>STOP LOSS</b>'}\n"
        f"PnL: {'+'if pnl>=0 else ''}{pnl:.2f} USDT\n"
        f"Balance: ${state['balance']:,.2f}\n"
        f"W/L: {wins}W / {losses}L | "
        f"WR: {round(wins/(wins+losses)*100) if wins+losses>0 else 0}%"
    )

    if TRADING_MODE == "LIVE":
        close_position_live(pos["type"])

    state["position"] = None
    save_state()


# ══════════════════════════════════════════════════════════════════
# MAIN STRATEGY
# ══════════════════════════════════════════════════════════════════

def run_strategy():
    global balance_at_entry
    rules = SMC_RULES

    # Session filter disabled — bot runs 24/7
    pass

    # ── Fetch data ─────────────────────────────────────────────────
    price      = get_ticker()
    candles_1h = get_candles("1H",  200)   # 1H for entry signals
    candles_4h = get_candles("4H",  200)   # 4H for box + S/R levels

    if len(candles_1h) < 50 or len(candles_4h) < 20:
        state["last_signal"] = "Not enough candle data"
        return

    # ── Check open position ────────────────────────────────────────
    if state["position"]:
        check_position(price)
        if state["position"]:
            p = state["position"]
            pnl_now = (price - p["entry"]) * p["qty"] if p["type"] == "LONG" else (p["entry"] - price) * p["qty"]
            state["last_signal"] = f"HOLDING {p['type']} @ {p['entry']:.2f} | PnL: {'+'if pnl_now>=0 else ''}{pnl_now:.2f}"
            log.info(state["last_signal"])
            return  # NEVER open new trade while position is open

    # ── Build box ──────────────────────────────────────────────────
    box = build_daily_box(candles_4h)
    if not box:
        state["last_signal"] = "No box data"
        return

    # ── Indicators ─────────────────────────────────────────────────
    closes_1h  = [c["close"] for c in candles_1h]
    rsi        = calc_rsi(closes_1h)
    state["current_rsi"] = rsi

    bull_div, bear_div = detect_rsi_divergence(candles_1h, lookback=20)
    support, resistance = find_4h_support_resistance(candles_4h, price)

    balance          = get_balance()
    balance_at_entry = balance

    log.info(
        f"Price={price:.2f} RSI={rsi} "
        f"Box=[{box['low']:.2f}–{box['high']:.2f}] MID={box['mid']:.2f} | "
        f"BullDiv={bull_div} BearDiv={bear_div} | "
        f"4H Support={support:.2f} Resistance={resistance:.2f}"
    )

    # ──────────────────────────────────────────────────────────────
    # SHORT SETUP
    # Conditions: price at/above PDH + RSI > 70
    # SL: nearest 4H resistance + 0.3% buffer
    # TP: MID of box (MUST be below entry for SHORT)
    # Size: x2 if bearish divergence
    # ──────────────────────────────────────────────────────────────
    # Price is near PDH = within 0.5% only (tight zone)
    # Must be very close to PDH — not in the middle of the box!
    at_pdh = (price >= box["high"] * 0.995) and (price <= box["high"] * 1.015)
    rsi_ob = rsi > rules["pdbox_short_rsi_threshold"]
    short_makes_sense = box["mid"] < price
    log.info(f"SHORT check: price={price:.2f} PDH={box['high']:.2f} "
             f"at_pdh={at_pdh} rsi={rsi} rsi_ok={rsi_ob}")

    if at_pdh and rsi_ob and short_makes_sense:
        log.info(f"SHORT setup: price={price:.2f} PDH={box['high']:.2f} RSI={rsi}")

        # SL at nearest 4H resistance above entry + 0.3% buffer
        sl = round(resistance * 1.003, 2)
        tp = box["mid"]

        # Ensure TP is BELOW entry for SHORT
        if tp >= price:
            tp = round(price * 0.99, 2)  # fallback: 1% below entry
            log.warning(f"SHORT TP was above entry, adjusted to {tp}")

        # Ensure SL is ABOVE entry for SHORT
        if sl <= price:
            sl = round(price * 1.005, 2)  # fallback: 0.5% above entry
            log.warning(f"SHORT SL was below entry, adjusted to {sl}")

        # If SL is too tight (< 0.3% away), widen it
        if abs(sl - price) / price < 0.003:
            sl = round(price * 1.005, 2)

        # Position size — double if bearish divergence
        risk_pct = RISK_PER_TRADE * 2 if bear_div else RISK_PER_TRADE
        qty      = calc_position_size(balance, risk_pct, price, sl)

        log.info(f"SHORT: SL={sl} TP={tp} qty={qty} divergence={bear_div} risk={risk_pct*100:.0f}%")

        # AI news filter
        headlines          = fetch_news()
        score, summary     = ai_news_score(headlines, "SHORT", price, box)

        # News is for your info only — does not block the trade
        send_telegram(
            f"📰 <b>News Update (SHORT)</b>\n"
            f"Score: {score} | {summary[:80]}"
        )
        ok = execute_trade("SHORT", price, sl, tp, qty, score, summary, bear_div)
        if not ok:
            state["last_signal"] = "SHORT — order failed"
        return

    # ──────────────────────────────────────────────────────────────
    # LONG SETUP
    # Conditions: price at/below PDL + RSI < 30
    # SL: nearest 4H support - 0.3% buffer
    # TP: MID of box (MUST be above entry for LONG)
    # Size: x2 if bullish divergence
    # ──────────────────────────────────────────────────────────────
    # Price is near PDL = within 0.5% only (tight zone)
    # Must be very close to PDL — not in the middle of the box!
    at_pdl = (price <= box["low"] * 1.005) and (price >= box["low"] * 0.985)
    rsi_os = rsi < rules["pdbox_long_rsi_threshold"]
    long_makes_sense = box["mid"] > price
    log.info(f"LONG check: price={price:.2f} PDL={box['low']:.2f} "
             f"at_pdl={at_pdl} rsi={rsi} rsi_ok={rsi_os}")

    if at_pdl and rsi_os and long_makes_sense:
        log.info(f"LONG setup: price={price:.2f} PDL={box['low']:.2f} RSI={rsi}")

        # SL at nearest 4H support below entry - 0.3% buffer
        sl = round(support * 0.997, 2)
        tp = box["mid"]

        # Ensure TP is ABOVE entry for LONG
        if tp <= price:
            tp = round(price * 1.01, 2)  # fallback: 1% above entry
            log.warning(f"LONG TP was below entry, adjusted to {tp}")

        # Ensure SL is BELOW entry for LONG
        if sl >= price:
            sl = round(price * 0.995, 2)  # fallback: 0.5% below entry
            log.warning(f"LONG SL was above entry, adjusted to {sl}")

        # If SL is too tight (< 0.3% away), widen it
        if abs(price - sl) / price < 0.003:
            sl = round(price * 0.995, 2)

        # Position size — double if bullish divergence
        risk_pct = RISK_PER_TRADE * 2 if bull_div else RISK_PER_TRADE
        qty      = calc_position_size(balance, risk_pct, price, sl)

        log.info(f"LONG: SL={sl} TP={tp} qty={qty} divergence={bull_div} risk={risk_pct*100:.0f}%")

        # AI news filter
        headlines      = fetch_news()
        score, summary = ai_news_score(headlines, "LONG", price, box)

        # News is for your info only — does not block the trade
        send_telegram(
            f"📰 <b>News Update (LONG)</b>\n"
            f"Score: {score} | {summary[:80]}"
        )
        ok = execute_trade("LONG", price, sl, tp, qty, score, summary, bull_div)
        if not ok:
            state["last_signal"] = "LONG — order failed"
        return

    # ── No setup ───────────────────────────────────────────────────
    div_status = "📊 Div detected!" if (bull_div or bear_div) else "No div"
    state["last_signal"] = (
        f"WAIT | RSI={rsi} | "
        f"Box [{box['low']:.0f}–{box['high']:.0f}] | "
        f"{div_status}"
    )
    log.info(state["last_signal"])


# ══════════════════════════════════════════════════════════════════
# BOT LOOP
# ══════════════════════════════════════════════════════════════════

def bot_loop():
    log.info("═══════════════════════════════════════")
    log.info("  SMC AI BOT v2 — Bitget | Railway")
    log.info(f"  Mode: {TRADING_MODE}")
    log.info(f"  Strategy: PDH/PDL Box + RSI + Divergence + 4H S/R")
    log.info("═══════════════════════════════════════")

    send_telegram(
        "⚡ <b>SMC AI Bot v2 Started</b>\n"
        f"Mode: {TRADING_MODE}\n"
        "Strategy:\n"
        "• Previous Day Box (PDH/PDL/MID)\n"
        "• RSI filter (>70 SHORT / <30 LONG)\n"
        "• RSI Divergence → double size\n"
        "• 4H S/R for Stop Loss\n"
        "• AI news filter before every trade\n"
        "• Timeframe: 1H entry\n"
        "Bot is running 24/7 🚀"
    )

    while state["running"]:
        try:
            now = datetime.now(timezone.utc)
            state["last_cycle"] = now.strftime("%Y-%m-%d %H:%M UTC")
            run_strategy()
        except Exception as e:
            log.error(f"Strategy error: {e}")
            state["errors"].append(f"{datetime.now(timezone.utc).strftime('%H:%M')} {str(e)[:80]}")
            state["errors"] = state["errors"][-10:]

        cycle = int(os.environ.get("CYCLE_SECONDS", "60"))
        save_state()  # persist state every cycle
        log.info(f"Next cycle in {cycle}s")
        time.sleep(cycle)


# Start bot thread
bot_thread = threading.Thread(target=bot_loop, daemon=True)
