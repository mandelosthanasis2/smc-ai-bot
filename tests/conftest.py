"""
tests/conftest.py
═════════════════
Shared pytest fixtures for the NRM Bot test suite.

The trading strategies are designed around dependency injection (a `deps`
dict carrying callables such as ``place_order`` and ``finalize``), which makes
them straightforward to test in isolation without a live exchange, database,
or Telegram connection. The fakes below stand in for those dependencies and
record what the strategy did so tests can assert on the behaviour.
"""

import sys
from pathlib import Path

import pytest

# Make the project root importable (strategies/, bot.py, ...) when pytest
# is invoked from anywhere within the repo.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class FakeRealtime:
    """Stand-in for the global realtime (`rt`) object used by strategies."""

    def __init__(self, price=100_000.0, rsi_15m=50.0, rsi_1h=50.0, initialized=True):
        self.price = price
        self.rsi_15m = rsi_15m
        self.rsi_1h = rsi_1h
        self.initialized = initialized


class OrderRecorder:
    """
    Records calls to the injected trading callables so a test can assert on
    the full lifecycle of a position (entry, partial close, final close)
    without touching a real exchange or database.
    """

    def __init__(self, state):
        self.state = state
        self.orders = []       # every place_order call
        self.partials = []     # every finalize_partial call
        self.finals = []       # every finalize call
        self.telegrams = []    # every telegram message (first line only)

    # -- injected callables -------------------------------------------------
    def place_order(self, side, qty, entry, sl, tp):
        oid = f"PAPER_{len(self.orders) + 1}"
        self.orders.append(
            {"side": side, "qty": qty, "entry": entry, "sl": sl, "tp": tp, "id": oid}
        )
        return oid

    def finalize(self, price, result, note="", pos=None):
        # Multi-position aware (Strategy B v2): when `pos` is given, close THAT
        # position and remove it from state["positions"]. Legacy single-position
        # strategies (A/C/SMC/CM) call finalize without `pos`.
        target = pos if pos is not None else self.state.get("position")
        if not target:
            return
        is_long = target["type"] == "LONG"
        pnl = round(((price - target["entry"]) if is_long else (target["entry"] - price)) * target["qty"], 2)
        self.state["balance"] = round(self.state["balance"] + pnl, 2)
        self.state["pnl_total"] = round(self.state["pnl_total"] + pnl, 2)
        if result == "WIN":
            self.state["wins"] += 1
        elif result == "LOSS":
            self.state["losses"] += 1
        self.finals.append({"price": price, "result": result, "note": note, "pnl": pnl})
        positions = self.state.get("positions")
        if pos is not None and isinstance(positions, list) and target in positions:
            positions.remove(target)
            self.state["position"] = positions[0] if positions else None
        else:
            self.state["position"] = None

    def finalize_partial(self, close_price, partial_qty, partial_pnl, note=""):
        self.state["balance"] = round(self.state["balance"] + partial_pnl, 2)
        self.state["pnl_total"] = round(self.state["pnl_total"] + partial_pnl, 2)
        self.state["wins"] += 1
        self.partials.append(
            {"price": close_price, "qty": partial_qty, "pnl": partial_pnl, "note": note}
        )

    def send_telegram(self, message):
        self.telegrams.append(message.split("\n")[0])

    def save_state(self):
        pass


@pytest.fixture
def fresh_state():
    """A clean strategy state dict with a known starting balance."""
    return {
        "position": None,
        "positions": [],
        "balance": 10_000.0,
        "pnl_total": 0.0,
        "wins": 0,
        "losses": 0,
        "trades": [],
        "last_signal": "",
    }


@pytest.fixture
def rt():
    """Default realtime object (price 100k, neutral RSI)."""
    return FakeRealtime()


@pytest.fixture
def recorder(fresh_state):
    """An OrderRecorder bound to a fresh state."""
    return OrderRecorder(fresh_state)
