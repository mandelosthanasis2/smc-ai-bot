"""
bot.py - SMC AI Trading Bot v3
WebSocket real-time price + RSI from Bitget
Strategy A: Daily box + 1H RSI
Strategy B: 1H box + 15m RSI
"""

import os
import json
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
    except Exception as e:
        log.warning(f"Telegram error: {e}")

# -- BITGET API ---------------------------------------------------
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
    except Exception as e:
        log.error(f"Bitget signed error: {e}")
        return {}

def get_candles(granularity, limit=500):
    gran_map = {"1H": "1H", "4H": "4H", "1D": "4H", "15m": "15m"}
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
        except Exception:
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

def place_order_live(side, qty, sl, tp):
    bitget_signed("POST", "/api/v2/mix/account/set-leverage", {
        "symbol": BITGET_SYMBOL, "productType": BITGET_PROD_TYPE,
        "marginCoin": "USDT", "leverage": str(LEVERAGE),
        "holdSide": "long" if side == "LONG" else "short",
    })
    r = bitget_signed("POST", "/api/v2/mix/order/place-order", {
        "symbol": BITGET_SYMBOL, "productType": BITGET_PROD_TYPE,
        "marginMode": "isolated", "marginCoin": "USDT",
        "size": str(round(qty, 4)),
        "side": "buy" if side == "LONG" else "sell",
        "tradeSide": "open", "orderType": "market",
        "presetStopSurplusPrice": str(round(tp, 2)),
        "presetStopLossPrice":    str(round(sl, 2)),
    })
    log.info(f"Live order: {r}")
    return r.get("data", {}).get("orderId", None)

def close_position_live(side, qty):
    bitget_signed("POST", "/api/v2/mix/order/place-order", {
        "symbol": BITGET_SYMBOL, "productType": BITGET_PROD_TYPE,
        "marginCoin": "USDT",
        "side": "sell" if side == "LONG" else "buy",
        "tradeSide": "close", "orderType": "market",
        "size": str(qty),
    })

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
        except Exception:
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
        except Exception as e:
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
                    ws.run_forever(
                        ping_interval=15,
                        ping_timeout=8,
                        reconnect=5,
                    )
                except Exception as e:
                    log.error(f"WS run error: {e}")
                time.sleep(3)

        threading.Thread(target=run, daemon=True).start()

        # Bitget requires a ping every 30s to keep connection alive
        def keep_alive():
            import time as t
            while True:
                t.sleep(25)
                try:
                    # Polling handles price updates when WS is down
                    pass
                except Exception:
                    pass

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
                except Exception:
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
    "position": None, "last_signal": "Starting...", "last_signal_time": "",
    "trades": [], "balance": 10000.0, "pnl_total": 0.0,
    "wins": 0, "losses": 0, "box": None, "current_rsi": 50.0,
    "current_price": 0.0, "last_cycle": "", "errors": [], "last_divergence": False,
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

def load_state_c():
    try:
        if os.path.exists(STATE_FILE_C):
            with open(STATE_FILE_C) as f: saved = json.load(f)
            merged = {**DEFAULT_STATE_C, **saved}
            log.info(f"State C loaded: ${merged.get('balance',10000):.2f} W{merged.get('wins',0)}/L{merged.get('losses',0)}")
            return merged
    except Exception as e:
        log.warning(f"Load state C error: {e}")
    merged = {**DEFAULT_STATE_C, **SAVED_STATE_C}
    log.info(f"SAVED_STATE_C: ${merged['balance']:.2f} W{merged['wins']}/L{merged['losses']}")
    return merged

def save_state_c():
    try:
        with open(STATE_FILE_C, "w") as f:
            json.dump(state_c, f, indent=2, default=str)
    except Exception as e:
        log.warning(f"Save state C error: {e}")

