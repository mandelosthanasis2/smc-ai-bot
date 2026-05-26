"""
BTC Multi-Agent Analysis System
Runs 3x daily (08:00, 13:00, 20:00 Greece time)
and sends a Telegram briefing.
"""

import os
import requests
import threading
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import anthropic
import schedule
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
ANTHROPIC_KEY   = os.environ.get("ANTHROPIC_API_KEY", "")
TELEGRAM_TOKEN  = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT   = os.environ.get("TELEGRAM_CHAT_ID", "")
BOT_URL         = os.environ.get("BOT_URL", "https://web-production-85af7.up.railway.app")
GREECE_TZ       = ZoneInfo("Europe/Athens")
claude          = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
MODEL           = "claude-haiku-4-5-20251001"   # fast & cheap for agents

# ── Helpers ───────────────────────────────────────────────────────────────────

def send_telegram(text: str):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception as e:
        log.error(f"Telegram error: {e}")


def ask_claude(system: str, user: str) -> str:
    """Single Claude call, returns text."""
    try:
        resp = claude.messages.create(
            model=MODEL,
            max_tokens=400,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return resp.content[0].text.strip()
    except Exception as e:
        log.error(f"Claude error: {e}")
        return "N/A"


def fetch_bot_data() -> dict:
    try:
        from bot import state, state_b, state_c, state_d, rt
        a = dict(state)
        a["price"]   = rt.price if rt.price > 0 else state.get("current_price", 0)
        a["rsi_1h"]  = round(rt.rsi_1h, 2) if hasattr(rt, "rsi_1h") else state.get("current_rsi", 0)
        a["rsi_15m"] = round(rt.rsi_15m, 2) if hasattr(rt, "rsi_15m") else 0
        a["box_high"] = (state.get("box") or {}).get("high", 0)
        a["box_low"]  = (state.get("box") or {}).get("low", 0)
        a["mid"]      = (state.get("box") or {}).get("mid", 0)
        return {"A": a, "B": dict(state_b), "C": dict(state_c), "D": dict(state_d)}
    except Exception as e:
        log.warning(f"Direct import failed: {e}")
        data = {}
        for endpoint, key in [("/api","A"),("/api/b","B"),("/api/c","C"),("/api/d","D")]:
            try:
                r = requests.get(BOT_URL + endpoint, timeout=8)
                data[key] = r.json()
            except Exception:
                data[key] = {}
        return data


def fetch_btc_news() -> str:
    """
    Fetch BTC headlines από πολλαπλές πηγές:
    1. CryptoCompare (free, no key)
    2. RSS feeds (CoinDesk, CoinTelegraph, Decrypt)
    Επιστρέφει τα 8 πιο πρόσφατα headlines.
    """
    headlines = []

    # ── Πηγή 1: CryptoCompare (χωρίς key) ───────────────────────
    try:
        r = requests.get(
            "https://min-api.cryptocompare.com/data/v2/news/"
            "?lang=EN&categories=BTC&sortOrder=latest&limit=5",
            timeout=8,
        )
        data = r.json()
        if data.get("Type") == 100:
            for item in data.get("Data", [])[:5]:
                title = item.get("title", "")
                if title:
                    headlines.append(title)
    except Exception as e:
        log.debug(f"CryptoCompare news error: {e}")

    # ── Πηγή 2: RSS feeds ────────────────────────────────────────
    if len(headlines) < 8:
        rss_feeds = [
            "https://www.coindesk.com/arc/outboundfeeds/rss/",
            "https://cointelegraph.com/rss",
            "https://decrypt.co/feed",
        ]
        try:
            import feedparser
            for feed_url in rss_feeds:
                if len(headlines) >= 8:
                    break
                try:
                    feed = feedparser.parse(feed_url)
                    for entry in feed.entries[:3]:
                        title = entry.get("title", "")
                        # Φιλτράρουμε μόνο BTC-σχετικά
                        if title and any(kw in title.upper() for kw in
                                        ["BTC", "BITCOIN", "CRYPTO", "BLOCKCHAIN", "ETF",
                                         "FED", "RATE", "MARKET", "BULL", "BEAR"]):
                            if title not in headlines:
                                headlines.append(title)
                except Exception:
                    continue
        except ImportError:
            log.debug("feedparser not installed")

    # ── Fallback: Reddit r/Bitcoin ────────────────────────────────
    if not headlines:
        try:
            r = requests.get(
                "https://www.reddit.com/r/Bitcoin/hot.json?limit=5",
                headers={"User-Agent": "NRMBot/1.0"},
                timeout=8,
            )
            posts = r.json().get("data", {}).get("children", [])
            for p in posts[:5]:
                title = p.get("data", {}).get("title", "")
                if title:
                    headlines.append(title)
        except Exception as e:
            log.debug(f"Reddit fallback error: {e}")

    if not headlines:
        return "Δεν υπάρχουν διαθέσιμα νέα"

    return "\n".join(f"• {h[:100]}" for h in headlines[:8])


def fetch_fear_greed() -> str:
    """Fetch Fear & Greed index."""
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=8)
        d = r.json()["data"][0]
        return f"{d['value']} ({d['value_classification']})"
    except Exception:
        return "N/A"


