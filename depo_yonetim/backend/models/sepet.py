"""
backend/models/sepet.py
-----------------------
Sepet domain sınıfı. Yönetici birden fazla ürünü sepete ekleyebilir,
her ürün için adet belirleyebilir, toplam tutarı hesaplayabilir ve
sepeti siparişe dönüştürebilir.

Kalemler `urun_id` anahtarıyla tutulur; böylece aynı ürün farklı
zamanlarda farklı Urun örneği olarak gelse bile doğru kalemi buluruz.
"""

from .urun import Urun


class Sepet:
    def __init__(self):
        # {urun_id: (Urun, adet)}
        self._kalemler: dict[int, tuple[Urun, int]] = {}

    # --- temel işlemler -------------------------------------------------
    def urun_ekle(self, urun: Urun, adet: int) -> None:
        """Sepete ürün ekler; varsa adetini artırır."""
        if adet <= 0:
            raise ValueError("Adet pozitif olmalidir.")
        if urun.urun_id is None:
            raise ValueError("Urun id'si olmayan kalem sepete eklenemez.")
        mevcut = self._kalemler.get(urun.urun_id)
        yeni_adet = (mevcut[1] if mevcut else 0) + adet
        self._kalemler[urun.urun_id] = (urun, yeni_adet)

    def urun_cikar(self, urun: Urun | int) -> None:
        """Sepetten ürünü tamamen çıkarır. Urun veya urun_id alabilir."""
        uid = urun.urun_id if isinstance(urun, Urun) else int(urun)
        self._kalemler.pop(uid, None)

    def urun_adet_guncelle(self, urun: Urun | int, adet: int) -> None:
        """Belirli bir ürünün adetini günceller."""
        if adet <= 0:
            raise ValueError("Adet pozitif olmalidir.")
        uid = urun.urun_id if isinstance(urun, Urun) else int(urun)
        if uid not in self._kalemler:
            raise ValueError("Sepette bu urun yok.")
        mevcut_urun, _ = self._kalemler[uid]
        self._kalemler[uid] = (mevcut_urun, adet)

    def toplam_hesapla(self) -> float:
        """Sepetteki toplam tutarı hesaplar."""
        return sum(u.fiyat * adet for u, adet in self._kalemler.values())

    def sepeti_temizle(self) -> None:
        """Sepetteki tüm kalemleri temizler."""
        self._kalemler.clear()

    # --- sorgular -------------------------------------------------------
    def kalemler(self) -> list[tuple[Urun, int]]:
        """Sepetteki tüm (urun, adet) çiftlerini döndürür."""
        return list(self._kalemler.values())

    def kalem_sayisi(self) -> int:
        return len(self._kalemler)

    def toplam_adet(self) -> int:
        return sum(adet for _, adet in self._kalemler.values())

    def bos_mu(self) -> bool:
        return not self._kalemler

    def icerir_mi(self, urun: Urun | int) -> bool:
        uid = urun.urun_id if isinstance(urun, Urun) else int(urun)
        return uid in self._kalemler

    def __repr__(self) -> str:
        return (
            f"Sepet({self.kalem_sayisi()} kalem, "
            f"toplam={self.toplam_hesapla():.2f} TL)"
        )