def load_state():
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE) as f: saved = json.load(f)
            merged = {**DEFAULT_STATE, **saved}
            merged["running"] = True; merged["mode"] = TRADING_MODE
            log.info(f"State A loaded: ${merged['balance']:.2f} W{merged['wins']}/L{merged['losses']}")
            return merged
    except Exception as e:
        log.warning(f"Load state error: {e}")
    merged = {**DEFAULT_STATE, **SAVED_STATE}
    merged["running"] = True; merged["mode"] = TRADING_MODE
    log.info(f"SAVED_STATE: ${merged['balance']:.2f}")
    return merged

def load_state_b():
    try:
        if os.path.exists(STATE_FILE_B):
            with open(STATE_FILE_B) as f: saved = json.load(f)
            merged = {**DEFAULT_STATE_B, **saved}
            log.info(f"State B loaded: ${merged.get('balance',10000):.2f} W{merged.get('wins',0)}/L{merged.get('losses',0)}")
            return merged
    except Exception as e:
        log.warning(f"Load state B error: {e}")
    merged = {**DEFAULT_STATE_B, **SAVED_STATE_B}
    log.info(f"SAVED_STATE_B: ${merged['balance']:.2f} W{merged['wins']}/L{merged['losses']}")
    return merged

def save_state():
    try:
        with open(STATE_FILE, "w") as f:
            json.dump({k:v for k,v in state.items() if k!="running"}, f, indent=2, default=str)
    except Exception as e:
        log.warning(f"Save state error: {e}")

def save_state_b():
    try:
        with open(STATE_FILE_B, "w") as f:
            json.dump(state_b, f, indent=2, default=str)
    except Exception as e:
        log.warning(f"Save state B error: {e}")

state   = load_state()
state["running"] = True
state_b = load_state_b()
state_c = load_state_c()

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
        except Exception: pass
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
    except Exception as e:
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
    except Exception: return state["balance"]

def calc_qty(balance, risk_pct, entry, sl):
    risk_dist = abs(entry - sl)
    if risk_dist <= 0: return 0.001
    return max(round((balance * risk_pct) / risk_dist, 4), 0.001)

def finalize_trade_a(price, result, note=""):
    pos = state["position"]
    if not pos: return
    pnl = round(((price-pos["entry"]) if pos["type"]=="LONG" else (pos["entry"]-price)) * pos["qty"], 2)
    state["pnl_total"] = round(state["pnl_total"] + pnl, 2)
    state["balance"]   = round(state["balance"]   + pnl, 2)
    if result == "WIN": state["wins"]   += 1
    else:               state["losses"] += 1
    state["trades"].append({
        "type": pos["type"], "entry": pos["entry"], "close": price,
        "pnl": pnl, "result": result,
        "time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "news_score": pos.get("news_score", 0),
        "divergence": pos.get("has_divergence", False), "note": note,
    })
    wins = state["wins"]; losses = state["losses"]
    wr   = round(wins/(wins+losses)*100) if wins+losses>0 else 0
    emoji = "✅" if result=="WIN" else "❌"
    send_telegram(
        f"{emoji} <b>[A] {note or result}</b>\n"
        f"PnL: {'+' if pnl>=0 else ''}${pnl:.2f}\n"
        f"Balance: ${state['balance']:,.2f}\n"
        f"W/L: {wins}W/{losses}L | WR: {wr}%"
    )
    if TRADING_MODE == "LIVE": close_position_live(pos["type"], pos["qty"])
    state["position"] = None
    save_state()

