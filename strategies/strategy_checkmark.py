"""
strategy_checkmark.py — Check Mark Pattern Strategy
═══════════════════════════════════════════════════
Αυτόνομη στρατηγική (αντικαθιστά τη D).

Βασισμένη στη "Check Mark Pattern" στρατηγική:
  1. THE CHECK  → opening 15m candle + manipulation + blowoff
  2. THE PIVOT  → double/triple test της ζώνης (5m)
  3. THE MARK   → entry + SL + TP1/TP2

State machine:
  WAITING_CHECK → CHECK_FORMED → WAITING_PIVOT → PIVOT_CONFIRMED → ENTERED

Opening = NY session open (13:30 UTC) — εκεί μπαίνει η US ρευστότητα.

ΟΛΗ η λογική είναι εδώ. Το bot.py απλά καλεί:
  • on_tick(deps, state, price)  — κάθε tick/scheduler cycle
Τα dependencies (get_candles, place_order, finalize, telegram, ai_validate)
περνιούνται μέσω του deps dict — έτσι δεν χρειάζεται edit στο bot.py.
"""

import contextlib
import logging
from datetime import datetime, timezone

log = logging.getLogger(__name__)

# deps["lock"] = per-strategy RLock (live). Στα tests (χωρίς lock) → nullcontext.
_NULL = contextlib.nullcontext()

# ── Configuration ─────────────────────────────────────────────
CONFIG = {
    "opening_hour_utc":   13,     # NY open hour
    "opening_min_utc":    30,     # NY open minute (13:30)
    "atr_period":         14,     # Daily ATR period
    "atr_threshold_pct":  0.20,   # 20% του ATR = manipulation threshold
    "pivot_tests_min":    2,      # ελάχιστα tests για pivot confirmation
    "pivot_zone_pct":     0.003,  # 0.3% ζώνη γύρω από το blowoff level
    "risk_pct":           0.02,   # 2% risk per trade
    "use_tp1":            True,   # conservative target (day high/low)
    "use_tp2":            True,   # aggressive target (blowoff range)
    "session_window_min": 120,    # πόσα λεπτά μετά το open ψάχνουμε για setup
}

# State machine stages
STAGE_WAITING_CHECK   = "WAITING_CHECK"
STAGE_CHECK_FORMED    = "CHECK_FORMED"
STAGE_WAITING_PIVOT   = "WAITING_PIVOT"
STAGE_PIVOT_CONFIRMED = "PIVOT_CONFIRMED"
STAGE_ENTERED         = "ENTERED"
STAGE_DONE            = "DONE"   # ολοκληρώθηκε για σήμερα


# ═══════════════════════════════════════════════════════════════
# Helper: ATR calculation
# ═══════════════════════════════════════════════════════════════

def _calc_atr(candles, period=14):
    """Average True Range από daily candles."""
    if not candles or len(candles) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(candles)):
        h  = candles[i]["high"]
        l  = candles[i]["low"]
        pc = candles[i-1]["close"]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
    # Wilder smoothing
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return round(atr, 2)


# ═══════════════════════════════════════════════════════════════
# Helper: ημερήσιο state reset
# ═══════════════════════════════════════════════════════════════

def _today_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

def _in_session_window(cfg):
    """Είμαστε εντός του παραθύρου μετά το open;"""
    now = datetime.now(timezone.utc)
    open_minutes = cfg["opening_hour_utc"] * 60 + cfg["opening_min_utc"]
    now_minutes  = now.hour * 60 + now.minute
    diff = now_minutes - open_minutes
    return 0 <= diff <= cfg["session_window_min"]

def _past_opening(cfg):
    """Έχει περάσει το opening time σήμερα;"""
    now = datetime.now(timezone.utc)
    open_minutes = cfg["opening_hour_utc"] * 60 + cfg["opening_min_utc"]
    now_minutes  = now.hour * 60 + now.minute
    return now_minutes >= open_minutes


# ═══════════════════════════════════════════════════════════════
# STAGE 1: THE CHECK
# ═══════════════════════════════════════════════════════════════

