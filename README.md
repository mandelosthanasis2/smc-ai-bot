# NRM Bot

Automated BTC perpetual-futures trading bot with a multi-agent AI validation
layer. Runs multiple independent strategies in parallel against Bitget
(USDT-M perpetuals), each gated through an AI validator before execution, with
a web dashboard for monitoring and a knowledge-base-backed trading coach.

> **Status:** paper trading. The bot executes against live market data with
> simulated capital; no real funds are at risk in the current configuration.

---

## Features

- **Five parallel strategies**, each with isolated state and independent P&L
  tracking (see [Strategies](#strategies)).
- **Multi-agent AI validator** — every signal passes through a news agent, a
  technical agent, and a coordinator that returns a
  `GO / SKIP / REDUCE_SIZE / DOUBLE_SIZE` decision.
- **Shadow mode** — the validator's decision is recorded without blocking the
  trade, allowing its real-world edge to be measured before it is given
  control of execution.
- **Retrieval-augmented coach** — a chat assistant that answers from a
  knowledge base built from the operator's own trading literature
  (ICT / SMC / supply-demand, etc.) using TF-IDF retrieval.
- **Web dashboard** — per-strategy views, analytics, and a comparison tab.
- **Dual persistence** — PostgreSQL primary with a local JSON fallback.

---

## Architecture

```
┌─────────────┐     signals      ┌──────────────────┐
│ TradingView │ ───────────────► │  Webhook routes  │
│   (Pine)    │                  │   (main.py)      │
└─────────────┘                  └────────┬─────────┘
                                          │
┌─────────────┐  scheduled scan  ┌────────▼─────────┐   validate   ┌──────────────┐
│  Bitget WS  │ ───────────────► │     bot.py       │ ───────────► │ AI Validator │
│  (candles)  │                  │  (strategies +   │ ◄─────────── │  (agents)    │
└─────────────┘                  │   scheduler)     │   decision   └──────┬───────┘
                                 └────────┬─────────┘                     │
                                          │                         ┌─────▼──────┐
                                  ┌───────▼────────┐                │ Knowledge  │
                                  │  PostgreSQL    │                │ base (RAG) │
                                  │  + JSON cache  │                └────────────┘
                                  └────────────────┘
```

### Key modules

| File / dir | Responsibility |
|---|---|
| `bot.py` | Market data, indicators, scheduler, strategy execution, persistence wiring |
| `main.py` | Flask app: dashboards, webhook endpoints, navigation |
| `analytics.py` | Analytics views and per-strategy statistics |
| `database.py` | PostgreSQL access layer (state + trade history) |
| `strategies/` | Self-contained strategy modules (dependency-injected) |
| `ai_validator/` | Pre-filter, agents (news / technical / coordinator), validator |
| `knowledge_retriever_railway.py` | TF-IDF retrieval over `knowledge_base.json` |
| `coach_agent.py` | Knowledge-base-backed trading chat assistant |

### Strategy module pattern

Newer strategies are **self-contained modules** under `strategies/` that receive
their collaborators through a `deps` dictionary (dependency injection) rather
than importing from `bot.py` directly. This keeps each strategy independently
testable and means a change to one cannot silently break another:

```python
# bot.py wires the dependencies …
deps = {
    "place_order": place_order_paper,
    "finalize": finalize_trade_smc,
    "finalize_partial": finalize_partial_smc,
    "ai_validate": _ai_validate,
    # …
}
strategy_smc.process_webhook(deps, state_smc, signal, price, data)
```

```python
# … and the strategy module only depends on the contract, not the bot.
def process_webhook(deps, state, signal, price=None, data=None):
    ...
```

---

## Strategies

| ID | Name | Signal source | Exit model |
|----|------|---------------|------------|
| **A** | Daily Box + 1H RSI | Scheduled scan | Trailing stop |
| **B** | 1H Box + 15m RSI | Scheduled scan | Trailing stop |
| **C** | 1H Box + Webhook | TradingView webhook | Trailing stop |
| **CM** | Check Mark Pattern | Scheduled scan @ 13:30 UTC | 2-phase TP (TP1 50% + break-even → TP2) |
| **SMC** | OB + FVG + CHoCH | TradingView webhook | 2-phase TP (TP1 50% + break-even → TP2) |

---

## Setup

### Requirements

- Python 3.12+
- PostgreSQL (provided by Railway in production)

### Installation

```bash
pip install -r requirements.txt
```

### Environment variables

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string |
| `TRADING_MODE` | `PAPER` or `LIVE` |
| `AI_VALIDATOR_ENABLED` | Enable the AI validation layer |
| `AI_SHADOW_MODE` | `true` = record decisions without blocking trades |
| `RISK_PER_TRADE` | Fractional risk per trade (e.g. `0.02`) |
| `ANTHROPIC_API_KEY` | Claude API key for the validator and coach |
| `BITGET_*` | Exchange credentials |
| `TELEGRAM_*` | Notification bot token / chat id |

### Running

```bash
python main.py
```

The dashboard is then served by Flask; webhook endpoints are exposed at
`/webhook/<strategy>` (e.g. `/webhook/smc`).

---

## Testing

The suite covers the parts where a bug costs money: position sizing,
take-profit ordering, and the multi-phase exit lifecycle.

```bash
pip install pytest
pytest
```

```bash
pytest -m strategy      # strategy logic only
pytest -m risk          # position-sizing only
```

---

## Knowledge base

The coach and validator retrieve from `knowledge_base.json`, a pre-built
TF-IDF corpus. To rebuild it from source PDFs:

```bash
pip install pdfplumber chromadb        # build-time only
python knowledge_builder.py            # PDFs  → ChromaDB
python export_knowledge.py             # ChromaDB → knowledge_base.json
```

Only `knowledge_base.json` is deployed; the raw PDFs and ChromaDB stay local.

---

## Project layout

```
.
├── bot.py                       # core engine
├── main.py                      # Flask app + webhooks
├── analytics.py                 # analytics views
├── database.py                  # PostgreSQL layer
├── coach_agent.py               # trading coach
├── knowledge_retriever_railway.py
├── knowledge_base.json
├── strategies/
│   ├── strategy_checkmark.py
│   └── strategy_smc.py
├── ai_validator/
│   ├── validator.py
│   ├── pre_filter.py
│   └── agents/
│       ├── news_agent.py
│       ├── technical_agent.py
│       └── coordinator_agent.py
├── tests/
│   ├── conftest.py
│   ├── test_strategy_smc.py
│   ├── test_strategy_checkmark.py
│   └── test_risk_sizing.py
├── requirements.txt
└── pytest.ini
```

---

## License

Private project. All rights reserved.
