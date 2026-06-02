"""
strategy_b.py — Strategy B (1H Box + 15m RSI)  ·  v2 multi-position refactor
═══════════════════════════════════════════════════════════════════════════
Αυτόνομη στρατηγική (scheduled scan), με dependency injection (όπως A/CM/SMC).

ΦΙΛΟΣΟΦΙΑ: mean-reversion στα άκρα ενός 1H box, επιβεβαιωμένο από 15m RSI
  extreme. R/R σταθερό 2:1. v2 = η επικυρωμένη (backtested) εκδοχή του HANDOFF.

──────────────────────────────────────────────────────────────────────────
ΑΛΛΑΓΕΣ v2 (Strategy B refactor — Phase 1, logic only):
  • ΠΟΛΛΑΠΛΕΣ ΘΕΣΕΙΣ: state["position"] (ένα dict) → state["positions"]
    (λίστα, max 3 ταυτόχρονες, total ανεξαρτήτως κατεύθυνσης). Κάθε θέση είναι
    ανεξάρτητη — δικό της entry/SL/TP, κλείνει μόνη της.
  • CANDLE-CLOSE ENTRY: το setup ελέγχεται ΜΙΑ φορά ανά ΚΛΕΙΣΤΟ 15m κερί (όχι
    κάθε ~30s scan). Διορθώνει το over-trading που σκότωνε τη ζωντανή B. Το
    marker είναι το timestamp του τελευταίου ΚΛΕΙΣΤΟΥ 15m κεριού (candles[-2]),
    άρα δουλεύει είτε τα κεριά έρχονται από WS είτε από REST polling.
  • ΧΩΡΙΣ BREAK-EVEN: το BE@50%→entry έκοβε winners πριν δουλέψουν (το backtest
    έδειξε ότι το win rate κατέρρεε). Κρατάμε ΜΟΝΟ το 0.3% trailing.
  • RISK 0.5% (base) — έρχεται από deps["risk_per_trade"] (RISK_PER_TRADE_B).
    Σε divergence → ×2 = 1% (επικυρωμένο survivable, DD <23%).
  • DIVERGENCE: νέος, causal ±5-swing ορισμός (βλ. swing_divergence). ΟΧΙ
    look-ahead — ένα swing επιβεβαιώνεται μόνο αφού περάσουν `window` κεριά.

Entry model (αμετάβλητο geometry):
  • SHORT στο 1H high: price στο box["high"], RSI15m>70, box mid < price
  • LONG  στο 1H low:  price στο box["low"],  RSI15m<30, box mid > price
  • tp = box mid · sl_dist = tp_dist/2  →  R/R 2:1 (ΣΤΑΘΕΡΟ — μη το αλλάξεις)

Exit model (per position, ΧΩΡΙΣ break-even):
  • TP hit → ενεργοποίηση trailing stop 0.3% (floor = TP). Αν trailing_enabled
    is False → κλείνει στο TP ως WIN (TAKE PROFIT).
  • Trailing hit → κλείνει (WIN).
  • SL hit → κλείνει (LOSS) — το SL δεν μετακινείται πια, άρα stop = loss.

ΣΗΜΕΙΩΣΗ: RSI=70 / R:R=2.0 είναι off-limits ανά το HANDOFF.
"""

import contextlib
import json
import logging
import os
from datetime import datetime, timezone

log = logging.getLogger(__name__)

# deps["lock"] = per-strategy RLock (live). Στα tests (χωρίς lock) → nullcontext.
_NULL = contextlib.nullcontext()

# ── Configuration ─────────────────────────────────────────────
CONFIG = {
    "trailing_distance": 0.003,  # 0.3% trailing stop distance
    "max_positions":     3,      # max ταυτόχρονες θέσεις (total)
    "swing_window":      5,      # ±5 candles για causal swing detection
}

# Module-level race-condition guard (πρώην global _b_entering στο bot.py).
# Προστατεύει από διπλό entry όσο το AI Validator (αργό network call) τρέχει.
_entering = False


# ═══════════════════════════════════════════════════════════════
# Divergence — causal ±window swing detection (no look-ahead)
# ═══════════════════════════════════════════════════════════════