def check_position_a(price):
    pos = state["position"]
    if not pos: return

    if os.environ.get("FORCE_CLOSE","").lower() == "true":
        finalize_trade_a(price, "WIN" if price>pos["entry"] else "LOSS", "FORCE CLOSE")
        return

    entry   = pos["entry"]
    tp      = pos["tp"]
    is_long = pos["type"] == "LONG"
    tp_dist = abs(tp - entry)
    if tp_dist == 0: return

    progress = ((price-entry)/tp_dist) if is_long else ((entry-price)/tp_dist)

    # Phase 1: 50% - Break Even
    if not pos.get("phase1_done") and progress >= 0.50:
        pos["sl"] = entry; pos["phase1_done"] = True
        log.info(f"[A] Phase 1: SL -> entry @ {entry:.2f}")
        send_telegram(f"🔒 <b>[A] BREAK EVEN</b>\nSL moved to ${entry:,.2f}")
        save_state()

    # Phase 2: 70% - Partial 30% close
    if not pos.get("phase2_done") and progress >= 0.70:
        pqty = round(pos["qty"]*0.30, 4)
        ppnl = round(((price-entry) if is_long else (entry-price))*pqty, 2)
        pos["qty"] = round(pos["qty"]-pqty, 4); pos["phase2_done"] = True
        state["pnl_total"] = round(state["pnl_total"]+ppnl, 2)
        state["balance"]   = round(state["balance"]  +ppnl, 2)
        log.info(f"[A] Phase 2: Partial 30% @ {price:.2f} PnL={ppnl:+.2f}")
        send_telegram(f"💰 <b>[A] PARTIAL 30%</b>\n+${ppnl:.2f} | Rem: {pos['qty']:.4f} BTC")
        if TRADING_MODE == "LIVE": close_position_live(pos["type"], pqty)
        save_state()

    # Phase 3+4: Past TP - Trailing stop
    past_tp = (is_long and price>=tp) or (not is_long and price<=tp)
    if past_tp:
        if not pos.get("trailing_active"):
            pos["trailing_active"] = True
            pos["trailing_high"]   = price
            log.info(f"[A] Phase 3: Trailing activated @ {price:.2f}")
            send_telegram(f"🚀 <b>[A] TRAILING ACTIVE</b>\nPassed TP ${tp:,.2f}")
            save_state()

        # Update trailing high
        if is_long: pos["trailing_high"] = max(pos.get("trailing_high",price), price)
        else:       pos["trailing_high"] = min(pos.get("trailing_high",price), price)

        th = pos["trailing_high"]
        ts = th*0.99 if is_long else th*1.01
        if (is_long and price<=ts) or (not is_long and price>=ts):
            log.info(f"[A] Phase 4: Trailing hit @ {price:.2f} (high={th:.2f})")
            finalize_trade_a(price, "WIN", f"TRAILING (high=${th:,.2f})")
        return

    # Normal SL
    hit_sl = (is_long and price<=pos["sl"]) or (not is_long and price>=pos["sl"])
    if hit_sl:
        result = "WIN" if pos["sl"]>=entry else "LOSS"
        finalize_trade_a(pos["sl"], result, "STOP LOSS")

# =================================================================
# POSITION MANAGEMENT - Strategy B (2 phases)
# =================================================================

def finalize_trade_b(price, result, note=""):
    pos = state_b["position"]
    if not pos: return
    pnl = round(((price-pos["entry"]) if pos["type"]=="LONG" else (pos["entry"]-price))*pos["qty"], 2)
    state_b["pnl_total"] = round(state_b["pnl_total"]+pnl, 2)
    state_b["balance"]   = round(state_b["balance"]  +pnl, 2)
    if result=="WIN": state_b["wins"]   += 1
    else:             state_b["losses"] += 1
    state_b["trades"].append({
        "type": pos["type"], "entry": pos["entry"], "close": price,
        "pnl": pnl, "result": result,
        "time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "divergence": pos.get("has_divergence", False), "note": note,
    })
    wins=state_b["wins"]; losses=state_b["losses"]
    emoji = "✅" if result=="WIN" else "❌"
    send_telegram(
        f"{emoji} <b>[B] {note or result}</b>\n"
        f"PnL: {'+' if pnl>=0 else ''}${pnl:.2f}\n"
        f"Balance: ${state_b['balance']:,.2f}\n"
        f"W/L: {wins}W/{losses}L"
    )
    state_b["position"] = None
    save_state_b()

