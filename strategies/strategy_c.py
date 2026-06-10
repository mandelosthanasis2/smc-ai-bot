"""
strategy_c.py — Strategy C (1H Box + Webhook)
═══════════════════════════════════════════════════
Αυτόνομη στρατηγική (webhook-driven), μετακινημένη αυτούσια από το bot.py /
main.py ως μέρος του Phase 2 refactor (dependency injection — όπως SMC).

ΦΙΛΟΣΟΦΙΑ: "thin" webhook strategy (ίδιο exit με την B, entry μέσω webhook).
  Τα signals έρχονται από TradingView webhook (/webhook/c). Το payload μπορεί
  να φέρει tp/sl· αν λείπουν, υπολογίζονται από το 1H box με R/R 2:1.
  Το bot ΔΕΝ σαρώνει για entries — απλά τα εκτελεί (αφού περάσουν από AI
  Validator) και διαχειρίζεται τη θέση.

Entry model (process_webhook):
  • signal "LONG"/"SHORT" από το webhook
  • tp/sl από το payload· fallback: tp = 1H box mid, sl_dist = tp_dist/2 (R/R 2:1)
  • dedup: αγνόησε διπλό signal εντός 30s
  • per-strategy overrides: TRADING_MODE_C / RISK_PER_TRADE_C (μέσω deps)

Exit model: 2-phase (trailing stop) — ίδιο με την B
  • Phase 1 (50% προς TP): SL → entry (break-even)
  • Phase 2 (TP hit):       trailing stop 0.3% (floor = TP). Αν
                            state["trailing_enabled"] is False → WIN στο TP.
  • Trailing hit:           κλείνει το υπόλοιπο (WIN)
  • Normal SL hit:          κλείνει (LOSS / BE / WIN ανάλογα με τη θέση του SL)

ΟΛΗ η trading-λογική είναι εδώ. Καλείται από:
  • process_webhook(deps, state, signal, price, data) — webhook route (main.py)
  • check_position(deps, state, price)                — scheduler cycle (bot.py)

ΣΗΜΕΙΩΣΗ: Πιστή (verbatim) μεταφορά. Καμία αλλαγή σε entry conditions,
SL/TP math (R/R 2:1), sizing ή exit behaviour — μόνο δομή.
"""

import contextlib
import json as _json
import logging
import os
import time as _time
from datetime import datetime, timezone

log = logging.getLogger(__name__)

# deps["lock"] = per-strategy RLock (live). Στα tests (χωρίς lock) → nullcontext.
_NULL = contextlib.nullcontext()

# ── Configuration ─────────────────────────────────────────────
# Named constants. Οι τιμές είναι ΠΑΝΟΜΟΙΟΤΥΠΕΣ με τα παλιά check_position_c /
# _wh_c — μόνο ονοματοδοσία.
CONFIG = {
    "trailing_distance": 0.003,  # 0.3% trailing stop distance
    "phase1_progress":   0.50,   # 50% προς TP → break-even
    "dedup_seconds":     30,     # αγνόησε διπλό signal εντός 30s
}

# Module-level dedup guard (πρώην _c_last_signal_time στο main.py).
_last_signal_time = 0.0


# ═══════════════════════════════════════════════════════════════
# MAIN: process_webhook — καλείται από το webhook route στο main.py
# ═══════════════════════════════════════════════════════════════

