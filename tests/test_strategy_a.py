"""
tests/test_strategy_a.py
════════════════════════
Unit tests for Strategy A (strategies/strategy_a.py) — Daily Box + 1H RSI.

Strategy A was moved out of bot.py into its own module (Phase 2 refactor)
following the dependency-injection pattern used by CM and SMC. These tests
are the regression guard for that move: they pin down the behaviour that
existed before so a future change to the structure cannot silently alter the
trading logic.

Two areas are covered:

1. **4-phase trailing exit** (``check_position``):
     • Phase 1 (≥50% to TP) → stop moves to break-even
     • Phase 2 (≥70% to TP) → 30% partial close (balance credited directly)
     • Phase 3 (past TP)     → trailing stop activates, floored at TP
     • Phase 4 (trailing hit)→ remainder closed as WIN
     • plain SL / break-even pull-back classification

2. **Entry wiring** (``on_tick``): a clean SHORT setup at the PDH opens a
   position with the expected entry/SL/TP, proving the deps contract is wired.
"""

import contextlib

import pytest

from strategies import strategy_a as A
from tests.conftest import OrderRecorder


# ── exit-path deps ────────────────────────────────────────────────────────

def _exit_deps(recorder, trading_mode="PAPER"):
    return {
        "finalize": recorder.finalize,
        "send_telegram": recorder.send_telegram,
        "save_state": recorder.save_state,
        "close_position_live": lambda side, qty: None,
        "trading_mode": trading_mode,
    }


def _open_long(qty=1.0, **over):
    pos = {
        "type": "LONG", "entry": 100_000.0, "sl": 99_000.0,
        "tp": 101_000.0, "qty": qty,
    }
    pos.update(over)
    return pos


def _open_short(qty=1.0, **over):
    pos = {
        "type": "SHORT", "entry": 100_000.0, "sl": 101_000.0,
        "tp": 99_000.0, "qty": qty,
    }
    pos.update(over)
    return pos


# ── 4-phase trailing exit ─────────────────────────────────────────────────

@pytest.mark.strategy
class TestFourPhaseExit:
    def test_phase1_moves_stop_to_break_even(self, fresh_state):
        fresh_state["position"] = _open_long()
        rec = OrderRecorder(fresh_state)
        # progress = 0.50 (price 100_500, tp_dist 1_000)
        A.check_position(_exit_deps(rec), fresh_state, 100_500.0)

        pos = fresh_state["position"]
        assert pos is not None
        assert pos["phase1_done"] is True
        assert pos["sl"] == pos["entry"]

    def test_phase2_closes_30_percent_and_credits_balance(self, fresh_state):
        fresh_state["position"] = _open_long()
        rec = OrderRecorder(fresh_state)
        # progress = 0.70 (price 100_700) → phase 1 AND phase 2 in one call
        A.check_position(_exit_deps(rec), fresh_state, 100_700.0)

        pos = fresh_state["position"]
        assert pos["phase2_done"] is True
        assert pos["qty"] == pytest.approx(0.70)          # 30% closed
        # partial PnL = (100_700 - 100_000) * 0.30 = 210, credited directly
        assert fresh_state["balance"] == pytest.approx(10_210.0)
        assert fresh_state["pnl_total"] == pytest.approx(210.0)

    def test_phase3_activates_trailing_floored_at_tp(self, fresh_state):
        fresh_state["position"] = _open_long(phase1_done=True, phase2_done=True)
        rec = OrderRecorder(fresh_state)
        # price exactly at TP → trailing activates, floored at TP (not below)
        A.check_position(_exit_deps(rec), fresh_state, 101_000.0)

        pos = fresh_state["position"]
        assert pos["trailing_active"] is True
        assert pos["trailing_sl"] == 101_000.0            # floor = TP

    def test_phase4_trailing_advances_then_closes_as_win(self, fresh_state):
        fresh_state["position"] = _open_long(
            phase1_done=True, phase2_done=True,
            trailing_active=True, trailing_peak=101_000.0, trailing_sl=101_000.0,
        )
        rec = OrderRecorder(fresh_state)
        deps = _exit_deps(rec)
        # advance: peak → 102_000, trailing_sl → 102_000*0.997 = 101_694
        A.check_position(deps, fresh_state, 102_000.0)
        assert fresh_state["position"]["trailing_sl"] == pytest.approx(101_694.0)
        # pull back to the trailing stop → WIN
        A.check_position(deps, fresh_state, 101_690.0)

        assert fresh_state["position"] is None
        assert rec.finals[-1]["result"] == "WIN"
        assert rec.finals[-1]["note"].startswith("TRAILING STOP")

    def test_trailing_never_drops_below_tp(self, fresh_state):
        fresh_state["position"] = _open_long(
            phase1_done=True, phase2_done=True,
            trailing_active=True, trailing_peak=101_000.0, trailing_sl=101_000.0,
        )
        rec = OrderRecorder(fresh_state)
        # tiny advance whose raw trailing (100_xxx) would fall below TP →
        # must be floored at TP, so no stop-out here.
        A.check_position(_exit_deps(rec), fresh_state, 101_050.0)
        pos = fresh_state["position"]
        assert pos is not None
        assert pos["trailing_sl"] >= pos["tp"]

    def test_short_trailing_floored_at_tp(self, fresh_state):
        fresh_state["position"] = _open_short(phase1_done=True, phase2_done=True)
        rec = OrderRecorder(fresh_state)
        A.check_position(_exit_deps(rec), fresh_state, 99_000.0)  # at TP

        pos = fresh_state["position"]
        assert pos["trailing_active"] is True
        assert pos["trailing_sl"] == 99_000.0             # ceiling = TP for SHORT

    def test_plain_stop_loss_is_a_loss(self, fresh_state):
        fresh_state["position"] = _open_long()
        rec = OrderRecorder(fresh_state)
        A.check_position(_exit_deps(rec), fresh_state, 99_000.0)  # hit SL

        assert fresh_state["position"] is None
        assert rec.finals[-1]["result"] == "LOSS"
        assert rec.finals[-1]["note"] == "STOP LOSS"

    def test_break_even_pullback_is_not_a_loss(self, fresh_state):
        # phase 1 already moved the stop to entry; price falls back to entry.
        fresh_state["position"] = _open_long(phase1_done=True, sl=100_000.0)
        rec = OrderRecorder(fresh_state)
        A.check_position(_exit_deps(rec), fresh_state, 100_000.0)

        assert fresh_state["position"] is None
        assert rec.finals[-1]["result"] == "BREAK EVEN"
        assert fresh_state["losses"] == 0


