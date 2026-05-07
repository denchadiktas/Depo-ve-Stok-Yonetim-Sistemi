# Depo ve Stok Yönetim Sistemi — Kurumsal Lojistik Uygulaması

Katmanlı mimari, OOP prensipleri ve PyQt6 kullanılarak geliştirilmiş masaüstü depo & stok yönetim uygulaması. Premium koyu tema, koridor renk kodlu hazırlama ekranı, atomik sipariş tamamlama akışı ve mola kota motoru ile birlikte gelir; Yönetici ve İşçi için ayrı paneller içerir.

## Klasör Yapısı

```
depo_yonetim/
├── main.py                         # Genel giriş — DB init → Login → Rol bazlı yönlendirme
├── README.md                       # Bu dosya
│
├── database/                       # Veri katmanı
│   ├── db_connection.py                # SQLite bağlantı fabrikası (foreign_keys ON, Row factory)
│   ├── db_init.py                      # Şema, idempotent migration zinciri, init_database()
│   ├── seed_data.py                    # Admin + 15 işçi + 24 ürün + 9 fake tamamlanmış sipariş
│   └── depo.db                         # SQLite veritabanı (otomatik oluşur)
│
├── backend/                        # İş mantığı + servis + controller
│   ├── models/                         # Domain sınıfları
│   │   ├── kullanici.py                    # Soyut taban (Yonetici / Isci miras alır)
│   │   ├── isci.py                         # İşçi sınıfı (in-memory mola state)
│   │   ├── urun.py                         # Ürün — stok_arttir/azalt, dusuk_stok_mu, lokasyon_key
│   │   ├── depo.py                         # Depo aggregate — toplam_deger, ara, dusuk_stoklar
│   │   ├── sepet.py                        # Sepet — {urun_id → (Urun, adet)}, toplam_hesapla
│   │   ├── siparis.py                      # Sipariş + SiparisDetay — durum yaşam döngüsü
│   │   └── mola_yonetimi.py                # Kota motoru: 2×15dk + 1×30dk, max 3 eşzamanlı
│   │
│   ├── services/                       # İş kuralları (DB ile tek temas noktası burası)
│   │   ├── sifre.py                        # PBKDF2-HMAC-SHA256, 200k iter, timing-safe compare
│   │   ├── kullanici_service.py            # Auth + lazy hash migration + isci_performans
│   │   ├── depo_service.py                 # Ürün CRUD, stok hareketi audit, düşük stok eşiği
│   │   ├── siparis_service.py              # Sepet→sipariş, atomik tamamlama, kısmi tamamlama
│   │   ├── mola_service.py                 # Mola kota & kapasite & lazy expire
│   │   └── db_helpers.py                   # Jenerik fetch/execute yardımcıları
│   │
│   └── controllers/                    # UI'a açılan ince katman
│       ├── auth_controller.py              # giris_yap, sifre_degistir, kullanici_ekle/sil
│       ├── depo_controller.py              # Ürün/sepet/sipariş — admin & işçi uçları
│       └── mola_controller.py              # molaya_cik, moladan_don, kalan_haklar, kapasite
│
└── frontend/                       # Sunum katmanı (PyQt6) — DB'ye doğrudan dokunmaz
    ├── login_ui.py                     # Tek pencere giriş — rol controller'dan döner
    ├── admin_panel_ui.py               # Yönetici paneli — 8 bölümlü kurumsal sidebar
    ├── isci_panel_ui.py                # İşçi paneli — Ürünler / Gelen Siparişler / Mola
    ├── widgets.py                      # StatusBadge, MetricCard, ToastManager, CapacityBar...
    ├── styles.py                       # apply_app_style — global QSS uygulayıcı
    └── style.qss                       # Premium koyu tema — tek QSS, tüm pencereler ortak
```

## Çalıştırma

Gerekli kütüphane(ler):

```bash
pip install PyQt6
```

Uygulamayı başlatın:

```bash
python main.py
```

İlk açılışta `init_database()` şemayı oluşturur, idempotent migration'ları uygular ve örnek veriyi yükler:

