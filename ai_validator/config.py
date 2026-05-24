"""
AI Validator — Configuration
═══════════════════════════
Όλες οι ρυθμίσεις του AI Validator σε ένα μέρος.

Αλλάζοντας τιμές εδώ, αλλάζει η συμπεριφορά του validator
χωρίς να αγγίξεις logic.
"""

import os

# ═══════════════════════════════════════════════════════════════
# Anthropic API
# ═══════════════════════════════════════════════════════════════
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# Models — Claude 4 family
TECHNICAL_AGENT_MODEL = "claude-haiku-4-5-20251001"      # Φθηνό, γρήγορο
NEWS_AGENT_MODEL = "claude-haiku-4-5-20251001"           # Φθηνό
COORDINATOR_MODEL = "claude-haiku-4-5-20251001"          # Τελική απόφαση

# Max tokens ανά agent — όσο πιο μικρά, τόσο πιο φθηνά
TECHNICAL_MAX_TOKENS = 800
NEWS_MAX_TOKENS = 500
COORDINATOR_MAX_TOKENS = 600


# ═══════════════════════════════════════════════════════════════
# Pre-Filter Rules (Φάση 3.2)
# ═══════════════════════════════════════════════════════════════

# Hard skip windows (UTC)
LOW_LIQUIDITY_HOURS = {
    # Tuple (day_of_week, hour_start, hour_end) — 0=Monday, 6=Sunday
    # Παρασκευή 22:00 UTC → Κυριακή 22:00 UTC
    "weekend": [
        (4, 22, 24),   # Friday 22:00-24:00
        (5, 0, 24),    # Saturday all day
        (6, 0, 22),    # Sunday 00:00-22:00
    ]
}

# Stale data threshold (seconds)
STALE_DATA_THRESHOLD_SEC = 120  # 2 λεπτά

# R/R limits
MIN_RISK_REWARD = 1.5
MAX_RISK_REWARD = 5.0

# Circuit breaker
CONSECUTIVE_LOSSES_THRESHOLD = 3
CIRCUIT_BREAKER_HOURS = 12

# Drawdown protection
DRAWDOWN_REDUCE_THRESHOLD = -10.0  # %
DRAWDOWN_LOOKBACK_DAYS = 7

# Counter-trend rules
COUNTER_TREND_MIN_RR = 2.0


# ═══════════════════════════════════════════════════════════════
# Decision Thresholds (Φάση 3.4)
# ═══════════════════════════════════════════════════════════════

# Confidence thresholds για κάθε απόφαση
CONFIDENCE_DOUBLE_SIZE = 0.85
CONFIDENCE_GO = 0.60
CONFIDENCE_REDUCE_SIZE = 0.40
# < 0.40 → SKIP

# Size multipliers
SIZE_MULTIPLIER = {
    "GO": 1.0,
    "REDUCE_SIZE": 0.5,
    "DOUBLE_SIZE": 2.0,
    "SKIP": 0.0,
}


# ═══════════════════════════════════════════════════════════════
# Caching (Φάση 3.3)
# ═══════════════════════════════════════════════════════════════

# Πόση ώρα να κρατάμε cached το macro context (News Agent)
NEWS_CACHE_DURATION_MIN = 15


# ═══════════════════════════════════════════════════════════════
# Fallback behavior (αν Claude API πέσει)
# ═══════════════════════════════════════════════════════════════

# Strategies με proven edge — εκτελούν κανονικά αν AI πέσει
PROVEN_STRATEGIES = {
    "B": {"min_trades": 50, "min_win_rate": 0.55}
    # Όταν επιβεβαιωθούν, θα προστεθούν A, C, D
}

# Retry settings
AI_RETRY_COUNT = 1
AI_RETRY_DELAY_SEC = 3
AI_TIMEOUT_SEC = 30


# ═══════════════════════════════════════════════════════════════
# Knowledge Base (Φάση 3.3)
# ═══════════════════════════════════════════════════════════════

# Path στο ChromaDB. Σε Railway θα είναι /app/chroma_db
CHROMA_DB_PATH = os.environ.get("CHROMA_DB_PATH", "./chroma_db")

# Πόσα top results να επιστρέφει το knowledge search
KNOWLEDGE_TOP_K = 3


# ═══════════════════════════════════════════════════════════════
# Logging
# ═══════════════════════════════════════════════════════════════

LOG_AI_DECISIONS = True            # Logging όλων των αποφάσεων
LOG_PROMPT_TO_CLAUDE = False       # Debug: αποθήκευση full prompt
