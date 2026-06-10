"""
bot.py - SMC AI Trading Bot v3
WebSocket real-time price + RSI from Bitget
Strategy A: Daily box + 1H RSI
Strategy B: 1H box + 15m RSI
"""

import os
import json
import copy
import time
import logging
import threading
import requests
import feedparser
import websocket
from collections import deque
from datetime import datetime, timezone
import anthropic
from config import *
from database import init_db, seed_if_empty, db_load_state, db_save_state, db_save_trade, db_get_user_ai_settings

# ── AI Validator ─────────────────────────────────────────────────
# Master switches (env vars) — αν OFF παντού, AI απενεργοποιείται για ΟΛΟΥΣ
# Per-user settings στη DB υπερισχύουν αν master = ON
AI_VALIDATOR_MASTER  = os.environ.get("AI_VALIDATOR_ENABLED", "true").lower() == "true"
AI_SHADOW_MASTER     = os.environ.get("AI_SHADOW_MODE", "true").lower() == "true"

# Κρατάμε τα παλιά ονόματα για backwards compat με τυχόν άλλα modules
AI_VALIDATOR_ENABLED = AI_VALIDATOR_MASTER
AI_SHADOW_MODE       = AI_SHADOW_MASTER

# ── Operational constants (named, ώστε να μη μένουν "magic numbers") ──
MIN_ORDER_QTY           = 0.001  # ελάχιστο μέγεθος θέσης (BTC)
ERROR_HISTORY_LIMIT     = 10     # πόσα πρόσφατα σφάλματα κρατάμε ανά στρατηγική
DEFAULT_CYCLE_SECONDS   = 60     # default περίοδος σάρωσης Strategy A (env CYCLE_SECONDS)
SCHEDULER_SLEEP_SECONDS = 30     # ύπνος μεταξύ κύκλων του scheduler loop

def _ai_validate(strategy, side, entry_price, stop_loss, take_profit,
                 rsi_15m, rsi_1h, box, has_divergence, trades, balance,
                 initial_balance=10000.0, candles_4h=None, extra=None,
                 user_id=1, candles_15m=None):
    """
    Καλεί το AI Validator. Επιστρέφει (action, size_multiplier, result_obj).
    
    Λογική απόφασης (cascade):
      1. Master OFF       → return GO (κανείς δεν τρέχει AI)
      2. User off         → return GO (αυτός ο user δεν θέλει AI)
      3. Shadow (any)     → AI τρέχει, logs, αλλά return GO
      4. Normal          → AI τρέχει και η απόφαση εφαρμόζεται
    """
    # ── 1. Master switch ─────────────────────────────────────
    if not AI_VALIDATOR_MASTER:
        return "GO", 1.0, None
    
    # ── 2. Per-user settings (από DB) ────────────────────────
    try:
        user_ai = db_get_user_ai_settings(user_id)
    except Exception as e:  # broad on purpose: any DB failure → fall back to safe defaults
        log.warning(f"[AIValidator] Could not read user settings: {e} — using defaults")
        user_ai = {"ai_validator_enabled": True, "ai_shadow_mode": True}
    
    if not user_ai["ai_validator_enabled"]:
        log.debug(f"[AIValidator] user_id={user_id} has AI disabled — skipping")
        return "GO", 1.0, None
    
    # ── 3. Shadow mode (master OR user) ──────────────────────
    # Αν είτε ο master είτε ο user έχει shadow ON → shadow mode
    shadow_active = AI_SHADOW_MASTER or user_ai["ai_shadow_mode"]
    
    try:
        from ai_validator import validate_signal
        result = validate_signal(
            strategy     = strategy,
            user_id      = user_id,
            symbol       = BITGET_SYMBOL,
            side         = side,
            entry_price  = entry_price,
            stop_loss    = stop_loss,
            take_profit  = take_profit,
            context      = {
                "rsi_15m":           rsi_15m,
                "rsi_1h":            rsi_1h,
                "current_price":     entry_price,
                "last_price_update": time.time(),
                "trades":            trades[-50:] if trades else [],
                "has_divergence":    has_divergence,
                "box":               box or {},
                "candles_4h":        candles_4h or [],
                "candles_15m":       candles_15m or [],
                "candles_1h":        get_candles("1H",  50) or [],
                "candles_5m":        get_candles("5m",  50) or [],
                "candles_1d":        get_candles("1D",  30) or [],
                "extra":             extra or {},
            },
            user_settings = {
                "balance":         balance,
                "initial_balance": initial_balance,
                "risk_percent":    RISK_PER_TRADE * 100,
                "trading_mode":    TRADING_MODE,
            },
            shadow_mode = shadow_active,
        )
        action = result.action
        mult   = result.size_multiplier
        log.info(
            f"[AIValidator] [{strategy}] user={user_id} {side} → {action} "
            f"(conf={result.confidence:.2f}, {result.processing_time_ms}ms) "
            f"{'[SHADOW]' if shadow_active else '[ACTIVE]'}"
        )
        # Telegram notification για σημαντικές αποφάσεις
        if action in ("SKIP", "DOUBLE_SIZE") or (action == "REDUCE_SIZE" and not shadow_active):
            shadow_tag = " [SHADOW]" if shadow_active else ""
            reason = list(result.reasoning.values())[0] if result.reasoning else ""
            send_telegram(
                f"🤖 <b>[AI{shadow_tag}] {strategy} {action}</b>\n"
                f"{side} @ ${entry_price:,.0f}\n"
                f"{reason[:100]}"
            )
        if shadow_active:
            return "GO", 1.0, result   # shadow: εκτέλεση κανονικά
        return action, mult, result
    except Exception as e:  # broad on purpose: AI layer must never block a trade → default GO
        log.error(f"[AIValidator] Error: {e} — defaulting to GO")
        return "GO", 1.0, None

def _send_ai_trade_summary(strategy, side, entry_price, sl, tp,
                           ai_action, ai_result, shadow_active):
    """Στέλνει AI analysis Telegram message σε κάθε νέο trade."""
    icons = {"GO":"✅","SKIP":"🚫","REDUCE_SIZE":"📉","DOUBLE_SIZE":"🚀"}
    icon  = icons.get(ai_action, "🤖")
    shadow_tag = " SHADOW" if shadow_active else " ACTIVE"
    if ai_result is None:
        send_telegram(icon + " [AI] " + strategy + " " + side + " — Validator off")
        return

    conf  = str(int(ai_result.confidence * 100)) + "%"
    r     = ai_result.reasoning or {}
    tech  = str(r.get("technical",   "N/A"))
    news  = str(r.get("news",        "N/A"))
    coord = str(r.get("coordinator", "N/A"))

    # ── Εξαγωγή score και strengths/weaknesses από technical ──
    score_str = ""
    strengths_str = ""
    weaknesses_str = ""
    try:
        tech_data = r.get("technical", {})
        if isinstance(tech_data, dict):
            score      = tech_data.get("score", "?")
            summary    = tech_data.get("summary", "")
            strengths  = tech_data.get("strengths",  [])
            weaknesses = tech_data.get("weaknesses", [])
            score_str  = f"Score={score}/10 | {summary}"
            if strengths:
                strengths_str  = "✅ " + " | ".join(str(s)[:45] for s in strengths[:2])
            if weaknesses:
                weaknesses_str = "⚠️ " + " | ".join(str(w)[:45] for w in weaknesses[:2])
        else:
            # Fallback: string format
            score_str = str(tech_data)[:80]
    except (AttributeError, KeyError, TypeError, ValueError, IndexError):
        score_str = tech[:80]

    # ── News score extraction ──
    news_short = news[:100] if news else "N/A"

    # ── Coordinator short ──
    coord_short = coord[:120] if coord else "N/A"

    # ── Assemble message ──
    parts = [
        icon + " <b>[AI" + shadow_tag + "] " + strategy + " " + ai_action + "</b>",
        "<b>" + side + "</b> @ $" + f"{entry_price:,.0f}" + " | Conf: " + conf,
        "",
        "📊 <b>Tech:</b> " + (score_str or tech[:60]),
    ]

    if strengths_str:
        parts.append("   " + strengths_str)
    if weaknesses_str:
        parts.append("   " + weaknesses_str)

    parts += [
        "📰 <b>News:</b> " + news_short,
        "🎯 " + coord_short,
    ]

    send_telegram("\n".join(parts))


# -- LOGGING ------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# -- TELEGRAM -----------------------------------------------------
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
    except requests.RequestException as e:
        log.warning(f"Telegram error: {e}")

# -- BITGET API ---------------------------------------------------
BITGET_BASE      = "https://api.bitget.com"
BITGET_SYMBOL    = "BTCUSDT"
BITGET_PROD_TYPE = "USDT-FUTURES"

