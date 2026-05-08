"""
bot.py - SMC AI Trading Bot v2
================================================================
Strategy:
  1. Previous Day Box (PDH/PDL/MID) built from 4H candles
  2. Entry on 1H timeframe
  3. SHORT at PDH: RSI > 70, price within 0.5% of PDH
  4. LONG  at PDL: RSI < 30, price within 0.5% of PDL
  5. SL at nearest 4H S/R + 0.3% buffer (MAX 1.5% from entry)
  6. TP at MID of box
  7. RSI Divergence (20 candle lookback) → double size (4%)
  8. AI news (Claude) → info only, doesn't block trades
  9. Telegram notifications
  10. Persistent state - survives deploys
================================================================
"""

import os
import time
import json
import logging
import threading
import requests
import feedparser
from datetime import datetime, timezone
import anthropic
from config import *

# ── LOGGING ──────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ── TELEGRAM ─────────────────────────────────────────────────────
def send_telegram(msg):
    token   = os.environ.get("TELEGRAM_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"},
            timeout=5
        )
    except Exception as e:
        log.warning(f"Telegram error: {e}")

# ── SMC RULES ────────────────────────────────────────────────────
SMC_RULES = {
    "pdbox_short_rsi_threshold": 70,
    "pdbox_long_rsi_threshold":  30,
    "sl_buffer":                 0.003,   # 0.3% buffer on SL
    "max_sl_pct":                0.015,   # MAX 1.5% SL from entry
    "use_ai_news_filter":        True,
    "trade_sessions":            ["london", "new_york"],
    "london_open":  8,  "london_close": 16,
    "ny_open":      13, "ny_close":     21,
}

# ── PERSISTENT STATE ─────────────────────────────────────────────
STATE_FILE = "/app/bot_state.json"

SAVED_STATE = {
    "balance":   10151.56,
    "pnl_total": 151.56,
    "wins":      1,
    "losses":    0,
    "trades": [
        {
            "close": 79452.85, "divergence": False, "entry": 80865.3,
            "news_score": 0, "pnl": 151.56, "result": "WIN",
            "time": "2026-05-08 02:18", "type": "SHORT"
        }
    ],
    "position": None,
}

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

def load_state():
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE) as f:
                saved = json.load(f)
            merged = {**DEFAULT_STATE, **saved}
            merged["running"] = True
            merged["mode"]    = TRADING_MODE
            log.info(f"State loaded: balance=${merged['balance']:.2f} wins={merged['wins']} losses={merged['losses']}")
            return merged
    except Exception as e:
        log.warning(f"Could not load state ({e}) - using SAVED_STATE")
    merged = {**DEFAULT_STATE, **SAVED_STATE}
    merged["running"] = True
    merged["mode"]    = TRADING_MODE
    log.info(f"SAVED_STATE: balance=${merged['balance']:.2f} wins={merged['wins']}")
    return merged

