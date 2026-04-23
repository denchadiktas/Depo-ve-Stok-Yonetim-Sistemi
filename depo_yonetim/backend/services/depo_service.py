"""
backend/services/depo_service.py
--------------------------------
Ürün CRUD + stok hareketi kalıcılığı. Bellek içi Urun/Depo nesneleri
ile veritabanı tabloları arasında çeviri yapar.
"""

from ..models.urun import Urun
from ..models.depo import Depo
from .db_helpers import execute, fetchone, fetchall


class DepoService:

    _SELECT = (
        "SELECT id, ad, stok, fiyat, koridor, raf, goz, kategori FROM urunler"
    )

    @staticmethod
    def _satir_urun(r) -> Urun:
        keys = set(r.keys())
        return Urun(
            r["id"], r["ad"], r["stok"], r["fiyat"],
            r["koridor"]  if "koridor"  in keys else "",
            r["raf"]      if "raf"      in keys else "",
            r["goz"]      if "goz"      in keys else "",
            r["kategori"] if "kategori" in keys else "",
        )

    # --- okuma ----------------------------------------------------------
    @staticmethod
    def tum_urunleri_getir() -> list[Urun]:
        rows = fetchall(DepoService._SELECT + " ORDER BY ad")
        return [DepoService._satir_urun(r) for r in rows]

    @staticmethod
    def depoyu_yukle() -> Depo:
        return Depo(DepoService.tum_urunleri_getir())

    @staticmethod
    def urun_getir(urun_id: int) -> Urun | None:
        r = fetchone(DepoService._SELECT + " WHERE id=?", (urun_id,))
        return DepoService._satir_urun(r) if r else None

    @staticmethod
    def urun_ara(metin: str) -> list[Urun]:
        like = f"%{(metin or '').strip()}%"
        rows = fetchall(
            DepoService._SELECT
            + " WHERE ad LIKE ? OR koridor LIKE ? OR raf LIKE ? OR goz LIKE ?"
              " OR kategori LIKE ? ORDER BY ad",
            (like, like, like, like, like),
        )
        return [DepoService._satir_urun(r) for r in rows]

    @staticmethod
    def kategorileri_getir() -> list[str]:
        """Urunlerdeki farkli kategori degerlerini sirali liste olarak
        dondurur (bos olanlari atlar)."""
        rows = fetchall(
            "SELECT DISTINCT kategori FROM urunler "
            "WHERE kategori != '' ORDER BY kategori"
        )
        return [r["kategori"] for r in rows]

    # --- yazma ----------------------------------------------------------
    @staticmethod
    def urun_ekle(ad: str, stok: int, fiyat: float,
                  koridor: str = "", raf: str = "", goz: str = "",
                  kategori: str = "") -> int:
        return execute(
            "INSERT INTO urunler "
            "(ad, stok, fiyat, koridor, raf, goz, kategori) "
            "VALUES (?,?,?,?,?,?,?)",
            (ad, int(stok), float(fiyat),
             (koridor or "").strip(), (raf or "").strip(),
             (goz or "").strip(), (kategori or "").strip()),
        )

    @staticmethod
    def urun_sil(urun_id: int) -> None:
        execute("DELETE FROM urunler WHERE id=?", (urun_id,))

    @staticmethod
    def urun_guncelle(urun_id: int, ad: str, stok: int, fiyat: float,
                      koridor: str | None = None, raf: str | None = None,
                      goz: str | None = None,
                      kategori: str | None = None) -> None:
        # Hic opsiyonel alan verilmediyse sadece ad/stok/fiyat guncelle
        if (koridor is None and raf is None and goz is None
                and kategori is None):
            execute(
                "UPDATE urunler SET ad=?, stok=?, fiyat=? WHERE id=?",
                (ad, int(stok), float(fiyat), urun_id),
            )
            return
        execute(
            "UPDATE urunler SET ad=?, stok=?, fiyat=?, "
            "koridor=?, raf=?, goz=?, kategori=? WHERE id=?",
            (ad, int(stok), float(fiyat),
             (koridor or "").strip(), (raf or "").strip(),
             (goz or "").strip(), (kategori or "").strip(), urun_id),
        )

    @staticmethod
    def lokasyon_guncelle(urun_id: int, koridor: str,
                          raf: str, goz: str) -> None:
        execute(
            "UPDATE urunler SET koridor=?, raf=?, goz=? WHERE id=?",
            ((koridor or "").strip(), (raf or "").strip(),
             (goz or "").strip(), int(urun_id)),
        )

    @staticmethod
    def fiyat_guncelle(urun_id: int, yeni_fiyat: float) -> None:
        execute("UPDATE urunler SET fiyat=? WHERE id=?", (float(yeni_fiyat), urun_id))

    @staticmethod
    def stok_guncelle(urun_id: int, yeni_stok: int) -> None:
        execute("UPDATE urunler SET stok=? WHERE id=?", (int(yeni_stok), urun_id))

    # --- stok hareketi --------------------------------------------------
    @staticmethod
    def stok_hareketi_kaydet(urun_id: int, islem_tipi: str, miktar: int,
                             kullanici_id: int | None) -> None:
        if islem_tipi not in ("giris", "cikis"):
            raise ValueError("islem_tipi 'giris' veya 'cikis' olmalidir.")
        execute(
            "INSERT INTO stok_hareketleri (urun_id, islem_tipi, miktar, kullanici_id) "
            "VALUES (?,?,?,?)",
            (urun_id, islem_tipi, int(miktar), kullanici_id),
        )

    @staticmethod
    def stok_arttir(urun_id: int, miktar: int, kullanici_id: int | None) -> Urun:
        urun = DepoService.urun_getir(urun_id)
        if not urun:
            raise ValueError("Urun bulunamadi.")
        urun.stok_arttir(miktar)  # bellek düzeyinde iş kuralı
        DepoService.stok_guncelle(urun.urun_id, urun.stok)
        DepoService.stok_hareketi_kaydet(urun.urun_id, "giris", miktar, kullanici_id)
        return urun

    @staticmethod
    def stok_azalt(urun_id: int, miktar: int, kullanici_id: int | None) -> Urun:
        urun = DepoService.urun_getir(urun_id)
        if not urun:
            raise ValueError("Urun bulunamadi.")
        urun.stok_azalt(miktar)  # stok yetersizse StokYetersizHatasi
        DepoService.stok_guncelle(urun.urun_id, urun.stok)
        DepoService.stok_hareketi_kaydet(urun.urun_id, "cikis", miktar, kullanici_id)
        return urun

    # --- raporlar -------------------------------------------------------
    @staticmethod
    def toplam_urun_sayisi() -> int:
        r = fetchone("SELECT COUNT(*) AS n FROM urunler")
        return int(r["n"]) if r else 0

    @staticmethod
    def toplam_depo_degeri() -> float:
        r = fetchone("SELECT COALESCE(SUM(stok*fiyat),0) AS t FROM urunler")
        return float(r["t"]) if r else 0.0

    @staticmethod
    def dusuk_stoklu_urunler(esik: int = Depo.DUSUK_STOK_ESIGI) -> list[Urun]:
        rows = fetchall(
            "SELECT id, ad, stok, fiyat FROM urunler WHERE stok < ? ORDER BY stok",
            (esik,),
        )
        return [Urun(r["id"], r["ad"], r["stok"], r["fiyat"]) for r in rows]

    @staticmethod
    def kullanici_bugunku_islem_sayisi(kullanici_id: int) -> int:
        r = fetchone(
            """SELECT COUNT(*) AS n FROM stok_hareketleri
                WHERE kullanici_id=? AND date(tarih)=date('now','localtime')""",
            (kullanici_id,),
        )
        return int(r["n"]) if r else 0
