"""
backend/models/kullanici.py
---------------------------
Kullanici temel sınıfı. Yonetici ve Isci bu sınıftan türer; rol bilgisi
yetkilendirme (yetki_var_mi) kararında kullanılır.
"""


class Kullanici:
    ROL_YONETICI = "Yonetici"
    ROL_ISCI = "Isci"

    def __init__(self, kullanici_id: int | None, kullanici_adi: str, sifre: str, rol: str):
        self.kullanici_id = kullanici_id
        self.kullanici_adi = kullanici_adi
        self.sifre = sifre
        self.rol = rol

    def yonetici_mi(self) -> bool:
        return self.rol == self.ROL_YONETICI

    def isci_mi(self) -> bool:
        return self.rol == self.ROL_ISCI

    def __repr__(self) -> str:
        return f"Kullanici(id={self.kullanici_id}, ad='{self.kullanici_adi}', rol='{self.rol}')"


class Yonetici(Kullanici):
    """Yönetici rolü – tüm CRUD ve rapor işlemlerine yetkilidir."""

    def __init__(self, kullanici_id, kullanici_adi, sifre):
        super().__init__(kullanici_id, kullanici_adi, sifre, Kullanici.ROL_YONETICI)
