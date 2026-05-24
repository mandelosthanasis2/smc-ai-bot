"""
AI Validator Module
═══════════════════
Module που ενσωματώνεται στο NRM Bot και παρέχει AI validation
για κάθε trade signal πριν την εκτέλεση.

Usage από το bot.py:
    from ai_validator import validate_signal
    
    decision = validate_signal(
        strategy="B",
        user_id=1,
        symbol="BTCUSDT",
        side="LONG",
        entry_price=65420.50,
        stop_loss=65100.00,
        take_profit=65900.00,
        context={...},
        user_settings={...}
    )
    
    if decision.action == "GO":
        place_order(...)
    elif decision.action == "REDUCE_SIZE":
        place_order(..., size_multiplier=decision.size_multiplier)
    # etc.

Φάσεις development:
    [✓] 3.1 — Skeleton με stub (always returns GO)
    [ ] 3.2 — Pre-filter με hard rules
    [ ] 3.3 — Agents (Technical, News, Coordinator)
    [ ] 3.4 — Integration στο bot.py
    [ ] 3.5 — Database migration
    [ ] 3.6 — Settings UI
"""

from .validator import validate_signal, ValidationResult

__version__ = "0.1.0"
__all__ = ["validate_signal", "ValidationResult"]
