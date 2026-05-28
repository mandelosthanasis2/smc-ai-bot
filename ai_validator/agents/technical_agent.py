"""
AI Validator — Technical Agent (v2)
════════════════════════════════════
Multi-timeframe holistic analysis.

Κοιτάει:
  • Trend alignment (1D, 4H, 1H)
  • Key levels (S/R, Order Blocks, FVGs)
  • SFP (Swing Failure Pattern)
  • RSI divergence
  • Volume confirmation
  • Session timing (London/NY overlap)
  • 5m micro-structure για fine entry
  • News/macro (από News Agent)
  • Knowledge Base context

Φιλοσοφία: balanced — δεν ψάχνει τέλειο setup,
αξιολογεί συνολικά και αποφασίζει έξυπνα.
"""

import json
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import anthropic

log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# Result dataclass
# ═══════════════════════════════════════════════════════════════

@dataclass
class TechnicalAnalysis:
    confluence_score: int = 5
    recommendation:   str = "GO"
    strengths:        list = None
    weaknesses:       list = None
    summary:          str = ""
    error:            Optional[str] = None

    def __post_init__(self):
        if self.strengths  is None: self.strengths  = []
        if self.weaknesses is None: self.weaknesses = []

    def to_dict(self) -> dict:
        return {
            "confluence_score": self.confluence_score,
            "recommendation":   self.recommendation,
            "strengths":        self.strengths,
            "weaknesses":       self.weaknesses,
            "summary":          self.summary,
        }


# ═══════════════════════════════════════════════════════════════
# Knowledge Base (optional)
# ═══════════════════════════════════════════════════════════════

try:
    from knowledge_retriever_railway import get_context_for_trade
    KB_AVAILABLE = True
    log.info("[TechnicalAgent] Knowledge base loaded")
except Exception as _kb_err:
    KB_AVAILABLE = False
    def get_context_for_trade(*a, **kw): return ""
    log.warning(f"[TechnicalAgent] KB not available: {_kb_err}")


# ═══════════════════════════════════════════════════════════════
# Helper: RSI calculation
# ═══════════════════════════════════════════════════════════════

def _calc_rsi(closes: list, period: int = 14) -> float:
    """Wilder RSI."""
    if len(closes) < period + 2:
        return 50.0
    gains, losses = [], []
    for i in range(1, period + 1):
        d = closes[i] - closes[i-1]
        gains.append(max(d, 0)); losses.append(max(-d, 0))
    avg_g = sum(gains) / period
    avg_l = sum(losses) / period
    for i in range(period + 1, len(closes)):
        d = closes[i] - closes[i-1]
        avg_g = (avg_g * (period-1) + max(d, 0))  / period
        avg_l = (avg_l * (period-1) + max(-d, 0)) / period
    if avg_l == 0: return 100.0
    return round(100 - 100 / (1 + avg_g / avg_l), 2)


# ═══════════════════════════════════════════════════════════════
# Helper: Trend detection
# ═══════════════════════════════════════════════════════════════

def _detect_trend(candles: list, fast: int = 20, slow: int = 50) -> str:
    """Trend από MA crossover."""
    if not candles or len(candles) < slow + 1:
        return "UNKNOWN"
    closes = [c["close"] for c in candles]
    ma_fast = sum(closes[-fast:]) / fast
    ma_slow = sum(closes[-slow:]) / slow
    if ma_fast > ma_slow * 1.005:
        return "BULLISH"
    elif ma_fast < ma_slow * 0.995:
        return "BEARISH"
    return "SIDEWAYS"


# ═══════════════════════════════════════════════════════════════
# Helper: Order Block detection
# ═══════════════════════════════════════════════════════════════

