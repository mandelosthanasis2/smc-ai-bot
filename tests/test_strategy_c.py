"""
tests/test_strategy_c.py
════════════════════════
Unit tests for Strategy C (strategies/strategy_c.py) — 1H Box + Webhook.

Strategy C was moved out of bot.py (exit) and main.py (webhook entry) into its
own module (Phase 2 refactor), following the webhook-driven pattern used by
SMC: process_webhook() for entries, check_position() for the 2-phase trailing
exit. These tests pin down the pre-existing behaviour so the structural move
cannot silently change the trading logic.

Two areas are covered:

1. **process_webhook** — entry from a TradingView signal:
     • explicit tp/sl from the payload are honoured
     • missing tp/sl fall back to the 1H box with R/R 2:1
     • wrong-sided tp/sl are rejected
     • the 30s dedup guard blocks a rapid second signal
     • AI SKIP blocks the entry

2. **check_position** — the 2-phase trailing exit (same model as B):
     • break-even, trailing activation floored at TP, trailing→WIN,
       trailing_enabled=False→TAKE PROFIT, plain SL / break-even.
"""

import contextlib

import pytest

from strategies import strategy_c as C
from tests.conftest import OrderRecorder


# ── exit-path deps ────────────────────────────────────────────────────────

def _exit_deps(recorder):
    return {
        "finalize": recorder.finalize,
        "send_telegram": recorder.send_telegram,
        "save_state": recorder.save_state,
    }


def _open_long(qty=1.0, **over):
    pos = {
        "type": "LONG", "entry": 100_000.0, "sl": 99_500.0,
        "tp": 101_000.0, "qty": qty,
    }
    pos.update(over)
    return pos


def _open_short(qty=1.0, **over):
    pos = {
        "type": "SHORT", "entry": 100_000.0, "sl": 100_500.0,
        "tp": 99_000.0, "qty": qty,
    }
    pos.update(over)
    return pos


# ── 2-phase trailing exit ─────────────────────────────────────────────────

@pytest.mark.strategy
class TestTwoPhaseExit:
    def test_phase1_moves_stop_to_break_even(self, fresh_state):
        fresh_state["position"] = _open_long()
        rec = OrderRecorder(fresh_state)
        C.check_position(_exit_deps(rec), fresh_state, 100_500.0)  # progress 0.50

        pos = fresh_state["position"]
        assert pos is not None
        assert pos["phase1_done"] is True
        assert pos["sl"] == pos["entry"]

    def test_tp_hit_activates_trailing_floored_at_tp(self, fresh_state):
        fresh_state["position"] = _open_long(phase1_done=True, sl=100_000.0)
        rec = OrderRecorder(fresh_state)
        C.check_position(_exit_deps(rec), fresh_state, 101_000.0)  # at TP

        pos = fresh_state["position"]
        assert pos["trailing_active"] is True
        assert pos["trailing_sl"] == 101_000.0          # floor = TP

    def test_trailing_disabled_takes_profit_at_tp(self, fresh_state):
        fresh_state["position"] = _open_long(phase1_done=True, sl=100_000.0)
        fresh_state["trailing_enabled"] = False
        rec = OrderRecorder(fresh_state)
        C.check_position(_exit_deps(rec), fresh_state, 101_000.0)

        assert fresh_state["position"] is None
        assert rec.finals[-1]["result"] == "WIN"
        assert rec.finals[-1]["note"] == "TAKE PROFIT"

    def test_trailing_advances_then_closes_as_win(self, fresh_state):
        fresh_state["position"] = _open_long(
            phase1_done=True, sl=100_000.0,
            trailing_active=True, trailing_peak=101_000.0, trailing_sl=101_000.0,
        )
        rec = OrderRecorder(fresh_state)
        deps = _exit_deps(rec)
        C.check_position(deps, fresh_state, 102_000.0)   # advance → tsl 101_694
        assert fresh_state["position"]["trailing_sl"] == pytest.approx(101_694.0)
        C.check_position(deps, fresh_state, 101_690.0)   # pull back → WIN

        assert fresh_state["position"] is None
        assert rec.finals[-1]["result"] == "WIN"
        assert rec.finals[-1]["note"].startswith("TRAILING STOP")

    def test_short_trailing_floored_at_tp(self, fresh_state):
        fresh_state["position"] = _open_short(phase1_done=True, sl=100_000.0)
        rec = OrderRecorder(fresh_state)
        C.check_position(_exit_deps(rec), fresh_state, 99_000.0)  # at TP

        pos = fresh_state["position"]
        assert pos["trailing_active"] is True
        assert pos["trailing_sl"] == 99_000.0           # ceiling = TP for SHORT

    def test_plain_stop_loss_is_a_loss(self, fresh_state):
        fresh_state["position"] = _open_long()
        rec = OrderRecorder(fresh_state)
        C.check_position(_exit_deps(rec), fresh_state, 99_500.0)  # hit SL

        assert fresh_state["position"] is None
        assert rec.finals[-1]["result"] == "LOSS"
        assert rec.finals[-1]["note"] == "STOP LOSS"

    def test_break_even_pullback_is_not_a_loss(self, fresh_state):
        fresh_state["position"] = _open_long(phase1_done=True, sl=100_000.0)
        rec = OrderRecorder(fresh_state)
        C.check_position(_exit_deps(rec), fresh_state, 100_000.0)  # back to entry

        assert fresh_state["position"] is None
        assert rec.finals[-1]["result"] == "BREAK EVEN"
        assert fresh_state["losses"] == 0