def fetch_funding_rate() -> str:
    """Fetch BTC perpetual funding rate from Bitget."""
    try:
        r = requests.get(
            "https://api.bitget.com/api/v2/mix/market/current-fund-rate?symbol=BTCUSDT&productType=USDT-FUTURES",
            timeout=8,
        )
        rate = float(r.json()["data"][0]["fundingRate"]) * 100
        return f"{rate:+.4f}%"
    except Exception:
        return "N/A"

def fetch_btc_dominance() -> str:
    """BTC Dominance % από CoinPaprika (free, no key)."""
    try:
        r = requests.get("https://api.coinpaprika.com/v1/global", timeout=8)
        d = r.json()
        dom = d.get("bitcoin_dominance_percentage", 0)
        return f"{dom:.1f}%"
    except Exception:
        return "N/A"


def fetch_open_interest() -> str:
    """BTC Open Interest από Bitget."""
    try:
        r = requests.get(
            "https://api.bitget.com/api/v2/mix/market/open-interest"
            "?symbol=BTCUSDT&productType=usdt-futures",
            timeout=8
        )
        d = r.json()
        oi = float(d["data"][0].get("openInterestList", [{}])[0].get("openInterest", 0) or
                   d["data"][0].get("openInterest", 0))
        if oi > 1_000_000_000:
            return f"${oi/1_000_000_000:.2f}B"
        elif oi > 1_000_000:
            return f"${oi/1_000_000:.1f}M"
        return f"${oi:,.0f}"
    except Exception:
        return "N/A"


def fetch_long_short_ratio() -> str:
    """BTC Long/Short Ratio από Bitget."""
    try:
        r = requests.get(
            "https://api.bitget.com/api/v2/mix/market/account-long-short-ratio"
            "?symbol=BTCUSDT&productType=usdt-futures&period=1h",
            timeout=8
        )
        d = r.json()
        items = d.get("data", [])
        if items:
            ls = float(items[-1].get("longShortRatio", 1))
            long_pct  = round(ls / (1 + ls) * 100, 1)
            short_pct = round(100 - long_pct, 1)
            sentiment = "🟢 Longs κυριαρχούν" if ls > 1.1 else "🔴 Shorts κυριαρχούν" if ls < 0.9 else "⚪ Ισορροπία"
            return f"L:{long_pct}% S:{short_pct}% — {sentiment}"
    except Exception:
        pass
    return "N/A"


def fetch_btc_change_24h() -> str:
    """BTC 24h change % από Bitget."""
    try:
        r = requests.get(
            "https://api.bitget.com/api/v2/mix/market/ticker"
            "?symbol=BTCUSDT&productType=usdt-futures",
            timeout=8
        )
        d = r.json()
        change = float(d["data"][0].get("change24h", 0) or
                       d["data"][0].get("priceChangePercent", 0))
        arrow = "📈" if change >= 0 else "📉"
        return f"{arrow} {change:+.2f}%"
    except Exception:
        return "N/A"


# ── The 5 Agents ──────────────────────────────────────────────────────────────

