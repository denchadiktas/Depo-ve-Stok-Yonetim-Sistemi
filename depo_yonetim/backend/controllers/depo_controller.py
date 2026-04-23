"""
backend/controllers/depo_controller.py
--------------------------------------
UI tarafından çağrılan yüksek seviyeli ürün/sipariş operasyonları.
Yetki kontrolü (yönetici-only / işçi-only) burada yapılır; iş kuralı
service'te.
"""

from ..models.kullanici import Kullanici
from ..models.sepet import Sepet
from ..models.urun import StokYetersizHatasi
from ..services.depo_service import DepoService
from ..services.kullanici_service import KullaniciService
from ..services.siparis_service import (
    SiparisService,
    SiparisZatenIslendi,
    KalemlerEksikHatasi,
    SiparisDurumu,
)


class YetkisizIslem(Exception):
    """İşçi'nin yetkisiz işlem denemesinde fırlatılır."""


def _yonetici_gerek(kullanici: Kullanici) -> None:
    if not kullanici or not kullanici.yonetici_mi():
        raise YetkisizIslem("Bu islem icin yonetici yetkisi gereklidir.")


def _isci_gerek(kullanici: Kullanici) -> None:
    if not kullanici or not kullanici.isci_mi():
        raise YetkisizIslem("Bu islem icin isci yetkisi gereklidir.")


