"""
bot.py — SMC AI Trading Bot
Exchange : Bitget (USDT perpetual futures)
Strategy : Previous Day High/Low Box + SMC (BOS, Liquidity Sweep, RSI)
AI Brain : Claude reads crypto + macro + social news before every trade
Hosting  : Railway.app (runs 24/7 online)
"""

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

# ── BOT STATE (shared with dashboard) ────────────────────────────
state = {
    "running":           True,
    "mode":              TRADING_MODE,
    "leverage":          LEVERAGE,
    "position":          None,
    "last_signal":       "Starting...",
    "last_signal_time":  "",
    "last_news_score":   0,
    "last_news_summary": "",
    "last_news_headlines": [],
    "trades":            [],
    "balance":           10000.0,   # Will be updated from exchange
    "pnl_total":         0.0,
    "wins":              0,
    "losses":            0,
    "box":               None,
    "current_price":     0.0,
    "current_rsi":       50.0,
    "last_cycle":        "",
    "errors":            [],
}


# ══════════════════════════════════════════════════════════════════
# BITGET API
# ══════════════════════════════════════════════════════════════════

BITGET_BASE = "https://api.bitget.com"

# Bitget v2 API uses productType=USDT-FUTURES and symbol=BTCUSDT
BITGET_SYMBOL    = "BTCUSDT"
BITGET_PROD_TYPE = "USDT-FUTURES"

def bitget_get(path, params=None):
    """Public GET request to Bitget."""
    try:
        r = requests.get(BITGET_BASE + path, params=params, timeout=10)
        return r.json()
    except Exception as e:
        log.error(f"Bitget GET error: {e}")
        return {}


