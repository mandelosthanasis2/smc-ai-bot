"""
AI Validator — Coordinator Agent (Φάση 3.3)
════════════════════════════════════════════
Παίρνει τα αποτελέσματα Technical + News Agent
και βγάζει την ΤΕΛΙΚΗ απόφαση: GO / SKIP / REDUCE_SIZE / DOUBLE_SIZE.

Λογική απόφασης:
  DOUBLE_SIZE: technical >= 8 AND news SUPPORTS AND has_divergence
  GO:          technical >= 6 AND news != CONTRADICTS
  REDUCE_SIZE: technical 4-5 OR (news CONTRADICTS AND technical >= 6) OR auto_reduce flag
  SKIP:        technical <= 3 OR (news strongly CONTRADICTS με score -2)

Ο Coordinator καλεί Claude ΜΟΝΟ για borderline cases (score 5-7).
Για ξεκάθαρα cases (score <=3 ή >=8), αποφασίζει χωρίς Claude.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

import anthropic

from .technical_agent import TechnicalAnalysis
from .news_agent import NewsAnalysis

log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# Result dataclass
# ═══════════════════════════════════════════════════════════════

@dataclass
class CoordinatorDecision:
    """
    Τελική απόφαση του Coordinator.
    Αυτό επιστρέφεται στον validator.py.
    """
    action: str = "GO"                 # GO / SKIP / REDUCE_SIZE / DOUBLE_SIZE
    size_multiplier: float = 1.0
    confidence: float = 0.7
    reasoning: str = ""
    used_claude: bool = False          # True αν κλήθηκε Claude για αυτή την απόφαση
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "action":          self.action,
            "size_multiplier": self.size_multiplier,
            "confidence":      self.confidence,
            "reasoning":       self.reasoning,
            "used_claude":     self.used_claude,
        }


# ═══════════════════════════════════════════════════════════════
# Rule-based decision (χωρίς Claude — για ξεκάθαρα cases)
# ═══════════════════════════════════════════════════════════════

def _rule_based_decision(
    technical: TechnicalAnalysis,
    news: NewsAnalysis,
    has_divergence: bool,
    auto_reduce: bool,
    strategy: str,
    trades: list,
) -> Optional[CoordinatorDecision]:
    """
    Αποφασίζει χωρίς Claude για ξεκάθαρα cases.
    Επιστρέφει None αν το case είναι borderline (→ πάει στο Claude).
    """
    score = technical.confluence_score
    news_score = news.score

    # ── SKIP cases (ξεκάθαρα) ────────────────────────────────
    if score <= 3:
        return CoordinatorDecision(
            action="SKIP",
            size_multiplier=0.0,
            confidence=0.9,
            reasoning=f"Weak technical setup (score={score}/10). {technical.summary}",
            used_claude=False,
        )

    if news_score <= -2:
        return CoordinatorDecision(
            action="SKIP",
            size_multiplier=0.0,
            confidence=0.85,
            reasoning=f"Strongly contradicting macro (news_score={news_score}). {news.summary}",
            used_claude=False,
        )

    # ── DOUBLE_SIZE (ξεκάθαρα) ───────────────────────────────
    if score >= 8 and news.verdict == "SUPPORTS" and has_divergence:
        # Έλεγχος multi-strategy confluence (αν trades list έχει patterns)
        return CoordinatorDecision(
            action="DOUBLE_SIZE",
            size_multiplier=2.0,
            confidence=0.90,
            reasoning=(
                f"Triple confluence: Strong technical (score={score}/10) + "
                f"Macro supports + Divergence detected. {technical.summary}"
            ),
            used_claude=False,
        )

    # ── REDUCE_SIZE (ξεκάθαρα) ──────────────────────────────
    if auto_reduce:
        # Auto reduce flag από pre-filter (counter-trend ή drawdown)
        # Αν το technical είναι ισχυρό, μόνο REDUCE — όχι SKIP
        if score >= 6:
            return CoordinatorDecision(
                action="REDUCE_SIZE",
                size_multiplier=0.5,
                confidence=0.75,
                reasoning=f"Auto-reduce flag active. Technical OK (score={score}/10) but risk factors present.",
                used_claude=False,
            )

    # ── Borderline cases → Claude ────────────────────────────
    # score 4-7: δεν είναι ξεκάθαρο
    return None  # → Συνέχισε στο Claude


# ═══════════════════════════════════════════════════════════════
# Claude call (για borderline cases)
# ═══════════════════════════════════════════════════════════════

def _ask_claude_coordinator(
    api_key: str,
    strategy: str,
    side: str,
    technical: TechnicalAnalysis,
    news: NewsAnalysis,
    has_divergence: bool,
    auto_reduce: bool,
) -> CoordinatorDecision:
    """Καλεί Claude Haiku για borderline αποφάσεις."""

    if not api_key:
        # Χωρίς API key — conservative default
        return CoordinatorDecision(
            action="GO" if technical.confluence_score >= 5 else "REDUCE_SIZE",
            size_multiplier=1.0 if technical.confluence_score >= 5 else 0.5,
            confidence=0.5,
            reasoning="No API key — rule-based fallback",
            used_claude=False,
        )

    strengths_text  = "\n".join(f"  + {s}" for s in technical.strengths)  or "  (none listed)"
    weaknesses_text = "\n".join(f"  - {w}" for w in technical.weaknesses) or "  (none listed)"

    prompt = f"""You are the final decision-maker for a BTC futures trading bot.

