# AI Validator Module

Module που ενσωματώνεται στο NRM Bot και παρέχει AI validation για κάθε trade signal πριν την εκτέλεση.

## Δομή φακέλων

```
ai_validator/
├── __init__.py              # Public API (export validate_signal)
├── validator.py             # Κύρια logic — καλείται από bot.py
├── config.py                # Όλες οι ρυθμίσεις
├── pre_filter.py            # [Φάση 3.2] Hard rules πριν το Claude
├── agents/
│   ├── __init__.py
│   ├── technical_agent.py   # [Φάση 3.3] Technical analysis
│   ├── news_agent.py        # [Φάση 3.3] Macro sentiment
│   ├── coordinator_agent.py # [Φάση 3.3] Τελική απόφαση
│   └── knowledge_retriever.py # [Φάση 3.3] ChromaDB search
└── README.md                # Αυτό το αρχείο
```

## Πώς χρησιμοποιείται

Από το `bot.py`:

```python
from ai_validator import validate_signal

# Πριν το place_order:
decision = validate_signal(
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
        # ... περισσότερα context data
    },
    user_settings={
        "risk_percent": 2.0,
        "balance": 18449,
        "trading_mode": "PAPER",
    },
)

if decision.action == "GO":
    place_order(size=normal_size)
elif decision.action == "REDUCE_SIZE":
    place_order(size=normal_size * 0.5)
elif decision.action == "DOUBLE_SIZE":
    place_order(size=normal_size * 2.0)
elif decision.action == "SKIP":
    log.info(f"Skipped: {decision.reasoning}")
```

## Φάσεις development

- [x] **3.1** — Skeleton με stub (επιστρέφει πάντα GO)
- [ ] **3.2** — Pre-filter με hard rules
- [ ] **3.3** — Agents (Technical, News, Coordinator)
- [ ] **3.4** — Integration στο `bot.py`
- [ ] **3.5** — Database migration (στήλες για AI commentary)
- [ ] **3.6** — Settings UI (per-strategy toggles + shadow mode)

## Self-test

Για να ελέγξεις ότι το module φορτώνει σωστά:

```bash
cd nrm_bot_root
python -m ai_validator.validator
```

Πρέπει να δεις:
```
✅ Self-test passed!
```

## Configuration

Όλες οι ρυθμίσεις είναι στο `config.py`. Δεν χρειάζεται να αγγίξεις
άλλο αρχείο για να αλλάξεις:
- Models του Claude (Haiku/Sonnet)
- Pre-filter thresholds
- Confidence thresholds
- Fallback behavior

## Dependencies

Νέα packages που πρέπει να προστεθούν στο `requirements.txt`:

```
anthropic>=0.40.0      # Claude SDK (ήδη υπάρχει)
chromadb>=0.4.0        # [Φάση 3.3]
sentence-transformers   # [Φάση 3.3] embeddings
```

Στη Φάση 3.1 δεν χρειάζονται νέα packages.