def _find_order_blocks(candles: list, lookback: int = 20) -> dict:
    """
    Βρίσκει Order Blocks: το τελευταίο bearish/bullish candle
    πριν από μια ισχυρή κίνηση.
    """
    if not candles or len(candles) < 5:
        return {"bullish_ob": None, "bearish_ob": None}

    recent = candles[-lookback:] if len(candles) >= lookback else candles
    bullish_ob = None
    bearish_ob = None

    for i in range(len(recent) - 3):
        c     = recent[i]
        c_next = recent[i+1]
        c_nn   = recent[i+2]

        # Bullish OB: bearish candle ακολουθείται από 2 bullish candles
        if (c["close"] < c["open"] and
            c_next["close"] > c_next["open"] and
            c_nn["close"] > c_nn["open"] and
            c_nn["close"] > c["high"]):
            bullish_ob = {"high": c["high"], "low": c["low"],
                          "mid": round((c["high"]+c["low"])/2, 2)}

        # Bearish OB: bullish candle ακολουθείται από 2 bearish candles
        if (c["close"] > c["open"] and
            c_next["close"] < c_next["open"] and
            c_nn["close"] < c_nn["open"] and
            c_nn["close"] < c["low"]):
            bearish_ob = {"high": c["high"], "low": c["low"],
                          "mid": round((c["high"]+c["low"])/2, 2)}

    return {"bullish_ob": bullish_ob, "bearish_ob": bearish_ob}


# ═══════════════════════════════════════════════════════════════
# Helper: FVG detection
# ═══════════════════════════════════════════════════════════════

def _find_fvg(candles: list, lookback: int = 20) -> dict:
    """
    Fair Value Gap: gap μεταξύ candle[i].high και candle[i+2].low (bullish)
    ή candle[i].low και candle[i+2].high (bearish).
    """
    if not candles or len(candles) < 3:
        return {"bullish_fvg": None, "bearish_fvg": None}

    recent = candles[-lookback:] if len(candles) >= lookback else candles
    bullish_fvg = None
    bearish_fvg = None

    for i in range(len(recent) - 2):
        c1 = recent[i]
        c3 = recent[i+2]

        # Bullish FVG: c1.high < c3.low (gap up)
        if c1["high"] < c3["low"]:
            bullish_fvg = {
                "top":    c3["low"],
                "bottom": c1["high"],
                "mid":    round((c3["low"] + c1["high"]) / 2, 2),
            }

        # Bearish FVG: c1.low > c3.high (gap down)
        if c1["low"] > c3["high"]:
            bearish_fvg = {
                "top":    c1["low"],
                "bottom": c3["high"],
                "mid":    round((c1["low"] + c3["high"]) / 2, 2),
            }

    return {"bullish_fvg": bullish_fvg, "bearish_fvg": bearish_fvg}


# ═══════════════════════════════════════════════════════════════
# Helper: SFP detection
# ═══════════════════════════════════════════════════════════════

def _detect_sfp(candles: list, lookback: int = 10) -> dict:
    """
    Swing Failure Pattern: τιμή σπάει previous high/low αλλά
    κλείνει πίσω από αυτό (false breakout / liquidity sweep).
    """
    if not candles or len(candles) < lookback + 1:
        return {"bullish_sfp": False, "bearish_sfp": False}

    recent  = candles[-(lookback+1):]
    current = recent[-1]
    prev    = recent[:-1]

    prev_highs = [c["high"] for c in prev]
    prev_lows  = [c["low"]  for c in prev]

    prev_high = max(prev_highs)
    prev_low  = min(prev_lows)

    # Bearish SFP: spike above prev_high αλλά close κάτω
    bearish_sfp = (
        current["high"] > prev_high and
        current["close"] < prev_high and
        current["close"] < current["open"]
    )

    # Bullish SFP: spike below prev_low αλλά close πάνω
    bullish_sfp = (
        current["low"] < prev_low and
        current["close"] > prev_low and
        current["close"] > current["open"]
    )

    return {
        "bullish_sfp":  bullish_sfp,
        "bearish_sfp":  bearish_sfp,
        "prev_high":    round(prev_high, 2),
        "prev_low":     round(prev_low, 2),
    }


# ═══════════════════════════════════════════════════════════════
# Helper: Key S/R levels
# ═══════════════════════════════════════════════════════════════

def _find_key_levels(candles_1h: list, candles_4h: list,
                      candles_1d: list, price: float) -> dict:
    """
    Βρίσκει σημαντικά S/R levels από πολλά TF.
    """
    levels = []

    for candles, tf in [(candles_1d, "1D"), (candles_4h, "4H"), (candles_1h, "1H")]:
        if not candles or len(candles) < 5:
            continue
        recent = candles[-30:] if len(candles) >= 30 else candles
        # Previous highs/lows ως S/R
        for c in recent[-5:]:
            levels.append({"price": c["high"], "type": "resistance", "tf": tf})
            levels.append({"price": c["low"],  "type": "support",    "tf": tf})

    if not levels or price <= 0:
        return {"nearest_support": None, "nearest_resistance": None, "levels": []}

    # Βρες τα πιο κοντινά levels
    supports    = [l for l in levels if l["price"] < price]
    resistances = [l for l in levels if l["price"] > price]

    nearest_sup = max(supports,    key=lambda x: x["price"]) if supports    else None
    nearest_res = min(resistances, key=lambda x: x["price"]) if resistances else None

    return {
        "nearest_support":    nearest_sup,
        "nearest_resistance": nearest_res,
    }