def bitget_signed(method, path, body=None):
    """Signed request to Bitget (for account/order endpoints)."""
    import hmac, hashlib, base64
    if not BITGET_API_KEY:
        return {}
    ts    = str(int(time.time() * 1000))
    body_str = json.dumps(body or {})
    msg   = ts + method.upper() + path + (body_str if method == "POST" else "")
    sig   = base64.b64encode(
        hmac.new(BITGET_API_SECRET.encode(), msg.encode(), hashlib.sha256).digest()
    ).decode()
    headers = {
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
    """Get USDT balance from Bitget."""
    if TRADING_MODE == "PAPER":
        return state["balance"]
    try:
        r = bitget_signed("GET", f"/api/v2/mix/account/account?symbol={BITGET_SYMBOL}&productType={BITGET_PROD_TYPE}&marginCoin=USDT")
        bal = float(r.get("data", {}).get("available", state["balance"]))
        state["balance"] = bal
        return bal
    except Exception as e:
        log.error(f"Balance error: {e}")
        return state["balance"]


def get_candles(granularity, limit=200):
    """
    Fetch OHLCV from Bitget v2 public API.
    For daily uses 1Dutc (UTC midnight aligned).
    """
    gran_map = {"1H": "1H", "1D": "1Dutc", "4H": "4H", "15m": "15m", "1m": "1m"}
    gran = gran_map.get(granularity, "1H")
    path = "/api/v2/mix/market/candles"
    params = {
        "symbol":      BITGET_SYMBOL,
        "productType": BITGET_PROD_TYPE,
        "granularity": gran,
        "limit":       str(limit),
    }
    r = bitget_get(path, params)
    candles = []
    raw = r.get("data", [])
    if not raw:
        log.warning(f"No candle data. gran={gran} response: {str(r)[:200]}")
        return candles
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
    if granularity == "1D" and candles:
        dates = [datetime.fromtimestamp(c["time"]/1000, tz=timezone.utc).strftime("%Y-%m-%d") for c in candles[-5:]]
        log.info(f"Last 5 daily candles: {dates}")
    return candles


def get_ticker():
    """Get current BTC price from Bitget v2."""
    r = bitget_get("/api/v2/mix/market/ticker", {
        "symbol": BITGET_SYMBOL,
        "productType": BITGET_PROD_TYPE,
    })
    try:
        price = float(r["data"][0]["lastPr"])
        state["current_price"] = price
        return price
    except Exception as e:
        log.warning(f"Ticker error: {e} | response: {r}")
        return state["current_price"]


def place_order_paper(side, qty, entry, sl, tp):
    """Simulate order in paper mode."""
    order_id = f"PAPER_{int(time.time())}"
    log.info(f"[PAPER] {side} {qty:.4f} BTC @ {entry:.2f} | SL={sl:.2f} TP={tp:.2f}")
    return order_id


def place_order_live(side, qty, sl, tp):
    """Place real order on Bitget v2 with leverage."""
    # Set leverage first
    bitget_signed("POST", "/api/v2/mix/account/set-leverage", {
        "symbol":      BITGET_SYMBOL,
        "productType": BITGET_PROD_TYPE,
        "marginCoin":  "USDT",
        "leverage":    str(LEVERAGE),
        "holdSide":    "long" if side == "LONG" else "short",
    })
    body = {
        "symbol":          BITGET_SYMBOL,
        "productType":     BITGET_PROD_TYPE,
        "marginMode":      "isolated",
        "marginCoin":      "USDT",
        "size":            str(round(qty, 4)),
        "side":            "buy" if side == "LONG" else "sell",
        "tradeSide":       "open",
        "orderType":       "market",
        "presetStopSurplusPrice": str(round(tp, 2)),
        "presetStopLossPrice":    str(round(sl, 2)),
    }
    r = bitget_signed("POST", "/api/v2/mix/order/place-order", body)
    log.info(f"Order response: {r}")
    return r.get("data", {}).get("orderId", None)


def close_position_live(side):
    """Close open position on Bitget v2."""
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
# TECHNICAL INDICATORS
# ══════════════════════════════════════════════════════════════════

def calc_rsi(closes, period=14):
    if len(closes) < period + 2:
        return 50.0
    gains, losses = [], []
    for i in range(1, period + 1):
        d = closes[-(i)] - closes[-(i+1)]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag = sum(gains) / period
    al = sum(losses) / period
    if al == 0:
        return 100.0
    return round(100 - 100 / (1 + ag / al), 1)


def find_swing_highs(candles, left=5, right=5):
    highs = []
    for i in range(left, len(candles) - right):
        h = candles[i]["high"]
        if all(h >= candles[j]["high"] for j in range(i-left, i+right+1) if j != i):
            highs.append({"bar": i, "price": h})
    return highs


def find_swing_lows(candles, left=5, right=5):
    lows = []
    for i in range(left, len(candles) - right):
        l = candles[i]["low"]
        if all(l <= candles[j]["low"] for j in range(i-left, i+right+1) if j != i):
            lows.append({"bar": i, "price": l})
    return lows


def detect_bos(candles, swing_highs, swing_lows):
    """Break of Structure: close breaks swing high/low with candle close confirmation."""
    if len(candles) < 2:
        return False, False
    c1, c0 = candles[-2]["close"], candles[-1]["close"]
    bos_bull = bool(swing_highs and c0 > swing_highs[-1]["price"] and c1 <= swing_highs[-1]["price"])
    bos_bear = bool(swing_lows  and c0 < swing_lows[-1]["price"]  and c1 >= swing_lows[-1]["price"])
    return bos_bull, bos_bear


def detect_liquidity_sweep(candles, swing_highs, swing_lows):
    """Wick breaks swing level but candle closes back inside — classic liquidity sweep."""
    if not candles:
        return False, False
    c = candles[-1]
    bull_sweep = any(c["low"] < s["price"] and c["close"] > s["price"] for s in swing_lows[-3:])
    bear_sweep = any(c["high"] > s["price"] and c["close"] < s["price"] for s in swing_highs[-3:])
    return bull_sweep, bear_sweep


def detect_fvg(candles):
    """Fair Value Gap / Imbalance — gap between candle[-3].high and candle[-1].low."""
    if len(candles) < 3:
        return False, False
    bull_fvg = candles[-3]["high"] < candles[-1]["low"]
    bear_fvg = candles[-3]["low"]  > candles[-1]["high"]
    return bull_fvg, bear_fvg


# ══════════════════════════════════════════════════════════════════
# PREVIOUS DAY BOX
# ══════════════════════════════════════════════════════════════════

def build_daily_box(daily_candles):
    """
    Yesterday's High/Low = Primary POI zones.
    Always use the most recent COMPLETED daily candle
    (not the current incomplete one).
    """
    if len(daily_candles) < 2:
        return None

    now_utc   = datetime.now(timezone.utc)
    today_str = now_utc.strftime("%Y-%m-%d")

    # Find the most recent candle that is NOT today (i.e. completed)
    yesterday = None
    for c in reversed(daily_candles):
        candle_date = datetime.fromtimestamp(c["time"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        if candle_date < today_str:
            yesterday = c
            break

    if not yesterday:
        yesterday = daily_candles[-2]
        log.warning(f"Box fallback to index -2")

    box = {
        "high": yesterday["high"],
        "low":  yesterday["low"],
        "mid":  round((yesterday["high"] + yesterday["low"]) / 2, 2),
        "date": datetime.fromtimestamp(yesterday["time"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d"),
        "size": round(yesterday["high"] - yesterday["low"], 2),
    }
    log.info(f"Box selected: date={box[chr(39)]date[chr(39)]} H={box[chr(39)]high[chr(39)]:.2f} L={box[chr(39)]low[chr(39)]:.2f}")
    state["box"] = box
    return box


def near_level(price, level, pct=None):
    pct = pct or SMC_RULES["pdbox_proximity_pct"]
    return abs(price - level) / level < pct


# ══════════════════════════════════════════════════════════════════
# SESSION FILTER
# ══════════════════════════════════════════════════════════════════

def in_session():
    hour = datetime.now(timezone.utc).hour
    r = SMC_RULES
    in_london = r["london_open"] <= hour < r["london_close"]
    in_ny     = r["ny_open"]     <= hour < r["ny_close"]
    return ("london"   in r["trade_sessions"] and in_london) or \
           ("new_york" in r["trade_sessions"] and in_ny)


# ══════════════════════════════════════════════════════════════════
# AI NEWS ANALYSIS
# ══════════════════════════════════════════════════════════════════

def fetch_news():
    """Fetch headlines from all news sources."""
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
    Claude analyzes latest news and returns:
    - score: -2 (very bearish) to +2 (very bullish)
    - summary: one-sentence explanation
    - For LONG: need score >= 0
    - For SHORT: need score <= 0
    """
    if not SMC_RULES["use_ai_news_filter"] or not headlines or not ANTHROPIC_API_KEY:
        return 0, "AI filter disabled"

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        news_block = "\n".join(f"• {h}" for h in headlines)

        prompt = f"""You are an AI crypto trading assistant. Analyze these news headlines for a {signal_type} trade on BTC/USDT.

Current BTC price: ${price:,.2f}
Previous Day Box: HIGH=${box['high']:,.2f} | MID=${box['mid']:,.2f} | LOW=${box['low']:,.2f}
Proposed trade direction: {signal_type}

Latest headlines:
{news_block}

Return ONLY a JSON object, no markdown, no extra text:
{{"score": <integer -2 to +2>, "summary": "<max 20 words>", "key_factor": "<most relevant headline>"}}

Score:
+2 = Very bullish (ETF, institutional buy, positive regulation)
+1 = Mildly bullish
 0 = Neutral / mixed
-1 = Mildly bearish
-2 = Very bearish (hack, ban, crash, major FUD)"""

        r = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=150,
            messages=[{"role": "user", "content": prompt}]
        )
        text = r.content[0].text.strip().replace("```json", "").replace("```", "").strip()
        data = json.loads(text)
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
        state["errors"].append(str(e))
        return 0, f"AI error: {str(e)[:60]}"


# ══════════════════════════════════════════════════════════════════
# STRATEGY EXECUTION
# ══════════════════════════════════════════════════════════════════

def execute_trade(signal, entry, sl, tp, qty, news_score, news_summary):
    """Execute trade in paper or live mode."""
    if TRADING_MODE == "PAPER":
        order_id = place_order_paper(signal, qty, entry, sl, tp)
    else:
        order_id = place_order_live(signal, qty, sl, tp)

    if order_id:
        state["position"] = {
            "type":          signal,
            "entry":         entry,
            "sl":            sl,
            "tp":            tp,
            "qty":           qty,
            "time":          datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "order_id":      order_id,
            "news_score":    news_score,
            "news_summary":  news_summary,
        }
        state["last_signal"] = signal
        state["last_signal_time"] = datetime.now(timezone.utc).strftime("%H:%M UTC")
        return True
    return False


def check_position(price):
    """Check if open position hit TP or SL."""
    pos = state["position"]
    if not pos:
        return

    hit_tp = (pos["type"] == "LONG"  and price >= pos["tp"]) or \
             (pos["type"] == "SHORT" and price <= pos["tp"])
    hit_sl = (pos["type"] == "LONG"  and price <= pos["sl"]) or \
             (pos["type"] == "SHORT" and price >= pos["sl"])

    if not hit_tp and not hit_sl:
        return

    close_price = pos["tp"] if hit_tp else pos["sl"]
    pnl = (close_price - pos["entry"]) * pos["qty"] if pos["type"] == "LONG" \
          else (pos["entry"] - close_price) * pos["qty"]
    pnl = round(pnl, 2)

    result = "WIN ✅" if hit_tp else "LOSS ❌"
    log.info(f"Position closed: {result} | PnL={pnl:+.2f} USDT")

    state["pnl_total"]   = round(state["pnl_total"] + pnl, 2)
    state["balance"]     = round(state["balance"] + pnl, 2)
    if hit_tp: state["wins"]   += 1
    else:      state["losses"] += 1

    state["trades"].append({
        "type":       pos["type"],
        "entry":      pos["entry"],
        "close":      close_price,
        "pnl":        pnl,
        "result":     "WIN" if hit_tp else "LOSS",
        "time":       datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "news_score": pos["news_score"],
    })

    if TRADING_MODE == "LIVE":
        close_position_live(pos["type"])

    state["position"] = None


def run_strategy():
    """Main strategy logic — called every hour."""
    rules = SMC_RULES

    # ── Session check ─────────────────────────────────────────────
    if not in_session():
        state["last_signal"] = f"Outside session (UTC {datetime.now(timezone.utc).hour}:00)"
        log.info(state["last_signal"])
        return

    # ── Fetch price & candles ─────────────────────────────────────
    price      = get_ticker()
    candles_1h = get_candles(TIMEFRAME_1H, 150)
    candles_1d = get_candles(TIMEFRAME_1D, 10)

    if len(candles_1h) < 50 or len(candles_1d) < 2:
        state["last_signal"] = "Not enough candle data"
        return

    # ── Check open position ───────────────────────────────────────
    if state["position"]:
        check_position(price)
        if state["position"]:
            p = state["position"]
            state["last_signal"] = f"HOLDING {p['type']} @ {p['entry']:.2f}"
            return

    # ── Indicators ────────────────────────────────────────────────
    box    = build_daily_box(candles_1d)
    closes = [c["close"] for c in candles_1h]
    rsi    = calc_rsi(closes)
    state["current_rsi"] = rsi

    s_highs  = find_swing_highs(candles_1h, left=5, right=5)
    s_lows   = find_swing_lows(candles_1h, left=5, right=5)
    bos_bull, bos_bear  = detect_bos(candles_1h, s_highs, s_lows)
    liq_bull, liq_bear  = detect_liquidity_sweep(candles_1h, s_highs, s_lows)
    fvg_bull, fvg_bear  = detect_fvg(candles_1h)

    if not box:
        state["last_signal"] = "No box data"
        return

    balance    = get_balance()
    box_height = box["high"] - box["low"]

    log.info(f"Price={price:.2f} RSI={rsi} Box=[{box['low']:.2f}–{box['high']:.2f}] "
             f"BOS_bull={bos_bull} BOS_bear={bos_bear} "
             f"Liq_bull={liq_bull} Liq_bear={liq_bear}")

    # ─────────────────────────────────────────────────────────────
    # SHORT SETUP: price at PDH + RSI overbought + SMC confirmation
    # ─────────────────────────────────────────────────────────────
    at_pdh  = near_level(price, box["high"])
    rsi_ob  = rsi > rules["pdbox_short_rsi_threshold"]
    smc_ok_short = liq_bear or bos_bear or fvg_bear

    if at_pdh and rsi_ob and smc_ok_short:
        log.info("SHORT setup found — fetching news for AI analysis...")
        headlines  = fetch_news()
        score, summary = ai_news_score(headlines, "SHORT", price, box)

        if score <= rules["min_news_score"]:
            entry = price
            sl    = round(box["high"] + box_height * 0.5, 2)
            tp    = box["mid"]
            risk  = abs(entry - sl)
            qty   = round((balance * RISK_PER_TRADE) / risk, 4) if risk > 0 else 0.001
            qty   = max(qty, 0.001)

            log.info(f"Placing SHORT: entry={entry} sl={sl} tp={tp} qty={qty} news={score}")
            ok = execute_trade("SHORT", entry, sl, tp, qty, score, summary)
            if ok:
                log.info("SHORT opened!")
            else:
                state["last_signal"] = "SHORT — order failed"
        else:
            state["last_signal"] = f"SHORT blocked — AI score={score} ({summary[:40]})"
            log.info(state["last_signal"])
        return

    # ─────────────────────────────────────────────────────────────
    # LONG SETUP: price at PDL + RSI oversold + SMC confirmation
    # ─────────────────────────────────────────────────────────────
    at_pdl  = near_level(price, box["low"])
    rsi_os  = rsi < rules["pdbox_long_rsi_threshold"]
    smc_ok_long = liq_bull or bos_bull or fvg_bull

    if at_pdl and rsi_os and smc_ok_long:
        log.info("LONG setup found — fetching news for AI analysis...")
        headlines  = fetch_news()
        score, summary = ai_news_score(headlines, "LONG", price, box)

        if score >= rules["min_news_score"]:
            entry = price
            sl    = round(box["low"] - box_height * 0.5, 2)
            tp    = box["mid"]
            risk  = abs(entry - sl)
            qty   = round((balance * RISK_PER_TRADE) / risk, 4) if risk > 0 else 0.001
            qty   = max(qty, 0.001)

            log.info(f"Placing LONG: entry={entry} sl={sl} tp={tp} qty={qty} news={score}")
            ok = execute_trade("LONG", entry, sl, tp, qty, score, summary)
            if ok:
                log.info("LONG opened!")
            else:
                state["last_signal"] = "LONG — order failed"
        else:
            state["last_signal"] = f"LONG blocked — AI score={score} ({summary[:40]})"
            log.info(state["last_signal"])
        return

    # ── No setup ──────────────────────────────────────────────────
    state["last_signal"] = f"WAIT | RSI={rsi} | Box [{box['low']:.0f}–{box['high']:.0f}]"
    log.info(state["last_signal"])


# ══════════════════════════════════════════════════════════════════
# BOT LOOP (runs in background thread)
# ══════════════════════════════════════════════════════════════════

def bot_loop():
    log.info("═══════════════════════════════════")
    log.info("  SMC AI BOT — Bitget | Railway")
    log.info(f"  Mode: {TRADING_MODE}")
    log.info("═══════════════════════════════════")

    while state["running"]:
        try:
            now = datetime.now(timezone.utc)
            state["last_cycle"] = now.strftime("%Y-%m-%d %H:%M UTC")
            run_strategy()
        except Exception as e:
            log.error(f"Strategy error: {e}")
            state["errors"].append(f"{datetime.now(timezone.utc).strftime('%H:%M')} {str(e)[:80]}")
            state["errors"] = state["errors"][-10:]

        # Sleep until next hour close
        now     = datetime.now(timezone.utc)
        wait    = (60 - now.minute) * 60 - now.second
        log.info(f"Next cycle in {60 - now.minute}m {60 - now.second}s")
        time.sleep(max(wait, 60))


# Start bot in background thread so dashboard can run in main thread
bot_thread = threading.Thread(target=bot_loop, daemon=True)