def _confirmed_swings(values, rsi_series, window, kind):
    """
    Επιστρέφει τη λίστα (value, rsi) στα confirmed swing points, με σειρά.

    Ένα swing στο index i είναι confirmed ΜΟΝΟ αν το values[i] είναι το
    ακρότατο σε ολόκληρο το παράθυρο [i-window, i+window] — δηλαδή υπάρχουν
    `window` κεριά ΚΑΙ πριν ΚΑΙ μετά. Επειδή το `values` περιέχει μόνο κλειστά
    κεριά μέχρι τώρα, τα τελευταία `window` κεριά ΔΕΝ μπορούν να σχηματίσουν
    swing → εγγενώς causal (no look-ahead).

    kind="high" → swing high (τοπικό μέγιστο)·  kind="low" → swing low.
    """
    out = []
    n = len(values)
    for i in range(window, n - window):
        seg = values[i - window:i + window + 1]
        v = values[i]
        if kind == "high":
            # strict τοπικό μέγιστο (>= όλο το παράθυρο, > άμεσοι γείτονες)
            if v >= max(seg) and v > values[i - 1] and v > values[i + 1]:
                out.append((v, rsi_series[i]))
        else:
            if v <= min(seg) and v < values[i - 1] and v < values[i + 1]:
                out.append((v, rsi_series[i]))
    return out


def swing_divergence(highs, lows, rsi_series, window=5):
    """
    Causal RSI divergence πάνω σε confirmed ±window swings.

    • Bullish (LONG):  η τιμή κάνει LOWER low από το προηγούμενο swing low,
                       αλλά το RSI κάνει HIGHER low.
    • Bearish (SHORT): η τιμή κάνει HIGHER high, αλλά το RSI κάνει LOWER high.

    Συγκρίνονται τα ΔΥΟ τελευταία confirmed swings (current vs prior).
    Τα highs/lows/rsi_series πρέπει να είναι aligned by candle index.

    Επιστρέφει (bull, bear).
    """
    n = min(len(highs), len(lows), len(rsi_series))
    if n < 2 * window + 2:
        return False, False
    highs = highs[:n]; lows = lows[:n]; rsi_series = rsi_series[:n]

    sh = _confirmed_swings(highs, rsi_series, window, "high")
    sl = _confirmed_swings(lows,  rsi_series, window, "low")

    bear = (len(sh) >= 2 and sh[-1][0] > sh[-2][0] and sh[-1][1] < sh[-2][1])
    bull = (len(sl) >= 2 and sl[-1][0] < sl[-2][0] and sl[-1][1] > sl[-2][1])

    if bear:
        log.info(f"[B] Bearish div: price {sh[-2][0]:.0f}->{sh[-1][0]:.0f} "
                 f"RSI {sh[-2][1]:.1f}->{sh[-1][1]:.1f}")
    if bull:
        log.info(f"[B] Bullish div: price {sl[-2][0]:.0f}->{sl[-1][0]:.0f} "
                 f"RSI {sl[-2][1]:.1f}->{sl[-1][1]:.1f}")
    return bull, bear


# ═══════════════════════════════════════════════════════════════
# Position helpers
# ═══════════════════════════════════════════════════════════════

def _ensure_positions(state):
    """
    Εξασφαλίζει ότι το state έχει λίστα state["positions"]. Migrates legacy
    single-position state (state["position"]) σε λίστα — ώστε φορτωμένο παλιό
    state (από DB/JSON, πριν το positions JSONB column) να μη χαθεί στο 1ο tick.
    """
    if not isinstance(state.get("positions"), list):
        legacy = state.get("position")
        state["positions"] = [legacy] if legacy else []
    elif not state["positions"] and state.get("position"):
        # κενή λίστα αλλά υπάρχει legacy single position (παλιό DB row) → migrate
        state["positions"] = [state["position"]]


def _sync_legacy_mirror(state):
    """
    Backward-compat mirror: το DB κρατά ακόμα το legacy single `position` column
    (δίπλα στο νέο `positions` JSONB array), ο header badge έχει fallback σε αυτό,
    και τυχόν παλιοί readers το περιμένουν. Καθρεφτίζουμε την ΠΡΩΤΗ ανοιχτή θέση.
    """
    state["position"] = state["positions"][0] if state["positions"] else None


# ═══════════════════════════════════════════════════════════════
# Position management — per-position 0.3% trailing exit (NO break-even)
# ═══════════════════════════════════════════════════════════════

