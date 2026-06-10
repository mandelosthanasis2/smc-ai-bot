"""
tests/test_live_order_payload.py
════════════════════════════════
Regression guard για το LIVE order payload της Strategy C.

Αφορμή: live incident όπου το close (close_position_live_c) ΔΕΝ έστελνε
`marginMode`, οπότε το Bitget το απέρριπτε με code 400172 ("The margin mode
cannot be empty"). Επειδή το finalize κρατά τη θέση όταν το close αποτυγχάνει,
αυτό δημιούργησε ατέρμονο retry-loop μέχρι χειροκίνητη παρέμβαση.

Δεν μπορούμε να καλέσουμε τις live συναρτήσεις χωρίς exchange, οπότε
επιθεωρούμε το ΠΗΓΑΙΟ του bot.py μέσω AST: εγγυόμαστε ότι το open ΚΑΙ το close
place-order στέλνουν το ίδιο σύνολο απαραίτητων πεδίων — ώστε να μην ξανα-
αποκλίνουν σιωπηλά.
"""

import ast
import pathlib

_BOT_SRC = pathlib.Path(__file__).resolve().parent.parent / "bot.py"
_PLACE_ORDER_PATH = "/api/v2/mix/order/place-order"

# Τα πεδία που ΚΑΘΕ mix place-order (open & close) πρέπει να στέλνει στο Bitget.
# Η απουσία οποιουδήποτε προκαλεί απόρριψη (π.χ. marginMode -> code 400172).
_REQUIRED_ORDER_FIELDS = frozenset({
    "symbol", "productType", "marginMode", "marginCoin",
    "size", "side", "tradeSide", "orderType",
})

# (function name στο bot.py, ανθρώπινο label)
_OPEN_FN = "place_order_live_c"
_CLOSE_FN = "close_position_live_c"


def _place_order_payload_keys(func_name):
    """Set των string keys του dict που περνιέται στο
    client.signed("POST", "/api/v2/mix/order/place-order", {...}) μέσα στη
    συνάρτηση `func_name` του bot.py (AST — χωρίς import bot)."""
    tree = ast.parse(_BOT_SRC.read_text(encoding="utf-8"))
    func = next((n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == func_name), None)
    assert func is not None, f"{func_name} δεν βρέθηκε στο bot.py"

    for call in ast.walk(func):
        if not isinstance(call, ast.Call):
            continue
        f = call.func
        if (isinstance(f, ast.Attribute) and f.attr == "signed"
                and len(call.args) >= 3
                and isinstance(call.args[1], ast.Constant)
                and call.args[1].value == _PLACE_ORDER_PATH
                and isinstance(call.args[2], ast.Dict)):
            return {k.value for k in call.args[2].keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)}
    raise AssertionError(f"Δεν βρέθηκε place-order call μέσα στο {func_name}")


def test_close_order_includes_margin_mode():
    """Το ακριβές regression: το close ΠΡΕΠΕΙ να στέλνει marginMode (code 400172)."""
    keys = _place_order_payload_keys(_CLOSE_FN)
    assert "marginMode" in keys, (
        "close order χωρίς marginMode -> Bitget code 400172 -> close retry-loop"
    )


def test_open_order_includes_margin_mode():
    """Sanity: και το open στέλνει marginMode (η αναφορά συμμόρφωσης)."""
    assert "marginMode" in _place_order_payload_keys(_OPEN_FN)


def test_open_has_all_required_fields():
    missing = _REQUIRED_ORDER_FIELDS - _place_order_payload_keys(_OPEN_FN)
    assert not missing, f"open order λείπουν required πεδία: {sorted(missing)}"


def test_close_has_all_required_fields():
    missing = _REQUIRED_ORDER_FIELDS - _place_order_payload_keys(_CLOSE_FN)
    assert not missing, f"close order λείπουν required πεδία: {sorted(missing)}"


def test_open_and_close_share_required_fields():
    """Open & close πρέπει να μοιράζονται ΟΛΑ τα required πεδία — καμία ασυμφωνία."""
    open_keys = _place_order_payload_keys(_OPEN_FN)
    close_keys = _place_order_payload_keys(_CLOSE_FN)
    open_req = open_keys & _REQUIRED_ORDER_FIELDS
    close_req = close_keys & _REQUIRED_ORDER_FIELDS
    assert open_req == close_req, (
        "open/close required πεδία αποκλίνουν: "
        f"μόνο-open={sorted(open_req - close_req)} "
        f"μόνο-close={sorted(close_req - open_req)}"
    )


def _place_order_field_value_src(func_name, field):
    """ast.unparse() του value-expression για το `field` μέσα στο place-order
    dict της `func_name` (π.χ. το expression του presetStopLossPrice)."""
    tree = ast.parse(_BOT_SRC.read_text(encoding="utf-8"))
    func = next((n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == func_name), None)
    assert func is not None, f"{func_name} δεν βρέθηκε στο bot.py"
    for call in ast.walk(func):
        if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                and call.func.attr == "signed" and len(call.args) >= 3
                and isinstance(call.args[1], ast.Constant)
                and call.args[1].value == _PLACE_ORDER_PATH
                and isinstance(call.args[2], ast.Dict)):
            for k, v in zip(call.args[2].keys, call.args[2].values):
                if isinstance(k, ast.Constant) and k.value == field:
                    return ast.unparse(v)
    raise AssertionError(f"{field} δεν βρέθηκε στο place-order του {func_name}")


def test_open_safety_sl_snapped_to_price_tick():
    """Regression: το safety SL πρέπει να στρογγυλοποιείται σε price tick
    (αλλιώς Bitget 'should be a multiple of 0.1') — όχι σκέτο round(sl, 2)."""
    src = _place_order_field_value_src(_OPEN_FN, "presetStopLossPrice")
    assert "round_to_tick" in src, (
        f"presetStopLossPrice δεν στρογγυλοποιείται σε tick, βρέθηκε: {src}"
    )


def test_close_treats_no_position_as_success():
    """Regression: το close πρέπει να αντιμετωπίζει 'no position' (22002) ως
    επιτυχία (μέσω close_succeeded) ώστε να καθαρίζει state χωρίς retry-loop."""
    tree = ast.parse(_BOT_SRC.read_text(encoding="utf-8"))
    func = next((n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == _CLOSE_FN), None)
    assert func is not None, f"{_CLOSE_FN} δεν βρέθηκε στο bot.py"
    src = ast.unparse(func)
    assert "close_succeeded" in src, (
        "close_position_live_c πρέπει να χρησιμοποιεί close_succeeded "
        "(αλλιώς το 22002 -> retry-loop)"
    )
