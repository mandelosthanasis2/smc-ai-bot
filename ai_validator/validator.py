"""
AI Validator — Κύρια λογική
═══════════════════════════
Συναρμολογεί pre-filter + agents και επιστρέφει την τελική απόφαση
στο bot.py.

Στη Φάση 3.1, αυτό είναι STUB — επιστρέφει πάντα GO με size_multiplier=1.0.
Έτσι μπορούμε να ελέγξουμε ότι το integration δουλεύει πριν βάλουμε
πραγματική λογική.
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Optional

log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# Data Classes
# ═══════════════════════════════════════════════════════════════

DecisionType = Literal["GO", "SKIP", "REDUCE_SIZE", "DOUBLE_SIZE"]


@dataclass
class ValidationResult:
    """
    Το αποτέλεσμα που επιστρέφεται στο bot.py.
    
    Attributes:
        action: Η τελική απόφαση (GO, SKIP, REDUCE_SIZE, DOUBLE_SIZE)
        size_multiplier: Πολλαπλασιαστής για το position size
                         GO=1.0, REDUCE_SIZE=0.5, DOUBLE_SIZE=2.0, SKIP=0.0
        confidence: 0.0 - 1.0, πόσο σίγουρο είναι το AI
        reasoning: Dict με αναλυτικό σκεπτικό από κάθε agent
        knowledge_references: Λίστα με αναφορές από τα 19 βιβλία
        warnings: Λίστα από warnings που πρέπει να εμφανιστούν
        source: 'pre_filter' ή 'ai_agents' ή 'fallback' (αν AI έπεσε)
        processing_time_ms: Πόση ώρα πήρε η ανάλυση
        timestamp: Πότε έγινε η απόφαση
    """
    action: DecisionType
    size_multiplier: float = 1.0
    confidence: float = 0.0
    reasoning: dict = field(default_factory=dict)
    knowledge_references: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    source: str = "stub"
    processing_time_ms: int = 0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    
    def to_dict(self) -> dict:
        """Για αποθήκευση στο DB και Telegram messages."""
        return {
            "action": self.action,
            "size_multiplier": self.size_multiplier,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "knowledge_references": self.knowledge_references,
            "warnings": self.warnings,
            "source": self.source,
            "processing_time_ms": self.processing_time_ms,
            "timestamp": self.timestamp,
        }
    
    def to_short_string(self) -> str:
        """Για logs — σύντομη γραμμή."""
        return (
            f"{self.action} "
            f"(conf={self.confidence:.2f}, "
            f"mult={self.size_multiplier}x, "
            f"src={self.source}, "
            f"{self.processing_time_ms}ms)"
        )


# ═══════════════════════════════════════════════════════════════
# Main Function — Καλείται από το bot.py
# ═══════════════════════════════════════════════════════════════

def validate_signal(
    strategy: str,
    user_id: int,
    symbol: str,
    side: str,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    context: dict,
    user_settings: dict,
    shadow_mode: bool = False,
) -> ValidationResult:
    """
    Κύρια συνάρτηση AI validation. Καλείται από το bot.py πριν από
    κάθε place_order.
    
    Args:
        strategy: Όνομα στρατηγικής ('A', 'B', 'C', 'D')
        user_id: ID χρήστη (από users table)
        symbol: Trading pair (π.χ. 'BTCUSDT')
        side: 'LONG' ή 'SHORT'
        entry_price: Τιμή εισόδου
        stop_loss: Stop loss τιμή
        take_profit: Take profit τιμή
        context: Dict με market context data (RSI, levels, volume, κλπ)
        user_settings: Dict με user settings (risk_percent, balance, mode)
        shadow_mode: Αν True, καταγράφει αλλά δεν εφαρμόζει την απόφαση
    
    Returns:
        ValidationResult με την τελική απόφαση
    """
    start_time = time.time()
    
    log.info(
        f"[AI Validator] Strategy={strategy} User={user_id} "
        f"Symbol={symbol} Side={side} Entry={entry_price}"
    )
    
    # ────────────────────────────────────────────────────────────
    # ΦΑΣΗ 3.1 — STUB: Πάντα GO
    # ────────────────────────────────────────────────────────────
    # Στις επόμενες φάσεις θα προστεθούν:
    #   1. Pre-filter (Φάση 3.2)
    #   2. AI Agents (Φάση 3.3)
    #   3. Decision logic (Φάση 3.4)
    # ────────────────────────────────────────────────────────────
    
    result = ValidationResult(
        action="GO",
        size_multiplier=1.0,
        confidence=1.0,
        reasoning={
            "stub": "Phase 3.1 stub — πάντα GO. Integration test only."
        },
        source="stub",
        processing_time_ms=int((time.time() - start_time) * 1000),
    )
    
    log.info(f"[AI Validator] Decision: {result.to_short_string()}")
    
    return result


# ═══════════════════════════════════════════════════════════════
# Self-test (για να σιγουρευτείς ότι το module δουλεύει)
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Setup logging για να δούμε output
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s"
    )
    
    print("\n" + "=" * 60)
    print("AI Validator — Self Test (Φάση 3.1)")
    print("=" * 60)
    
    # Δοκιμαστικό signal
    test_result = validate_signal(
        strategy="B",
        user_id=1,
        symbol="BTCUSDT",
        side="LONG",
        entry_price=65420.50,
        stop_loss=65100.00,
        take_profit=65900.00,
        context={
            "rsi_1h": 28.5,
            "rsi_15m": 22.0,
            "current_price": 65150,
            "volume_spike": True,
        },
        user_settings={
            "risk_percent": 2.0,
            "balance": 18449,
            "trading_mode": "PAPER",
        },
    )
    
    print(f"\nDecision: {test_result.action}")
    print(f"Size Multiplier: {test_result.size_multiplier}")
    print(f"Confidence: {test_result.confidence}")
    print(f"Source: {test_result.source}")
    print(f"Processing time: {test_result.processing_time_ms}ms")
    print(f"\nReasoning: {test_result.reasoning}")
    print(f"\nFull dict:\n{test_result.to_dict()}")
    print("\n✅ Self-test passed!\n")