def bitget_get(path, params=None):
    try:
        r = requests.get(BITGET_BASE + path, params=params, timeout=10)
        return r.json()
    except (requests.RequestException, ValueError) as e:
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
    headers = {
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
    except (requests.RequestException, ValueError) as e:
        log.error(f"Bitget signed error: {e}")
        return {}

def get_candles(granularity, limit=500):
    gran_map = {"1H": "1H", "4H": "4H", "1D": "1D", "15m": "15m", "5m": "5m"}
    gran     = gran_map.get(granularity, "1H")
    r        = bitget_get("/api/v2/mix/market/candles", {
        "symbol": BITGET_SYMBOL, "productType": BITGET_PROD_TYPE,
        "granularity": gran, "limit": str(limit),
    })
    raw = r.get("data", [])
    if not raw:
        log.warning(f"No candles. gran={gran}")
        return []
    candles = []
    for c in raw:
        try:
            candles.append({
                "time": int(c[0]), "open": float(c[1]),
                "high": float(c[2]), "low": float(c[3]),
                "close": float(c[4]), "volume": float(c[5]),
            })
        except (ValueError, TypeError, IndexError):
            pass
    # Sort by time ascending (oldest first) regardless of API order
    candles.sort(key=lambda x: x["time"])
    if candles:
        log.debug(f"Candles {gran}: {len(candles)} total, "
                  f"first={datetime.fromtimestamp(candles[0]['time']/1000,tz=timezone.utc).strftime('%m-%d %H:%M')} "
                  f"last={datetime.fromtimestamp(candles[-1]['time']/1000,tz=timezone.utc).strftime('%m-%d %H:%M')}")
    return candles

def place_order_paper(side, qty, entry, sl, tp):
    log.info(f"[PAPER] {side} qty={qty:.4f} @ {entry:.2f} SL={sl:.2f} TP={tp:.2f}")
    return f"PAPER_{int(time.time())}"

# ─────────────────────────────────────────────────────────────────────────────
# LEGACY GLOBAL LIVE PATH — DISABLED (fail-closed).
# Όλο το live ordering περνά πλέον ΑΠΟΚΛΕΙΣΤΙΚΑ από per-strategy, allowlisted
# clients με κρυπτογραφημένα dashboard keys (βλ. place_order_live_c). Αυτές οι
# δύο global env-key συναρτήσεις (που τις μοιράζονταν A/B/CM/SMC) απενεργοποιούνται
# ώστε ΚΑΜΙΑ στρατηγική εκτός allowlist να μην έχει προσβάσιμο live path —
# ακόμη κι αν κάποιος ορίσει TRADING_MODE=LIVE.
# ─────────────────────────────────────────────────────────────────────────────
def place_order_live(side, qty, sl, tp):
    log.error("[SAFETY] global place_order_live is DISABLED — live ordering is "
              "per-strategy & allowlisted (LIVE_STRATEGIES). Refusing.")
    return None

def close_position_live(side, qty):
    log.error("[SAFETY] global close_position_live is DISABLED — refusing.")
    return None

# =================================================================
# REAL-TIME DATA via WebSocket + REST history
# =================================================================

class RealtimeData:
    def __init__(self):
        self.lock        = threading.Lock()
        self.closes_1h   = deque(maxlen=600)
        self.closes_15m  = deque(maxlen=600)
        self.closes_4h   = deque(maxlen=600)
        self.price       = 0.0
        self.rsi_1h      = 50.0
        self.rsi_15m     = 50.0
        self.initialized = False
        self.ws          = None   # live WebSocketApp (for the heartbeat thread)

    def _calc_rsi(self, closes, period=14):
        """
        Wilder RSI - identical to TradingView.
        Needs minimum 100 candles for accurate result.
        """
        closes = list(closes)
        n = len(closes)
        if n < period + 1:
            return 50.0

        # Calculate all price changes
        changes = [closes[i] - closes[i-1] for i in range(1, n)]

        # Seed with first `period` changes
        gains  = [max(c, 0) for c in changes[:period]]
        losses = [max(-c, 0) for c in changes[:period]]
        ag = sum(gains)  / period
        al = sum(losses) / period

        # Wilder smoothing over remaining changes
        for c in changes[period:]:
            ag = (ag * (period - 1) + max(c,  0)) / period
            al = (al * (period - 1) + max(-c, 0)) / period

        if al == 0:
            return 100.0
        return round(100 - 100 / (1 + ag / al), 2)

    def _update_rsi(self):
        with self.lock:
            c1h  = list(self.closes_1h)
            c15m = list(self.closes_15m)
        # Append live price as current open candle (like TradingView does)
        # History already contains only CLOSED candles
        # So we append current price to simulate the real-time RSI
        if self.price > 0:
            self.rsi_1h  = self._calc_rsi(c1h  + [self.price])
            self.rsi_15m = self._calc_rsi(c15m + [self.price])
        else:
            self.rsi_1h  = self._calc_rsi(c1h)
            self.rsi_15m = self._calc_rsi(c15m)

    def load_history(self):
        log.info("Loading candle history (500 candles each)...")
        for gran, attr in [("1H","closes_1h"), ("15m","closes_15m"), ("4H","closes_4h")]:
            candles = get_candles(gran, 500)
            if candles:
                # Exclude last candle - it may be currently open (not closed yet)
                # Only use confirmed closed candles for RSI history
                closed = candles[:-1]
                with self.lock:
                    getattr(self, attr).extend([c["close"] for c in closed])
                log.info(f"Loaded {len(closed)} {gran} closed candles (excluded current open)")
        r = bitget_get("/api/v2/mix/market/ticker", {
            "symbol": BITGET_SYMBOL, "productType": BITGET_PROD_TYPE
        })
        try:
            self.price = float(r["data"][0]["lastPr"])
        except (KeyError, IndexError, TypeError, ValueError):
            pass
        self._update_rsi()
        self.initialized = True
        # Log detailed info to verify RSI accuracy
        with self.lock:
            c1h  = list(self.closes_1h)
            c15m = list(self.closes_15m)
        log.info(f"Ready: price={self.price:.2f} RSI_1H={self.rsi_1h} RSI_15m={self.rsi_15m}")
        log.info(f"1H closes: count={len(c1h)} first={c1h[0]:.2f} last={c1h[-1]:.2f}")
        log.info(f"15m closes: count={len(c15m)} first={c15m[0]:.2f} last={c15m[-1]:.2f}")
        log.info(f"1H last 5 closes: {[round(x,2) for x in c1h[-5:]]}")
        log.info(f"RSI with live price appended: 1H={self._calc_rsi(c1h+[self.price])} 15m={self._calc_rsi(c15m+[self.price])}")

    def on_ws_message(self, ws, message):
        try:
            # Bitget app-level heartbeat reply is plain text "pong" (and we may
            # echo "ping") — not JSON. Handle before json.loads so it doesn't
            # spam "WS parse error".
            if isinstance(message, str) and message.strip() in ("pong", "ping"):
                return
            data = json.loads(message)
            if "data" not in data:
                return
            arg   = data.get("arg", {})
            chan  = arg.get("channel", "")
            items = data["data"]

            for item in items:
                # Ticker - live price
                if chan == "ticker" and "lastPr" in item:
                    self.price = float(item["lastPr"])
                    self._update_rsi()  # recalculate RSI with live price

                # Candle closed (confirm=1)
                elif chan.startswith("candle") and isinstance(item, list) and len(item) >= 5:
                    # Bitget candle ws: [ts, o, h, l, c, vol, quoteVol, confirm]
                    # confirm=1 means candle is CLOSED
                    confirm = str(item[7]) if len(item) >= 8 else "0"
                    close_price = float(item[4])
                    if confirm == "1":
                        # Candle confirmed closed - add to history only
                        # Do NOT update self.price - live price comes from ticker
                        if "1H"  in chan:
                            with self.lock: self.closes_1h.append(close_price)
                            log.info(f"1H candle CLOSED: {close_price:.2f}")
                            self._update_rsi()
                            log.info(f"RSI after 1H close: 1H={self.rsi_1h}")
                        elif "15m" in chan:
                            with self.lock: self.closes_15m.append(close_price)
                            log.info(f"15m candle CLOSED: {close_price:.2f}")
                            self._update_rsi()
                            log.info(f"RSI after 15m close: 15m={self.rsi_15m}")
                        elif "4H"  in chan:
                            with self.lock: self.closes_4h.append(close_price)
        except (json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError) as e:
            log.warning(f"WS parse error: {e}")

    def start_websocket(self):
        def run():
            while True:
                try:
                    ws = websocket.WebSocketApp(
                        "wss://ws.bitget.com/v2/ws/public",
                        on_open    = self._on_open,
                        on_message = self.on_ws_message,
                        on_error   = lambda ws, e: log.error(f"WS error: {e}"),
                        on_close   = lambda ws, *a: log.warning("WS closed - reconnecting"),
                    )
                    self.ws = ws  # expose to the heartbeat thread
                    ws.run_forever(
                        ping_interval=15,
                        ping_timeout=8,
                        reconnect=5,
                    )
                except Exception as e:  # broad on purpose: reconnect loop must never die
                    log.error(f"WS run error: {e}")
                finally:
                    self.ws = None
                time.sleep(3)

        threading.Thread(target=run, daemon=True).start()

        # Bitget keepalive: the server expects an APPLICATION-LEVEL "ping" text
        # frame (it replies "pong"). The websocket protocol ping above is NOT
        # Bitget's heartbeat — without this, Bitget drops the connection after its
        # grace window (the ~2-3 min reconnect sawtooth seen in the deploy logs).
        # Send every 20s (Bitget's limit is 30s); a failed send surfaces a dead
        # socket so run_forever can reconnect.
        def keep_alive():
            while True:
                time.sleep(20)
                ws = self.ws
                if ws is None:
                    continue
                try:
                    ws.send("ping")
                except Exception as e:  # broad on purpose: dead socket → reconnect handles it
                    log.warning(f"WS heartbeat send failed: {e}")

        threading.Thread(target=keep_alive, daemon=True).start()
        log.info("WebSocket started")

    def _on_open(self, ws):
        log.info("WebSocket connected - subscribing...")
        ws.send(json.dumps({
            "op": "subscribe",
            "args": [
                {"instType": "USDT-FUTURES", "channel": "ticker",   "instId": "BTCUSDT"},
                {"instType": "USDT-FUTURES", "channel": "candle1H", "instId": "BTCUSDT"},
                {"instType": "USDT-FUTURES", "channel": "candle15m","instId": "BTCUSDT"},
                {"instType": "USDT-FUTURES", "channel": "candle4H", "instId": "BTCUSDT"},
            ]
        }))

    def start_polling(self):
        """Fallback price polling every 3s."""
        def poll():
            while True:
                try:
                    r = bitget_get("/api/v2/mix/market/ticker", {
                        "symbol": BITGET_SYMBOL, "productType": BITGET_PROD_TYPE
                    })
                    self.price = float(r["data"][0]["lastPr"])
                    self._update_rsi()  # keep RSI fresh via polling too
                except Exception:  # broad on purpose: fallback polling loop must never die
                    pass
                time.sleep(3)
        threading.Thread(target=poll, daemon=True).start()

rt = RealtimeData()

# =================================================================
# INDICATORS
# =================================================================

def detect_divergence(closes_list, highs, lows, lookback=20):
    if len(closes_list) < lookback + 2:
        return False, False
    rsi_vals = []
    for i in range(max(0, len(closes_list)-lookback), len(closes_list)):
        rsi_vals.append(rt._calc_rsi(closes_list[:i+1]))

    h = highs[-lookback:] if len(highs) >= lookback else highs
    l = lows[-lookback:]  if len(lows)  >= lookback else lows

    ph, rh, pl, rl = [], [], [], []
    for i in range(1, len(h)-1):
        if h[i] > h[i-1] and h[i] > h[i+1]:
            ph.append(h[i]); rh.append(rsi_vals[i] if i < len(rsi_vals) else 50)
        if l[i] < l[i-1] and l[i] < l[i+1]:
            pl.append(l[i]); rl.append(rsi_vals[i] if i < len(rsi_vals) else 50)

    bear = len(ph)>=2 and ph[-1]>ph[-2] and rh[-1]<rh[-2]
    bull = len(pl)>=2 and pl[-1]<pl[-2] and rl[-1]>rl[-2]
    if bear: log.info(f"Bearish div: price {ph[-2]:.0f}->{ph[-1]:.0f} RSI {rh[-2]:.1f}->{rh[-1]:.1f}")
    if bull: log.info(f"Bullish div: price {pl[-2]:.0f}->{pl[-1]:.0f} RSI {rl[-2]:.1f}->{rl[-1]:.1f}")
    return bull, bear

def detect_divergence_b(closes, highs, lows, window=5):
    """
    Strategy-B-specific divergence: causal ±window swing detection.

    Διαφέρει από το detect_divergence (που το μοιράζονται A/main) — εκείνο
    χρησιμοποιεί ±1 pivots. Η B v2 θέλει confirmed ±5 swings, χωρίς look-ahead
    (HANDOFF). Κρατιέται ξεχωριστή ώστε να μην αλλάξει σιωπηλά η συμπεριφορά
    της A. Τα closes/highs/lows πρέπει να είναι aligned by candle index.

    Χτίζει causal RSI series (RSI όπως ήταν στο close κάθε κεριού) και delegate
    στο strategies.strategy_b.swing_divergence.
    """
    from strategies.strategy_b import swing_divergence
    n = min(len(closes), len(highs), len(lows))
    if n < 2 * window + 2:
        return False, False
    rsi_series = [rt._calc_rsi(closes[:i + 1]) for i in range(n)]
    return swing_divergence(highs[:n], lows[:n], rsi_series, window)

def find_4h_sr(candles_4h, price, lookback=50):
    recent = candles_4h[-lookback:] if len(candles_4h)>lookback else candles_4h
    highs, lows = [], []
    for i in range(2, len(recent)-2):
        h = recent[i]["high"]; l = recent[i]["low"]
        if all(h >= recent[j]["high"] for j in [i-1,i-2,i+1,i+2]): highs.append(h)
        if all(l <= recent[j]["low"]  for j in [i-1,i-2,i+1,i+2]): lows.append(l)
    res = min([h for h in highs if h > price], default=price*1.02)
    sup = max([l for l in lows  if l < price], default=price*0.98)
    log.info(f"4H S/R: sup={sup:.2f} res={res:.2f}")
    return sup, res

def build_daily_box(candles_4h):
    if not candles_4h: return None
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    days  = {}
    for c in candles_4h:
        d = datetime.fromtimestamp(c["time"]/1000, tz=timezone.utc).strftime("%Y-%m-%d")
        if d not in days: days[d] = {"high": c["high"], "low": c["low"]}
        else:
            days[d]["high"] = max(days[d]["high"], c["high"])
            days[d]["low"]  = min(days[d]["low"],  c["low"])
    sorted_d = sorted(days.keys())
    log.info("Daily dates: " + str(sorted_d[-5:]))
    yest = next((d for d in reversed(sorted_d) if d < today), None)
    if not yest: return None
    y = days[yest]
    box = {"high": y["high"], "low": y["low"],
           "mid":  round((y["high"]+y["low"])/2, 2),
           "date": yest, "size": round(y["high"]-y["low"], 2)}
    log.info(f"Daily Box: {yest} H={box['high']:.2f} L={box['low']:.2f} MID={box['mid']:.2f}")
    return box

def build_1h_box(candles_1h):
    if len(candles_1h) < 2: return None
    p = candles_1h[-2]
    box = {"high": p["high"], "low": p["low"],
           "mid":  round((p["high"]+p["low"])/2, 2),
           "size": round(p["high"]-p["low"], 2),
           "time": datetime.fromtimestamp(p["time"]/1000, tz=timezone.utc).strftime("%H:%M UTC")}
    log.info(f"1H Box: H={box['high']:.2f} L={box['low']:.2f} MID={box['mid']:.2f}")
    return box

# =================================================================
# PERSISTENT STATE
# =================================================================

STATE_FILE   = "/app/bot_state.json"
STATE_FILE_B = "/app/bot_state_b.json"

SAVED_STATE = {
    "balance": 9949.11,
    "pnl_total": -50.89,
    "wins": 3,
    "losses": 1,
    "position": None,
    "trades": [
        {"close":79452.85,"divergence":False,"entry":80865.3,"news_score":0,
         "pnl":151.56,"result":"WIN","time":"2026-05-08 02:18","type":"SHORT"},
        {"close":76835.22,"divergence":False,"entry":78005.3,"news_score":0,
         "note":"STOP LOSS","pnl":-203.01,"result":"LOSS","time":"2026-05-18 01:34","type":"LONG"},
        {"close":76780.1,"divergence":False,"entry":76780.1,"news_score":1,
         "note":"STOP LOSS","pnl":0.0,"result":"WIN","time":"2026-05-19 01:26","type":"LONG"},
    ],
}

DEFAULT_STATE = {
    "mode": TRADING_MODE, "leverage": LEVERAGE, "position": None,
    "last_signal": "Starting...", "last_signal_time": "",
    "last_news_score": 0, "last_news_summary": "", "last_news_headlines": [],
    "trades": [], "balance": 10000.0, "pnl_total": 0.0,
    "wins": 0, "losses": 0, "box": None, "current_price": 0.0,
    "current_rsi": 50.0, "last_cycle": "", "errors": [], "last_divergence": False,
}

DEFAULT_STATE_B = {
    "position": None,          # Phase-1 compat mirror (= positions[0] or None)
    "positions": [],           # v2 multi-position: up to CONFIG["max_positions"]
    "last_entry_candle_ts": None,  # candle-close gate marker
    "last_signal": "Starting...", "last_signal_time": "",
    "trades": [], "balance": 10000.0, "pnl_total": 0.0,
    "wins": 0, "losses": 0, "box": None, "current_rsi": 50.0,
    "current_price": 0.0, "last_cycle": "", "errors": [], "last_divergence": False,
    "trailing_enabled": True,
}

SAVED_STATE_B = {
    "balance": 17210.56,
    "pnl_total": 7210.56,
    "wins": 29,
    "losses": 24,
    "position": None,
    "trades": [
        {"close":77691.0,"divergence":True,"entry":77691.0,"note":"STOP LOSS","pnl":0.0,"result":"WIN","time":"2026-05-17 23:40","type":"LONG"},
        {"close":76853.45,"divergence":True,"entry":77263.4,"note":"STOP LOSS","pnl":-399.99,"result":"LOSS","time":"2026-05-17 23:42","type":"LONG"},
        {"close":76826.6,"divergence":True,"entry":76826.6,"note":"STOP LOSS","pnl":0.0,"result":"WIN","time":"2026-05-18 01:33","type":"LONG"},
        {"close":77164.9,"divergence":False,"entry":76813.6,"note":"TAKE PROFIT","pnl":384.01,"result":"WIN","time":"2026-05-18 02:08","type":"LONG"},
        {"close":76978.18,"divergence":True,"entry":76982.0,"note":"STOP LOSS","pnl":-399.36,"result":"LOSS","time":"2026-05-18 02:22","type":"LONG"},
        {"close":76989.65,"divergence":True,"entry":76937.3,"note":"TAKE PROFIT","pnl":766.62,"result":"WIN","time":"2026-05-18 02:23","type":"LONG"},
        {"close":76979.23,"divergence":False,"entry":76982.7,"note":"STOP LOSS","pnl":-207.03,"result":"LOSS","time":"2026-05-18 02:30","type":"LONG"},
        {"close":76989.65,"divergence":False,"entry":76971.5,"note":"TAKE PROFIT","pnl":405.99,"result":"WIN","time":"2026-05-18 02:31","type":"LONG"},
        {"close":76989.65,"divergence":False,"entry":76981.7,"note":"TAKE PROFIT","pnl":422.54,"result":"WIN","time":"2026-05-18 02:33","type":"LONG"},
        {"close":76980.58,"divergence":False,"entry":76983.6,"note":"STOP LOSS","pnl":-219.46,"result":"LOSS","time":"2026-05-18 02:34","type":"LONG"},
        {"close":76969.33,"divergence":False,"entry":76976.1,"note":"STOP LOSS","pnl":-215.07,"result":"LOSS","time":"2026-05-18 02:35","type":"LONG"},
        {"close":76940.38,"divergence":False,"entry":76956.8,"note":"STOP LOSS","pnl":-210.77,"result":"LOSS","time":"2026-05-18 02:36","type":"LONG"},
        {"close":76904.23,"divergence":True,"entry":76932.7,"note":"STOP LOSS","pnl":-413.1,"result":"LOSS","time":"2026-05-18 02:36","type":"LONG"},
        {"close":76821.12,"divergence":True,"entry":76877.3,"note":"STOP LOSS","pnl":-396.57,"result":"LOSS","time":"2026-05-18 02:40","type":"LONG"},
        {"close":76721.98,"divergence":True,"entry":76811.2,"note":"STOP LOSS","pnl":-380.71,"result":"LOSS","time":"2026-05-18 02:52","type":"LONG"},
        {"close":76989.65,"divergence":True,"entry":76719.2,"note":"TAKE PROFIT","pnl":731.0,"result":"WIN","time":"2026-05-18 03:46","type":"LONG"},
        {"close":76936.6,"divergence":False,"entry":76931.5,"note":"TAKE PROFIT","pnl":394.72,"result":"WIN","time":"2026-05-18 03:49","type":"LONG"},
        {"close":76924.15,"divergence":False,"entry":76928.3,"note":"STOP LOSS","pnl":-205.26,"result":"LOSS","time":"2026-05-18 03:52","type":"LONG"},
        {"close":76883.8,"divergence":False,"entry":76883.8,"note":"STOP LOSS","pnl":0.0,"result":"WIN","time":"2026-05-18 03:56","type":"LONG"},
        {"close":76936.6,"divergence":False,"entry":76881.8,"note":"TAKE PROFIT","pnl":402.3,"result":"WIN","time":"2026-05-18 03:58","type":"LONG"},
        {"close":76936.6,"divergence":False,"entry":76908.5,"note":"TAKE PROFIT","pnl":418.39,"result":"WIN","time":"2026-05-18 04:00","type":"LONG"},
        {"close":76831.23,"divergence":False,"entry":76852.2,"note":"STOP LOSS","pnl":-217.57,"result":"LOSS","time":"2026-05-18 04:23","type":"LONG"},
        {"close":76767.93,"divergence":False,"entry":76810.0,"note":"STOP LOSS","pnl":-213.21,"result":"LOSS","time":"2026-05-18 04:28","type":"LONG"},
        {"close":76894.15,"divergence":False,"entry":76764.5,"note":"TAKE PROFIT","pnl":417.93,"result":"WIN","time":"2026-05-18 04:40","type":"LONG"},
        {"close":76894.15,"divergence":False,"entry":76889.4,"note":"TAKE PROFIT","pnl":433.7,"result":"WIN","time":"2026-05-18 04:51","type":"LONG"},
        {"close":76901.45,"divergence":True,"entry":76900.0,"note":"TAKE PROFIT","pnl":897.74,"result":"WIN","time":"2026-05-18 05:42","type":"LONG"},
        {"close":76901.45,"divergence":True,"entry":76878.9,"note":"TAKE PROFIT","pnl":975.31,"result":"WIN","time":"2026-05-18 05:43","type":"LONG"},
        {"close":76901.45,"divergence":False,"entry":76867.1,"note":"TAKE PROFIT","pnl":527.04,"result":"WIN","time":"2026-05-18 05:46","type":"LONG"},
        {"close":76901.45,"divergence":False,"entry":76888.1,"note":"TAKE PROFIT","pnl":548.38,"result":"WIN","time":"2026-05-18 05:52","type":"LONG"},
        {"close":76901.45,"divergence":False,"entry":76895.8,"note":"TAKE PROFIT","pnl":570.91,"result":"WIN","time":"2026-05-18 05:56","type":"LONG"},
        {"close":76888.48,"divergence":False,"entry":76892.8,"note":"STOP LOSS","pnl":-296.37,"result":"LOSS","time":"2026-05-18 05:58","type":"LONG"},
        {"close":76869.43,"divergence":False,"entry":76880.1,"note":"STOP LOSS","pnl":-290.44,"result":"LOSS","time":"2026-05-18 05:59","type":"LONG"},
        {"close":76901.45,"divergence":False,"entry":76866.1,"note":"TAKE PROFIT","pnl":569.43,"result":"WIN","time":"2026-05-18 06:00","type":"LONG"},
        {"close":76900.3,"divergence":False,"entry":76919.9,"note":"STOP LOSS","pnl":-296.02,"result":"LOSS","time":"2026-05-18 06:03","type":"LONG"},
        {"close":76870.6,"divergence":False,"entry":76900.1,"note":"STOP LOSS","pnl":-290.1,"result":"LOSS","time":"2026-05-18 06:04","type":"LONG"},
        {"close":76814.95,"divergence":False,"entry":76863.0,"note":"STOP LOSS","pnl":-284.3,"result":"LOSS","time":"2026-05-18 06:05","type":"LONG"},
        {"close":76713.85,"divergence":False,"entry":76795.6,"note":"STOP LOSS","pnl":-278.61,"result":"LOSS","time":"2026-05-18 06:08","type":"LONG"},
        {"close":76588.45,"divergence":False,"entry":76712.0,"note":"STOP LOSS","pnl":-273.05,"result":"LOSS","time":"2026-05-18 06:10","type":"LONG"},
        {"close":76959.1,"divergence":False,"entry":76575.8,"note":"TAKE PROFIT","pnl":535.16,"result":"WIN","time":"2026-05-18 07:00","type":"LONG"},
        {"close":76755.05,"divergence":False,"entry":76740.2,"note":"TAKE PROFIT","pnl":556.19,"result":"WIN","time":"2026-05-18 07:21","type":"LONG"},
        {"close":76896.82,"divergence":False,"entry":76900.0,"note":"STOP LOSS","pnl":-289.41,"result":"LOSS","time":"2026-05-18 08:36","type":"LONG"},
        {"close":76906.35,"divergence":False,"entry":76873.5,"note":"TAKE PROFIT","pnl":567.07,"result":"WIN","time":"2026-05-18 08:38","type":"LONG"},
        {"close":76906.35,"divergence":False,"entry":76899.1,"note":"TAKE PROFIT","pnl":590.74,"result":"WIN","time":"2026-05-18 08:39","type":"LONG"},
        {"close":76906.35,"divergence":False,"entry":76902.2,"note":"TAKE PROFIT","pnl":612.08,"result":"WIN","time":"2026-05-18 08:40","type":"LONG"},
        {"close":76906.35,"divergence":False,"entry":76898.3,"note":"TAKE PROFIT","pnl":637.24,"result":"WIN","time":"2026-05-18 08:42","type":"LONG"},
        {"close":76897.73,"divergence":False,"entry":76900.6,"note":"STOP LOSS","pnl":-331.76,"result":"LOSS","time":"2026-05-18 08:49","type":"LONG"},
        {"close":76906.35,"divergence":False,"entry":76877.9,"note":"TAKE PROFIT","pnl":650.03,"result":"WIN","time":"2026-05-18 08:50","type":"LONG"},
        {"close":77015.0,"divergence":False,"entry":77010.0,"note":"TAKE PROFIT","pnl":676.25,"result":"WIN","time":"2026-05-18 09:00","type":"LONG"},
        {"close":76987.25,"divergence":False,"entry":76996.5,"note":"STOP LOSS","pnl":-351.65,"result":"LOSS","time":"2026-05-18 09:02","type":"LONG"},
        {"close":76932.65,"divergence":False,"entry":76960.1,"note":"STOP LOSS","pnl":-344.62,"result":"LOSS","time":"2026-05-18 09:04","type":"LONG"},
        {"close":76887.5,"divergence":False,"entry":76930.0,"note":"STOP LOSS","pnl":-337.73,"result":"LOSS","time":"2026-05-18 09:10","type":"LONG"},
        {"close":76886.3,"divergence":False,"entry":76886.3,"note":"STOP LOSS","pnl":0.0,"result":"WIN","time":"2026-05-18 09:32","type":"LONG"},
        {"close":76886.3,"divergence":False,"entry":76886.3,"note":"STOP LOSS","pnl":0.0,"result":"WIN","time":"2026-05-18 09:32","type":"LONG"},
        {"close":76978.0,"divergence":False,"entry":76878.2,"note":"TAKE PROFIT","pnl":662.0,"result":"WIN","time":"2026-05-18 13:53","type":"LONG"},
    ]
}

# Strategy C state (webhook only, same logic as B)
DEFAULT_STATE_C = {
    "position": None, "last_signal": "Starting...", "last_signal_time": "",
    "trades": [], "balance": 10000.0, "pnl_total": 0.0,
    "wins": 0, "losses": 0, "box": None, "current_rsi": 50.0,
    "current_price": 0.0, "last_cycle": "", "errors": [], "last_divergence": False,
    "trailing_enabled": True,
}

SAVED_STATE_C = {
    "balance": 10399.98,
    "pnl_total": 399.98,
    "wins": 1,
    "losses": 0,
    "position": None,
    "trades": [
        {"close":77200.0,"divergence":False,"entry":76800.0,"note":"TAKE PROFIT","pnl":400.0,"result":"WIN","time":"2026-05-18 16:19","type":"LONG"},
    ],
}

STATE_FILE_C = "/app/bot_state_c.json"
STATE_FILE_D = "/app/bot_state_d.json"
STATE_FILE_CM = "/app/bot_state_cm.json"

# ── Strategy D defaults ──────────────────────────────────────────
DEFAULT_STATE_D = {
    "position": None, "last_signal": "Starting...", "last_signal_time": "",
    "trades": [], "balance": 10000.0, "pnl_total": 0.0,
    "wins": 0, "losses": 0, "current_price": 0.0,
    "last_cycle": "", "errors": [], "last_ob": None, "last_fvg": None,
}

DEFAULT_STATE_CM = {
    "position": None, "last_signal": "Starting...", "last_signal_time": "",
    "trades": [], "balance": 10000.0, "pnl_total": 0.0,
    "wins": 0, "losses": 0, "current_price": 0.0,
    "last_cycle": "", "errors": [], "checkmark": None,
    "trailing_enabled": True,
}

# ── Strategy SMC defaults (OB+FVG+CHoCH, webhook only, 2-phase TP) ──
DEFAULT_STATE_SMC = {
    "position": None, "last_signal": "Starting...", "last_signal_time": "",
    "trades": [], "balance": 10000.0, "pnl_total": 0.0,
    "wins": 0, "losses": 0, "current_price": 0.0,
    "last_cycle": "", "errors": [],
}

SAVED_STATE_SMC = {
    "balance": 10000.0, "pnl_total": 0.0, "wins": 0, "losses": 0,
    "position": None, "trades": [],
}

STATE_FILE_SMC = "/app/bot_state_smc.json"

SAVED_STATE_D = {
    "balance": 10000.0,
    "pnl_total": 0.0,
    "wins": 0,
    "losses": 0,
    "position": None,
    "trades": [],
}

def load_state_d():
    db = db_load_state("D")
    if db:
        merged = {**DEFAULT_STATE_D, **db}
        log.info(f"State D from DB: ${merged['balance']:.2f} W{merged['wins']}/L{merged['losses']}")
        return merged
    try:
        if os.path.exists(STATE_FILE_D):
            with open(STATE_FILE_D) as f: saved = json.load(f)
            merged = {**DEFAULT_STATE_D, **saved}
            log.info(f"State D from JSON: ${merged.get('balance',10000):.2f}")
            return merged
    except (OSError, ValueError, TypeError) as e:
        log.warning(f"Load state D JSON error: {e}")
    merged = {**DEFAULT_STATE_D, **SAVED_STATE_D}
    log.info(f"State D from SAVED_STATE_D: ${merged['balance']:.2f}")
    return merged

def save_state_d():
    snap = snapshot_state("D")   # consistent copy under lock; I/O below is lock-free
    db_save_state("D", snap)
    try:
        with open(STATE_FILE_D, "w") as f:
            json.dump(snap, f, indent=2, default=str)
    except (OSError, TypeError) as e:
        log.warning(f"Save state D JSON error: {e}")


def load_state_cm():
    db = db_load_state("CM")
    if db:
        merged = {**DEFAULT_STATE_CM, **db}
        log.info(f"State CM from DB: ${merged['balance']:.2f} W{merged['wins']}/L{merged['losses']}")
        return merged
    try:
        if os.path.exists(STATE_FILE_CM):
            with open(STATE_FILE_CM) as f: saved = json.load(f)
            return {**DEFAULT_STATE_CM, **saved}
    except (OSError, ValueError, TypeError) as e:
        log.warning(f"Load state CM error: {e}")
    return {**DEFAULT_STATE_CM}

def save_state_cm():
    snap = snapshot_state("CM")   # consistent copy under lock; I/O below is lock-free
    db_save_state("CM", snap)
    try:
        with open(STATE_FILE_CM, "w") as f:
            json.dump(snap, f, indent=2, default=str)
    except (OSError, TypeError) as e:
        log.warning(f"Save state CM error: {e}")

def load_state_smc():
    db = db_load_state("SMC")
    if db:
        merged = {**DEFAULT_STATE_SMC, **db}
        log.info(f"State SMC from DB: ${merged['balance']:.2f} W{merged['wins']}/L{merged['losses']}")
        return merged
    try:
        if os.path.exists(STATE_FILE_SMC):
            with open(STATE_FILE_SMC) as f: saved = json.load(f)
            merged = {**DEFAULT_STATE_SMC, **saved}
            log.info(f"State SMC from JSON: ${merged.get('balance',10000):.2f}")
            return merged
    except (OSError, ValueError, TypeError) as e:
        log.warning(f"Load state SMC error: {e}")
    merged = {**DEFAULT_STATE_SMC, **SAVED_STATE_SMC}
    log.info(f"State SMC from SAVED_STATE_SMC: ${merged['balance']:.2f}")
    return merged

def save_state_smc():
    snap = snapshot_state("SMC")   # consistent copy under lock; I/O below is lock-free
    db_save_state("SMC", snap)
    try:
        with open(STATE_FILE_SMC, "w") as f:
            json.dump(snap, f, indent=2, default=str)
    except (OSError, TypeError) as e:
        log.warning(f"Save state SMC JSON error: {e}")

def load_state_c():
    # 1) Προσπαθεί από DB
    db = db_load_state("C")
    if db:
        merged = {**DEFAULT_STATE_C, **db}
        log.info(f"State C from DB: ${merged['balance']:.2f} W{merged['wins']}/L{merged['losses']}")
        return merged
    # 2) Fallback: JSON file
    try:
        if os.path.exists(STATE_FILE_C):
            with open(STATE_FILE_C) as f: saved = json.load(f)
            merged = {**DEFAULT_STATE_C, **saved}
            log.info(f"State C from JSON: ${merged.get('balance',10000):.2f}")
            return merged
    except (OSError, ValueError, TypeError) as e:
        log.warning(f"Load state C JSON error: {e}")
    # 3) Fallback: hardcoded
    merged = {**DEFAULT_STATE_C, **SAVED_STATE_C}
    log.info(f"State C from SAVED_STATE_C: ${merged['balance']:.2f}")
    return merged

def save_state_c():
    snap = snapshot_state("C")   # consistent copy under lock; I/O below is lock-free
    # Αποθήκευση στη DB
    db_save_state("C", snap)
    # Backup JSON (fallback)
    try:
        with open(STATE_FILE_C, "w") as f:
            json.dump(snap, f, indent=2, default=str)
    except (OSError, TypeError) as e:
        log.warning(f"Save state C JSON error: {e}")

def load_state():
    # 1) Προσπαθεί από DB
    db = db_load_state("A")
    if db:
        merged = {**DEFAULT_STATE, **db}
        merged["running"] = True; merged["mode"] = TRADING_MODE
        log.info(f"State A from DB: ${merged['balance']:.2f} W{merged['wins']}/L{merged['losses']}")
        return merged
    # 2) Fallback: JSON file
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE) as f: saved = json.load(f)
            merged = {**DEFAULT_STATE, **saved}
            merged["running"] = True; merged["mode"] = TRADING_MODE
            log.info(f"State A from JSON: ${merged['balance']:.2f}")
            return merged
    except (OSError, ValueError, TypeError) as e:
        log.warning(f"Load state A JSON error: {e}")
    # 3) Fallback: hardcoded
    merged = {**DEFAULT_STATE, **SAVED_STATE}
    merged["running"] = True; merged["mode"] = TRADING_MODE
    log.info(f"State A from SAVED_STATE: ${merged['balance']:.2f}")
    return merged

