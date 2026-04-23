"""
backend/services/db_helpers.py
------------------------------
Küçük SQL sarmalayıcıları. Service'ler bu fonksiyonları kullanarak
bağlantı açma/kapama tekrarından kurtulur. `transaction()` bağlam
yöneticisi tek bağlantı üzerinde atomik (hepsi-ya-da-hiç) işlemler
yapmayı sağlar; siparişi hazırlama gibi çoklu-adım güncellemelerde
kullanılır.
"""

from contextlib import contextmanager

from database.db_connection import get_connection


def execute(sql: str, params: tuple = ()) -> int:
    """INSERT/UPDATE/DELETE çalıştırır; lastrowid döner."""
    conn = get_connection()
    try:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def fetchone(sql: str, params: tuple = ()):
    conn = get_connection()
    try:
        return conn.execute(sql, params).fetchone()
    finally:
        conn.close()


def fetchall(sql: str, params: tuple = ()):
    conn = get_connection()
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


@contextmanager
def transaction():
    """Tek bağlantı üzerinde atomik işlem yapmak için bağlam yöneticisi.

    Kullanım:
        with transaction() as conn:
            conn.execute(...); conn.execute(...)

    Blok bir hata ile çıkarsa rollback edilir; aksi halde commit edilir.
    Çağıran `conn.execute` sonuçlarını doğrudan kullanabilir.
    """
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
