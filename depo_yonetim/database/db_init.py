"""
database/db_init.py
-------------------
Tablo şemalarını oluşturur ve ilk çalıştırmada örnek veriyi ekler:
  - 1 yönetici, 15 işçi
  - 20 ev eşyası ürünü

Uygulama her açıldığında `init_database()` çağrılır; tablolar yoksa oluşur,
kullanıcı/ürün kayıtları boşsa seed verisi basılır. Ayrıca eski
`siparisler` şeması tespit edilirse (tek ürün/adet yapısı), yeni
sepet-tabanlı yapıya geçirilir.
"""

from .db_connection import get_connection
from . import seed_data


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS urunler (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ad       TEXT    NOT NULL UNIQUE,
    stok     INTEGER NOT NULL DEFAULT 0,
    fiyat    REAL    NOT NULL DEFAULT 0,
    kategori TEXT    NOT NULL DEFAULT '',
    koridor  TEXT    NOT NULL DEFAULT '',
    raf      TEXT    NOT NULL DEFAULT '',
    goz      TEXT    NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS kullanicilar (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    kullanici_adi TEXT    NOT NULL UNIQUE,
    sifre         TEXT    NOT NULL DEFAULT '',
    sifre_hash    TEXT    NOT NULL DEFAULT '',
    sifre_salt    TEXT    NOT NULL DEFAULT '',
    rol           TEXT    NOT NULL CHECK (rol IN ('Yonetici', 'Isci'))
);

CREATE TABLE IF NOT EXISTS siparisler (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    olusturan_id           INTEGER NOT NULL,
    atanan_isci_id         INTEGER,
    durum                  TEXT    NOT NULL
                               CHECK (durum IN ('beklemede','hazirlaniyor',
                                                'tamamlandi','iptal',
                                                'kismi_tamamlandi'))
                               DEFAULT 'beklemede',
    tarih                  TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    hizlandirma_istendi    INTEGER NOT NULL DEFAULT 0,
    hazirlanma_baslangic   TEXT,
    hazirlanma_bitis       TEXT,
    FOREIGN KEY (olusturan_id)   REFERENCES kullanicilar(id),
    FOREIGN KEY (atanan_isci_id) REFERENCES kullanicilar(id)
);

CREATE TABLE IF NOT EXISTS siparis_detaylari (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    siparis_id INTEGER NOT NULL,
    urun_id    INTEGER NOT NULL,
    adet       INTEGER NOT NULL,
    hazirlandi INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (siparis_id) REFERENCES siparisler(id) ON DELETE CASCADE,
    FOREIGN KEY (urun_id)    REFERENCES urunler(id)
);

CREATE TABLE IF NOT EXISTS stok_hareketleri (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    urun_id      INTEGER NOT NULL,
    islem_tipi   TEXT    NOT NULL CHECK (islem_tipi IN ('giris', 'cikis')),
    miktar       INTEGER NOT NULL,
    tarih        TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    kullanici_id INTEGER,
    FOREIGN KEY (urun_id)      REFERENCES urunler(id),
    FOREIGN KEY (kullanici_id) REFERENCES kullanicilar(id)
);

CREATE TABLE IF NOT EXISTS mola_kayitlari (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    kullanici_id      INTEGER NOT NULL,
    baslangic_zamani  TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    bitis_zamani      TEXT,
    durum             TEXT    NOT NULL CHECK (durum IN ('aktif','tamamlandi')),
    sure_dakika       INTEGER NOT NULL DEFAULT 15,
    FOREIGN KEY (kullanici_id) REFERENCES kullanicilar(id)
);
"""

def init_database() -> None:
    """Şemayı oluşturur ve ilk çalıştırmada örnek veriyi ekler.

    Tüm seed mantığı `database.seed_data` modülünde toplanmıştır.
    Seed fonksiyonları idempotenttir; tablo boş değilse sessizce geri
    döner — mevcut veri korunur.
    """
    conn = get_connection()
    try:
        _eski_siparis_semasini_migrate_et(conn)
        conn.executescript(SCHEMA_SQL)
        _migrate_siparis_detay_hazirlandi(conn)
        _migrate_siparisler_iptal_ve_hizlandirma(conn)
        _migrate_siparisler_kismi_ve_sure(conn)
        _migrate_urunler_lokasyon(conn)
        _migrate_mola_sure_dakika(conn)
        _migrate_kullanicilar_sifre_hash(conn)
        seed_data.seed_kullanicilar(conn)
        seed_data.seed_urunler(conn)
        seed_data.seed_lokasyonlar(conn)
        seed_data.seed_fake_tamamlanmis_siparisler(conn)
        conn.commit()
    finally:
        conn.close()


def _migrate_kullanicilar_sifre_hash(conn) -> None:
    """kullanicilar tablosuna sifre_hash + sifre_salt kolonlari ekle.
    Eski kayitlar plain text sifre kolonunu korur; giris yapinca lazy
    olarak hash'lenecek (KullaniciService.giris_yap)."""
    cols = {c["name"] for c in
            conn.execute("PRAGMA table_info(kullanicilar)").fetchall()}
    if "sifre_hash" not in cols:
        conn.execute(
            "ALTER TABLE kullanicilar "
            "ADD COLUMN sifre_hash TEXT NOT NULL DEFAULT ''"
        )
    if "sifre_salt" not in cols:
        conn.execute(
            "ALTER TABLE kullanicilar "
            "ADD COLUMN sifre_salt TEXT NOT NULL DEFAULT ''"
        )


def _migrate_mola_sure_dakika(conn) -> None:
    """mola_kayitlari tablosuna sure_dakika kolonu ekle (yoksa).
    Varsayilan 15 dk — eski kayitlar kisa mola olarak kabul edilir."""
    cols = {c["name"] for c in
            conn.execute("PRAGMA table_info(mola_kayitlari)").fetchall()}
    if "sure_dakika" not in cols:
        conn.execute(
            "ALTER TABLE mola_kayitlari "
            "ADD COLUMN sure_dakika INTEGER NOT NULL DEFAULT 15"
        )


def _migrate_urunler_lokasyon(conn) -> None:
    """urunler tablosuna lokasyon (koridor/raf/goz) + kategori
    kolonlarini ekle."""
    cols = {c["name"] for c in
            conn.execute("PRAGMA table_info(urunler)").fetchall()}
    for kol in ("koridor", "raf", "goz", "kategori"):
        if kol not in cols:
            conn.execute(
                f"ALTER TABLE urunler ADD COLUMN {kol} TEXT NOT NULL DEFAULT ''"
            )


def _migrate_siparisler_kismi_ve_sure(conn) -> None:
    """siparisler tablosuna hazirlanma_baslangic/bitis kolonlari ekle ve
    CHECK constraint'ine 'kismi_tamamlandi' degerini dahil et. Gerekirse
    tablo rebuild edilir (CHECK degistirilemediginden)."""
    cols = {c["name"] for c in
            conn.execute("PRAGMA table_info(siparisler)").fetchall()}
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='siparisler'"
    ).fetchone()
    mevcut_sql = (row["sql"] or "") if row else ""

    has_kismi = "kismi_tamamlandi" in mevcut_sql
    has_baslangic = "hazirlanma_baslangic" in cols
    has_bitis = "hazirlanma_bitis" in cols

    if has_kismi and has_baslangic and has_bitis:
        return

    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        conn.execute("""
            CREATE TABLE siparisler_new (
                id                     INTEGER PRIMARY KEY AUTOINCREMENT,
                olusturan_id           INTEGER NOT NULL,
                atanan_isci_id         INTEGER,
                durum                  TEXT    NOT NULL
                                           CHECK (durum IN ('beklemede',
                                                            'hazirlaniyor',
                                                            'tamamlandi',
                                                            'iptal',
                                                            'kismi_tamamlandi'))
                                           DEFAULT 'beklemede',
                tarih                  TEXT    NOT NULL
                                           DEFAULT (datetime('now','localtime')),
                hizlandirma_istendi    INTEGER NOT NULL DEFAULT 0,
                hazirlanma_baslangic   TEXT,
                hazirlanma_bitis       TEXT,
                FOREIGN KEY (olusturan_id)   REFERENCES kullanicilar(id),
                FOREIGN KEY (atanan_isci_id) REFERENCES kullanicilar(id)
            )
        """)
        # Eski veriyi kopyala; olmayan kolonlari NULL/0 ile doldur
        sec_baslangic = ("hazirlanma_baslangic"
                         if has_baslangic else "NULL AS hazirlanma_baslangic")
        sec_bitis = ("hazirlanma_bitis"
                     if has_bitis else "NULL AS hazirlanma_bitis")
        conn.execute(f"""
            INSERT INTO siparisler_new
                (id, olusturan_id, atanan_isci_id, durum, tarih,
                 hizlandirma_istendi, hazirlanma_baslangic, hazirlanma_bitis)
            SELECT id, olusturan_id, atanan_isci_id, durum, tarih,
                   hizlandirma_istendi, {sec_baslangic}, {sec_bitis}
              FROM siparisler
        """)
        conn.execute("DROP TABLE siparisler")
        conn.execute("ALTER TABLE siparisler_new RENAME TO siparisler")
    finally:
        conn.execute("PRAGMA foreign_keys=ON")


