"""
AI Validator — News Agent (Φάση 3.3)
══════════════════════════════════════
Αναλύει το macro/sentiment context για ένα συγκεκριμένο trade signal.

Διαφορά από analysis_agent.py:
  - analysis_agent.py: "Ποια είναι η γενική κατάσταση της αγοράς;"
  - news_agent.py:     "Δεδομένου αυτού του LONG signal @ $64,100,
                        τι λένε τα νέα και το sentiment;"

Cache: Τα αποτελέσματα κρατούνται 15 λεπτά για να μην
καλούμε τα APIs σε κάθε trade signal.
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import requests
import anthropic

log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# Cache (15 λεπτά)
# ═══════════════════════════════════════════════════════════════

_cache: dict = {}
CACHE_TTL_SEC = 15 * 60  # 15 λεπτά


def _cache_get(key: str):
    entry = _cache.get(key)
    if entry and (time.time() - entry["ts"]) < CACHE_TTL_SEC:
        return entry["value"]
    return None


def _cache_set(key: str, value):
    _cache[key] = {"value": value, "ts": time.time()}


# ═══════════════════════════════════════════════════════════════
# Result dataclass
# ═══════════════════════════════════════════════════════════════

@dataclass
class NewsAnalysis:
    """
    Αποτέλεσμα του News Agent.
    
    score: -2 έως +2
      -2: Strongly bearish macro (major crash news, regulation ban κλπ)
      -1: Mildly bearish
       0: Neutral
      +1: Mildly bullish
      +2: Strongly bullish (ETF approval, institutional buying κλπ)
    
    verdict: 'SUPPORTS', 'NEUTRAL', 'CONTRADICTS'
      SUPPORTS:    Macro συμφωνεί με το trade direction
      NEUTRAL:     Macro δεν έχει σαφή γνώμη
      CONTRADICTS: Macro πάει αντίθετα από το trade
    """
    score: int = 0
    verdict: str = "NEUTRAL"        # SUPPORTS / NEUTRAL / CONTRADICTS
    fear_greed: str = "N/A"
    funding_rate: str = "N/A"
    summary: str = ""
    headlines_used: int = 0
    from_cache: bool = False
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "score":          self.score,
            "verdict":        self.verdict,
            "fear_greed":     self.fear_greed,
            "funding_rate":   self.funding_rate,
            "summary":        self.summary,
            "headlines_used": self.headlines_used,
            "from_cache":     self.from_cache,
        }


# ═══════════════════════════════════════════════════════════════
# Data fetchers (επαναχρησιμοποιημένα από analysis_agent.py)
# ═══════════════════════════════════════════════════════════════

def _fetch_headlines() -> list[str]:
    """Τραβάει BTC headlines από CryptoPanic (free, no key)."""
    cached = _cache_get("headlines")
    if cached is not None:
        log.debug("[NewsAgent] Headlines from cache")
        return cached

    headlines = []
    sources = [
        "https://feeds.feedburner.com/CoinDesk",
        "https://cointelegraph.com/rss",
        "https://cryptonews.com/news/feed/",
    ]
    try:
        import feedparser
        for url in sources:
            try:
                feed = feedparser.parse(url)
                for e in feed.entries[:3]:
                    headlines.append(e.title)
            except Exception:
                pass
    except ImportError:
        # feedparser δεν είναι installed — fallback στο CryptoPanic
        pass

    # Fallback: CryptoPanic (no key needed)
    if not headlines:
        try:
            r = requests.get(
                "https://cryptopanic.com/api/v1/posts/?auth_token=free&currencies=BTC&kind=news&limit=8",
                timeout=8,
            )
            posts = r.json().get("results", [])
            headlines = [p.get("title", "") for p in posts[:8]]
        except Exception as e:
            log.warning(f"[NewsAgent] CryptoPanic error: {e}")

    _cache_set("headlines", headlines)
    log.info(f"[NewsAgent] Fetched {len(headlines)} headlines")
    return headlines


def _fetch_fear_greed() -> str:
    """Fear & Greed Index — cache 15 λεπτά."""
    cached = _cache_get("fear_greed")
    if cached is not None:
        return cached
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=8)
        d = r.json()["data"][0]
        result = f"{d['value']} ({d['value_classification']})"
        _cache_set("fear_greed", result)
        return result
    except Exception as e:
        log.warning(f"[NewsAgent] Fear&Greed error: {e}")
        return "N/A"


def _fetch_funding_rate() -> str:
    """BTC Funding Rate από Bitget — cache 15 λεπτά."""
    cached = _cache_get("funding_rate")
    if cached is not None:
        return cached
    try:
        r = requests.get(
            "https://api.bitget.com/api/v2/mix/market/current-fund-rate"
            "?symbol=BTCUSDT&productType=USDT-FUTURES",
            timeout=8,
        )
        rate = float(r.json()["data"][0]["fundingRate"]) * 100
        result = f"{rate:+.4f}%"
        _cache_set("funding_rate", result)
        return result
    except Exception as e:
        log.warning(f"[NewsAgent] Funding rate error: {e}")
        return "N/A"


# ═══════════════════════════════════════════════════════════════
# Claude call
# ═══════════════════════════════════════════════════════════════

def _ask_claude_news(
    api_key: str,
    side: str,
    entry_price: float,
    headlines: list[str],
    fear_greed: str,
    funding_rate: str,
) -> dict:
    """
    Καλεί Claude Haiku για macro analysis.
    Επιστρέφει dict με score και summary.
    """
    if not api_key:
        return {"score": 0, "summary": "No API key", "verdict": "NEUTRAL"}

    # Cache key βασισμένο σε side + headlines count (όχι exact content για performance)
    cache_key = f"claude_news_{side}_{len(headlines)}"
    cached = _cache_get(cache_key)
    if cached is not None:
        log.debug("[NewsAgent] Claude response from cache")
        return {**cached, "from_cache": True}

    headlines_text = "\n".join(f"- {h}" for h in headlines[:8]) or "No headlines available"

    prompt = f"""You are analyzing whether macro conditions SUPPORT or CONTRADICT a specific crypto trade.

