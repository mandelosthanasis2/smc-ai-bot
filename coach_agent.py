"""
coach_agent.py — Trading Coach για Railway
==========================================
Απαντάει σε ερωτήσεις trading βασισμένος στα βιβλία.
"""

import os
import anthropic

# Knowledge Base
try:
    from knowledge_retriever_railway import get_context
    KB_AVAILABLE = True
except Exception:
    KB_AVAILABLE = False
    def get_context(*a, **kw): return ""

SYSTEM_PROMPT = """
You are an expert Trading Coach and Teacher.
You teach trading concepts based EXCLUSIVELY on the books in your knowledge base.
You never make things up.

IMPORTANT FORMATTING:
- NEVER use markdown (no ##, no **, no ---, no ```)
- Write in plain text only
- Keep trading terms in English always (Order Block, FVG, Supply Zone, etc.)
- Only explanations change language

YOUR PERSONALITY:
- Patient and encouraging
- Clear and simple explanations with examples
- Reference specific books when possible
- ALWAYS respond in the same language the student uses

YOUR KNOWLEDGE (from books):
- ICT Trading Bible (Parts 1 & 2)
- Smart Money Concepts
- Supply and Demand Trading
- Order Flow Trading Setups
- Volume Profile
- The Candlestick Trading Bible
- Technical Analysis Masterclass
- How to Swing Trade
- And more...

TEACHING RULES:
1. Always base answers on the books
2. If you don\'t know something from the books, say so honestly
3. Give practical examples with price levels
4. Explain WHY, not just WHAT
5. Connect concepts between different strategies
"""

# Per-session conversation history (in-memory)
_sessions: dict = {}

def get_or_create_session(session_id: str) -> list:
    if session_id not in _sessions:
        _sessions[session_id] = []
    return _sessions[session_id]

def chat(user_message: str, session_id: str = "default") -> str:
    """Απαντάει σε ερώτηση. Κρατάει ιστορικό ανά session."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return "Σφάλμα: ANTHROPIC_API_KEY δεν βρέθηκε."

    # KB context
    kb = get_context(user_message, max_chunks=5) if KB_AVAILABLE else ""
    system = SYSTEM_PROMPT + (f"\n\n{kb}" if kb else "")

    history = get_or_create_session(session_id)
    history.append({"role": "user", "content": user_message})
    recent = history[-12:]  # last 6 exchanges

    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp   = client.messages.create(
            model      = "claude-haiku-4-5-20251001",
            max_tokens = 4096,
            system     = system,
            messages   = recent,
        )
        answer = resp.content[0].text
        history.append({"role": "assistant", "content": answer})
        return answer
    except Exception as e:
        return f"Σφάλμα: {str(e)[:100]}"

def reset_session(session_id: str = "default") -> str:
    if session_id in _sessions:
        _sessions[session_id] = []
    return "Η συνομιλία μηδενίστηκε!"

SUGGESTIONS = [
    "Τι είναι Order Block και πώς το βρίσκω;",
    "Εξήγησέ μου το FVG (Fair Value Gap)",
    "Τι είναι SFP (Swing Failure Pattern);",
    "Πώς εντοπίζω Market Structure;",
    "Τι είναι liquidity sweep;",
    "Πώς συνδυάζω πολλές στρατηγικές;",
    "Εξήγησέ μου το Supply and Demand",
    "Τι είναι CHoCH και BOS;",
]
