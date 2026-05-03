# ═══════════════════════════════════════════════════════════════
# config.py — SMC AI Trading Bot
# Exchange: Bitget | Hosting: Railway.app
# ═══════════════════════════════════════════════════════════════
import os

# ── API KEYS (set as Environment Variables on Railway) ──────────
# Never hardcode keys here — use Railway's Variables panel
BITGET_API_KEY     = os.environ.get("BITGET_API_KEY",     "")
BITGET_API_SECRET  = os.environ.get("BITGET_API_SECRET",  "")
BITGET_PASSPHRASE  = os.environ.get("BITGET_PASSPHRASE",  "")  # Bitget needs passphrase too
ANTHROPIC_API_KEY  = os.environ.get("ANTHROPIC_API_KEY",  "")

# ── TRADING MODE ─────────────────────────────────────────────────
# PAPER = simulated trades (no real money), LIVE = real trades
TRADING_MODE       = os.environ.get("TRADING_MODE", "PAPER")   # "PAPER" or "LIVE"

# ── TRADING SETTINGS ─────────────────────────────────────────────
SYMBOL         = "BTCUSDT"          # Bitget v2 symbol (no suffix needed)
TIMEFRAME_1H   = "1H"
TIMEFRAME_1D   = "1D"
RISK_PER_TRADE = 0.02   # 2% risk per trade
LEVERAGE       = 1      # Leverage (1x default — change here to increase: 1, 2, 3, 5, 10)

# ── SMC STRATEGY RULES ───────────────────────────────────────────
SMC_RULES = {
    "pdbox_short_rsi_threshold": 70,   # SHORT if RSI > 70 at PDH
    "pdbox_long_rsi_threshold":  30,   # LONG if RSI < 30 at PDL
    "pdbox_proximity_pct":       0.012, # 1.2% proximity to PDH/PDL (wider)
    "risk_reward_ratio":         2.0,
    "tp_at_midbox":              True,
    "require_liquidity_sweep":   False, # Not required — RSI extreme is enough
    "require_bos":               False, # Not required — price at level is enough
    "use_ai_news_filter":        True,
    "min_news_score":            0,
    "trade_sessions":            ["london", "new_york"],
    "london_open":  8,
    "london_close": 16,
    "ny_open":      13,
    "ny_close":     21,
}

# ── NEWS SOURCES ─────────────────────────────────────────────────
NEWS_SOURCES = [
    "https://feeds.feedburner.com/CoinDesk",
    "https://cointelegraph.com/rss",
    "https://cryptonews.com/news/feed/",
    "https://www.newsbtc.com/feed/",
    "https://rss.app/feeds/twitterUser/elonmusk.xml",   # Social
]

# ── DASHBOARD ────────────────────────────────────────────────────
PORT = int(os.environ.get("PORT", 5000))   # Railway sets PORT automatically