# ── entry wiring (on_tick) ────────────────────────────────────────────────

class _FakeRT:
    """Minimal realtime stand-in with the attributes on_tick reads."""

    def __init__(self, price=100_000.0, rsi_1h=75.0, rsi_15m=75.0):
        self.price = price
        self.rsi_1h = rsi_1h
        self.rsi_15m = rsi_15m
        self.initialized = True
        self.lock = contextlib.nullcontext()
        self.closes_1h = [price] * 30


def _entry_deps(rec, rt, **over):
    deps = {
        "rt": rt,
        "get_candles": lambda gran, limit: [
            {"high": 100_000.0, "low": 99_000.0, "close": 99_500.0} for _ in range(limit)
        ],
        "build_daily_box": lambda c4h: {"high": 100_000.0, "low": 95_000.0, "mid": 99_000.0},
        "detect_divergence": lambda closes, highs, lows: (False, False),
        "find_4h_sr": lambda c4h, price: (98_000.0, 100_200.0),
        "get_balance": lambda: 10_000.0,
        "calc_qty": lambda bal, risk, entry, sl: 0.5,
        "place_order": rec.place_order,
        "place_order_live": lambda *a, **k: None,
        "close_position_live": lambda side, qty: None,
        "fetch_news": lambda: [],
        "ai_news_score": lambda headlines, side, price, box: (0, ""),
        "send_telegram": rec.send_telegram,
        "ai_validate": lambda **k: ("GO", 1.0, None),
        "finalize": rec.finalize,
        "save_state": rec.save_state,
        "send_ai_summary": lambda *a, **k: None,
        "trading_mode": "PAPER",
        "risk_per_trade": 0.02,
        "ai_shadow_mode": True,
        "ai_shadow_master": True,
    }
    deps.update(over)
    return deps


@pytest.mark.strategy
class TestEntryWiring:
    def test_short_setup_at_pdh_opens_position(self, fresh_state):
        rec = OrderRecorder(fresh_state)
        rt = _FakeRT(price=100_000.0, rsi_1h=75.0)  # RSI > 70 at the PDH
        A.on_tick(_entry_deps(rec, rt), fresh_state, 100_000.0)

        pos = fresh_state["position"]
        assert pos is not None
        assert pos["type"] == "SHORT"
        assert pos["entry"] == 100_000.0
        assert pos["tp"] == 99_000.0                       # box mid
        assert pos["sl"] == round(100_200.0 * 1.003, 2)    # resistance * 1.003
        assert pos["sl"] > pos["entry"] > pos["tp"]
        assert len(rec.orders) == 1

    def test_ai_skip_blocks_entry(self, fresh_state):
        rec = OrderRecorder(fresh_state)
        rt = _FakeRT(price=100_000.0, rsi_1h=75.0)
        deps = _entry_deps(rec, rt, ai_validate=lambda **k: ("SKIP", 1.0, None))
        A.on_tick(deps, fresh_state, 100_000.0)

        assert fresh_state["position"] is None
        assert len(rec.orders) == 0

    def test_no_signal_when_rsi_neutral(self, fresh_state):
        rec = OrderRecorder(fresh_state)
        rt = _FakeRT(price=100_000.0, rsi_1h=50.0)         # no PDH short, no PDL long
        A.on_tick(_entry_deps(rec, rt), fresh_state, 100_000.0)

        assert fresh_state["position"] is None
        assert fresh_state["last_signal"].startswith("WAIT")
