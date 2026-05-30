"""
tests/test_strategy_smc.py
══════════════════════════
Unit tests for the SMC strategy (strategies/strategy_smc.py).

SMC is a thin, webhook-driven strategy: TradingView sends a fully-formed
signal (side / price / sl / tp1 / tp2 / confluence) and the bot executes it
through a 2-phase exit (TP1 closes 50% and moves the stop to break-even,
TP2 closes the remainder). These tests pin down the level parsing, position
sizing, the de-duplication guard, the AI-validator gate, and the exit
lifecycle.
"""

import pytest

from strategies import strategy_smc
from tests.conftest import OrderRecorder


@pytest.fixture(autouse=True)
def _reset_dedup():
    """Each test starts with the module-level dedup guard cleared."""
    strategy_smc._last_signal_time = 0.0
    yield


def _calc_qty(balance, risk_pct, entry, sl):
    """Mirror of bot.calc_qty so SMC sizing can be tested standalone."""
    dist = abs(entry - sl)
    if dist <= 0:
        return 0.001
    return max(round((balance * risk_pct) / dist, 4), 0.001)


def _deps(recorder, rt, ai_validate=None):
    return {
        "get_price": lambda: rt.price,
        "calc_qty": _calc_qty,
        "place_order": recorder.place_order,
        "send_telegram": recorder.send_telegram,
        "ai_validate": ai_validate,
        "save_state": recorder.save_state,
        "rt": rt,
    }


# ── Level parsing ─────────────────────────────────────────────────────────

@pytest.mark.unit
class TestParseLevels:
    def test_uses_pine_supplied_levels(self):
        data = {"sl": "99000", "tp1": "102000", "tp2": "103000"}
        sl, tp1, tp2 = strategy_smc._parse_levels(data, "LONG", 100_000.0, strategy_smc.CONFIG)
        assert (sl, tp1, tp2) == (99000.0, 102000.0, 103000.0)

    def test_falls_back_when_levels_missing(self):
        # No sl/tp provided → fallback to %/RR based levels, never zero.
        sl, tp1, tp2 = strategy_smc._parse_levels({}, "LONG", 100_000.0, strategy_smc.CONFIG)
        assert sl < 100_000 < tp1 < tp2

    def test_short_levels_are_inverted(self):
        sl, tp1, tp2 = strategy_smc._parse_levels({}, "SHORT", 100_000.0, strategy_smc.CONFIG)
        assert sl > 100_000 > tp1 > tp2


# ── Entry / sizing / gating ───────────────────────────────────────────────

@pytest.mark.strategy
class TestEntry:
    def test_long_entry_opens_position_with_correct_levels(self, fresh_state, rt):
        rec = OrderRecorder(fresh_state)
        data = {"signal": "LONG", "price": "100000", "tp1": "102000",
                "tp2": "103000", "sl": "99000", "confluence": "normal"}
        strategy_smc.process_webhook(_deps(rec, rt), fresh_state, "LONG", 100_000.0, data)

        pos = fresh_state["position"]
        assert pos is not None
        assert pos["type"] == "LONG"
        assert (pos["sl"], pos["tp1"], pos["tp2"]) == (99000.0, 102000.0, 103000.0)
        assert pos["phase1_done"] is False
        assert len(rec.orders) == 1

    def test_strong_confluence_doubles_size(self, fresh_state, rt):
        rec = OrderRecorder(fresh_state)
        data = {"signal": "LONG", "price": "100000", "tp1": "102000",
                "tp2": "103000", "sl": "99000", "confluence": "strong"}
        strategy_smc.process_webhook(_deps(rec, rt), fresh_state, "LONG", 100_000.0, data)
        # risk 2% * 2 (strong) = 4% of 10k = 400 / 1000pts risk = 0.4 BTC
        assert fresh_state["position"]["qty"] == pytest.approx(0.4)

    def test_normal_confluence_uses_base_size(self, fresh_state, rt):
        rec = OrderRecorder(fresh_state)
        data = {"signal": "LONG", "price": "100000", "tp1": "102000",
                "tp2": "103000", "sl": "99000", "confluence": "normal"}
        strategy_smc.process_webhook(_deps(rec, rt), fresh_state, "LONG", 100_000.0, data)
        # 2% of 10k = 200 / 1000pts = 0.2 BTC
        assert fresh_state["position"]["qty"] == pytest.approx(0.2)

    def test_no_entry_when_position_already_open(self, fresh_state, rt):
        fresh_state["position"] = {"type": "LONG"}  # already in a trade
        rec = OrderRecorder(fresh_state)
        data = {"signal": "LONG", "price": "100000", "sl": "99000"}
        strategy_smc.process_webhook(_deps(rec, rt), fresh_state, "LONG", 100_000.0, data)
        assert rec.orders == []  # no new order placed


@pytest.mark.strategy
class TestDedup:
    def test_duplicate_signal_within_window_is_ignored(self, fresh_state, rt):
        rec = OrderRecorder(fresh_state)
        data = {"signal": "LONG", "price": "100000", "tp1": "102000",
                "tp2": "103000", "sl": "99000"}
        deps = _deps(rec, rt)
        strategy_smc.process_webhook(deps, fresh_state, "LONG", 100_000.0, data)
        # Second identical signal arrives immediately → must be blocked.
        fresh_state["position"] = None  # pretend the first closed instantly
        strategy_smc.process_webhook(deps, fresh_state, "LONG", 100_000.0, data)
        assert len(rec.orders) == 1