def save_state():
    try:
        with open(STATE_FILE, "w") as f:
            json.dump({k: v for k, v in state.items() if k != "running"}, f, indent=2, default=str)
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
    sig      = base64.b64encode(hmac.new(BITGET_API_SECRET.encode(), msg.encode(), hashlib.sha256).digest()).decode()
    headers  = {
        "ACCESS-KEY": BITGET_API_KEY, "ACCESS-SIGN": sig,
        "ACCESS-TIMESTAMP": ts, "ACCESS-PASSPHRASE": BITGET_PASSPHRASE,
        "Content-Type": "application/json", "locale": "en-US",
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
    gran_map = {"1H": "1H", "4H": "4H", "1D": "4H"}
    gran     = gran_map.get(granularity, "1H")
    r        = bitget_get("/api/v2/mix/market/candles", {
        "symbol": BITGET_SYMBOL, "productType": BITGET_PROD_TYPE,
        "granularity": gran, "limit": str(limit),
    })
    raw = r.get("data", [])
    if not raw:
        log.warning(f"No candles. gran={gran} response: {str(r)[:200]}")
        return []
    candles = []
    for c in reversed(raw):
        try:
            candles.append({"time": int(c[0]), "open": float(c[1]), "high": float(c[2]),
                            "low": float(c[3]), "close": float(c[4]), "volume": float(c[5])})
        except Exception:
            pass
    return candles

def get_ticker():
    r = bitget_get("/api/v2/mix/market/ticker", {"symbol": BITGET_SYMBOL, "productType": BITGET_PROD_TYPE})
    try:
        price = float(r["data"][0]["lastPr"])
        state["current_price"] = price
        return price
    except Exception as e:
        log.warning(f"Ticker error: {e}")
        return state["current_price"]

def place_order_paper(side, qty, entry, sl, tp):
    log.info(f"[PAPER] {side} qty={qty:.4f} @ {entry:.2f} | SL={sl:.2f} TP={tp:.2f}")
    return f"PAPER_{int(time.time())}"

def place_order_live(side, qty, sl, tp):
    bitget_signed("POST", "/api/v2/mix/account/set-leverage", {
        "symbol": BITGET_SYMBOL, "productType": BITGET_PROD_TYPE,
        "marginCoin": "USDT", "leverage": str(LEVERAGE),
        "holdSide": "long" if side == "LONG" else "short",
    })
    body = {
        "symbol": BITGET_SYMBOL, "productType": BITGET_PROD_TYPE,
        "marginMode": "isolated", "marginCoin": "USDT",
        "size": str(round(qty, 4)),
        "side": "buy" if side == "LONG" else "sell",
        "tradeSide": "open", "orderType": "market",
        "presetStopSurplusPrice": str(round(tp, 2)),
        "presetStopLossPrice":    str(round(sl, 2)),
    }
    r = bitget_signed("POST", "/api/v2/mix/order/place-order", body)
    log.info(f"Live order: {r}")
    return r.get("data", {}).get("orderId", None)

def close_position_live(side):
    bitget_signed("POST", "/api/v2/mix/order/place-order", {
        "symbol": BITGET_SYMBOL, "productType": BITGET_PROD_TYPE,
        "marginCoin": "USDT",
        "side": "sell" if side == "LONG" else "buy",
        "tradeSide": "close", "orderType": "market",
        "size": str(state["position"]["qty"]),
    })

# ── INDICATORS ───────────────────────────────────────────────────
def calc_rsi(closes, period=14):
    if len(closes) < period + 2:
        return 50.0
    ag = al = 0.0
    for i in range(1, period + 1):
        d = closes[-i] - closes[-i-1]
        if d > 0: ag += d
        else:     al -= d
    ag /= period; al /= period
    return round(100 - 100 / (1 + ag / al), 2) if al > 0 else 100.0

def detect_rsi_divergence(candles_1h, lookback=20):
    if len(candles_1h) < lookback + 2:
        return False, False
    recent   = candles_1h[-lookback:]
    closes   = [c["close"] for c in candles_1h]
    highs    = [c["high"]  for c in recent]
    lows     = [c["low"]   for c in recent]
    rsi_vals = [calc_rsi(closes[:len(closes)-lookback+i+1]) for i in range(lookback)]

    ph, rh, pl, rl = [], [], [], []
    for i in range(1, len(highs)-1):
        if highs[i] > highs[i-1] and highs[i] > highs[i+1]:
            ph.append(highs[i]); rh.append(rsi_vals[i])
        if lows[i]  < lows[i-1]  and lows[i]  < lows[i+1]:
            pl.append(lows[i]);  rl.append(rsi_vals[i])

    bear = len(ph) >= 2 and ph[-1] > ph[-2] and rh[-1] < rh[-2]
    bull = len(pl) >= 2 and pl[-1] < pl[-2] and rl[-1] > rl[-2]

    if bear: log.info(f"Bearish divergence: price {ph[-2]:.0f}→{ph[-1]:.0f} RSI {rh[-2]:.1f}→{rh[-1]:.1f}")
    if bull: log.info(f"Bullish divergence: price {pl[-2]:.0f}→{pl[-1]:.0f} RSI {rl[-2]:.1f}→{rl[-1]:.1f}")

    state["last_divergence"] = bear or bull
    return bull, bear

def find_4h_sr(candles_4h, price, lookback=50):
    recent = candles_4h[-lookback:] if len(candles_4h) > lookback else candles_4h
    highs, lows = [], []
    for i in range(2, len(recent)-2):
        h = recent[i]["high"]; l = recent[i]["low"]
        if all(h >= recent[j]["high"] for j in [i-1,i-2,i+1,i+2]): highs.append(h)
        if all(l <= recent[j]["low"]  for j in [i-1,i-2,i+1,i+2]): lows.append(l)
    res = min([h for h in highs if h > price], default=price * 1.02)
    sup = max([l for l in lows  if l < price], default=price * 0.98)
    log.info(f"4H levels: support={sup:.2f} resistance={res:.2f}")
    return sup, res

# ── PREVIOUS DAY BOX ─────────────────────────────────────────────
def build_daily_box(candles_4h):
    if not candles_4h:
        return None
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    days = {}
    for c in candles_4h:
        d = datetime.fromtimestamp(c["time"]/1000, tz=timezone.utc).strftime("%Y-%m-%d")
        if d not in days:
            days[d] = {"high": c["high"], "low": c["low"]}
        else:
            days[d]["high"] = max(days[d]["high"], c["high"])
            days[d]["low"]  = min(days[d]["low"],  c["low"])
    sorted_dates = sorted(days.keys())
    log.info("Reconstructed daily dates: " + str(sorted_dates[-7:]))
    yesterday = next((d for d in reversed(sorted_dates) if d < today_str), None)
    if not yesterday:
        return None
    y   = days[yesterday]
    box = {"high": y["high"], "low": y["low"],
           "mid":  round((y["high"] + y["low"]) / 2, 2),
           "date": yesterday, "size": round(y["high"] - y["low"], 2)}
    log.info(f"Box: date={yesterday} H={box['high']:.2f} L={box['low']:.2f} MID={box['mid']:.2f}")
    state["box"] = box
    return box

# ── NEWS ──────────────────────────────────────────────────────────
NEWS_SOURCES = [
    "https://feeds.feedburner.com/CoinDesk",
    "https://cointelegraph.com/rss",
    "https://cryptonews.com/news/feed/",
    "https://www.newsbtc.com/feed/",
]

def fetch_news():
    headlines = []
    for url in NEWS_SOURCES:
        try:
            feed = feedparser.parse(url)
            for e in feed.entries[:4]:
                headlines.append(e.title)
        except Exception as ex:
            log.warning(f"News feed error: {ex}")
    state["last_news_headlines"] = headlines[:20]
    return headlines[:20]

def ai_news_score(headlines, signal_type, price, box):
    if not headlines or not ANTHROPIC_API_KEY:
        return 0, "No API key"
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        news_block = "\n".join(f"• {h}" for h in headlines)
        prompt = f"""Analyze crypto news for {signal_type} trade on BTC/USDT.
Price: ${price:,.2f} | Box: H=${box['high']:,.2f} MID=${box['mid']:,.2f} L=${box['low']:,.2f}

Headlines:
{news_block}

Return ONLY JSON: {{"score": <-2 to +2>, "summary": "<max 20 words>", "key_factor": "<headline>"}}
+2=very bullish, 0=neutral, -2=very bearish"""

        r    = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=150,
            messages=[{"role": "user", "content": prompt}]
        )
        text = r.content[0].text.strip().replace("```json","").replace("```","").strip()
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
        return 0, f"AI error: {str(e)[:60]}"

