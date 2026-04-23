"""
backend/models/urun.py
----------------------
Urun (ürün) domain sınıfı.

Bu sınıf yalnızca iş kuralını bilir (stok arttır / azalt, yeter mi?),
veritabanını tanımaz. Kalıcılık DepoService katmanının sorumluluğundadır.

Lokasyon bilgisi: koridor / raf / goz. İşçi paneli bu alanlara göre
sıralama yaparak "toplama rotası" oluşturur.
"""


class StokYetersizHatasi(Exception):
    """Stok azaltma talebi mevcut stoktan büyükse fırlatılır."""


class Urun:
    def __init__(
        self,
        urun_id: int | None,
        ad: str,
        stok: int,
        fiyat: float,
        koridor: str = "",
        raf: str = "",
        goz: str = "",
        kategori: str = "",
    ):
        self.urun_id = urun_id
        self.ad = ad
        self.stok = int(stok)
        self.fiyat = float(fiyat)
        self.koridor = (koridor or "").strip()
        self.raf = (raf or "").strip()
        self.goz = (goz or "").strip()
        self.kategori = (kategori or "").strip()

    # --- iş kuralları ---------------------------------------------------
    def stok_arttir(self, miktar: int) -> None:
        if miktar <= 0:
            raise ValueError("Miktar pozitif olmalidir.")
        self.stok += miktar

    def stok_azalt(self, miktar: int) -> None:
        if miktar <= 0:
            raise ValueError("Miktar pozitif olmalidir.")
        if miktar > self.stok:
            raise StokYetersizHatasi(
                f"'{self.ad}' icin stok yetersiz "
                f"(mevcut: {self.stok}, istenen: {miktar})."
            )
        self.stok -= miktar

    # --- yardimcilar ----------------------------------------------------
    def toplam_deger(self) -> float:
        return self.stok * self.fiyat

    def dusuk_stok_mu(self, esik: int = 25) -> bool:
        return self.stok < esik

    def lokasyon(self) -> str:
        parcalar = [p for p in (self.koridor, self.raf, self.goz) if p]
        return "-".join(parcalar) if parcalar else ""

    def lokasyon_key(self) -> tuple[str, str, str]:
        """Toplama rotasi siralamasi icin deterministik anahtar."""
        return (self.koridor or "~", self.raf or "~", self.goz or "~")

    def __repr__(self) -> str:
        return (
            f"Urun(id={self.urun_id}, ad='{self.ad}', stok={self.stok}, "
            f"fiyat={self.fiyat}, lokasyon='{self.lokasyon()}')"
        )