def _manage_position(deps, state, pos, price):
    """
    Διαχειρίζεται ΜΙΑ θέση. Καλεί deps["finalize"](price, result, note, pos=pos)
    όταν η θέση κλείνει — το finalize αφαιρεί τη συγκεκριμένη θέση από τη λίστα.
    """
    finalize      = deps["finalize"]
    send_telegram = deps["send_telegram"]
    save_state    = deps["save_state"]
    lock          = deps.get("lock") or _NULL
    d             = CONFIG["trailing_distance"]

    entry   = pos["entry"]
    tp      = pos["tp"]
    is_long = pos["type"] == "LONG"

    # TP hit → ενεργοποίηση trailing stop 0.3% (floored at TP)
    hit_tp = (is_long and price >= tp) or (not is_long and price <= tp)
    if hit_tp and not pos.get("trailing_active"):
        if not state.get("trailing_enabled", True):
            finalize(tp, "WIN", "TAKE PROFIT", pos=pos)
            return
        init_tsl = round(price * (1 - d), 2) if is_long else round(price * (1 + d), 2)
        with lock:
            pos["trailing_active"] = True
            pos["trailing_sl"] = max(init_tsl, tp) if is_long else min(init_tsl, tp)  # floor = TP
            pos["trailing_peak"] = price
        log.info(f"[B] Trailing activated @ {price:.2f}, TSL={pos['trailing_sl']:.2f}")
        send_telegram(f"🚀 <b>[B] TRAILING ACTIVE</b>\nTP reached ${tp:,.2f} — now trailing 0.3%\nTrailing SL: ${pos['trailing_sl']:,.2f}")
        save_state()
        return

    # Trailing active → ενημέρωση TSL + έλεγχος εξόδου
    if pos.get("trailing_active"):
        peak = pos.get("trailing_peak", price)
        if is_long:
            if price > peak:
                new_tsl = round(price * (1 - d), 2)
                with lock:
                    pos["trailing_peak"] = price
                    pos["trailing_sl"] = max(new_tsl, tp)  # ποτέ κάτω από το TP
                save_state()
            if price <= pos["trailing_sl"]:
                finalize(price, "WIN", f"TRAILING STOP @ ${price:,.2f}", pos=pos)
        else:
            if price < peak:
                new_tsl = round(price * (1 + d), 2)
                with lock:
                    pos["trailing_peak"] = price
                    pos["trailing_sl"] = min(new_tsl, tp)  # ποτέ πάνω από το TP (SHORT)
                save_state()
            if price >= pos["trailing_sl"]:
                finalize(price, "WIN", f"TRAILING STOP @ ${price:,.2f}", pos=pos)
        return

    # Plain SL — χωρίς break-even το SL δεν μετακινείται, οπότε stop = LOSS
    hit_sl = (is_long and price <= pos["sl"]) or (not is_long and price >= pos["sl"])
    if hit_sl:
        finalize(pos["sl"], "LOSS", "STOP LOSS", pos=pos)


def check_position(deps, state, price):
    """
    Διαχειρίζεται ΟΛΕΣ τις ανοιχτές θέσεις (trailing exit, no break-even).
    Iterate πάνω σε ΑΝΤΙΓΡΑΦΟ της λίστας γιατί το finalize μπορεί να αφαιρέσει
    στοιχεία κατά τη διάρκεια.
    """
    _ensure_positions(state)

    if os.environ.get("FORCE_CLOSE_B", "").lower() == "true":
        finalize = deps["finalize"]
        for pos in list(state["positions"]):
            finalize(price, "WIN" if price > pos["entry"] else "LOSS", "FORCE CLOSE", pos=pos)
        _sync_legacy_mirror(state)
        return

    for pos in list(state["positions"]):
        _manage_position(deps, state, pos, price)
    _sync_legacy_mirror(state)


# ═══════════════════════════════════════════════════════════════
# Entry — opens one position (appended to state["positions"])
# ═══════════════════════════════════════════════════════════════

