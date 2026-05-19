"""
database.py — PostgreSQL persistence for SMC AI Bot
Αντικαθιστά τα JSON files με PostgreSQL στο Railway.
"""

import os
import json
import logging
from datetime import datetime, timezone

log = logging.getLogger(__name__)

# ── psycopg2 ──────────────────────────────────────────────────────
try:
    import psycopg2
    import psycopg2.extras
    HAS_DB = True
except ImportError:
    HAS_DB = False
    log.warning("psycopg2 not installed — DB disabled, using JSON fallback")

DATABASE_URL = os.environ.get("DATABASE_URL", "")

def get_conn():
    if not HAS_DB or not DATABASE_URL:
        return None
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode="require")
        return conn
    except Exception as e:
        log.error(f"DB connect error: {e}")
        return None

# =================================================================
# SCHEMA
# =================================================================

def init_db():
    """Δημιουργεί τους πίνακες αν δεν υπάρχουν."""
    conn = get_conn()
    if not conn:
        log.warning("init_db: no DB connection")
        return
    try:
        with conn.cursor() as cur:
            # bot_state: ένα row ανά strategy (A, B, C)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS bot_state (
                    strategy    VARCHAR(1) PRIMARY KEY,
                    balance     NUMERIC(12,2) NOT NULL DEFAULT 10000,
                    pnl_total   NUMERIC(12,2) NOT NULL DEFAULT 0,
                    wins        INTEGER NOT NULL DEFAULT 0,
                    losses      INTEGER NOT NULL DEFAULT 0,
                    position    JSONB,
                    updated_at  TIMESTAMP DEFAULT NOW()
                )
            """)
            # trades: ένα row ανά trade
            cur.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id          SERIAL PRIMARY KEY,
                    strategy    VARCHAR(1) NOT NULL,
                    type        VARCHAR(5) NOT NULL,
                    entry       NUMERIC(12,2),
                    close       NUMERIC(12,2),
                    pnl         NUMERIC(10,2),
                    result      VARCHAR(4),
                    note        VARCHAR(50),
                    divergence  BOOLEAN DEFAULT FALSE,
                    news_score  INTEGER DEFAULT 0,
                    trade_time  VARCHAR(20),
                    created_at  TIMESTAMP DEFAULT NOW()
                )
            """)
        conn.commit()
        log.info("DB schema ready ✓")
    except Exception as e:
        log.error(f"init_db error: {e}")
        conn.rollback()
    finally:
        conn.close()

# =================================================================
# LOAD STATE
# =================================================================

def db_load_state(strategy: str) -> dict | None:
    """
    Φορτώνει balance, pnl, wins, losses, position, trades από DB.
    Επιστρέφει dict ή None αν δεν υπάρχει DB / row.
    """
    conn = get_conn()
    if not conn:
        return None
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # State
            cur.execute(
                "SELECT * FROM bot_state WHERE strategy = %s",
                (strategy,)
            )
            row = cur.fetchone()
            if not row:
                return None

            # Trades (τελευταία 200)
            cur.execute(
                """SELECT type, entry, close, pnl, result, note,
                          divergence, news_score, trade_time as time
                   FROM trades
                   WHERE strategy = %s
                   ORDER BY id ASC""",
                (strategy,)
            )
            trades = []
            for t in cur.fetchall():
                trades.append({
                    "type":       t["type"],
                    "entry":      float(t["entry"]) if t["entry"] else 0,
                    "close":      float(t["close"]) if t["close"] else 0,
                    "pnl":        float(t["pnl"]) if t["pnl"] else 0,
                    "result":     t["result"],
                    "note":       t["note"] or "",
                    "divergence": t["divergence"],
                    "news_score": t["news_score"] or 0,
                    "time":       t["time"] or "",
                })

        result = {
            "balance":   float(row["balance"]),
            "pnl_total": float(row["pnl_total"]),
            "wins":      row["wins"],
            "losses":    row["losses"],
            "position":  row["position"],  # JSONB → dict ή None
            "trades":    trades,
        }
        log.info(f"DB load [{strategy}]: ${result['balance']:.2f} W{result['wins']}/L{result['losses']} trades={len(trades)}")
        return result

    except Exception as e:
        log.error(f"db_load_state [{strategy}] error: {e}")
        return None
    finally:
        conn.close()

# =================================================================
# SAVE STATE
# =================================================================

def db_save_state(strategy: str, state: dict):
    """
    Αποθηκεύει balance, pnl, wins, losses, position.
    Τα trades αποθηκεύονται ξεχωριστά με db_save_trade().
    """
    conn = get_conn()
    if not conn:
        return
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO bot_state (strategy, balance, pnl_total, wins, losses, position, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (strategy) DO UPDATE SET
                    balance    = EXCLUDED.balance,
                    pnl_total  = EXCLUDED.pnl_total,
                    wins       = EXCLUDED.wins,
                    losses     = EXCLUDED.losses,
                    position   = EXCLUDED.position,
                    updated_at = NOW()
            """, (
                strategy,
                state.get("balance", 10000),
                state.get("pnl_total", 0),
                state.get("wins", 0),
                state.get("losses", 0),
                json.dumps(state.get("position")) if state.get("position") else None,
            ))
        conn.commit()
    except Exception as e:
        log.error(f"db_save_state [{strategy}] error: {e}")
        conn.rollback()
    finally:
        conn.close()

def db_save_trade(strategy: str, trade: dict):
    """
    Αποθηκεύει ένα νέο trade στη DB.
    Καλείται από finalize_trade_x() αφού κλείσει η θέση.
    """
    conn = get_conn()
    if not conn:
        return
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO trades
                    (strategy, type, entry, close, pnl, result, note,
                     divergence, news_score, trade_time)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                strategy,
                trade.get("type"),
                trade.get("entry"),
                trade.get("close"),
                trade.get("pnl"),
                trade.get("result"),
                trade.get("note", ""),
                trade.get("divergence", False),
                trade.get("news_score", 0),
                trade.get("time", ""),
            ))
        conn.commit()
    except Exception as e:
        log.error(f"db_save_trade [{strategy}] error: {e}")
        conn.rollback()
    finally:
        conn.close()

# =================================================================
# SEED: φόρτωσε τα SAVED_STATE στη DB αν είναι άδεια
# =================================================================

def seed_if_empty(strategy: str, saved_state: dict):
    """
    Αν η DB δεν έχει row για αυτή τη strategy, γράψε τα SAVED_STATE.
    Τρέχει μία φορά μετά το init_db().
    """
    conn = get_conn()
    if not conn:
        return
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM bot_state WHERE strategy = %s", (strategy,))
            exists = cur.fetchone()
        if exists:
            log.info(f"DB seed [{strategy}]: already has data, skipping")
            return

        # Γράψε state
        db_save_state(strategy, saved_state)

        # Γράψε trades
        for t in saved_state.get("trades", []):
            db_save_trade(strategy, t)

        log.info(f"DB seed [{strategy}]: seeded ${saved_state['balance']:.2f} + {len(saved_state.get('trades',[]))} trades ✓")
    except Exception as e:
        log.error(f"seed_if_empty [{strategy}] error: {e}")
    finally:
        conn.close()
