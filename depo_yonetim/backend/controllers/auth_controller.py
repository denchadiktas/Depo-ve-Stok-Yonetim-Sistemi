"""
backend/controllers/auth_controller.py
--------------------------------------
UI'in kimlik dogrulama ve sifre yonetimiyle ilgili ince girisi.

  * `giris_yap(ad, sifre)`  -> Kullanici | None
  * `sifre_degistir(kullanici, eski, yeni)` -> (ok, msg)

Service katmani dogrulamayi hash uzerinden yapar; eski plain-text
kayitlar basarili girisin ardindan otomatik hash'e tasinir
(KullaniciService.giris_yap icinde lazy migration).
"""

from ..services.kullanici_service import KullaniciService
from ..models.kullanici import Kullanici


class YetkisizIslem(Exception):
    """Yonetici yetkisi gerektiren bir islemde yetki reddi."""


def _yonetici_gerek(kullanici: Kullanici) -> None:
    if not kullanici or not kullanici.yonetici_mi():
        raise YetkisizIslem("Bu islem icin yonetici yetkisi gereklidir.")


class AuthController:

    @staticmethod
    def giris_yap(kullanici_adi: str, sifre: str) -> Kullanici | None:
        if not kullanici_adi or not sifre:
            return None
        return KullaniciService.giris_yap(kullanici_adi.strip(), sifre)

    @staticmethod
    def sifre_degistir(kullanici: Kullanici,
                       eski_sifre: str,
                       yeni_sifre: str) -> tuple[bool, str]:
        if not kullanici or kullanici.kullanici_id is None:
            return False, "Oturum bulunamadi."
        return KullaniciService.sifre_degistir(
            kullanici.kullanici_id, eski_sifre, yeni_sifre,
        )

    # ---- Admin kullanici yonetimi -----------------------------------
    @staticmethod
    def tum_kullanicilar(kullanici: Kullanici) -> list[dict]:
        _yonetici_gerek(kullanici)
        return KullaniciService.tum_kullanicilar()

    @staticmethod
    def kullanici_ekle(kullanici: Kullanici,
                       kullanici_adi: str, sifre: str,
                       rol: str) -> tuple[bool, str]:
        _yonetici_gerek(kullanici)
        return KullaniciService.kullanici_ekle(kullanici_adi, sifre, rol)

    @staticmethod
    def kullanici_sil(kullanici: Kullanici,
                      hedef_id: int) -> tuple[bool, str]:
        _yonetici_gerek(kullanici)
        return KullaniciService.kullanici_sil(
            hedef_id, koruma_admin_id=kullanici.kullanici_id,
        )

    @staticmethod
    def sifre_sifirla(kullanici: Kullanici,
                      hedef_id: int,
                      yeni_sifre: str) -> tuple[bool, str]:
        _yonetici_gerek(kullanici)
        return KullaniciService.sifre_sifirla(hedef_id, yeni_sifre)