def check_position_b(price):
    pos = state_b["position"]
    if not pos: return

    if os.environ.get("FORCE_CLOSE_B","").lower() == "true":
        finalize_trade_b(price, "WIN" if price>pos["entry"] else "LOSS", "FORCE CLOSE")
        return

    entry   = pos["entry"]
    tp      = pos["tp"]
    is_long = pos["type"] == "LONG"
    tp_dist = abs(tp-entry)

    # Phase 1: 50% - Break Even
    if tp_dist>0 and not pos.get("phase1_done"):
        progress = ((price-entry)/tp_dist) if is_long else ((entry-price)/tp_dist)
        if progress >= 0.50:
            pos["sl"] = entry; pos["phase1_done"] = True
            log.info(f"[B] Phase 1: SL -> entry @ {entry:.2f}")
            send_telegram(f"🔒 <b>[B] BREAK EVEN</b>\nSL moved to ${entry:,.2f}")
            save_state_b()

    hit_tp = (is_long and price>=tp) or (not is_long and price<=tp)
    hit_sl = (is_long and price<=pos["sl"]) or (not is_long and price>=pos["sl"])

    if hit_tp: finalize_trade_b(tp,         "WIN",  "TAKE PROFIT")
    elif hit_sl:
        result = "WIN" if pos["sl"]>=entry else "LOSS"
        finalize_trade_b(pos["sl"], result, "STOP LOSS")

# =================================================================
# STRATEGY A - Daily box + 1H RSI
# =================================================================

def run_strategy_a():
    price = rt.price
    rsi   = rt.rsi_1h

    state["current_price"] = price
    state["current_rsi"]   = rsi

    if price<=0 or not rt.initialized:
        state["last_signal"] = "Initializing..."
        return

    if state["position"]:
        check_position_a(price)
        if state["position"]:
            pos = state["position"]
            pnl = ((price-pos["entry"]) if pos["type"]=="LONG" else (pos["entry"]-price))*pos["qty"]
            state["last_signal"] = f"HOLDING {pos['type']} @ {pos['entry']:.2f} | PnL: {pnl:+.2f}"
            return

    candles_4h = get_candles("4H", 500)
    candles_1h = get_candles("1H", 200)
    if not candles_4h or not candles_1h:
        state["last_signal"] = "No candle data"
        return

    box = build_daily_box(candles_4h)
    if not box:
        state["last_signal"] = "No box"
        return
    state["box"] = box

    highs_1h = [c["high"] for c in candles_1h]
    lows_1h  = [c["low"]  for c in candles_1h]
    with rt.lock:
        closes_1h = list(rt.closes_1h)
    bull_div, bear_div = detect_divergence(closes_1h, highs_1h[-20:], lows_1h[-20:])
    state["last_divergence"] = bull_div or bear_div

    support, resistance = find_4h_sr(candles_4h, price)
    balance = get_balance_a()

    log.info(f"[A] Price={price:.2f} RSI={rsi} Box=[{box['low']:.0f}-{box['high']:.0f}] MID={box['mid']:.0f} div={bull_div}/{bear_div}")

    # SHORT at PDH
    at_pdh = (price >= box["high"]*0.995) and (price <= box["high"]*1.015)
    if at_pdh and rsi>70 and box["mid"]<price:
        sl = round(resistance*1.003, 2)
        tp = box["mid"]
        if tp>=price: tp=round(price*0.99, 2)
        if sl<=price: sl=round(price*1.01, 2)
        if sl>price*1.015: sl=round(price*1.015, 2)
        risk_pct = RISK_PER_TRADE*2 if bear_div else RISK_PER_TRADE
        qty      = calc_qty(balance, risk_pct, price, sl)
        log.info(f"[A] SHORT: entry={price:.2f} tp={tp:.2f} sl={sl:.2f}")
        headlines      = fetch_news()
        score, summary = ai_news_score(headlines, "SHORT", price, box)
        send_telegram(f"📰 <b>[A] News SHORT</b>\nScore:{score} | {summary}")
        order_id = place_order_paper("SHORT",qty,price,sl,tp) if TRADING_MODE=="PAPER" else place_order_live("SHORT",qty,sl,tp)
        if order_id:
            state["position"] = {"type":"SHORT","entry":price,"sl":sl,"tp":tp,"qty":qty,
                                  "time":datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                                  "order_id":order_id,"news_score":score,"news_summary":summary,"has_divergence":bear_div}
            state["last_signal"]="SHORT"; state["last_signal_time"]=datetime.now(timezone.utc).strftime("%H:%M UTC")
            save_state()
            send_telegram(f"🔴 <b>[A] SHORT</b>\nEntry:${price:,.2f} TP:${tp:,.2f} SL:${sl:,.2f}\n{'🔥DIV' if bear_div else 'Normal'}")
        return

    # LONG at PDL
    at_pdl = (price <= box["low"]*1.005) and (price >= box["low"]*0.985)
    if at_pdl and rsi<30 and box["mid"]>price:
        sl = round(support*0.997, 2)
        tp = box["mid"]
        if tp<=price: tp=round(price*1.01, 2)
        if sl>=price: sl=round(price*0.99, 2)
        if sl<price*0.985: sl=round(price*0.985, 2)
        risk_pct = RISK_PER_TRADE*2 if bull_div else RISK_PER_TRADE
        qty      = calc_qty(balance, risk_pct, price, sl)
        log.info(f"[A] LONG: entry={price:.2f} tp={tp:.2f} sl={sl:.2f}")
        headlines      = fetch_news()
        score, summary = ai_news_score(headlines, "LONG", price, box)
        send_telegram(f"📰 <b>[A] News LONG</b>\nScore:{score} | {summary}")
        order_id = place_order_paper("LONG",qty,price,sl,tp) if TRADING_MODE=="PAPER" else place_order_live("LONG",qty,sl,tp)
        if order_id:
            state["position"] = {"type":"LONG","entry":price,"sl":sl,"tp":tp,"qty":qty,
                                  "time":datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                                  "order_id":order_id,"news_score":score,"news_summary":summary,"has_divergence":bull_div}
            state["last_signal"]="LONG"; state["last_signal_time"]=datetime.now(timezone.utc).strftime("%H:%M UTC")
            save_state()
            send_telegram(f"🟢 <b>[A] LONG</b>\nEntry:${price:,.2f} TP:${tp:,.2f} SL:${sl:,.2f}\n{'🔥DIV' if bull_div else 'Normal'}")
        return

    div_txt = "Div!" if (bull_div or bear_div) else "No div"
    state["last_signal"] = f"WAIT | RSI={rsi} | [{box['low']:.0f}-{box['high']:.0f}] | {div_txt}"
    log.info(f"[A] {state['last_signal']}")

