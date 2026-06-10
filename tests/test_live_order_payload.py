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


def _find_func(name):
    tree = ast.parse(_BOT_SRC.read_text(encoding="utf-8"))
    func = next((n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == name), None)
    assert func is not None, f"{name} δεν βρέθηκε στο bot.py"
    return func


def _signed_payload(func_name, path):
    """(dict_node, extra) για το client.signed('POST', path, body):
    το body είναι είτε dict literal είτε Name που ανατίθεται σε dict literal
    στη συνάρτηση· extra = {key: value_src} για conditional προσθήκες
    body["key"] = ... (π.χ. presetStopSurplusPrice όταν trailing off)."""
    func = _find_func(func_name)
    for call in ast.walk(func):
        if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                and call.func.attr == "signed" and len(call.args) >= 3
                and isinstance(call.args[1], ast.Constant)
                and call.args[1].value == path):
            arg = call.args[2]
            if isinstance(arg, ast.Dict):
                return arg, {}
            if isinstance(arg, ast.Name):
                base, extra = None, {}
                for n in ast.walk(func):
                    if not (isinstance(n, ast.Assign) and len(n.targets) == 1):
                        continue
                    t = n.targets[0]
                    if isinstance(t, ast.Name) and t.id == arg.id and isinstance(n.value, ast.Dict):
                        base = n.value
                    elif (isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name)
                          and t.value.id == arg.id and isinstance(t.slice, ast.Constant)):
                        extra[t.slice.value] = ast.unparse(n.value)
                if base is not None:
                    return base, extra
    raise AssertionError(f"signed call προς {path} δεν βρέθηκε στο {func_name}")


def _place_order_payload_keys(func_name):
    """Set των string keys του place-order payload (μαζί με conditional keys)."""
    base, extra = _signed_payload(func_name, _PLACE_ORDER_PATH)
    keys = {k.value for k in base.keys
            if isinstance(k, ast.Constant) and isinstance(k.value, str)}
    return keys | set(extra)


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
    """ast.unparse() του value-expression για το `field` του place-order payload
    (dict literal ή conditional body[field] = ...)."""
    base, extra = _signed_payload(func_name, _PLACE_ORDER_PATH)
    for k, v in zip(base.keys, base.values):
        if isinstance(k, ast.Constant) and k.value == field:
            return ast.unparse(v)
    if field in extra:
        return extra[field]
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


# ── PR1 infra: position TP/SL plan-order helpers (verbatim Bitget params) ────
_TPSL_PATH = "/api/v2/mix/order/place-tpsl-order"
_MODIFY_TPSL_PATH = "/api/v2/mix/order/modify-tpsl-order"


def _signed_dict(func_name, path):
    """Το dict literal που περνιέται στο client.signed('POST', path, {...})."""
    tree = ast.parse(_BOT_SRC.read_text(encoding="utf-8"))
    func = next((n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == func_name), None)
    assert func is not None, f"{func_name} δεν βρέθηκε στο bot.py"
    for call in ast.walk(func):
        if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                and call.func.attr == "signed" and len(call.args) >= 3
                and isinstance(call.args[1], ast.Constant) and call.args[1].value == path
                and isinstance(call.args[2], ast.Dict)):
            return call.args[2]
    raise AssertionError(f"signed call προς {path} δεν βρέθηκε στο {func_name}")


def _keys(d):
    return {k.value for k in d.keys if isinstance(k, ast.Constant)}


def _value_src(d, field):
    for k, v in zip(d.keys, d.values):
        if isinstance(k, ast.Constant) and k.value == field:
            return ast.unparse(v)
    return None


