"""
database.py — PostgreSQL persistence for NRM Bot (multi-user)
"""

import os
import json
import logging
import bcrypt
from datetime import datetime, timezone

log = logging.getLogger(__name__)

# ── psycopg2 ──────────────────────────────────────────────────────
try:
    import psycopg2
    import psycopg2.extras
    HAS_DB = True
except ImportError:
    HAS_DB = False
    log.warning("psycopg2 not installed — DB disabled")

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

            # USERS
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id                      SERIAL PRIMARY KEY,
                    username                VARCHAR(100) UNIQUE NOT NULL,
                    email                   VARCHAR(255) UNIQUE,
                    password_hash           VARCHAR(255) NOT NULL,
                    role                    VARCHAR(20) DEFAULT 'user',
                    is_active               BOOLEAN DEFAULT true,
                    live_trading_approved   BOOLEAN DEFAULT false,
                    live_trading_requested  BOOLEAN DEFAULT false,
                    created_at              TIMESTAMP DEFAULT NOW()
                )
            """)

            # USER SETTINGS
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_settings (
                    id                  SERIAL PRIMARY KEY,
                    user_id             INTEGER REFERENCES users(id) UNIQUE,
                    bitget_api_key      VARCHAR(255),
                    bitget_secret_key   VARCHAR(255),
                    bitget_passphrase   VARCHAR(255),
                    telegram_token      VARCHAR(255),
                    telegram_chat_id    VARCHAR(255),
                    risk_percent        NUMERIC DEFAULT 2.0,
                    strategy_a          BOOLEAN DEFAULT true,
                    strategy_b          BOOLEAN DEFAULT true,
                    strategy_c          BOOLEAN DEFAULT true,
                    strategy_d          BOOLEAN DEFAULT true,
                    trading_mode        VARCHAR(20) DEFAULT 'paper',
                    created_at          TIMESTAMP DEFAULT NOW()
                )
            """)

            # BOT STATE — προσθήκη user_id αν δεν υπάρχει
            cur.execute("""
                CREATE TABLE IF NOT EXISTS bot_state (
                    strategy    VARCHAR(1),
                    user_id     INTEGER REFERENCES users(id),
                    balance     NUMERIC(12,2) NOT NULL DEFAULT 10000,
                    pnl_total   NUMERIC(12,2) NOT NULL DEFAULT 0,
                    wins        INTEGER NOT NULL DEFAULT 0,
                    losses      INTEGER NOT NULL DEFAULT 0,
                    position    JSONB,
                    updated_at  TIMESTAMP DEFAULT NOW(),
                    PRIMARY KEY (strategy, user_id)
                )
            """)

            # TRADES — προσθήκη user_id αν δεν υπάρχει
            cur.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id          SERIAL PRIMARY KEY,
                    user_id     INTEGER REFERENCES users(id),
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

            # Migration: προσθήκη user_id στα υπάρχοντα tables αν λείπει
            cur.execute("""
                ALTER TABLE bot_state ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id)
            """)
            cur.execute("""
                ALTER TABLE trades ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id)
            """)

        conn.commit()
        log.info("DB schema ready ✓")
    except Exception as e:
        log.error(f"init_db error: {e}")
        conn.rollback()
    finally:
        conn.close()

# =================================================================
# USER FUNCTIONS
# =================================================================

def get_user_by_username(username: str) -> dict | None:
    conn = get_conn()
    if not conn: return None
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE username = %s", (username,))
            row = cur.fetchone()
            return dict(row) if row else None
    except Exception as e:
        log.error(f"get_user_by_username error: {e}")
        return None
    finally:
        conn.close()

def get_user_by_id(user_id: int) -> dict | None:
    conn = get_conn()
    if not conn: return None
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            row = cur.fetchone()
            return dict(row) if row else None
    except Exception as e:
        log.error(f"get_user_by_id error: {e}")
        return None
    finally:
        conn.close()