# ═══════════════════════════════════════════════════════════════
# Helper: Volume analysis
# ═══════════════════════════════════════════════════════════════

def _analyze_volume(candles: list) -> dict:
    """Volume confirmation."""
    if not candles or len(candles) < 10:
        return {"signal": "UNKNOWN", "ratio": 1.0}

    vols    = [c.get("volume", 0) for c in candles]
    cur_vol = vols[-1]
    avg_vol = sum(vols[:-1]) / max(len(vols)-1, 1)

    if avg_vol == 0:
        return {"signal": "UNKNOWN", "ratio": 1.0}

    ratio = cur_vol / avg_vol

    if   ratio >= 2.0: signal = "EXTREMELY_HIGH"
    elif ratio >= 1.5: signal = "HIGH"
    elif ratio >= 1.2: signal = "ELEVATED"
    elif ratio >= 0.8: signal = "NORMAL"
    else:              signal = "LOW"

    return {"signal": signal, "ratio": round(ratio, 2)}


# ═══════════════════════════════════════════════════════════════
# Helper: Session timing
# ═══════════════════════════════════════════════════════════════

def _get_session_info() -> dict:
    """Τρέχουσα trading session (UTC)."""
    now  = datetime.now(timezone.utc)
    hour = now.hour

    # London: 08:00-17:00 UTC
    # New York: 13:00-22:00 UTC
    # Overlap: 13:00-17:00 UTC (best liquidity)
    # Asia: 00:00-09:00 UTC

    if 13 <= hour < 17:
        session, quality = "LONDON/NY OVERLAP", "EXCELLENT"
    elif 8 <= hour < 17:
        session, quality = "LONDON", "GOOD"
    elif 13 <= hour < 22:
        session, quality = "NEW YORK", "GOOD"
    elif 0 <= hour < 9:
        session, quality = "ASIA", "MODERATE"
    else:
        session, quality = "OFF-HOURS", "LOW"

    return {
        "session":     session,
        "quality":     quality,
        "hour_utc":    hour,
        "good_session": quality in ("EXCELLENT", "GOOD"),
    }


# ═══════════════════════════════════════════════════════════════
# Helper: RSI divergence
# ═══════════════════════════════════════════════════════════════

def _detect_divergence(candles: list, lookback: int = 20) -> dict:
    """Ανιχνεύει RSI divergence."""
    if not candles or len(candles) < lookback + 14:
        return {"bullish_div": False, "bearish_div": False}

    recent = candles[-lookback:]
    closes = [c["close"] for c in candles]
    highs  = [c["high"]  for c in recent]
    lows   = [c["low"]   for c in recent]

    # RSI για τα recent candles
    rsi_values = []
    offset = len(closes) - lookback
    for i in range(lookback):
        rsi_values.append(_calc_rsi(closes[:offset+i+1]))

    if len(rsi_values) < 4:
        return {"bullish_div": False, "bearish_div": False}

    # Bullish div: price κάνει lower low, RSI κάνει higher low
    price_ll = lows[-1] < min(lows[:-1])
    rsi_hl   = rsi_values[-1] > min(rsi_values[:-1])
    bull_div = price_ll and rsi_hl

    # Bearish div: price κάνει higher high, RSI κάνει lower high
    price_hh = highs[-1] > max(highs[:-1])
    rsi_lh   = rsi_values[-1] < max(rsi_values[:-1])
    bear_div = price_hh and rsi_lh

    return {"bullish_div": bull_div, "bearish_div": bear_div}