# ── TRADE EXECUTION ───────────────────────────────────────────────
balance_at_entry = 10000.0

def calc_qty(balance, risk_pct, entry, sl):
    risk_dist = abs(entry - sl)
    if risk_dist <= 0: return 0.001
    return max(round((balance * risk_pct) / risk_dist, 4), 0.001)

def execute_trade(signal, entry, sl, tp, qty, news_score, news_summary, has_div):
    global balance_at_entry
    if TRADING_MODE == "PAPER":
        order_id = place_order_paper(signal, qty, entry, sl, tp)
    else:
        order_id = place_order_live(signal, qty, sl, tp)
    if not order_id:
        return False
    state["position"] = {
        "type": signal, "entry": entry, "sl": sl, "tp": tp, "qty": qty,
        "time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "order_id": order_id, "news_score": news_score,
        "news_summary": news_summary, "has_divergence": has_div,
    }
    state["last_signal"]      = signal
    state["last_signal_time"] = datetime.now(timezone.utc).strftime("%H:%M UTC")
    save_state()

    risk_pct = RISK_PER_TRADE * 2 if has_div else RISK_PER_TRADE
    div_txt  = "🔥 DOUBLE (divergence)" if has_div else "Normal"
    send_telegram(
        f"{'🟢' if signal=='LONG' else '🔴'} <b>{signal} OPENED</b>\n"
        f"Entry: ${entry:,.2f}\n"
        f"TP:    ${tp:,.2f}\n"
        f"SL:    ${sl:,.2f}\n"
        f"Size:  {div_txt}\n"
        f"Risk:  {risk_pct*100:.0f}%\n"
        f"AI Score: {news_score}\n"
        f"📰 {news_summary[:80]}"
    )
    return True