# ── webhook entry ─────────────────────────────────────────────────────────

class _FakeRT:
    def __init__(self, price=100_000.0, rsi_15m=50.0, rsi_1h=50.0):
        self.price = price
        self.rsi_15m = rsi_15m
        self.rsi_1h = rsi_1h
        self.lock = contextlib.nullcontext()


def _entry_deps(rec, rt, box=None, **over):
    box = box or {"high": 101_000.0, "low": 99_000.0, "mid": 100_000.0}
    deps = {
        "get_price": lambda: rt.price,
        "calc_qty": lambda bal, risk, entry, sl: 0.5,
        "place_order": rec.place_order,
        "send_telegram": rec.send_telegram,
        "ai_validate": lambda **k: ("GO", 1.0, None),
        "save_state": rec.save_state,
        "send_ai_summary": lambda *a, **k: None,
        "get_candles": lambda gran, limit: [{"high": 1, "low": 1, "close": 1}] * limit,
        "build_1h_box": lambda cn: box,
        "rt": rt,
        "risk_pct": 0.02,
        "ai_shadow_master": True,
    }
    deps.update(over)
    return deps


@pytest.mark.strategy
class TestWebhookEntry:
    def setup_method(self):
        # reset the module-level dedup guard between tests
        C._last_signal_time = 0.0

    def test_explicit_tp_sl_from_payload_are_honoured(self, fresh_state):
        rec = OrderRecorder(fresh_state)
        rt = _FakeRT(price=100_000.0)
        data = {"tp": "102000", "sl": "99000"}
        C.process_webhook(_entry_deps(rec, rt), fresh_state, "LONG", 100_000.0, data)

        pos = fresh_state["position"]
        assert pos is not None
        assert pos["type"] == "LONG"
        assert pos["tp"] == 102_000.0
        assert pos["sl"] == 99_000.0
        assert len(rec.orders) == 1

    def test_missing_levels_fall_back_to_box_with_rr_2to1(self, fresh_state):
        rec = OrderRecorder(fresh_state)
        rt = _FakeRT(price=101_000.0)
        # box mid 100_000; SHORT → tp = mid, sl_dist = (price - mid)/2
        box = {"high": 102_000.0, "low": 98_000.0, "mid": 100_000.0}
        C.process_webhook(_entry_deps(rec, rt, box=box), fresh_state, "SHORT", 101_000.0, {})

        pos = fresh_state["position"]
        assert pos is not None
        assert pos["tp"] == 100_000.0                    # box mid
        assert pos["sl"] == 101_500.0                    # 101_000 + (1_000/2)
        reward = abs(pos["entry"] - pos["tp"])
        risk = abs(pos["sl"] - pos["entry"])
        assert reward == pytest.approx(2 * risk)         # R/R 2:1

    def test_wrong_sided_levels_are_rejected(self, fresh_state):
        rec = OrderRecorder(fresh_state)
        rt = _FakeRT(price=100_000.0)
        # LONG but tp below price → invalid, no position
        data = {"tp": "99000", "sl": "98000"}
        C.process_webhook(_entry_deps(rec, rt), fresh_state, "LONG", 100_000.0, data)

        assert fresh_state["position"] is None
        assert len(rec.orders) == 0

    def test_dedup_blocks_rapid_second_signal(self, fresh_state):
        rec = OrderRecorder(fresh_state)
        rt = _FakeRT(price=100_000.0)
        deps = _entry_deps(rec, rt)
        data = {"tp": "102000", "sl": "99000"}
        C.process_webhook(deps, fresh_state, "LONG", 100_000.0, data)
        # clear the position so only the dedup guard can block the 2nd signal
        fresh_state["position"] = None
        C.process_webhook(deps, fresh_state, "LONG", 100_000.0, data)

        assert len(rec.orders) == 1                      # second was deduped

    def test_ai_skip_blocks_entry(self, fresh_state):
        rec = OrderRecorder(fresh_state)
        rt = _FakeRT(price=100_000.0)
        deps = _entry_deps(rec, rt, ai_validate=lambda **k: ("SKIP", 1.0, None))
        data = {"tp": "102000", "sl": "99000"}
        C.process_webhook(deps, fresh_state, "LONG", 100_000.0, data)

        assert fresh_state["position"] is None
        assert len(rec.orders) == 0

    def test_no_entry_when_position_already_open(self, fresh_state):
        fresh_state["position"] = _open_long()
        rec = OrderRecorder(fresh_state)
        rt = _FakeRT(price=100_000.0)
        data = {"tp": "102000", "sl": "99000"}
        C.process_webhook(_entry_deps(rec, rt), fresh_state, "LONG", 100_000.0, data)

        assert len(rec.orders) == 0                      # existing position untouched