def agent_technical(data: dict, price: float, rsi_1h: float, rsi_15m: float) -> str:
    a = data.get("A", {})
    box_h = a.get("box_high", "?")
    box_l = a.get("box_low", "?")
    mid   = a.get("mid", "?")
    return ask_claude(
        "Είσαι crypto technical analyst. ΜΟΝΟ ελληνικά. MAX 3 γραμμές. ΟΧΙ markdown/bold/headers.",
        f"""BTC current price: ${price:,.2f}
RSI 1H: {rsi_1h} | RSI 15m: {rsi_15m}
Daily Box: {box_l} - {box_h} | MID: {mid}

Give a brief technical outlook: trend, key levels, bias (bullish/bearish/neutral)."""
    )


def agent_sentiment(news: str, fear_greed: str) -> str:
    return ask_claude(
        "Είσαι crypto sentiment analyst. ΜΟΝΟ ελληνικά. MAX 2 γραμμές. ΟΧΙ markdown.",
        f"""Fear & Greed Index: {fear_greed}

Latest BTC news:
{news}

Summarize market sentiment: bullish/bearish/neutral and why."""
    )


def agent_onchain(funding: str, price: float,
                  open_interest: str = "N/A", ls_ratio: str = "N/A") -> str:
    return ask_claude(
        "Είσαι crypto on-chain analyst. ΜΟΝΟ ελληνικά. MAX 2 γραμμές. ΟΧΙ markdown.",
        f"""BTC Price: ${price:,.2f}
Funding Rate: {funding}
Open Interest: {open_interest}
Long/Short Ratio: {ls_ratio}

Ανάλυσε αυτά τα δεδομένα. Τι σηματοδοτούν για την κατεύθυνση;"""
    )


def agent_debate(technical: str, sentiment: str, onchain: str) -> tuple[str, str]:
    """Bull and Bear agents debate based on the 3 reports."""
    bull = ask_claude(
        "Είσαι BULL trader. ΜΟΝΟ ελληνικά. 1-2 προτάσεις. ΟΧΙ markdown.",
        f"Technical report:\n{technical}\n\nSentiment report:\n{sentiment}\n\nOn-chain report:\n{onchain}"
    )
    bear = ask_claude(
        "Είσαι BEAR trader. ΜΟΝΟ ελληνικά. 1-2 προτάσεις. ΟΧΙ markdown.",
        f"Technical report:\n{technical}\n\nSentiment report:\n{sentiment}\n\nOn-chain report:\n{onchain}"
    )
    return bull, bear


def agent_verdict(technical: str, sentiment: str, onchain: str,
                  bull: str, bear: str, data: dict, session: str) -> str:
    """Final verdict agent — reads everything and gives actionable advice."""
    # Summarize bot state
    states = []
    for k in ["A", "B", "C", "D"]:
        d = data.get(k, {})
        pos   = d.get("position", "FLAT")
        bal   = d.get("balance", "?")
        wins  = d.get("wins", 0)
        losses= d.get("losses", 0)
        states.append(f"Strategy {k}: {pos} | Balance: ${bal} | W{wins}/L{losses}")
    bot_state = "\n".join(states)

    return ask_claude(
        "Είσαι risk manager BTC bot. Session: " + session + ". ΜΟΝΟ ελληνικά. ΟΧΙ markdown. MAX 5 γραμμές. Format: VERDICT:[ΑΝΟΔΙΚΟ/ΚΑΘΟΔΙΚΟ/ΟΥΔΕΤΕΡΟ] | ΕΜΠΙΣΤΟΣΥΝΗ:[ΥΨΗΛΗ/ΜΕΤΡΙΑ/ΧΑΜΗΛΗ] — A:[1 φράση] — B:[1 φράση] — C:[1 φράση] — D:[1 φράση] — ΠΡΟΣΟΧΗ:[1 κίνδυνος]",
        f"""Technical:\n{technical}

Sentiment:\n{sentiment}

On-chain:\n{onchain}

Bull argument:\n{bull}

Bear argument:\n{bear}

Current bot state:\n{bot_state}"""
    )

# ── Main Briefing ─────────────────────────────────────────────────────────────