def check_position(price):
    pos = state["position"]
    if not pos:
        return

    # FORCE CLOSE
    if os.environ.get("FORCE_CLOSE", "").lower() == "true":
        pnl = ((price - pos["entry"]) if pos["type"] == "LONG"
               else (pos["entry"] - price)) * pos["qty"]
        pnl = round(pnl, 2)
        state["pnl_total"] = round(state["pnl_total"] + pnl, 2)
        state["balance"]   = round(state["balance"]   + pnl, 2)
        if pnl >= 0: state["wins"]   += 1
        else:        state["losses"] += 1
        state["trades"].append({
            "type": pos["type"], "entry": pos["entry"], "close": price,
            "pnl": pnl, "result": "WIN" if pnl >= 0 else "LOSS",
            "time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "news_score": pos.get("news_score", 0),
            "divergence": pos.get("has_divergence", False),
        })
        send_telegram(
            f"🔵 <b>FORCE CLOSED</b> {pos['type']}\n"
            f"Price: ${price:,.2f}\n"
            f"PnL: {'+'if pnl>=0 else ''}${pnl:.2f}\n"
            f"Balance: ${state['balance']:,.2f}"
        )
        log.info(f"FORCE CLOSE: {pos['type']} pnl={pnl:+.2f}")
        state["position"] = None
        save_state()
        return

    # Safety check: TP/SL on correct side
    if pos["type"] == "LONG":
        if pos["tp"] <= pos["entry"] or pos["sl"] >= pos["entry"]:
            log.error(f"LONG wrong TP/SL - closing. entry={pos['entry']} tp={pos['tp']} sl={pos['sl']}")
            state["position"] = None
            save_state()
            return
    if pos["type"] == "SHORT":
        if pos["tp"] >= pos["entry"] or pos["sl"] <= pos["entry"]:
            log.error(f"SHORT wrong TP/SL - closing. entry={pos['entry']} tp={pos['tp']} sl={pos['sl']}")
            state["position"] = None
            save_state()
            return

    hit_tp = (pos["type"] == "LONG"  and price >= pos["tp"]) or \
             (pos["type"] == "SHORT" and price <= pos["tp"])
    hit_sl = (pos["type"] == "LONG"  and price <= pos["sl"]) or \
             (pos["type"] == "SHORT" and price >= pos["sl"])

    if not hit_tp and not hit_sl:
        return

    close_price = pos["tp"] if hit_tp else pos["sl"]
    pnl = ((close_price - pos["entry"]) if pos["type"] == "LONG"
           else (pos["entry"] - close_price)) * pos["qty"]
    pnl = round(pnl, 2)

    log.info(f"Position closed: {'TP ✅' if hit_tp else 'SL ❌'} | PnL={pnl:+.2f}")
    state["pnl_total"] = round(state["pnl_total"] + pnl, 2)
    state["balance"]   = round(state["balance"]   + pnl, 2)
    if hit_tp: state["wins"]   += 1
    else:      state["losses"] += 1

    state["trades"].append({
        "type": pos["type"], "entry": pos["entry"], "close": close_price,
        "pnl": pnl, "result": "WIN" if hit_tp else "LOSS",
        "time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "news_score": pos.get("news_score", 0),
        "divergence": pos.get("has_divergence", False),
    })

    wins = state["wins"]; losses = state["losses"]
    send_telegram(
        f"{'✅ <b>TAKE PROFIT</b>' if hit_tp else '❌ <b>STOP LOSS</b>'}\n"
        f"PnL: {'+'if pnl>=0 else ''}${pnl:.2f}\n"
        f"Balance: ${state['balance']:,.2f}\n"
        f"W/L: {wins}W/{losses}L | WR: {round(wins/(wins+losses)*100) if wins+losses>0 else 0}%"
    )

    if TRADING_MODE == "LIVE":
        close_position_live(pos["type"])

    state["position"] = None
    save_state()