def _open(deps, state, side, price, sl, tp, qty, has_div, ai_action, _ai_result):
    """Build & append μια νέα θέση. Κοινό για SHORT/LONG."""
    place_order_paper = deps["place_order"]
    place_order_live  = deps["place_order_live"]
    send_telegram     = deps["send_telegram"]
    send_ai_summary   = deps["send_ai_summary"]
    save_state        = deps["save_state"]
    trading_mode      = deps.get("trading_mode", "PAPER")
    ai_shadow_master  = deps["ai_shadow_master"]
    lock              = deps.get("lock") or _NULL

    order_id = (place_order_paper(side, qty, price, sl, tp) if trading_mode == "PAPER"
                else place_order_live(side, qty, sl, tp))
    if not order_id:
        return False

    pos = {
        "type": side, "entry": price, "sl": sl, "tp": tp, "qty": qty,
        "time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "order_id": order_id, "has_divergence": has_div,
        "ai_action": ai_action, "ai_shadow": ai_shadow_master,
        "ai_confidence": (_ai_result.confidence if _ai_result else 0),
        "ai_reasoning": (json.dumps(_ai_result.reasoning) if _ai_result and _ai_result.reasoning else ""),
    }
    with lock:
        state["positions"].append(pos)
        state["last_signal"] = side
        state["last_signal_time"] = datetime.now(timezone.utc).strftime("%H:%M UTC")
    _sync_legacy_mirror(state)
    send_ai_summary("B", side, price, sl, tp, ai_action, _ai_result, ai_shadow_master)
    save_state()
    emoji = "🔴" if side == "SHORT" else "🟢"
    send_telegram(f"{emoji} <b>[B] {side}</b>\nEntry:${price:,.2f} TP:${tp:,.2f} SL:${sl:,.2f}\n"
                  f"R/R 2:1 {'🔥DIV' if has_div else ''} | {len(state['positions'])}/{CONFIG['max_positions']} open")
    return True


# ═══════════════════════════════════════════════════════════════
# MAIN: on_tick — καλείται κάθε scheduler cycle από το bot.py
# ═══════════════════════════════════════════════════════════════