def _detect_check(deps, cm, cfg):
    """
    Εντοπίζει το opening 15m κερί και ελέγχει:
      • Manipulation (εύρος > 20% ATR)
      • Blowoff (έσπασε prev day low/high & γύρισε)
    """
    get_candles = deps["get_candles"]

    # Daily candles για ATR
    candles_1d = get_candles("1D", 30)
    if not candles_1d or len(candles_1d) < cfg["atr_period"] + 1:
        return None

    atr = _calc_atr(candles_1d, cfg["atr_period"])
    if atr <= 0:
        return None

    threshold = atr * cfg["atr_threshold_pct"]

    # Το opening 15m κερί (το πρώτο μετά τις 13:30)
    candles_15m = get_candles("15m", 20)
    if not candles_15m or len(candles_15m) < 5:
        return None

    # Βρες το opening candle — το πρώτο 15m candle στο/μετά το opening time
    opening_candle = None
    for c in candles_15m:
        ts = datetime.fromtimestamp(c["ts"]/1000, tz=timezone.utc) if c.get("ts") else None
        if ts and ts.hour == cfg["opening_hour_utc"] and ts.minute >= cfg["opening_min_utc"]:
            opening_candle = c
            break

    # Fallback: το τελευταίο closed candle αν δεν βρέθηκε exact
    if not opening_candle:
        opening_candle = candles_15m[-2]  # last closed

    candle_range = opening_candle["high"] - opening_candle["low"]

    # ── Manipulation check ──
    is_manipulation = candle_range > threshold
    if not is_manipulation:
        return None

    # ── Blowoff check ──
    # Prev day high/low από daily candle
    prev_day = candles_1d[-2] if len(candles_1d) >= 2 else candles_1d[-1]
    prev_low  = prev_day["low"]
    prev_high = prev_day["high"]

    is_red   = opening_candle["close"] < opening_candle["open"]
    is_green = opening_candle["close"] > opening_candle["open"]

    # Blowoff bottom: έσπασε prev_low αλλά έκλεισε πάνω από αυτό → LONG setup
    blowoff_bottom = (
        opening_candle["low"] < prev_low and
        opening_candle["close"] > prev_low
    )
    # Blowoff top: έσπασε prev_high αλλά έκλεισε κάτω → SHORT setup
    blowoff_top = (
        opening_candle["high"] > prev_high and
        opening_candle["close"] < prev_high
    )

    if blowoff_bottom:
        return {
            "side":          "LONG",
            "blowoff_level": opening_candle["low"],
            "opening_high":  opening_candle["high"],
            "opening_low":   opening_candle["low"],
            "open_price":    opening_candle["open"],
            "atr":           atr,
            "candle_range":  round(candle_range, 2),
            "day_high":      prev_high,
            "day_low":       prev_low,
        }
    elif blowoff_top:
        return {
            "side":          "SHORT",
            "blowoff_level": opening_candle["high"],
            "opening_high":  opening_candle["high"],
            "opening_low":   opening_candle["low"],
            "open_price":    opening_candle["open"],
            "atr":           atr,
            "candle_range":  round(candle_range, 2),
            "day_high":      prev_high,
            "day_low":       prev_low,
        }

    return None


# ═══════════════════════════════════════════════════════════════
# STAGE 2: THE PIVOT
# ═══════════════════════════════════════════════════════════════

def _detect_pivot(deps, cm, cfg):
    """
    Ψάχνει για double/triple test της blowoff ζώνης στο 5m.
    Η τιμή πλησιάζει το blowoff level αλλά ΔΕΝ το σπάει, και αναπηδά.
    """
    get_candles = deps["get_candles"]
    candles_5m  = get_candles("5m", 30)
    if not candles_5m or len(candles_5m) < 5:
        return False, 0

    check = cm["check"]
    level = check["blowoff_level"]
    side  = check["side"]
    zone  = level * cfg["pivot_zone_pct"]

    # Μέτρα πόσες φορές η τιμή δοκίμασε τη ζώνη χωρίς να τη σπάσει
    tests = 0
    for c in candles_5m[-15:]:
        if side == "LONG":
            # Πλησίασε το low (εντός ζώνης) αλλά δεν το έσπασε
            touched = c["low"] <= level + zone and c["low"] >= level - zone
            held    = c["close"] > level
            if touched and held:
                tests += 1
        else:  # SHORT
            touched = c["high"] >= level - zone and c["high"] <= level + zone
            held    = c["close"] < level
            if touched and held:
                tests += 1

    confirmed = tests >= cfg["pivot_tests_min"]
    return confirmed, tests