# ── STRATEGY ─────────────────────────────────────────────────────
def run_strategy():
    global balance_at_entry
    rules = SMC_RULES

    price      = get_ticker()
    candles_1h = get_candles("1H", 200)
    candles_4h = get_candles("4H", 200)

    if len(candles_1h) < 50 or len(candles_4h) < 20:
        state["last_signal"] = "Not enough candle data"
        return

    # Check open position first
    if state["position"]:
        check_position(price)
        if state["position"]:
            pos = state["position"]
            pnl = (price - pos["entry"]) * pos["qty"] if pos["type"] == "LONG" \
                  else (pos["entry"] - price) * pos["qty"]
            state["last_signal"] = f"HOLDING {pos['type']} @ {pos['entry']:.2f} | PnL: {pnl:+.2f}"
            log.info(state["last_signal"])
            return

    # Build box
    box = build_daily_box(candles_4h)
    if not box:
        state["last_signal"] = "No box data"
        return

    # Indicators
    # Use closed 1H candles for RSI - consistent with strategy timeframe
    closes = [c["close"] for c in candles_1h]
    rsi    = calc_rsi(closes)
    log.info(f"RSI={rsi} price={price:.2f}")
    state["current_rsi"] = rsi

    bull_div, bear_div  = detect_rsi_divergence(candles_1h, lookback=20)
    support, resistance = find_4h_sr(candles_4h, price)
    balance             = get_balance()
    balance_at_entry    = balance

    log.info(f"Price={price:.2f} RSI={rsi} Box=[{box['low']:.2f}–{box['high']:.2f}] MID={box['mid']:.2f} | "
             f"BullDiv={bull_div} BearDiv={bear_div} | 4H Support={support:.2f} Resistance={resistance:.2f}")

    # ── SHORT: price within 0.5% of PDH + RSI > 70 ───────────────
    at_pdh          = (price >= box["high"] * 0.995) and (price <= box["high"] * 1.015)
    rsi_ob          = rsi > rules["pdbox_short_rsi_threshold"]
    short_makes_sense = box["mid"] < price
    log.info(f"SHORT check: price={price:.2f} PDH={box['high']:.2f} at_pdh={at_pdh} rsi={rsi} rsi_ok={rsi_ob}")

    if at_pdh and rsi_ob and short_makes_sense:
        sl = round(resistance * (1 + rules["sl_buffer"]), 2)
        tp = box["mid"]

        if tp >= price: tp = round(price * 0.99, 2)
        if sl <= price: sl = round(price * 1.01, 2)

        # MAX SL = 1.5% above entry
        if sl > price * (1 + rules["max_sl_pct"]):
            sl = round(price * (1 + rules["max_sl_pct"]), 2)
            log.info(f"SHORT SL capped at 1.5%: {sl}")

        risk_pct = RISK_PER_TRADE * 2 if bear_div else RISK_PER_TRADE
        qty      = calc_qty(balance, risk_pct, price, sl)
        log.info(f"SHORT: SL={sl} TP={tp} qty={qty} divergence={bear_div} risk={risk_pct*100:.0f}%")

        headlines      = fetch_news()
        score, summary = ai_news_score(headlines, "SHORT", price, box)
        send_telegram(f"📰 <b>News Update (SHORT)</b>\nScore: {score} | {summary[:80]}")

        ok = execute_trade("SHORT", price, sl, tp, qty, score, summary, bear_div)
        if not ok:
            state["last_signal"] = "SHORT - order failed"
        return

    # ── LONG: price within 0.5% of PDL + RSI < 30 ────────────────
    at_pdl         = (price <= box["low"] * 1.005) and (price >= box["low"] * 0.985)
    rsi_os         = rsi < rules["pdbox_long_rsi_threshold"]
    long_makes_sense = box["mid"] > price
    log.info(f"LONG check: price={price:.2f} PDL={box['low']:.2f} at_pdl={at_pdl} rsi={rsi} rsi_ok={rsi_os}")

    if at_pdl and rsi_os and long_makes_sense:
        sl = round(support * (1 - rules["sl_buffer"]), 2)
        tp = box["mid"]

        if tp <= price: tp = round(price * 1.01, 2)
        if sl >= price: sl = round(price * 0.99, 2)

        # MAX SL = 1.5% below entry
        if sl < price * (1 - rules["max_sl_pct"]):
            sl = round(price * (1 - rules["max_sl_pct"]), 2)
            log.info(f"LONG SL capped at 1.5%: {sl}")

        risk_pct = RISK_PER_TRADE * 2 if bull_div else RISK_PER_TRADE
        qty      = calc_qty(balance, risk_pct, price, sl)
        log.info(f"LONG: SL={sl} TP={tp} qty={qty} divergence={bull_div} risk={risk_pct*100:.0f}%")

        headlines      = fetch_news()
        score, summary = ai_news_score(headlines, "LONG", price, box)
        send_telegram(f"📰 <b>News Update (LONG)</b>\nScore: {score} | {summary[:80]}")

        ok = execute_trade("LONG", price, sl, tp, qty, score, summary, bull_div)
        if not ok:
            state["last_signal"] = "LONG - order failed"
        return

    # ── WAIT ──────────────────────────────────────────────────────
    div_txt = "📊 Div detected!" if (bull_div or bear_div) else "No div"
    state["last_signal"] = f"WAIT | RSI={rsi} | Box [{box['low']:.0f}–{box['high']:.0f}] | {div_txt}"
    log.info(state["last_signal"])

