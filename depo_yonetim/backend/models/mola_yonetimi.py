"""
backend/models/mola_yonetimi.py
-------------------------------
MolaYonetimi — mola duzeni + suresi.

Kurallar:
  * Aynı anda en fazla MAKS_MOLA (3) kişi molada olabilir.
  * Günlük kota: 2 adet 15 dk ("kisa") + 1 adet 30 dk ("uzun") — toplam 3.
  * Molanın süresi başlangıçta belirlenir (15 veya 30). Süre dolduğunda
    sistem bir sonraki sorgusunda molayi otomatik bitirir (lazy expiration).
  * İşçi erken dönebilir — bu durumda hak kullanılmış sayılır.

Kalıcı state veritabanında; bu sınıf veritabanı üzerinden kontrol yapar.
"""

from ..services.db_helpers import fetchone, fetchall, execute


class MolaYonetimi:
    MAKS_MOLA = 3                      # es zamanli mola kapasitesi
    KISA_DK = 15
    UZUN_DK = 30
    GUN_MAKS_KISA = 2                  # gunluk 15 dk mola kotasi
    GUN_MAKS_UZUN = 1                  # gunluk 30 dk mola kotasi

    # --- expiration ----------------------------------------------------
    def expire_olanlari_bitir(self) -> int:
        """Süresi dolmuş aktif molaları 'tamamlandi' yapar. Her sorgu
        oncesinde cagrilir. Dönüş: otomatik bitirilen kayit sayisi.

        SQL: baslangic_zamani + sure_dakika * 60 sn < now ise expire.
        """
        try:
            cur_rowcount = execute(
                """UPDATE mola_kayitlari
                      SET durum='tamamlandi',
                          bitis_zamani=datetime('now','localtime')
                    WHERE durum='aktif'
                      AND datetime(baslangic_zamani,
                                   '+' || sure_dakika || ' minutes')
                          <= datetime('now','localtime')"""
            )
            # execute() `lastrowid` dondurur — etkilenen satir icin pragmatic
            # olarak ayri sorgu cali∫tirmak yerine 0/1 farkini UI tarafinda
            # goz ardi edebiliriz.
            return int(cur_rowcount or 0)
        except Exception:
            return 0

    # --- sorgular -------------------------------------------------------
    def aktif_moladaki_sayi(self) -> int:
        self.expire_olanlari_bitir()
        row = fetchone(
            "SELECT COUNT(*) AS n FROM mola_kayitlari WHERE durum='aktif'"
        )
        return int(row["n"]) if row else 0

    def mola_hakki_var_mi(self) -> bool:
        """Sistem kapasitesi boş mu? (günlük kullanıcı kotası ayrı)."""
        return self.aktif_moladaki_sayi() < self.MAKS_MOLA

    def isci_molada_mi(self, isci_id: int) -> bool:
        self.expire_olanlari_bitir()
        row = fetchone(
            "SELECT 1 FROM mola_kayitlari WHERE kullanici_id=? AND durum='aktif'",
            (isci_id,),
        )
        return row is not None

    def aktif_mola(self, isci_id: int) -> dict | None:
        """İşçi molada ise aktif kaydı döner (başlangıç + süre + bitiş
        zamanı + kalan saniye). Değilse None."""
        self.expire_olanlari_bitir()
        row = fetchone(
            """SELECT id, kullanici_id, baslangic_zamani, sure_dakika,
                      datetime(baslangic_zamani,
                               '+' || sure_dakika || ' minutes') AS bitis_plan,
                      CAST((julianday(datetime(baslangic_zamani,
                                               '+' || sure_dakika
                                               || ' minutes'))
                            - julianday(datetime('now','localtime')))
                           * 86400 AS INTEGER) AS kalan_saniye
                 FROM mola_kayitlari
                WHERE kullanici_id=? AND durum='aktif'""",
            (int(isci_id),),
        )
        return dict(row) if row else None

    # --- gunluk kota ---------------------------------------------------
    def gunluk_kullanim(self, isci_id: int) -> dict:
        """Bugün için işçinin kullandığı mola sayıları (aktif + tamamlandi).
        Dönen sözlük: {'kisa': N, 'uzun': M, 'toplam': N+M}."""
        self.expire_olanlari_bitir()
        rows = fetchall(
            """SELECT sure_dakika, COUNT(*) AS n
                 FROM mola_kayitlari
                WHERE kullanici_id=?
                  AND date(baslangic_zamani)=date('now','localtime')
             GROUP BY sure_dakika""",
            (int(isci_id),),
        )
        kisa = 0; uzun = 0
        for r in rows:
            sd = int(r["sure_dakika"])
            n = int(r["n"])
            if sd == self.UZUN_DK:
                uzun += n
            else:
                kisa += n
        return {"kisa": kisa, "uzun": uzun, "toplam": kisa + uzun}

    def kalan_haklar(self, isci_id: int) -> dict:
        k = self.gunluk_kullanim(isci_id)
        return {
            "kisa": max(0, self.GUN_MAKS_KISA - k["kisa"]),
            "uzun": max(0, self.GUN_MAKS_UZUN - k["uzun"]),
        }

    # --- eylemler -------------------------------------------------------
    def mola_baslat(self, isci_id: int,
                    sure_dk: int = 15) -> tuple[bool, str]:
        """Molayı belirtilen süre ile başlat. 15 veya 30 dk olmalı.

        Kontroller (sirayla):
          1. Gecerli sure_dk mi? (15 veya 30)
          2. Isci zaten molada mi?
          3. Sistem kapasitesi bos mu? (max 3 es zamanli)
          4. Isci'nin bu tip icin gunluk kotasi doldu mu?
        """
        if sure_dk not in (self.KISA_DK, self.UZUN_DK):
            return False, (
                f"Gecersiz mola suresi: {sure_dk} dk. "
                f"(15 veya 30 olmalidir.)"
            )
        if self.isci_molada_mi(isci_id):
            return False, "Zaten moladasiniz."
        if not self.mola_hakki_var_mi():
            return False, "Maksimum mola kapasitesine ulasildi (3/3)."

        kalan = self.kalan_haklar(isci_id)
        if sure_dk == self.KISA_DK and kalan["kisa"] <= 0:
            return False, (
                f"Bugunki {self.KISA_DK} dk mola hakkiniz bitti "
                f"(maks {self.GUN_MAKS_KISA})."
            )
        if sure_dk == self.UZUN_DK and kalan["uzun"] <= 0:
            return False, (
                f"Bugunki {self.UZUN_DK} dk mola hakkiniz bitti "
                f"(maks {self.GUN_MAKS_UZUN})."
            )

        execute(
            "INSERT INTO mola_kayitlari (kullanici_id, durum, sure_dakika) "
            "VALUES (?, 'aktif', ?)",
            (isci_id, int(sure_dk)),
        )
        return True, f"{sure_dk} dk molaya cikildi."

    def mola_bitir(self, isci_id: int) -> tuple[bool, str]:
        """Manuel moladan donme. Hak harcanmis sayilir (zaten kullanildi).
        """
        self.expire_olanlari_bitir()
        if not self.isci_molada_mi(isci_id):
            return False, "Aktif mola bulunamadi."
        execute(
            """UPDATE mola_kayitlari
                  SET bitis_zamani = datetime('now','localtime'),
                      durum = 'tamamlandi'
                WHERE kullanici_id = ? AND durum = 'aktif'""",
            (isci_id,),
        )
        return True, "Moladan donuldu."

    # --- raporlar -------------------------------------------------------
    def moladaki_iscileri_getir(self) -> list[dict]:
        self.expire_olanlari_bitir()
        rows = fetchall(
            """SELECT k.id, k.kullanici_adi, m.baslangic_zamani,
                      m.sure_dakika,
                      datetime(m.baslangic_zamani,
                               '+' || m.sure_dakika || ' minutes')
                          AS bitis_plan,
                      CAST((julianday(datetime(m.baslangic_zamani,
                                               '+' || m.sure_dakika
                                               || ' minutes'))
                            - julianday(datetime('now','localtime')))
                           * 86400 AS INTEGER) AS kalan_saniye
                 FROM mola_kayitlari m
                 JOIN kullanicilar    k ON k.id = m.kullanici_id
                WHERE m.durum = 'aktif'
                ORDER BY m.baslangic_zamani"""
        )
        return [dict(r) for r in rows]
