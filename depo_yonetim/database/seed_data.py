"""
database/seed_data.py
---------------------
Uygulamanın ilk açılışında tetiklenen seed mantığı. Şunları üretir:

  * 1 yönetici (admin / admin123) + 15 işçi (isci1..isci15 / 1234)
  * 24 ev eşyası ürünü — 20 tanesi yüksek stoklu (250–500 arası),
    4 tanesi kritik eşiğin altında (12, 15, 18, 20)
  * Ürünlere deterministik koridor/raf/goz lokasyon dağıtımı
  * 9 fake "tamamlandi" sipariş — admin oluşturmuş, işçilere atanmış,
    tarihleri son 30 güne yayılmış; detayları `siparis_detaylari`
    tablosuna kayıt edilmiş (hazirlandi=2), stoklar buna göre
    düşürülmüş, her kalem için `stok_hareketleri` 'cikis' kaydı var.

Tüm seed fonksiyonları idempotent: ilgili tablo boş değilse sessizce
geri döner; mevcut veriyi ezmez. Bu sayede migration'lar ile birlikte
güvenle tekrar tekrar çağrılabilir.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta


# ----------------------------------------------------------------------
# Sabitler
# ----------------------------------------------------------------------
ADMIN = ("admin", "admin123", "Yonetici")
ISCI_SAYISI = 15
ISCI_SIFRE = "1234"

# (ad, başlangıç_stok, fiyat, kategori)
# Çoğu 250-500 arası stoklu; son 4 ürün kritik (<25).
ORNEK_URUNLER: list[tuple[str, int, float, str]] = [
    ("Sandalye",        320, 450.0,   "Mobilya"),
    ("Masa",            280, 1800.0,  "Mobilya"),
    ("Calisma Masasi",  410, 2400.0,  "Ofis"),
    ("Kitaplik",        355, 2100.0,  "Depolama"),
    ("Dolap",           265, 5400.0,  "Depolama"),
    ("Komodin",         470, 780.0,   "Yatak Odasi"),
    ("TV Unitesi",      295, 3100.0,  "Oturma"),
    ("Koltuk",          375, 7800.0,  "Oturma"),
    ("Sehpa",           445, 520.0,   "Oturma"),
    ("Mutfak Rafi",     310, 640.0,   "Mutfak"),
    ("Ayna",            390, 380.0,   "Dekor"),
    ("Yemek Masasi",    285, 3400.0,  "Mutfak"),
    ("Ofis Koltugu",    340, 1950.0,  "Ofis"),
    ("Puf",             480, 260.0,   "Oturma"),
    ("Cekmeceli Sehpa", 355, 890.0,   "Oturma"),
    ("Banyo Dolabi",    315, 1250.0,  "Banyo"),
    ("Hali",            405, 1890.0,  "Dekor"),
    ("Gardirop",        275, 6300.0,  "Yatak Odasi"),
    ("Askilik",         365, 320.0,   "Depolama"),
    ("Rafli Dolap",     395, 2780.0,  "Depolama"),
    # --- Kritik stok (düsük 4) — fake siparişlerde kullanılmaz
    ("Ayakkabilik",      20, 950.0,   "Depolama"),
    ("Lambader",         18, 880.0,   "Dekor"),
    ("Kiler Rafi",       15, 540.0,   "Depolama"),
    ("Portmanto",        12, 720.0,   "Depolama"),
]

# UI comboboxi icin bilinen kategoriler (serbest metin de kabul edilir).
KATEGORILER = [
    "Mobilya", "Oturma", "Yatak Odasi", "Mutfak", "Banyo",
    "Ofis", "Depolama", "Dekor", "Diger",
]

# Fake siparişlerden muaf kalacak (kritik stok gorunumu bozulmasin)
KRITIK_URUN_ADLARI = {"Ayakkabilik", "Lambader", "Kiler Rafi", "Portmanto"}

FAKE_SIPARIS_SAYISI = 9


# ======================================================================
# Kullanıcılar
# ======================================================================
def seed_kullanicilar(conn) -> None:
    """Admin + 15 isci seed eder. Sifreler PBKDF2-SHA256 ile
    `sifre_hash`/`sifre_salt` kolonlarina yazilir; duz `sifre` bos
    birakilir. Giris sirasinda dogrulama hash uzerinden yapilir."""
    row = conn.execute("SELECT COUNT(*) AS n FROM kullanicilar").fetchone()
    if row and int(row["n"]) > 0:
        return

    # Geç import: seed_data modülü db_init tarafindan init sirasinda
    # cagirilir; circular import'u onlemek icin burada import ediyoruz.
    from backend.services.sifre import hash_et

    h, s = hash_et(ADMIN[1])
    conn.execute(
        "INSERT INTO kullanicilar "
        "(kullanici_adi, sifre, sifre_hash, sifre_salt, rol) "
        "VALUES (?,?,?,?,?)",
        (ADMIN[0], "", h, s, ADMIN[2]),
    )
    for i in range(1, ISCI_SAYISI + 1):
        h, s = hash_et(ISCI_SIFRE)
        conn.execute(
            "INSERT INTO kullanicilar "
            "(kullanici_adi, sifre, sifre_hash, sifre_salt, rol) "
            "VALUES (?,?,?,?,?)",
            (f"isci{i}", "", h, s, "Isci"),
        )


# ======================================================================
# Ürünler
# ======================================================================
def seed_urunler(conn) -> None:
    row = conn.execute("SELECT COUNT(*) AS n FROM urunler").fetchone()
    bos_muydu = not row or int(row["n"]) == 0
    if bos_muydu:
        conn.executemany(
            "INSERT INTO urunler (ad, stok, fiyat, kategori) "
            "VALUES (?,?,?,?)",
            ORNEK_URUNLER,
        )
        return
    # Doluysa: kategori kolonu bos olanlara bilinen urunlerin kategorisini ata
    ad_kategori = {u[0]: u[3] for u in ORNEK_URUNLER}
    for ad, kat in ad_kategori.items():
        conn.execute(
            "UPDATE urunler SET kategori=? WHERE ad=? AND kategori=''",
            (kat, ad),
        )


# ======================================================================
# Lokasyon (koridor / raf / göz)
# ======================================================================
def seed_lokasyonlar(conn) -> None:
    rows = conn.execute(
        "SELECT id FROM urunler WHERE koridor='' OR raf='' OR goz=''"
    ).fetchall()
    koridorlar = ["A", "B", "C", "D"]
    for i, r in enumerate(rows):
        conn.execute(
            "UPDATE urunler SET koridor=?, raf=?, goz=? WHERE id=?",
            (
                koridorlar[i % len(koridorlar)],
                f"R{(i % 6) + 1}",
                f"G{(i % 4) + 1}",
                int(r["id"]),
            ),
        )


# ======================================================================
# Fake tamamlanmış siparişler
# ======================================================================
def seed_fake_tamamlanmis_siparisler(conn) -> None:
    """Son 30 gün içine yayılmış 9 tamamlanmış sipariş üretir.

    Davranışlar:
      * Admin tarafından oluşturulmuş gibi (olusturan_id = admin)
      * İşçilere rastgele atanmış (atanan_isci_id = isciX)
      * Durum = 'tamamlandi'
      * 2–5 farklı ürün, her biri için makul adet
      * Detaylar `hazirlandi=2` (tamamlanan kalem) olarak kayıt
      * Stoklar düşürülüp `stok_hareketleri`'ne 'cikis' yazılır
      * Başlangıç/bitiş zamanları da geçmiş gerçekçi değerler
      * Kritik 4 ürün (Ayakkabilik, Lambader, Kiler Rafi, Portmanto)
        dahil edilmez — kritik stok görünümü bozulmasın
    """
    row = conn.execute("SELECT COUNT(*) AS n FROM siparisler").fetchone()
    if row and int(row["n"]) > 0:
        return

    admin = conn.execute(
        "SELECT id FROM kullanicilar WHERE kullanici_adi='admin'"
    ).fetchone()
    if not admin:
        return
    admin_id = int(admin["id"])

    isci_rows = conn.execute(
        "SELECT id FROM kullanicilar WHERE rol='Isci' ORDER BY id"
    ).fetchall()
    isci_ids = [int(r["id"]) for r in isci_rows]
    if not isci_ids:
        return

    # Kritik ürünleri disla
    placeholders = ",".join("?" for _ in KRITIK_URUN_ADLARI)
    urun_rows = conn.execute(
        f"SELECT id, ad, fiyat FROM urunler WHERE ad NOT IN ({placeholders})",
        tuple(KRITIK_URUN_ADLARI),
    ).fetchall()
    urun_list = [
        {"id": int(r["id"]), "ad": r["ad"], "fiyat": float(r["fiyat"])}
        for r in urun_rows
    ]
    if len(urun_list) < 5:
        return

    rng = random.Random(7)  # deterministik — tekrarlanabilir seed
    simdi = datetime.now()

    for _ in range(FAKE_SIPARIS_SAYISI):
        gun_once = rng.randint(1, 30)
        saat = rng.randint(8, 17)
        dk = rng.randint(0, 59)
        siparis_dt = (simdi - timedelta(days=gun_once)).replace(
            hour=saat, minute=dk, second=0, microsecond=0,
        )
        bas_dt = siparis_dt + timedelta(minutes=rng.randint(5, 60))
        bit_dt = bas_dt + timedelta(minutes=rng.randint(3, 40))

        tarih_s = siparis_dt.strftime("%Y-%m-%d %H:%M:%S")
        bas_s = bas_dt.strftime("%Y-%m-%d %H:%M:%S")
        bit_s = bit_dt.strftime("%Y-%m-%d %H:%M:%S")

        atanan = rng.choice(isci_ids)
        cur = conn.execute(
            "INSERT INTO siparisler "
            "(olusturan_id, atanan_isci_id, durum, tarih, "
            " hazirlanma_baslangic, hazirlanma_bitis) "
            "VALUES (?,?,?,?,?,?)",
            (admin_id, atanan, "tamamlandi", tarih_s, bas_s, bit_s),
        )
        siparis_id = cur.lastrowid

        kalem_sayisi = rng.randint(2, 5)
        secilen = rng.sample(urun_list, min(kalem_sayisi, len(urun_list)))
        for u in secilen:
            uid = u["id"]
            # Güncel stok (önceki fake siparişler de bu üründen düşmüş
            # olabilir — negatif'e kaçmamak için her seferinde oku)
            sr = conn.execute(
                "SELECT stok FROM urunler WHERE id=?", (uid,)
            ).fetchone()
            mevcut = int(sr["stok"]) if sr else 0
            if mevcut <= 5:
                # Cok dusukse bu siparis icin o urunu atla
                continue
            # Batch başına en fazla ~%8 düşür — realistik parti
            ust = max(2, min(mevcut // 12, 18))
            adet = rng.randint(1, ust)
            conn.execute(
                "INSERT INTO siparis_detaylari "
                "(siparis_id, urun_id, adet, hazirlandi) "
                "VALUES (?,?,?,2)",
                (siparis_id, uid, adet),
            )
            conn.execute(
                "UPDATE urunler SET stok = stok - ? WHERE id=?",
                (adet, uid),
            )
            conn.execute(
                "INSERT INTO stok_hareketleri "
                "(urun_id, islem_tipi, miktar, tarih, kullanici_id) "
                "VALUES (?,?,?,?,?)",
                (uid, "cikis", adet, bit_s, atanan),
            )


__all__ = [
    "ADMIN",
    "ISCI_SAYISI",
    "ORNEK_URUNLER",
    "KRITIK_URUN_ADLARI",
    "FAKE_SIPARIS_SAYISI",
    "seed_kullanicilar",
    "seed_urunler",
    "seed_lokasyonlar",
    "seed_fake_tamamlanmis_siparisler",
]