# ═══════════════════════════════════════════════════════════════
# STAGE 3: THE MARK (Entry)
# ═══════════════════════════════════════════════════════════════

def _detect_entry(deps, cm, cfg):
    """
    Entry trigger:
      LONG:  πράσινο 5m κερί κλείνει πάνω από κόκκινο στη pivot ζώνη
      SHORT: κόκκινο 5m κερί κλείνει κάτω από πράσινο
    """
    get_candles = deps["get_candles"]
    candles_5m  = get_candles("5m", 10)
    if not candles_5m or len(candles_5m) < 3:
        return None

    check = cm["check"]
    side  = check["side"]

    last = candles_5m[-1]   # τελευταίο closed
    prev = candles_5m[-2]

    if side == "LONG":
        prev_red   = prev["close"] < prev["open"]
        last_green = last["close"] > last["open"]
        trigger    = last_green and last["close"] > prev["high"]
        if prev_red and trigger:
            return _build_entry(check, last["close"], cfg)
    else:  # SHORT
        prev_green = prev["close"] > prev["open"]
        last_red   = last["close"] < last["open"]
        trigger    = last_red and last["close"] < prev["low"]
        if prev_green and trigger:
            return _build_entry(check, last["close"], cfg)

    return None


def _build_entry(check, entry_price, cfg):
    """Φτιάχνει entry με SL και TP1/TP2."""
    side          = check["side"]
    blowoff_level = check["blowoff_level"]
    blowoff_range = abs(check["open_price"] - blowoff_level)

    if side == "LONG":
        sl  = round(blowoff_level * 0.999, 2)            # κάτω από blowoff low
        target_a = check["day_high"]                     # day high (liquidity return)
        target_b = round(entry_price + blowoff_range, 2) # blowoff range projection
        # TP1 = κοντινός, TP2 = μακρινός (sort ώστε entry < TP1 < TP2)
        tp1, tp2 = sorted([target_a, target_b])
    else:  # SHORT
        sl  = round(blowoff_level * 1.001, 2)            # πάνω από blowoff high
        target_a = check["day_low"]
        target_b = round(entry_price - blowoff_range, 2)
        # TP1 = κοντινός, TP2 = μακρινός (sort ώστε entry > TP1 > TP2)
        tp1, tp2 = sorted([target_a, target_b], reverse=True)

    # Primary TP = TP1 (κοντινός): εκεί κλείνει το 50% + BE
    primary_tp = tp1

    return {
        "side":  side,
        "entry": entry_price,
        "sl":    sl,
        "tp":    primary_tp,
        "tp1":   tp1,
        "tp2":   tp2,
        "blowoff_range": round(blowoff_range, 2),
    }


# ═══════════════════════════════════════════════════════════════
# MAIN: on_tick — καλείται από bot.py
# ═══════════════════════════════════════════════════════════════