Trade: {side} BTC/USDT @ ${entry_price:,.0f}
Fear & Greed Index: {fear_greed}
BTC Funding Rate: {funding_rate}

Latest headlines:
{headlines_text}

Answer ONLY with valid JSON (no markdown, no explanation):
{{
  "score": <integer from -2 to 2>,
  "verdict": "<SUPPORTS|NEUTRAL|CONTRADICTS>",
  "summary": "<max 20 words explaining why>"
}}

score meaning:
  +2 = strongly supports the {side} (major bullish news for LONG, bearish for SHORT)
  +1 = mildly supports
   0 = neutral/unclear
  -1 = mildly contradicts
  -2 = strongly contradicts (do NOT take this trade)"""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=150,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        text = text.replace("```json", "").replace("```", "").strip()
        import json
        data = json.loads(text)
        result = {
            "score":   max(-2, min(2, int(data.get("score", 0)))),
            "verdict": data.get("verdict", "NEUTRAL"),
            "summary": data.get("summary", ""),
        }
        _cache_set(cache_key, result)
        return result
    except Exception as e:
        log.error(f"[NewsAgent] Claude error: {e}")
        return {"score": 0, "verdict": "NEUTRAL", "summary": f"Error: {str(e)[:50]}"}


# ═══════════════════════════════════════════════════════════════
# Main function
# ═══════════════════════════════════════════════════════════════

def analyze_news(
    side: str,
    entry_price: float,
    anthropic_api_key: str,
) -> NewsAnalysis:
    """
    Κύρια συνάρτηση News Agent.
    Καλείται από τον Coordinator.

    Args:
        side: 'LONG' ή 'SHORT'
        entry_price: Τιμή εισόδου
        anthropic_api_key: API key για Claude

    Returns:
        NewsAnalysis
    """
    log.info(f"[NewsAgent] Analyzing news for {side} @ ${entry_price:,.0f}")

    # 1. Fetch data (mostly cached)
    headlines    = _fetch_headlines()
    fear_greed   = _fetch_fear_greed()
    funding_rate = _fetch_funding_rate()

    # 2. Claude analysis
    claude_result = _ask_claude_news(
        api_key      = anthropic_api_key,
        side         = side,
        entry_price  = entry_price,
        headlines    = headlines,
        fear_greed   = fear_greed,
        funding_rate = funding_rate,
    )

    result = NewsAnalysis(
        score          = claude_result.get("score", 0),
        verdict        = claude_result.get("verdict", "NEUTRAL"),
        fear_greed     = fear_greed,
        funding_rate   = funding_rate,
        summary        = claude_result.get("summary", ""),
        headlines_used = len(headlines),
        from_cache     = claude_result.get("from_cache", False),
    )

    log.info(
        f"[NewsAgent] Score={result.score} Verdict={result.verdict} "
        f"F&G={result.fear_greed} Funding={result.funding_rate} | {result.summary}"
    )
    return result
