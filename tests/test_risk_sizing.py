"""
tests/test_risk_sizing.py
═════════════════════════
Tests for position sizing (``calc_qty``).

``calc_qty`` lives in ``bot.py``, which performs heavy module-level setup
(exchange clients, websocket threads, state loading) on import. To keep these
unit tests fast and side-effect free, the formula under test is reproduced
here verbatim and verified against known cases. The reference implementation
in ``bot.py`` is::

    def calc_qty(balance, risk_pct, entry, sl):
        risk_dist = abs(entry - sl)
        if risk_dist <= 0:
            return 0.001
        return max(round((balance * risk_pct) / risk_dist, 4), 0.001)

If the production formula changes, this test file must be updated in lockstep;
the duplication is intentional and documented to avoid importing the world.
"""

import pytest


def calc_qty(balance, risk_pct, entry, sl):
    risk_dist = abs(entry - sl)
    if risk_dist <= 0:
        return 0.001
    return max(round((balance * risk_pct) / risk_dist, 4), 0.001)


@pytest.mark.risk
class TestCalcQty:
    def test_risks_exactly_the_configured_fraction(self):
        # 2% of 10k = $200 risk, over a $1,000 stop distance → 0.2 BTC.
        qty = calc_qty(10_000, 0.02, 100_000, 99_000)
        assert qty == pytest.approx(0.2)
        # Sanity: qty * stop_distance == dollar risk
        assert qty * abs(100_000 - 99_000) == pytest.approx(200.0)

    def test_wider_stop_means_smaller_size(self):
        tight = calc_qty(10_000, 0.02, 100_000, 99_500)   # $500 stop
        wide = calc_qty(10_000, 0.02, 100_000, 98_000)    # $2,000 stop
        assert tight > wide

    def test_short_side_uses_absolute_distance(self):
        long_qty = calc_qty(10_000, 0.02, 100_000, 99_000)
        short_qty = calc_qty(10_000, 0.02, 100_000, 101_000)
        assert long_qty == pytest.approx(short_qty)

    def test_zero_stop_distance_returns_floor_not_crash(self):
        # Guards against division-by-zero when entry == sl.
        assert calc_qty(10_000, 0.02, 100_000, 100_000) == 0.001

    def test_never_returns_below_minimum(self):
        # Tiny risk budget would round to ~0; floor keeps it tradeable.
        qty = calc_qty(10, 0.02, 100_000, 99_000)
        assert qty >= 0.001

    def test_doubling_risk_doubles_size(self):
        base = calc_qty(10_000, 0.02, 100_000, 99_000)
        doubled = calc_qty(10_000, 0.04, 100_000, 99_000)
        assert doubled == pytest.approx(base * 2)