def on_tick(deps, state, price):
    """
    Διαχειρίζεται τις ανοιχτές θέσεις (κάθε tick) και ανοίγει νέες ΜΟΝΟ στο
    κλείσιμο 15m κεριού (candle-close gate), μέχρι το cap των 3.

    deps: {
        rt, get_candles, build_1h_box, detect_divergence, calc_qty, calc_rsi,
        place_order, place_order_live, send_telegram, ai_validate,
        finalize, save_state, send_ai_summary,
        trading_mode, risk_per_trade, ai_shadow_master, lock
    }
    """
    global _entering

    rt                = deps["rt"]
    get_candles       = deps["get_candles"]
    build_1h_box      = deps["build_1h_box"]
    detect_divergence = deps["detect_divergence"]
    calc_qty          = deps["calc_qty"]
    calc_rsi          = deps.get("calc_rsi")   # RSI επί ΚΛΕΙΣΤΩΝ κεριών (entry)
    ai_validate       = deps["ai_validate"]
    risk_per_trade    = deps["risk_per_trade"]

    rsi_15m = rt.rsi_15m                       # live RSI (forming candle) — display
    state["current_rsi"]   = rsi_15m
    state["current_price"] = price  # needed for dashboard unrealised PnL

    if price <= 0 or not rt.initialized:
        state["last_signal"] = "Initializing..."
        return

    _ensure_positions(state)

    # ── Exits: τρέχουν ΚΑΘΕ tick (trailing stops χρειάζονται live price) ──
    if state["positions"]:
        check_position(deps, state, price)

    # ── 1H box (κάθε tick, για το dashboard) ──
    candles_1h = get_candles("1H", 50)
    if not candles_1h:
        state["last_signal"] = "No candle data"
        return
    box = build_1h_box(candles_1h)
    if not box:
        return
    state["box"] = box

    open_n = len(state["positions"])

    # ── Candle-close gate: αξιολόγηση entry ΜΙΑ φορά ανά κλειστό 15m κερί ──
    candles_15m = get_candles("15m", 200)
    closed_ts = candles_15m[-2]["time"] if candles_15m and len(candles_15m) >= 2 else None
    new_candle = closed_ts is not None and closed_ts != state.get("last_entry_candle_ts")

    if not new_candle:
        div_txt = "Div!" if state.get("last_divergence") else "No div"
        state["last_signal"] = (f"HOLDING {open_n}/{CONFIG['max_positions']} | RSI={rsi_15m} | "
                                f"[{box['low']:.0f}-{box['high']:.0f}] | {div_txt}")
        return

    # Νέο κλειστό κερί → καταγραφή ώστε να μην ξανα-αξιολογηθεί το ίδιο κερί
    state["last_entry_candle_ts"] = closed_ts

    # ── Entry RSI επί ΚΛΕΙΣΤΩΝ κεριών (όχι το live rt.rsi_15m που έχει το forming
    # candle με live price). Εξαλείφει το drift backtest-vs-live: το backtest
    # κρίνει στο close, εδώ κρίνουμε κι εμείς στο close. candles_15m[-1] είναι το
    # forming κερί → το αφαιρούμε. ──
    closed_15m = candles_15m[:-1] if candles_15m else []
    closed_closes = [c["close"] for c in closed_15m]
    if calc_rsi and len(closed_closes) >= 15:
        rsi_entry = calc_rsi(closed_closes)
    else:
        rsi_entry = rsi_15m   # fallback (λίγα κεριά ή χωρίς calc_rsi)

    # Divergence (causal ±5 swing) — μόνο στο close, πάνω σε ΚΛΕΙΣΤΑ κεριά
    if closed_15m:
        highs  = [c["high"] for c in closed_15m]
        lows   = [c["low"]  for c in closed_15m]
        bull_div, bear_div = detect_divergence(closed_closes, highs, lows)
    else:
        bull_div = bear_div = False
    state["last_divergence"] = bull_div or bear_div

    # Cap: max 3 ταυτόχρονες θέσεις (total)
    if open_n >= CONFIG["max_positions"]:
        state["last_signal"] = f"CAP {open_n}/{CONFIG['max_positions']} | RSI={rsi_15m}"
        return

    balance = state["balance"]
    log.info(f"[B] Price={price:.2f} RSI_close={rsi_entry} (live={rsi_15m}) "
             f"1H=[{box['low']:.0f}-{box['high']:.0f}] open={open_n}/{CONFIG['max_positions']}")

    if _entering:
        return  # race-condition guard (αργό AI call)

    # ── SHORT at 1H High ──
    at_high = (price >= box["high"] * 0.995) and (price <= box["high"] * 1.015)
    if at_high and rsi_entry > 70 and box["mid"] < price:
        tp_dist  = price - box["mid"]
        sl_dist  = tp_dist / 2
        tp       = box["mid"]; sl = round(price + sl_dist, 2)
        risk_pct = risk_per_trade * 2 if bear_div else risk_per_trade
        qty      = calc_qty(balance, risk_pct, price, sl)
        _entering = True
        try:
            ai_action, ai_mult, _ai_result = ai_validate(
                strategy="B", side="SHORT",
                entry_price=price, stop_loss=sl, take_profit=tp,
                rsi_15m=rsi_15m, rsi_1h=rt.rsi_1h,
                box=box, has_divergence=bear_div,
                trades=state.get("trades", []), balance=balance,
                candles_15m=candles_15m or get_candles("15m", 30),
            )
            if ai_action == "SKIP":
                return
            if ai_action in ("REDUCE_SIZE", "DOUBLE_SIZE"):
                qty = round(qty * ai_mult, 4)
            _open(deps, state, "SHORT", price, sl, tp, qty, bear_div, ai_action, _ai_result)
        finally:
            _entering = False
        return

    # ── LONG at 1H Low ──
    at_low = (price <= box["low"] * 1.005) and (price >= box["low"] * 0.985)
    if at_low and rsi_entry < 30 and box["mid"] > price:
        tp_dist  = box["mid"] - price
        sl_dist  = tp_dist / 2
        tp       = box["mid"]; sl = round(price - sl_dist, 2)
        risk_pct = risk_per_trade * 2 if bull_div else risk_per_trade
        qty      = calc_qty(balance, risk_pct, price, sl)
        _entering = True
        try:
            ai_action, ai_mult, _ai_result = ai_validate(
                strategy="B", side="LONG",
                entry_price=price, stop_loss=sl, take_profit=tp,
                rsi_15m=rsi_15m, rsi_1h=rt.rsi_1h,
                box=box, has_divergence=bull_div,
                trades=state.get("trades", []), balance=balance,
                candles_15m=candles_15m or get_candles("15m", 30),
            )
            if ai_action == "SKIP":
                return
            if ai_action in ("REDUCE_SIZE", "DOUBLE_SIZE"):
                qty = round(qty * ai_mult, 4)
            _open(deps, state, "LONG", price, sl, tp, qty, bull_div, ai_action, _ai_result)
        finally:
            _entering = False
        return

    div_txt = "Div!" if (bull_div or bear_div) else "No div"
    state["last_signal"] = (f"WAIT | RSI={rsi_15m} | [{box['low']:.0f}-{box['high']:.0f}] | "
                            f"{div_txt} | {open_n}/{CONFIG['max_positions']} open")
    log.info(f"[B] {state['last_signal']}")
