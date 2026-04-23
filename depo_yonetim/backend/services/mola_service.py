"""
backend/services/mola_service.py
--------------------------------
MolaYonetimi'nin ince servis sarmalayicisi. Controller katmani bu
service uzerinden mola islemlerini tetikler; rapor/metrik sorgulari
burada toplanir.

Not: Her sorgu oncesinde MolaYonetimi icinden `expire_olanlari_bitir`
otomatik calisir — sureleri dolan molalar lazy olarak sonlandirilir.
"""

from ..models.mola_yonetimi import MolaYonetimi
from .db_helpers import fetchone
from .kullanici_service import KullaniciService


class MolaService:
    def __init__(self):
        self.mola = MolaYonetimi()

    # --- eylemler -------------------------------------------------------
    def molaya_cik(self, isci_id: int,
                   sure_dk: int = MolaYonetimi.KISA_DK) -> tuple[bool, str]:
        """sure_dk: 15 veya 30."""
        return self.mola.mola_baslat(isci_id, sure_dk)

    def moladan_don(self, isci_id: int) -> tuple[bool, str]:
        return self.mola.mola_bitir(isci_id)

    def expireli_bitir(self) -> int:
        return self.mola.expire_olanlari_bitir()

    # --- sorgular (isci odakli) ----------------------------------------
    def aktif_mola(self, isci_id: int) -> dict | None:
        return self.mola.aktif_mola(isci_id)

    def gunluk_kullanim(self, isci_id: int) -> dict:
        return self.mola.gunluk_kullanim(isci_id)

    def kalan_haklar(self, isci_id: int) -> dict:
        return self.mola.kalan_haklar(isci_id)

    # --- metrikler ------------------------------------------------------
    def moladaki_sayi(self) -> int:
        return self.mola.aktif_moladaki_sayi()

    def kalan_kapasite(self) -> int:
        return max(0, MolaYonetimi.MAKS_MOLA - self.moladaki_sayi())

    def aktif_calisan_sayisi(self) -> int:
        return KullaniciService.toplam_isci_sayisi() - self.moladaki_sayi()

    def isci_molada_mi(self, isci_id: int) -> bool:
        return self.mola.isci_molada_mi(isci_id)

    def moladaki_isciler(self) -> list[dict]:
        return self.mola.moladaki_iscileri_getir()

    def isci_bugun_mola_sayisi(self, isci_id: int) -> int:
        self.mola.expire_olanlari_bitir()
        r = fetchone(
            """SELECT COUNT(*) AS n FROM mola_kayitlari
                WHERE kullanici_id=?
                  AND date(baslangic_zamani)=date('now','localtime')""",
            (isci_id,),
        )
        return int(r["n"]) if r else 0