# =================================================================
# POSITION MANAGEMENT - Strategy C (webhook only, same as B)
# =================================================================

def finalize_trade_c(price, result, note=""):
    pos = state_c["position"]
    if not pos: return
    pnl = round(((price-pos["entry"]) if pos["type"]=="LONG" else (pos["entry"]-price))*pos["qty"], 2)
    state_c["pnl_total"] = round(state_c["pnl_total"]+pnl, 2)
    state_c["balance"]   = round(state_c["balance"]  +pnl, 2)
    if result=="WIN": state_c["wins"]   += 1
    else:             state_c["losses"] += 1
    state_c["trades"].append({
        "type": pos["type"], "entry": pos["entry"], "close": price,
        "pnl": pnl, "result": result,
        "time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "divergence": pos.get("has_divergence", False), "note": note,
    })
    wins=state_c["wins"]; losses=state_c["losses"]
    emoji = "✅" if result=="WIN" else "❌"
    msg = (f"{emoji} <b>[C] {note or result}</b>\n"
           f"PnL: {'+' if pnl>=0 else ''}${pnl:.2f}\n"
           f"Balance: ${state_c['balance']:,.2f}\n"
           f"W/L: {wins}W/{losses}L")
    send_telegram(msg)
    state_c["position"] = None
    save_state_c()