# ── BOT LOOP ─────────────────────────────────────────────────────
def bot_loop():
    log.info("=======================================")
    log.info("  SMC AI BOT v2 - Bitget | Railway")
    log.info(f"  Mode: {TRADING_MODE} | Leverage: {LEVERAGE}x")
    log.info(f"  Balance: ${state['balance']:.2f} | Wins: {state['wins']} Losses: {state['losses']}")
    log.info("=======================================")

    send_telegram(
        f"⚡ <b>SMC AI Bot Started</b>\n"
        f"Mode: {TRADING_MODE}\n"
        f"Balance: ${state['balance']:.2f}\n"
        f"W/L: {state['wins']}W / {state['losses']}L\n"
        f"Strategy: PDH/PDL Box + RSI + Divergence\n"
        f"SL: max 1.5% from entry 🔒"
    )

    while state["running"]:
        try:
            state["last_cycle"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            run_strategy()
        except Exception as e:
            log.error(f"Strategy error: {e}")
            state["errors"].append(f"{datetime.now(timezone.utc).strftime('%H:%M')} {str(e)[:80]}")
            state["errors"] = state["errors"][-10:]

        cycle = int(os.environ.get("CYCLE_SECONDS", "60"))
        save_state()
        log.info(f"Next cycle in {cycle}s")
        time.sleep(cycle)

bot_thread = threading.Thread(target=bot_loop, daemon=True)
