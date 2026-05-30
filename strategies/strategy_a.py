"""
strategy_a.py — Strategy A (Daily Box + 1H RSI)
═══════════════════════════════════════════════════
Αυτόνομη στρατηγική (scheduled scan), μετακινημένη αυτούσια από το bot.py
ως μέρος του Phase 2 refactor (dependency injection — όπως CM/SMC).

ΦΙΛΟΣΟΦΙΑ: scheduled-scan strategy.
  Κάθε scheduler cycle (~60s) σαρώνει daily box + 1H RSI + divergence και,
  αν βρει setup στα άκρα του box (PDH/PDL), ανοίγει θέση (αφού περάσει από
  AI Validator). Η διαχείριση θέσης είναι 4-phase με trailing stop.

Entry model:
  • SHORT στο PDH:  price στο box["high"], RSI>70, box mid < price
  • LONG  στο PDL:  price στο box["low"],  RSI<30, box mid > price
  • bull/bear divergence → διπλάσιο risk

Exit model: 4-phase (trailing stop)
  • Phase 1 (50% προς TP):  SL → entry (break-even)
  • Phase 2 (70% προς TP):  κλείνει 30% partial
  • Phase 3 (past TP):       ενεργοποίηση trailing stop 0.3% (floor = TP)
  • Phase 4 (trailing hit):  κλείνει το υπόλοιπο (WIN)
  • Normal SL hit:           κλείνει (LOSS / BE / WIN ανάλογα με τη θέση του SL)

ΟΛΗ η trading-λογική είναι εδώ. Το bot.py καλεί:
  • on_tick(deps, state, price)        — κάθε scheduler cycle
  • check_position(deps, state, price) — εσωτερικά, όταν υπάρχει θέση
Τα dependencies (rt, get_candles, indicators, place_order, finalize, …)
περνιούνται μέσω του deps dict — η λογική δεν εξαρτάται από το bot.py.

ΣΗΜΕΙΩΣΗ: Πιστή (verbatim) μεταφορά. Καμία αλλαγή σε entry conditions,
SL/TP math, sizing ή exit behaviour — μόνο δομή.
"""

import json
import logging
import os
from datetime import datetime, timezone

log = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────
# Named constants για τα magic numbers του exit model. Οι τιμές είναι
# ΠΑΝΟΜΟΙΟΤΥΠΕΣ με την αρχική check_position_a — μόνο ονοματοδοσία.
CONFIG = {
    "trailing_distance": 0.003,  # 0.3% trailing stop distance
    "phase1_progress":   0.50,   # 50% προς TP → break-even
    "phase2_progress":   0.70,   # 70% προς TP → partial close
    "phase2_close_pct":  0.30,   # ποσοστό θέσης που κλείνει στο Phase 2
}


# ═══════════════════════════════════════════════════════════════
# Position management — 4-phase trailing exit
# ═══════════════════════════════════════════════════════════════

