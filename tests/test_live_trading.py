"""
tests/test_live_trading.py
══════════════════════════
Tests για το live-trading safety layer (Strategy C real money).

Δοκιμάζουμε τα κομμάτια που είναι I/O-free (δεν χρειάζονται Bitget/DB):
  • live_trading.py — sizing (round-up στο min, risk cap, affordability, auto-min
    leverage) και mode resolution (fail-closed).
  • secrets_vault.py — encrypt/decrypt round-trip, masking, fail-closed χωρίς key.
  • config.LIVE_STRATEGIES — default ΚΕΝΟ (όλες PAPER).

Το πλήρες live engine (bot.place_order_live_c, finalize_trade_c, reconciler)
χρειάζεται το exchange και επαληθεύεται live· εδώ κλειδώνουμε τη ΛΟΓΙΚΗ ασφαλείας.
"""

import importlib
import os

import pytest

import live_trading as LT


# ── sizing ────────────────────────────────────────────────────────────────

# Κοινά specs/limits για ευκολία (BTC perp: min 0.001).
_KW = dict(min_qty=0.001, size_step=0.001, leverage_cap=3,
           max_trade_risk_pct=0.10, margin_buffer=0.90)


class TestPrepareLiveSize:
    def test_rounds_up_to_exchange_minimum(self):
        # risk-based qty κάτω από το min → στρογγυλοποιείται στο 0.001
        # entry 100k, sl 99k (1% stop). min-trade risk = 0.001*1000 = $1 ≤ 10% of $80.
        res = LT.prepare_live_size(0.0001, 100_000, 99_000, 80, **_KW)
        assert res is not None
        qty, lev = res
        assert qty == 0.001

    def test_auto_min_leverage_capped(self):
        # notional 0.001*100k = $100· margin buffer 0.9*$80=$72 → need ceil(100/72)=2x
        res = LT.prepare_live_size(0.001, 100_000, 99_000, 80, **_KW)
        assert res is not None
        _, lev = res
        assert lev == 2

    def test_leverage_never_exceeds_cap(self):
        # tiny balance → would need huge leverage → capped, και αν δεν χωρά → skip
        res = LT.prepare_live_size(0.001, 100_000, 99_900, 5, **_KW)
        # $100 notional, usable 0.9*$5=$4.5 → need 23x but cap 3 → margin $33>4.5 → skip
        assert res is None

    def test_skip_when_min_trade_risk_exceeds_cap(self):
        # wide stop: sl 80k vs entry 100k = $20k dist. min-trade risk 0.001*20000=$20
        # > 10% of $80 ($8) → skip
        res = LT.prepare_live_size(0.001, 100_000, 80_000, 80, **_KW)
        assert res is None

    def test_skip_when_not_affordable_even_at_cap(self):
        # balance too small to afford min notional even at cap leverage
        res = LT.prepare_live_size(0.001, 100_000, 99_500, 20, **_KW)
        # $100 notional, usable $18, cap 3x → margin $33 > $18 → skip
        assert res is None

    def test_affordable_normal_case(self):
        res = LT.prepare_live_size(0.001, 100_000, 99_000, 200, **_KW)
        assert res is not None
        qty, lev = res
        assert qty == 0.001
        assert lev == 1            # $100 notional, usable $180 → 1x

    def test_zero_or_negative_balance_skips(self):
        assert LT.prepare_live_size(0.001, 100_000, 99_000, 0, **_KW) is None
        assert LT.prepare_live_size(0.001, 0, 0, 80, **_KW) is None

    def test_round_up_to_step_snaps(self):
        assert LT.round_up_to_step(0.0014, 0.001, 0.001) == 0.002
        assert LT.round_up_to_step(0.0, 0.001, 0.001) == 0.001


class TestLeverageFor:
    def test_minimal_leverage(self):
        assert LT.leverage_for(100, 200, 3, 0.90) == 1     # usable 180 ≥ 100
        assert LT.leverage_for(100, 80, 3, 0.90) == 2      # usable 72 → ceil(100/72)=2
        assert LT.leverage_for(1000, 80, 3, 0.90) == 3     # capped at 3


# ── mode resolution (FAIL-CLOSED) ──────────────────────────────────────────

class TestResolveMode:
    def test_not_in_allowlist_is_paper(self):
        assert LT.resolve_mode("C", frozenset(), lambda s: True) == "PAPER"
        assert LT.resolve_mode("A", frozenset({"C"}), lambda s: True) == "PAPER"

    def test_in_allowlist_but_creds_bad_is_paper(self):
        assert LT.resolve_mode("C", frozenset({"C"}), lambda s: False) == "PAPER"

    def test_live_only_with_allowlist_and_creds(self):
        assert LT.resolve_mode("C", frozenset({"C"}), lambda s: True) == "LIVE"

    def test_creds_fn_receives_strategy(self):
        seen = {}
        LT.resolve_mode("C", frozenset({"C"}), lambda s: seen.setdefault("s", s) or True)
        assert seen["s"] == "C"


# ── secrets_vault ──────────────────────────────────────────────────────────

import secrets_vault  # noqa: E402


class TestSecretsVault:
    def _with_key(self):
        key = secrets_vault.generate_key()
        os.environ["SECRETS_ENCRYPTION_KEY"] = key
        return key

    def teardown_method(self):
        os.environ.pop("SECRETS_ENCRYPTION_KEY", None)

    def test_round_trip(self):
        self._with_key()
        token = secrets_vault.encrypt("bitget-api-key-secret")
        assert token is not None
        assert token != "bitget-api-key-secret"      # actually encrypted
        assert secrets_vault.decrypt(token) == "bitget-api-key-secret"

    def test_fail_closed_without_key(self):
        os.environ.pop("SECRETS_ENCRYPTION_KEY", None)
        assert secrets_vault.available() is False
        assert secrets_vault.encrypt("x") is None
        assert secrets_vault.decrypt("x") is None

    def test_decrypt_wrong_key_returns_none(self):
        self._with_key()
        token = secrets_vault.encrypt("secret")
        os.environ["SECRETS_ENCRYPTION_KEY"] = secrets_vault.generate_key()  # different key
        assert secrets_vault.decrypt(token) is None

    def test_invalid_key_fail_closed(self):
        os.environ["SECRETS_ENCRYPTION_KEY"] = "not-a-valid-fernet-key"
        assert secrets_vault.available() is False
        assert secrets_vault.encrypt("x") is None

    def test_mask(self):
        assert secrets_vault.mask("abcdef1234") == "••••1234"
        assert secrets_vault.mask("") == ""


# ── config gating: default = everything paper ──────────────────────────────

class TestConfigAllowlist:
    def test_default_allowlist_empty(self):
        os.environ.pop("LIVE_STRATEGIES", None)
        import config
        importlib.reload(config)
        assert config.LIVE_STRATEGIES == frozenset()

    def test_allowlist_parses_csv_uppercase(self):
        os.environ["LIVE_STRATEGIES"] = "c"
        import config
        importlib.reload(config)
        try:
            assert config.LIVE_STRATEGIES == frozenset({"C"})
        finally:
            os.environ.pop("LIVE_STRATEGIES", None)
            importlib.reload(config)
