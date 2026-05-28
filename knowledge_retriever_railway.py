"""
knowledge_retriever_railway.py
==============================
Railway-compatible knowledge retriever.
Χρησιμοποιεί knowledge_base.json (χωρίς ChromaDB).
Keyword + TF-IDF search για γρήγορο retrieval.
"""

import json
import math
import os
import re
from pathlib import Path
from collections import defaultdict

# ── Φόρτωσε το JSON μία φορά ──────────────────────────────────
_KB_PATH   = os.path.join(os.path.dirname(__file__), "knowledge_base.json")
_chunks    = []
_tfidf     = {}  # term → {chunk_idx: tf-idf score}
_loaded    = False

def _load():
    global _chunks, _tfidf, _loaded
    if _loaded:
        return

    if not Path(_KB_PATH).exists():
        print(f"[KB] knowledge_base.json not found at {_KB_PATH}")
        _loaded = True
        return

    with open(_KB_PATH, encoding="utf-8") as f:
        data = json.load(f)

    _chunks = data.get("chunks", [])
    print(f"[KB] Loaded {len(_chunks)} chunks from knowledge_base.json")

    # Φτιάξε TF-IDF index
    _build_tfidf()
    _loaded = True

def _tokenize(text):
    """Απλό tokenization — lowercase words."""
    return re.findall(r'[a-z]+', text.lower())

def _build_tfidf():
    """Φτιάχνει TF-IDF index για γρήγορο search."""
    global _tfidf
    N = len(_chunks)
    if N == 0:
        return

    # Document frequency
    df = defaultdict(int)
    chunk_tokens = []
    for c in _chunks:
        tokens = set(_tokenize(c["text"] + " " + c.get("source","") + " " + c.get("category","")))
        chunk_tokens.append(tokens)
        for t in tokens:
            df[t] += 1

    # TF-IDF
    _tfidf = defaultdict(dict)
    for idx, (chunk, tokens) in enumerate(zip(_chunks, chunk_tokens)):
        all_tokens = _tokenize(chunk["text"])
        total = len(all_tokens) or 1
        tf_count = defaultdict(int)
        for t in all_tokens:
            tf_count[t] += 1
        for t, cnt in tf_count.items():
            tf  = cnt / total
            idf = math.log(N / (df[t] + 1))
            _tfidf[t][idx] = tf * idf

def _score_chunk(idx, query_tokens):
    """Score ενός chunk για δοθέν query."""
    score = 0.0
    for t in query_tokens:
        if t in _tfidf and idx in _tfidf[t]:
            score += _tfidf[t][idx]
    return score

def search(query, n=5, category=None):
    """
    Βρίσκει τα πιο σχετικά chunks για το query.
    """
    _load()
    if not _chunks:
        return []

    query_tokens = _tokenize(query)
    if not query_tokens:
        return []

    # Score όλα τα chunks
    scores = []
    for idx, chunk in enumerate(_chunks):
        if category and chunk.get("category") != category:
            continue
        score = _score_chunk(idx, query_tokens)
        if score > 0:
            scores.append((score, idx))

    # Ταξινόμηση + top-n
    scores.sort(reverse=True)
    results = []
    for score, idx in scores[:n]:
        c = _chunks[idx]
        results.append({
            "text":      c["text"],
            "source":    c.get("source", "unknown"),
            "category":  c.get("category", "general"),
            "relevance": round(score, 4),
        })

    return results

def get_context(query, max_chunks=6):
    """
    Φτιάχνει context string για τον Technical Agent.
    """
    _load()
    if not _chunks:
        return ""

    # Multi-query για καλύτερο coverage
    queries = [
        (query, None),
        ("order block entry confirmation signal", "smc_ict"),
        ("stop loss risk management position size", "risk_management"),
    ]

    seen, all_results = set(), []
    for q, cat in queries:
        for r in search(q, n=4, category=cat):
            key = r["text"][:80]
            if key not in seen and r["relevance"] > 0.001:
                seen.add(key)
                all_results.append(r)

    if not all_results:
        return ""

    # Ταξινόμηση και top-max_chunks
    all_results.sort(key=lambda x: x["relevance"], reverse=True)
    top = all_results[:max_chunks]

    sep = "-" * 40
    parts = ["## KNOWLEDGE BASE — Relevant Rules"]
    for i, r in enumerate(top, 1):
        header = f"### [{i}] {r['source'].upper()} ({r['category']})"
        body   = r["text"][:500]
        parts.append(header)
        parts.append(body)
        parts.append(sep)
    return "\n".join(parts)

def get_context_for_trade(strategy, side, entry, stop_loss, take_profit):
    """
    Context ειδικά για ένα trade signal — στοχευμένο ανά στρατηγική.

    Strategy A/B/C: Box + RSI → ψάχνει RSI rules, S/R, risk management
    Strategy D: OB + FVG + CHoCH → ψάχνει ICT/SMC concepts
    """
    _load()
    if not _chunks:
        return ""

    if strategy in ("A", "B", "C"):
        # Box + RSI strategies — ψάχνε για γενικά trading rules
        queries = [
            (f"RSI overbought oversold {side} signal confirmation", None),
            ("support resistance level key price rejection", "technical"),
            ("stop loss position sizing risk percent trade", "risk_management"),
            ("candlestick pattern confirmation entry signal", "candlesticks"),
            ("swing trading trend following momentum", "swing_trading"),
        ]
    else:  # Strategy D — ICT/SMC
        queries = [
            (f"order block {side} entry confirmation", "smc_ict"),
            ("fair value gap FVG imbalance fill", "smc_ict"),
            ("change of character CHoCH break of structure BOS", "smc_ict"),
            ("supply demand zone entry rejection", "supply_demand"),
            ("stop loss risk management position size", "risk_management"),
        ]

    seen, all_results = set(), []
    for q, cat in queries:
        for r in search(q, n=3, category=cat):
            key = r["text"][:80]
            if key not in seen and r["relevance"] > 0.001:
                seen.add(key)
                all_results.append(r)

    if not all_results:
        return ""

    all_results.sort(key=lambda x: x["relevance"], reverse=True)
    top = all_results[:5]
    sep = "-" * 40
    parts = ["## KNOWLEDGE BASE - Relevant Rules"]
    for i, r in enumerate(top, 1):
        header = "### [" + str(i) + "] " + r["source"].upper() + " (" + r["category"] + ")"
        body   = r["text"][:500]
        parts.append(header)
        parts.append(body)
        parts.append(sep)
    return "\n".join(parts)

def stats():
    """Στατιστικά βάσης γνώσης."""
    _load()
    from collections import Counter
    cats = Counter(c.get("category","?") for c in _chunks)
    return {"total": len(_chunks), "by_category": dict(cats)}
