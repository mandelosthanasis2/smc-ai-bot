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
    """Pull live state from all 4 strategy endpoints."""
    data = {}
    for endpoint, key in [("/api", "A"), ("/api/b", "B"), ("/api/c", "C"), ("/api/d", "D")]:
        try:
            r = requests.get(BOT_URL + endpoint, timeout=8)
            data[key] = r.json()
        except Exception as e:
            log.warning(f"Cannot reach {endpoint}: {e}")
            data[key] = {}
    return data


def fetch_btc_news() -> str:
    """Fetch latest BTC headlines from CryptoPanic (free, no key needed)."""
    try:
        r = requests.get(
            "https://cryptopanic.com/api/v1/posts/?auth_token=free&currencies=BTC&kind=news&limit=8",
            timeout=8,
        )
        posts = r.json().get("results", [])
        headlines = [p.get("title", "") for p in posts[:8]]
        return "\n".join(f"- {h}" for h in headlines) if headlines else "No news available"
    except Exception as e:
        log.warning(f"News fetch error: {e}")
        return "News unavailable"


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

# ── The 5 Agents ──────────────────────────────────────────────────────────────

def agent_technical(data: dict, price: float, rsi_1h: float, rsi_15m: float) -> str:
    a = data.get("A", {})
    box_h = a.get("box_high", "?")
    box_l = a.get("box_low", "?")
    mid   = a.get("mid", "?")
    return ask_claude(
        "You are a crypto technical analyst. Be concise, max 4 lines.",
        f"""BTC current price: ${price:,.2f}
RSI 1H: {rsi_1h} | RSI 15m: {rsi_15m}
Daily Box: {box_l} - {box_h} | MID: {mid}

Give a brief technical outlook: trend, key levels, bias (bullish/bearish/neutral)."""
    )


def agent_sentiment(news: str, fear_greed: str) -> str:
    return ask_claude(
        "You are a crypto sentiment analyst. Be concise, max 4 lines.",
        f"""Fear & Greed Index: {fear_greed}

Latest BTC news:
{news}

Summarize market sentiment: bullish/bearish/neutral and why."""
    )


def agent_onchain(funding: str, price: float) -> str:
    return ask_claude(
        "You are a crypto on-chain analyst. Be concise, max 4 lines.",
        f"""BTC Price: ${price:,.2f}
Funding Rate: {funding}

Interpret the funding rate signal. Is the market overheated long or short? What does this mean for direction?"""
    )


def agent_debate(technical: str, sentiment: str, onchain: str) -> tuple[str, str]:
    """Bull and Bear agents debate based on the 3 reports."""
    bull = ask_claude(
        "You are a BULL trader. Make the strongest possible case to BUY BTC right now. Max 3 lines.",
        f"Technical report:\n{technical}\n\nSentiment report:\n{sentiment}\n\nOn-chain report:\n{onchain}"
    )
    bear = ask_claude(
        "You are a BEAR trader. Make the strongest possible case to SELL or AVOID BTC right now. Max 3 lines.",
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
        f"""You are a senior risk manager for a BTC futures trading bot.
Session: {session}
Give a final verdict and specific advice for each strategy (A=Daily Box, B=1H Box auto, C=1H Box webhook, D=webhook).
Format:
VERDICT: [BULLISH/BEARISH/NEUTRAL]
CONFIDENCE: [HIGH/MEDIUM/LOW]
Strategy A: [advice]
Strategy B: [advice]
Strategy C: [advice]
Strategy D: [advice]
WATCH OUT: [one key risk]
Max 10 lines total.""",
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

    # 1. Fetch all data
    bot_data   = fetch_bot_data()
    news       = fetch_btc_news()
    fear_greed = fetch_fear_greed()
    funding    = fetch_funding_rate()

    # Extract price & RSI from strategy A
    a_data  = bot_data.get("A", {})
    price   = float(a_data.get("price", 0))
    rsi_1h  = a_data.get("rsi_1h", "?")
    rsi_15m = a_data.get("rsi_15m", "?")

    # 2. Run 5 agents
    log.info("Running agents...")
    technical = agent_technical(bot_data, price, rsi_1h, rsi_15m)
    sentiment = agent_sentiment(news, fear_greed)
    onchain   = agent_onchain(funding, price)
    bull, bear = agent_debate(technical, sentiment, onchain)
    verdict   = agent_verdict(technical, sentiment, onchain, bull, bear, bot_data, session)

    # 3. Session emoji
    emoji = {"🌅 ΠΡΩΙ": "🌅", "☀️ ΜΕΣΗΜΕΡΙ": "☀️", "🌙 ΒΡΑΔΥ": "🌙"}.get(session, "📊")

    # 4. Format Telegram message
    now_gr = datetime.now(GREECE_TZ).strftime("%d/%m %H:%M")
    msg = f"""<b>{emoji} BTC BRIEFING — {session}</b>
<i>{now_gr} | BTC: ${price:,.2f}</i>

<b>📊 Τεχνική Ανάλυση:</b>
{technical}

<b>📰 Sentiment (Fear&amp;Greed: {fear_greed}):</b>
{sentiment}

<b>⛓️ On-Chain (Funding: {funding}):</b>
{onchain}

<b>🐂 Bull Case:</b>
{bull}

<b>🐻 Bear Case:</b>
{bear}

<b>✅ VERDICT:</b>
{verdict}"""

    send_telegram(msg)
    log.info(f"{session} briefing sent!")


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
