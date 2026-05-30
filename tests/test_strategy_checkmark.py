"""
tests/test_strategy_checkmark.py
════════════════════════════════
Unit tests for the Check Mark strategy (strategies/strategy_checkmark.py).

The focus here is twofold:

1. **TP ordering** — a regression guard for the bug where the "near" and
   "far" take-profit levels could come out inverted (TP2 closer than TP1).
   The fix sorts the two candidate targets so that, for a LONG,
   ``entry < TP1 < TP2`` always holds (and the mirror for a SHORT).

2. **2-phase exit** — TP1 closes 50% and moves the stop to break-even,
   TP2 closes the remainder, and a pull-back to the moved stop is recorded
   as BREAK EVEN rather than a loss.
"""

import pytest

from strategies import strategy_checkmark as cm
from tests.conftest import OrderRecorder


def _exit_deps(recorder):
    return {
        "finalize": recorder.finalize,
        "finalize_partial": recorder.finalize_partial,
        "send_telegram": recorder.send_telegram,
        "save_state": recorder.save_state,
    }


# ── TP ordering (regression for the inverted-TP bug) ──────────────────────

@pytest.mark.strategy
class TestTakeProfitOrdering:
    def test_long_targets_are_sorted_near_then_far(self):
        # Reproduces the dashboard scenario: day_high is far, projection is near.
        check = {
            "side": "LONG", "open_price": 72_950.0, "blowoff_level": 72_400.0,
            "day_high": 75_388.0, "day_low": 72_000.0,
        }
        entry = cm._build_entry(check, 72_746.80, cm.CONFIG)
        assert entry["entry"] < entry["tp1"] < entry["tp2"]
        # primary TP (where 50% closes) must be the near target = TP1
        assert entry["tp"] == entry["tp1"]

    def test_short_targets_are_sorted_near_then_far(self):
        check = {
            "side": "SHORT", "open_price": 72_950.0, "blowoff_level": 73_500.0,
            "day_high": 74_000.0, "day_low": 71_000.0,
        }
        entry = cm._build_entry(check, 73_200.0, cm.CONFIG)
        assert entry["entry"] > entry["tp1"] > entry["tp2"]
        assert entry["tp"] == entry["tp1"]

    def test_long_stop_is_below_entry(self):
        check = {
            "side": "LONG", "open_price": 72_950.0, "blowoff_level": 72_400.0,
            "day_high": 75_388.0, "day_low": 72_000.0,
        }
        entry = cm._build_entry(check, 72_746.80, cm.CONFIG)
        assert entry["sl"] < entry["entry"]

    def test_short_stop_is_above_entry(self):
        check = {
            "side": "SHORT", "open_price": 72_950.0, "blowoff_level": 73_500.0,
            "day_high": 74_000.0, "day_low": 71_000.0,
        }
        entry = cm._build_entry(check, 73_200.0, cm.CONFIG)
        assert entry["sl"] > entry["entry"]


# ── 2-phase exit lifecycle ────────────────────────────────────────────────

@pytest.mark.strategy
class TestTwoPhaseExit:
    def _open_long(self, qty=0.5):
        return {
            "type": "LONG", "entry": 72_746.80, "sl": 72_400.0,
            "tp1": 73_296.80, "tp2": 75_388.0, "qty": qty, "phase1_done": False,
        }

    def test_tp1_closes_half_and_sets_breakeven(self, fresh_state):
        fresh_state["position"] = self._open_long()
        rec = OrderRecorder(fresh_state)
        cm._manage_position(_exit_deps(rec), fresh_state, 73_296.80)

        pos = fresh_state["position"]
        assert pos is not None
        assert pos["phase1_done"] is True
        assert pos["sl"] == pos["entry"]
        assert pos["qty"] == pytest.approx(0.25)
        assert len(rec.partials) == 1

    def test_tp2_closes_remainder_as_win(self, fresh_state):
        fresh_state["position"] = self._open_long()
        rec = OrderRecorder(fresh_state)
        deps = _exit_deps(rec)
        cm._manage_position(deps, fresh_state, 73_296.80)  # TP1
        cm._manage_position(deps, fresh_state, 75_388.0)   # TP2

        assert fresh_state["position"] is None
        assert rec.finals[-1]["result"] == "WIN"
        assert rec.finals[-1]["note"] == "TP2"

    def test_pullback_to_breakeven_is_not_a_loss(self, fresh_state):
        fresh_state["position"] = self._open_long()
        rec = OrderRecorder(fresh_state)
        deps = _exit_deps(rec)
        cm._manage_position(deps, fresh_state, 73_296.80)   # TP1 → SL to BE
        cm._manage_position(deps, fresh_state, 72_746.80)   # back to entry

        assert fresh_state["position"] is None
        assert rec.finals[-1]["result"] == "BREAK EVEN"
        assert fresh_state["losses"] == 0

    def test_stop_loss_before_tp1_is_a_loss(self, fresh_state):
        fresh_state["position"] = self._open_long()
        rec = OrderRecorder(fresh_state)
        cm._manage_position(_exit_deps(rec), fresh_state, 72_400.0)  # hit SL

        assert fresh_state["position"] is None
        assert rec.finals[-1]["result"] == "LOSS"