def load_state_b():
    # 1) Προσπαθεί από DB
    db = db_load_state("B")
    if db:
        merged = {**DEFAULT_STATE_B, **db}
        log.info(f"State B from DB: ${merged['balance']:.2f} W{merged['wins']}/L{merged['losses']}")
        return merged
    # 2) Fallback: JSON file
    try:
        if os.path.exists(STATE_FILE_B):
            with open(STATE_FILE_B) as f: saved = json.load(f)
            merged = {**DEFAULT_STATE_B, **saved}
            log.info(f"State B from JSON: ${merged.get('balance',10000):.2f}")
            return merged
    except (OSError, ValueError, TypeError) as e:
        log.warning(f"Load state B JSON error: {e}")
    # 3) Fallback: hardcoded
    merged = {**DEFAULT_STATE_B, **SAVED_STATE_B}
    log.info(f"State B from SAVED_STATE_B: ${merged['balance']:.2f}")
    return merged

def save_state():
    snap = snapshot_state("A")   # consistent copy under lock; I/O below is lock-free
    # Αποθήκευση στη DB
    db_save_state("A", snap)
    # Backup JSON (fallback)
    try:
        with open(STATE_FILE, "w") as f:
            json.dump({k:v for k,v in snap.items() if k!="running"}, f, indent=2, default=str)
    except (OSError, TypeError) as e:
        log.warning(f"Save state A JSON error: {e}")