# ═══════════════════════════════════════════════════════════════
# Build context για Claude
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
    candles_15m: list,
    candles_1h: list  = None,
    candles_5m: list  = None,
    candles_1d: list  = None,
    extra_context: dict = None,
) -> str:

    candles_1h  = candles_1h  or []
    candles_5m  = candles_5m  or []
    candles_1d  = candles_1d  or []
    extra_context = extra_context or {}

    # ── Trend ──────────────────────────────────────────────
    trend_1d = _detect_trend(candles_1d, fast=10, slow=20)
    trend_4h = _detect_trend(candles_4h, fast=20, slow=50)
    trend_1h = _detect_trend(candles_1h, fast=20, slow=50) if candles_1h else "UNKNOWN"

    is_long = side == "LONG"
    trend_aligned = (
        (is_long  and trend_4h == "BULLISH") or
        (not is_long and trend_4h == "BEARISH")
    )

    # ── Order Blocks ───────────────────────────────────────
    ob_4h = _find_order_blocks(candles_4h)
    ob_1h = _find_order_blocks(candles_1h) if candles_1h else {"bullish_ob": None, "bearish_ob": None}
    ob_5m = _find_order_blocks(candles_5m) if candles_5m else {"bullish_ob": None, "bearish_ob": None}

    # OB κοντά στο entry price (εντός 1%)
    def _ob_near_entry(ob_dict):
        ob = ob_dict.get("bullish_ob" if is_long else "bearish_ob")
        if ob and entry_price > 0:
            dist_pct = abs(entry_price - ob["mid"]) / entry_price * 100
            return dist_pct < 1.0, ob
        return False, None

    ob_4h_near, ob_4h_data = _ob_near_entry(ob_4h)
    ob_1h_near, ob_1h_data = _ob_near_entry(ob_1h)
    ob_5m_near, ob_5m_data = _ob_near_entry(ob_5m)

    # ── FVG ────────────────────────────────────────────────
    fvg_1h = _find_fvg(candles_1h) if candles_1h else {"bullish_fvg": None, "bearish_fvg": None}
    fvg_4h = _find_fvg(candles_4h)
    fvg_5m = _find_fvg(candles_5m) if candles_5m else {"bullish_fvg": None, "bearish_fvg": None}

    fvg_key = "bullish_fvg" if is_long else "bearish_fvg"
    fvg_near_1h = fvg_1h.get(fvg_key)
    fvg_near_4h = fvg_4h.get(fvg_key)

    # ── SFP ────────────────────────────────────────────────
    sfp_15m = _detect_sfp(candles_15m) if candles_15m else {"bullish_sfp": False, "bearish_sfp": False}
    sfp_5m  = _detect_sfp(candles_5m)  if candles_5m  else {"bullish_sfp": False, "bearish_sfp": False}

    sfp_confirms = (
        (is_long  and (sfp_15m["bullish_sfp"] or sfp_5m["bullish_sfp"])) or
        (not is_long and (sfp_15m["bearish_sfp"] or sfp_5m["bearish_sfp"]))
    )

    # ── Volume ─────────────────────────────────────────────
    vol_15m = _analyze_volume(candles_15m) if candles_15m else {"signal": "UNKNOWN", "ratio": 1.0}
    vol_5m  = _analyze_volume(candles_5m)  if candles_5m  else {"signal": "UNKNOWN", "ratio": 1.0}

    # ── Divergence ─────────────────────────────────────────
    div_15m = _detect_divergence(candles_15m) if len(candles_15m or []) > 20 else {"bullish_div": False, "bearish_div": False}
    div_5m  = _detect_divergence(candles_5m)  if len(candles_5m  or []) > 20 else {"bullish_div": False, "bearish_div": False}

    div_key = "bullish_div" if is_long else "bearish_div"
    has_rsi_div = has_divergence or div_15m.get(div_key) or div_5m.get(div_key)

    # ── RSI ────────────────────────────────────────────────
    rsi_5m  = _calc_rsi([c["close"] for c in candles_5m])  if candles_5m  else 50.0
    rsi_4h  = _calc_rsi([c["close"] for c in candles_4h])  if candles_4h  else 50.0
    rsi_1d  = _calc_rsi([c["close"] for c in candles_1d])  if candles_1d  else 50.0

    # ── Key Levels ─────────────────────────────────────────
    key_levels = _find_key_levels(candles_1h, candles_4h, candles_1d, entry_price)

    # ── Session ────────────────────────────────────────────
    session = _get_session_info()

    # ── Box info ───────────────────────────────────────────
    box_info = "N/A"
    if box:
        box_size = box.get("high", 0) - box.get("low", 0)
        dist = abs(entry_price - (box.get("low") if is_long else box.get("high", 0)))
        dist_pct = (dist / entry_price * 100) if entry_price > 0 else 0
        box_info = (
            f"H={box.get('high','?'):,.0f} "
            f"L={box.get('low','?'):,.0f} "
            f"Mid={box.get('mid','?'):,.0f} "
            f"Size={box_size:,.0f} "
            f"Distance={dist_pct:.2f}%"
        )

    # ── Extra (για strategy D) ─────────────────────────────
    extra_lines = ""
    if extra_context:
        relevant = {k: v for k, v in extra_context.items()
                    if k not in ("auto_reduce","auto_reduce_reason","from_cache")}
        if relevant:
            extra_lines = "\nExtra: " + " | ".join(f"{k}={v}" for k,v in relevant.items())

    # ── KB Context ─────────────────────────────────────────
    kb_context = ""
    if KB_AVAILABLE:
        try:
            kb_context = get_context_for_trade(strategy, side, entry_price, stop_loss, take_profit)
        except Exception:
            pass

    # ── Assemble ───────────────────────────────────────────
    ctx = f"""=== TRADE SIGNAL ===
Strategy: {strategy} | Side: {side}
Entry: ${entry_price:,.2f} | SL: ${stop_loss:,.2f} | TP: ${take_profit:,.2f} | R/R: {risk_reward:.1f}

=== MULTI-TIMEFRAME TREND ===
1D Trend:  {trend_1d}
4H Trend:  {trend_4h}  {"✅ ALIGNED" if trend_aligned else "⚠️ COUNTER-TREND"}
1H Trend:  {trend_1h}
Trend aligned with trade: {"YES" if trend_aligned else "NO"}

=== RSI MULTI-TIMEFRAME ===
1D RSI: {rsi_1d:.1f}
4H RSI: {rsi_4h:.1f}
1H RSI: {rsi_1h:.1f}
15m RSI: {rsi_15m:.1f}
5m RSI: {rsi_5m:.1f}

=== KEY LEVELS & STRUCTURE ===
Strategy Box: {box_info}
Nearest Support:    ${key_levels['nearest_support']['price']:,.2f} [{key_levels['nearest_support']['tf']}]  if key_levels['nearest_support'] else N/A
Nearest Resistance: ${key_levels['nearest_resistance']['price']:,.2f} [{key_levels['nearest_resistance']['tf']}] if key_levels['nearest_resistance'] else N/A

=== ORDER BLOCKS ===
4H OB near entry: {"YES — " + str(ob_4h_data) if ob_4h_near else "No"}
1H OB near entry: {"YES — " + str(ob_1h_data) if ob_1h_near else "No"}
5m OB near entry: {"YES — " + str(ob_5m_data) if ob_5m_near else "No"}

=== FAIR VALUE GAPS ===
4H FVG ({side}): {"YES — " + str(fvg_near_4h) if fvg_near_4h else "No"}
1H FVG ({side}): {"YES — " + str(fvg_near_1h) if fvg_near_1h else "No"}

=== SFP (Swing Failure Pattern) ===
15m SFP confirms {side}: {"YES ✅" if (is_long and sfp_15m["bullish_sfp"]) or (not is_long and sfp_15m["bearish_sfp"]) else "No"}
5m  SFP confirms {side}: {"YES ✅" if (is_long and sfp_5m["bullish_sfp"]) or (not is_long and sfp_5m["bearish_sfp"]) else "No"}
Overall SFP: {"CONFIRMED ✅" if sfp_confirms else "Not detected"}

=== RSI DIVERGENCE ===
Has divergence: {"YES ✅" if has_rsi_div else "No"}
15m: bull={div_15m['bullish_div']} bear={div_15m['bearish_div']}
5m:  bull={div_5m['bullish_div']}  bear={div_5m['bearish_div']}

=== VOLUME ===
15m Volume: {vol_15m['signal']} (ratio {vol_15m['ratio']:.2f}x avg)
5m  Volume: {vol_5m['signal']}  (ratio {vol_5m['ratio']:.2f}x avg)

=== SESSION TIMING ===
Session: {session['session']} | Quality: {session['quality']}
Hour UTC: {session['hour_utc']}:00
Good timing: {"YES ✅" if session['good_session'] else "Poor ⚠️"}
{extra_lines}"""

    if kb_context:
        ctx += f"\n\n{kb_context}"

    return ctx


