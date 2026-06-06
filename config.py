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

# ── LIVE TRADING — per-strategy allowlist (FAIL-CLOSED) ──────────────────────
# ΜΟΝΟ οι στρατηγικές που αναγράφονται ΡΗΤΑ εδώ μπορούν να στείλουν πραγματικό
# order. DEFAULT ΚΕΝΟ ⇒ ΟΛΕΣ PAPER. Για live Strategy C: LIVE_STRATEGIES="C".
# Είναι το master gate (operator-controlled στο Railway) — ένα bug στο UI δεν
# μπορεί να ενεργοποιήσει live αν δεν υπάρχει εδώ η στρατηγική.
LIVE_STRATEGIES = frozenset(
    s.strip().upper() for s in os.environ.get("LIVE_STRATEGIES", "").split(",") if s.strip()
)
# Ποιου χρήστη τα (κρυπτογραφημένα) dashboard keys χρηματοδοτούν το live trading.
# Single live account (default user_id=1).
LIVE_TRADING_USER_ID = int(os.environ.get("LIVE_TRADING_USER_ID", "1"))
# Auto-leverage cap: για μικρό λογαριασμό ($80) χρειάζεται μόχλευση ώστε να
# χωρά το exchange minimum (0.001 BTC). Επιλέγεται η ΕΛΑΧΙΣΤΗ που χρειάζεται,
# με ανώτατο αυτό το cap. Μεγαλύτερο = πιο κοντινό liquidation.
LIVE_LEVERAGE_CAP = int(os.environ.get("LIVE_LEVERAGE_CAP", "3"))
# Αν μια θέση πρέπει να στρογγυλοποιηθεί στο exchange minimum, μην την ανοίξεις
# αν ρισκάρει πάνω από αυτό το ποσοστό του balance (μετά το rounding).
LIVE_MAX_TRADE_RISK_PCT = float(os.environ.get("LIVE_MAX_TRADE_RISK_PCT", "0.10"))
# Margin buffer: χρησιμοποίησε το πολύ αυτό το ποσοστό του balance ως margin.
LIVE_MARGIN_BUFFER = float(os.environ.get("LIVE_MARGIN_BUFFER", "0.90"))
# Encryption key για τα at-rest secrets ζει στο env var SECRETS_ENCRYPTION_KEY
# (βλ. secrets_vault.py) — ΟΧΙ εδώ, ΟΧΙ στη βάση.

# ── TRADING SETTINGS ─────────────────────────────────────────────
SYMBOL         = "BTCUSDT"          # Bitget v2 symbol (no suffix needed)
TIMEFRAME_1H   = "1H"
TIMEFRAME_1D   = "1D"
RISK_PER_TRADE = 0.02   # 2% risk per trade (Strategies A / C / SMC / CM)
# Strategy B runs its own, much smaller risk. The Strategy-B refactor backtests
# showed 0.5% is the ONLY survivable risk at a concurrent cap of 3 (anything
# higher pushed max drawdown past ~25% / margin-call territory). Kept separate
# from the global RISK_PER_TRADE so tuning B never silently changes the others.
RISK_PER_TRADE_B = 0.005   # 0.5% base risk per B trade (×2 → 1% on divergence)
LEVERAGE = int(os.environ.get("LEVERAGE", 1))

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
