"""
tests/test_concurrency.py
═════════════════════════
Thread-safety tests for the per-strategy state locks (HANDOFF item 3).

The bot mutates the strategy state dicts from the scheduler / webhook threads
while the Flask request threads read them. Without synchronisation a reader
serialising a state dict (jsonify / deepcopy iterates in Python) can crash with
``RuntimeError: dictionary changed size during iteration`` when a writer mutates
a nested container (the position dict, the trades/errors lists) at the same
moment.

These tests inject a *real* lock into the strategy deps and run a reader thread
(taking deepcopy snapshots under the lock — exactly what ``snapshot_state`` does
in bot.py) concurrently with a writer thread hammering ``check_position``. If a
mutation in the exit path were left outside ``with lock:``, the reader's locked
deepcopy could still race the writer and this test would surface it.
"""

import contextlib
import copy
import threading

import pytest

from strategies import strategy_a as A
from strategies import strategy_b as B
from strategies import strategy_c as C
from tests.conftest import OrderRecorder


def _long_pos():
    return {"type": "LONG", "entry": 100_000.0, "sl": 99_000.0, "tp": 101_000.0, "qty": 1.0}


def _hammer(module, exit_deps_extra, fresh_state, iterations=4000):
    """Run a locked-snapshot reader against a check_position writer."""
    lock = threading.RLock()
    fresh_state["position"] = _long_pos()
    rec = OrderRecorder(fresh_state)
    deps = {
        "finalize": rec.finalize,
        "send_telegram": rec.send_telegram,
        "save_state": rec.save_state,
        "lock": lock,
    }
    deps.update(exit_deps_extra)

    errors = []
    stop = threading.Event()

    def reader():
        try:
            while not stop.is_set():
                with lock:
                    snap = copy.deepcopy(fresh_state)
                # snapshot must always be internally well-formed
                pos = snap.get("position")
                assert pos is None or pos["type"] == "LONG"
        except Exception as e:  # pragma: no cover - only on failure
            errors.append(("reader", repr(e)))

    def writer():
        try:
            price = 101_000.0
            for _ in range(iterations):
                price += 1.0  # rising → trailing keeps mutating pos in place
                module.check_position(deps, fresh_state, price)
                if not fresh_state["position"]:
                    fresh_state["position"] = _long_pos()
        except Exception as e:  # pragma: no cover - only on failure
            errors.append(("writer", repr(e)))
        finally:
            stop.set()

    r = threading.Thread(target=reader)
    w = threading.Thread(target=writer)
    r.start(); w.start()
    w.join(); r.join()
    return errors


@pytest.mark.strategy
def test_strategy_a_concurrent_reader_is_safe(fresh_state):
    errors = _hammer(A, {"close_position_live": lambda *a: None, "trading_mode": "PAPER"}, fresh_state)
    assert not errors, errors


@pytest.mark.strategy
def test_strategy_b_concurrent_reader_is_safe(fresh_state):
    errors = _hammer(B, {}, fresh_state)
    assert not errors, errors


@pytest.mark.strategy
def test_strategy_c_concurrent_reader_is_safe(fresh_state):
    errors = _hammer(C, {}, fresh_state)
    assert not errors, errors


@pytest.mark.strategy
def test_missing_lock_falls_back_to_nullcontext(fresh_state):
    """deps without a 'lock' key (e.g. unit tests) must still work."""
    fresh_state["position"] = _long_pos()
    rec = OrderRecorder(fresh_state)
    deps = {
        "finalize": rec.finalize,
        "send_telegram": rec.send_telegram,
        "save_state": rec.save_state,
        "close_position_live": lambda *a: None,
        "trading_mode": "PAPER",
    }  # no "lock"
    # progress 0.50 → break-even; must not raise despite no lock injected
    A.check_position(deps, fresh_state, 100_500.0)
    assert fresh_state["position"]["sl"] == fresh_state["position"]["entry"]
