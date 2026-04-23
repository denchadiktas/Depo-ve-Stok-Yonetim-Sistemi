"""
backend/models/siparis.py
-------------------------
Siparis domain sınıfı.

Siparişler artık sepet-tabanlıdır: bir sipariş birden fazla kalemden
(urun + adet) oluşur, bir yönetici tarafından oluşturulur ve bir işçiye
atanabilir. Durum akışı:

    beklemede  ->  hazirlaniyor  ->  tamamlandi

Stok kontrolü ve düşümü `SiparisService.siparisi_tamamla()` içinde
atomik olarak yapılır; burada sadece iş kuralları (adet/durum) bulunur.
"""

from .urun import Urun, StokYetersizHatasi


class SiparisDurumu:
    BEKLEMEDE = "beklemede"
    HAZIRLANIYOR = "hazirlaniyor"
    TAMAMLANDI = "tamamlandi"
    IPTAL = "iptal"
    KISMI_TAMAMLANDI = "kismi_tamamlandi"

    HEPSI = (BEKLEMEDE, HAZIRLANIYOR, TAMAMLANDI, IPTAL, KISMI_TAMAMLANDI)


class SiparisDetay:
    """Bir siparişin tek kalemini temsil eder."""

    def __init__(self, urun: Urun, adet: int):
        if adet <= 0:
            raise ValueError("Siparis detay adeti pozitif olmalidir.")
        self.urun = urun
        self.adet = int(adet)

    def tutar(self) -> float:
        return self.adet * self.urun.fiyat

    def __repr__(self) -> str:
        return f"SiparisDetay(urun='{self.urun.ad}', adet={self.adet})"


class Siparis:
    def __init__(
        self,
        siparis_id: int | None,
        olusturan_id: int,
        atanan_isci_id: int | None = None,
        durum: str = SiparisDurumu.BEKLEMEDE,
        tarih: str | None = None,
        detaylar: list[SiparisDetay] | None = None,
        hizlandirma_istendi: bool = False,
    ):
        if durum not in SiparisDurumu.HEPSI:
            raise ValueError(f"Gecersiz siparis durumu: {durum}")
        self.siparis_id = siparis_id
        self.olusturan_id = int(olusturan_id)
        self.atanan_isci_id = (
            int(atanan_isci_id) if atanan_isci_id is not None else None
        )
        self.durum = durum
        self.tarih = tarih
        self.detaylar: list[SiparisDetay] = list(detaylar) if detaylar else []
        self.hizlandirma_istendi = bool(hizlandirma_istendi)

    # --- iş kuralları --------------------------------------------------
    def detay_ekle(self, urun: Urun, adet: int) -> None:
        self.detaylar.append(SiparisDetay(urun, adet))

    def isciye_ata(self, isci_id: int) -> None:
        self.atanan_isci_id = int(isci_id)

    def hazirlaniyora_al(self) -> None:
        if self.durum != SiparisDurumu.BEKLEMEDE:
            raise ValueError(
                f"Yalnizca 'beklemede' olan siparisler hazirlanabilir "
                f"(mevcut: {self.durum})."
            )
        self.durum = SiparisDurumu.HAZIRLANIYOR

    def tamamla(self) -> None:
        if self.durum not in (SiparisDurumu.BEKLEMEDE, SiparisDurumu.HAZIRLANIYOR):
            raise ValueError(
                f"Siparis 'tamamlandi' olarak isaretlenemez (mevcut: {self.durum})."
            )
        self.durum = SiparisDurumu.TAMAMLANDI

    # --- yardımcılar ---------------------------------------------------
    def toplam_tutar(self) -> float:
        return sum(d.tutar() for d in self.detaylar)

    def toplam_adet(self) -> int:
        return sum(d.adet for d in self.detaylar)

    def __repr__(self) -> str:
        return (
            f"Siparis(id={self.siparis_id}, durum='{self.durum}', "
            f"kalem={len(self.detaylar)}, tutar={self.toplam_tutar():.2f})"
        )


__all__ = [
    "Siparis",
    "SiparisDetay",
    "SiparisDurumu",
    "StokYetersizHatasi",
]
