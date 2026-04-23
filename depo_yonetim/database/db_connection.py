"""
database/db_connection.py
-------------------------
SQLite bağlantısını yöneten tek nokta. Diğer tüm katmanlar buradaki
get_connection() fonksiyonu üzerinden veritabanına erişir. Böylece
bağlantı yolu tek yerden değiştirilebilir (Single Source of Truth).
"""

import os
import sqlite3

DB_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(DB_DIR, "depo.db")


def get_connection() -> sqlite3.Connection:
    """Uygulama genelinde kullanılacak SQLite bağlantısını döndürür."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn
