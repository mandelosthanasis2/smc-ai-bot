"""
tests/test_strategy_b.py
════════════════════════
Unit tests for Strategy B (strategies/strategy_b.py) — 1H Box + 15m RSI.

Strategy B was moved out of bot.py into its own module (Phase 2 refactor)
following the dependency-injection pattern used by A / CM / SMC. These tests
pin down the pre-existing behaviour so the structural move cannot silently
change the trading logic. B's parameters (RSI 70 / R:R 2.0) are off-limits
per the handoff — the entry tests assert that the 2:1 reward:risk geometry
is preserved exactly.

Two areas are covered:

1. **2-phase trailing exit** (``check_position``):
     • Phase 1 (≥50% to TP) → stop moves to break-even
     • Phase 2 (TP hit)     → trailing stop activates, floored at TP
       (or, if trailing_enabled is False, closes at TP as a WIN)
     • trailing hit → WIN; plain SL / break-even classification

2. **Entry wiring** (``on_tick``): a clean short/long setup opens a position
   with R/R 2:1 (sl_dist = tp_dist / 2) and the deps contract wired.
"""

import contextlib

import pytest

from strategies import strategy_b as B
from tests.conftest import OrderRecorder


# ── exit-path deps ────────────────────────────────────────────────────────

def _exit_deps(recorder):
    return {
        "finalize": recorder.finalize,
        "send_telegram": recorder.send_telegram,
        "save_state": recorder.save_state,
    }


def _open_long(qty=1.0, **over):
    # entry 100_000, tp 101_000 (tp_dist 1_000), sl 99_500 (R/R 2:1)
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
        # progress = 0.50 → break-even (price not yet at TP, so position holds)
        B.check_position(_exit_deps(rec), fresh_state, 100_500.0)

        pos = fresh_state["position"]
        assert pos is not None
        assert pos["phase1_done"] is True
        assert pos["sl"] == pos["entry"]

    def test_tp_hit_activates_trailing_floored_at_tp(self, fresh_state):
        fresh_state["position"] = _open_long(phase1_done=True, sl=100_000.0)
        rec = OrderRecorder(fresh_state)
        B.check_position(_exit_deps(rec), fresh_state, 101_000.0)  # at TP

        pos = fresh_state["position"]
        assert pos is not None
        assert pos["trailing_active"] is True
        assert pos["trailing_sl"] == 101_000.0          # floor = TP

    def test_trailing_disabled_takes_profit_at_tp(self, fresh_state):
        fresh_state["position"] = _open_long(phase1_done=True, sl=100_000.0)
        fresh_state["trailing_enabled"] = False
        rec = OrderRecorder(fresh_state)
        B.check_position(_exit_deps(rec), fresh_state, 101_000.0)  # at TP

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
        # advance: peak → 102_000, trailing_sl → 102_000*0.997 = 101_694
        B.check_position(deps, fresh_state, 102_000.0)
        assert fresh_state["position"]["trailing_sl"] == pytest.approx(101_694.0)
        # pull back to the trailing stop → WIN
        B.check_position(deps, fresh_state, 101_690.0)

        assert fresh_state["position"] is None
        assert rec.finals[-1]["result"] == "WIN"
        assert rec.finals[-1]["note"].startswith("TRAILING STOP")

    def test_short_trailing_floored_at_tp(self, fresh_state):
        fresh_state["position"] = _open_short(phase1_done=True, sl=100_000.0)
        rec = OrderRecorder(fresh_state)
        B.check_position(_exit_deps(rec), fresh_state, 99_000.0)  # at TP

        pos = fresh_state["position"]
        assert pos["trailing_active"] is True
        assert pos["trailing_sl"] == 99_000.0           # ceiling = TP for SHORT

    def test_plain_stop_loss_is_a_loss(self, fresh_state):
        fresh_state["position"] = _open_long()
        rec = OrderRecorder(fresh_state)
        B.check_position(_exit_deps(rec), fresh_state, 99_500.0)  # hit SL

        assert fresh_state["position"] is None
        assert rec.finals[-1]["result"] == "LOSS"
        assert rec.finals[-1]["note"] == "STOP LOSS"

    def test_break_even_pullback_is_not_a_loss(self, fresh_state):
        fresh_state["position"] = _open_long(phase1_done=True, sl=100_000.0)
        rec = OrderRecorder(fresh_state)
        B.check_position(_exit_deps(rec), fresh_state, 100_000.0)  # back to entry

        assert fresh_state["position"] is None
        assert rec.finals[-1]["result"] == "BREAK EVEN"
        assert fresh_state["losses"] == 0


