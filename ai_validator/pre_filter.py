"""
AI Validator — Pre-Filter (Φάση 3.2)
══════════════════════════════════════
Εκτελείται ΠΡΙΝ από κάθε Claude call.

Ρόλοι:
  1. Hard skip  — κανόνες που κόβουν trades χωρίς Claude
  2. Auto flags — flags που επηρεάζουν την τελική απόφαση
  3. Context    — συγκεντρώνει τα data που θα στείλουμε στο Claude

Επιστρέφει PreFilterResult με:
  - skip=True  → το bot ΔΕΝ καλεί Claude, ακυρώνει το trade
  - skip=False → το bot συνεχίζει στο Claude
  - auto_reduce=True → flag για Claude (counter-trend ή drawdown)
  - context_data → dict με τα data για τους agents
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# Config (inline για να μην κυκλικά εισάγουμε)
# Αν θες να αλλάξεις κατώφλια, άλλαξέ τα εδώ.
# ═══════════════════════════════════════════════════════════════

# R/R limits
MIN_RISK_REWARD = 1.5
MAX_RISK_REWARD = 5.0

# Circuit breaker
CONSECUTIVE_LOSSES_THRESHOLD = 3
CIRCUIT_BREAKER_HOURS        = 12

# Drawdown protection
DRAWDOWN_REDUCE_THRESHOLD = -10.0   # %
DRAWDOWN_LOOKBACK_DAYS    = 7

# Counter-trend R/R minimum
COUNTER_TREND_MIN_RR = 2.0

# Stale data (seconds)
STALE_DATA_THRESHOLD_SEC = 120


# ═══════════════════════════════════════════════════════════════
# Result dataclass
# ═══════════════════════════════════════════════════════════════

@dataclass
class PreFilterResult:
    """
    Αποτέλεσμα του pre-filter.
    
    Attributes:
        skip: Αν True, το trade ακυρώνεται αμέσως (χωρίς Claude)
        skip_reason: Γιατί ακυρώθηκε (για logs και Telegram)
        auto_reduce: Flag για Claude — "κάνε REDUCE_SIZE αν αμφιταλαντεύεσαι"
        auto_reduce_reason: Γιατί έχει το flag
        context_data: Όλα τα data για τους agents
    """
    skip: bool = False
    skip_reason: str = ""
    auto_reduce: bool = False
    auto_reduce_reason: str = ""
    context_data: dict = field(default_factory=dict)

    def to_short_string(self) -> str:
        if self.skip:
            return f"SKIP ({self.skip_reason})"
        if self.auto_reduce:
            return f"PASS [auto_reduce: {self.auto_reduce_reason}]"
        return "PASS"


# ═══════════════════════════════════════════════════════════════
# Helper functions
# ═══════════════════════════════════════════════════════════════

def _calc_rr(entry: float, sl: float, tp: float) -> float:
    """Υπολογισμός Risk/Reward ratio."""
    risk   = abs(entry - sl)
    reward = abs(tp - entry)
    if risk <= 0:
        return 0.0
    return round(reward / risk, 2)


def _is_weekend_low_liquidity() -> bool:
    """
    Crypto trades 24/7 — το weekend rule αφαιρέθηκε.
    Κρατιέται για μελλοντική χρήση αν προστεθεί forex/metals.
    """
    return False


def _calc_drawdown_pct(trades: list, days: int = 7) -> float:
    """
    Υπολογίζει το drawdown % των τελευταίων N ημερών.
    Επιστρέφει αρνητικό αριθμό (π.χ. -12.5 = 12.5% drawdown).
    """
    if not trades:
        return 0.0
    now = datetime.now(timezone.utc)
    cutoff_str = now.strftime("%Y-%m-%d")

    # Φιλτράρουμε trades από τις τελευταίες N ημέρες
    recent_pnl = 0.0
    for t in trades[-100:]:  # max τελευταία 100 trades για performance
        try:
            trade_time = t.get("time", "")
            if not trade_time:
                continue
            # format: "2026-05-18 13:53" ή "2026-05-18 13:53 UTC"
            trade_date = trade_time[:10]
            # Απλός έλεγχος: αν το trade είναι στις τελευταίες 7 ημέρες
            if trade_date >= cutoff_str[:7]:  # same month check (προσεγγιστικό)
                recent_pnl += t.get("pnl", 0.0)
        except Exception:
            continue

    return recent_pnl  # δεν το κάνουμε % γιατί χρειαζόμαστε το balance


def _count_consecutive_losses(trades: list) -> int:
    """Μετράει τις συνεχόμενες αποτυχίες από το τέλος της λίστας."""
    count = 0
    for t in reversed(trades):
        if t.get("result") == "LOSS":
            count += 1
        else:
            break
    return count


def _is_counter_trend(side: str, candles_4h: list) -> bool:
    """
    Ελέγχει αν το trade πάει αντίθετα από τον 4H trend.
    Χρησιμοποιεί απλό moving average comparison.
    """
    if not candles_4h or len(candles_4h) < 20:
        return False
    closes = [c["close"] for c in candles_4h[-20:]]
    ma_fast = sum(closes[-5:]) / 5    # 5-candle MA
    ma_slow = sum(closes[-20:]) / 20  # 20-candle MA
    trend_is_up   = ma_fast > ma_slow
    trend_is_down = ma_fast < ma_slow
    if side == "LONG"  and trend_is_down: return True
    if side == "SHORT" and trend_is_up:   return True
    return False


# ═══════════════════════════════════════════════════════════════
# Main Pre-Filter Function
# ═══════════════════════════════════════════════════════════════

def run_pre_filter(
    strategy: str,
    side: str,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    rsi_15m: float,
    rsi_1h: float,
    current_price: float,
    last_price_update: float,       # timestamp (time.time()) της τελευταίας ενημέρωσης τιμής
    trades: list,                   # λίστα trades από το state (π.χ. state_b["trades"])
    balance: float,
    initial_balance: float,
    has_divergence: bool,
    box: dict,                      # 1H box ή daily box (high, low, mid)
    candles_4h: list = None,        # για trend detection — μόνο αν διαθέσιμα
    extra_context: dict = None,     # οποιαδήποτε extra data από το bot
) -> PreFilterResult:
    """
    Κύρια συνάρτηση pre-filter. Καλείται πριν το Claude.
    
    Returns:
        PreFilterResult
    """
    import time as _time

    result = PreFilterResult()
    extra_context = extra_context or {}
    candles_4h    = candles_4h or []

    # ────────────────────────────────────────────────────────────
    # HARD SKIP RULES
    # ────────────────────────────────────────────────────────────

    # Rule 1 — Weekend low liquidity (disabled για crypto — 24/7 market)
    # Ενεργοποίησε αν προσθέσεις forex/metals assets
    if _is_weekend_low_liquidity():
        result.skip        = True
        result.skip_reason = "Weekend low liquidity"
        log.info(f"[PreFilter] {strategy} SKIP: {result.skip_reason}")
        return result

    # Rule 2 — Stale price data
    time_since_update = _time.time() - last_price_update
    if time_since_update > STALE_DATA_THRESHOLD_SEC:
        result.skip        = True
        result.skip_reason = f"Stale price data ({time_since_update:.0f}s old, max {STALE_DATA_THRESHOLD_SEC}s)"
        log.info(f"[PreFilter] {strategy} SKIP: {result.skip_reason}")
        return result

    # Rule 3 — Invalid price
    if entry_price <= 0 or stop_loss <= 0 or take_profit <= 0:
        result.skip        = True
        result.skip_reason = "Invalid price/SL/TP (zero or negative)"
        log.info(f"[PreFilter] {strategy} SKIP: {result.skip_reason}")
        return result

    # Rule 4 — Extreme R/R
    rr = _calc_rr(entry_price, stop_loss, take_profit)
    if rr < MIN_RISK_REWARD:
        result.skip        = True
        result.skip_reason = f"R/R too low: {rr:.2f} (min {MIN_RISK_REWARD})"
        log.info(f"[PreFilter] {strategy} SKIP: {result.skip_reason}")
        return result

    if rr > MAX_RISK_REWARD:
        result.skip        = True
        result.skip_reason = f"R/R too high: {rr:.2f} (max {MAX_RISK_REWARD}) — TP unrealistic"
        log.info(f"[PreFilter] {strategy} SKIP: {result.skip_reason}")
        return result

    # Rule 5 — Circuit breaker (3 consecutive losses)
    consec_losses = _count_consecutive_losses(trades)
    if consec_losses >= CONSECUTIVE_LOSSES_THRESHOLD:
        # Ελέγχουμε αν το τελευταίο loss ήταν πριν από 12 ώρες
        last_trade = trades[-1] if trades else {}
        last_trade_time_str = last_trade.get("time", "")
        hours_since_last = 99  # default: παλιό, επιτρέπεται
        try:
            if last_trade_time_str:
                lt = datetime.strptime(last_trade_time_str[:16], "%Y-%m-%d %H:%M")
                lt = lt.replace(tzinfo=timezone.utc)
                hours_since_last = (datetime.now(timezone.utc) - lt).total_seconds() / 3600
        except Exception:
            pass

        if hours_since_last < CIRCUIT_BREAKER_HOURS:
            result.skip        = True
            result.skip_reason = (
                f"Circuit breaker: {consec_losses} consecutive losses, "
                f"{hours_since_last:.1f}h ago (pause {CIRCUIT_BREAKER_HOURS}h)"
            )
            log.warning(f"[PreFilter] {strategy} CIRCUIT BREAKER: {result.skip_reason}")
            return result

    # ────────────────────────────────────────────────────────────
    # AUTO REDUCE FLAGS (δεν κόβουν trade, αλλά λένε στο Claude να μειώσει size)
    # ────────────────────────────────────────────────────────────

    # Flag 1 — Counter-trend με χαμηλό R/R
    if candles_4h and rr < COUNTER_TREND_MIN_RR:
        if _is_counter_trend(side, candles_4h):
            result.auto_reduce        = True
            result.auto_reduce_reason = (
                f"Counter-trend {side} with R/R={rr:.2f} (min {COUNTER_TREND_MIN_RR} for counter-trend)"
            )
            log.info(f"[PreFilter] {strategy} AUTO_REDUCE: {result.auto_reduce_reason}")

    # Flag 2 — Drawdown protection
    if initial_balance > 0:
        drawdown_pct = ((balance - initial_balance) / initial_balance) * 100
        if drawdown_pct <= DRAWDOWN_REDUCE_THRESHOLD:
            result.auto_reduce        = True
            result.auto_reduce_reason = (
                f"Drawdown protection: {drawdown_pct:.1f}% "
                f"(threshold {DRAWDOWN_REDUCE_THRESHOLD}%)"
            )
            log.info(f"[PreFilter] {strategy} AUTO_REDUCE: {result.auto_reduce_reason}")

    # ────────────────────────────────────────────────────────────
    # CONTEXT COLLECTION (για τους Claude agents)
    # ────────────────────────────────────────────────────────────

    # Υπολογισμός volume spike (απλοποιημένος)
    volume_info = "unknown"
    if candles_4h and len(candles_4h) >= 5:
        recent_vols  = [c.get("volume", 0) for c in candles_4h[-5:]]
        avg_vol      = sum(recent_vols[:-1]) / max(len(recent_vols) - 1, 1)
        last_vol     = recent_vols[-1]
        vol_ratio    = (last_vol / avg_vol) if avg_vol > 0 else 1.0
        volume_info  = f"{vol_ratio:.1f}x avg ({'spike' if vol_ratio > 1.5 else 'normal' if vol_ratio > 0.7 else 'low'})"

    result.context_data = {
        # Signal info
        "strategy":    strategy,
        "side":        side,
        "entry_price": entry_price,
        "stop_loss":   stop_loss,
        "take_profit": take_profit,
        "risk_reward": rr,

        # RSI
        "rsi_15m": rsi_15m,
        "rsi_1h":  rsi_1h,

        # Box levels
        "box_high": box.get("high", 0) if box else 0,
        "box_low":  box.get("low",  0) if box else 0,
        "box_mid":  box.get("mid",  0) if box else 0,

        # Market conditions
        "current_price":  current_price,
        "volume_info":    volume_info,
        "has_divergence": has_divergence,

        # Performance context
        "balance":          balance,
        "consecutive_losses": consec_losses,
        "auto_reduce":      result.auto_reduce,
        "auto_reduce_reason": result.auto_reduce_reason,

        # Extra data από το bot (webhook data, OB/FVG κλπ)
        **extra_context,
    }

    log.info(
        f"[PreFilter] {strategy} PASS | "
        f"{side} @ {entry_price:.2f} | R/R={rr:.2f} | "
        f"RSI_15m={rsi_15m} RSI_1h={rsi_1h} | "
        f"div={has_divergence} | reduce={result.auto_reduce}"
    )

    return result


# ═══════════════════════════════════════════════════════════════
# Self-test
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import time
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(name)s] %(message)s")

    print("\n" + "=" * 60)
    print("Pre-Filter — Self Test (Φάση 3.2)")
    print("=" * 60)

    FAKE_TRADES = [
        {"result": "WIN",  "pnl": 120.0, "time": "2026-05-20 10:00"},
        {"result": "LOSS", "pnl": -60.0, "time": "2026-05-22 14:00"},
        {"result": "LOSS", "pnl": -60.0, "time": "2026-05-23 09:00"},
    ]
    FAKE_BOX = {"high": 66000, "low": 64000, "mid": 65000}

    # Test 1: Κανονικό LONG — πρέπει να περάσει
    print("\n[Test 1] Κανονικό LONG — αναμένεται PASS")
    r = run_pre_filter(
        strategy="B", side="LONG",
        entry_price=64100, stop_loss=63800, take_profit=65000,
        rsi_15m=28.0, rsi_1h=42.0,
        current_price=64100,
        last_price_update=time.time(),
        trades=FAKE_TRADES, balance=18000, initial_balance=10000,
        has_divergence=False, box=FAKE_BOX,
    )
    print(f"  → {r.to_short_string()}")
    assert not r.skip, "Test 1 failed!"
    print("  ✅ OK")

    # Test 2: R/R πολύ χαμηλό — πρέπει να κοπεί
    print("\n[Test 2] R/R = 1.0 — αναμένεται SKIP")
    r = run_pre_filter(
        strategy="B", side="LONG",
        entry_price=64100, stop_loss=63800, take_profit=64400,  # R/R=1.0
        rsi_15m=28.0, rsi_1h=42.0,
        current_price=64100,
        last_price_update=time.time(),
        trades=FAKE_TRADES, balance=18000, initial_balance=10000,
        has_divergence=False, box=FAKE_BOX,
    )
    print(f"  → {r.to_short_string()}")
    assert r.skip and "R/R" in r.skip_reason, "Test 2 failed!"
    print("  ✅ OK")

    # Test 3: Stale data — πρέπει να κοπεί
    print("\n[Test 3] Stale price data (3 λεπτά παλιό) — αναμένεται SKIP")
    r = run_pre_filter(
        strategy="B", side="LONG",
        entry_price=64100, stop_loss=63800, take_profit=65000,
        rsi_15m=28.0, rsi_1h=42.0,
        current_price=64100,
        last_price_update=time.time() - 200,  # 200 δευτερόλεπτα παλιό
        trades=FAKE_TRADES, balance=18000, initial_balance=10000,
        has_divergence=False, box=FAKE_BOX,
    )
    print(f"  → {r.to_short_string()}")
    assert r.skip and "Stale" in r.skip_reason, "Test 3 failed!"
    print("  ✅ OK")

    # Test 4: Circuit breaker (3 losses στη σειρά, πρόσφατα)
    print("\n[Test 4] Circuit breaker (3 consecutive losses) — αναμένεται SKIP")
    three_losses = [
        {"result": "LOSS", "pnl": -60.0, "time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")},
        {"result": "LOSS", "pnl": -60.0, "time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")},
        {"result": "LOSS", "pnl": -60.0, "time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")},
    ]
    r = run_pre_filter(
        strategy="B", side="LONG",
        entry_price=64100, stop_loss=63800, take_profit=65000,
        rsi_15m=28.0, rsi_1h=42.0,
        current_price=64100,
        last_price_update=time.time(),
        trades=three_losses, balance=9880, initial_balance=10000,
        has_divergence=False, box=FAKE_BOX,
    )
    print(f"  → {r.to_short_string()}")
    assert r.skip and "Circuit" in r.skip_reason, "Test 4 failed!"
    print("  ✅ OK")

    # Test 5: Drawdown > 10% → auto_reduce
    print("\n[Test 5] Drawdown -15% — αναμένεται PASS με auto_reduce")
    r = run_pre_filter(
        strategy="B", side="LONG",
        entry_price=64100, stop_loss=63800, take_profit=65000,
        rsi_15m=28.0, rsi_1h=42.0,
        current_price=64100,
        last_price_update=time.time(),
        trades=FAKE_TRADES, balance=8500, initial_balance=10000,  # -15%
        has_divergence=False, box=FAKE_BOX,
    )
    print(f"  → {r.to_short_string()}")
    assert not r.skip and r.auto_reduce, "Test 5 failed!"
    print("  ✅ OK")

    print("\n" + "=" * 60)
    print("✅ Όλα τα tests πέρασαν!")
    print("=" * 60 + "\n")
