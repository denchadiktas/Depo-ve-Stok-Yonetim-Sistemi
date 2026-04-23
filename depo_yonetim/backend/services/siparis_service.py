"""
backend/services/siparis_service.py
-----------------------------------
Sepet tabanlı sipariş akışı.

İş akışı:
  1) Yönetici `sepet_ile_siparis_olustur` çağırır — siparis + detaylar
     'beklemede' olarak kaydedilir, isteğe bağlı işçiye atanır.
  2) Atanan işçi her kalemi topladıkça `kalem_hazir_toggle` ile
     işaretler — stok bu aşamada düşmez, yalnızca bayrak güncellenir.
  3) Tüm kalemler işaretlenince `siparisi_tamamla` — tek transaction
     içinde stok kontrolü + düşüm + `stok_hareketleri` 'cikis' yazımı
     + durum 'tamamlandi'. Stok yetersizse atomik rollback +
     StokYetersizHatasi. Aynı siparişin iki kez tamamlanmaması için
     koşullu UPDATE (yarış koruması) kullanılır.
  4) Kısmi tamamlama: `siparisi_kismi_tamamla` yalnızca işaretli
     kalemleri düşürür, durum 'kismi_tamamlandi'. İptal edildiğinde
     (`siparisi_iptal_et`) düşürülmüş kalemler stok'a geri yüklenir.
"""

from ..models.sepet import Sepet
from ..models.siparis import Siparis, SiparisDurumu
from ..models.urun import StokYetersizHatasi
from .db_helpers import execute, fetchone, fetchall, transaction


class SiparisZatenIslendi(Exception):
    """Aynı siparişi iki kez hazırlama / geçersiz durum geçişi."""


class KalemlerEksikHatasi(Exception):
    """Henüz hazırlanmamış kalem varken tamamlama denenirse fırlar."""