@pytest.mark.strategy
class TestAIGate:
    def _ai(self, action):
        class _Res:
            confidence = 75
            reasoning = {}
            source = "ai_agents"
        return lambda **kw: (action, 1.0, _Res())

    def test_ai_skip_blocks_entry(self, fresh_state, rt):
        rec = OrderRecorder(fresh_state)
        data = {"signal": "LONG", "price": "100000", "tp1": "102000",
                "tp2": "103000", "sl": "99000"}
        deps = _deps(rec, rt, ai_validate=self._ai("SKIP"))
        strategy_smc.process_webhook(deps, fresh_state, "LONG", 100_000.0, data)
        assert fresh_state["position"] is None
        assert rec.orders == []

    def test_ai_go_allows_entry(self, fresh_state, rt):
        rec = OrderRecorder(fresh_state)
        data = {"signal": "LONG", "price": "100000", "tp1": "102000",
                "tp2": "103000", "sl": "99000"}
        deps = _deps(rec, rt, ai_validate=self._ai("GO"))
        strategy_smc.process_webhook(deps, fresh_state, "LONG", 100_000.0, data)
        assert fresh_state["position"] is not None


# ── 2-phase exit lifecycle ────────────────────────────────────────────────

@pytest.mark.strategy
class TestTwoPhaseExit:
    def _open_long(self, qty=0.5):
        return {
            "type": "LONG", "entry": 100_000.0, "sl": 99_000.0,
            "tp1": 102_000.0, "tp2": 103_000.0, "qty": qty, "phase1_done": False,
        }

    def test_tp1_closes_half_and_moves_sl_to_breakeven(self, fresh_state):
        fresh_state["position"] = self._open_long(qty=0.5)
        rec = OrderRecorder(fresh_state)
        deps = {"finalize": rec.finalize, "finalize_partial": rec.finalize_partial,
                "send_telegram": rec.send_telegram, "save_state": rec.save_state}

        strategy_smc.check_position(deps, fresh_state, 102_000.0)  # hit TP1

        pos = fresh_state["position"]
        assert pos is not None              # still open (only 50% closed)
        assert pos["phase1_done"] is True
        assert pos["sl"] == pos["entry"]    # stop moved to break-even
        assert pos["qty"] == pytest.approx(0.25)
        assert len(rec.partials) == 1
        # partial pnl = (102000-100000) * 0.25 = 500
        assert rec.partials[0]["pnl"] == pytest.approx(500.0)

    def test_tp2_closes_remainder_as_win(self, fresh_state):
        fresh_state["position"] = self._open_long(qty=0.5)
        rec = OrderRecorder(fresh_state)
        deps = {"finalize": rec.finalize, "finalize_partial": rec.finalize_partial,
                "send_telegram": rec.send_telegram, "save_state": rec.save_state}

        strategy_smc.check_position(deps, fresh_state, 102_000.0)  # TP1
        strategy_smc.check_position(deps, fresh_state, 103_000.0)  # TP2

        assert fresh_state["position"] is None
        assert rec.finals[-1]["result"] == "WIN"
        assert rec.finals[-1]["note"] == "TP2"

    def test_full_win_pnl_is_sum_of_both_phases(self, fresh_state):
        fresh_state["position"] = self._open_long(qty=0.5)
        rec = OrderRecorder(fresh_state)
        deps = {"finalize": rec.finalize, "finalize_partial": rec.finalize_partial,
                "send_telegram": rec.send_telegram, "save_state": rec.save_state}

        strategy_smc.check_position(deps, fresh_state, 102_000.0)
        strategy_smc.check_position(deps, fresh_state, 103_000.0)

        # TP1: (102000-100000)*0.25 = 500 ; TP2: (103000-100000)*0.25 = 750
        assert fresh_state["pnl_total"] == pytest.approx(1250.0)

    def test_stop_loss_before_tp1_is_a_loss(self, fresh_state):
        fresh_state["position"] = self._open_long(qty=0.5)
        rec = OrderRecorder(fresh_state)
        deps = {"finalize": rec.finalize, "finalize_partial": rec.finalize_partial,
                "send_telegram": rec.send_telegram, "save_state": rec.save_state}

        strategy_smc.check_position(deps, fresh_state, 99_000.0)  # hit SL

        assert fresh_state["position"] is None
        assert rec.finals[-1]["result"] == "LOSS"

    def test_breakeven_after_tp1_is_not_counted_as_loss(self, fresh_state):
        fresh_state["position"] = self._open_long(qty=0.5)
        rec = OrderRecorder(fresh_state)
        deps = {"finalize": rec.finalize, "finalize_partial": rec.finalize_partial,
                "send_telegram": rec.send_telegram, "save_state": rec.save_state}

        strategy_smc.check_position(deps, fresh_state, 102_000.0)  # TP1 → SL to BE
        strategy_smc.check_position(deps, fresh_state, 100_000.0)  # back to entry

        assert fresh_state["position"] is None
        assert rec.finals[-1]["result"] == "BREAK EVEN"
        assert fresh_state["losses"] == 0
