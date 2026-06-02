"""
tests/test_strategy_b.py
════════════════════════
Unit tests for Strategy B (strategies/strategy_b.py) — 1H Box + 15m RSI, v2.

The Strategy-B refactor (HANDOFF) turned B into a multi-position strategy:
  • state["position"] (one dict)  → state["positions"] (list, max 3)
  • break-even removed            → only the 0.3% trailing remains
  • entries gated to candle close → one evaluation per closed 15m candle
  • risk 0.5% base (×2 on divergence)
  • causal ±5 swing divergence

These tests pin the new behaviour. B's parameters (RSI 70 / R:R 2.0) stay
off-limits per the handoff — the entry tests assert the 2:1 geometry exactly.
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


def _with_positions(state, *positions):
    state["positions"] = list(positions)
    state["position"] = positions[0] if positions else None
    return state


# ── per-position trailing exit (NO break-even) ────────────────────────────

@pytest.mark.strategy
class TestTrailingExit:
    def test_no_break_even_at_50pct(self, fresh_state):
        # v2 removed break-even: reaching 50% to TP must NOT move the stop.
        _with_positions(fresh_state, _open_long())
        rec = OrderRecorder(fresh_state)
        B.check_position(_exit_deps(rec), fresh_state, 100_500.0)  # 50% to TP

        pos = fresh_state["positions"][0]
        assert "phase1_done" not in pos
        assert pos["sl"] == 99_500.0            # stop unchanged (no BE)
        assert not pos.get("trailing_active")

    def test_tp_hit_activates_trailing_floored_at_tp(self, fresh_state):
        _with_positions(fresh_state, _open_long())
        rec = OrderRecorder(fresh_state)
        B.check_position(_exit_deps(rec), fresh_state, 101_000.0)  # at TP

        pos = fresh_state["positions"][0]
        assert pos["trailing_active"] is True
        assert pos["trailing_sl"] == 101_000.0          # floor = TP

    def test_trailing_disabled_takes_profit_at_tp(self, fresh_state):
        _with_positions(fresh_state, _open_long())
        fresh_state["trailing_enabled"] = False
        rec = OrderRecorder(fresh_state)
        B.check_position(_exit_deps(rec), fresh_state, 101_000.0)  # at TP

        assert fresh_state["positions"] == []
        assert rec.finals[-1]["result"] == "WIN"
        assert rec.finals[-1]["note"] == "TAKE PROFIT"

    def test_trailing_advances_then_closes_as_win(self, fresh_state):
        _with_positions(fresh_state, _open_long(
            trailing_active=True, trailing_peak=101_000.0, trailing_sl=101_000.0,
        ))
        rec = OrderRecorder(fresh_state)
        deps = _exit_deps(rec)
        # advance: peak → 102_000, trailing_sl → 102_000*0.997 = 101_694
        B.check_position(deps, fresh_state, 102_000.0)
        assert fresh_state["positions"][0]["trailing_sl"] == pytest.approx(101_694.0)
        # pull back to the trailing stop → WIN
        B.check_position(deps, fresh_state, 101_690.0)

        assert fresh_state["positions"] == []
        assert rec.finals[-1]["result"] == "WIN"
        assert rec.finals[-1]["note"].startswith("TRAILING STOP")

    def test_short_trailing_floored_at_tp(self, fresh_state):
        _with_positions(fresh_state, _open_short())
        rec = OrderRecorder(fresh_state)
        B.check_position(_exit_deps(rec), fresh_state, 99_000.0)  # at TP

        pos = fresh_state["positions"][0]
        assert pos["trailing_active"] is True
        assert pos["trailing_sl"] == 99_000.0           # ceiling = TP for SHORT

    def test_plain_stop_loss_is_a_loss(self, fresh_state):
        _with_positions(fresh_state, _open_long())
        rec = OrderRecorder(fresh_state)
        B.check_position(_exit_deps(rec), fresh_state, 99_500.0)  # hit SL

        assert fresh_state["positions"] == []
        assert rec.finals[-1]["result"] == "LOSS"
        assert rec.finals[-1]["note"] == "STOP LOSS"


# ── multi-position management ─────────────────────────────────────────────

@pytest.mark.strategy
class TestMultiPosition:
    def test_each_position_closes_independently(self, fresh_state):
        # one LONG at TP (→ trailing) and one SHORT hitting its stop (→ loss).
        long_pos = _open_long()
        short_pos = _open_short()
        _with_positions(fresh_state, long_pos, short_pos)
        rec = OrderRecorder(fresh_state)
        # price 101_000: LONG hits TP (trails, stays open); SHORT hits SL (closes)
        B.check_position(_exit_deps(rec), fresh_state, 101_000.0)

        assert long_pos in fresh_state["positions"]
        assert short_pos not in fresh_state["positions"]
        assert long_pos.get("trailing_active") is True
        assert rec.finals[-1]["result"] == "LOSS"

    def test_legacy_mirror_tracks_first_open_position(self, fresh_state):
        a, b = _open_long(), _open_short()
        _with_positions(fresh_state, a, b)
        rec = OrderRecorder(fresh_state)
        # 100_000 is inside both stops/targets → nothing triggers
        B.check_position(_exit_deps(rec), fresh_state, 100_000.0)
        # compat mirror = first open position (dashboard/DB still read it)
        assert fresh_state["position"] is a


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


def _candles(n, ts=1000):
    # last element (index -1) is the forming candle; [-2] is the last CLOSED one,
    # whose "time" drives the candle-close gate.
    return [
        {"high": 100_000.0, "low": 99_000.0, "close": 99_500.0, "time": ts + i}
        for i in range(n)
    ]


def _entry_deps(rec, rt, box, **over):
    deps = {
        "rt": rt,
        "get_candles": lambda gran, limit: _candles(limit),
        "build_1h_box": lambda c1h: box,
        "detect_divergence": lambda closes, highs, lows: (False, False),
        "calc_qty": lambda bal, risk, entry, sl: 0.5,
        # close-candle RSI: echo rt.rsi_15m so tests keep controlling RSI via rt
        "calc_rsi": lambda closes: rt.rsi_15m,
        "place_order": rec.place_order,
        "place_order_live": lambda *a, **k: None,
        "send_telegram": rec.send_telegram,
        "ai_validate": lambda **k: ("GO", 1.0, None),
        "finalize": rec.finalize,
        "save_state": rec.save_state,
        "send_ai_summary": lambda *a, **k: None,
        "trading_mode": "PAPER",
        "risk_per_trade": 0.005,
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

        assert len(fresh_state["positions"]) == 1
        pos = fresh_state["positions"][0]
        assert pos["type"] == "SHORT"
        assert pos["entry"] == 100_000.0
        assert pos["tp"] == 98_000.0                             # box mid
        # R/R 2:1 — sl_dist is half the tp_dist (2_000 / 2 = 1_000 above entry)
        assert pos["sl"] == 101_000.0
        assert abs(pos["entry"] - pos["tp"]) == pytest.approx(2 * abs(pos["sl"] - pos["entry"]))
        assert B._entering is False                             # guard released
        assert fresh_state["position"] is pos                  # compat mirror

    def test_long_setup_opens_position_with_rr_2to1(self, fresh_state):
        rec = OrderRecorder(fresh_state)
        rt = _FakeRT(price=100_000.0, rsi_15m=25.0)              # RSI < 30 at 1H low
        box = {"high": 104_000.0, "low": 100_000.0, "mid": 102_000.0}
        B.on_tick(_entry_deps(rec, rt, box), fresh_state, 100_000.0)

        pos = fresh_state["positions"][0]
        assert pos["type"] == "LONG"
        assert pos["tp"] == 102_000.0
        assert pos["sl"] == 99_000.0                            # 1_000 below entry
        assert abs(pos["tp"] - pos["entry"]) == pytest.approx(2 * abs(pos["entry"] - pos["sl"]))

    def test_ai_skip_blocks_entry_and_releases_guard(self, fresh_state):
        rec = OrderRecorder(fresh_state)
        rt = _FakeRT(price=100_000.0, rsi_15m=75.0)
        box = {"high": 100_000.0, "low": 96_000.0, "mid": 98_000.0}
        deps = _entry_deps(rec, rt, box, ai_validate=lambda **k: ("SKIP", 1.0, None))
        B.on_tick(deps, fresh_state, 100_000.0)

        assert fresh_state["positions"] == []
        assert len(rec.orders) == 0
        assert B._entering is False

    def test_no_signal_when_rsi_neutral(self, fresh_state):
        rec = OrderRecorder(fresh_state)
        rt = _FakeRT(price=100_000.0, rsi_15m=50.0)
        box = {"high": 100_000.0, "low": 96_000.0, "mid": 98_000.0}
        B.on_tick(_entry_deps(rec, rt, box), fresh_state, 100_000.0)

        assert fresh_state["positions"] == []
        assert fresh_state["last_signal"].startswith("WAIT")

    def test_entry_uses_closed_candle_rsi_not_live(self, fresh_state):
        # live rt.rsi_15m is neutral (50) — would NOT trigger — but the closed
        # candle RSI (via calc_rsi) is 75 → SHORT must fire off the closed value.
        rec = OrderRecorder(fresh_state)
        rt = _FakeRT(price=100_000.0, rsi_15m=50.0)
        box = {"high": 100_000.0, "low": 96_000.0, "mid": 98_000.0}
        deps = _entry_deps(rec, rt, box, calc_rsi=lambda closes: 75.0)
        B.on_tick(deps, fresh_state, 100_000.0)

        assert len(fresh_state["positions"]) == 1
        assert fresh_state["positions"][0]["type"] == "SHORT"

    def test_live_rsi_alone_does_not_trigger(self, fresh_state):
        # opposite: live RSI hot (75) but closed-candle RSI neutral (50) → no entry
        rec = OrderRecorder(fresh_state)
        rt = _FakeRT(price=100_000.0, rsi_15m=75.0)
        box = {"high": 100_000.0, "low": 96_000.0, "mid": 98_000.0}
        deps = _entry_deps(rec, rt, box, calc_rsi=lambda closes: 50.0)
        B.on_tick(deps, fresh_state, 100_000.0)

        assert fresh_state["positions"] == []
        assert fresh_state["last_signal"].startswith("WAIT")

    def test_divergence_doubles_risk(self, fresh_state):
        # bearish divergence on a SHORT setup → risk passed to calc_qty is 2× base
        seen = {}
        rec = OrderRecorder(fresh_state)
        rt = _FakeRT(price=100_000.0, rsi_15m=75.0)
        box = {"high": 100_000.0, "low": 96_000.0, "mid": 98_000.0}

        def spy_calc_qty(bal, risk, entry, sl):
            seen["risk"] = risk
            return 0.5

        deps = _entry_deps(
            rec, rt, box,
            calc_qty=spy_calc_qty,
            detect_divergence=lambda closes, highs, lows: (False, True),  # bearish
        )
        B.on_tick(deps, fresh_state, 100_000.0)

        assert seen["risk"] == pytest.approx(0.01)        # 0.005 × 2
        assert fresh_state["positions"][0]["has_divergence"] is True


# ── candle-close gate + concurrency cap ───────────────────────────────────

@pytest.mark.strategy
class TestCandleCloseGate:
    def setup_method(self):
        B._entering = False

    def test_only_one_entry_per_closed_candle(self, fresh_state):
        rec = OrderRecorder(fresh_state)
        rt = _FakeRT(price=100_000.0, rsi_15m=75.0)
        box = {"high": 100_000.0, "low": 96_000.0, "mid": 98_000.0}
        deps = _entry_deps(rec, rt, box)  # candles share the same [-2] timestamp

        B.on_tick(deps, fresh_state, 100_000.0)   # new candle → opens #1
        B.on_tick(deps, fresh_state, 100_000.0)   # same candle → gated, no #2

        assert len(fresh_state["positions"]) == 1

    def test_new_candle_allows_re_entry(self, fresh_state):
        rec = OrderRecorder(fresh_state)
        rt = _FakeRT(price=100_000.0, rsi_15m=75.0)
        box = {"high": 100_000.0, "low": 96_000.0, "mid": 98_000.0}

        deps1 = _entry_deps(rec, rt, box, get_candles=lambda g, l: _candles(l, ts=1000))
        B.on_tick(deps1, fresh_state, 100_000.0)  # candle A → #1
        deps2 = _entry_deps(rec, rt, box, get_candles=lambda g, l: _candles(l, ts=2000))
        B.on_tick(deps2, fresh_state, 100_000.0)  # candle B → #2

        assert len(fresh_state["positions"]) == 2

    def test_cap_blocks_fourth_position(self, fresh_state):
        rec = OrderRecorder(fresh_state)
        rt = _FakeRT(price=100_000.0, rsi_15m=75.0)
        box = {"high": 100_000.0, "low": 96_000.0, "mid": 98_000.0}
        # pre-fill 3 open positions (the cap)
        _with_positions(fresh_state, _open_short(), _open_short(), _open_short())

        deps = _entry_deps(rec, rt, box, get_candles=lambda g, l: _candles(l, ts=9000))
        B.on_tick(deps, fresh_state, 100_000.0)

        assert len(fresh_state["positions"]) == 3          # unchanged
        assert fresh_state["last_signal"].startswith("CAP")


# ── load migration (_ensure_positions) ───────────────────────────────────

@pytest.mark.strategy
class TestEnsurePositions:
    def test_none_with_legacy_position_migrates(self):
        pos = _open_long()
        st = {"position": pos}                    # no "positions" key (old JSON)
        B._ensure_positions(st)
        assert st["positions"] == [pos]

    def test_empty_list_with_legacy_position_migrates(self):
        # old DB row: positions column NULL -> loader gives [], but position set
        pos = _open_short()
        st = {"position": pos, "positions": []}
        B._ensure_positions(st)
        assert st["positions"] == [pos]

    def test_empty_list_no_legacy_stays_empty(self):
        st = {"position": None, "positions": []}
        B._ensure_positions(st)
        assert st["positions"] == []

    def test_existing_list_is_preserved(self):
        a, b = _open_long(), _open_short()
        st = {"position": a, "positions": [a, b]}
        B._ensure_positions(st)
        assert st["positions"] == [a, b]


# ── causal ±5 swing divergence (pure function) ────────────────────────────

@pytest.mark.strategy
class TestSwingDivergence:
    def test_bearish_divergence_higher_high_lower_rsi(self):
        # two confirmed swing highs (±2 window): price up, RSI down → bearish
        window = 2
        highs = [10, 11, 12, 11, 10, 11, 13, 11, 10]   # swing highs at idx 2 (12) & 6 (13)
        lows = [9] * len(highs)
        rsi = [50, 55, 70, 60, 50, 55, 65, 55, 50]      # rsi at idx2=70, idx6=65 (lower)
        bull, bear = B.swing_divergence(highs, lows, rsi, window=window)
        assert bear is True
        assert bull is False

    def test_bullish_divergence_lower_low_higher_rsi(self):
        window = 2
        lows = [20, 19, 18, 19, 20, 19, 17, 19, 20]     # swing lows at idx2 (18) & idx6 (17)
        highs = [25] * len(lows)
        rsi = [50, 45, 30, 40, 50, 45, 35, 45, 50]      # rsi idx2=30, idx6=35 (higher)
        bull, bear = B.swing_divergence(highs, lows, rsi, window=window)
        assert bull is True
        assert bear is False

    def test_no_divergence_when_rsi_confirms(self):
        window = 2
        highs = [10, 11, 12, 11, 10, 11, 13, 11, 10]
        lows = [9] * len(highs)
        rsi = [50, 55, 60, 55, 50, 58, 70, 58, 50]      # rsi rises with price → no div
        bull, bear = B.swing_divergence(highs, lows, rsi, window=window)
        assert bear is False
        assert bull is False

    def test_too_short_series_is_safe(self):
        assert B.swing_divergence([1, 2, 3], [1, 2, 3], [50, 50, 50], window=5) == (False, False)