def save_state_b():
    snap = snapshot_state("B")   # consistent copy under lock; I/O below is lock-free
    # Αποθήκευση στη DB
    db_save_state("B", snap)
    # Backup JSON (fallback)
    try:
        with open(STATE_FILE_B, "w") as f:
            json.dump(snap, f, indent=2, default=str)
    except (OSError, TypeError) as e:
        log.warning(f"Save state B JSON error: {e}")

# =================================================================
# DB INIT + SEED (τρέχει μία φορά στο startup)
# =================================================================
init_db()
seed_if_empty("A", SAVED_STATE)
seed_if_empty("B", SAVED_STATE_B)
seed_if_empty("C", SAVED_STATE_C)
seed_if_empty("D", SAVED_STATE_D)
seed_if_empty("SMC", SAVED_STATE_SMC)

state   = load_state()
state["running"] = True
state_b = load_state_b()
state_c = load_state_c()
state_d = load_state_d()
state_cm = load_state_cm()
state_smc = load_state_smc()

# =================================================================
# THREAD SAFETY — per-strategy locks
# =================================================================
# The state dicts above are written by the scheduler thread (bot_loop) and the
# webhook threads, and read by the Flask request threads (dashboards / APIs).
# Each strategy gets its OWN re-entrant lock:
#   • per-strategy → a slow save/serialize on one strategy never blocks reads
#     of another, and only ONE lock is ever held in any code path, so there is
#     no lock-ordering cycle and therefore no possibility of deadlock;
#   • RLock → a writer holding the lock can call save_state*/finalize, which
#     re-acquire the same lock, without self-deadlocking.
# Locks are held ONLY around fast in-memory mutations and the snapshot copy in
# snapshot_state(); never around network / exchange / AI-validation / DB / file
# I/O — so the dashboard never blocks waiting on a writer.
state_lock     = threading.RLock()
state_lock_b   = threading.RLock()
state_lock_c   = threading.RLock()
state_lock_d   = threading.RLock()
state_lock_cm  = threading.RLock()
state_lock_smc = threading.RLock()

_STATE_REGISTRY = {
    "A":   (state,     state_lock),
    "B":   (state_b,   state_lock_b),
    "C":   (state_c,   state_lock_c),
    "D":   (state_d,   state_lock_d),
    "CM":  (state_cm,  state_lock_cm),
    "SMC": (state_smc, state_lock_smc),
}

def snapshot_state(name):
    """Return a detached deepcopy of a strategy's state, taken under its lock.

    The lock is held only for the (fast, in-memory) copy; the caller then
    serializes / renders the snapshot WITHOUT holding the lock, so a Flask
    reader never blocks on a scheduler write and a scheduler write never blocks
    on template rendering. deepcopy touches only plain dict/list/scalar data
    and calls no application code, so it cannot re-enter a writer's lock.
    """
    st, lock = _STATE_REGISTRY[name]
    with lock:
        return copy.deepcopy(st)

# Race condition guard — αποτρέπει διπλό AI call όταν το scheduler τρέχει κάθε 30s.
# (Το _b_entering μετακινήθηκε στο strategies/strategy_b.py ως module-level guard.)
_a_entering = False

# =================================================================
# NEWS
# =================================================================

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
            for e in feed.entries[:4]: headlines.append(e.title)
        except (AttributeError, KeyError, TypeError): pass
    state["last_news_headlines"] = headlines[:20]
    return headlines[:20]