def on_tick(deps, state, price):
    """
    Κύρια entry point. Καλείται κάθε scheduler cycle.

    deps: dict με {get_candles, place_order, finalize, send_telegram,
                   ai_validate, save_state, rt}
    state: το state dict της στρατηγικής (state_checkmark)
    price: τρέχουσα τιμή
    """
    cfg = CONFIG
    send_telegram = deps["send_telegram"]
    save_state    = deps["save_state"]
    lock          = deps.get("lock") or _NULL

    # ── Αν υπάρχει ανοιχτή θέση → manage ──
    if state.get("position"):
        _manage_position(deps, state, price)
        return

    # ── Ημερήσιο reset ──
    cm = state.get("checkmark")
    today = _today_str()
    if not cm or cm.get("date") != today:
        with lock:
            state["checkmark"] = {
                "date":  today,
                "stage": STAGE_WAITING_CHECK,
                "check": None,
            }
        cm = state["checkmark"]
        save_state()

    # ── Αν τελείωσε για σήμερα ──
    if cm["stage"] == STAGE_DONE:
        state["last_signal"] = "Done for today — next scan tomorrow 13:30 UTC"
        return
    if cm["stage"] == STAGE_ENTERED:
        state["last_signal"] = "Position entered ✓"
        return

    # ── Πρέπει να έχει περάσει το opening ──
    if not _past_opening(cfg):
        state["last_signal"] = "Waiting for NY open (13:30 UTC)"
        return

    # ── Εκτός session window → done ──
    if not _in_session_window(cfg) and cm["stage"] == STAGE_WAITING_CHECK:
        with lock:
            cm["stage"] = STAGE_DONE
        save_state()
        return

    # ═══ STATE MACHINE ═══

    # STAGE 1: WAITING_CHECK → ψάχνει manipulation + blowoff
    if cm["stage"] == STAGE_WAITING_CHECK:
        state["last_signal"] = "Scanning for Check (manipulation + blowoff)"
        check = _detect_check(deps, cm, cfg)
        if check:
            with lock:
                cm["check"] = check
                cm["stage"] = STAGE_WAITING_PIVOT
            save_state()
            send_telegram(
                f"🔍 <b>[CM] CHECK FORMED</b>\n"
                f"{check['side']} setup detected\n"
                f"Blowoff {'bottom' if check['side']=='LONG' else 'top'} @ "
                f"${check['blowoff_level']:,.2f}\n"
                f"ATR: ${check['atr']:,.2f} | Range: ${check['candle_range']:,.2f}\n"
                f"Waiting for pivot confirmation..."
            )
        return

    # STAGE 2: WAITING_PIVOT → double/triple test
    if cm["stage"] == STAGE_WAITING_PIVOT:
        state["last_signal"] = f"Check formed ({cm['check']['side']}) — waiting pivot test"
        confirmed, tests = _detect_pivot(deps, cm, cfg)
        if confirmed:
            with lock:
                cm["stage"]       = STAGE_PIVOT_CONFIRMED
                cm["pivot_tests"] = tests
            save_state()
            send_telegram(
                f"✅ <b>[CM] PIVOT CONFIRMED</b>\n"
                f"Zone tested {tests}x — buyers/sellers present\n"
                f"Waiting for entry trigger..."
            )
        return

    # STAGE 3: PIVOT_CONFIRMED → entry trigger
    if cm["stage"] == STAGE_PIVOT_CONFIRMED:
        state["last_signal"] = f"Pivot confirmed — waiting entry trigger ({cm['check']['side']})"
        entry = _detect_entry(deps, cm, cfg)
        if entry:
            _execute_entry(deps, state, entry, cm)
        return


# ═══════════════════════════════════════════════════════════════
# Entry execution
# ═══════════════════════════════════════════════════════════════

