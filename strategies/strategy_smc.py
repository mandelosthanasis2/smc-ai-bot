"""
strategy_smc.py — SMC Strategy (OB + FVG + CHoCH)
═══════════════════════════════════════════════════
Αυτόνομη στρατηγική (webhook-driven), βασισμένη στο Pine script
"SMC Strategy D — OB + FVG + CHoCH".

ΦΙΛΟΣΟΦΙΑ: "thin" webhook strategy.
  Το TradingView Pine υπολογίζει ΟΛΑ (signal/price/tp1/tp2/sl/confluence)
  και τα στέλνει μέσω alert JSON. Το bot ΔΕΝ ξαναϋπολογίζει entry/exit —
  απλά τα εκτελεί (αφού περάσουν από AI Validator) και διαχειρίζεται τη θέση.

Pine alert JSON shape:
  {"signal":"LONG","price":"...","tp1":"...","tp2":"...","sl":"...","confluence":"strong"}

Exit model: 2-phase TP (ίδιο με την παλιά D)
  • TP1 hit → κλείνει 50% + μετακινεί SL → entry (break-even)
  • TP2 hit → κλείνει το υπόλοιπο (WIN)
  • SL hit → κλείνει (LOSS / BE / WIN ανάλογα με τη θέση του SL)
  • strong confluence → διπλάσιο risk

ΟΛΗ η λογική είναι εδώ. Το bot.py καλεί:
  • process_webhook(deps, state, signal) — όταν φτάνει webhook signal
  • check_position(deps, state, price)   — κάθε scheduler cycle (αν υπάρχει θέση)
Τα dependencies περνιούνται μέσω του deps dict.
"""

import json as _json
import logging
import time as _time
from datetime import datetime, timezone

log = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────
CONFIG = {
    "risk_pct":              0.02,   # 2% base risk per trade
    "confluence_multiplier": 2.0,    # strong confluence → ×2 risk
    "dedup_seconds":         30,     # αγνόησε διπλό signal εντός 30s
    "tp1_close_pct":         0.5,    # ποσοστό θέσης που κλείνει στο TP1
    # Fallback SL/TP αν το Pine δεν στείλει τιμές (% από entry)
    "fallback_sl_pct":       0.015,  # 1.5%
    "fallback_tp1_rr":       2.0,    # 2:1
    "fallback_tp2_rr":       3.0,    # 3:1
}

# Module-level dedup guard (όπως τα _c/_d_last_signal_time στο main.py)
_last_signal_time = 0.0


# ═══════════════════════════════════════════════════════════════
# Helper: SL/TP parsing από το webhook payload (με fallback)
# ═══════════════════════════════════════════════════════════════

def _parse_levels(data, side, price, cfg):
    """
    Διαβάζει sl/tp1/tp2 από το Pine payload.
    Αν λείπουν/είναι μηδέν → fallback σε R/R-based υπολογισμό.
    """
    is_long = side == "LONG"
    try:
        sl  = float(data.get("sl", 0))  or (price * (1 - cfg["fallback_sl_pct"]) if is_long
                                            else price * (1 + cfg["fallback_sl_pct"]))
        risk = abs(price - sl)
        tp1 = float(data.get("tp1", 0)) or (price + risk * cfg["fallback_tp1_rr"] if is_long
                                            else price - risk * cfg["fallback_tp1_rr"])
        tp2 = float(data.get("tp2", 0)) or (price + risk * cfg["fallback_tp2_rr"] if is_long
                                            else price - risk * cfg["fallback_tp2_rr"])
    except (ValueError, TypeError):
        sl  = price * (1 - cfg["fallback_sl_pct"]) if is_long else price * (1 + cfg["fallback_sl_pct"])
        risk = abs(price - sl)
        tp1 = price + risk * cfg["fallback_tp1_rr"] if is_long else price - risk * cfg["fallback_tp1_rr"]
        tp2 = price + risk * cfg["fallback_tp2_rr"] if is_long else price - risk * cfg["fallback_tp2_rr"]

    return round(sl, 2), round(tp1, 2), round(tp2, 2)


# ═══════════════════════════════════════════════════════════════
# MAIN: process_webhook — καλείται από το webhook route στο main.py
# ═══════════════════════════════════════════════════════════════