def ai_news_score(headlines, signal_type, price, box):
    if not headlines or not ANTHROPIC_API_KEY:
        return 0, ""
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        prompt = f"""Crypto news for {signal_type} BTC/USDT @ ${price:,.0f}. MID=${box['mid']:,.0f}.
Headlines: {chr(10).join(f'- {h}' for h in headlines[:8])}
JSON only: {{"score":<-2 to 2>,"summary":"<15 words>"}}"""
        r    = client.messages.create(model="claude-haiku-4-5", max_tokens=100,
                                      messages=[{"role":"user","content":prompt}])
        text = r.content[0].text.strip().replace("```json","").replace("```","").strip()
        data = json.loads(text)
        score   = max(-2, min(2, int(data.get("score", 0))))
        summary = data.get("summary", "")
        state["last_news_score"]   = score
        state["last_news_summary"] = summary
        return score, summary
    except Exception as e:  # broad on purpose: news scoring is best-effort → neutral on any failure
        log.error(f"AI news error: {e}")
        return 0, ""

# =================================================================
# POSITION MANAGEMENT - Strategy A (4 phases)
# =================================================================

def get_balance_a():
    if TRADING_MODE == "PAPER": return state["balance"]
    try:
        r   = bitget_signed("GET", f"/api/v2/mix/account/account?symbol={BITGET_SYMBOL}&productType={BITGET_PROD_TYPE}&marginCoin=USDT")
        bal = float(r.get("data",{}).get("available", state["balance"]))
        state["balance"] = bal
        return bal
    except (KeyError, TypeError, ValueError): return state["balance"]

def calc_qty(balance, risk_pct, entry, sl):
    risk_dist = abs(entry - sl)
    if risk_dist <= 0: return MIN_ORDER_QTY
    return max(round((balance * risk_pct) / risk_dist, 4), MIN_ORDER_QTY)


# ═══════════════════════════════════════════════════════════════════════════
# LIVE TRADING ENGINE — per-strategy allowlist + encrypted dashboard creds
# ═══════════════════════════════════════════════════════════════════════════
# ΕΓΓΥΗΣΗ (α): υπάρχει ΑΚΡΙΒΩΣ ΜΙΑ λειτουργική live-order συνάρτηση
# (place_order_live_c) και κάνει hard-assert ότι 'C' ∈ LIVE_STRATEGIES + έγκυρα
# decrypted creds. Οι legacy global live συναρτήσεις είναι disabled. Καμία άλλη
# στρατηγική δεν έχει προσβάσιμο live path. Default allowlist κενό ⇒ όλες PAPER.
import secrets_vault
import live_trading

class BitgetClient:
    """Υπογράφει Bitget requests με ΡΗΤΑ credentials (όχι env vars). ΠΟΤΕ δεν
    λογάρει τα keys/signature."""
    def __init__(self, api_key, secret, passphrase):
        self._k = api_key; self._s = secret; self._p = passphrase

    def signed(self, method, path, body=None):
        import hmac, hashlib, base64
        ts = str(int(time.time() * 1000))
        body_str = json.dumps(body or {})
        msg = ts + method.upper() + path + (body_str if method == "POST" else "")
        sig = base64.b64encode(
            hmac.new(self._s.encode(), msg.encode(), hashlib.sha256).digest()
        ).decode()
        headers = {
            "ACCESS-KEY": self._k, "ACCESS-SIGN": sig, "ACCESS-TIMESTAMP": ts,
            "ACCESS-PASSPHRASE": self._p, "Content-Type": "application/json", "locale": "en-US",
        }
        try:
            if method == "GET":
                r = requests.get(BITGET_BASE + path, headers=headers, timeout=10)
            else:
                r = requests.post(BITGET_BASE + path, headers=headers, data=body_str, timeout=10)
            return r.json()
        except (requests.RequestException, ValueError) as e:
            log.error(f"[LIVE] Bitget request error: {type(e).__name__}")
            return {}


_live_creds_cache = {"client": None, "ok": False, "checked_at": 0.0}
_live_creds_lock  = threading.Lock()
_LIVE_CRED_TTL    = 300   # re-validate creds κάθε 5'

def _build_live_client():
    """Φέρε & αποκρυπτογράφησε τα creds του LIVE_TRADING_USER_ID → BitgetClient.
    FAIL-CLOSED: None αν λείπει vault key/creds."""
    if not secrets_vault.available():
        return None
    from database import get_live_credentials
    creds = get_live_credentials(LIVE_TRADING_USER_ID)
    if not creds:
        return None
    return BitgetClient(creds["api_key"], creds["secret"], creds["passphrase"])

def _validate_client(client):
    """Lightweight signed GET account — επιβεβαιώνει ότι τα keys δουλεύουν."""
    if client is None:
        return False
    path = (f"/api/v2/mix/account/account?symbol={BITGET_SYMBOL}"
            f"&productType={BITGET_PROD_TYPE}&marginCoin=USDT")
    r = client.signed("GET", path)
    return str(r.get("code")) == "00000"

def live_credentials_ok(strategy, force=False):
    """True ΜΟΝΟ αν: strategy ∈ LIVE_STRATEGIES ΚΑΙ έγκυρα decrypted creds ΚΑΙ
    επιτυχής signed call. Cached με TTL. FAIL-CLOSED."""
    if strategy not in LIVE_STRATEGIES:
        return False
    now = time.time()
    with _live_creds_lock:
        fresh = (now - _live_creds_cache["checked_at"]) < _LIVE_CRED_TTL
        if not force and fresh and _live_creds_cache["client"] is not None:
            return _live_creds_cache["ok"]
        client = _build_live_client()
        ok = _validate_client(client)
        _live_creds_cache.update(client=client, ok=ok, checked_at=now)
        if not ok:
            log.warning("[LIVE] credential check failed — %s stays PAPER", strategy)
        return ok

def _live_client():
    with _live_creds_lock:
        return _live_creds_cache["client"]

def resolve_strategy_mode(strategy):
    """'LIVE' μόνο αν allowlisted ΚΑΙ creds OK· αλλιώς 'PAPER'. FAIL-CLOSED."""
    return "LIVE" if (strategy in LIVE_STRATEGIES and live_credentials_ok(strategy)) else "PAPER"


def _live_account():
    """Read-only signed GET account με τα live keys. → (data_dict, None) επιτυχία,
    ή (None, error_msg). Κοινό για test_live_connection + live_available_balance."""
    if not secrets_vault.available():
        return None, "SECRETS_ENCRYPTION_KEY δεν έχει οριστεί στο server."
    client = _build_live_client()
    if client is None:
        return None, "Δεν βρέθηκαν αποθηκευμένα/αποκρυπτογραφήσιμα Bitget keys."
    path = (f"/api/v2/mix/account/account?symbol={BITGET_SYMBOL}"
            f"&productType={BITGET_PROD_TYPE}&marginCoin=USDT")
    r = client.signed("GET", path)
    code = str(r.get("code"))
    if code != "00000":
        return None, f"Bitget error {code}: {r.get('msg', '?')}"
    data = r.get("data") or {}
    if isinstance(data, list):
        data = data[0] if data else {}
    return data, None

def _to_float(v):
    try:    return float(v)
    except (TypeError, ValueError): return None

def test_live_connection():
    """READ-ONLY διαγνωστικό για το dashboard: signed GET account. ΔΕΝ στέλνει
    order, ΔΕΝ εξαρτάται από το LIVE_STRATEGIES — επικυρώνει τα keys ΧΩΡΙΣ live.
    Returns {ok, available, equity, msg}. ΠΟΤΕ δεν επιστρέφει/λογάρει τα keys."""
    data, err = _live_account()
    if err:
        return {"ok": False, "msg": err}
    available = _to_float(data.get("available"))
    equity    = _to_float(data.get("accountEquity"))
    log.info("[LIVE] connection test OK (available=%s equity=%s USDT)", available, equity)
    return {"ok": True, "available": available, "equity": equity, "msg": "Connected"}


# ── Real exchange balance — πηγή για το LIVE sizing (όχι το paper balance) ──
_live_balance_cache = {"value": None, "ts": 0.0}

def live_available_balance(max_age=5.0):
    """Πραγματικό available USDT από το exchange (cached ~5s ώστε sizing & order
    να βλέπουν την ίδια τιμή με ένα call). → float, ή None αν δεν διαβαστεί
    (no creds / API error / parse). FAIL-CLOSED — ο caller ΔΕΝ ανοίγει θέση."""
    now = time.time()
    if _live_balance_cache["value"] is not None and (now - _live_balance_cache["ts"]) < max_age:
        return _live_balance_cache["value"]
    data, err = _live_account()
    if err:
        log.error("[LIVE][C] cannot read real balance: %s", err)
        return None
    val = _to_float(data.get("available"))
    if val is None:
        log.error("[LIVE][C] real balance unpar. — refusing")
        return None
    _live_balance_cache.update(value=val, ts=now)
    return val


# ── Contract specs + sizing για μικρό λογαριασμό ────────────────────────────
_contract_specs = {"min_qty": MIN_ORDER_QTY, "size_step": MIN_ORDER_QTY,
                   "price_tick": 0.1, "fetched": False}

def get_contract_specs():
    """min trade size & step & price tick για το BTCUSDT perp (cached).
    Fallbacks: size 0.001, price_tick 0.1."""
    if _contract_specs["fetched"]:
        return _contract_specs
    try:
        r = bitget_get("/api/v2/mix/market/contracts",
                       {"symbol": BITGET_SYMBOL, "productType": BITGET_PROD_TYPE})
        data = r.get("data") or []
        if data:
            c = data[0]
            mn = float(c.get("minTradeNum", MIN_ORDER_QTY)) or MIN_ORDER_QTY
            step = float(c.get("sizeMultiplier", mn)) or mn
            try:    # price tick = priceEndStep / 10^pricePlace (BTCUSDT: 1/10^1 = 0.1)
                pp = int(c.get("pricePlace", 1))
                pes = float(c.get("priceEndStep", 1)) or 1.0
                tick = pes / (10 ** pp)
            except (TypeError, ValueError):
                tick = _contract_specs["price_tick"]
            _contract_specs.update(min_qty=mn, size_step=step, price_tick=tick, fetched=True)
            log.info("[LIVE] contract specs: min_qty=%s step=%s price_tick=%s", mn, step, tick)
    except Exception as e:
        log.warning("[LIVE] contract specs fetch failed (%s) — fallbacks 0.001 / 0.1", type(e).__name__)
    return _contract_specs

def prepare_live_size(qty, entry, sl, balance):
    """Wrapper γύρω από το (pure) live_trading.prepare_live_size με τα config
    constants + contract specs + logging. → (final_qty, leverage) ή None (skip)."""
    specs = get_contract_specs()
    res = live_trading.prepare_live_size(
        qty, entry, sl, balance,
        min_qty=specs["min_qty"], size_step=specs["size_step"] or specs["min_qty"],
        leverage_cap=LIVE_LEVERAGE_CAP, max_trade_risk_pct=LIVE_MAX_TRADE_RISK_PCT,
        margin_buffer=LIVE_MARGIN_BUFFER,
    )
    if res is None:
        log.warning("[LIVE][C] skip: sizing rejected (qty / risk cap %.0f%% / affordability) "
                    "for entry~%.2f balance $%.2f", LIVE_MAX_TRADE_RISK_PCT * 100, entry, balance)
    return res

def _live_calc_qty_c(balance, risk_pct, entry, sl):
    """calc_qty για LIVE C. ΑΓΝΟΕΙ το `balance` arg (paper balance που περνά η
    strategy_c) και χρησιμοποιεί το ΠΡΑΓΜΑΤΙΚΟ available του exchange. Αν δεν
    διαβαστεί το real balance → 0.0 (η strategy_c ΔΕΝ ανοίγει θέση — όχι fallback
    στο paper). Risk-based μέγεθος → exchange-valid (rounded) ή 0=skip."""
    real_bal = live_available_balance()
    if real_bal is None:
        log.error("[LIVE][C] no real balance — refusing to size (no paper fallback)")
        return 0.0
    raw = calc_qty(real_bal, risk_pct, entry, sl)
    res = prepare_live_size(raw, entry, sl, real_bal)
    return res[0] if res else 0.0


