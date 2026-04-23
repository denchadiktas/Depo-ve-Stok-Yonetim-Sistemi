"""
backend/services/kullanici_service.py
-------------------------------------
Kullanıcı (giriş + listeleme) işlemleri.
"""

import secrets

from ..models.kullanici import Kullanici, Yonetici
from ..models.isci import Isci
from .db_helpers import fetchone, fetchall, execute
from . import sifre as sifre_util


def _sabit_zaman_esit(a: str, b: str) -> bool:
    """Eski plain-text sifre karsilastirmasi icin timing-attack koruma."""
    return secrets.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


class KullaniciService:

    @staticmethod
    def giris_yap(kullanici_adi: str, sifre: str) -> Kullanici | None:
        """Giris dogrulamasi — hash oncelikli. Eski plain-text kayitlari
        ilk basarili giriste lazy olarak hash'e tasir."""
        row = fetchone(
            "SELECT id, kullanici_adi, sifre, sifre_hash, sifre_salt, rol "
            "FROM kullanicilar WHERE kullanici_adi=?",
            (kullanici_adi,),
        )
        if not row:
            return None

        h = row["sifre_hash"] if "sifre_hash" in row.keys() else ""
        s = row["sifre_salt"] if "sifre_salt" in row.keys() else ""
        plain_eski = row["sifre"] or ""

        # 1) Hash varsa dogrula
        if h and s:
            if not sifre_util.dogrula(sifre, h, s):
                return None
        # 2) Eski plain-text -> sabit-zaman kontrol + lazy migrate
        elif plain_eski:
            if not _sabit_zaman_esit(sifre, plain_eski):
                return None
            yeni_h, yeni_s = sifre_util.hash_et(sifre)
            execute(
                "UPDATE kullanicilar "
                "SET sifre_hash=?, sifre_salt=?, sifre='' WHERE id=?",
                (yeni_h, yeni_s, int(row["id"])),
            )
        else:
            # Ne hash ne plain — kullanici giriemez
            return None

        if row["rol"] == Kullanici.ROL_YONETICI:
            return Yonetici(row["id"], row["kullanici_adi"], "")
        return Isci(row["id"], row["kullanici_adi"], "")

    @staticmethod
    def sifre_degistir(kullanici_id: int, eski_sifre: str,
                       yeni_sifre: str) -> tuple[bool, str]:
        """Kullanici kendi sifresini degistirir. Basari/uyari mesaji
        ile birlikte donen tuple UI'a dogrudan yansitilabilir."""
        if not yeni_sifre or len(yeni_sifre) < 4:
            return False, "Yeni sifre en az 4 karakter olmalidir."
        if yeni_sifre == eski_sifre:
            return False, "Yeni sifre eski sifre ile ayni olamaz."
        row = fetchone(
            "SELECT sifre, sifre_hash, sifre_salt FROM kullanicilar "
            "WHERE id=?",
            (int(kullanici_id),),
        )
        if not row:
            return False, "Kullanici bulunamadi."

        h = row["sifre_hash"] or ""
        s = row["sifre_salt"] or ""
        plain_eski = row["sifre"] or ""

        if h and s:
            if not sifre_util.dogrula(eski_sifre, h, s):
                return False, "Mevcut sifre hatali."
        elif plain_eski:
            if not _sabit_zaman_esit(eski_sifre, plain_eski):
                return False, "Mevcut sifre hatali."
        else:
            return False, "Sifre kaydi yok."

        yeni_h, yeni_s = sifre_util.hash_et(yeni_sifre)
        execute(
            "UPDATE kullanicilar "
            "SET sifre_hash=?, sifre_salt=?, sifre='' WHERE id=?",
            (yeni_h, yeni_s, int(kullanici_id)),
        )
        return True, "Sifre basariyla degistirildi."

    @staticmethod
    def tum_isciler() -> list[Isci]:
        rows = fetchall(
            "SELECT id, kullanici_adi, sifre FROM kullanicilar WHERE rol=?",
            (Kullanici.ROL_ISCI,),
        )
        return [Isci(r["id"], r["kullanici_adi"], r["sifre"]) for r in rows]

    # ------------------------------------------------------------------
    # Admin yonetimi: kullanici CRUD
    # ------------------------------------------------------------------
    @staticmethod
    def tum_kullanicilar() -> list[dict]:
        """Tablo gorunumu icin tum kullanicilari donen liste (sifre hariç)."""
        rows = fetchall(
            "SELECT id, kullanici_adi, rol FROM kullanicilar ORDER BY id"
        )
        return [dict(r) for r in rows]

    @staticmethod
    def kullanici_ekle(kullanici_adi: str, sifre: str,
                       rol: str) -> tuple[bool, str]:
        """Yeni isci veya yonetici ekle. Sifre hash'lenerek kaydedilir."""
        kullanici_adi = (kullanici_adi or "").strip()
        if not kullanici_adi:
            return False, "Kullanici adi bos olamaz."
        if not sifre or len(sifre) < 4:
            return False, "Sifre en az 4 karakter olmalidir."
        if rol not in (Kullanici.ROL_YONETICI, Kullanici.ROL_ISCI):
            return False, f"Gecersiz rol: {rol}"
        # Duplicate kontrol
        r = fetchone(
            "SELECT id FROM kullanicilar WHERE kullanici_adi=?",
            (kullanici_adi,),
        )
        if r:
            return False, f"'{kullanici_adi}' kullanici adi zaten kayitli."
        h, s = sifre_util.hash_et(sifre)
        execute(
            "INSERT INTO kullanicilar "
            "(kullanici_adi, sifre, sifre_hash, sifre_salt, rol) "
            "VALUES (?,?,?,?,?)",
            (kullanici_adi, "", h, s, rol),
        )
        return True, f"'{kullanici_adi}' kullanicisi eklendi."

    @staticmethod
    def kullanici_sil(kullanici_id: int,
                      koruma_admin_id: int | None = None) -> tuple[bool, str]:
        """Kullanici sil. Admin'in kendini silmesini engeller (koruma_id
        verilirse); ayrica son kalan yoneticiyi silmeyi yasaklar."""
        r = fetchone(
            "SELECT id, kullanici_adi, rol FROM kullanicilar WHERE id=?",
            (int(kullanici_id),),
        )
        if not r:
            return False, "Kullanici bulunamadi."
        if koruma_admin_id is not None and int(r["id"]) == int(koruma_admin_id):
            return False, "Kendi hesabinizi silemezsiniz."
        if r["rol"] == Kullanici.ROL_YONETICI:
            sayim = fetchone(
                "SELECT COUNT(*) AS n FROM kullanicilar WHERE rol=?",
                (Kullanici.ROL_YONETICI,),
            )
            if sayim and int(sayim["n"]) <= 1:
                return False, "Son yonetici silinemez (sistemin kilitlenmemesi icin)."
        execute("DELETE FROM kullanicilar WHERE id=?", (int(kullanici_id),))
        return True, f"'{r['kullanici_adi']}' silindi."

    @staticmethod
    def sifre_sifirla(kullanici_id: int,
                      yeni_sifre: str) -> tuple[bool, str]:
        """Admin tarafindan bir kullanicinin sifresini sifirlama — eski
        sifreyi bilmeye gerek yok."""
        if not yeni_sifre or len(yeni_sifre) < 4:
            return False, "Yeni sifre en az 4 karakter olmalidir."
        r = fetchone(
            "SELECT id, kullanici_adi FROM kullanicilar WHERE id=?",
            (int(kullanici_id),),
        )
        if not r:
            return False, "Kullanici bulunamadi."
        h, s = sifre_util.hash_et(yeni_sifre)
        execute(
            "UPDATE kullanicilar "
            "SET sifre_hash=?, sifre_salt=?, sifre='' WHERE id=?",
            (h, s, int(kullanici_id)),
        )
        return True, f"'{r['kullanici_adi']}' kullanicisinin sifresi sifirlandi."

    @staticmethod
    def toplam_isci_sayisi() -> int:
        r = fetchone(
            "SELECT COUNT(*) AS n FROM kullanicilar WHERE rol=?",
            (Kullanici.ROL_ISCI,),
        )
        return int(r["n"]) if r else 0

    # ------------------------------------------------------------------
    # Performans takibi
    # ------------------------------------------------------------------
    @staticmethod
    def isci_performans(gun: int = 30) -> list[dict]:
        """Son `gun` gun icinde her isci icin performans ozeti.

        Dönen her satirda:
          * isci_id, kullanici_adi
          * tamamlanan_siparis          : durum='tamamlandi' sipariş sayisi
          * kismi_tamamlanan            : durum='kismi_tamamlandi' sayisi
          * toplam_kalem                : islenen kalem sayisi
          * toplam_adet                 : islenen toplam adet
          * ortalama_sure_saniye        : tamamlananlarin ortalama sure
          * stok_hareketi_sayisi        : son gun icindeki stok islem sayisi
        """
        rows = fetchall(
            """SELECT k.id AS isci_id, k.kullanici_adi,
                      SUM(CASE WHEN s.durum='tamamlandi' THEN 1 ELSE 0 END)
                          AS tamamlanan_siparis,
                      SUM(CASE WHEN s.durum='kismi_tamamlandi' THEN 1 ELSE 0 END)
                          AS kismi_tamamlanan,
                      COALESCE(SUM(CASE WHEN sd.hazirlandi IN (1,2)
                                        THEN 1 ELSE 0 END), 0)
                          AS toplam_kalem,
                      COALESCE(SUM(CASE WHEN sd.hazirlandi IN (1,2)
                                        THEN sd.adet ELSE 0 END), 0)
                          AS toplam_adet,
                      AVG(CASE
                            WHEN s.durum IN ('tamamlandi','kismi_tamamlandi')
                             AND s.hazirlanma_baslangic IS NOT NULL
                             AND s.hazirlanma_bitis IS NOT NULL
                            THEN (julianday(s.hazirlanma_bitis) -
                                  julianday(s.hazirlanma_baslangic)) * 86400.0
                            END) AS ortalama_sure_saniye
                 FROM kullanicilar k
            LEFT JOIN siparisler s
                   ON s.atanan_isci_id = k.id
                  AND date(s.tarih) >= date('now','localtime', ?)
            LEFT JOIN siparis_detaylari sd ON sd.siparis_id = s.id
                WHERE k.rol = ?
             GROUP BY k.id
             ORDER BY tamamlanan_siparis DESC, kismi_tamamlanan DESC""",
            (f"-{int(gun) - 1} days", Kullanici.ROL_ISCI),
        )
        out = [dict(r) for r in rows]
        # stok hareketi sayisi ayri sorgu
        hareket_rows = fetchall(
            """SELECT kullanici_id, COUNT(*) AS n
                 FROM stok_hareketleri
                WHERE date(tarih) >= date('now','localtime', ?)
             GROUP BY kullanici_id""",
            (f"-{int(gun) - 1} days",),
        )
        hareket_map = {int(r["kullanici_id"] or 0): int(r["n"]) for r in hareket_rows}
        for o in out:
            o["stok_hareketi_sayisi"] = hareket_map.get(int(o["isci_id"]), 0)
        return out