def check_position_c(price):
    pos = state_c["position"]
    if not pos: return

    if os.environ.get("FORCE_CLOSE_C","").lower() == "true":
        finalize_trade_c(price, "WIN" if price>pos["entry"] else "LOSS", "FORCE CLOSE")
        return

    entry   = pos["entry"]
    tp      = pos["tp"]
    is_long = pos["type"] == "LONG"
    tp_dist = abs(tp-entry)

    # Phase 1: 50% - Break Even
    if tp_dist>0 and not pos.get("phase1_done"):
        progress = ((price-entry)/tp_dist) if is_long else ((entry-price)/tp_dist)
        if progress >= 0.50:
            pos["sl"] = entry; pos["phase1_done"] = True
            log.info(f"[C] Phase 1: SL -> entry @ {entry:.2f}")
            send_telegram(f"🔒 <b>[C] BREAK EVEN</b>\nSL moved to ${entry:,.2f}")
            save_state_c()

    hit_tp = (is_long and price>=tp) or (not is_long and price<=tp)
    hit_sl = (is_long and price<=pos["sl"]) or (not is_long and price>=pos["sl"])

    if hit_tp: finalize_trade_c(tp, "WIN", "TAKE PROFIT")
    elif hit_sl:
        result = "WIN" if pos["sl"]>=entry else "LOSS"
        finalize_trade_c(pos["sl"], result, "STOP LOSS")

# =================================================================
# STRATEGY B - 1H box + 15m RSI
# =================================================================

def run_strategy_b():
    price   = rt.price
    rsi_15m = rt.rsi_15m

    state_b["current_rsi"]   = rsi_15m
    state_b["current_price"] = price  # needed for dashboard unrealised PnL

    if price<=0 or not rt.initialized:
        state_b["last_signal"] = "Initializing..."
        return

    if state_b["position"]:
        check_position_b(price)
        if state_b["position"]:
            pos = state_b["position"]
            pnl = ((price-pos["entry"]) if pos["type"]=="LONG" else (pos["entry"]-price))*pos["qty"]
            state_b["last_signal"] = f"HOLDING {pos['type']} @ {pos['entry']:.2f} | PnL: {pnl:+.2f}"
            return

    candles_1h = get_candles("1H", 50)
    if not candles_1h:
        state_b["last_signal"] = "No candle data"
        return

    box = build_1h_box(candles_1h)
    if not box: return
    state_b["box"] = box

    candles_15m = get_candles("15m", 100)
    if candles_15m:
        h15 = [c["high"] for c in candles_15m]
        l15 = [c["low"]  for c in candles_15m]
        with rt.lock: c15 = list(rt.closes_15m)
        bull_div, bear_div = detect_divergence(c15, h15[-20:], l15[-20:])
    else:
        bull_div = bear_div = False
    state_b["last_divergence"] = bull_div or bear_div

    balance = state_b["balance"]
    log.info(f"[B] Price={price:.2f} RSI15m={rsi_15m} 1H=[{box['low']:.0f}-{box['high']:.0f}]")

    # SHORT at 1H High
    at_high = (price>=box["high"]*0.995) and (price<=box["high"]*1.015)
    if at_high and rsi_15m>70 and box["mid"]<price:
        tp_dist = price - box["mid"]
        sl_dist = tp_dist/2
        tp=box["mid"]; sl=round(price+sl_dist, 2)
        risk_pct = RISK_PER_TRADE*2 if bear_div else RISK_PER_TRADE
        qty      = calc_qty(balance, risk_pct, price, sl)
        order_id = place_order_paper("SHORT",qty,price,sl,tp) if TRADING_MODE=="PAPER" else place_order_live("SHORT",qty,sl,tp)
        if order_id:
            state_b["position"]={"type":"SHORT","entry":price,"sl":sl,"tp":tp,"qty":qty,
                                   "time":datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                                   "order_id":order_id,"has_divergence":bear_div}
            state_b["last_signal"]="SHORT"; state_b["last_signal_time"]=datetime.now(timezone.utc).strftime("%H:%M UTC")
            save_state_b()
            send_telegram(f"🔴 <b>[B] SHORT</b>\nEntry:${price:,.2f} TP:${tp:,.2f} SL:${sl:,.2f}\nR/R 2:1 {'🔥DIV' if bear_div else ''}")
        return

    # LONG at 1H Low
    at_low = (price<=box["low"]*1.005) and (price>=box["low"]*0.985)
    if at_low and rsi_15m<30 and box["mid"]>price:
        tp_dist = box["mid"] - price
        sl_dist = tp_dist/2
        tp=box["mid"]; sl=round(price-sl_dist, 2)
        risk_pct = RISK_PER_TRADE*2 if bull_div else RISK_PER_TRADE
        qty      = calc_qty(balance, risk_pct, price, sl)
        order_id = place_order_paper("LONG",qty,price,sl,tp) if TRADING_MODE=="PAPER" else place_order_live("LONG",qty,sl,tp)
        if order_id:
            state_b["position"]={"type":"LONG","entry":price,"sl":sl,"tp":tp,"qty":qty,
                                   "time":datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                                   "order_id":order_id,"has_divergence":bull_div}
            state_b["last_signal"]="LONG"; state_b["last_signal_time"]=datetime.now(timezone.utc).strftime("%H:%M UTC")
            save_state_b()
            send_telegram(f"🟢 <b>[B] LONG</b>\nEntry:${price:,.2f} TP:${tp:,.2f} SL:${sl:,.2f}\nR/R 2:1 {'🔥DIV' if bull_div else ''}")
        return

    div_txt = "Div!" if (bull_div or bear_div) else "No div"
    state_b["last_signal"] = f"WAIT | RSI={rsi_15m} | [{box['low']:.0f}-{box['high']:.0f}] | {div_txt}"
    log.info(f"[B] {state_b['last_signal']}")