class SiparisService:

    # ------------------------------------------------------------------
    # Oluşturma
    # ------------------------------------------------------------------
    @staticmethod
    def sepet_ile_siparis_olustur(
        sepet: Sepet,
        olusturan_id: int,
        atanan_isci_id: int | None = None,
    ) -> Siparis:
        """Sepetteki kalemleri 'beklemede' durumunda bir siparişe
        dönüştürür. Stok düşümü bu aşamada YAPILMAZ — hazırlanma
        sırasında yapılır."""
        if sepet.bos_mu():
            raise ValueError("Sepet bos; siparis olusturulamaz.")

        with transaction() as conn:
            cur = conn.execute(
                "INSERT INTO siparisler (olusturan_id, atanan_isci_id, durum) "
                "VALUES (?,?,?)",
                (int(olusturan_id), atanan_isci_id, SiparisDurumu.BEKLEMEDE),
            )
            sid = cur.lastrowid
            conn.executemany(
                "INSERT INTO siparis_detaylari (siparis_id, urun_id, adet) "
                "VALUES (?,?,?)",
                [(sid, u.urun_id, int(adet)) for u, adet in sepet.kalemler()],
            )

        siparis = Siparis(
            siparis_id=sid,
            olusturan_id=olusturan_id,
            atanan_isci_id=atanan_isci_id,
            durum=SiparisDurumu.BEKLEMEDE,
        )
        for urun, adet in sepet.kalemler():
            siparis.detay_ekle(urun, adet)
        return siparis

    @staticmethod
    def isciye_ata(siparis_id: int, isci_id: int | None) -> None:
        """Bekleyen bir siparise isci ata veya atamayi degistir. `isci_id`
        None verilirse atama kaldirilir (teknik olarak 'atanmamis')."""
        r = fetchone(
            "SELECT durum FROM siparisler WHERE id=?", (int(siparis_id),)
        )
        if not r:
            raise ValueError("Siparis bulunamadi.")
        if r["durum"] != SiparisDurumu.BEKLEMEDE:
            raise SiparisZatenIslendi(
                "Yalnizca beklemedeki siparislerin atamasi degistirilebilir."
            )
        execute(
            "UPDATE siparisler SET atanan_isci_id=? WHERE id=? AND durum=?",
            (
                int(isci_id) if isci_id is not None else None,
                int(siparis_id),
                SiparisDurumu.BEKLEMEDE,
            ),
        )

    # ------------------------------------------------------------------
    # Rastgele siparis uretici (demo/stress/simulasyon)
    # ------------------------------------------------------------------
    @staticmethod
    def rastgele_siparis_uret(
        olusturan_id: int,
        atanan_isci_id: int | None = None,
        hizlandirma: bool = False,
        kalem_min: int = 1,
        kalem_max: int = 4,
    ) -> Siparis:
        """Rastgele bir siparis uretir. Stoklu urunlerden rastgele
        `kalem_min..kalem_max` arasi secer; her biri icin `1..min(stok, 3)`
        adet atar. Istenirse hizlandirma bayragini set eder."""
        import random
        from ..models.sepet import Sepet
        from .depo_service import DepoService

        urunler = [u for u in DepoService.tum_urunleri_getir() if u.stok > 0]
        if not urunler:
            raise ValueError(
                "Stogu olan urun yok; rastgele siparis uretilemez."
            )

        kalem_sayisi = random.randint(
            max(1, int(kalem_min)),
            min(max(1, int(kalem_max)), len(urunler)),
        )
        secilen = random.sample(urunler, kalem_sayisi)
        sepet = Sepet()
        for u in secilen:
            adet = random.randint(1, min(u.stok, 3))
            sepet.urun_ekle(u, adet)

        siparis = SiparisService.sepet_ile_siparis_olustur(
            sepet, olusturan_id, atanan_isci_id
        )
        if hizlandirma and siparis.siparis_id is not None:
            try:
                SiparisService.hizlandirma_iste(siparis.siparis_id)
                siparis.hizlandirma_istendi = True
            except Exception:
                pass
        return siparis

    @staticmethod
    def toplu_rastgele_siparis(
        olusturan_id: int,
        n: int = 5,
        isci_idler: list[int] | None = None,
        hizlandirma_sansi: float = 0.15,
    ) -> list[int]:
        """N rastgele siparis uret, rastgele isciye ata. Uretilebilen
        siparis id'lerini dondurur (stok yetersizliginde erken durur)."""
        import random
        from .kullanici_service import KullaniciService

        if isci_idler is None:
            isci_idler = [i.kullanici_id
                          for i in KullaniciService.tum_isciler()]

        olusturulan: list[int] = []
        for _ in range(max(0, int(n))):
            atanan = random.choice(isci_idler) if isci_idler else None
            hizlandir = random.random() < hizlandirma_sansi
            try:
                s = SiparisService.rastgele_siparis_uret(
                    olusturan_id=olusturan_id,
                    atanan_isci_id=atanan,
                    hizlandirma=hizlandir,
                )
                if s.siparis_id is not None:
                    olusturulan.append(int(s.siparis_id))
            except Exception:
                break
        return olusturulan

    # ------------------------------------------------------------------
    # Admin operasyonlari: iptal + hizlandirma istegi
    # ------------------------------------------------------------------
    @staticmethod
    def siparisi_iptal_et(siparis_id: int,
                          iptal_eden_id: int | None = None) -> dict:
        """Siparisi iptal et. Iki senaryo:

        * 'beklemede' — hicbir stok dusmemis; sade durum = 'iptal'
        * 'kismi_tamamlandi' — dusen stoklari geri yukle (stok_hareketleri
          'giris' ile) ve kalan kalemleri sil; durum = 'iptal'

        Döndürülen dict: `{ 'iptal_durumu': 'bos'|'kismi',
                            'geri_yuklenen': [{urun_adi, adet}, ...] }`.
        """
        with transaction() as conn:
            s = conn.execute(
                "SELECT durum FROM siparisler WHERE id=?",
                (int(siparis_id),),
            ).fetchone()
            if not s:
                raise ValueError("Siparis bulunamadi.")
            durum = s["durum"]
            if durum not in (SiparisDurumu.BEKLEMEDE,
                             SiparisDurumu.KISMI_TAMAMLANDI):
                raise SiparisZatenIslendi(
                    f"Sadece 'beklemede' veya 'kismi_tamamlandi' durumdaki "
                    f"siparis iptal edilebilir (mevcut: {durum})."
                )

            geri_yuklenen: list[dict] = []
            if durum == SiparisDurumu.KISMI_TAMAMLANDI:
                # hazirlandi=2 kalemler icin stok geri yuklemesi yap
                tamamlanan = conn.execute(
                    """SELECT sd.urun_id, sd.adet, u.ad AS urun_adi
                         FROM siparis_detaylari sd
                         JOIN urunler u ON u.id = sd.urun_id
                        WHERE sd.siparis_id=? AND sd.hazirlandi=2""",
                    (int(siparis_id),),
                ).fetchall()
                for t in tamamlanan:
                    conn.execute(
                        "UPDATE urunler SET stok = stok + ? WHERE id=?",
                        (int(t["adet"]), int(t["urun_id"])),
                    )
                    conn.execute(
                        "INSERT INTO stok_hareketleri "
                        "(urun_id, islem_tipi, miktar, kullanici_id) "
                        "VALUES (?,?,?,?)",
                        (int(t["urun_id"]), "giris", int(t["adet"]),
                         int(iptal_eden_id) if iptal_eden_id else None),
                    )
                    geri_yuklenen.append({
                        "urun_adi": t["urun_adi"],
                        "adet": int(t["adet"]),
                    })

            # Tum detay satirlarini sil ve durumu iptal yap
            conn.execute(
                "DELETE FROM siparis_detaylari WHERE siparis_id=?",
                (int(siparis_id),),
            )
            conn.execute(
                "UPDATE siparisler SET durum=? WHERE id=?",
                (SiparisDurumu.IPTAL, int(siparis_id)),
            )

        return {
            "iptal_durumu": ("kismi" if durum == SiparisDurumu.KISMI_TAMAMLANDI
                             else "bos"),
            "geri_yuklenen": geri_yuklenen,
        }

    @staticmethod
    def hizlandirma_iste(siparis_id: int) -> None:
        """Yonetici bir siparise 'acil/hizlandir' isareti koyar. Isci
        panelinde kart vurgulanır ve bildirim düşer. Tekrar çağırmak
        güvenlidir (idempotent)."""
        r = fetchone(
            "SELECT durum, hizlandirma_istendi FROM siparisler WHERE id=?",
            (int(siparis_id),),
        )
        if not r:
            raise ValueError("Siparis bulunamadi.")
        if r["durum"] != SiparisDurumu.BEKLEMEDE:
            raise SiparisZatenIslendi(
                f"Yalnizca beklemedeki siparis hizlandirilabilir "
                f"(mevcut: {r['durum']})."
            )
        execute(
            "UPDATE siparisler SET hizlandirma_istendi=1 WHERE id=?",
            (int(siparis_id),),
        )

    # ------------------------------------------------------------------
    # Kalem hazir isaretleme (isci tarafindan)
    # ------------------------------------------------------------------
    @staticmethod
    def kalem_hazir_toggle(detay_id: int, hazir: bool, isci_id: int) -> dict:
        """İşçinin raftan ürün topladıkça kalem işaretlemesi.

        Kural: yalnizca 'beklemede' durumundaki siparislerde; siparis
        isciye atanmissa yalnizca o isci degistirebilir. Stok burada
        dusmez — yalnizca hazirlandi bayragi degisir.

        İlk "hazir" işaretinde sipariste hazirlanma_baslangic kaydı
        yoksa set edilir — bu işçinin sipariste toplama islemine
        başlama anını kaydeder.

        Döndürülen dict: güncel `{detay_id, hazirlandi, hazir_sayisi,
        kalem_sayisi, tum_hazir}` — UI tek çağrıda yenileyebilsin diye.
        """
        with transaction() as conn:
            row = conn.execute(
                """SELECT sd.id AS did, sd.siparis_id,
                          s.durum, s.atanan_isci_id,
                          s.hazirlanma_baslangic
                     FROM siparis_detaylari sd
                     JOIN siparisler s ON s.id = sd.siparis_id
                    WHERE sd.id=?""",
                (int(detay_id),),
            ).fetchone()
            if not row:
                raise ValueError("Siparis detayi bulunamadi.")
            if row["durum"] != SiparisDurumu.BEKLEMEDE:
                raise SiparisZatenIslendi(
                    f"Siparis '{row['durum']}' durumunda; kalem isaretlenemez."
                )
            if (row["atanan_isci_id"] is not None and
                    int(row["atanan_isci_id"]) != int(isci_id)):
                raise PermissionError("Bu siparis baska bir isciye atanmis.")

            conn.execute(
                "UPDATE siparis_detaylari SET hazirlandi=? WHERE id=?",
                (1 if hazir else 0, int(detay_id)),
            )
            # Ilk hazir isaretinde hazirlanma_baslangic kaydi ac
            if hazir and not row["hazirlanma_baslangic"]:
                conn.execute(
                    "UPDATE siparisler "
                    "   SET hazirlanma_baslangic=datetime('now','localtime') "
                    " WHERE id=? AND hazirlanma_baslangic IS NULL",
                    (int(row["siparis_id"]),),
                )

            ozet = conn.execute(
                """SELECT COUNT(*) AS toplam,
                          SUM(CASE WHEN hazirlandi=1 THEN 1 ELSE 0 END) AS hazir
                     FROM siparis_detaylari WHERE siparis_id=?""",
                (int(row["siparis_id"]),),
            ).fetchone()
            hazir_sayi = int(ozet["hazir"] or 0)
            toplam = int(ozet["toplam"] or 0)

        return {
            "detay_id": int(detay_id),
            "hazirlandi": 1 if hazir else 0,
            "hazir_sayisi": hazir_sayi,
            "kalem_sayisi": toplam,
            "tum_hazir": toplam > 0 and hazir_sayi == toplam,
        }

    # ------------------------------------------------------------------
    # Tamamlama (tum kalemler hazir isaretlenmis olmalidir)
    # ------------------------------------------------------------------
    @staticmethod
    def siparisi_tamamla(siparis_id: int, isci_id: int) -> Siparis:
        """Toplama bitti — stoklari atomik dus ve durumu 'tamamlandi' yap.

        Ön koşullar:
          * siparis 'beklemede' durumda
          * siparis isciye atanmis (veya atanmamis olabilir)
          * tum kalemler `hazirlandi=1`
        Tek transaction içinde:
          * son stok kontrolu (işaretlemeyle stok düşümü arasında
            başka operatör stoğu azaltmis olabilir)
          * stoklar dus + stok_hareketleri 'cikis' yaz
          * durum 'tamamlandi' (kosullu UPDATE: yaris engelleme)
        """
        with transaction() as conn:
            s = conn.execute(
                "SELECT id, olusturan_id, atanan_isci_id, durum, tarih "
                "FROM siparisler WHERE id=?",
                (int(siparis_id),),
            ).fetchone()
            if not s:
                raise ValueError("Siparis bulunamadi.")
            if s["durum"] != SiparisDurumu.BEKLEMEDE:
                raise SiparisZatenIslendi(
                    f"Siparis zaten '{s['durum']}' durumunda."
                )
            if (s["atanan_isci_id"] is not None and
                    int(s["atanan_isci_id"]) != int(isci_id)):
                raise PermissionError("Bu siparis baska bir isciye atanmis.")

            detaylar = conn.execute(
                """SELECT sd.urun_id, sd.adet, sd.hazirlandi,
                          u.ad AS urun_adi, u.stok
                     FROM siparis_detaylari sd
                     JOIN urunler u ON u.id = sd.urun_id
                    WHERE sd.siparis_id=?""",
                (int(siparis_id),),
            ).fetchall()
            if not detaylar:
                raise ValueError("Siparis icin detay bulunamadi.")

            eksikler = [d["urun_adi"] for d in detaylar
                        if int(d["hazirlandi"]) != 1]
            if eksikler:
                raise KalemlerEksikHatasi(
                    "Henuz hazirlanmayan kalem(ler) var: "
                    + ", ".join(eksikler)
                )

            # son stok kontrolu (hepsi)
            yetersiz = []
            for d in detaylar:
                if d["adet"] > d["stok"]:
                    yetersiz.append(
                        f"{d['urun_adi']} (mevcut: {d['stok']}, "
                        f"istenen: {d['adet']})"
                    )
            if yetersiz:
                raise StokYetersizHatasi(
                    "Bazi urunlerde stok yetersiz: " + "; ".join(yetersiz)
                )

            # stoklari dus + hareket yaz
            for d in detaylar:
                conn.execute(
                    "UPDATE urunler SET stok = stok - ? WHERE id=?",
                    (int(d["adet"]), int(d["urun_id"])),
                )
                conn.execute(
                    "INSERT INTO stok_hareketleri "
                    "(urun_id, islem_tipi, miktar, kullanici_id) "
                    "VALUES (?,?,?,?)",
                    (int(d["urun_id"]), "cikis", int(d["adet"]), int(isci_id)),
                )

            # durumu kosullu guncelle — yari engelleme; bitis zamani da
            cur = conn.execute(
                "UPDATE siparisler SET durum=?, "
                "    atanan_isci_id=COALESCE(atanan_isci_id, ?), "
                "    hazirlanma_bitis=datetime('now','localtime') "
                "WHERE id=? AND durum=?",
                (
                    SiparisDurumu.TAMAMLANDI,
                    int(isci_id),
                    int(siparis_id),
                    SiparisDurumu.BEKLEMEDE,
                ),
            )
            if cur.rowcount != 1:
                raise SiparisZatenIslendi(
                    "Siparis durumu degismis; tamamlama engellendi."
                )

            s2 = conn.execute(
                "SELECT id, olusturan_id, atanan_isci_id, durum, tarih "
                "FROM siparisler WHERE id=?",
                (int(siparis_id),),
            ).fetchone()

        return Siparis(
            siparis_id=s2["id"],
            olusturan_id=s2["olusturan_id"],
            atanan_isci_id=s2["atanan_isci_id"],
            durum=s2["durum"],
            tarih=s2["tarih"],
        )

    # ------------------------------------------------------------------
    # Kismi tamamlama
    # ------------------------------------------------------------------
    @staticmethod
    def siparisi_kismi_tamamla(siparis_id: int, isci_id: int) -> Siparis:
        """İşaretli kalemleri düş, kalan kalemleri beklemede bırak ve
        durumu 'kismi_tamamlandi' yap. Tek kalem bile işaretli değilse
        KalemlerEksikHatasi fırlar. Tüm kalemler işaretli ise zaten
        `siparisi_tamamla` kullanmalı — burada da uyarı veririz.
        """
        with transaction() as conn:
            s = conn.execute(
                "SELECT atanan_isci_id, durum FROM siparisler WHERE id=?",
                (int(siparis_id),),
            ).fetchone()
            if not s:
                raise ValueError("Siparis bulunamadi.")
            if s["durum"] != SiparisDurumu.BEKLEMEDE:
                raise SiparisZatenIslendi(
                    f"Siparis zaten '{s['durum']}' durumunda."
                )
            if (s["atanan_isci_id"] is not None and
                    int(s["atanan_isci_id"]) != int(isci_id)):
                raise PermissionError("Bu siparis baska bir isciye atanmis.")

            detaylar = conn.execute(
                """SELECT sd.id AS did, sd.urun_id, sd.adet, sd.hazirlandi,
                          u.ad AS urun_adi, u.stok
                     FROM siparis_detaylari sd
                     JOIN urunler u ON u.id = sd.urun_id
                    WHERE sd.siparis_id=?""",
                (int(siparis_id),),
            ).fetchall()
            if not detaylar:
                raise ValueError("Siparis icin detay bulunamadi.")

            hazir_olanlar = [d for d in detaylar if int(d["hazirlandi"]) == 1]
            bekleyenler = [d for d in detaylar if int(d["hazirlandi"]) == 0]

            if not hazir_olanlar:
                raise KalemlerEksikHatasi(
                    "Kismi tamamlama icin en az bir kalem isaretlenmelidir."
                )
            if not bekleyenler:
                # Hepsi hazir — tam tamamlamaya yonlendir
                raise ValueError(
                    "Tum kalemler hazir; `siparisi_tamamla` kullanin."
                )

            # Son stok kontrolu (yalniz hazir olanlar icin)
            yetersiz = []
            for d in hazir_olanlar:
                if d["adet"] > d["stok"]:
                    yetersiz.append(
                        f"{d['urun_adi']} (mevcut: {d['stok']}, "
                        f"istenen: {d['adet']})"
                    )
            if yetersiz:
                raise StokYetersizHatasi(
                    "Bazi urunlerde stok yetersiz: " + "; ".join(yetersiz)
                )

            # Hazir olan kalemleri dus + hareket yaz. Detay satirlari
            # silinmez; hazirlandi=2 (tamamlanan kalem) olarak isaretlenir.
            # Boylece ileride iptal edilirse stok geri yuklenebilir.
            for d in hazir_olanlar:
                conn.execute(
                    "UPDATE urunler SET stok = stok - ? WHERE id=?",
                    (int(d["adet"]), int(d["urun_id"])),
                )
                conn.execute(
                    "INSERT INTO stok_hareketleri "
                    "(urun_id, islem_tipi, miktar, kullanici_id) "
                    "VALUES (?,?,?,?)",
                    (int(d["urun_id"]), "cikis", int(d["adet"]),
                     int(isci_id)),
                )
                conn.execute(
                    "UPDATE siparis_detaylari SET hazirlandi=2 WHERE id=?",
                    (int(d["did"]),),
                )

            # Durum guncelle (kismi_tamamlandi). Bekleyen kalemler
            # beklemede durumu tasimaya devam eder; ancak asal siparis
            # artik 'kismi_tamamlandi'. Ileride iptal edilebilir veya
            # yeni bir siparis olarak ele alinabilir.
            cur = conn.execute(
                "UPDATE siparisler SET durum=?, "
                "    hazirlanma_bitis=datetime('now','localtime'), "
                "    atanan_isci_id=COALESCE(atanan_isci_id, ?) "
                "WHERE id=? AND durum=?",
                (
                    SiparisDurumu.KISMI_TAMAMLANDI,
                    int(isci_id),
                    int(siparis_id),
                    SiparisDurumu.BEKLEMEDE,
                ),
            )
            if cur.rowcount != 1:
                raise SiparisZatenIslendi(
                    "Siparis durumu degismis; kismi tamamlama engellendi."
                )

            # Henuz tamamlanmamis (hazirlandi=1) kalemlerin bayraklarini
            # sifirla — kismi tamamlama sonrasi bekleyen isaretli kalem
            # olmamali. hazirlandi=2 (tamamlanan) kayitlar korunur ki
            # ileride iptal edilirse stoklar geri yuklenebilsin.
            conn.execute(
                "UPDATE siparis_detaylari SET hazirlandi=0 "
                "WHERE siparis_id=? AND hazirlandi=1",
                (int(siparis_id),),
            )

            s2 = conn.execute(
                "SELECT id, olusturan_id, atanan_isci_id, durum, tarih "
                "FROM siparisler WHERE id=?",
                (int(siparis_id),),
            ).fetchone()

        return Siparis(
            siparis_id=s2["id"],
            olusturan_id=s2["olusturan_id"],
            atanan_isci_id=s2["atanan_isci_id"],
            durum=s2["durum"],
            tarih=s2["tarih"],
        )

    # ------------------------------------------------------------------
    # Sorgular
    # ------------------------------------------------------------------
    @staticmethod
    def siparis_detayi_getir(siparis_id: int) -> dict | None:
        """Tek bir siparişi detaylarıyla birlikte döndürür."""
        s = fetchone(
            """SELECT s.id, s.olusturan_id, s.atanan_isci_id, s.durum, s.tarih,
                      s.hizlandirma_istendi,
                      s.hazirlanma_baslangic, s.hazirlanma_bitis,
                      ko.kullanici_adi AS olusturan_adi,
                      ki.kullanici_adi AS atanan_isci_adi
                 FROM siparisler s
            LEFT JOIN kullanicilar ko ON ko.id = s.olusturan_id
            LEFT JOIN kullanicilar ki ON ki.id = s.atanan_isci_id
                WHERE s.id=?""",
            (int(siparis_id),),
        )
        if not s:
            return None
        # Lokasyon alanlari ve toplama sirasi icin koridor/raf/goz al
        detaylar = fetchall(
            """SELECT sd.id AS detay_id, sd.urun_id, sd.adet, sd.hazirlandi,
                      u.ad AS urun_adi, u.fiyat, u.stok AS mevcut_stok,
                      u.koridor, u.raf, u.goz,
                      (sd.adet * u.fiyat) AS tutar
                 FROM siparis_detaylari sd
                 JOIN urunler u ON u.id = sd.urun_id
                WHERE sd.siparis_id=?
             ORDER BY
                  CASE WHEN u.koridor='' THEN 'zzz' ELSE u.koridor END,
                  CASE WHEN u.raf=''     THEN 'zzz' ELSE u.raf END,
                  CASE WHEN u.goz=''     THEN 'zzz' ELSE u.goz END,
                  u.ad""",
            (int(siparis_id),),
        )
        det_list = [dict(d) for d in detaylar]
        hazir_sayi = sum(1 for d in det_list if int(d["hazirlandi"]) == 1)
        tamamlanan_sayi = sum(1 for d in det_list if int(d["hazirlandi"]) == 2)
        # Sure hesapla (saniye)
        sure_sn = None
        s_dict = dict(s)
        try:
            from datetime import datetime
            if s_dict.get("hazirlanma_baslangic"):
                fmt = "%Y-%m-%d %H:%M:%S"
                b = datetime.strptime(s_dict["hazirlanma_baslangic"], fmt)
                bit = (datetime.strptime(s_dict["hazirlanma_bitis"], fmt)
                       if s_dict.get("hazirlanma_bitis") else datetime.now())
                sure_sn = int((bit - b).total_seconds())
        except (ValueError, TypeError):
            sure_sn = None
        s_dict["sure_saniye"] = sure_sn
        return {
            "siparis": s_dict,
            "detaylar": det_list,
            "toplam_tutar": sum(float(d["tutar"]) for d in det_list),
            "kalem_sayisi": len(det_list),
            "hazir_sayisi": hazir_sayi,
            "tamamlanan_sayisi": tamamlanan_sayi,
            "tum_hazir": len(det_list) > 0 and hazir_sayi == len(det_list),
        }

    @staticmethod
    def tum_siparisler() -> list[dict]:
        """Yönetici için tüm siparişleri (sade başlık) döndürür."""
        rows = fetchall(
            """SELECT s.id, s.durum, s.tarih, s.hizlandirma_istendi,
                      s.hazirlanma_baslangic, s.hazirlanma_bitis,
                      ko.kullanici_adi AS olusturan_adi,
                      ki.kullanici_adi AS atanan_isci_adi,
                      COALESCE(SUM(sd.adet * u.fiyat), 0) AS tutar,
                      COALESCE(SUM(sd.adet), 0) AS toplam_adet
                 FROM siparisler s
            LEFT JOIN kullanicilar ko      ON ko.id = s.olusturan_id
            LEFT JOIN kullanicilar ki      ON ki.id = s.atanan_isci_id
            LEFT JOIN siparis_detaylari sd ON sd.siparis_id = s.id
            LEFT JOIN urunler u            ON u.id = sd.urun_id
             GROUP BY s.id
             ORDER BY s.id DESC"""
        )
        return [dict(r) for r in rows]

    @staticmethod
    def istatistikler() -> dict:
        """Dashboard için durum bazlı sipariş sayaçları."""
        rows = fetchall(
            "SELECT durum, COUNT(*) AS n FROM siparisler GROUP BY durum"
        )
        sayac = {d: 0 for d in SiparisDurumu.HEPSI}
        for r in rows:
            sayac[r["durum"]] = int(r["n"])
        sayac["toplam"] = sum(sayac[d] for d in SiparisDurumu.HEPSI)
        return sayac

    @staticmethod
    def gunluk_siparis_sayilari(gun: int = 7) -> list[dict]:
        """Son `gun` gün için günlük sipariş sayısı (eksik günler 0)."""
        from datetime import datetime, timedelta
        rows = fetchall(
            """SELECT date(tarih) AS g, COUNT(*) AS n FROM siparisler
                WHERE date(tarih) >= date('now','localtime',?)
             GROUP BY date(tarih)""",
            (f"-{int(gun) - 1} days",),
        )
        elde = {r["g"]: int(r["n"]) for r in rows}
        bugun = datetime.now().date()
        sonuc: list[dict] = []
        for i in range(gun - 1, -1, -1):
            d = bugun - timedelta(days=i)
            k = d.isoformat()
            sonuc.append({"tarih": k, "etiket": d.strftime("%d.%m"),
                          "adet": elde.get(k, 0)})
        return sonuc

    @staticmethod
    def isciye_atanan_siparisler(isci_id: int,
                                 sadece_bekleyen: bool = True) -> list[dict]:
        sql = (
            """SELECT s.id, s.durum, s.tarih, s.hizlandirma_istendi,
                      s.hazirlanma_baslangic, s.hazirlanma_bitis,
                      ko.kullanici_adi AS olusturan_adi,
                      COALESCE(SUM(sd.adet * u.fiyat), 0) AS tutar,
                      COALESCE(SUM(sd.adet), 0) AS toplam_adet,
                      COUNT(sd.id) AS kalem_sayisi,
                      COALESCE(SUM(CASE WHEN sd.hazirlandi=1 THEN 1 ELSE 0 END),
                               0) AS hazir_sayisi,
                      COALESCE(SUM(CASE WHEN sd.hazirlandi=2 THEN 1 ELSE 0 END),
                               0) AS tamamlanan_sayisi
                 FROM siparisler s
            LEFT JOIN kullanicilar ko      ON ko.id = s.olusturan_id
            LEFT JOIN siparis_detaylari sd ON sd.siparis_id = s.id
            LEFT JOIN urunler u            ON u.id = sd.urun_id
                WHERE s.atanan_isci_id=? """
        )
        params: tuple = (int(isci_id),)
        if sadece_bekleyen:
            # "Gelen siparisler" — bekleyen veya hazirlaniyor olanlar.
            # Tamamlandi / iptal / kismi_tamamlandi isci panelinde
            # gorunmez (admin panelindeki 'Tum Siparisler'de gorunur).
            sql += " AND s.durum IN (?, ?) "
            params = (
                int(isci_id),
                SiparisDurumu.BEKLEMEDE,
                SiparisDurumu.HAZIRLANIYOR,
            )
        sql += " GROUP BY s.id ORDER BY s.id DESC"
        rows = fetchall(sql, params)
        return [dict(r) for r in rows]


__all__ = [
    "SiparisService",
    "StokYetersizHatasi",
    "SiparisZatenIslendi",
    "KalemlerEksikHatasi",
    "SiparisDurumu",
]