def _migrate_siparisler_iptal_ve_hizlandirma(conn) -> None:
    """siparisler tablosuna `hizlandirma_istendi` kolonu + `durum`
    CHECK constraint'ine 'iptal' degeri ekle.

    SQLite'da CHECK constraint ALTER TABLE ile degistirilemez; bunun
    icin tablo sadece gerekli oldugunda yeniden insa edilir. Eski
    veriler korunur, foreign key'ler siparis_detaylari tarafinda
    `ON DELETE CASCADE` oldugu icin rebuild sirasinda etkilenmez —
    yine de yeniden insa atomik olsun diye FK gecici kapatilir.
    """
    # Yeni kolon var mi?
    cols = {
        c["name"]
        for c in conn.execute("PRAGMA table_info(siparisler)").fetchall()
    }
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='siparisler'"
    ).fetchone()
    mevcut_sql = (row["sql"] or "") if row else ""
    has_iptal = "iptal" in mevcut_sql
    has_hiz = "hizlandirma_istendi" in cols
    if has_iptal and has_hiz:
        return

    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        conn.execute("""
            CREATE TABLE siparisler_new (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                olusturan_id         INTEGER NOT NULL,
                atanan_isci_id       INTEGER,
                durum                TEXT    NOT NULL
                                         CHECK (durum IN ('beklemede',
                                                          'hazirlaniyor',
                                                          'tamamlandi',
                                                          'iptal'))
                                         DEFAULT 'beklemede',
                tarih                TEXT    NOT NULL
                                         DEFAULT (datetime('now','localtime')),
                hizlandirma_istendi  INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (olusturan_id)   REFERENCES kullanicilar(id),
                FOREIGN KEY (atanan_isci_id) REFERENCES kullanicilar(id)
            )
        """)
        if has_hiz:
            conn.execute(
                "INSERT INTO siparisler_new "
                "(id, olusturan_id, atanan_isci_id, durum, tarih, "
                " hizlandirma_istendi) "
                "SELECT id, olusturan_id, atanan_isci_id, durum, tarih, "
                "       hizlandirma_istendi "
                "  FROM siparisler"
            )
        else:
            conn.execute(
                "INSERT INTO siparisler_new "
                "(id, olusturan_id, atanan_isci_id, durum, tarih, "
                " hizlandirma_istendi) "
                "SELECT id, olusturan_id, atanan_isci_id, durum, tarih, 0 "
                "  FROM siparisler"
            )
        conn.execute("DROP TABLE siparisler")
        conn.execute("ALTER TABLE siparisler_new RENAME TO siparisler")
    finally:
        conn.execute("PRAGMA foreign_keys=ON")