# ═══════════════════════════════════════════════════════════════
# Claude call
# ═══════════════════════════════════════════════════════════════

def _ask_claude(api_key: str, context: str, side: str) -> dict:
    if not api_key:
        return {
            "confluence_score": 5, "recommendation": "GO",
            "strengths": [], "weaknesses": [],
            "summary": "No API key — defaulting to GO",
        }

    prompt = f"""You are an experienced BTC futures trader and technical analyst.
A trade signal has been generated. Analyze ALL the data below and make a balanced decision.

{context}

IMPORTANT PHILOSOPHY:
- Perfect setups don't exist. Don't require everything to align.
- Weigh positives vs negatives holistically.
- Score 5-6 = uncertain = still GO (default to trading)
- Only SKIP for clear red flags (strong counter-trend + bad timing + no confirmation)
- Only DOUBLE_SIZE for exceptional confluence (5+ confirmations)

Return ONLY valid JSON (no markdown, no explanation):
{{
  "confluence_score": <integer 0-10>,
  "recommendation": "<GO|REDUCE|SKIP>",
  "strengths": ["<max 3 key positives>"],
  "weaknesses": ["<max 3 key concerns>"],
  "summary": "<max 15 words, specific>"
}}

Scoring:
  8-10: Exceptional — trend + OB/FVG + SFP + divergence + good session
  6-7:  Good — trend aligned + some confirmation
  4-5:  Neutral — mixed signals, trade with normal size
  2-3:  Weak — counter-trend or major red flags
  0-1:  Very weak — strong reversal signs against the trade

recommendation:
  GO:     score >= 4
  REDUCE: score 2-3 (trade with 0.5x size)
  SKIP:   score <= 1 (clear bad trade)"""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp   = client.messages.create(
            model      = "claude-haiku-4-5-20251001",
            max_tokens = 400,
            messages   = [{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        text = text.replace("```json","").replace("```","").strip()
        start = text.find("{"); end = text.rfind("}")
        if start == -1 or end == -1:
            raise ValueError("No JSON in response")
        data = json.loads(text[start:end+1])

        score = max(0, min(10, int(data.get("confluence_score", 5))))
        rec   = data.get("recommendation", "GO")
        if rec not in ("GO","REDUCE","SKIP"): rec = "GO"

        return {
            "confluence_score": score,
            "recommendation":   rec,
            "strengths":        data.get("strengths",  [])[:3],
            "weaknesses":       data.get("weaknesses", [])[:3],
            "summary":          data.get("summary", ""),
        }

    except Exception as e:
        log.error(f"[TechnicalAgent] Claude error: {e}")
        return {
            "confluence_score": 5, "recommendation": "GO",
            "strengths": [], "weaknesses": [f"Analysis error: {str(e)[:50]}"],
            "summary": "Error — defaulting to GO",
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
    candles_4h:  list = None,
    extra_context: dict = None,
    candles_15m: list = None,
    candles_1h:  list = None,
    candles_5m:  list = None,
    candles_1d:  list = None,
) -> TechnicalAnalysis:

    log.info(
        f"[TechnicalAgent] {strategy} {side} @ {entry_price:.2f} "
        f"RSI_15m={rsi_15m} RSI_1h={rsi_1h} div={has_divergence} "
        f"TF: 4H={'✓' if candles_4h else '✗'} "
        f"1H={'✓' if candles_1h else '✗'} "
        f"5m={'✓' if candles_5m else '✗'} "
        f"1D={'✓' if candles_1d else '✗'}"
    )

    context = _build_context(
        strategy=strategy, side=side,
        entry_price=entry_price, stop_loss=stop_loss,
        take_profit=take_profit, risk_reward=risk_reward,
        rsi_15m=rsi_15m, rsi_1h=rsi_1h,
        box=box, has_divergence=has_divergence,
        candles_4h=candles_4h or [],
        candles_15m=candles_15m or [],
        candles_1h=candles_1h or [],
        candles_5m=candles_5m or [],
        candles_1d=candles_1d or [],
        extra_context=extra_context or {},
    )

    data = _ask_claude(anthropic_api_key, context, side)

    result = TechnicalAnalysis(
        confluence_score = data["confluence_score"],
        recommendation   = data["recommendation"],
        strengths        = data["strengths"],
        weaknesses       = data["weaknesses"],
        summary          = data["summary"],
    )

    log.info(
        f"[TechnicalAgent] Score={result.confluence_score}/10 "
        f"Rec={result.recommendation} | {result.summary}"
    )
    return result