Strategy: {strategy} | Direction: {side}
Auto-reduce flag: {'YES (counter-trend or drawdown protection)' if auto_reduce else 'No'}

TECHNICAL ANALYSIS (score {technical.confluence_score}/10):
Strengths:
{strengths_text}
Weaknesses:
{weaknesses_text}
Summary: {technical.summary}

NEWS/MACRO ANALYSIS:
Score: {news.score} (-2=very bearish to +2=very bullish for this trade)
Verdict: {news.verdict}
Fear & Greed: {news.fear_greed}
Funding Rate: {news.funding_rate}
Summary: {news.summary}
Divergence detected: {'YES' if has_divergence else 'No'}

Make the final trading decision. Return ONLY valid JSON:
{{
  "action": "<GO|SKIP|REDUCE_SIZE|DOUBLE_SIZE>",
  "size_multiplier": <0.0|0.5|1.0|2.0>,
  "confidence": <0.0 to 1.0>,
  "reasoning": "<max 20 words>"
}}

Rules:
- GO (1.0x): Technical OK, macro neutral or supportive
- REDUCE_SIZE (0.5x): Mixed signals or auto-reduce flag active
- DOUBLE_SIZE (2.0x): Score>=8 AND macro supports AND divergence
- SKIP (0.0x): Score<=3 OR strongly contradicting macro"""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        text = text.replace("```json", "").replace("```", "").strip()
        data = json.loads(text)

        action = data.get("action", "GO")
        if action not in ("GO", "SKIP", "REDUCE_SIZE", "DOUBLE_SIZE"):
            action = "GO"

        size_map = {"GO": 1.0, "SKIP": 0.0, "REDUCE_SIZE": 0.5, "DOUBLE_SIZE": 2.0}

        return CoordinatorDecision(
            action          = action,
            size_multiplier = size_map.get(action, 1.0),
            confidence      = max(0.0, min(1.0, float(data.get("confidence", 0.7)))),
            reasoning       = data.get("reasoning", ""),
            used_claude     = True,
        )
    except Exception as e:
        log.error(f"[Coordinator] Claude error: {e}")
        # Fallback: conservative
        return CoordinatorDecision(
            action="REDUCE_SIZE",
            size_multiplier=0.5,
            confidence=0.5,
            reasoning=f"Claude error — conservative REDUCE_SIZE. Error: {str(e)[:40]}",
            used_claude=False,
            error=str(e),
        )


# ═══════════════════════════════════════════════════════════════
# Main function
# ═══════════════════════════════════════════════════════════════

def coordinate(
    strategy: str,
    side: str,
    technical: TechnicalAnalysis,
    news: NewsAnalysis,
    has_divergence: bool,
    auto_reduce: bool,
    anthropic_api_key: str,
    trades: list = None,
) -> CoordinatorDecision:
    """
    Κύρια συνάρτηση Coordinator.
    Πρώτα προσπαθεί rule-based, αν borderline → Claude.
    """
    trades = trades or []

    log.info(
        f"[Coordinator] Strategy={strategy} {side} | "
        f"Technical={technical.confluence_score}/10 ({technical.recommendation}) | "
        f"News={news.score} ({news.verdict}) | "
        f"div={has_divergence} auto_reduce={auto_reduce}"
    )

    # 1. Δοκίμασε rule-based πρώτα
    decision = _rule_based_decision(
        technical=technical, news=news,
        has_divergence=has_divergence, auto_reduce=auto_reduce,
        strategy=strategy, trades=trades,
    )

    if decision is not None:
        log.info(
            f"[Coordinator] Rule-based decision: {decision.action} "
            f"(conf={decision.confidence:.2f}) | {decision.reasoning}"
        )
        return decision

    # 2. Borderline → Claude
    log.info(f"[Coordinator] Borderline case (score={technical.confluence_score}) → calling Claude")
    decision = _ask_claude_coordinator(
        api_key=anthropic_api_key,
        strategy=strategy, side=side,
        technical=technical, news=news,
        has_divergence=has_divergence, auto_reduce=auto_reduce,
    )

    log.info(
        f"[Coordinator] Claude decision: {decision.action} "
        f"(conf={decision.confidence:.2f}) | {decision.reasoning}"
    )
    return decision