def _execute_entry(deps, state, entry, cm):
    """Εκτελεί το entry μέσω AI Validator + place_order."""
    cfg           = CONFIG
    place_order   = deps["place_order"]
    send_telegram = deps["send_telegram"]
    save_state    = deps["save_state"]
    ai_validate   = deps.get("ai_validate")
    lock          = deps.get("lock") or _NULL

    side  = entry["side"]
    price = entry["entry"]
    sl    = entry["sl"]
    tp    = entry["tp"]

    balance = state.get("balance", 10000)
    risk_amt = balance * cfg["risk_pct"]
    risk_pts = abs(price - sl)
    if risk_pts <= 0:
        return
    qty = round(risk_amt / risk_pts, 4)

    # ── AI Validator ──
    ai_action, ai_mult, ai_result = "GO", 1.0, None
    if ai_validate:
        try:
            ai_action, ai_mult, ai_result = ai_validate(
                strategy="CM", side=side,
                entry_price=price, stop_loss=sl, take_profit=tp,
                rsi_15m=deps["rt"].rsi_15m, rsi_1h=deps["rt"].rsi_1h,
                box=None, has_divergence=False,
                trades=state.get("trades", []), balance=balance,
                candles_15m=deps["get_candles"]("15m", 30),
            )
        except Exception as e:
            log.error(f"[CM] AI validate error: {e}")

    if ai_action == "SKIP":
        with lock:
            cm["stage"] = STAGE_DONE
        save_state()
        return
    if ai_action in ("REDUCE_SIZE", "DOUBLE_SIZE"):
        qty = round(qty * ai_mult, 4)

    # ── Place order ──
    oid = place_order(side, qty, price, sl, tp)
    if not oid:
        return

    import json as _json
    with lock:
        state["position"] = {
            "type":  side,
            "entry": price,
            "sl":    sl,
            "tp":    tp,
            "tp1":   entry["tp1"],
            "tp2":   entry["tp2"],
            "qty":   qty,
            "trailing_active": False,
            "phase1_done":     False,
            "ai_action":     ai_action,
            "ai_confidence": ai_result.confidence if ai_result else 0,
            "ai_reasoning":  _json.dumps(ai_result.reasoning) if ai_result else "",
            "ai_shadow":     getattr(ai_result, "source", "") == "ai_agents",
        }
        cm["stage"] = STAGE_ENTERED
    save_state()

    send_telegram(
        f"{'🟢' if side=='LONG' else '🔴'} <b>[CM] {side}</b>\n"
        f"Entry: ${price:,.2f}\n"
        f"SL: ${sl:,.2f} | TP1: ${entry['tp1']:,.2f} | TP2: ${entry['tp2']:,.2f}\n"
        f"Check Mark Pattern complete ✓"
    )

    # AI summary
    if deps.get("send_ai_summary") and ai_result:
        deps["send_ai_summary"]("CM", side, price, sl, tp, ai_action, ai_result,
                                getattr(ai_result, "source", "") == "ai_agents")


# ═══════════════════════════════════════════════════════════════
# Position management (SL/TP/Trailing)
# ═══════════════════════════════════════════════════════════════

def _manage_position(deps, state, price):
    """
    Διαχειρίζεται ανοιχτή θέση με 2-phase TP:
      Phase 1: TP1 hit → κλείνει 50% + SL → break-even (entry)
      Phase 2: TP2 hit → κλείνει υπόλοιπο 50% (WIN) | SL hit → κλείνει
    """
    finalize         = deps["finalize"]
    finalize_partial = deps["finalize_partial"]
    send_telegram    = deps["send_telegram"]
    save_state       = deps["save_state"]
    lock             = deps.get("lock") or _NULL

    pos = state["position"]
    if not pos:
        return

    is_long = pos["type"] == "LONG"
    entry   = pos["entry"]
    sl      = pos["sl"]
    tp1     = pos["tp1"]
    tp2     = pos["tp2"]

    # ── Phase 1: TP1 hit → close 50%, SL → break-even ──
    if not pos.get("phase1_done"):
        hit_tp1 = (is_long and price >= tp1) or (not is_long and price <= tp1)
        if hit_tp1:
            partial_qty = round(pos["qty"] * 0.5, 6)
            partial_pnl = round(((tp1 - entry) if is_long else (entry - tp1)) * partial_qty, 2)
            finalize_partial(tp1, partial_qty, partial_pnl, "TP1 (50%)")
            with lock:
                pos["sl"]          = entry              # break-even
                pos["qty"]         = round(pos["qty"] - partial_qty, 6)
                pos["phase1_done"] = True
            save_state()
            send_telegram(
                f"🎯 <b>[CM] TP1 HIT (50%)</b>\n"
                f"Close: ${tp1:,.2f} | PnL: +${partial_pnl:.2f}\n"
                f"SL → Break Even | Target TP2: ${tp2:,.2f}"
            )
            return

    # ── Phase 2: TP2 hit → close remainder | SL hit → close ──
    hit_tp2 = (is_long and price >= tp2) or (not is_long and price <= tp2)
    hit_sl  = (is_long and price <= sl)  or (not is_long and price >= sl)

    if hit_tp2:
        finalize(tp2, "WIN", "TP2")
        return
    if hit_sl:
        actual_pnl = ((sl - entry) if is_long else (entry - sl)) * pos["qty"]
        if abs(actual_pnl) < 1.0:
            finalize(sl, "BREAK EVEN", "BREAK EVEN")
        elif actual_pnl > 0:
            finalize(sl, "WIN", "STOP LOSS (profit)")
        else:
            finalize(sl, "LOSS", "STOP LOSS")
        return