# =================================================================
# BOT LOOP
# =================================================================

def bot_loop():
    log.info("=" * 45)
    log.info("  SMC AI BOT v3 - Real-time WebSocket RSI")
    log.info(f"  Mode: {TRADING_MODE} | Leverage: {LEVERAGE}x")
    log.info(f"  Balance A: ${state['balance']:.2f} W{state['wins']}/L{state['losses']}")
    log.info(f"  Balance B: ${state_b['balance']:.2f}")
    log.info("=" * 45)

    rt.load_history()
    rt.start_websocket()
    rt.start_polling()
    time.sleep(5)

    send_telegram(
        f"⚡ <b>SMC AI Bot v3 Started</b>\n"
        f"Mode: {TRADING_MODE}\n"
        f"Balance A: ${state['balance']:.2f} | W{state['wins']}/L{state['losses']}\n"
        f"Balance B: ${state_b['balance']:.2f}\n"
        f"RSI: Real-time WebSocket\n"
        f"Strategy A: 60s | Strategy B: 30s"
    )

    last_run_a = 0

    while state["running"]:
        try:
            now    = datetime.now(timezone.utc)
            now_ts = now.timestamp()
            now_str = now.strftime("%Y-%m-%d %H:%M UTC")
            cycle_a = int(os.environ.get("CYCLE_SECONDS", "60"))

            # Strategy A every 60s
            if now_ts - last_run_a >= cycle_a:
                state["last_cycle"] = now_str
                try:
                    run_strategy_a()
                except Exception as e:
                    log.error(f"Strategy A error: {e}")
                    state["errors"].append(f"{now.strftime('%H:%M')} {str(e)[:80]}")
                    state["errors"] = state["errors"][-10:]
                save_state()
                last_run_a = now_ts

            # Strategy B every 30s
            state_b["last_cycle"] = now_str
            try:
                run_strategy_b()
            except Exception as e:
                log.error(f"Strategy B error: {e}")
                state_b["errors"].append(f"{now.strftime('%H:%M')} {str(e)[:80]}")
                state_b["errors"] = state_b["errors"][-10:]
            save_state_b()

            # Strategy C: check open position every 30s (entries via webhook only)
            state_c["last_cycle"]   = now_str
            state_c["current_price"] = rt.price
            state_c["current_rsi"]  = rt.rsi_15m
            if state_c["position"]:
                try:
                    check_position_c(rt.price)
                except Exception as e:
                    log.error(f"Strategy C error: {e}")
            save_state_c()

        except Exception as e:
            log.error(f"Main loop error: {e}")

        time.sleep(30)


bot_thread = threading.Thread(target=bot_loop, daemon=True)