def check_position(deps, state, price):
    """
    Διαχειρίζεται ανοιχτή θέση με 4-phase trailing exit (ίδιο με το παλιό
    check_position_a). Τα state mutations γίνονται απευθείας στο `state` dict.
    """
    finalize             = deps["finalize"]
    send_telegram        = deps["send_telegram"]
    save_state           = deps["save_state"]
    close_position_live  = deps["close_position_live"]
    trading_mode         = deps.get("trading_mode", "PAPER")
    cfg                  = CONFIG

    pos = state["position"]
    if not pos:
        return

    if os.environ.get("FORCE_CLOSE", "").lower() == "true":
        finalize(price, "WIN" if price > pos["entry"] else "LOSS", "FORCE CLOSE")
        return

    entry   = pos["entry"]
    tp      = pos["tp"]
    is_long = pos["type"] == "LONG"
    tp_dist = abs(tp - entry)
    if tp_dist == 0:
        return

    progress = ((price - entry) / tp_dist) if is_long else ((entry - price) / tp_dist)

    # Phase 1: 50% - Break Even
    if not pos.get("phase1_done") and progress >= cfg["phase1_progress"]:
        pos["sl"] = entry; pos["phase1_done"] = True
        log.info(f"[A] Phase 1: SL -> entry @ {entry:.2f}")
        send_telegram(f"🔒 <b>[A] BREAK EVEN</b>\nSL moved to ${entry:,.2f}")
        save_state()

    # Phase 2: 70% - Partial 30% close
    if not pos.get("phase2_done") and progress >= cfg["phase2_progress"]:
        pqty = round(pos["qty"] * cfg["phase2_close_pct"], 4)
        ppnl = round(((price - entry) if is_long else (entry - price)) * pqty, 2)
        pos["qty"] = round(pos["qty"] - pqty, 4); pos["phase2_done"] = True
        state["pnl_total"] = round(state["pnl_total"] + ppnl, 2)
        state["balance"]   = round(state["balance"]   + ppnl, 2)
        log.info(f"[A] Phase 2: Partial 30% @ {price:.2f} PnL={ppnl:+.2f}")
        send_telegram(f"💰 <b>[A] PARTIAL 30%</b>\n+${ppnl:.2f} | Rem: {pos['qty']:.4f} BTC")
        if trading_mode == "LIVE": close_position_live(pos["type"], pqty)
        save_state()

    # Phase 3+4: Past TP - Trailing stop (SL ποτέ κάτω από το TP)
    past_tp = (is_long and price >= tp) or (not is_long and price <= tp)
    if past_tp:
        if not pos.get("trailing_active"):
            pos["trailing_active"] = True
            pos["trailing_peak"]   = price
            init_tsl = round(price * (1 - cfg["trailing_distance"]), 2) if is_long else round(price * (1 + cfg["trailing_distance"]), 2)
            # Trailing SL ξεκινάει στο TP (ή λίγο πιο πάνω) — ποτέ κάτω από TP
            pos["trailing_sl"] = max(init_tsl, tp) if is_long else min(init_tsl, tp)
            log.info(f"[A] Phase 3: Trailing activated @ {price:.2f}, TSL={pos['trailing_sl']:.2f}")
            send_telegram(f"🚀 <b>[A] TRAILING ACTIVE</b>\nPassed TP ${tp:,.2f}\nTrailing SL: ${pos['trailing_sl']:,.2f}")
            save_state()
            return

        peak = pos.get("trailing_peak", price)
        if is_long:
            if price > peak:
                pos["trailing_peak"] = price
                new_tsl = round(price * (1 - cfg["trailing_distance"]), 2)
                pos["trailing_sl"] = max(new_tsl, tp)  # ποτέ κάτω από το TP
                save_state()
            if price <= pos["trailing_sl"]:
                log.info(f"[A] Phase 4: Trailing hit @ {price:.2f} (peak={peak:.2f})")
                finalize(price, "WIN", f"TRAILING STOP @ ${price:,.2f}")
                return
        else:
            if price < peak:
                pos["trailing_peak"] = price
                new_tsl = round(price * (1 + cfg["trailing_distance"]), 2)
                pos["trailing_sl"] = min(new_tsl, tp)  # ποτέ πάνω από το TP (SHORT)
                save_state()
            if price >= pos["trailing_sl"]:
                log.info(f"[A] Phase 4: Trailing hit @ {price:.2f} (peak={peak:.2f})")
                finalize(price, "WIN", f"TRAILING STOP @ ${price:,.2f}")
                return
        return

    # Normal SL
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
    διαχειρίζεται την ανοιχτή θέση. Πιστή μεταφορά του run_strategy_a.

    deps: dict με {
        rt, get_candles, build_daily_box, detect_divergence, find_4h_sr,
        get_balance, calc_qty, place_order, place_order_live,
        close_position_live, fetch_news, ai_news_score, send_telegram,
        ai_validate, finalize, save_state, send_ai_summary,
        trading_mode, risk_per_trade, ai_shadow_mode, ai_shadow_master
    }
    """
    rt                = deps["rt"]
    get_candles       = deps["get_candles"]
    build_daily_box   = deps["build_daily_box"]
    detect_divergence = deps["detect_divergence"]
    find_4h_sr        = deps["find_4h_sr"]
    get_balance       = deps["get_balance"]
    calc_qty          = deps["calc_qty"]
    place_order_paper = deps["place_order"]
    place_order_live  = deps["place_order_live"]
    fetch_news        = deps["fetch_news"]
    ai_news_score     = deps["ai_news_score"]
    send_telegram     = deps["send_telegram"]
    ai_validate       = deps["ai_validate"]
    save_state        = deps["save_state"]
    send_ai_summary   = deps["send_ai_summary"]
    trading_mode      = deps.get("trading_mode", "PAPER")
    risk_per_trade    = deps["risk_per_trade"]
    ai_shadow_mode    = deps["ai_shadow_mode"]
    ai_shadow_master  = deps["ai_shadow_master"]

    rsi = rt.rsi_1h

    state["current_price"] = price
    state["current_rsi"]   = rsi

    if price <= 0 or not rt.initialized:
        state["last_signal"] = "Initializing..."
        return

    if state["position"]:
        check_position(deps, state, price)
        if state["position"]:
            pos = state["position"]
            pnl = ((price - pos["entry"]) if pos["type"] == "LONG" else (pos["entry"] - price)) * pos["qty"]
            trailing_tag = " | 🚀 TRAILING" if pos.get("trailing_active") else ""
            state["last_signal"] = f"HOLDING {pos['type']} @ {pos['entry']:.2f} | PnL: {pnl:+.2f}{trailing_tag}"
            return

    candles_4h = get_candles("4H", 500)
    candles_1h = get_candles("1H", 200)
    if not candles_4h or not candles_1h:
        state["last_signal"] = "No candle data"
        return

    box = build_daily_box(candles_4h)
    if not box:
        state["last_signal"] = "No box"
        return
    state["box"] = box

    highs_1h = [c["high"] for c in candles_1h]
    lows_1h  = [c["low"]  for c in candles_1h]
    with rt.lock:
        closes_1h = list(rt.closes_1h)
    bull_div, bear_div = detect_divergence(closes_1h, highs_1h[-20:], lows_1h[-20:])
    state["last_divergence"] = bull_div or bear_div

    support, resistance = find_4h_sr(candles_4h, price)
    balance = get_balance()

    log.info(f"[A] Price={price:.2f} RSI={rsi} Box=[{box['low']:.0f}-{box['high']:.0f}] MID={box['mid']:.0f} div={bull_div}/{bear_div}")

    # SHORT at PDH
    at_pdh = (price >= box["high"] * 0.995) and (price <= box["high"] * 1.015)
    if at_pdh and rsi > 70 and box["mid"] < price:
        sl = round(resistance * 1.003, 2)
        tp = box["mid"]
        if tp >= price: tp = round(price * 0.99, 2)
        if sl <= price: sl = round(price * 1.01, 2)
        if sl > price * 1.015: sl = round(price * 1.015, 2)
        risk_pct = risk_per_trade * 2 if bear_div else risk_per_trade
        qty      = calc_qty(balance, risk_pct, price, sl)
        log.info(f"[A] SHORT: entry={price:.2f} tp={tp:.2f} sl={sl:.2f}")
        headlines      = fetch_news()
        score, summary = ai_news_score(headlines, "SHORT", price, box)
        send_telegram(f"📰 <b>[A] News SHORT</b>\nScore:{score} | {summary}")
        # ── AI Validator ──────────────────────────────────────
        ai_action, ai_mult, _ai_result = ai_validate(
            strategy="A", side="SHORT",
            entry_price=price, stop_loss=sl, take_profit=tp,
            rsi_15m=rt.rsi_15m, rsi_1h=rsi,
            box=box, has_divergence=bear_div,
            trades=state.get("trades", []), balance=balance,
            candles_4h=candles_4h,
        )
        if ai_action == "SKIP": return
        if ai_action in ("REDUCE_SIZE", "DOUBLE_SIZE"): qty = round(qty * ai_mult, 4)
        # ─────────────────────────────────────────────────────
        order_id = place_order_paper("SHORT", qty, price, sl, tp) if trading_mode == "PAPER" else place_order_live("SHORT", qty, sl, tp)
        if order_id:
            state["position"] = {"type": "SHORT", "entry": price, "sl": sl, "tp": tp, "qty": qty,
                                  "time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                                  "order_id": order_id, "news_score": score, "news_summary": summary, "has_divergence": bear_div,
                                  "ai_action": ai_action, "ai_shadow": ai_shadow_mode,
                                  "ai_confidence": (_ai_result.confidence if _ai_result else 0),
                                  "ai_reasoning": (json.dumps(_ai_result.reasoning) if _ai_result and _ai_result.reasoning else "")}
            state["last_signal"] = "SHORT"; state["last_signal_time"] = datetime.now(timezone.utc).strftime("%H:%M UTC")
            save_state()
            send_telegram(f"🔴 <b>[A] SHORT</b>\nEntry:${price:,.2f} TP:${tp:,.2f} SL:${sl:,.2f}\n{'🔥DIV' if bear_div else 'Normal'}")
            send_ai_summary("A", "SHORT", price, sl, tp, ai_action, _ai_result, ai_shadow_master)
        return

    # LONG at PDL
    at_pdl = (price <= box["low"] * 1.005) and (price >= box["low"] * 0.985)
    if at_pdl and rsi < 30 and box["mid"] > price:
        sl = round(support * 0.997, 2)
        tp = box["mid"]
        if tp <= price: tp = round(price * 1.01, 2)
        if sl >= price: sl = round(price * 0.99, 2)
        if sl < price * 0.985: sl = round(price * 0.985, 2)
        risk_pct = risk_per_trade * 2 if bull_div else risk_per_trade
        qty      = calc_qty(balance, risk_pct, price, sl)
        log.info(f"[A] LONG: entry={price:.2f} tp={tp:.2f} sl={sl:.2f}")
        headlines      = fetch_news()
        score, summary = ai_news_score(headlines, "LONG", price, box)
        send_telegram(f"📰 <b>[A] News LONG</b>\nScore:{score} | {summary}")
        # ── AI Validator ──────────────────────────────────────
        ai_action, ai_mult, _ai_result = ai_validate(
            strategy="A", side="LONG",
            entry_price=price, stop_loss=sl, take_profit=tp,
            rsi_15m=rt.rsi_15m, rsi_1h=rsi,
            box=box, has_divergence=bull_div,
            trades=state.get("trades", []), balance=balance,
            candles_4h=candles_4h,
        )
        if ai_action == "SKIP": return
        if ai_action in ("REDUCE_SIZE", "DOUBLE_SIZE"): qty = round(qty * ai_mult, 4)
        # ─────────────────────────────────────────────────────
        order_id = place_order_paper("LONG", qty, price, sl, tp) if trading_mode == "PAPER" else place_order_live("LONG", qty, sl, tp)
        if order_id:
            state["position"] = {"type": "LONG", "entry": price, "sl": sl, "tp": tp, "qty": qty,
                                  "time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                                  "order_id": order_id, "news_score": score, "news_summary": summary, "has_divergence": bull_div,
                                  "ai_action": ai_action, "ai_shadow": ai_shadow_mode,
                                  "ai_confidence": (_ai_result.confidence if _ai_result else 0),
                                  "ai_reasoning": (json.dumps(_ai_result.reasoning) if _ai_result and _ai_result.reasoning else "")}
            state["last_signal"] = "LONG"; state["last_signal_time"] = datetime.now(timezone.utc).strftime("%H:%M UTC")
            save_state()
            send_telegram(f"🟢 <b>[A] LONG</b>\nEntry:${price:,.2f} TP:${tp:,.2f} SL:${sl:,.2f}\n{'🔥DIV' if bull_div else 'Normal'}")
            send_ai_summary("A", "LONG", price, sl, tp, ai_action, _ai_result, ai_shadow_master)
        return

    div_txt = "Div!" if (bull_div or bear_div) else "No div"
    state["last_signal"] = f"WAIT | RSI={rsi} | [{box['low']:.0f}-{box['high']:.0f}] | {div_txt}"
    log.info(f"[A] {state['last_signal']}")