# ── Live order placement / close για τη C (encrypted creds) ─────────────────
def place_order_live_c(side, qty, entry, sl, tp):
    """LIVE open για τη C. exchange SL = strategy SL (backstop αν πέσει το process·
    το software trailing κλείνει νωρίτερα). ΟΧΙ preset TP. Returns order_id ή None.
    ΔΕΝ επιστρέφει oid χωρίς επιβεβαιωμένη εκτέλεση → κανένα ghost στο open."""
    if "C" not in LIVE_STRATEGIES:                       # hard gate (α)
        log.error("[SAFETY] place_order_live_c called but 'C' not in LIVE_STRATEGIES")
        return None
    if qty <= 0:
        return None                                       # skip (sizing είπε όχι)
    if not live_credentials_ok("C"):
        log.error("[LIVE][C] credentials not OK at order time — refusing")
        return None
    client = _live_client()
    if client is None:
        return None
    real_bal = live_available_balance()
    if real_bal is None:                                  # δεν ανοίγουμε χωρίς real balance
        log.error("[LIVE][C] no real balance at order time — refusing order")
        return None
    notional = qty * entry
    leverage = live_trading.leverage_for(notional, real_bal,
                                         LIVE_LEVERAGE_CAP, LIVE_MARGIN_BUFFER)
    client.signed("POST", "/api/v2/mix/account/set-leverage", {
        "symbol": BITGET_SYMBOL, "productType": BITGET_PROD_TYPE, "marginCoin": "USDT",
        "leverage": str(leverage), "holdSide": "long" if side == "LONG" else "short",
    })
    tick = get_contract_specs()["price_tick"]
    body = {
        "symbol": BITGET_SYMBOL, "productType": BITGET_PROD_TYPE,
        "marginMode": "isolated", "marginCoin": "USDT",
        "size": str(qty),
        "side": "buy" if side == "LONG" else "sell",
        "tradeSide": "open", "orderType": "market",
        "presetStopLossPrice": str(live_trading.round_to_tick(sl, tick)),  # atomic SL στο fill (snapped to tick)
    }
    # Trailing OFF: το TP είναι hard close → preset στο exchange (Option-A path).
    # Trailing ON: ΚΑΝΕΝΑ preset TP — το TP είναι trigger για trailing (modify-loop).
    if tp and not state_c.get("trailing_enabled", True):
        body["presetStopSurplusPrice"] = str(live_trading.round_to_tick(tp, tick))
    r = client.signed("POST", "/api/v2/mix/order/place-order", body)
    if str(r.get("code")) != "00000":
        log.error("[LIVE][C] OPEN rejected: code=%s msg=%s", r.get("code"), r.get("msg"))
        send_telegram(f"⚠️ <b>[C][LIVE] ORDER FAILED</b>\n{r.get('msg','?')}")
        return None
    oid = (r.get("data") or {}).get("orderId")
    if not oid:
        log.error("[LIVE][C] OPEN: no orderId in response")
        return None
    log.info("[LIVE][C] OPEN %s qty=%s lev=%dx entry~%.2f SL=%.2f oid=%s",
             side, qty, leverage, entry, sl, oid)
    return oid

def close_position_live_c(side, qty):
    """LIVE market close για τη C. Returns True/False (καθαρά, χωρίς ghost)."""
    if "C" not in LIVE_STRATEGIES or not live_credentials_ok("C"):
        return False
    client = _live_client()
    if client is None:
        return False
    r = client.signed("POST", "/api/v2/mix/order/place-order", {
        "symbol": BITGET_SYMBOL, "productType": BITGET_PROD_TYPE,
        "marginMode": "isolated", "marginCoin": "USDT",
        "side": "sell" if side == "LONG" else "buy",
        "tradeSide": "close", "orderType": "market", "size": str(qty),
    })
    if not live_trading.close_succeeded(r.get("code")):
        log.error("[LIVE][C] CLOSE failed: code=%s msg=%s", r.get("code"), r.get("msg"))
        return False
    if str(r.get("code")) == "22002":   # exchange ήδη flat (π.χ. safety SL) → success
        log.warning("[LIVE][C] CLOSE %s: exchange already flat (22002) — treating as closed", side)
    else:
        log.info("[LIVE][C] CLOSE %s qty=%s ok", side, qty)
    return True

# ── Position TP/SL plan orders (exchange-managed exit για τη C) ──────────────
# Params verbatim από Bitget Place-Tpsl-Order / Modify-Tpsl-Order. ΔΕΝ υπάρχει
# marginMode σε αυτά τα endpoints (μόνο marginCoin). Για pos_loss/pos_profit το
# size ΔΕΝ στέλνεται στο place· στο modify το size είναι "". Το triggerPrice
# στρογγυλοποιείται πάντα στο price tick. PR1 = infra (δεν καλείται ακόμα).
def place_tpsl_order_c(plan_type, trigger_price, hold_side):
    """Θέτει position TP/SL στο exchange. plan_type: 'pos_loss' | 'pos_profit'.
    hold_side: 'long' | 'short'. Returns orderId (str) ή None."""
    if "C" not in LIVE_STRATEGIES or not live_credentials_ok("C"):
        return None
    client = _live_client()
    if client is None:
        return None
    tick = get_contract_specs()["price_tick"]
    r = client.signed("POST", "/api/v2/mix/order/place-tpsl-order", {
        "symbol": BITGET_SYMBOL, "productType": BITGET_PROD_TYPE, "marginCoin": "USDT",
        "planType": plan_type,
        "triggerPrice": str(live_trading.round_to_tick(trigger_price, tick)),
        "triggerType": "mark_price",
        "holdSide": hold_side,
    })
    if str(r.get("code")) != "00000":
        log.error("[LIVE][C] place-tpsl (%s) failed: code=%s msg=%s",
                  plan_type, r.get("code"), r.get("msg"))
        return None
    oid = (r.get("data") or {}).get("orderId")
    log.info("[LIVE][C] place-tpsl %s trigger=%s oid=%s", plan_type, trigger_price, oid)
    return oid

def modify_tpsl_order_c(order_id, trigger_price):
    """Μετακινεί το trigger ενός υπάρχοντος position TP/SL (BE/trailing). size=""
    για position orders (verbatim). Returns True/False."""
    if "C" not in LIVE_STRATEGIES or not live_credentials_ok("C"):
        return False
    client = _live_client()
    if client is None:
        return False
    tick = get_contract_specs()["price_tick"]
    r = client.signed("POST", "/api/v2/mix/order/modify-tpsl-order", {
        "orderId": str(order_id),
        "symbol": BITGET_SYMBOL, "productType": BITGET_PROD_TYPE, "marginCoin": "USDT",
        "triggerPrice": str(live_trading.round_to_tick(trigger_price, tick)),
        "size": "",
    })
    if str(r.get("code")) != "00000":
        log.error("[LIVE][C] modify-tpsl failed: code=%s msg=%s", r.get("code"), r.get("msg"))
        return False
    log.info("[LIVE][C] modify-tpsl oid=%s -> trigger=%s ok", order_id, trigger_price)
    return True

def _discover_pos_sl_oid_c(hold_side):
    """Ψάχνει στο orders-plan-pending (planType=profit_loss, verbatim) για το
    position-SL plan order της C → orderId ή None. Δεν υποθέτουμε αν το preset
    SL του open γίνεται modifiable order — το ΠΑΡΑΤΗΡΟΥΜΕ (discovery-or-place)."""
    client = _live_client()
    if client is None:
        return None
    path = (f"/api/v2/mix/order/orders-plan-pending?planType=profit_loss"
            f"&productType={BITGET_PROD_TYPE}&symbol={BITGET_SYMBOL}")
    r = client.signed("GET", path)
    if str(r.get("code")) != "00000":
        log.warning("[LIVE][C] SL discovery failed: code=%s msg=%s", r.get("code"), r.get("msg"))
        return None
    for o in ((r.get("data") or {}).get("entrustedList") or []):
        plan = str(o.get("planType", ""))
        pos_side = str(o.get("posSide", ""))
        # SL-τύπου plan, στη δική μας πλευρά (net = one-way mode, δεκτό)
        if "loss" in plan and pos_side in (hold_side, "net"):
            log.info("[LIVE][C] SL discovery: found planType=%s oid=%s trigger=%s",
                     plan, o.get("orderId"), o.get("triggerPrice"))
            return o.get("orderId")
    log.info("[LIVE][C] SL discovery: no pending SL plan order (preset is not a plan order)")
    return None

def move_live_sl_c(pos, new_trigger, force=False):
    """Μετακινεί το exchange SL της live C θέσης (BE/trailing) — ΠΟΤΕ market close.
    Discovery-or-place: βρες το orderId του position SL (μία φορά) και κάνε modify·
    αν δεν υπάρχει plan order (preset = attribute), βάλε pos_loss (έχει orderId).
    Debounced εκτός αν force (BE/πρώτο trailing set). Returns True/False."""
    if not pos or not pos.get("live"):
        return False
    now = time.time()
    if not force and not live_trading.should_modify_trailing(
            pos.get("exchange_sl"), new_trigger, rt.price or new_trigger,
            get_contract_specs()["price_tick"], pos.get("last_sl_modify_ts", 0.0), now):
        return False                       # debounce — όχι αποτυχία, απλώς όχι τώρα
    hold_side = "long" if pos["type"] == "LONG" else "short"
    oid = pos.get("sl_oid")
    if not oid:
        oid = _discover_pos_sl_oid_c(hold_side)
        if oid:
            pos["sl_oid"] = oid
    if oid:
        ok = modify_tpsl_order_c(oid, new_trigger)
        if not ok:
            # Το order μπορεί να μην υπάρχει πια (π.χ. ακυρώθηκε) — ξανά discovery
            # στο επόμενο tick αντί να κολλήσουμε σε νεκρό orderId.
            pos["sl_oid"] = None
            return False
    else:
        new_oid = place_tpsl_order_c("pos_loss", new_trigger, hold_side)
        if not new_oid:
            return False
        pos["sl_oid"] = new_oid
    pos["exchange_sl"] = new_trigger
    pos["last_sl_modify_ts"] = now
    return True

def c_order_deps():
    """(place_order, calc_qty, is_live) για τη C, βάσει mode. Single source of
    truth για το live/paper της C — το χρησιμοποιεί το webhook (main.py)."""
    if resolve_strategy_mode("C") == "LIVE":
        return place_order_live_c, _live_calc_qty_c, True
    return place_order_paper, calc_qty, False


# ── Live reconciler — πηγή αλήθειας το exchange· εξαλείφει ghosts ───────────
def _exchange_position_c():
    """('ok', {size, side}) | ('ok', None=flat) | ('error', None)."""
    client = _live_client()
    if client is None:
        return ("error", None)
    path = (f"/api/v2/mix/position/single-position?symbol={BITGET_SYMBOL}"
            f"&productType={BITGET_PROD_TYPE}&marginCoin=USDT")
    r = client.signed("GET", path)
    if str(r.get("code")) != "00000":
        return ("error", None)
    for p in (r.get("data") or []):
        total = float(p.get("total", 0) or 0)
        if total > 0:
            return ("ok", {"size": total, "side": p.get("holdSide")})
    return ("ok", None)

def live_reconciler():
    """Κάθε 20s, για live C: ευθυγραμμίζει state ↔ exchange. Τρέχει μόνο αν live."""
    log.info("[LIVE] reconciler started")
    while True:
        time.sleep(20)
        try:
            if "C" not in LIVE_STRATEGIES or not live_credentials_ok("C"):
                continue
            status, expos = _exchange_position_c()
            if status == "error":
                continue
            pos = state_c.get("position")
            if pos and pos.get("live") and expos is None:
                # exchange έκλεισε (SL backstop/TP) αλλά state ανοιχτό → finalize
                # ΧΩΡΙΣ νέα exchange-close (είναι ήδη flat).
                entry = pos["entry"]; px = rt.price or entry
                result = "WIN" if ((px > entry) == (pos["type"] == "LONG")) else "LOSS"
                log.warning("[LIVE][C] reconcile: exchange flat, state open → finalize")
                finalize_trade_c(px, result, "RECONCILE (exchange closed)", close_exchange=False)
            elif (not pos) and expos is not None:
                # GHOST: exchange ανοιχτό, state flat → alert + flatten
                log.error("[LIVE][C] reconcile: GHOST (exchange open, state flat) → flatten")
                send_telegram("⚠️ <b>[C][LIVE] GHOST</b> θέση στο exchange (όχι στο state) — flatten.")
                close_position_live_c("LONG" if expos["side"] == "long" else "SHORT", expos["size"])
        except Exception as e:
            log.error("[LIVE] reconciler error: %s", type(e).__name__)

def finalize_trade_a(price, result, note=""):
    pos = state["position"]
    if not pos: return
    pnl = round(((price-pos["entry"]) if pos["type"]=="LONG" else (pos["entry"]-price)) * pos["qty"], 2)
    # BREAK EVEN: δεν μετράει ούτε win ούτε loss
    trade = {
        "type": pos["type"], "entry": pos["entry"], "close": price,
        "pnl": pnl, "result": result,
        "time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "news_score": pos.get("news_score", 0),
        "divergence": pos.get("has_divergence", False), "note": note,
        "ai_action": pos.get("ai_action", ""),
        "ai_confidence": pos.get("ai_confidence", 0),
        "ai_reasoning": pos.get("ai_reasoning", ""),
        "ai_shadow_mode": pos.get("ai_shadow", False),
    }
    with state_lock:
        state["pnl_total"] = round(state["pnl_total"] + pnl, 2)
        state["balance"]   = round(state["balance"]   + pnl, 2)
        if result == "WIN":         state["wins"]   += 1
        elif result == "LOSS":      state["losses"] += 1
        state["trades"].append(trade)
        wins = state["wins"]; losses = state["losses"]; bal = state["balance"]
        state["position"] = None
    wr    = round(wins/(wins+losses)*100) if wins+losses>0 else 0
    emoji = "✅" if result=="WIN" else "❌"
    db_save_trade("A", trade)
    send_telegram(
        f"{emoji} <b>[A] {note or result}</b>\n"
        f"PnL: {'+' if pnl>=0 else ''}${pnl:.2f}\n"
        f"Balance: ${bal:,.2f}\n"
        f"W/L: {wins}W/{losses}L | WR: {wr}%"
    )
    if TRADING_MODE == "LIVE": close_position_live(pos["type"], pos["qty"])
    save_state()

# check_position_a μετακινήθηκε στο strategies/strategy_a.py (Phase 2 refactor).
# Καλείται εσωτερικά από το strategy_a.on_tick μέσω deps["finalize"]/deps[...].

# =================================================================
# POSITION MANAGEMENT - Strategy B (v2: multi-position, 0.3% trailing, no BE)
# =================================================================

def finalize_trade_b(price, result, note="", pos=None):
    # v2 multi-position: το `pos` προσδιορίζει ΠΟΙΑ θέση κλείνει. Legacy fallback
    # (pos=None) → η μοναδική state_b["position"] (για συμβατότητα).
    if pos is None:
        pos = state_b.get("position")
    if not pos: return
    pnl = round(((price-pos["entry"]) if pos["type"]=="LONG" else (pos["entry"]-price))*pos["qty"], 2)
    trade_b = {
        "type": pos["type"], "entry": pos["entry"], "close": price,
        "pnl": pnl, "result": result,
        "time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "divergence": pos.get("has_divergence", False), "note": note,
        "ai_action": pos.get("ai_action", ""),
        "ai_confidence": pos.get("ai_confidence", 0),
        "ai_reasoning": pos.get("ai_reasoning", ""),
        "ai_shadow_mode": pos.get("ai_shadow", False),
    }
    with state_lock_b:
        state_b["pnl_total"] = round(state_b["pnl_total"]+pnl, 2)
        state_b["balance"]   = round(state_b["balance"]  +pnl, 2)
        if result == "WIN":    state_b["wins"]   += 1
        elif result == "LOSS": state_b["losses"] += 1
        state_b["trades"].append(trade_b)
        wins=state_b["wins"]; losses=state_b["losses"]; bal=state_b["balance"]
        # Αφαίρεση της κλειστής θέσης από τη λίστα (multi-position)
        positions = state_b.get("positions")
        if isinstance(positions, list) and pos in positions:
            positions.remove(pos)
        else:
            state_b["position"] = None
        # Phase-1 mirror: το dashboard/DB δείχνουν ακόμα single position
        state_b["position"] = state_b["positions"][0] if state_b.get("positions") else None
    emoji = "✅" if result=="WIN" else "❌"
    db_save_trade("B", trade_b)
    send_telegram(
        f"{emoji} <b>[B] {note or result}</b>\n"
        f"PnL: {'+' if pnl>=0 else ''}${pnl:.2f}\n"
        f"Balance: ${bal:,.2f}\n"
        f"W/L: {wins}W/{losses}L"
    )
    save_state_b()

# check_position_b μετακινήθηκε στο strategies/strategy_b.py (Phase 2 refactor).
# Καλείται εσωτερικά από το strategy_b.on_tick μέσω deps["finalize"]/deps[...].

# =================================================================
# STRATEGY A - Daily box + 1H RSI
# =================================================================

def run_strategy_a():
    """Strategy A (Daily Box + 1H RSI) — καλεί το αυτόνομο module."""
    from strategies import strategy_a
    price = rt.price
    deps = {
        "rt":                  rt,
        "get_candles":         get_candles,
        "build_daily_box":     build_daily_box,
        "detect_divergence":   detect_divergence,
        "find_4h_sr":          find_4h_sr,
        "get_balance":         get_balance_a,
        "calc_qty":            calc_qty,
        "place_order":         place_order_paper,
        "place_order_live":    place_order_live,
        "close_position_live": close_position_live,
        "fetch_news":          fetch_news,
        "ai_news_score":       ai_news_score,
        "send_telegram":       send_telegram,
        "ai_validate":         _ai_validate,
        "finalize":            finalize_trade_a,
        "save_state":          save_state,
        "send_ai_summary":     _send_ai_trade_summary,
        "trading_mode":        TRADING_MODE,
        "risk_per_trade":      RISK_PER_TRADE,
        "ai_shadow_mode":      AI_SHADOW_MODE,
        "ai_shadow_master":    AI_SHADOW_MASTER,
        "lock":                state_lock,
    }
    strategy_a.on_tick(deps, state, price)

# =================================================================
# POSITION MANAGEMENT - Strategy C (webhook only, same as B)
# =================================================================

def finalize_trade_c(price, result, note="", close_exchange=True):
    pos = state_c["position"]
    if not pos: return
    # LIVE: κλείσε ΠΡΩΤΑ στο exchange. Αν αποτύχει → ΜΗΝ καθαρίσεις το state
    # (αλλιώς ghost: state flat, exchange ανοιχτό). close_exchange=False όταν ο
    # reconciler καλεί επειδή το exchange είναι ΗΔΗ flat.
    if pos.get("live") and close_exchange:
        if not close_position_live_c(pos["type"], pos["qty"]):
            log.error("[LIVE][C] close failed — keeping position; reconciler θα ξαναδοκιμάσει")
            send_telegram("⚠️ <b>[C][LIVE] CLOSE FAILED</b>\nΗ θέση παραμένει ανοιχτή — retry.")
            return
    pnl = round(((price-pos["entry"]) if pos["type"]=="LONG" else (pos["entry"]-price))*pos["qty"], 2)
    # BREAK EVEN: δεν μετράει
    trade_c = {
        "type": pos["type"], "entry": pos["entry"], "close": price,
        "pnl": pnl, "result": result,
        "time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "divergence": pos.get("has_divergence", False), "note": note,
        "ai_action": pos.get("ai_action", ""),
        "ai_confidence": pos.get("ai_confidence", 0),
        "ai_reasoning": pos.get("ai_reasoning", ""),
        "ai_shadow_mode": pos.get("ai_shadow", False),
    }
    with state_lock_c:
        state_c["pnl_total"] = round(state_c["pnl_total"]+pnl, 2)
        state_c["balance"]   = round(state_c["balance"]  +pnl, 2)
        if result == "WIN":    state_c["wins"]   += 1
        elif result == "LOSS": state_c["losses"] += 1
        state_c["trades"].append(trade_c)
        wins=state_c["wins"]; losses=state_c["losses"]; bal=state_c["balance"]
        state_c["position"] = None
    emoji = "✅" if result=="WIN" else "❌"
    db_save_trade("C", trade_c)
    msg = (f"{emoji} <b>[C] {note or result}</b>\n"
           f"PnL: {'+' if pnl>=0 else ''}${pnl:.2f}\n"
           f"Balance: ${bal:,.2f}\n"
           f"W/L: {wins}W/{losses}L")
    send_telegram(msg)
    save_state_c()

def check_position_c(price):
    """Strategy C exit (2-phase trailing) — καλεί το αυτόνομο module."""
    from strategies import strategy_c
    deps = {
        "finalize":      finalize_trade_c,
        "send_telegram": send_telegram,
        "save_state":    save_state_c,
        "lock":          state_lock_c,
        # LIVE exit = exchange-managed: μετακινούμε το stop (BE/trailing), δεν
        # στέλνουμε market close. Το κλείσιμο το ανιχνεύει ο reconciler.
        "modify_sl":     lambda new_trigger, force=False: move_live_sl_c(
                             state_c.get("position"), new_trigger, force),
    }
    strategy_c.check_position(deps, state_c, price)

# =================================================================
# STRATEGY B - 1H box + 15m RSI
# =================================================================

def run_strategy_b():
    """Strategy B (1H Box + 15m RSI) — καλεί το αυτόνομο module."""
    from strategies import strategy_b
    price = rt.price
    deps = {
        "rt":                rt,
        "get_candles":       get_candles,
        "build_1h_box":      build_1h_box,
        "detect_divergence": detect_divergence_b,   # B-specific causal ±5 swings
        "calc_qty":          calc_qty,
        "calc_rsi":          rt._calc_rsi,           # RSI επί κλειστών κεριών (entry)
        "place_order":       place_order_paper,
        "place_order_live":  place_order_live,
        "send_telegram":     send_telegram,
        "ai_validate":       _ai_validate,
        "finalize":          finalize_trade_b,
        "save_state":        save_state_b,
        "send_ai_summary":   _send_ai_trade_summary,
        "trading_mode":      TRADING_MODE,
        "risk_per_trade":    RISK_PER_TRADE_B,       # 0.5% base (×2 on divergence)
        "ai_shadow_master":  AI_SHADOW_MASTER,
        "lock":              state_lock_b,
    }
    strategy_b.on_tick(deps, state_b, price)

# =================================================================
# POSITION MANAGEMENT - Strategy D (OB + FVG + CHoCH, webhook only)
# 2-phase TP: TP1 at 2:1 (50% close), TP2 at 3:1 (remainder)
# =================================================================

def finalize_trade_d(price, result, note=""):
    pos = state_d["position"]
    if not pos: return
    pnl = round(((price - pos["entry"]) if pos["type"] == "LONG" else (pos["entry"] - price)) * pos["qty"], 2)
    trade_d = {
        "type":       pos["type"],
        "entry":      pos["entry"],
        "close":      price,
        "pnl":        pnl,
        "result":     result,
        "time":       datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "divergence": pos.get("has_confluence", False),
        "note":       note,
        "ai_action":     pos.get("ai_action", ""),
        "ai_confidence": pos.get("ai_confidence", 0),
        "ai_reasoning":  pos.get("ai_reasoning", ""),
        "ai_shadow_mode": pos.get("ai_shadow", False),
    }
    with state_lock_d:
        state_d["pnl_total"] = round(state_d["pnl_total"] + pnl, 2)
        state_d["balance"]   = round(state_d["balance"]   + pnl, 2)
        if result == "WIN": state_d["wins"]   += 1
        else:               state_d["losses"] += 1
        state_d["trades"].append(trade_d)
        wins = state_d["wins"]; losses = state_d["losses"]; bal = state_d["balance"]
        state_d["position"] = None
    emoji = "✅" if result == "WIN" else "❌"
    db_save_trade("D", trade_d)
    send_telegram(
        f"{emoji} <b>[D] {note or result}</b>\n"
        f"PnL: {'+' if pnl >= 0 else ''}${pnl:.2f}\n"
        f"Balance: ${bal:,.2f}\n"
        f"W/L: {wins}W/{losses}L"
    )
    save_state_d()


def finalize_trade_cm(price, result, note=""):
    pos = state_cm["position"]
    if not pos: return
    pnl = round(((price - pos["entry"]) if pos["type"] == "LONG" else (pos["entry"] - price)) * pos["qty"], 2)
    trade_cm = {
        "type":       pos["type"],
        "entry":      pos["entry"],
        "close":      price,
        "pnl":        pnl,
        "result":     result,
        "time":       datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "divergence": False,
        "note":       note,
        "ai_action":     pos.get("ai_action", ""),
        "ai_confidence": pos.get("ai_confidence", 0),
        "ai_reasoning":  pos.get("ai_reasoning", ""),
        "ai_shadow_mode": pos.get("ai_shadow", False),
    }
    with state_lock_cm:
        state_cm["pnl_total"] = round(state_cm["pnl_total"] + pnl, 2)
        state_cm["balance"]   = round(state_cm["balance"]   + pnl, 2)
        if result == "WIN": state_cm["wins"]   += 1
        elif result == "LOSS": state_cm["losses"] += 1
        state_cm["trades"].append(trade_cm)
        wins = state_cm["wins"]; losses = state_cm["losses"]; bal = state_cm["balance"]
        state_cm["position"] = None
    emoji = "✅" if result == "WIN" else ("➖" if result == "BREAK EVEN" else "❌")
    db_save_trade("CM", trade_cm)
    send_telegram(
        f"{emoji} <b>[CM] {note or result}</b>\n"
        f"PnL: {'+' if pnl >= 0 else ''}${pnl:.2f}\n"
        f"Balance: ${bal:,.2f}\n"
        f"W/L: {wins}W/{losses}L"
    )
    save_state_cm()