def _migrate_siparis_detay_hazirlandi(conn) -> None:
    """siparis_detaylari tablosuna `hazirlandi` kolonunu ekle (yoksa).

    0 = henuz hazirlanmadi, 1 = isci raftan topladi.
    Siparis 'tamamlandi' olmadan once tum kalemlerin 1 olmasi gerekir.
    """
    cols = {
        c["name"]
        for c in conn.execute("PRAGMA table_info(siparis_detaylari)").fetchall()
    }
    if "hazirlandi" not in cols:
        conn.execute(
            "ALTER TABLE siparis_detaylari "
            "ADD COLUMN hazirlandi INTEGER NOT NULL DEFAULT 0"
        )


def _eski_siparis_semasini_migrate_et(conn) -> None:
    """Eski siparisler tablosu (urun_id/adet kolonlu) varsa sepet
    temelli yeni yapıya çevir. Eski veriler temizlenir; bu proje
    örnek amaçlıdır ve sipariş geçmişi üretim verisi değildir."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='siparisler'"
    ).fetchone()
    if not row:
        return
    cols = {c["name"] for c in conn.execute("PRAGMA table_info(siparisler)").fetchall()}
    if "olusturan_id" in cols:
        return  # zaten yeni şema
    conn.execute("DROP TABLE IF EXISTS siparis_detaylari")
    conn.execute("DROP TABLE siparisler")