def process_webhook(deps, state, signal, price=None, data=None):
    """
    Επεξεργάζεται ένα webhook signal και ανοίγει θέση (αν περάσει το AI Validator).

    deps: dict με {
        get_price, calc_qty, place_order, send_telegram, ai_validate,
        save_state, send_ai_summary, trading_mode, rt
    }
    state:  το state dict της στρατηγικής (state_smc)
    signal: "LONG" ή "SHORT"
    price:  τιμή από το payload (ή None → τρέχουσα τιμή)
    data:   το πλήρες webhook JSON (για sl/tp1/tp2/confluence)
    """
    global _last_signal_time
    cfg = CONFIG
    if data is None:
        data = {}

    get_price     = deps["get_price"]
    calc_qty      = deps["calc_qty"]
    place_order   = deps["place_order"]
    send_telegram = deps["send_telegram"]
    save_state    = deps["save_state"]
    ai_validate   = deps.get("ai_validate")
    trading_mode  = deps.get("trading_mode", "PAPER")
    rt            = deps.get("rt")

    p = price or get_price()

    # ── Guards ──
    if p <= 0 or state.get("position"):
        return

    now = _time.time()
    if now - _last_signal_time < cfg["dedup_seconds"]:
        log.info(f"[SMC] Duplicate signal ignored (last={now - _last_signal_time:.1f}s ago)")
        return
    _last_signal_time = now

    # ── Parse levels ──
    sl, tp1, tp2 = _parse_levels(data, signal, p, cfg)
    confluence_strong = data.get("confluence", "normal") == "strong"

    # ── Position sizing (×2 αν strong confluence) ──
    base_risk = cfg["risk_pct"] * (cfg["confluence_multiplier"] if confluence_strong else 1.0)
    qty = calc_qty(state.get("balance", 10000), base_risk, p, sl)
    if qty <= 0:
        return

    # ── AI Validator ──
    ai_action, ai_mult, ai_result = "GO", 1.0, None
    if ai_validate:
        try:
            ai_action, ai_mult, ai_result = ai_validate(
                strategy="SMC", side=signal,
                entry_price=p, stop_loss=sl, take_profit=tp1,
                rsi_15m=rt.rsi_15m if rt else 50,
                rsi_1h=rt.rsi_1h if rt else 50,
                box=None, has_divergence=confluence_strong,
                trades=state.get("trades", []),
                balance=state.get("balance", 10000),
            )
        except Exception as e:
            log.error(f"[SMC] AI validate error: {e}")

    if ai_action == "SKIP":
        log.info("[SMC] AI Validator → SKIP")
        return
    if ai_action in ("REDUCE_SIZE", "DOUBLE_SIZE"):
        qty = round(qty * ai_mult, 4)

    # ── Place order ──
    oid = place_order(signal, qty, p, sl, tp1)
    if not oid:
        return

    ai_shadow = getattr(ai_result, "source", "") == "ai_agents"
    state["position"] = {
        "type":          signal,
        "entry":         p,
        "sl":            sl,
        "tp1":           tp1,
        "tp2":           tp2,
        "qty":           qty,
        "time":          datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "order_id":      oid,
        "has_confluence": confluence_strong,
        "phase1_done":   False,
        "ai_action":     ai_action,
        "ai_confidence": ai_result.confidence if ai_result else 0,
        "ai_reasoning":  _json.dumps(ai_result.reasoning) if ai_result and ai_result.reasoning else "",
        "ai_shadow":     ai_shadow,
    }
    state["last_signal"]      = signal
    state["last_signal_time"] = datetime.now(timezone.utc).strftime("%H:%M UTC")
    save_state()

    send_telegram(
        f"{'🟢' if signal == 'LONG' else '🔴'} <b>[SMC] {signal}</b>\n"
        f"Entry: ${p:,.2f}\n"
        f"SL: ${sl:,.2f} | TP1: ${tp1:,.2f} | TP2: ${tp2:,.2f}\n"
        f"{'🔥 Strong confluence (2× size)' if confluence_strong else 'Normal confluence'}"
    )

    # AI summary (richer Telegram)
    if deps.get("send_ai_summary") and ai_result:
        deps["send_ai_summary"]("SMC", signal, p, sl, tp1, ai_action, ai_result, ai_shadow)


# ═══════════════════════════════════════════════════════════════
# Position management — 2-phase TP (TP1 50% + BE → TP2)
# ═══════════════════════════════════════════════════════════════

def check_position(deps, state, price):
    """
    Διαχειρίζεται ανοιχτή θέση με 2-phase TP (ίδιο με την παλιά D):
      Phase 1: TP1 hit → κλείνει 50%, μετακινεί SL → entry (break-even)
      Phase 2: TP2 hit → κλείνει υπόλοιπο (WIN) | SL hit → κλείνει
    """
    finalize      = deps["finalize"]
    finalize_partial = deps["finalize_partial"]
    send_telegram = deps["send_telegram"]
    save_state    = deps["save_state"]

    pos = state.get("position")
    if not pos:
        return

    entry   = pos["entry"]
    sl      = pos["sl"]
    tp1     = pos["tp1"]
    tp2     = pos["tp2"]
    is_long = pos["type"] == "LONG"

    # ── Phase 1: TP1 hit → close 50%, SL → break even ──
    if not pos.get("phase1_done"):
        hit_tp1 = (is_long and price >= tp1) or (not is_long and price <= tp1)
        if hit_tp1:
            partial_qty = round(pos["qty"] * CONFIG["tp1_close_pct"], 6)
            partial_pnl = round(((tp1 - entry) if is_long else (entry - tp1)) * partial_qty, 2)
            # Καταγραφή partial μέσω του finalize_partial (κρατάει θέση ανοιχτή)
            finalize_partial(tp1, partial_qty, partial_pnl, "TP1 (50%)")
            # Move SL → entry, reduce qty
            pos["sl"]          = entry
            pos["qty"]         = round(pos["qty"] - partial_qty, 6)
            pos["phase1_done"] = True
            save_state()
            send_telegram(
                f"🎯 <b>[SMC] TP1 HIT (50%)</b>\n"
                f"Close: ${tp1:,.2f} | PnL: +${partial_pnl:.2f}\n"
                f"SL → Break Even | Riding to TP2: ${tp2:,.2f}"
            )
            return

    # ── Phase 2: TP2 or SL ──
    hit_tp2 = (is_long and price >= tp2) or (not is_long and price <= tp2)
    hit_sl  = (is_long and price <= sl)  or (not is_long and price >= sl)

    if hit_tp2:
        finalize(tp2, "WIN", "TP2")
    elif hit_sl:
        actual_pnl = ((sl - entry) if is_long else (entry - sl)) * pos["qty"]
        if abs(actual_pnl) < 1.0:
            result, note = "BREAK EVEN", "BREAK EVEN"
        elif actual_pnl > 0:
            result, note = "WIN", "STOP LOSS (profit)"
        else:
            result, note = "LOSS", "STOP LOSS"
        finalize(sl, result, note)