def finalize_partial_cm(close_price, partial_qty, partial_pnl, note=""):
    """Καταγράφει partial close (TP1 50%) — κρατάει τη θέση ανοιχτή."""
    pos = state_cm["position"]
    trade_cm = {
        "type":   pos["type"] if pos else "",
        "entry":  pos["entry"] if pos else 0,
        "close":  close_price,
        "pnl":    partial_pnl,
        "result": "WIN",
        "time":   datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "divergence": False,
        "note":   note,
    }
    with state_lock_cm:
        state_cm["balance"]   = round(state_cm["balance"]   + partial_pnl, 2)
        state_cm["pnl_total"] = round(state_cm["pnl_total"] + partial_pnl, 2)
        state_cm["wins"]     += 1
        state_cm["trades"].append(trade_cm)
    db_save_trade("CM", trade_cm)
    log.info(f"[CM] Partial close @ {close_price:.2f} | +${partial_pnl:.2f}")
    save_state_cm()


def run_strategy_cm():
    """Check Mark strategy — καλεί το αυτόνομο module."""
    from strategies import strategy_checkmark
    price = rt.price
    state_cm["current_price"] = price
    if price <= 0 or not rt.initialized:
        state_cm["last_signal"] = "Initializing..."
        return
    deps = {
        "get_candles":    get_candles,
        "place_order":    place_order_paper,
        "finalize":       finalize_trade_cm,
        "finalize_partial": finalize_partial_cm,
        "send_telegram":  send_telegram,
        "ai_validate":    _ai_validate,
        "save_state":     save_state_cm,
        "send_ai_summary":_send_ai_trade_summary,
        "rt":             rt,
        "lock":           state_lock_cm,
    }
    strategy_checkmark.on_tick(deps, state_cm, price)


# =================================================================
# POSITION MANAGEMENT - Strategy SMC (OB + FVG + CHoCH, webhook only)
# Αυτόνομο module: strategies/strategy_smc.py — 2-phase TP
# =================================================================

def finalize_trade_smc(price, result, note=""):
    pos = state_smc["position"]
    if not pos: return
    pnl = round(((price - pos["entry"]) if pos["type"] == "LONG" else (pos["entry"] - price)) * pos["qty"], 2)
    trade_smc = {
        "type":       pos["type"],
        "entry":      pos["entry"],
        "close":      price,
        "pnl":        pnl,
        "result":     result,
        "time":       datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "divergence": pos.get("has_confluence", False),
        "note":       note,
        "ai_action":     pos.get("ai_action", ""),
        "ai_confidence": pos.get("ai_confidence", 0),
        "ai_reasoning":  pos.get("ai_reasoning", ""),
        "ai_shadow_mode": pos.get("ai_shadow", False),
    }
    with state_lock_smc:
        state_smc["pnl_total"] = round(state_smc["pnl_total"] + pnl, 2)
        state_smc["balance"]   = round(state_smc["balance"]   + pnl, 2)
        if result == "WIN": state_smc["wins"]   += 1
        elif result == "LOSS": state_smc["losses"] += 1
        state_smc["trades"].append(trade_smc)
        wins = state_smc["wins"]; losses = state_smc["losses"]; bal = state_smc["balance"]
        state_smc["position"] = None
    emoji = "✅" if result == "WIN" else ("➖" if result == "BREAK EVEN" else "❌")
    db_save_trade("SMC", trade_smc)
    send_telegram(
        f"{emoji} <b>[SMC] {note or result}</b>\n"
        f"PnL: {'+' if pnl >= 0 else ''}${pnl:.2f}\n"
        f"Balance: ${bal:,.2f}\n"
        f"W/L: {wins}W/{losses}L"
    )
    save_state_smc()


def finalize_partial_smc(close_price, partial_qty, partial_pnl, note=""):
    """Καταγράφει partial close (TP1 50%) — κρατάει τη θέση ανοιχτή."""
    pos = state_smc["position"]
    trade_smc = {
        "type":   pos["type"] if pos else "",
        "entry":  pos["entry"] if pos else 0,
        "close":  close_price,
        "pnl":    partial_pnl,
        "result": "WIN",
        "time":   datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "divergence": pos.get("has_confluence", False) if pos else False,
        "note":   note,
    }
    with state_lock_smc:
        state_smc["balance"]   = round(state_smc["balance"]   + partial_pnl, 2)
        state_smc["pnl_total"] = round(state_smc["pnl_total"] + partial_pnl, 2)
        state_smc["wins"]     += 1
        state_smc["trades"].append(trade_smc)
    db_save_trade("SMC", trade_smc)
    log.info(f"[SMC] Partial close @ {close_price:.2f} | +${partial_pnl:.2f}")
    save_state_smc()


def check_position_smc(price):
    """Καλεί το αυτόνομο module για διαχείριση θέσης (2-phase TP)."""
    from strategies import strategy_smc
    deps = {
        "finalize":         finalize_trade_smc,
        "finalize_partial": finalize_partial_smc,
        "send_telegram":    send_telegram,
        "save_state":       save_state_smc,
        "lock":             state_lock_smc,
    }
    strategy_smc.check_position(deps, state_smc, price)


def check_position_d(price):
    pos = state_d["position"]
    if not pos: return

    if os.environ.get("FORCE_CLOSE_D", "").lower() == "true":
        finalize_trade_d(price, "WIN" if price > pos["entry"] else "LOSS", "FORCE CLOSE")
        return

    entry   = pos["entry"]
    sl      = pos["sl"]
    tp1     = pos["tp1"]
    tp2     = pos["tp2"]
    is_long = pos["type"] == "LONG"

    # Phase 1: TP1 hit → close 50%, move SL to entry
    if not pos.get("phase1_done"):
        hit_tp1 = (is_long and price >= tp1) or (not is_long and price <= tp1)
        if hit_tp1:
            # Close 50% of position at TP1
            partial_qty = round(pos["qty"] * 0.5, 6)
            partial_pnl = round(((tp1 - entry) if is_long else (entry - tp1)) * partial_qty, 2)
            trade_d = {
                "type": pos["type"], "entry": entry, "close": tp1,
                "pnl": partial_pnl, "result": "WIN",
                "time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
                "divergence": pos.get("has_confluence", False), "note": "TP1 (50%)",
            }
            with state_lock_d:
                state_d["balance"]   = round(state_d["balance"]   + partial_pnl, 2)
                state_d["pnl_total"] = round(state_d["pnl_total"] + partial_pnl, 2)
                state_d["wins"]     += 1
                state_d["trades"].append(trade_d)
                # Move SL to entry (break even) and reduce qty
                pos["sl"]          = entry
                pos["qty"]         = round(pos["qty"] * 0.5, 6)
                pos["phase1_done"] = True
            db_save_trade("D", trade_d)
            log.info(f"[D] TP1 hit @ {tp1:.2f} | +${partial_pnl:.2f} | SL → entry")
            send_telegram(
                f"🎯 <b>[D] TP1 HIT (50%)</b>\n"
                f"Close: ${tp1:,.2f} | PnL: +${partial_pnl:.2f}\n"
                f"SL → Break Even | Riding to TP2: ${tp2:,.2f}"
            )
            save_state_d()
            return

    # Phase 2: TP2 or SL
    hit_tp2 = (is_long and price >= tp2) or (not is_long and price <= tp2)
    hit_sl  = (is_long and price <= sl)  or (not is_long and price >= sl)

    if hit_tp2:
        finalize_trade_d(tp2, "WIN", "TP2")
    elif hit_sl:
        actual_pnl = ((sl - entry) if is_long else (entry - sl)) * pos["qty"]
        if abs(actual_pnl) < 1.0:
            result = "BREAK EVEN"; note = "BREAK EVEN"
        elif actual_pnl > 0:
            result = "WIN"; note = "STOP LOSS (profit)"
        else:
            result = "LOSS"; note = "STOP LOSS"
        finalize_trade_d(sl, result, note)

# =================================================================
# BOT LOOP
# =================================================================

def bot_loop():
    log.info("=" * 45)
    log.info("  NRM Bot - Real-time WebSocket RSI")
    log.info(f"  Mode: {TRADING_MODE} | Leverage: {LEVERAGE}x")
    log.info(f"  Balance A: ${state['balance']:.2f} W{state['wins']}/L{state['losses']}")
    log.info(f"  Balance B: ${state_b['balance']:.2f}")
    log.info(f"  Balance C: ${state_c['balance']:.2f}")
    log.info(f"  Balance D: ${state_d['balance']:.2f}")
    log.info("=" * 45)

    rt.load_history()
    rt.start_websocket()
    rt.start_polling()

    # Live reconciler — μόνο αν κάποια στρατηγική είναι allowlisted για live.
    if LIVE_STRATEGIES:
        log.info("[LIVE] LIVE_STRATEGIES=%s — starting reconciler", sorted(LIVE_STRATEGIES))
        log.info("[LIVE] leverage cap = %dx (auto-min) | risk per trade = %.1f%% | margin buffer = %.0f%%",
                 LIVE_LEVERAGE_CAP, RISK_PER_TRADE * 100, LIVE_MARGIN_BUFFER * 100)
        threading.Thread(target=live_reconciler, daemon=True).start()

    time.sleep(5)

    send_telegram(
        f"⚡ <b>NRM Bot Started</b>\n"
        f"Mode: {TRADING_MODE}\n"
        f"Balance A: ${state['balance']:.2f} | W{state['wins']}/L{state['losses']}\n"
        f"Balance B: ${state_b['balance']:.2f}\n"
        f"Balance C: ${state_c['balance']:.2f}\n"
        f"Balance D: ${state_d['balance']:.2f}\n"
        f"RSI: Real-time WebSocket\n"
        f"Strategy A: 60s | Strategy B: 30s"
    )

    last_run_a = 0

    while state["running"]:
        try:
            now    = datetime.now(timezone.utc)
            now_ts = now.timestamp()
            now_str = now.strftime("%Y-%m-%d %H:%M UTC")
            cycle_a = int(os.environ.get("CYCLE_SECONDS", str(DEFAULT_CYCLE_SECONDS)))

            # Strategy A every 60s
            if now_ts - last_run_a >= cycle_a:
                state["last_cycle"] = now_str
                try:
                    run_strategy_a()
                except Exception as e:
                    log.error(f"Strategy A error: {e}")
                    with state_lock:
                        state["errors"].append(f"{now.strftime('%H:%M')} {str(e)[:80]}")
                        state["errors"] = state["errors"][-ERROR_HISTORY_LIMIT:]
                save_state()
                last_run_a = now_ts

            # Strategy B every 30s
            state_b["last_cycle"] = now_str
            try:
                run_strategy_b()
            except Exception as e:
                log.error(f"Strategy B error: {e}")
                with state_lock_b:
                    state_b["errors"].append(f"{now.strftime('%H:%M')} {str(e)[:80]}")
                    state_b["errors"] = state_b["errors"][-ERROR_HISTORY_LIMIT:]
            save_state_b()

            # Strategy CM (Check Mark) every 30s
            state_cm["last_cycle"] = now_str
            try:
                run_strategy_cm()
            except Exception as e:
                log.error(f"Strategy CM error: {e}")
                with state_lock_cm:
                    state_cm["errors"].append(f"{now.strftime('%H:%M')} {str(e)[:80]}")
                    state_cm["errors"] = state_cm["errors"][-ERROR_HISTORY_LIMIT:]
            save_state_cm()

            # Strategy C: check open position every 30s (entries via webhook only)
            state_c["last_cycle"]    = now_str
            state_c["current_price"] = rt.price
            state_c["current_rsi"]   = rt.rsi_15m
            if state_c["position"]:
                try:
                    check_position_c(rt.price)
                except Exception as e:
                    log.error(f"Strategy C error: {e}")
            save_state_c()

            # Strategy D: check open position every 30s (entries via webhook only)
            state_d["last_cycle"]    = now_str
            state_d["current_price"] = rt.price
            if state_d["position"]:
                try:
                    check_position_d(rt.price)
                except Exception as e:
                    log.error(f"Strategy D error: {e}")
            save_state_d()

            # Strategy SMC: check open position every 30s (entries via webhook only)
            state_smc["last_cycle"]    = now_str
            state_smc["current_price"] = rt.price
            if state_smc["position"]:
                try:
                    check_position_smc(rt.price)
                except Exception as e:
                    log.error(f"Strategy SMC error: {e}")
            save_state_smc()

        except Exception as e:  # broad on purpose: scheduler loop must never crash
            log.error(f"Main loop error: {e}")

        time.sleep(SCHEDULER_SLEEP_SECONDS)


bot_thread = threading.Thread(target=bot_loop, daemon=True)
