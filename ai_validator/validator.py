"""
AI Validator — Κύρια λογική (Φάση 3.3)
═══════════════════════════════════════
Συναρμολογεί pre-filter + agents και επιστρέφει την τελική απόφαση.

Pipeline:
  1. Pre-filter  (hard rules, χωρίς Claude)
  2. News Agent  (macro context, cached 15min)
  3. Technical Agent (setup analysis, per-trade)
  4. Coordinator (τελική απόφαση GO/SKIP/REDUCE/DOUBLE)
"""

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Optional

log = logging.getLogger(__name__)

DecisionType = Literal["GO", "SKIP", "REDUCE_SIZE", "DOUBLE_SIZE"]


@dataclass
class ValidationResult:
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
        return (
            f"{self.action} "
            f"(conf={self.confidence:.2f}, "
            f"mult={self.size_multiplier}x, "
            f"src={self.source}, "
            f"{self.processing_time_ms}ms)"
        )


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
    Κύρια συνάρτηση. Καλείται από bot.py πριν από κάθε place_order.
    """
    start_time = time.time()

    log.info(
        f"[Validator] Strategy={strategy} User={user_id} "
        f"{side} @ {entry_price:.2f} SL={stop_loss:.2f} TP={take_profit:.2f}"
    )

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")

    # ── 1. Pre-Filter ────────────────────────────────────────
    try:
        from .pre_filter import run_pre_filter
        pf = run_pre_filter(
            strategy          = strategy,
            side              = side,
            entry_price       = entry_price,
            stop_loss         = stop_loss,
            take_profit       = take_profit,
            rsi_15m           = context.get("rsi_15m", 50.0),
            rsi_1h            = context.get("rsi_1h", 50.0),
            current_price     = context.get("current_price", entry_price),
            last_price_update = context.get("last_price_update", time.time()),
            trades            = context.get("trades", []),
            balance           = user_settings.get("balance", 10000),
            initial_balance   = user_settings.get("initial_balance", 10000),
            has_divergence    = context.get("has_divergence", False),
            box               = context.get("box", {}),
            candles_4h        = context.get("candles_4h", []),
            extra_context     = context.get("extra", {}),
        )

        if pf.skip:
            elapsed = int((time.time() - start_time) * 1000)
            return ValidationResult(
                action="SKIP",
                size_multiplier=0.0,
                confidence=0.95,
                reasoning={"pre_filter": pf.skip_reason},
                source="pre_filter",
                processing_time_ms=elapsed,
            )
    except Exception as e:
        log.error(f"[Validator] Pre-filter error: {e}")
        pf = type("PF", (), {"skip": False, "auto_reduce": False, "auto_reduce_reason": "", "context_data": {}})()

    # ── 2. News Agent ────────────────────────────────────────
    try:
        from .agents.news_agent import analyze_news
        news = analyze_news(
            side              = side,
            entry_price       = entry_price,
            anthropic_api_key = api_key,
        )
    except Exception as e:
        log.error(f"[Validator] News agent error: {e}")
        from .agents.news_agent import NewsAnalysis
        news = NewsAnalysis(score=0, verdict="NEUTRAL", summary=f"Error: {e}")

    # ── 3. Technical Agent ───────────────────────────────────
    try:
        from .agents.technical_agent import analyze_technical
        technical = analyze_technical(
            strategy          = strategy,
            side              = side,
            entry_price       = entry_price,
            stop_loss         = stop_loss,
            take_profit       = take_profit,
            risk_reward       = pf.context_data.get("risk_reward", 2.0),
            rsi_15m           = context.get("rsi_15m", 50.0),
            rsi_1h            = context.get("rsi_1h", 50.0),
            box               = context.get("box", {}),
            has_divergence    = context.get("has_divergence", False),
            anthropic_api_key = api_key,
            candles_4h        = context.get("candles_4h", []),
            extra_context     = context.get("extra", {}),
        )
    except Exception as e:
        log.error(f"[Validator] Technical agent error: {e}")
        from .agents.technical_agent import TechnicalAnalysis
        technical = TechnicalAnalysis(confluence_score=5, recommendation="GO", summary=f"Error: {e}")

    # ── 4. Coordinator ───────────────────────────────────────
    try:
        from .agents.coordinator_agent import coordinate
        coord = coordinate(
            strategy          = strategy,
            side              = side,
            technical         = technical,
            news              = news,
            has_divergence    = context.get("has_divergence", False),
            auto_reduce       = pf.auto_reduce,
            anthropic_api_key = api_key,
            trades            = context.get("trades", []),
        )
    except Exception as e:
        log.error(f"[Validator] Coordinator error: {e}")
        coord = type("C", (), {
            "action": "GO", "size_multiplier": 1.0,
            "confidence": 0.5, "reasoning": f"Error: {e}", "used_claude": False
        })()

    # ── 5. Assemble result ───────────────────────────────────
    elapsed = int((time.time() - start_time) * 1000)

    result = ValidationResult(
        action          = coord.action,
        size_multiplier = coord.size_multiplier,
        confidence      = coord.confidence,
        reasoning = {
            "coordinator": coord.reasoning,
            "technical":   f"Score={technical.confluence_score}/10 | {technical.summary}",
            "news":        f"Score={news.score} | {news.verdict} | {news.summary}",
            "pre_filter":  f"auto_reduce={pf.auto_reduce}" + (f" ({pf.auto_reduce_reason})" if pf.auto_reduce else ""),
        },
        source              = "ai_agents",
        processing_time_ms  = elapsed,
    )

    log.info(f"[Validator] Final: {result.to_short_string()}")
    return result
