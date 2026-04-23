"""
backend/models/isci.py
----------------------
Isci sınıfı – Kullanici'dan türer ve mola durumunu taşır.
Bellek içi (in-memory) mola bilgisi tutulur; kalıcı kayıtlar
mola_kayitlari tablosunda MolaService aracılığıyla tutulur.
"""

from datetime import datetime
from .kullanici import Kullanici


class Isci(Kullanici):
    def __init__(self, kullanici_id: int | None, kullanici_adi: str, sifre: str):
        super().__init__(kullanici_id, kullanici_adi, sifre, Kullanici.ROL_ISCI)
        self.molada_mi: bool = False
        self.mola_baslangic: datetime | None = None
        self.mola_bitis: datetime | None = None

    def molaya_cik(self) -> None:
        self.molada_mi = True
        self.mola_baslangic = datetime.now()
        self.mola_bitis = None

    def moladan_don(self) -> None:
        self.molada_mi = False
        self.mola_bitis = datetime.now()
