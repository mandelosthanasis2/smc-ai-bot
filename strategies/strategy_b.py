"""
strategy_b.py — Strategy B (1H Box + 15m RSI)
═══════════════════════════════════════════════════
Αυτόνομη στρατηγική (scheduled scan), μετακινημένη αυτούσια από το bot.py
ως μέρος του Phase 2 refactor (dependency injection — όπως A/CM/SMC).

ΦΙΛΟΣΟΦΙΑ: scheduled-scan strategy, πιο γρήγορο timeframe από την A.
  Κάθε scheduler cycle (~30s) σαρώνει 1H box (prev 1H candle) + 15m RSI +
  divergence και, αν βρει setup στα άκρα του box, ανοίγει θέση (αφού περάσει
  από AI Validator). R/R σταθερό 2:1.

Entry model:
  • SHORT στο 1H high: price στο box["high"], RSI15m>70, box mid < price
  • LONG  στο 1H low:  price στο box["low"],  RSI15m<30, box mid > price
  • tp = box mid · sl_dist = tp_dist/2  →  R/R 2:1 (ΣΤΑΘΕΡΟ — μη το αλλάξεις)
  • bull/bear divergence → διπλάσιο risk

Exit model: 2-phase (trailing stop)
  • Phase 1 (50% προς TP): SL → entry (break-even)
  • Phase 2 (TP hit):       ενεργοποίηση trailing stop 0.3% (floor = TP).
                            Αν state["trailing_enabled"] is False → κλείνει
                            στο TP ως WIN (TAKE PROFIT).
  • Trailing hit:           κλείνει το υπόλοιπο (WIN)
  • Normal SL hit:          κλείνει (LOSS / BE / WIN ανάλογα με τη θέση του SL)

ΣΗΜΕΙΩΣΗ: Πιστή (verbatim) μεταφορά. Καμία αλλαγή σε entry conditions,
SL/TP math (R/R 2:1), sizing, RSI thresholds ή exit behaviour — μόνο δομή.
Οι παράμετροι της B (RSI=70 / R:R=2.0) είναι off-limits ανά το HANDOFF.
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
# Named constants για τα magic numbers του exit model. Οι τιμές είναι
# ΠΑΝΟΜΟΙΟΤΥΠΕΣ με το αρχικό check_position_b — μόνο ονοματοδοσία.
CONFIG = {
    "trailing_distance": 0.003,  # 0.3% trailing stop distance
    "phase1_progress":   0.50,   # 50% προς TP → break-even
}

# Module-level race-condition guard (πρώην global _b_entering στο bot.py).
# Προστατεύει από διπλό entry όσο το AI Validator (αργό network call) τρέχει.
_entering = False


# ═══════════════════════════════════════════════════════════════
# Position management — 2-phase trailing exit
# ═══════════════════════════════════════════════════════════════

def check_position(deps, state, price):
    """
    Διαχειρίζεται ανοιχτή θέση με 2-phase trailing exit (ίδιο με το παλιό
    check_position_b). Τα state mutations γίνονται απευθείας στο `state` dict.
    """
    finalize      = deps["finalize"]
    send_telegram = deps["send_telegram"]
    save_state    = deps["save_state"]
    lock          = deps.get("lock") or _NULL
    cfg           = CONFIG

    pos = state["position"]
    if not pos:
        return

    if os.environ.get("FORCE_CLOSE_B", "").lower() == "true":
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
            with lock:
                pos["sl"] = entry; pos["phase1_done"] = True
            log.info(f"[B] Phase 1: SL -> entry @ {entry:.2f}")
            send_telegram(f"🔒 <b>[B] BREAK EVEN</b>\nSL moved to ${entry:,.2f}")
            save_state()

    # Phase 2: TP hit → ενεργοποίηση trailing stop 0.3% (αν enabled)
    hit_tp = (is_long and price >= tp) or (not is_long and price <= tp)
    if hit_tp and not pos.get("trailing_active"):
        if not state.get("trailing_enabled", True):
            finalize(tp, "WIN", "TAKE PROFIT")
            return
        init_tsl = round(price * (1 - cfg["trailing_distance"]), 2) if is_long else round(price * (1 + cfg["trailing_distance"]), 2)
        with lock:
            pos["trailing_active"] = True
            pos["trailing_sl"] = max(init_tsl, tp) if is_long else min(init_tsl, tp)  # floor = TP
            pos["trailing_peak"] = price
        log.info(f"[B] Trailing activated @ {price:.2f}, TSL={pos['trailing_sl']:.2f}")
        send_telegram(f"🚀 <b>[B] TRAILING ACTIVE</b>\nTP reached ${tp:,.2f} — now trailing 0.3%\nTrailing SL: ${pos['trailing_sl']:,.2f}")
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
            if price <= pos["trailing_sl"]:
                finalize(price, "WIN", f"TRAILING STOP @ ${price:,.2f}")
                return
        else:
            if price < peak:
                new_tsl = round(price * (1 + cfg["trailing_distance"]), 2)
                with lock:
                    pos["trailing_peak"] = price
                    pos["trailing_sl"] = min(new_tsl, tp)  # ποτέ πάνω από το TP (SHORT)
                save_state()
            if price >= pos["trailing_sl"]:
                finalize(price, "WIN", f"TRAILING STOP @ ${price:,.2f}")
                return
        return

    hit_sl = (is_long and price <= pos["sl"]) or (not is_long and price >= pos["sl"])
    if hit_sl:
        actual_pnl = ((pos["sl"] - entry) if is_long else (entry - pos["sl"])) * pos["qty"]
        if abs(actual_pnl) < 1.0:
            result = "BREAK EVEN"; note = "BREAK EVEN"
        elif actual_pnl > 0:
            result = "WIN"; note = "STOP LOSS (profit)"
        else:
            result = "LOSS"; note = "STOP LOSS"
        finalize(pos["sl"], result, note)


# ═══════════════════════════════════════════════════════════════
# MAIN: on_tick — καλείται κάθε scheduler cycle από το bot.py
# ═══════════════════════════════════════════════════════════════

def on_tick(deps, state, price):
    """
    Σαρώνει για setup και ανοίγει θέση (αν περάσει το AI Validator), ή
    διαχειρίζεται την ανοιχτή θέση. Πιστή μεταφορά του run_strategy_b.

    deps: dict με {
        rt, get_candles, build_1h_box, detect_divergence, calc_qty,
        place_order, place_order_live, send_telegram, ai_validate,
        finalize, save_state, send_ai_summary,
        trading_mode, risk_per_trade, ai_shadow_master
    }
    """
    global _entering

    rt                = deps["rt"]
    get_candles       = deps["get_candles"]
    build_1h_box      = deps["build_1h_box"]
    detect_divergence = deps["detect_divergence"]
    calc_qty          = deps["calc_qty"]
    place_order_paper = deps["place_order"]
    place_order_live  = deps["place_order_live"]
    send_telegram     = deps["send_telegram"]
    ai_validate       = deps["ai_validate"]
    save_state        = deps["save_state"]
    send_ai_summary   = deps["send_ai_summary"]
    trading_mode      = deps.get("trading_mode", "PAPER")
    risk_per_trade    = deps["risk_per_trade"]
    ai_shadow_master  = deps["ai_shadow_master"]
    lock              = deps.get("lock") or _NULL

    rsi_15m = rt.rsi_15m

    state["current_rsi"]   = rsi_15m
    state["current_price"] = price  # needed for dashboard unrealised PnL

    if price <= 0 or not rt.initialized:
        state["last_signal"] = "Initializing..."
        return

    if state["position"]:
        check_position(deps, state, price)
        if state["position"]:
            pos = state["position"]
            pnl = ((price - pos["entry"]) if pos["type"] == "LONG" else (pos["entry"] - price)) * pos["qty"]
            state["last_signal"] = f"HOLDING {pos['type']} @ {pos['entry']:.2f} | PnL: {pnl:+.2f}"
            return

    candles_1h = get_candles("1H", 50)
    if not candles_1h:
        state["last_signal"] = "No candle data"
        return

    box = build_1h_box(candles_1h)
    if not box: return
    state["box"] = box

    candles_15m = get_candles("15m", 100)
    if candles_15m:
        h15 = [c["high"] for c in candles_15m]
        l15 = [c["low"]  for c in candles_15m]
        with rt.lock: c15 = list(rt.closes_15m)
        bull_div, bear_div = detect_divergence(c15, h15[-20:], l15[-20:])
    else:
        bull_div = bear_div = False
    state["last_divergence"] = bull_div or bear_div

    balance = state["balance"]
    log.info(f"[B] Price={price:.2f} RSI15m={rsi_15m} 1H=[{box['low']:.0f}-{box['high']:.0f}]")

    # SHORT at 1H High
    if _entering: return  # Race condition guard
    at_high = (price >= box["high"] * 0.995) and (price <= box["high"] * 1.015)
    if at_high and rsi_15m > 70 and box["mid"] < price:
        tp_dist = price - box["mid"]
        sl_dist = tp_dist / 2
        tp = box["mid"]; sl = round(price + sl_dist, 2)
        risk_pct = risk_per_trade * 2 if bear_div else risk_per_trade
        qty      = calc_qty(balance, risk_pct, price, sl)
        # ── AI Validator ──────────────────────────────────────
        _entering = True
        ai_action, ai_mult, _ai_result = ai_validate(
            strategy="B", side="SHORT",
            entry_price=price, stop_loss=sl, take_profit=tp,
            rsi_15m=rsi_15m, rsi_1h=rt.rsi_1h,
            box=box, has_divergence=bear_div,
            trades=state.get("trades", []), balance=balance,
            candles_15m=candles_15m or get_candles("15m", 30),
        )
        if ai_action == "SKIP": _entering = False; return
        if ai_action in ("REDUCE_SIZE", "DOUBLE_SIZE"): qty = round(qty * ai_mult, 4)
        # ─────────────────────────────────────────────────────
        order_id = place_order_paper("SHORT", qty, price, sl, tp) if trading_mode == "PAPER" else place_order_live("SHORT", qty, sl, tp)
        if order_id:
            with lock:
                state["position"] = {"type": "SHORT", "entry": price, "sl": sl, "tp": tp, "qty": qty,
                                       "time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                                       "order_id": order_id, "has_divergence": bear_div,
                                       "ai_action": ai_action, "ai_shadow": ai_shadow_master,
                                       "ai_confidence": (_ai_result.confidence if _ai_result else 0),
                                       "ai_reasoning": (json.dumps(_ai_result.reasoning) if _ai_result and _ai_result.reasoning else "")}
            send_ai_summary("B", "SHORT", price, sl, tp, ai_action, _ai_result, ai_shadow_master)
            with lock:
                state["last_signal"] = "SHORT"; state["last_signal_time"] = datetime.now(timezone.utc).strftime("%H:%M UTC")
            save_state()
            send_telegram(f"🔴 <b>[B] SHORT</b>\nEntry:${price:,.2f} TP:${tp:,.2f} SL:${sl:,.2f}\nR/R 2:1 {'🔥DIV' if bear_div else ''}")
        _entering = False
        return

    # LONG at 1H Low
    at_low = (price <= box["low"] * 1.005) and (price >= box["low"] * 0.985)
    if at_low and rsi_15m < 30 and box["mid"] > price:
        tp_dist = box["mid"] - price
        sl_dist = tp_dist / 2
        tp = box["mid"]; sl = round(price - sl_dist, 2)
        risk_pct = risk_per_trade * 2 if bull_div else risk_per_trade
        qty      = calc_qty(balance, risk_pct, price, sl)
        # ── AI Validator ──────────────────────────────────────
        _entering = True
        ai_action, ai_mult, _ai_result = ai_validate(
            strategy="B", side="LONG",
            entry_price=price, stop_loss=sl, take_profit=tp,
            rsi_15m=rsi_15m, rsi_1h=rt.rsi_1h,
            box=box, has_divergence=bull_div,
            trades=state.get("trades", []), balance=balance,
            candles_15m=candles_15m or get_candles("15m", 30),
        )
        if ai_action == "SKIP": _entering = False; return
        if ai_action in ("REDUCE_SIZE", "DOUBLE_SIZE"): qty = round(qty * ai_mult, 4)
        # ─────────────────────────────────────────────────────
        order_id = place_order_paper("LONG", qty, price, sl, tp) if trading_mode == "PAPER" else place_order_live("LONG", qty, sl, tp)
        if order_id:
            with lock:
                state["position"] = {"type": "LONG", "entry": price, "sl": sl, "tp": tp, "qty": qty,
                                       "time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                                       "order_id": order_id, "has_divergence": bull_div,
                                       "ai_action": ai_action, "ai_shadow": ai_shadow_master,
                                       "ai_confidence": (_ai_result.confidence if _ai_result else 0),
                                       "ai_reasoning": (json.dumps(_ai_result.reasoning) if _ai_result and _ai_result.reasoning else "")}
            send_ai_summary("B", "LONG", price, sl, tp, ai_action, _ai_result, ai_shadow_master)
            with lock:
                state["last_signal"] = "LONG"; state["last_signal_time"] = datetime.now(timezone.utc).strftime("%H:%M UTC")
            save_state()
            send_telegram(f"🟢 <b>[B] LONG</b>\nEntry:${price:,.2f} TP:${tp:,.2f} SL:${sl:,.2f}\nR/R 2:1 {'🔥DIV' if bull_div else ''}")
        _entering = False
        return

    div_txt = "Div!" if (bull_div or bear_div) else "No div"
    state["last_signal"] = f"WAIT | RSI={rsi_15m} | [{box['low']:.0f}-{box['high']:.0f}] | {div_txt}"
    log.info(f"[B] {state['last_signal']}")