def run_briefing(session: str):
    """Run full multi-agent analysis and send Telegram."""
    log.info(f"Starting {session} briefing...")

    # 1. Fetch all data παράλληλα
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        f_bot      = ex.submit(fetch_bot_data)
        f_news     = ex.submit(fetch_btc_news)
        f_fg       = ex.submit(fetch_fear_greed)
        f_funding  = ex.submit(fetch_funding_rate)
        f_dom      = ex.submit(fetch_btc_dominance)
        f_oi       = ex.submit(fetch_open_interest)
        f_ls       = ex.submit(fetch_long_short_ratio)
        f_chg      = ex.submit(fetch_btc_change_24h)

    bot_data    = f_bot.result()
    news        = f_news.result()
    fear_greed  = f_fg.result()
    funding     = f_funding.result()
    dominance   = f_dom.result()
    open_interest = f_oi.result()
    ls_ratio    = f_ls.result()
    change_24h  = f_chg.result()

    # Extract price & RSI from strategy A
    a_data  = bot_data.get("A", {})
    price   = float(a_data.get("price") or a_data.get("current_price") or 0)
    rsi_1h  = a_data.get("rsi_1h") or a_data.get("current_rsi") or "?"
    rsi_15m = a_data.get("rsi_15m") or "?"

    # 2. Run 5 agents
    log.info("Running agents...")
    technical = agent_technical(bot_data, price, rsi_1h, rsi_15m)
    sentiment = agent_sentiment(news, fear_greed)
    onchain   = agent_onchain(funding, price, open_interest, ls_ratio)
    bull, bear = agent_debate(technical, sentiment, onchain)
    verdict   = agent_verdict(technical, sentiment, onchain, bull, bear, bot_data, session)

        # 3. Split σε 2 messages
    emoji  = {"🌅 ΠΡΩΙ": "🌅", "☀️ ΜΕΣΗΜΕΡΙ": "☀️", "🌙 ΒΡΑΔΥ": "🌙"}.get(session, "📊")
    now_gr = datetime.now(GREECE_TZ).strftime("%d/%m %H:%M")
    NL     = chr(10)
    msg1 = (emoji + " <b>BTC " + session + "</b> | " + now_gr
            + NL + "<b>$" + "{:,.0f}".format(price) + "</b> " + change_24h
            + " | Dom: " + dominance + " | OI: " + open_interest
            + NL + "L/S: " + ls_ratio
            + NL + NL + "📊 " + technical[:350]
            + NL + NL + "📰 F&G: " + fear_greed + " — " + sentiment[:250]
            + NL + NL + "⛓️ Funding: " + funding + " — " + onchain[:200])
    msg2 = ("🐂 " + bull[:200]
            + NL + NL + "🐻 " + bear[:200]
            + NL + NL + "✅ " + verdict[:600])
    send_telegram(msg1)
    send_telegram(msg2)
    log.infolog.info(f"{session} briefing sent!")


# ── Scheduler ─────────────────────────────────────────────────────────────────

def start_scheduler():
    """Schedule 3 daily briefings in Greece timezone."""

    def job_morning():
        now = datetime.now(GREECE_TZ)
        if now.hour == 8:
            threading.Thread(target=run_briefing, args=("🌅 ΠΡΩΙ",), daemon=True).start()

    def job_midday():
        now = datetime.now(GREECE_TZ)
        if now.hour == 13:
            threading.Thread(target=run_briefing, args=("☀️ ΜΕΣΗΜΕΡΙ",), daemon=True).start()

    def job_evening():
        now = datetime.now(GREECE_TZ)
        if now.hour == 20:
            threading.Thread(target=run_briefing, args=("🌙 ΒΡΑΔΥ",), daemon=True).start()

    # Check every minute
    schedule.every().hour.at(":00").do(job_morning)
    schedule.every().hour.at(":00").do(job_midday)
    schedule.every().hour.at(":00").do(job_evening)

    log.info("Analysis agent scheduler started. Briefings at 08:00, 13:00, 20:00 (Athens)")

    while True:
        schedule.run_pending()
        time.sleep(30)


def run_now(session: str = "🧪 TEST"):
    """Call this to test immediately without waiting for schedule."""
    threading.Thread(target=run_briefing, args=(session,), daemon=True).start()


if __name__ == "__main__":
    # If called with --test, run immediately
    import sys
    if "--test" in sys.argv:
        log.info("Running test briefing now...")
        run_briefing("🧪 TEST")
    else:
        start_scheduler()