def create_user(username: str, password: str, email: str = None, role: str = 'user') -> dict | None:
    """Δημιουργεί νέο χρήστη με encrypted password."""
    password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    conn = get_conn()
    if not conn: return None
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                INSERT INTO users (username, email, password_hash, role)
                VALUES (%s, %s, %s, %s)
                RETURNING *
            """, (username, email, password_hash, role))
            user = dict(cur.fetchone())
            # Δημιουργία default settings για τον νέο χρήστη
            cur.execute("""
                INSERT INTO user_settings (user_id) VALUES (%s)
                ON CONFLICT (user_id) DO NOTHING
            """, (user['id'],))
        conn.commit()
        log.info(f"User created: {username} (role={role})")
        return user
    except Exception as e:
        log.error(f"create_user error: {e}")
        conn.rollback()
        return None
    finally:
        conn.close()

def verify_password(username: str, password: str) -> dict | None:
    """Ελέγχει username/password και επιστρέφει τον χρήστη αν είναι σωστό."""
    user = get_user_by_username(username)
    if not user: return None
    if not user.get('is_active'): return None
    try:
        if bcrypt.checkpw(password.encode('utf-8'), user['password_hash'].encode('utf-8')):
            return user
    except Exception as e:
        log.error(f"verify_password error: {e}")
    return None

def change_password(user_id: int, new_password: str) -> bool:
    """Αλλάζει το password ενός χρήστη."""
    password_hash = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    conn = get_conn()
    if not conn: return False
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET password_hash = %s WHERE id = %s", (password_hash, user_id))
        conn.commit()
        return True
    except Exception as e:
        log.error(f"change_password error: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

# =================================================================
# USER SETTINGS FUNCTIONS
# =================================================================

def get_user_settings(user_id: int) -> dict | None:
    conn = get_conn()
    if not conn: return None
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM user_settings WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            return dict(row) if row else None
    except Exception as e:
        log.error(f"get_user_settings error: {e}")
        return None
    finally:
        conn.close()

def save_user_settings(user_id: int, settings: dict) -> bool:
    conn = get_conn()
    if not conn: return False
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO user_settings (
                    user_id, bitget_api_key, bitget_secret_key, bitget_passphrase,
                    telegram_token, telegram_chat_id, risk_percent,
                    strategy_a, strategy_b, strategy_c, strategy_d, trading_mode
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    bitget_api_key      = EXCLUDED.bitget_api_key,
                    bitget_secret_key   = EXCLUDED.bitget_secret_key,
                    bitget_passphrase   = EXCLUDED.bitget_passphrase,
                    telegram_token      = EXCLUDED.telegram_token,
                    telegram_chat_id    = EXCLUDED.telegram_chat_id,
                    risk_percent        = EXCLUDED.risk_percent,
                    strategy_a          = EXCLUDED.strategy_a,
                    strategy_b          = EXCLUDED.strategy_b,
                    strategy_c          = EXCLUDED.strategy_c,
                    strategy_d          = EXCLUDED.strategy_d,
                    trading_mode        = EXCLUDED.trading_mode
            """, (
                user_id,
                settings.get('bitget_api_key'),
                settings.get('bitget_secret_key'),
                settings.get('bitget_passphrase'),
                settings.get('telegram_token'),
                settings.get('telegram_chat_id'),
                settings.get('risk_percent', 2.0),
                settings.get('strategy_a', True),
                settings.get('strategy_b', True),
                settings.get('strategy_c', True),
                settings.get('strategy_d', True),
                settings.get('trading_mode', 'paper'),
            ))
        conn.commit()
        return True
    except Exception as e:
        log.error(f"save_user_settings error: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

# =================================================================
# ADMIN FUNCTIONS
# =================================================================

def get_all_users() -> list:
    """Επιστρέφει όλους τους χρήστες για το admin panel."""
    conn = get_conn()
    if not conn: return []
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT u.id, u.username, u.email, u.role, u.is_active,
                       u.live_trading_approved, u.live_trading_requested, u.created_at,
                       s.trading_mode, s.risk_percent,
                       s.strategy_a, s.strategy_b, s.strategy_c, s.strategy_d
                FROM users u
                LEFT JOIN user_settings s ON u.id = s.user_id
                ORDER BY u.created_at DESC
            """)
            return [dict(row) for row in cur.fetchall()]
    except Exception as e:
        log.error(f"get_all_users error: {e}")
        return []
    finally:
        conn.close()

def approve_live_trading(user_id: int) -> bool:
    conn = get_conn()
    if not conn: return False
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE users SET live_trading_approved = true, live_trading_requested = false
                WHERE id = %s
            """, (user_id,))
            cur.execute("""
                UPDATE user_settings SET trading_mode = 'live' WHERE user_id = %s
            """, (user_id,))
        conn.commit()
        return True
    except Exception as e:
        log.error(f"approve_live_trading error: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

def reject_live_trading(user_id: int) -> bool:
    conn = get_conn()
    if not conn: return False
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE users SET live_trading_approved = false, live_trading_requested = false
                WHERE id = %s
            """, (user_id,))
        conn.commit()
        return True
    except Exception as e:
        log.error(f"reject_live_trading error: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

def toggle_user_active(user_id: int, is_active: bool) -> bool:
    conn = get_conn()
    if not conn: return False
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET is_active = %s WHERE id = %s", (is_active, user_id))
        conn.commit()
        return True
    except Exception as e:
        log.error(f"toggle_user_active error: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

def request_live_trading(user_id: int) -> bool:
    conn = get_conn()
    if not conn: return False
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET live_trading_requested = true WHERE id = %s", (user_id,))
        conn.commit()
        return True
    except Exception as e:
        log.error(f"request_live_trading error: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

# =================================================================
# BOT STATE FUNCTIONS (multi-user)
# =================================================================

def db_load_state(strategy: str, user_id: int = 1) -> dict | None:
    conn = get_conn()
    if not conn: return None
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM bot_state WHERE strategy = %s AND user_id = %s",
                (strategy, user_id)
            )
            row = cur.fetchone()
            if not row: return None

            cur.execute("""
                SELECT type, entry, close, pnl, result, note,
                       divergence, news_score, trade_time as time
                FROM trades
                WHERE strategy = %s AND user_id = %s
                ORDER BY id ASC
            """, (strategy, user_id))

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

        return {
            "balance":   float(row["balance"]),
            "pnl_total": float(row["pnl_total"]),
            "wins":      row["wins"],
            "losses":    row["losses"],
            "position":  row["position"],
            "trades":    trades,
        }
    except Exception as e:
        log.error(f"db_load_state [{strategy}] error: {e}")
        return None
    finally:
        conn.close()

def db_save_state(strategy: str, state: dict, user_id: int = 1):
    conn = get_conn()
    if not conn: return
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO bot_state (strategy, user_id, balance, pnl_total, wins, losses, position, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (strategy, user_id) DO UPDATE SET
                    balance    = EXCLUDED.balance,
                    pnl_total  = EXCLUDED.pnl_total,
                    wins       = EXCLUDED.wins,
                    losses     = EXCLUDED.losses,
                    position   = EXCLUDED.position,
                    updated_at = NOW()
            """, (
                strategy, user_id,
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

def db_save_trade(strategy: str, trade: dict, user_id: int = 1):
    conn = get_conn()
    if not conn: return
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO trades
                    (user_id, strategy, type, entry, close, pnl, result, note,
                     divergence, news_score, trade_time)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                user_id, strategy,
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

def seed_if_empty(strategy: str, saved_state: dict, user_id: int = 1):
    conn = get_conn()
    if not conn: return
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM bot_state WHERE strategy = %s AND user_id = %s", (strategy, user_id))
            exists = cur.fetchone()
        if exists:
            return
        db_save_state(strategy, saved_state, user_id)
        for t in saved_state.get("trades", []):
            db_save_trade(strategy, t, user_id)
        log.info(f"DB seed [{strategy}] user={user_id}: seeded ✓")
    except Exception as e:
        log.error(f"seed_if_empty [{strategy}] error: {e}")
    finally:
        conn.close()

# =================================================================
# ADMIN STATS
# =================================================================

def get_admin_stats() -> dict:
    """Συνολικά stats για το admin panel."""
    conn = get_conn()
    if not conn: return {}
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT COUNT(*) as total FROM users WHERE role = 'user'")
            total_users = cur.fetchone()['total']

            cur.execute("SELECT COUNT(*) as total FROM users WHERE is_active = true AND role = 'user'")
            active_users = cur.fetchone()['total']

            cur.execute("SELECT COUNT(*) as total FROM users WHERE live_trading_requested = true")
            pending_requests = cur.fetchone()['total']

            cur.execute("SELECT COUNT(*) as total FROM users WHERE live_trading_approved = true")
            live_users = cur.fetchone()['total']

            cur.execute("SELECT COUNT(*) as total FROM trades")
            total_trades = cur.fetchone()['total']

        return {
            'total_users': total_users,
            'active_users': active_users,
            'pending_requests': pending_requests,
            'live_users': live_users,
            'total_trades': total_trades,
        }
    except Exception as e:
        log.error(f"get_admin_stats error: {e}")
        return {}
    finally:
        conn.close()