def process_webhook(deps, state, signal, price=None, data=None):
    """
    Επεξεργάζεται ένα webhook signal και ανοίγει θέση (αν περάσει το AI
    Validator). Πιστή μεταφορά του _wh_c.

    deps: dict με {
        get_price, calc_qty, place_order, send_telegram, ai_validate,
        save_state, send_ai_summary, get_candles, build_1h_box, rt,
        risk_pct, ai_shadow_master
    }
    """
    global _last_signal_time
    cfg = CONFIG
    if data is None:
        data = {}

    get_price        = deps["get_price"]
    calc_qty         = deps["calc_qty"]
    place_order      = deps["place_order"]
    send_telegram    = deps["send_telegram"]
    ai_validate      = deps["ai_validate"]
    save_state       = deps["save_state"]
    send_ai_summary  = deps["send_ai_summary"]
    get_candles      = deps["get_candles"]
    build_1h_box     = deps["build_1h_box"]
    rt               = deps["rt"]
    risk_pct         = deps["risk_pct"]
    ai_shadow_master = deps["ai_shadow_master"]
    lock             = deps.get("lock") or _NULL

    p = price or get_price()
    now = _time.time()
    if p <= 0 or state.get('position'):
        return
    if now - _last_signal_time < cfg["dedup_seconds"]:
        log.info(f"[C] Duplicate signal ignored (last={now - _last_signal_time:.1f}s ago)")
        return
    _last_signal_time = now

    tp = float(data.get('tp', 0)); sl = float(data.get('sl', 0))
    if not tp or not sl:
        cn = get_candles('1H', 50)
        if not cn: return
        bx = build_1h_box(cn)
        if not bx: return
        if signal == 'SHORT': tp = bx['mid']; sl = round(p + (p - bx['mid']) / 2, 2)
        else: tp = bx['mid']; sl = round(p - (bx['mid'] - p) / 2, 2)
    else:
        tp = round(tp, 2); sl = round(sl, 2)
    if signal == 'SHORT' and (tp >= p or sl <= p): return
    if signal == 'LONG'  and (tp <= p or sl >= p): return
    qty = calc_qty(state.get('balance', 10000), risk_pct, p, sl)
    # ── AI Validator ──────────────────────────────────────────────
    _ai_act, _ai_mult, _ai_res = ai_validate(
        strategy="C", side=signal,
        entry_price=p, stop_loss=sl, take_profit=tp,
        rsi_15m=rt.rsi_15m, rsi_1h=rt.rsi_1h,
        box=state.get("box"), has_divergence=False,
        trades=state.get("trades", []), balance=state.get("balance", 10000),
        candles_15m=get_candles("15m", 30),
    )
    if _ai_act == "SKIP": return
    if _ai_act in ("REDUCE_SIZE", "DOUBLE_SIZE"): qty = round(qty * _ai_mult, 4)
    # ─────────────────────────────────────────────────────────────
    oid = place_order(signal, qty, p, sl, tp)
    if oid:
        with lock:
            state['position'] = {'type': signal, 'entry': p, 'sl': sl, 'tp': tp, 'qty': qty,
                                 'time': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
                                 'opened_at_ms': int(_time.time() * 1000),  # fill-accounting match key
                                 'order_id': oid, 'live': bool(deps.get('is_live', False)),
                                 'ai_action': _ai_act, 'ai_shadow': ai_shadow_master,
                                 'ai_confidence': (_ai_res.confidence if _ai_res else 0),
                                 'ai_reasoning': (_json.dumps(_ai_res.reasoning) if _ai_res and _ai_res.reasoning else "")}
            state['last_signal'] = signal; state['last_signal_time'] = datetime.now(timezone.utc).strftime('%H:%M UTC')
        save_state()
        send_telegram(f"{'🔴' if signal == 'SHORT' else '🟢'} <b>[C] {signal}</b>\nEntry: ${p:,.2f} | TP: ${tp:,.2f} | SL: ${sl:,.2f}")
        send_ai_summary("C", signal, p, sl, tp, _ai_act, _ai_res, ai_shadow_master)


# ═══════════════════════════════════════════════════════════════
# Position management — 2-phase trailing exit (ίδιο με την B)
# ═══════════════════════════════════════════════════════════════

