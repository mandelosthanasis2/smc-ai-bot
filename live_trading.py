"""
live_trading.py — pure live-sizing & mode-resolution logic (no I/O, no heavy deps)
═══════════════════════════════════════════════════════════════════════════════
Καθαρές, side-effect-free συναρτήσεις για το live trading της Strategy C. Ζουν
χωριστά από το bot.py ώστε να είναι μονάδα-ελεγχόμενες χωρίς exchange/DB/network
(το bot.py τις τυλίγει με logging + config). Imports: μόνο `math`.

Επιλογές χρήστη που υλοποιούνται εδώ:
  • Round-up στο exchange minimum + size step.
  • Auto-min leverage με cap.
  • Skip (None) αν το (rounded) trade ρισκάρει πάνω από cap, ή δεν είναι affordable.
"""

import math


def round_up_to_step(qty: float, min_qty: float, step: float) -> float:
    """Φέρε το qty πάνω από το exchange minimum και snap (ceil) στο size step."""
    step = step or min_qty
    q = max(qty, min_qty)
    return round(math.ceil(q / step) * step, 8)


def round_to_tick(price: float, tick: float) -> float:
    """Snap μια τιμή στο πλησιέστερο price tick (π.χ. 0.1 για BTCUSDT), χωρίς
    float drift. Το Bitget απορρίπτει τιμές που δεν είναι πολλαπλάσια του tick
    (code: "should be a multiple of ..."). Fallback σε 2 δεκαδικά αν tick άκυρο."""
    if not tick or tick <= 0:
        return round(price, 2)
    ndigits = max(0, -int(math.floor(math.log10(tick))))
    return round(round(price / tick) * tick, ndigits)


def leverage_for(notional: float, balance: float, leverage_cap: int, margin_buffer: float) -> int:
    """Ελάχιστη ακέραιη μόχλευση ώστε margin (=notional/lev) ≤ balance·buffer, με cap."""
    usable = max(balance * margin_buffer, 1e-9)
    return max(1, min(math.ceil(notional / usable), int(leverage_cap)))


def prepare_live_size(qty, entry, sl, balance, *, min_qty, size_step,
                      leverage_cap, max_trade_risk_pct, margin_buffer):
    """
    → (final_qty, leverage)  αν το trade είναι εφικτό & εντός risk cap
    → None                    για καθαρό skip

    Pure: καμία I/O, κανένα logging — ο caller λογάρει τον λόγο skip.
    """
    if balance <= 0 or entry <= 0:
        return None
    final_qty = round_up_to_step(qty, min_qty, size_step)
    if final_qty <= 0:
        return None
    # risk cap (ΜΕΤΑ το rounding — το min-size μπορεί να ρισκάρει πολύ σε μικρό λογαριασμό)
    trade_risk = abs(entry - sl) * final_qty
    if trade_risk > balance * max_trade_risk_pct:
        return None
    # affordability: ακόμη και στο cap leverage, το margin πρέπει να χωρά
    notional = final_qty * entry
    leverage = leverage_for(notional, balance, leverage_cap, margin_buffer)
    if notional / leverage > balance * margin_buffer:
        return None
    return final_qty, leverage


def resolve_mode(strategy: str, allowlist, creds_ok_fn) -> str:
    """'LIVE' μόνο αν strategy ∈ allowlist ΚΑΙ creds_ok_fn(strategy) — αλλιώς 'PAPER'."""
    if strategy in allowlist and creds_ok_fn(strategy):
        return "LIVE"
    return "PAPER"
