"""
backend/models/depo.py
----------------------
Depo sınıfı – Urun koleksiyonu üzerinde işlem yapan toplayıcı (aggregate).

Burada yalnızca "bellek içi" davranış bulunur; veritabanı ile alışveriş
DepoService katmanında yapılır. Service, kalıcı veriyi okuyup Depo
nesnesine doldurur, sonra bu sınıfın metotlarıyla analiz/sunum yapılır.
"""

from .urun import Urun


class Depo:
    DUSUK_STOK_ESIGI = 25

    def __init__(self, urunler: list[Urun] | None = None):
        self._urunler: list[Urun] = list(urunler) if urunler else []

    # --- CRUD (bellek düzeyi) ------------------------------------------
    def urun_ekle(self, urun: Urun) -> None:
        self._urunler.append(urun)

    def urun_sil(self, urun_id: int) -> None:
        self._urunler = [u for u in self._urunler if u.urun_id != urun_id]

    def urun_guncelle(self, urun: Urun) -> None:
        for i, u in enumerate(self._urunler):
            if u.urun_id == urun.urun_id:
                self._urunler[i] = urun
                return

    # --- raporlar -------------------------------------------------------
    def urun_listele(self) -> list[Urun]:
        return list(self._urunler)

    def stok_durumu_goster(self) -> list[dict]:
        return [
            {"id": u.urun_id, "ad": u.ad, "stok": u.stok, "fiyat": u.fiyat}
            for u in self._urunler
        ]

    def dusuk_stoklari_goster(self, esik: int = DUSUK_STOK_ESIGI) -> list[Urun]:
        return [u for u in self._urunler if u.stok < esik]

    def toplam_deger(self) -> float:
        return sum(u.toplam_deger() for u in self._urunler)

    def ara(self, metin: str) -> list[Urun]:
        m = (metin or "").strip().lower()
        if not m:
            return self.urun_listele()
        return [u for u in self._urunler if m in u.ad.lower()]
