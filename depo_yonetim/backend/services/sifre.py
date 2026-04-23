"""
backend/services/sifre.py
-------------------------
Sifre hash/dogrulama — PBKDF2-HMAC-SHA256. Sadece standart kutuphane;
harici bagimlilik yok.

  * `hash_et(sifre)`            -> (hash_hex, salt_hex)
  * `dogrula(sifre, h, s)`      -> bool (sabit-zaman karsilastirma)
  * Iterasyon: 200_000 — 2026 itibariyle makul.

`secrets.compare_digest` timing-attack'a karsi koruma saglar.
"""

from __future__ import annotations

import hashlib
import secrets

ALGO = "sha256"
ITER = 200_000
SALT_BYTES = 16


def hash_et(sifre: str, salt_hex: str | None = None) -> tuple[str, str]:
    """Duz sifreyi hash'le. Salt verilmediyse yeni bir tane uretilir.
    Donen: (hash_hex, salt_hex) — her ikisi de DB'de saklanir."""
    if not isinstance(sifre, str):
        raise TypeError("Sifre str olmalidir.")
    if salt_hex:
        salt = bytes.fromhex(salt_hex)
    else:
        salt = secrets.token_bytes(SALT_BYTES)
    dk = hashlib.pbkdf2_hmac(ALGO, sifre.encode("utf-8"), salt, ITER)
    return dk.hex(), salt.hex()


def dogrula(sifre: str, hash_hex: str, salt_hex: str) -> bool:
    """Verilen sifrenin, saklanan hash ile uyustugunu sabit zamanda
    kontrol eder. Hash/salt eksikse False doner."""
    if not sifre or not hash_hex or not salt_hex:
        return False
    try:
        salt = bytes.fromhex(salt_hex)
    except ValueError:
        return False
    dk = hashlib.pbkdf2_hmac(ALGO, sifre.encode("utf-8"), salt, ITER)
    return secrets.compare_digest(dk.hex(), hash_hex)