# ── entry wiring (on_tick) ────────────────────────────────────────────────

class _FakeRT:
    """Minimal realtime stand-in with the attributes on_tick reads."""

    def __init__(self, price=100_000.0, rsi_15m=75.0, rsi_1h=60.0):
        self.price = price
        self.rsi_15m = rsi_15m
        self.rsi_1h = rsi_1h
        self.initialized = True
        self.lock = contextlib.nullcontext()
        self.closes_15m = [price] * 30


def _entry_deps(rec, rt, box, **over):
    deps = {
        "rt": rt,
        "get_candles": lambda gran, limit: [
            {"high": 100_000.0, "low": 99_000.0, "close": 99_500.0} for _ in range(limit)
        ],
        "build_1h_box": lambda c1h: box,
        "detect_divergence": lambda closes, highs, lows: (False, False),
        "calc_qty": lambda bal, risk, entry, sl: 0.5,
        "place_order": rec.place_order,
        "place_order_live": lambda *a, **k: None,
        "send_telegram": rec.send_telegram,
        "ai_validate": lambda **k: ("GO", 1.0, None),
        "finalize": rec.finalize,
        "save_state": rec.save_state,
        "send_ai_summary": lambda *a, **k: None,
        "trading_mode": "PAPER",
        "risk_per_trade": 0.02,
        "ai_shadow_master": True,
    }
    deps.update(over)
    return deps


@pytest.mark.strategy
class TestEntryWiring:
    def setup_method(self):
        # reset the module-level race guard between tests
        B._entering = False

    def test_short_setup_opens_position_with_rr_2to1(self, fresh_state):
        rec = OrderRecorder(fresh_state)
        rt = _FakeRT(price=100_000.0, rsi_15m=75.0)              # RSI > 70 at 1H high
        box = {"high": 100_000.0, "low": 96_000.0, "mid": 98_000.0}
        B.on_tick(_entry_deps(rec, rt, box), fresh_state, 100_000.0)

        pos = fresh_state["position"]
        assert pos is not None
        assert pos["type"] == "SHORT"
        assert pos["entry"] == 100_000.0
        assert pos["tp"] == 98_000.0                             # box mid
        # R/R 2:1 — sl_dist is half the tp_dist (2_000 / 2 = 1_000 above entry)
        assert pos["sl"] == 101_000.0
        reward = abs(pos["entry"] - pos["tp"])
        risk = abs(pos["sl"] - pos["entry"])
        assert reward == pytest.approx(2 * risk)
        assert B._entering is False                             # guard released

    def test_long_setup_opens_position_with_rr_2to1(self, fresh_state):
        rec = OrderRecorder(fresh_state)
        rt = _FakeRT(price=100_000.0, rsi_15m=25.0)              # RSI < 30 at 1H low
        box = {"high": 104_000.0, "low": 100_000.0, "mid": 102_000.0}
        B.on_tick(_entry_deps(rec, rt, box), fresh_state, 100_000.0)

        pos = fresh_state["position"]
        assert pos is not None
        assert pos["type"] == "LONG"
        assert pos["tp"] == 102_000.0
        assert pos["sl"] == 99_000.0                            # 1_000 below entry
        reward = abs(pos["tp"] - pos["entry"])
        risk = abs(pos["entry"] - pos["sl"])
        assert reward == pytest.approx(2 * risk)

    def test_ai_skip_blocks_entry_and_releases_guard(self, fresh_state):
        rec = OrderRecorder(fresh_state)
        rt = _FakeRT(price=100_000.0, rsi_15m=75.0)
        box = {"high": 100_000.0, "low": 96_000.0, "mid": 98_000.0}
        deps = _entry_deps(rec, rt, box, ai_validate=lambda **k: ("SKIP", 1.0, None))
        B.on_tick(deps, fresh_state, 100_000.0)

        assert fresh_state["position"] is None
        assert len(rec.orders) == 0
        assert B._entering is False

    def test_no_signal_when_rsi_neutral(self, fresh_state):
        rec = OrderRecorder(fresh_state)
        rt = _FakeRT(price=100_000.0, rsi_15m=50.0)
        box = {"high": 100_000.0, "low": 96_000.0, "mid": 98_000.0}
        B.on_tick(_entry_deps(rec, rt, box), fresh_state, 100_000.0)

        assert fresh_state["position"] is None
        assert fresh_state["last_signal"].startswith("WAIT")
