"""
AI Validator — Technical Agent (Φάση 3.3)
══════════════════════════════════════════
Αναλύει το technical setup ενός συγκεκριμένου trade signal.

Χρησιμοποιεί:
  - RSI values (15m, 1H) που έχει ήδη το bot
  - Box levels (daily ή 1H)
  - Divergence flag
  - R/R ratio
  - Trend direction (από candles)

ΔΕΝ χρειάζεται ChromaDB/knowledge base σε αυτή τη φάση.
Θα προστεθεί στη Φάση 3.3b αν χρειαστεί.
"""

import json
import logging
from dataclasses import dataclass
from typing import Optional

import anthropic

log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# Result dataclass
# ═══════════════════════════════════════════════════════════════

@dataclass
class TechnicalAnalysis:
    """
    Αποτέλεσμα του Technical Agent.

    confluence_score: 0-10
      0-3:  Weak setup — λείπουν βασικά κριτήρια
      4-6:  Moderate setup — αρκετά κριτήρια ΟΚ
      7-9:  Strong setup — σχεδόν όλα συμφωνούν
      10:   Perfect confluence

    recommendation: 'GO', 'REDUCE', 'SKIP'
    """
    confluence_score: int = 5
    recommendation: str = "GO"          # GO / REDUCE / SKIP
    strengths: list = None
    weaknesses: list = None
    summary: str = ""
    error: Optional[str] = None

    def __post_init__(self):
        if self.strengths is None:
            self.strengths = []
        if self.weaknesses is None:
            self.weaknesses = []

    def to_dict(self) -> dict:
        return {
            "confluence_score": self.confluence_score,
            "recommendation":   self.recommendation,
            "strengths":        self.strengths,
            "weaknesses":       self.weaknesses,
            "summary":          self.summary,
        }


# ═══════════════════════════════════════════════════════════════
# Helper: Build context string για το Claude prompt
# ═══════════════════════════════════════════════════════════════

def _build_context(
    strategy: str,
    side: str,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    risk_reward: float,
    rsi_15m: float,
    rsi_1h: float,
    box: dict,
    has_divergence: bool,
    candles_4h: list,
    extra_context: dict,
    candles_15m: list = None,
) -> str:
    """Φτιάχνει το context string για το Claude prompt."""

    # Trend από 4H candles
    trend_info = "Unknown"
    if candles_4h and len(candles_4h) >= 20:
        closes   = [c["close"] for c in candles_4h[-20:]]
        ma_fast  = sum(closes[-5:]) / 5
        ma_slow  = sum(closes) / 20
        if ma_fast > ma_slow * 1.005:
            trend_info = "UPTREND (4H MA fast > slow)"
        elif ma_fast < ma_slow * 0.995:
            trend_info = "DOWNTREND (4H MA fast < slow)"
        else:
            trend_info = "SIDEWAYS (4H MAs flat)"

    # ── VOLUME ANALYSIS — confirmation από τα 15m candles ──
    volume_info = "N/A (no volume data)"
    cnd = candles_15m or candles_4h
    if cnd and len(cnd) >= 20:
        try:
            recent_vols = [c.get("volume", 0) for c in cnd[-20:]]
            current_vol = recent_vols[-1]
            avg_vol     = sum(recent_vols[:-1]) / max(len(recent_vols)-1, 1)
            ratio       = (current_vol / avg_vol) if avg_vol > 0 else 1.0

            # Volume on signal candle - σχέση με μέσο
            if ratio >= 2.0:
                vol_strength = "EXTREMELY HIGH (>2x avg) — strong confirmation"
            elif ratio >= 1.5:
                vol_strength = "HIGH (1.5-2x avg) — good confirmation"
            elif ratio >= 1.2:
                vol_strength = "ELEVATED (1.2-1.5x avg) — mild confirmation"
            elif ratio >= 0.8:
                vol_strength = "NORMAL (~average)"
            else:
                vol_strength = "LOW (<0.8x avg) — weak signal, no commitment"

            # Volume trend last 3 candles - ανοδικός;
            last3_vols = recent_vols[-3:]
            vol_trend = ""
            if len(last3_vols) == 3:
                if last3_vols[2] > last3_vols[1] > last3_vols[0]:
                    vol_trend = " | Volume increasing (3 candles)"
                elif last3_vols[2] < last3_vols[1] < last3_vols[0]:
                    vol_trend = " | Volume decreasing (exhaustion?)"

            volume_info = f"{vol_strength} (ratio {ratio:.2f}){vol_trend}"
        except Exception:
            volume_info = "Error calculating volume"

    # Box info
    box_info = "N/A"
    if box:
        box_size = box.get("high", 0) - box.get("low", 0)
        dist_from_level = abs(entry_price - (box.get("low") if side == "LONG" else box.get("high", 0)))
        dist_pct = (dist_from_level / entry_price * 100) if entry_price > 0 else 0
        box_info = (
            f"High={box.get('high', '?'):,.0f} "
            f"Low={box.get('low', '?'):,.0f} "
            f"Mid={box.get('mid', '?'):,.0f} "
            f"Size={box_size:,.0f} "
            f"Distance from level: {dist_pct:.2f}%"
        )

    # RSI interpretation
    rsi_context = ""
    if side == "LONG":
        if rsi_15m < 25:
            rsi_context = "RSI 15m extremely oversold (<25) — strong signal but possible capitulation"
        elif rsi_15m < 30:
            rsi_context = "RSI 15m oversold (<30) — valid LONG signal"
        elif rsi_15m < 40:
            rsi_context = "RSI 15m below midpoint — neutral to mild bullish"
        else:
            rsi_context = f"RSI 15m={rsi_15m} — NOT oversold for LONG"
    else:  # SHORT
        if rsi_15m > 75:
            rsi_context = "RSI 15m extremely overbought (>75) — strong signal but possible blow-off"
        elif rsi_15m > 70:
            rsi_context = "RSI 15m overbought (>70) — valid SHORT signal"
        elif rsi_15m > 60:
            rsi_context = "RSI 15m above midpoint — neutral to mild bearish"
        else:
            rsi_context = f"RSI 15m={rsi_15m} — NOT overbought for SHORT"

    # Extra context (OB/FVG για Strategy D, κλπ)
    extra_lines = ""
    if extra_context:
        relevant = {k: v for k, v in extra_context.items()
                   if k not in ("auto_reduce", "auto_reduce_reason", "from_cache")}
        if relevant:
            extra_lines = "\nExtra context:\n" + "\n".join(f"  {k}: {v}" for k, v in relevant.items())

    return f"""Strategy: {strategy} | Side: {side}
Entry: ${entry_price:,.2f} | SL: ${stop_loss:,.2f} | TP: ${take_profit:,.2f} | R/R: {risk_reward:.2f}

RSI 15m: {rsi_15m} | RSI 1H: {rsi_1h}
RSI interpretation: {rsi_context}

4H Trend: {trend_info}
Volume (15m): {volume_info}
Box ({strategy} box): {box_info}
Divergence: {'YES — increases conviction' if has_divergence else 'No'}
{extra_lines}"""