def check_position(deps, state, price):
    """
    Διαχειρίζεται ανοιχτή θέση με 2-phase trailing exit (ίδιο με το παλιό
    check_position_c). Τα state mutations γίνονται απευθείας στο `state` dict.

    LIVE θέσεις (pos["live"]): exchange-managed exit. Ο bot ΔΕΝ στέλνει market
    close για SL/trailing — μόνο μετακινεί το exchange stop μέσω deps["modify_sl"]
    (BE, trailing). Το πραγματικό κλείσιμο το εκτελεί το exchange stop και το
    ανιχνεύει ο reconciler («exchange flat, state open → finalize»). Μόνη
    εξαίρεση: FORCE_CLOSE_C. Paper: συμπεριφορά ταυτόσημη με πριν.
    """
    finalize      = deps["finalize"]
    send_telegram = deps["send_telegram"]
    save_state    = deps["save_state"]
    lock          = deps.get("lock") or _NULL
    modify_sl     = deps.get("modify_sl")
    cfg           = CONFIG

    pos = state["position"]
    if not pos:
        return
    is_live = bool(pos.get("live")) and modify_sl is not None

    if os.environ.get("FORCE_CLOSE_C", "").lower() == "true":
        finalize(price, "WIN" if price > pos["entry"] else "LOSS", "FORCE CLOSE")
        return

    entry   = pos["entry"]
    tp      = pos["tp"]
    is_long = pos["type"] == "LONG"
    tp_dist = abs(tp - entry)

    # Phase 1: 50% → Break Even
    if tp_dist > 0 and not pos.get("phase1_done"):
        progress = ((price - entry) / tp_dist) if is_long else ((entry - price) / tp_dist)
        if progress >= cfg["phase1_progress"]:
            # LIVE: πρώτα το exchange. Αν αποτύχει το move, ΔΕΝ σημαδεύουμε το
            # phase1_done — retry στο επόμενο tick (το stop μένει στο αρχικό).
            if is_live and not modify_sl(entry, force=True):
                return
            with lock:
                pos["sl"] = entry; pos["phase1_done"] = True
            log.info(f"[C] Phase 1: SL -> entry @ {entry:.2f}")
            send_telegram(f"🔒 <b>[C] BREAK EVEN</b>\nSL moved to ${entry:,.2f}")
            save_state()

    # Phase 2: TP hit → ενεργοποίηση trailing stop 0.3% (αν enabled)
    hit_tp = (is_long and price >= tp) or (not is_long and price <= tp)
    if hit_tp and not pos.get("trailing_active"):
        if not state.get("trailing_enabled", True):
            if is_live:
                return  # exchange preset TP κλείνει τη θέση — reconciler finalizes
            finalize(tp, "WIN", "TAKE PROFIT")
            return
        init_tsl = round(price * (1 - cfg["trailing_distance"]), 2) if is_long else round(price * (1 + cfg["trailing_distance"]), 2)
        with lock:
            pos["trailing_active"] = True
            pos["trailing_sl"] = max(init_tsl, tp) if is_long else min(init_tsl, tp)  # floor = TP
            pos["trailing_peak"] = price
        if is_live:
            # Σφίξε το exchange stop στο αρχικό trailing level (best effort —
            # αν αποτύχει, θα ξανασταλεί στο επόμενο peak update).
            modify_sl(pos["trailing_sl"], force=True)
        log.info(f"[C] Trailing activated @ {price:.2f}, TSL={pos['trailing_sl']:.2f}")
        send_telegram(f"🚀 <b>[C] TRAILING ACTIVE</b>\nTP reached ${tp:,.2f} — now trailing 0.3%\nTrailing SL: ${pos['trailing_sl']:,.2f}")
        save_state()
        return

    # Phase 2 active: ενημέρωση trailing SL
    if pos.get("trailing_active"):
        peak = pos.get("trailing_peak", price)
        if is_long:
            if price > peak:
                new_tsl = round(price * (1 - cfg["trailing_distance"]), 2)
                with lock:
                    pos["trailing_peak"] = price
                    pos["trailing_sl"] = max(new_tsl, tp)  # ποτέ κάτω από το TP
                save_state()
                if is_live:
                    modify_sl(pos["trailing_sl"])  # debounced στο bot layer
            if price <= pos["trailing_sl"]:
                if is_live:
                    return  # το exchange stop εκτελεί — reconciler finalizes
                finalize(price, "WIN", f"TRAILING STOP @ ${price:,.2f}")
                return
        else:
            if price < peak:
                new_tsl = round(price * (1 + cfg["trailing_distance"]), 2)
                with lock:
                    pos["trailing_peak"] = price
                    pos["trailing_sl"] = min(new_tsl, tp)  # ποτέ πάνω από το TP (SHORT)
                save_state()
                if is_live:
                    modify_sl(pos["trailing_sl"])  # debounced στο bot layer
            if price >= pos["trailing_sl"]:
                if is_live:
                    return  # το exchange stop εκτελεί — reconciler finalizes
                finalize(price, "WIN", f"TRAILING STOP @ ${price:,.2f}")
                return
        return

    hit_sl = (is_long and price <= pos["sl"]) or (not is_long and price >= pos["sl"])
    if hit_sl:
        if is_live:
            return  # το exchange SL εκτελεί — reconciler finalizes με το exchange ως αλήθεια
        actual_pnl = ((pos["sl"] - entry) if is_long else (entry - pos["sl"])) * pos["qty"]
        if abs(actual_pnl) < 1.0:
            result = "BREAK EVEN"; note = "BREAK EVEN"
        elif actual_pnl > 0:
            result = "WIN"; note = "STOP LOSS (profit)"
        else:
            result = "LOSS"; note = "STOP LOSS"
        finalize(pos["sl"], result, note)