class DepoController:

    # --- ortak (herkes) -------------------------------------------------
    @staticmethod
    def urunleri_getir():
        return DepoService.tum_urunleri_getir()

    @staticmethod
    def ara(metin: str):
        return DepoService.urun_ara(metin)

    @staticmethod
    def dusuk_stoklu_urunler():
        return DepoService.dusuk_stoklu_urunler()

    # --- yönetici-only --------------------------------------------------
    @staticmethod
    def urun_ekle(kullanici, ad, stok, fiyat,
                  koridor: str = "", raf: str = "", goz: str = "",
                  kategori: str = ""):
        _yonetici_gerek(kullanici)
        return DepoService.urun_ekle(
            ad, stok, fiyat, koridor, raf, goz, kategori,
        )

    @staticmethod
    def urun_sil(kullanici, urun_id):
        _yonetici_gerek(kullanici)
        DepoService.urun_sil(urun_id)

    @staticmethod
    def urun_guncelle(kullanici, urun_id, ad, stok, fiyat,
                      koridor: str | None = None,
                      raf: str | None = None,
                      goz: str | None = None,
                      kategori: str | None = None):
        _yonetici_gerek(kullanici)
        DepoService.urun_guncelle(urun_id, ad, stok, fiyat,
                                  koridor, raf, goz, kategori)

    @staticmethod
    def kategorileri_getir():
        return DepoService.kategorileri_getir()

    @staticmethod
    def lokasyon_guncelle(kullanici, urun_id, koridor, raf, goz):
        _yonetici_gerek(kullanici)
        DepoService.lokasyon_guncelle(urun_id, koridor, raf, goz)

    @staticmethod
    def fiyat_guncelle(kullanici, urun_id, yeni_fiyat):
        _yonetici_gerek(kullanici)
        DepoService.fiyat_guncelle(urun_id, yeni_fiyat)

    @staticmethod
    def toplam_depo_degeri():
        return DepoService.toplam_depo_degeri()

    @staticmethod
    def toplam_urun_sayisi():
        return DepoService.toplam_urun_sayisi()

    # --- stok işlemleri (işçi + yönetici) -------------------------------
    @staticmethod
    def stok_arttir(kullanici, urun_id, miktar):
        return DepoService.stok_arttir(urun_id, miktar, kullanici.kullanici_id)

    @staticmethod
    def stok_azalt(kullanici, urun_id, miktar):
        # StokYetersizHatasi fırlayabilir; UI yakalar.
        return DepoService.stok_azalt(urun_id, miktar, kullanici.kullanici_id)

    # --- sipariş (yönetici) ---------------------------------------------
    @staticmethod
    def sepetten_siparis_olustur(kullanici, sepet: Sepet,
                                 atanan_isci_id: int | None = None):
        """Sepetteki ürünleri 'beklemede' bir siparişe dönüştürür."""
        _yonetici_gerek(kullanici)
        return SiparisService.sepet_ile_siparis_olustur(
            sepet, kullanici.kullanici_id, atanan_isci_id
        )

    @staticmethod
    def siparise_isci_ata(kullanici, siparis_id: int, isci_id: int | None):
        _yonetici_gerek(kullanici)
        SiparisService.isciye_ata(siparis_id, isci_id)

    @staticmethod
    def siparisi_iptal_et(kullanici, siparis_id: int):
        """Beklemede veya kismi_tamamlandi siparisi iptal eder.
        Kismi durumda dusen stoklar otomatik geri yuklenir."""
        _yonetici_gerek(kullanici)
        return SiparisService.siparisi_iptal_et(
            siparis_id, iptal_eden_id=kullanici.kullanici_id
        )

    @staticmethod
    def hizlandirma_iste(kullanici, siparis_id: int):
        _yonetici_gerek(kullanici)
        SiparisService.hizlandirma_iste(siparis_id)

    @staticmethod
    def rastgele_siparis_uret(kullanici, adet: int = 1):
        """Yonetici elle veya otomatik cagri ile N rastgele siparis uretir.
        Dondurulen: olusturulan siparis id'leri listesi."""
        _yonetici_gerek(kullanici)
        return SiparisService.toplu_rastgele_siparis(
            olusturan_id=kullanici.kullanici_id,
            n=int(adet),
        )

    @staticmethod
    def tum_siparisler(kullanici):
        _yonetici_gerek(kullanici)
        return SiparisService.tum_siparisler()

    @staticmethod
    def siparis_istatistikleri(kullanici):
        _yonetici_gerek(kullanici)
        return SiparisService.istatistikler()

    @staticmethod
    def gunluk_siparis_sayilari(kullanici, gun: int = 7):
        _yonetici_gerek(kullanici)
        return SiparisService.gunluk_siparis_sayilari(gun)

    @staticmethod
    def iscileri_getir(kullanici):
        """Yönetici, sipariş atamak için işçi listesini görür."""
        _yonetici_gerek(kullanici)
        return KullaniciService.tum_isciler()

    # --- sipariş (işçi) -------------------------------------------------
    @staticmethod
    def bana_atanan_siparisler(kullanici, sadece_bekleyen: bool = True):
        _isci_gerek(kullanici)
        return SiparisService.isciye_atanan_siparisler(
            kullanici.kullanici_id, sadece_bekleyen
        )

    @staticmethod
    def siparis_detayi(siparis_id: int):
        return SiparisService.siparis_detayi_getir(siparis_id)

    @staticmethod
    def kalem_hazir_isaretle(kullanici, detay_id: int, hazir: bool):
        """İşçinin siparis kalemini raftan toplayıp işaretlemesi.
        Stok burada DUSMEZ — yalnızca `hazirlandi` bayragi guncellenir."""
        _isci_gerek(kullanici)
        return SiparisService.kalem_hazir_toggle(
            detay_id, hazir, kullanici.kullanici_id
        )

    @staticmethod
    def siparisi_tamamla(kullanici, siparis_id: int):
        """Tum kalemler hazirlandiktan sonra siparisi atomik tamamlar.

        Fırlatabileceği istisnalar:
          * KalemlerEksikHatasi — hala hazirlanmayan kalem var
          * StokYetersizHatasi  — son kontrolde stok dusmus
          * SiparisZatenIslendi — siparis durumu beklemede degil
          * PermissionError     — baska isciye atanmis
        """
        _isci_gerek(kullanici)
        return SiparisService.siparisi_tamamla(siparis_id, kullanici.kullanici_id)

    @staticmethod
    def siparisi_kismi_tamamla(kullanici, siparis_id: int):
        """Isaretli kalemleri dus, kalanlari beklemede birak, durumu
        'kismi_tamamlandi' yap. En az bir kalem isaretli olmalidir."""
        _isci_gerek(kullanici)
        return SiparisService.siparisi_kismi_tamamla(
            siparis_id, kullanici.kullanici_id
        )

    # --- rapor ----------------------------------------------------------
    @staticmethod
    def bugunku_islem_sayisi(kullanici_id: int) -> int:
        return DepoService.kullanici_bugunku_islem_sayisi(kullanici_id)

    @staticmethod
    def isci_performans(kullanici, gun: int = 30):
        _yonetici_gerek(kullanici)
        return KullaniciService.isci_performans(gun)


__all__ = [
    "DepoController",
    "YetkisizIslem",
    "StokYetersizHatasi",
    "SiparisZatenIslendi",
    "KalemlerEksikHatasi",
    "SiparisDurumu",
]