# ═══════════════════════════════════════════════════════════════
# Claude call
# ═══════════════════════════════════════════════════════════════

def _ask_claude_technical(api_key: str, context: str, side: str) -> dict:
    """Καλεί Claude Haiku για technical analysis."""
    if not api_key:
        return {
            "confluence_score": 5,
            "recommendation": "GO",
            "strengths": [],
            "weaknesses": [],
            "summary": "No API key — defaulting to GO",
        }

    prompt = f"""You are a technical analyst for a BTC futures trading bot using box trading and RSI strategies.

Analyze this specific trade setup and return ONLY valid JSON:

{context}

Return ONLY this JSON (no markdown, no explanation):
{{
  "confluence_score": <integer 0-10>,
  "recommendation": "<GO|REDUCE|SKIP>",
  "strengths": ["<strength 1>", "<strength 2>"],
  "weaknesses": ["<weakness 1>"],
  "summary": "<max 15 words>"
}}

Scoring guide:
  10: Perfect — RSI extreme + at key level + divergence + with trend + HIGH volume confirmation
  7-9: Strong — most criteria met (volume should be elevated or higher)
  4-6: Moderate — some criteria met, proceed with caution
  0-3: Weak — key criteria missing OR low volume (no commitment), consider skipping

Volume rules:
  - HIGH/EXTREMELY HIGH volume on signal candle = strong confirmation (+1 to score)
  - LOW volume on signal candle = weak signal, no commitment (-1 to score)
  - Divergence WITHOUT volume confirmation = unreliable

recommendation:
  GO:     confluence_score >= 6
  REDUCE: confluence_score 4-5 (take trade with smaller size)
  SKIP:   confluence_score <= 3 (setup not valid)"""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        text = text.replace("```json", "").replace("```", "").strip()
        data = json.loads(text)
        return {
            "confluence_score": max(0, min(10, int(data.get("confluence_score", 5)))),
            "recommendation":   data.get("recommendation", "GO"),
            "strengths":        data.get("strengths", []),
            "weaknesses":       data.get("weaknesses", []),
            "summary":          data.get("summary", ""),
        }
    except Exception as e:
        log.error(f"[TechnicalAgent] Claude error: {e}")
        return {
            "confluence_score": 5,
            "recommendation": "GO",
            "strengths": [],
            "weaknesses": [f"Analysis error: {str(e)[:50]}"],
            "summary": "Error in analysis — defaulting to GO",
        }


# ═══════════════════════════════════════════════════════════════
# Main function
# ═══════════════════════════════════════════════════════════════

def analyze_technical(
    strategy: str,
    side: str,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    risk_reward: float,
    rsi_15m: float,
    rsi_1h: float,
    box: dict,
    has_divergence: bool,
    anthropic_api_key: str,
    candles_4h: list = None,
    extra_context: dict = None,
    candles_15m: list = None,
) -> TechnicalAnalysis:
    """
    Κύρια συνάρτηση Technical Agent.
    Καλείται από τον Coordinator.
    """
    candles_4h    = candles_4h or []
    extra_context = extra_context or {}

    log.info(
        f"[TechnicalAgent] Strategy={strategy} {side} @ {entry_price:.2f} "
        f"RSI_15m={rsi_15m} RSI_1h={rsi_1h} div={has_divergence}"
    )

    # Build context string
    context = _build_context(
        strategy=strategy, side=side,
        entry_price=entry_price, stop_loss=stop_loss, take_profit=take_profit,
        risk_reward=risk_reward, rsi_15m=rsi_15m, rsi_1h=rsi_1h,
        box=box, has_divergence=has_divergence,
        candles_4h=candles_4h, extra_context=extra_context,
        candles_15m=candles_15m,
    )

    # Claude call
    result_data = _ask_claude_technical(anthropic_api_key, context, side)

    result = TechnicalAnalysis(
        confluence_score = result_data["confluence_score"],
        recommendation   = result_data["recommendation"],
        strengths        = result_data["strengths"],
        weaknesses       = result_data["weaknesses"],
        summary          = result_data["summary"],
    )

    log.info(
        f"[TechnicalAgent] Score={result.confluence_score}/10 "
        f"Rec={result.recommendation} | {result.summary}"
    )
    return result