def test_place_tpsl_has_required_params_and_no_invalid_ones():
    d = _signed_dict("place_tpsl_order_c", _TPSL_PATH)
    keys = _keys(d)
    required = {"symbol", "productType", "marginCoin", "planType", "triggerPrice", "holdSide"}
    assert required <= keys, f"place-tpsl λείπουν required: {sorted(required - keys)}"
    # verbatim: το place-tpsl ΔΕΝ έχει marginMode· pos_loss/pos_profit ΔΕΝ θέλουν size
    assert "marginMode" not in keys, "place-tpsl δεν έχει πεδίο marginMode"
    assert "size" not in keys, "pos_loss/pos_profit δεν στέλνουν size"
    assert "round_to_tick" in (_value_src(d, "triggerPrice") or ""), "triggerPrice όχι tick-rounded"


def test_modify_tpsl_has_required_params_and_empty_size():
    d = _signed_dict("modify_tpsl_order_c", _MODIFY_TPSL_PATH)
    keys = _keys(d)
    required = {"orderId", "symbol", "productType", "marginCoin", "triggerPrice", "size"}
    assert required <= keys, f"modify-tpsl λείπουν required: {sorted(required - keys)}"
    # verbatim: για position TP/SL το size πρέπει να είναι ""
    assert _value_src(d, "size") == "''", f"modify-tpsl size πρέπει να είναι '', βρέθηκε {_value_src(d, 'size')}"
    assert "round_to_tick" in (_value_src(d, "triggerPrice") or ""), "triggerPrice όχι tick-rounded"


# ── PR2: exchange-managed exit (preset TP όταν trailing off + SL discovery) ──

def test_open_preset_tp_is_conditional_and_tick_rounded():
    """Trailing OFF → hard TP στο exchange (presetStopSurplusPrice, tick-rounded).
    Πρέπει να υπάρχει ως conditional key (ΟΧΙ πάντα — trailing ON δεν στέλνει TP)."""
    base, extra = _signed_payload(_OPEN_FN, _PLACE_ORDER_PATH)
    base_keys = {k.value for k in base.keys if isinstance(k, ast.Constant)}
    assert "presetStopSurplusPrice" not in base_keys, (
        "preset TP πρέπει να είναι conditional (μόνο όταν trailing off), όχι πάντα"
    )
    assert "presetStopSurplusPrice" in extra, "λείπει το conditional preset TP (trailing off)"
    assert "round_to_tick" in extra["presetStopSurplusPrice"], "preset TP όχι tick-rounded"


def test_sl_discovery_uses_verbatim_plan_pending_params():
    """Το discovery διαβάζει orders-plan-pending με τα verbatim required params
    (planType=profit_loss + productType) και επιστρέφει orderId."""
    func = _find_func("_discover_pos_sl_oid_c")
    src = ast.unparse(func)
    assert "orders-plan-pending" in src
    assert "planType=profit_loss" in src, "planType=profit_loss είναι required (verbatim)"
    assert "productType=" in src, "productType είναι required (verbatim)"


# ── PR3: real fill accounting (history-position, verbatim) ───────────────────

def test_fill_lookup_uses_verbatim_history_position_params():
    """Το fill lookup διαβάζει history-position με productType + response key
    `list` (verbatim), και ΔΕΝ αποφασίζει από τα αμφίσημα *TotalPos fields."""
    func = _find_func("_closed_position_fill_c")
    src = ast.unparse(func)
    assert "history-position" in src
    assert "productType=" in src
    assert "'list'" in src or '"list"' in src, "response key είναι `list` (verbatim)"
    assert "closeAvgPrice" in src and "select_closed_position" in src


def test_finalize_pnl_override_is_optional_and_default_none():
    """Το pnl_override πρέπει να είναι optional kwarg με default None —
    paper path 100% ανεπηρέαστο."""
    func = _find_func("finalize_trade_c")
    args = func.args
    assert "pnl_override" in [a.arg for a in args.args], "λείπει το pnl_override"
    defaults = dict(zip([a.arg for a in args.args][-len(args.defaults):], args.defaults))
    d = defaults.get("pnl_override")
    assert isinstance(d, ast.Constant) and d.value is None
