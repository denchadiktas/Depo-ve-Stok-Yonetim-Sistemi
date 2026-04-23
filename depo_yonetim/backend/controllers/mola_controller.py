"""
backend/controllers/mola_controller.py
--------------------------------------
Mola eylemlerini ve mola ile ilgili metrikleri UI'a sunar.
"""

from ..models.mola_yonetimi import MolaYonetimi
from ..services.mola_service import MolaService
from ..services.kullanici_service import KullaniciService


class MolaController:
    # UI kolayligi icin sabitleri disariya da ac
    KISA_DK = MolaYonetimi.KISA_DK
    UZUN_DK = MolaYonetimi.UZUN_DK
    GUN_MAKS_KISA = MolaYonetimi.GUN_MAKS_KISA
    GUN_MAKS_UZUN = MolaYonetimi.GUN_MAKS_UZUN
    MAKS_MOLA = MolaYonetimi.MAKS_MOLA

    def __init__(self):
        self.service = MolaService()

    # --- eylemler -------------------------------------------------------
    def molaya_cik(self, isci_id: int,
                   sure_dk: int = KISA_DK) -> tuple[bool, str]:
        return self.service.molaya_cik(isci_id, sure_dk)

    def moladan_don(self, isci_id: int) -> tuple[bool, str]:
        return self.service.moladan_don(isci_id)

    def expireli_bitir(self) -> int:
        """Sureleri dolan molalari manuel tetikle (poll oncesi faydali)."""
        return self.service.expireli_bitir()

    # --- isci bazli sorgular -------------------------------------------
    def aktif_mola(self, isci_id: int) -> dict | None:
        return self.service.aktif_mola(isci_id)

    def gunluk_kullanim(self, isci_id: int) -> dict:
        return self.service.gunluk_kullanim(isci_id)

    def kalan_haklar(self, isci_id: int) -> dict:
        return self.service.kalan_haklar(isci_id)

    # --- metrikler ------------------------------------------------------
    def moladaki_sayi(self) -> int:
        return self.service.moladaki_sayi()

    def aktif_calisan_sayisi(self) -> int:
        return self.service.aktif_calisan_sayisi()

    def kalan_kapasite(self) -> int:
        return self.service.kalan_kapasite()

    def isci_molada_mi(self, isci_id: int) -> bool:
        return self.service.isci_molada_mi(isci_id)

    def moladaki_isciler(self) -> list[dict]:
        return self.service.moladaki_isciler()

    def toplam_isci_sayisi(self) -> int:
        return KullaniciService.toplam_isci_sayisi()

    def isci_bugun_mola_sayisi(self, isci_id: int) -> int:
        return self.service.isci_bugun_mola_sayisi(isci_id)