- 1 yönetici hesabı (`admin / admin123`)
- 15 işçi (`isci1`..`isci15` — şifre `1234`)
- 24 ürün — 20 tanesi yüksek stoklu (250–500), **4 tanesi kritik eşiğin altında** (12, 15, 18, 20)
- Ürünlere deterministik **koridor / raf / göz** dağıtımı (A–D koridorları)
- 9 fake "tamamlandi" sipariş — son 30 güne yayılı, stoklar düşürülmüş, `stok_hareketleri` audit kayıtları ile tutarlı

## Giriş (main.py)

Uygulama açılışı: `init_database()` → `apply_app_style(app)` (global QSS) → `LoginWindow` → Rol bazlı panel. Yönlendirme `LoginWindow._giris_yap` içinde `kullanici.rol` üzerinden tek noktadan geçer; `AuthController.giris_yap` başarılıysa Yönetici → `AdminPanel`, İşçi → `IsciPanel` açılır.

```
Yonetici : admin           / admin123
Isci     : isci1           / 1234
           isci2           / 1234
           ...             (isci15'e kadar)
```

> Uyarı: Tüm demo şifreleri test amaçlıdır. Üretime geçişten önce `admin123` ve `1234` mutlaka değiştirilmeli (PBKDF2 hash zaten var, sadece güçlü parolaya geçilmeli).

## Mimari Notu

Proje üç katmanlı yapıyı sıkı uygular:

- `database/` → SQLite ile tek temas noktası (raw SQL, jenerik bağlantı fabrikası, idempotent migration'lar)
- `backend/` → İş kuralları, validasyon, sipariş yaşam döngüsü, mola kota motoru, atomik tamamlama. `models/` saf domain, `services/` DB ile konuşan iş mantığı, `controllers/` UI'a açılan ince yüzey
- `frontend/` → Hiçbir UI dosyası doğrudan DB'ye dokunmaz; her şey controller → service zinciri üzerinden gider

Rol ayrımı `Kullanici.ROL_YONETICI` / `ROL_ISCI` üzerinden yapılır; admin uçları (ürün CRUD, sipariş oluşturma, kullanıcı yönetimi) yalnızca Yönetici panelinden çağrılabilir, hazırlama/tamamlama uçları ise İşçi panelinden.

## Özellikler

### Yönetici Paneli (admin_panel_ui.py)

8 bölümlü kurumsal sol sidebar — her bölüm bağımsız sayfa, üstte profil avatarı + bildirim zili.

- **📊 Dashboard:** 4 metrik kartı (toplam ürün / depo değeri / aktif çalışan / mola kapasitesi), son 7 gün sipariş trend grafiği, animasyonlu sayı geçişleri
- **📦 Ürünler:** CRUD tablosu — ad, kategori, stok, fiyat, **koridor/raf/göz** lokasyonu; stok renk kodlaması (kırmızı <25, gri normal, yeşil ≥100); arama + kategori filtresi
- **🛒 Sepet / Sipariş Oluştur:** Sol ürün listesi, sağ canlı sepet (toplam tutar + kalem sayısı), işçi atama dropdown'ı, "Hızlandırılmış" işareti
- **📑 Siparişler:** Tüm siparişler — durum badge'i (`beklemede` / `hazirlaniyor` / `tamamlandi` / `kismi_tamamlandi` / `iptal`), 5 sn'de bir otomatik tazeleme, satıra tıklayınca sağdan açılan detay paneli (kalemler, hazırlanan/kalan, hızlandırma flag'i, iptal butonu)
- **⚠️ Düşük Stok:** Eşik varsayılan 25, ayarlanabilir; sadece eşik altı ürünler listelenir
- **☕ İşçi Molaları:** Kapasite barı (0–3 / 3 — renk kodlu), moladaki işçiler tablosu, kalan süre canlı sayaç, gün içi kullanım özeti
- **🏆 İşçi Performansı:** Son 30 gün — tamamlanan & kısmi sipariş sayısı, işlenen kalem & adet, ortalama tamamlanma süresi (sn), stok hareketi sayısı
- **📈 Raporlar:** Sipariş trendleri, günlük özetler, durum dağılımı
- **👥 Kullanıcılar:** Yönetici/işçi ekle-sil, şifre sıfırla; kendini silme + son admin'i silme yasak

### İşçi Paneli (isci_panel_ui.py)

Sade üç sekmeli arayüz — odak: **hızlı toplama**.

- **📦 Ürünler:** Arama + lokasyon görüntüleme + manuel stok ± (audit'e `stok_hareketleri` 'giris'/'cikis' olarak yazılır)
- **📥 Gelen Siparişler:** Bana atanmış aktif siparişlerin kart görünümü, "Başla" tıklayınca **HazirlamaDialog** açılır:
  - Sipariş detayı + durum badge'i + hızlandırma rozeti
  - **Koridor renk kodlu yönlendirme banner'ı** — A–H her koridor farklı renk, lokasyon sırasına göre adım adım rota
  - Kalem tablosu: # / ✓ Hazır / Lokasyon / Ürün / Adet / Stok / Birim / Tutar
  - İlerleme barı (hazırlanan / toplam)
  - **Tamamla** → atomik geçiş: tüm kalemler hazır mı → stok yeterli mi → stoktan düş + `stok_hareketleri` 'cikis' kaydı + `durum=tamamlandi` (race-safe, `StokYetersizHatasi` yakalanır)
  - **Kısmi Tamamla** → sadece işaretli kalemleri düş, kalanlar `kismi_tamamlandi` durumunda kalır
- **☕ Mola Durumu:** Kapasite barı, **2×15dk** + **1×30dk** kalan hak göstergesi, "15dk Mola" / "30dk Mola" / "Erken Bitir" butonları, aktif moladaysa kalan süre sayacı

### Tema & Bileşenler

- **Tek QSS, global stil:** `frontend/style.qss` — premium koyu mavi/indigo palet, `apply_app_style(app)` ile QApplication'a bir kez uygulanır, tüm pencereler aynı temadan beslenir
- **Drop shadow + LoginCard:** Login kartı 48px blur + 12px offset gölge ile yüzer görünüm
- **Durum badge'leri:** beklemede (sarı `#fbbf24`), hazirlaniyor (mavi `#3b82f6`), tamamlandi (yeşil `#10b981`), iptal (kırmızı `#ef4444`), kismi_tamamlandi (mor)
- **Stok renk kodları:** <25 kırmızı `#dc2626`, ≥100 yeşil `#059669`, ara değerler nötr
- **Koridor renkleri:** A–H için sabit palet — hazırlama ekranında raf rotası bu renklerle vurgulanır (görsel toplama yardımı)
- **Custom widget'lar (`widgets.py`):** `StatusBadge`, `MetricCard` (animasyonlu sayı geçişi), `ToastManager` (info/warning/error), `LoadingOverlay`, `NotificationBell`, `OrderCard`, `Sidebar`, `CapacityBar`, `SidePanel`, `MiniLineChart`, `MiniBarChart`, `SifreDegistirDialog`, `ProfileAvatarButton`
- **Türkçe odaklı UX:** Tüm etiketler Türkçe; veritabanı kolon adları snake_case Türkçe (`olusturan_id`, `atanan_isci_id`, `hazirlanma_baslangic`)

## Backend

- **Şifre güvenliği:** `services/sifre.py` — **PBKDF2-HMAC-SHA256, 200.000 iterasyon**, 16 byte rastgele salt, `hmac.compare_digest` ile timing-safe karşılaştırma. Plain text `sifre` kolonu legacy kayıtlar için bırakılmış; ilk başarılı girişte **lazy hash migration** ile hash + salt'a yazılır
- **Migration zinciri (idempotent):** `_eski_siparis_semasini_migrate_et` (eski tek-ürün şemasını sepet tabanlıya çevirir), `_migrate_siparis_detay_hazirlandi`, `_migrate_siparisler_iptal_ve_hizlandirma` (CHECK constraint için tablo rebuild), `_migrate_siparisler_kismi_ve_sure`, `_migrate_urunler_lokasyon` (koridor/raf/göz/kategori), `_migrate_mola_sure_dakika`, `_migrate_kullanicilar_sifre_hash` — `PRAGMA table_info` ile kolon kontrolü, eski DB'ler veri kaybetmeden yükselir
- **Atomik sipariş tamamlama (`siparis_service.siparisi_tamamla`):** Tek transaction içinde — tüm kalemler `hazirlandi=1` mi → her kalem için güncel stok yeterli mi → stoktan düş + `stok_hareketleri`'ne 'cikis' yaz + `durum=tamamlandi`. Yetersiz stok → `StokYetersizHatasi`, transaction rollback
- **Kısmi tamamlama:** Sadece `hazirlandi=1` kalemler düşer, kalanlar `durum=kismi_tamamlandi`'da kalır; iptal edilirse sadece düşürülmüş kalemler iade edilir (audit ile birlikte)
- **Mola kota motoru (`models/mola_yonetimi.py`):** Günlük hak — **2 × 15dk + 1 × 30dk = 3 mola**; eşzamanlı kapasite **maks. 3 işçi**; süresi geçen molalar her sorgudan önce `expire_olanlari_bitir()` ile lazy kapatılır (background thread yok)
- **Stok hareketi audit:** Her stok değişimi `stok_hareketleri` tablosuna `islem_tipi` ('giris' / 'cikis'), `miktar`, `tarih`, `kullanici_id` ile yazılır — işçi performans raporları bu tablodan beslenir
- **İşçi performans (`kullanici_service.isci_performans`):** Son 30 gün — tamamlanan + kısmi sipariş sayısı, kalem & adet toplamı, ortalama tamamlanma süresi (sn cinsinden, `hazirlanma_baslangic` ↔ `hazirlanma_bitis` farkı), stok hareketi sayısı
- **Admin koruması:** `kullanici_sil` kendini silmeyi ve son yöneticiyi silmeyi reddeder
- **Foreign keys:** `db_connection.get_connection()` her bağlantıda `PRAGMA foreign_keys = ON` çalıştırır; `siparis_detaylari` → `siparisler` `ON DELETE CASCADE`

## Test Hesapları

| Kullanıcı | Rol | Şifre | Not |
|---|---|---|---|
| `admin` | Yonetici | `admin123` | Tüm CRUD + sipariş oluşturma + kullanıcı yönetimi |
| `isci1` | Isci | `1234` | Hazırlama ekranı + mola kullanımı |
| `isci2`..`isci15` | Isci | `1234` | Yük dağıtımı testi için 14 ek işçi |

> Yönetici şifresi: `admin123` — Tüm işçi şifreleri: `1234`

## Üretime Geçiş Kontrol Listesi

- [ ] `admin123` ve `1234` test şifreleri mutlaka değiştirilmeli — özellikle `1234` zayıf, brute force'a karşı kilit/throttle eklenmeli
- [ ] `database/seed_data.py`'deki `seed_kullanicilar`, `seed_urunler`, `seed_lokasyonlar` ve `seed_fake_tamamlanmis_siparisler` çağrıları üretimde devre dışı bırakılmalı (15 işçi + 9 fake sipariş seed'i)
- [ ] Düşük stok eşiği (varsayılan 25) gerçek depo politikasıyla hizalanmalı; ürün başına eşik gerekiyorsa `urunler` tablosuna `min_stok` kolonu eklenmeli
- [ ] `seed_data.KATEGORILER` ve koridor listesi (`A`–`D`) gerçek deponun fiziksel düzenine göre güncellenmeli
- [ ] `depo.db` SQLite dosyası yedekleme planına alınmalı; çok kullanıcılı eşzamanlı yazım gerekiyorsa **PostgreSQL'e geçiş** düşünülmeli (SQLite tek yazar kilidiyle çalışır — yoğun depoda darboğaz olur)
- [ ] Mola kotaları (`2×15dk + 1×30dk`, maks. 3 eşzamanlı) İK politikasıyla hizalanmalı; `mola_yonetimi.py`'deki sabitler config'e taşınmalı
- [ ] `services/sifre.py` PBKDF2 200k iterasyon — modern öneri 600k+; mümkünse `argon2id`'ye geçilmeli (şu an third-party dep eklemek istenmediği için PBKDF2 tercih edilmiş)
- [ ] Sipariş tamamlama race condition için SQLite'ta `BEGIN IMMEDIATE` ile transaction izolasyonu sağlanmalı (PostgreSQL'e geçilirse `SELECT ... FOR UPDATE` kullanılabilir)
- [ ] Frontend 5sn polling yerine event-driven güncelleme (örn. lokal pub/sub veya websocket) düşünülebilir — yoğun siparişte gereksiz DB yükü yaratır
