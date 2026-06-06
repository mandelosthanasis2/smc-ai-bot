"""
secrets_vault.py — symmetric encryption for at-rest secrets (Bitget API keys)
═══════════════════════════════════════════════════════════════════════════
Κρυπτογραφεί/αποκρυπτογραφεί ευαίσθητα strings (Bitget API key/secret/passphrase)
με Fernet (AES-128-CBC + HMAC-SHA256). Το κλειδί έρχεται ΑΠΟΚΛΕΙΣΤΙΚΑ από το
env var SECRETS_ENCRYPTION_KEY (Railway), ΠΟΤΕ από τη βάση.

ΑΡΧΕΣ ΑΣΦΑΛΕΙΑΣ:
  • FAIL-CLOSED: αν λείπει/είναι άκυρο το κλειδί ή η lib, encrypt/decrypt
    επιστρέφουν None — ο caller (live trading) πέφτει σε PAPER, δεν σκάει.
  • ΠΟΤΕ δεν λογάρει plaintext ή ciphertext — μόνο τύπο σφάλματος.

Δημιουργία κλειδιού (μία φορά, βάλ' το στο Railway ως SECRETS_ENCRYPTION_KEY):
    python -c "import secrets_vault; print(secrets_vault.generate_key())"
"""

import logging
import os

log = logging.getLogger(__name__)

_ENV_KEY = "SECRETS_ENCRYPTION_KEY"

try:
    from cryptography.fernet import Fernet, InvalidToken
    _HAVE_FERNET = True
except Exception:  # lib όχι εγκατεστημένη → fail-closed
    Fernet = None
    InvalidToken = Exception
    _HAVE_FERNET = False


def _fernet():
    """Επιστρέφει Fernet instance ή None (fail-closed). Δεν λογάρει το κλειδί."""
    if not _HAVE_FERNET:
        log.warning("secrets_vault: cryptography lib not installed — encryption unavailable")
        return None
    key = os.environ.get(_ENV_KEY, "")
    if not key:
        return None
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception as e:  # invalid/μη-base32 key
        log.error("secrets_vault: invalid %s (%s)", _ENV_KEY, type(e).__name__)
        return None


def available() -> bool:
    """True αν μπορούμε όντως να encrypt/decrypt (lib + έγκυρο key)."""
    return _fernet() is not None


def encrypt(plaintext: str):
    """plaintext → ciphertext str, ή None αν αποτύχει (fail-closed)."""
    f = _fernet()
    if f is None or not plaintext:
        return None
    try:
        return f.encrypt(plaintext.encode()).decode()
    except Exception as e:
        log.error("secrets_vault: encrypt failed (%s)", type(e).__name__)
        return None


def decrypt(token: str):
    """ciphertext str → plaintext, ή None αν αποτύχει (fail-closed). ΔΕΝ λογάρει τιμές."""
    f = _fernet()
    if f is None or not token:
        return None
    try:
        return f.decrypt(token.encode() if isinstance(token, str) else token).decode()
    except InvalidToken:
        log.error("secrets_vault: decrypt failed (InvalidToken — wrong key or corrupt data)")
        return None
    except Exception as e:
        log.error("secrets_vault: decrypt failed (%s)", type(e).__name__)
        return None


def mask(plaintext: str) -> str:
    """Masked αναπαράσταση για UI: '••••1234' (τελευταία 4). Ποτέ το πλήρες."""
    if not plaintext:
        return ""
    tail = plaintext[-4:] if len(plaintext) >= 4 else plaintext
    return "••••" + tail


def generate_key() -> str:
    """Νέο Fernet key (για το Railway env var). Raises αν λείπει η lib."""
    if not _HAVE_FERNET:
        raise RuntimeError("cryptography not installed")
    return Fernet.generate_key().decode()
