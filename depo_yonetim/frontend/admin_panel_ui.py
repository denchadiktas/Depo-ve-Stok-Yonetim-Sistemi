"""
frontend/admin_panel_ui.py
--------------------------
Yönetici paneli (premium tema). Sol kenarda animasyonlu sidebar, sağda
QStackedWidget ile sayfalar:
  1) Dashboard        : metric kartlar + 7 gunluk siparis cizgi grafigi
  2) Urunler          : CRUD + fiyat/stok, renkli stok rozetleri, canli arama
  3) Sepet / Siparis  : sol urunler - sag sepet + isciye atama
  4) Siparisler       : durum badge + tiklayinca sag "SidePanel" detay +
                        otomatik tazeleme (5s)
  5) Dusuk Stok       : esigin altindaki urunler
  6) Isci Molalari    : kapasite bar + molali isciler tablosu

Tüm stiller `frontend/style.qss` içinde. Bildirim (toast) ve yukleme
(spinner) bileşenleri `frontend/widgets.py` içinde.
"""

from PyQt6.QtCore import Qt, QTimer, QSettings
from PyQt6.QtGui import QColor, QBrush
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QMessageBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QStackedWidget,
    QStatusBar, QGridLayout, QAbstractItemView, QSplitter,
)

from backend.controllers.depo_controller import (
    DepoController, YetkisizIslem, StokYetersizHatasi, SiparisZatenIslendi,
)
from backend.controllers.auth_controller import AuthController
from backend.controllers.mola_controller import MolaController
from backend.models.sepet import Sepet

from .widgets import (
    MetricCard, StatusBadge, ToastManager, LoadingOverlay, NotificationBell,
    SidePanel, MiniLineChart, MiniBarChart, Sidebar, CapacityBar, NumItem,
    SifreDegistirDialog, ProfileAvatarButton, _repolish,
)


# ----------------------------------------------------------------------
DUSUK_STOK_ESIK = 25
YUKSEK_STOK_ESIK = 100


def _stok_rengi(stok: int) -> QColor | None:
    if stok < DUSUK_STOK_ESIK:
        return QColor("#dc2626")     # kirmizi
    if stok >= YUKSEK_STOK_ESIK:
        return QColor("#059669")     # yesil
    return None


class AdminPanel(QMainWindow):
    def __init__(self, kullanici):
        super().__init__()
        self.kullanici = kullanici
        self.mola_ctrl = MolaController()
        self.sepet = Sepet()

        self.setWindowTitle("Yonetici Paneli - Depo ve Stok Yonetimi")
        self.resize(1360, 840)

        self.toast = ToastManager(self)
        self._login_ref = None
        self._son_siparis_id = 0   # bildirim için izleme
        self._secili_siparis_id: int | None = None

        self._olustur_ui()
        self._tum_verileri_yenile()

        # periyodik: dashboard + siparis + mola
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._periyodik_yenile)
        self._timer.start(5000)

    # ------------------------------------------------------------------
    def _olustur_ui(self):
        kok = QWidget()
        kok.setObjectName("PanelRoot")
        self.setCentralWidget(kok)
        lay = QHBoxLayout(kok)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Sidebar
        self.sidebar = Sidebar("DEPO YONETIMI",
                               f"👤 {self.kullanici.kullanici_adi} • Yonetici")
        self.sidebar.add_nav("📊", "Dashboard",        0, self._nav_goster)
        self.sidebar.add_nav("📦", "Urunler",          1, self._nav_goster)
        self.sidebar.add_nav("🛒", "Sepet / Siparis",  2, self._nav_goster)
        self.sidebar.add_nav("📑", "Siparisler",       3, self._nav_goster)
        self.sidebar.add_nav("⚠️", "Dusuk Stok",       4, self._nav_goster)
        self.sidebar.add_nav("☕", "Isci Molalari",    5, self._nav_goster)
        self.sidebar.add_nav("🏆", "Isci Performansi", 6, self._nav_goster)
        self.sidebar.add_nav("📈", "Raporlar",         7, self._nav_goster)
        self.sidebar.add_nav("👥", "Kullanicilar",     8, self._nav_goster)

        sifre_btn = QPushButton("🔑  Sifre Degistir")
        sifre_btn.setObjectName("GhostBtn")
        sifre_btn.clicked.connect(self._sifre_degistir_ac)
        self.sidebar.add_footer(sifre_btn)

        cikis = QPushButton("↩  Cikis Yap")
        cikis.setObjectName("DangerBtn")
        cikis.clicked.connect(self._cikis_yap)
        self.sidebar.add_footer(cikis)

        lay.addWidget(self.sidebar)

        # İçerik (header + stack)
        icerik = QWidget(); icerik.setObjectName("PanelRoot")
        il = QVBoxLayout(icerik); il.setContentsMargins(0, 0, 0, 0); il.setSpacing(0)

        # Top bar: profile avatar + notification bell
        top = QFrame()
        top.setStyleSheet("background: transparent;")
        tl = QHBoxLayout(top); tl.setContentsMargins(24, 14, 24, 6); tl.setSpacing(10)
        tl.addStretch(1)
        self.avatar = ProfileAvatarButton(self.kullanici, parent=top)
        self.avatar.set_menu_handlers(
            on_sifre=self._sifre_degistir_ac,
            on_cikis=self._cikis_yap,
        )
        tl.addWidget(self.avatar, 0, Qt.AlignmentFlag.AlignRight)
        self.bell = NotificationBell(top)
        tl.addWidget(self.bell, 0, Qt.AlignmentFlag.AlignRight)
        il.addWidget(top)

        # Stack
        self.stack = QStackedWidget()
        il.addWidget(self.stack, 1)

        self._page_dashboard  = self._page_dashboard_olustur()
        self._page_urunler    = self._page_urunler_olustur()
        self._page_sepet      = self._page_sepet_olustur()
        self._page_siparisler = self._page_siparisler_olustur()
        self._page_dusuk      = self._page_dusuk_olustur()
        self._page_mola       = self._page_mola_olustur()
        self._page_performans = self._page_performans_olustur()
        self._page_raporlar   = self._page_raporlar_olustur()
        self._page_kullanici  = self._page_kullanicilar_olustur()
        for p in (self._page_dashboard, self._page_urunler, self._page_sepet,
                  self._page_siparisler, self._page_dusuk, self._page_mola,
                  self._page_performans, self._page_raporlar,
                  self._page_kullanici):
            self.stack.addWidget(p)

        lay.addWidget(icerik, 1)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage(
            f"Giris: {self.kullanici.kullanici_adi} ({self.kullanici.rol})"
        )

        # Yukleme overlay (tum panel)
        self._loader = LoadingOverlay(self)

        self._nav_goster(0)

    def _nav_goster(self, idx: int):
        self.stack.setCurrentIndex(idx)
        self.sidebar.set_active(idx)
        if idx == 0:   self._dashboard_yenile()
        elif idx == 1: self._urunler_tablosu_yenile()
        elif idx == 2: self._sepet_sayfasini_yenile()
        elif idx == 3: self._siparisler_tablosunu_yenile()
        elif idx == 4: self._dusuk_tablo_yenile()
        elif idx == 5: self._mola_tablo_yenile()
        elif idx == 6: self._performans_yenile()
        elif idx == 7: self._raporlar_ozet_yenile()
        elif idx == 8: self._kullanicilar_tablosunu_yenile()

    def _periyodik_yenile(self):
        # Aktif sayfanın verilerini + tüm sayfalardaki bildirimi güncelle
        idx = self.stack.currentIndex()
        self._dashboard_yenile()
        self._mola_tablo_yenile()
        if idx == 3:
            self._siparisler_tablosunu_yenile()
        self._bildirim_kontrol()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if hasattr(self, "_loader"):
            self._loader.setGeometry(self.rect())

    # ==================================================================
    # Sayfa 1: Dashboard
    # ==================================================================
    def _page_dashboard_olustur(self) -> QWidget:
        w = QWidget()
        outer = QVBoxLayout(w); outer.setContentsMargins(24, 10, 24, 24); outer.setSpacing(14)

        ust = QHBoxLayout()
        t = QLabel("Dashboard"); t.setObjectName("PageTitle")
        sub = QLabel("Genel bakis ve gunluk siparis trendi")
        sub.setObjectName("PageSubtitle")
        dv = QVBoxLayout(); dv.setSpacing(2); dv.addWidget(t); dv.addWidget(sub)
        ust.addLayout(dv); ust.addStretch(1)
        b_widgetler = QPushButton("⚙  Kartlari Duzenle")
        b_widgetler.setObjectName("SecondaryBtn")
        b_widgetler.clicked.connect(self._dashboard_kartlari_duzenle)
        ust.addWidget(b_widgetler)
        outer.addLayout(ust)

        # Metric grid — kartlar key'li tutuluyor ki gizle/goster ayari
        # QSettings uzerinden kalici olabilsin.
        grid = QGridLayout(); grid.setSpacing(14)
        self.card_toplam_urun  = MetricCard("Toplam Urun",       "-", "📦", "indigo")
        self.card_toplam_deger = MetricCard("Depo Degeri (TL)",  "-", "💰", "violet")
        self.card_dusuk_stok   = MetricCard("Dusuk Stok",        "-", "⚠️",  "rose")
        self.card_toplam_sip   = MetricCard("Toplam Siparis",    "-", "📑", "blue")
        self.card_bek_sip      = MetricCard("Bekleyen Siparis",  "-", "⏳", "amber")
        self.card_tam_sip      = MetricCard("Tamamlanan",        "-", "✅", "green")
        self.card_aktif        = MetricCard("Aktif Calisan",     "-", "🧑‍💼", "slate")
        self.card_molada       = MetricCard("Moladaki",          "-", "☕",  "amber")

        # (key, label, widget) — duzenle dialogunda ve gizle/goster icin
        self._dash_kartlar = [
            ("toplam_urun",  "Toplam Urun",       self.card_toplam_urun),
            ("toplam_deger", "Depo Degeri",       self.card_toplam_deger),
            ("dusuk_stok",   "Dusuk Stok",        self.card_dusuk_stok),
            ("toplam_sip",   "Toplam Siparis",    self.card_toplam_sip),
            ("bek_sip",      "Bekleyen Siparis",  self.card_bek_sip),
            ("tam_sip",      "Tamamlanan",        self.card_tam_sip),
            ("aktif",        "Aktif Calisan",     self.card_aktif),
            ("molada",       "Moladaki",          self.card_molada),
        ]
        self._dash_grid = grid
        self._dash_kartlari_yerlestir()
        outer.addLayout(grid)

        # Chart kartlari: sol (gunluk line) + sag (durum bar)
        charts_row = QHBoxLayout(); charts_row.setSpacing(14)

        line_card = QFrame(); line_card.setObjectName("Card")
        cl = QVBoxLayout(line_card); cl.setContentsMargins(18, 16, 18, 16); cl.setSpacing(8)
        cbaslik = QHBoxLayout()
        cl_lbl = QLabel("GUNLUK SIPARIS (7 GUN)")
        cl_lbl.setObjectName("CardLabel")
        cbaslik.addWidget(cl_lbl); cbaslik.addStretch(1)
        self.chart_total_lbl = QLabel("-"); self.chart_total_lbl.setObjectName("CardValue")
        cbaslik.addWidget(self.chart_total_lbl)
        cl.addLayout(cbaslik)
        self.chart = MiniLineChart()
        self.chart.setMinimumHeight(200)
        cl.addWidget(self.chart, 1)
        charts_row.addWidget(line_card, 1)

        bar_card = QFrame(); bar_card.setObjectName("Card")
        bl = QVBoxLayout(bar_card); bl.setContentsMargins(18, 16, 18, 16); bl.setSpacing(8)
        b_lbl = QLabel("SIPARIS DAGILIMI (DURUM)")
        b_lbl.setObjectName("CardLabel")
        bl.addWidget(b_lbl)
        self.durum_bar = MiniBarChart()
        self.durum_bar.setMinimumHeight(200)
        bl.addWidget(self.durum_bar, 1)
        charts_row.addWidget(bar_card, 1)

        outer.addLayout(charts_row, 1)
        return w

    # ---- Dashboard kartlari (gizle/goster) ----------------------------
    def _dash_ayar(self) -> QSettings:
        return QSettings("DepoYonetim", "AdminPanel")

    def _dash_gizli_keys(self) -> set[str]:
        s = self._dash_ayar().value("dashboard/gizli", "", type=str)
        return {k for k in (s or "").split(",") if k}

    def _dash_gizli_kaydet(self, gizli: set[str]) -> None:
        self._dash_ayar().setValue("dashboard/gizli", ",".join(sorted(gizli)))

    def _dash_kartlari_yerlestir(self) -> None:
        """Gorunen kartlari 4 sutunlu grid'e yeniden yerlestirir."""
        # Mevcut kartlari grid'den kaldir
        while self._dash_grid.count():
            item = self._dash_grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
        gizli = self._dash_gizli_keys()
        goster = [(k, l, w) for (k, l, w) in self._dash_kartlar
                  if k not in gizli]
        # Gizli kartlari da gizle ki memory'de kalsinlar ama gorunmesinler
        for k, _, w in self._dash_kartlar:
            w.setVisible(k not in gizli)
        for i, (_k, _l, w) in enumerate(goster):
            self._dash_grid.addWidget(w, i // 4, i % 4)

    def _dashboard_kartlari_duzenle(self):
        from PyQt6.QtWidgets import (
            QDialog as _QDlg, QCheckBox as _QCB, QDialogButtonBox as _QDBB,
            QVBoxLayout as _QVB,
        )
        dlg = _QDlg(self)
        dlg.setWindowTitle("Dashboard Kartlari")
        dlg.resize(360, 380)
        v = _QVB(dlg); v.setContentsMargins(18, 18, 18, 18); v.setSpacing(8)
        t = QLabel("Gosterilecek kartlari secin:")
        t.setStyleSheet("color:#e2e8f0; font-weight:700; font-size:13px;")
        v.addWidget(t)

        gizli = self._dash_gizli_keys()
        checkboxes: list[tuple[str, _QCB]] = []
        for key, label, _w in self._dash_kartlar:
            cb = _QCB(label)
            cb.setChecked(key not in gizli)
            v.addWidget(cb)
            checkboxes.append((key, cb))
        v.addStretch(1)
        btns = _QDBB(_QDBB.StandardButton.Ok | _QDBB.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        v.addWidget(btns)

        if dlg.exec():
            yeni_gizli: set[str] = set()
            for key, cb in checkboxes:
                if not cb.isChecked():
                    yeni_gizli.add(key)
            self._dash_gizli_kaydet(yeni_gizli)
            self._dash_kartlari_yerlestir()
            self.toast.info(
                "Dashboard",
                f"{len(self._dash_kartlar) - len(yeni_gizli)} kart gosteriliyor."
            )

    def _dashboard_yenile(self):
        self.card_toplam_urun.set_value(str(DepoController.toplam_urun_sayisi()))
        self.card_toplam_deger.set_value(f"{DepoController.toplam_depo_degeri():,.2f}")
        self.card_dusuk_stok.set_value(str(len(DepoController.dusuk_stoklu_urunler())))
        try:
            ist = DepoController.siparis_istatistikleri(self.kullanici)
            self.card_toplam_sip.set_value(str(ist["toplam"]))
            self.card_bek_sip.set_value(str(ist["beklemede"]))
            self.card_tam_sip.set_value(str(ist["tamamlandi"]))
            gun = DepoController.gunluk_siparis_sayilari(self.kullanici, 7)
            self.chart.set_data([(g["etiket"], g["adet"]) for g in gun])
            self.chart_total_lbl.setText(str(sum(g["adet"] for g in gun)))
            # Durum dagilimi bar chart
            self.durum_bar.set_data([
                ("Beklemede",   ist.get("beklemede", 0),        "#f59e0b"),
                ("Hazirlaniyor", ist.get("hazirlaniyor", 0),    "#3b82f6"),
                ("Tamamlandi",  ist.get("tamamlandi", 0),       "#10b981"),
                ("Kismi",       ist.get("kismi_tamamlandi", 0), "#8b5cf6"),
                ("Iptal",       ist.get("iptal", 0),            "#64748b"),
            ])
        except YetkisizIslem:
            pass
        self.card_aktif.set_value(str(self.mola_ctrl.aktif_calisan_sayisi()))
        self.card_molada.set_value(str(self.mola_ctrl.moladaki_sayi()))

    # ==================================================================
    # Sayfa 2: Urunler
    # ==================================================================
    def _page_urunler_olustur(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w); v.setContentsMargins(24, 10, 24, 24); v.setSpacing(12)

        ust = QHBoxLayout()
        t = QLabel("Urun Yonetimi"); t.setObjectName("PageTitle")
        ust.addWidget(t); ust.addStretch(1)
        self.urun_arama = QLineEdit()
        self.urun_arama.setObjectName("SearchInput")
        self.urun_arama.setPlaceholderText("🔍  Urun ara…")
        self.urun_arama.setFixedWidth(280)
        self.urun_arama.textChanged.connect(self._urunler_tablosu_yenile)
        ust.addWidget(self.urun_arama)
        v.addLayout(ust)

        # Split: tablo + mini quick-preview panel
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.urun_tablo = QTableWidget()
        self.urun_tablo.setColumnCount(6)
        self.urun_tablo.setHorizontalHeaderLabels(
            ["ID", "Ad", "Kategori", "Stok", "Fiyat (TL)", "Lokasyon"]
        )
        self.urun_tablo.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self.urun_tablo.setSortingEnabled(True)
        self.urun_tablo.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.urun_tablo.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.urun_tablo.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.urun_tablo.setAlternatingRowColors(True)
        self.urun_tablo.itemSelectionChanged.connect(self._secili_urunu_forma_getir)
        splitter.addWidget(self.urun_tablo)

        # Quick preview
        qp = QFrame(); qp.setObjectName("Card")
        ql = QVBoxLayout(qp); ql.setContentsMargins(18, 16, 18, 16); ql.setSpacing(6)
        ql_lbl = QLabel("URUN ONIZLEME"); ql_lbl.setObjectName("CardLabel")
        self.qp_ad = QLabel("—");  self.qp_ad.setObjectName("CardValue")
        self.qp_ad.setWordWrap(True)
        self.qp_stok = QLabel("Stok: —");    self.qp_stok.setObjectName("PanelValue")
        self.qp_fiyat = QLabel("Fiyat: —");  self.qp_fiyat.setObjectName("PanelValue")
        self.qp_deger = QLabel("Toplam Deger: —"); self.qp_deger.setObjectName("PanelValue")
        self.qp_lokasyon = QLabel("Lokasyon: —"); self.qp_lokasyon.setObjectName("PanelValue")
        self.qp_durum = StatusBadge("—", "info")
        ql.addWidget(ql_lbl); ql.addWidget(self.qp_ad)
        ql.addSpacing(6); ql.addWidget(self.qp_stok); ql.addWidget(self.qp_fiyat)
        ql.addWidget(self.qp_deger)
        ql.addWidget(self.qp_lokasyon)
        ql.addSpacing(8); ql.addWidget(self.qp_durum, 0, Qt.AlignmentFlag.AlignLeft)
        ql.addStretch(1)
        splitter.addWidget(qp)
        splitter.setSizes([820, 320])
        splitter.setStretchFactor(0, 1)
        v.addWidget(splitter, 1)

        # Form
        form = QFrame(); form.setObjectName("Card")
        fv = QVBoxLayout(form); fv.setContentsMargins(16, 16, 16, 16); fv.setSpacing(10)
        satir1 = QHBoxLayout()
        self.f_ad = QLineEdit(); self.f_ad.setPlaceholderText("Urun adi")
        self.f_stok = QSpinBox(); self.f_stok.setRange(0, 10_000_000)
        self.f_fiyat = QDoubleSpinBox()
        self.f_fiyat.setRange(0, 10_000_000); self.f_fiyat.setDecimals(2)
        self.f_fiyat.setSuffix(" TL")
        satir1.addWidget(QLabel("Ad:")); satir1.addWidget(self.f_ad, 2)
        satir1.addWidget(QLabel("Stok:")); satir1.addWidget(self.f_stok)
        satir1.addWidget(QLabel("Fiyat:")); satir1.addWidget(self.f_fiyat)
        fv.addLayout(satir1)

        # Lokasyon + kategori satiri
        lok_satir = QHBoxLayout()
        self.f_koridor = QLineEdit()
        self.f_koridor.setPlaceholderText("A"); self.f_koridor.setMaximumWidth(80)
        self.f_raf = QLineEdit()
        self.f_raf.setPlaceholderText("R1"); self.f_raf.setMaximumWidth(80)
        self.f_goz = QLineEdit()
        self.f_goz.setPlaceholderText("G1"); self.f_goz.setMaximumWidth(80)
        self.f_kategori = QComboBox()
        self.f_kategori.setEditable(True)  # serbest metin de girilebilir
        try:
            from database.seed_data import KATEGORILER as _KAT
        except Exception:
            _KAT = []
        self.f_kategori.addItem("")
        for k in _KAT:
            self.f_kategori.addItem(k)
        self.f_kategori.setMaximumWidth(180)

        lok_satir.addWidget(QLabel("Kategori:")); lok_satir.addWidget(self.f_kategori)
        lok_satir.addSpacing(12)
        lok_satir.addWidget(QLabel("Koridor:")); lok_satir.addWidget(self.f_koridor)
        lok_satir.addSpacing(6)
        lok_satir.addWidget(QLabel("Raf:")); lok_satir.addWidget(self.f_raf)
        lok_satir.addSpacing(6)
        lok_satir.addWidget(QLabel("Goz:")); lok_satir.addWidget(self.f_goz)
        lok_satir.addStretch(1)
        fv.addLayout(lok_satir)

        satir2 = QHBoxLayout()
        b_ekle   = QPushButton("Ekle");        b_ekle.setObjectName("ActionBtn")
        b_guncel = QPushButton("Guncelle");    b_guncel.setObjectName("SecondaryBtn")
        b_fiyat  = QPushButton("Fiyat");       b_fiyat.setObjectName("WarnBtn")
        b_stokp  = QPushButton("Stok +");      b_stokp.setObjectName("SuccessBtn")
        b_stokm  = QPushButton("Stok -");      b_stokm.setObjectName("WarnBtn")
        b_sil    = QPushButton("Sil");         b_sil.setObjectName("DangerBtn")
        b_ekle.clicked.connect(self._urun_ekle)
        b_guncel.clicked.connect(self._urun_guncelle)
        b_fiyat.clicked.connect(self._fiyat_guncelle)
        b_stokp.clicked.connect(lambda: self._stok_degistir(+1))
        b_stokm.clicked.connect(lambda: self._stok_degistir(-1))
        b_sil.clicked.connect(self._urun_sil)
        for b in (b_ekle, b_guncel, b_fiyat, b_stokp, b_stokm, b_sil):
            satir2.addWidget(b)
        satir2.addStretch(1)
        fv.addLayout(satir2)

        v.addWidget(form)
        return w

    def _secili_urun_id(self) -> int | None:
        r = self.urun_tablo.currentRow()
        if r < 0:
            return None
        item = self.urun_tablo.item(r, 0)
        return int(item.text()) if item else None

    def _secili_urunu_forma_getir(self):
        r = self.urun_tablo.currentRow()
        if r < 0:
            return
        uid = self._secili_urun_id()
        if uid is None:
            return
        urun = DepoController.urunleri_getir()
        urun = next((u for u in urun if u.urun_id == uid), None)
        if urun is None:
            return
        self.f_ad.setText(urun.ad)
        self.f_stok.setValue(int(urun.stok))
        self.f_fiyat.setValue(float(urun.fiyat))
        self.f_koridor.setText(urun.koridor)
        self.f_raf.setText(urun.raf)
        self.f_goz.setText(urun.goz)
        idx = self.f_kategori.findText(urun.kategori)
        if idx >= 0:
            self.f_kategori.setCurrentIndex(idx)
        else:
            self.f_kategori.setEditText(urun.kategori)
        # Quick preview
        self.qp_ad.setText(urun.ad)
        self.qp_stok.setText(f"Stok: {urun.stok}")
        self.qp_fiyat.setText(f"Fiyat: {urun.fiyat:,.2f} TL")
        self.qp_deger.setText(
            f"Toplam Deger: {urun.stok * urun.fiyat:,.2f} TL"
        )
        lok = urun.lokasyon() or "—"
        self.qp_lokasyon.setText(f"Lokasyon: {lok}")
        if urun.stok < DUSUK_STOK_ESIK:
            self.qp_durum.setText("DUSUK STOK"); self.qp_durum.set_level("warn")
        elif urun.stok >= YUKSEK_STOK_ESIK:
            self.qp_durum.setText("STOK YUKSEK"); self.qp_durum.set_level("tamamlandi")
        else:
            self.qp_durum.setText("NORMAL"); self.qp_durum.set_level("info")

    def _urunler_tablosu_yenile(self):
        self.urun_tablo.setSortingEnabled(False)
        metin = self.urun_arama.text().strip() if hasattr(self, "urun_arama") else ""
        urunler = DepoController.ara(metin) if metin else DepoController.urunleri_getir()
        self.urun_tablo.setRowCount(len(urunler))
        for i, u in enumerate(urunler):
            self.urun_tablo.setItem(i, 0, NumItem(u.urun_id, str(u.urun_id)))
            self.urun_tablo.setItem(i, 1, QTableWidgetItem(u.ad))
            self.urun_tablo.setItem(
                i, 2, QTableWidgetItem(u.kategori or "—")
            )
            stok_it = NumItem(u.stok, str(u.stok))
            renk = _stok_rengi(u.stok)
            if renk is not None:
                stok_it.setForeground(QBrush(renk))
                stok_it.setToolTip(
                    "Dusuk stok" if u.stok < DUSUK_STOK_ESIK else "Stok yuksek"
                )
            self.urun_tablo.setItem(i, 3, stok_it)
            self.urun_tablo.setItem(i, 4, NumItem(u.fiyat, f"{u.fiyat:.2f}"))
            lok_it = QTableWidgetItem(u.lokasyon() or "—")
            lok_it.setToolTip(f"Koridor/Raf/Goz = {u.lokasyon() or '—'}")
            self.urun_tablo.setItem(i, 5, lok_it)
        self.urun_tablo.setSortingEnabled(True)

    def _urun_ekle(self):
        ad = self.f_ad.text().strip()
        if not ad:
            self.toast.warn("Eksik Bilgi", "Urun adi bos olamaz."); return
        try:
            DepoController.urun_ekle(
                self.kullanici, ad,
                self.f_stok.value(), self.f_fiyat.value(),
                self.f_koridor.text().strip(),
                self.f_raf.text().strip(),
                self.f_goz.text().strip(),
                self.f_kategori.currentText().strip(),
            )
        except YetkisizIslem as e:
            self.toast.error("Yetki", str(e)); return
        except Exception as e:
            self.toast.error("Hata", str(e)); return
        self.toast.success("Eklendi", f"'{ad}' urunu kayit edildi.")
        self._urunler_tablosu_yenile()
        self._dashboard_yenile()

    def _urun_guncelle(self):
        uid = self._secili_urun_id()
        if uid is None:
            self.toast.info("Secim", "Lutfen bir urun secin."); return
        try:
            DepoController.urun_guncelle(
                self.kullanici, uid,
                self.f_ad.text().strip(),
                self.f_stok.value(),
                self.f_fiyat.value(),
                self.f_koridor.text().strip(),
                self.f_raf.text().strip(),
                self.f_goz.text().strip(),
                self.f_kategori.currentText().strip(),
            )
        except Exception as e:
            self.toast.error("Hata", str(e)); return
        self.toast.success("Guncellendi", "Urun bilgisi guncellendi.")
        self._urunler_tablosu_yenile(); self._dashboard_yenile()

    def _fiyat_guncelle(self):
        uid = self._secili_urun_id()
        if uid is None:
            self.toast.info("Secim", "Lutfen bir urun secin."); return
        try:
            DepoController.fiyat_guncelle(self.kullanici, uid, self.f_fiyat.value())
        except Exception as e:
            self.toast.error("Hata", str(e)); return
        self.toast.success("Fiyat Degisti", f"Yeni fiyat: {self.f_fiyat.value():.2f} TL")
        self._urunler_tablosu_yenile(); self._dashboard_yenile()

    def _stok_degistir(self, yon: int):
        uid = self._secili_urun_id()
        if uid is None:
            self.toast.info("Secim", "Lutfen bir urun secin."); return
        miktar = self.f_stok.value()
        if miktar <= 0:
            self.toast.warn("Miktar", "Stok miktari pozitif olmalidir."); return
        try:
            if yon > 0:
                DepoController.stok_arttir(self.kullanici, uid, miktar)
                self.toast.success("Stok +", f"{miktar} adet eklendi.")
            else:
                DepoController.stok_azalt(self.kullanici, uid, miktar)
                self.toast.info("Stok -", f"{miktar} adet dusuldu.")
        except StokYetersizHatasi as e:
            self.toast.error("Stok Yetersiz", str(e)); return
        except Exception as e:
            self.toast.error("Hata", str(e)); return
        self._urunler_tablosu_yenile(); self._dashboard_yenile()

    def _urun_sil(self):
        uid = self._secili_urun_id()
        if uid is None:
            self.toast.info("Secim", "Lutfen bir urun secin."); return
        c = QMessageBox.question(self, "Onay", "Urun silinsin mi?")
        if c != QMessageBox.StandardButton.Yes:
            return
        try:
            DepoController.urun_sil(self.kullanici, uid)
        except Exception as e:
            self.toast.error("Hata", str(e)); return
        self.toast.success("Silindi", "Urun kaldirildi.")
        self._urunler_tablosu_yenile(); self._dashboard_yenile()

    # ==================================================================
    # Sayfa 3: Sepet / Siparis
    # ==================================================================
    def _page_sepet_olustur(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w); v.setContentsMargins(24, 10, 24, 24); v.setSpacing(12)

        t = QLabel("Sepet ve Siparis Olustur"); t.setObjectName("PageTitle")
        v.addWidget(t)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # SOL: urun listesi
        sol = QFrame(); sol.setObjectName("Card")
        sl = QVBoxLayout(sol); sl.setContentsMargins(14, 14, 14, 14); sl.setSpacing(8)
        sol_ust = QHBoxLayout()
        sol_ust.addWidget(QLabel("<b style='color:#0f172a;'>URUNLER</b>"))
        self.sepet_arama = QLineEdit()
        self.sepet_arama.setObjectName("SearchInput")
        self.sepet_arama.setPlaceholderText("🔍  Urun ara…")
        self.sepet_arama.textChanged.connect(self._sepet_urun_listesini_yenile)
        sol_ust.addWidget(self.sepet_arama, 1)
        sl.addLayout(sol_ust)

        self.sepet_urun_tablo = QTableWidget()
        self.sepet_urun_tablo.setColumnCount(5)
        self.sepet_urun_tablo.setHorizontalHeaderLabels(
            ["ID", "Ad", "Stok", "Fiyat (TL)", "Lokasyon"])
        self.sepet_urun_tablo.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self.sepet_urun_tablo.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.sepet_urun_tablo.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.sepet_urun_tablo.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.sepet_urun_tablo.setSortingEnabled(True)
        self.sepet_urun_tablo.setAlternatingRowColors(True)
        sl.addWidget(self.sepet_urun_tablo, 1)

        satir = QHBoxLayout()
        self.sepet_adet = QSpinBox(); self.sepet_adet.setRange(1, 10_000)
        b_ekle = QPushButton("➕  Sepete Ekle"); b_ekle.setObjectName("ActionBtn")
        b_ekle.clicked.connect(self._sepete_ekle)
        satir.addWidget(QLabel("Adet:")); satir.addWidget(self.sepet_adet)
        satir.addStretch(1); satir.addWidget(b_ekle)
        sl.addLayout(satir)
        splitter.addWidget(sol)

        # SAĞ: sepet
        sag = QFrame(); sag.setObjectName("Card")
        sg = QVBoxLayout(sag); sg.setContentsMargins(14, 14, 14, 14); sg.setSpacing(8)
        sg_ust = QHBoxLayout()
        sg_ust.addWidget(QLabel("<b style='color:#0f172a;'>SEPET</b>"))
        sg_ust.addStretch(1)
        b_temizle = QPushButton("Temizle"); b_temizle.setObjectName("DangerBtn")
        b_temizle.clicked.connect(self._sepeti_temizle)
        sg_ust.addWidget(b_temizle)
        sg.addLayout(sg_ust)

        self.sepet_tablo = QTableWidget()
        self.sepet_tablo.setColumnCount(5)
        self.sepet_tablo.setHorizontalHeaderLabels(
            ["Urun", "Adet", "B.Fiyat", "Tutar", ""])
        self.sepet_tablo.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self.sepet_tablo.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        sg.addWidget(self.sepet_tablo, 1)

        self.sepet_toplam_lbl = QLabel("Toplam: 0.00 TL")
        self.sepet_toplam_lbl.setStyleSheet(
            "color:#0f172a; font-size:15px; font-weight:800;")
        sg.addWidget(self.sepet_toplam_lbl)

        atama = QHBoxLayout()
        atama.addWidget(QLabel("Atanacak Isci:"))
        self.isci_combo = QComboBox(); self.isci_combo.setMinimumWidth(180)
        atama.addWidget(self.isci_combo, 1)
        sg.addLayout(atama)

        b_siparis = QPushButton("✔  Siparis Olustur"); b_siparis.setObjectName("SuccessBtn")
        b_siparis.clicked.connect(self._siparis_olustur)
        sg.addWidget(b_siparis)

        splitter.addWidget(sag)
        splitter.setSizes([680, 520])
        v.addWidget(splitter, 1)
        return w

    def _sepet_urun_listesini_yenile(self):
        metin = self.sepet_arama.text().strip() if hasattr(self, "sepet_arama") else ""
        urunler = DepoController.ara(metin) if metin else DepoController.urunleri_getir()
        self._sepet_urun_cache = {u.urun_id: u for u in urunler}
        t = self.sepet_urun_tablo
        t.setSortingEnabled(False)
        t.setRowCount(len(urunler))
        for i, u in enumerate(urunler):
            t.setItem(i, 0, NumItem(u.urun_id, str(u.urun_id)))
            t.setItem(i, 1, QTableWidgetItem(u.ad))
            stok_it = NumItem(u.stok, str(u.stok))
            renk = _stok_rengi(u.stok)
            if renk is not None:
                stok_it.setForeground(QBrush(renk))
            t.setItem(i, 2, stok_it)
            t.setItem(i, 3, NumItem(u.fiyat, f"{u.fiyat:.2f}"))
            t.setItem(i, 4, QTableWidgetItem(u.lokasyon() or "—"))
        t.setSortingEnabled(True)

    def _secili_sepet_urun_id(self) -> int | None:
        r = self.sepet_urun_tablo.currentRow()
        if r < 0:
            return None
        item = self.sepet_urun_tablo.item(r, 0)
        return int(item.text()) if item else None

    def _sepete_ekle(self):
        uid = self._secili_sepet_urun_id()
        if uid is None:
            self.toast.info("Secim", "Lutfen bir urun secin."); return
        urun = getattr(self, "_sepet_urun_cache", {}).get(uid)
        if urun is None:
            self.toast.error("Hata", "Urun bulunamadi."); return
        try:
            self.sepet.urun_ekle(urun, self.sepet_adet.value())
        except ValueError as e:
            self.toast.error("Hata", str(e)); return
        self.toast.info("Sepet", f"'{urun.ad}' x {self.sepet_adet.value()} eklendi.")
        self._sepet_tablosunu_yenile()

    def _sepet_tablosunu_yenile(self):
        kalemler = self.sepet.kalemler()
        t = self.sepet_tablo
        t.setRowCount(len(kalemler))
        for i, (u, adet) in enumerate(kalemler):
            t.setItem(i, 0, QTableWidgetItem(u.ad))
            t.setItem(i, 1, NumItem(adet, str(adet)))
            t.setItem(i, 2, NumItem(u.fiyat, f"{u.fiyat:.2f}"))
            t.setItem(i, 3, NumItem(u.fiyat * adet, f"{u.fiyat * adet:.2f}"))
            b = QPushButton("Kaldir"); b.setObjectName("DangerBtn")
            b.clicked.connect(lambda _=False, uid=u.urun_id: self._sepetten_kaldir(uid))
            t.setCellWidget(i, 4, b)
        self.sepet_toplam_lbl.setText(
            f"Toplam: {self.sepet.toplam_hesapla():,.2f} TL  "
            f"({self.sepet.kalem_sayisi()} kalem, {self.sepet.toplam_adet()} adet)"
        )

    def _sepetten_kaldir(self, urun_id: int):
        self.sepet.urun_cikar(urun_id)
        self._sepet_tablosunu_yenile()

    def _sepeti_temizle(self):
        if self.sepet.bos_mu():
            return
        c = QMessageBox.question(self, "Onay", "Sepet temizlensin mi?")
        if c != QMessageBox.StandardButton.Yes:
            return
        self.sepet.sepeti_temizle()
        self._sepet_tablosunu_yenile()
        self.toast.info("Sepet", "Sepet temizlendi.")

    def _isci_combo_yenile(self):
        self.isci_combo.clear()
        self.isci_combo.addItem("— (atama yapma)", None)
        try:
            for i in DepoController.iscileri_getir(self.kullanici):
                self.isci_combo.addItem(i.kullanici_adi, i.kullanici_id)
        except YetkisizIslem as e:
            self.toast.error("Yetki", str(e))

    def _sepet_sayfasini_yenile(self):
        self._sepet_urun_listesini_yenile()
        self._sepet_tablosunu_yenile()
        self._isci_combo_yenile()

    def _siparis_olustur(self):
        if self.sepet.bos_mu():
            self.toast.warn("Sepet Bos", "Once sepete urun ekleyin."); return
        atanan = self.isci_combo.currentData()
        self._loader.start()
        try:
            s = DepoController.sepetten_siparis_olustur(
                self.kullanici, self.sepet, atanan)
        except YetkisizIslem as e:
            self._loader.stop(); self.toast.error("Yetki", str(e)); return
        except Exception as e:
            self._loader.stop(); self.toast.error("Hata", str(e)); return
        self._loader.stop()
        self.toast.success(
            "Siparis Olusturuldu",
            f"#{s.siparis_id} — {len(s.detaylar)} kalem, {s.toplam_tutar():,.2f} TL"
        )
        self.sepet.sepeti_temizle()
        self._sepet_tablosunu_yenile()
        self._siparisler_tablosunu_yenile()
        self._dashboard_yenile()

    # ==================================================================
    # Sayfa 4: Siparisler + SidePanel
    # ==================================================================
    def _page_siparisler_olustur(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w); v.setContentsMargins(24, 10, 24, 24); v.setSpacing(12)

        ust = QHBoxLayout()
        t = QLabel("Tum Siparisler"); t.setObjectName("PageTitle")
        sub = QLabel("Otomatik tazeleme: 5 sn  •  Arkaplanda rastgele siparis akisi aktif")
        sub.setObjectName("PageSubtitle")
        dv = QVBoxLayout(); dv.setSpacing(2); dv.addWidget(t); dv.addWidget(sub)
        ust.addLayout(dv); ust.addStretch(1)
        v.addLayout(ust)

        # Arkaplanda surekli calisan rastgele siparis uretici: her 30 sn
        # bir yeni siparis dusuruyor, bu sayede isciler bos kalmiyor.
        self._auto_siparis_timer = QTimer(self)
        self._auto_siparis_timer.setInterval(30000)
        self._auto_siparis_timer.timeout.connect(self._auto_siparis_tick)
        self._auto_siparis_timer.start()

        row = QHBoxLayout(); row.setSpacing(12)

        self.siparis_tablo = QTableWidget()
        self.siparis_tablo.setColumnCount(7)
        self.siparis_tablo.setHorizontalHeaderLabels(
            ["ID", "Olusturan", "Atanan", "Adet", "Tutar", "Durum", "Tarih"])
        self.siparis_tablo.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self.siparis_tablo.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.siparis_tablo.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.siparis_tablo.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.siparis_tablo.setSortingEnabled(True)
        self.siparis_tablo.setAlternatingRowColors(True)
        self.siparis_tablo.itemSelectionChanged.connect(self._siparis_secildi)
        row.addWidget(self.siparis_tablo, 1)

        self.side = SidePanel()
        row.addWidget(self.side, 0)
        v.addLayout(row, 1)
        return w

    def _siparisler_tablosunu_yenile(self):
        try:
            rows = DepoController.tum_siparisler(self.kullanici)
        except YetkisizIslem:
            return

        # bildirim için en yüksek ID'yi kaydet
        if rows:
            max_id = max(int(r["id"]) for r in rows)
            if self._son_siparis_id == 0:
                self._son_siparis_id = max_id

        t = self.siparis_tablo
        t.setSortingEnabled(False)
        t.setRowCount(len(rows))
        for i, r in enumerate(rows):
            t.setItem(i, 0, NumItem(r["id"], str(r["id"])))
            t.setItem(i, 1, QTableWidgetItem(str(r.get("olusturan_adi") or "-")))
            t.setItem(i, 2, QTableWidgetItem(str(r.get("atanan_isci_adi") or "-")))
            t.setItem(i, 3, NumItem(r["toplam_adet"], str(r["toplam_adet"])))
            t.setItem(i, 4, NumItem(r["tutar"], f"{float(r['tutar']):,.2f}"))
            # durum badge + acil rozet (varsa) — cellWidget ile
            acil = bool(int(r.get("hizlandirma_istendi") or 0))
            badge = StatusBadge(); badge.apply_durum(str(r["durum"]))
            wrap = QWidget(); wl = QHBoxLayout(wrap)
            wl.setContentsMargins(8, 4, 8, 4); wl.setSpacing(6)
            wl.addWidget(badge)
            if acil and str(r["durum"]) == "beklemede":
                acil_b = StatusBadge("⚡", "acil")
                acil_b.setToolTip("Hizlandirma istendi")
                wl.addWidget(acil_b)
            wl.addStretch(1)
            t.setCellWidget(i, 5, wrap)
            # sıralama için gizli durum item
            dur_item = QTableWidgetItem(r["durum"])
            dur_item.setFlags(dur_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            t.setItem(i, 5, dur_item)
            t.setItem(i, 6, QTableWidgetItem(str(r["tarih"])))
        t.setSortingEnabled(True)

    # ---- Arkaplan rastgele siparis akisi -----------------------------
    def _auto_siparis_tick(self):
        """Her 30 sn'de bir sessizce bir rastgele siparis dusurur."""
        try:
            ids = DepoController.rastgele_siparis_uret(self.kullanici, 1)
        except Exception:
            return
        if ids:
            self.bell.push(f"🎲 Yeni siparis #{ids[0]}")
            self._siparisler_tablosunu_yenile()

    def _siparis_secildi(self):
        r = self.siparis_tablo.currentRow()
        if r < 0:
            return
        it = self.siparis_tablo.item(r, 0)
        if not it:
            return
        sid = int(it.text())
        self._secili_siparis_id = sid
        self._side_panel_doldur(sid)

    def _side_panel_doldur(self, siparis_id: int):
        d = DepoController.siparis_detayi(siparis_id)
        if not d:
            self.toast.error("Hata", "Siparis bulunamadi."); return
        self.side.set_title(f"Siparis #{siparis_id}")
        self.side.clear_body()

        s = d["siparis"]
        acil = bool(int(s.get("hizlandirma_istendi") or 0))
        badge = StatusBadge(); badge.apply_durum(str(s["durum"]))

        ust = QWidget(); ul = QHBoxLayout(ust)
        ul.setContentsMargins(0, 0, 0, 0); ul.setSpacing(6)
        ul.addWidget(badge)
        if acil and str(s["durum"]) == "beklemede":
            acil_b = StatusBadge("⚡  HIZLANDIR", "acil")
            ul.addWidget(acil_b)
        ul.addStretch(1)
        self.side.add_body(ust)

        def _kv(k, v):
            row = QWidget(); rl = QHBoxLayout(row); rl.setContentsMargins(0, 2, 0, 2)
            key = QLabel(k.upper()); key.setObjectName("PanelKey")
            val = QLabel(str(v)); val.setObjectName("PanelValue")
            key.setFixedWidth(110)
            rl.addWidget(key); rl.addWidget(val, 1)
            return row

        self.side.add_body(_kv("Olusturan", s.get("olusturan_adi") or "-"))
        self.side.add_body(_kv("Atanan",    s.get("atanan_isci_adi") or "-"))
        self.side.add_body(_kv("Tarih",     s.get("tarih") or "-"))

        # Hazirlama suresi (baslangic/bitis varsa)
        basl = s.get("hazirlanma_baslangic")
        bit = s.get("hazirlanma_bitis")
        if basl:
            self.side.add_body(_kv("Haz. Baslangic", basl))
        if bit:
            self.side.add_body(_kv("Haz. Bitis", bit))
        sn = s.get("sure_saniye")
        if sn is not None:
            dk, sn2 = divmod(int(sn), 60)
            self.side.add_body(_kv("Sure", f"{dk} dk {sn2} sn"))

        # Kalemler tablosu — hazirlandi sutunu ile
        dets = d["detaylar"]
        detay_tablo = QTableWidget(len(dets), 4)
        detay_tablo.setHorizontalHeaderLabels(
            ["Hazir", "Urun", "Adet", "Tutar"]
        )
        hh = detay_tablo.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        detay_tablo.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        detay_tablo.setMaximumHeight(280)
        for i, dt in enumerate(dets):
            h = int(dt.get("hazirlandi") or 0)
            ikon = QTableWidgetItem("✓" if h else "○")
            ikon.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if h:
                ikon.setForeground(QBrush(QColor("#059669")))
                ikon.setToolTip("Hazirlandi")
            else:
                ikon.setForeground(QBrush(QColor("#94a3b8")))
            detay_tablo.setItem(i, 0, ikon)
            detay_tablo.setItem(i, 1, QTableWidgetItem(dt["urun_adi"]))
            detay_tablo.setItem(i, 2, NumItem(dt["adet"], str(dt["adet"])))
            detay_tablo.setItem(
                i, 3, NumItem(dt["tutar"], f"{float(dt['tutar']):,.2f}")
            )
        self.side.add_body(detay_tablo)

        # Progress bar — kalem hazırlık oranına göre
        kalem_sayisi = int(d.get("kalem_sayisi") or 0)
        hazir_sayisi = int(d.get("hazir_sayisi") or 0)
        pb_baslik = QLabel(
            f"ILERLEME — {hazir_sayisi}/{kalem_sayisi} kalem hazirlandi"
        )
        pb_baslik.setObjectName("PanelKey")
        self.side.add_body(pb_baslik)
        from PyQt6.QtWidgets import QProgressBar
        pb = QProgressBar()
        if s["durum"] == "tamamlandi":
            pb.setRange(0, 100); pb.setValue(100)
            pb.setProperty("level", "low")
        else:
            pb.setRange(0, max(kalem_sayisi, 1))
            pb.setValue(hazir_sayisi)
            oran = (hazir_sayisi / kalem_sayisi) if kalem_sayisi else 0.0
            if kalem_sayisi and hazir_sayisi == kalem_sayisi:
                pb.setProperty("level", "low")
            elif oran >= 0.5:
                pb.setProperty("level", "mid")
            else:
                pb.setProperty("level", "high")
        pb.setTextVisible(True)
        _repolish(pb)
        self.side.add_body(pb)

        # toplam
        top = QLabel(f"TOPLAM: {d['toplam_tutar']:,.2f} TL")
        top.setStyleSheet("color:#0f172a; font-size:15px; font-weight:800; padding-top:6px;")
        self.side.add_body(top)

        # --- Yonetici aksiyonlari (yalnizca beklemede) -----------------
        if str(s["durum"]) == "beklemede":
            self._aksiyon_kartini_ekle(siparis_id, s, acil)

        self.side.ac(360)

    # ------------------------------------------------------------------
    def _aksiyon_kartini_ekle(self, siparis_id: int, s: dict,
                              acil: bool) -> None:
        """Side panel'e yonetici aksiyonlarini (hizlandir, isci degistir,
        iptal) ekler. Yalnizca beklemede siparisler icin anlamli."""
        kart = QFrame(); kart.setObjectName("Card")
        kl = QVBoxLayout(kart); kl.setContentsMargins(12, 12, 12, 12); kl.setSpacing(8)
        b = QLabel("YONETICI AKSIYONLARI"); b.setObjectName("PanelKey")
        kl.addWidget(b)

        # Isci degistir satiri
        atama_row = QHBoxLayout(); atama_row.setSpacing(6)
        combo = QComboBox()
        combo.setMinimumWidth(150)
        combo.addItem("— (atama yok)", None)
        try:
            iscis = DepoController.iscileri_getir(self.kullanici)
        except YetkisizIslem:
            iscis = []
        for ic in iscis:
            combo.addItem(ic.kullanici_adi, ic.kullanici_id)
        # Mevcut atamayi sec
        mevcut = s.get("atanan_isci_id")
        if mevcut is not None:
            for idx in range(combo.count()):
                if combo.itemData(idx) == int(mevcut):
                    combo.setCurrentIndex(idx); break
        atama_row.addWidget(combo, 1)
        b_ata = QPushButton("Uygula")
        b_ata.setObjectName("SecondaryBtn")
        b_ata.clicked.connect(
            lambda _=False, sid=siparis_id, c=combo:
                self._atamayi_degistir(sid, c.currentData())
        )
        atama_row.addWidget(b_ata)
        kl.addLayout(atama_row)

        # Hizlandir + Iptal butonlari
        btns = QHBoxLayout(); btns.setSpacing(6)
        b_hiz = QPushButton("⚡  Hizlandir")
        b_hiz.setObjectName("WarnBtn")
        if acil:
            b_hiz.setEnabled(False)
            b_hiz.setText("⚡  Hizlandirma Istendi")
        b_hiz.clicked.connect(
            lambda _=False, sid=siparis_id: self._hizlandir(sid)
        )
        b_iptal = QPushButton("✕  Iptal Et")
        b_iptal.setObjectName("DangerBtn")
        b_iptal.clicked.connect(
            lambda _=False, sid=siparis_id: self._siparisi_iptal_et(sid)
        )
        btns.addWidget(b_hiz); btns.addWidget(b_iptal)
        kl.addLayout(btns)

        self.side.add_body(kart)

    # ------------------------------------------------------------------
    def _atamayi_degistir(self, siparis_id: int, yeni_isci_id):
        try:
            DepoController.siparise_isci_ata(
                self.kullanici, siparis_id, yeni_isci_id
            )
        except SiparisZatenIslendi as e:
            self.toast.warn("Islem yapilamadi", str(e)); return
        except Exception as e:
            self.toast.error("Hata", str(e)); return
        self.toast.success("Atama Guncellendi",
                           "Siparis atamasi degistirildi.")
        self._siparisler_tablosunu_yenile()
        self._side_panel_doldur(siparis_id)

    def _hizlandir(self, siparis_id: int):
        try:
            DepoController.hizlandirma_iste(self.kullanici, siparis_id)
        except SiparisZatenIslendi as e:
            self.toast.warn("Islem yapilamadi", str(e)); return
        except Exception as e:
            self.toast.error("Hata", str(e)); return
        self.toast.success("Hizlandirma Istendi",
                           "Isciye bildirim gonderildi.")
        self._siparisler_tablosunu_yenile()
        self._side_panel_doldur(siparis_id)

    def _siparisi_iptal_et(self, siparis_id: int):
        c = QMessageBox.question(
            self, "Siparisi Iptal Et",
            f"#{siparis_id} numarali siparis iptal edilsin mi?\n"
            "(Henuz hazirlanmamis bu siparisin durumu 'iptal' olacak.)"
        )
        if c != QMessageBox.StandardButton.Yes:
            return
        try:
            DepoController.siparisi_iptal_et(self.kullanici, siparis_id)
        except SiparisZatenIslendi as e:
            self.toast.warn("Islem yapilamadi", str(e)); return
        except Exception as e:
            self.toast.error("Hata", str(e)); return
        self.toast.info("Iptal Edildi", f"#{siparis_id} iptal edildi.")
        self._siparisler_tablosunu_yenile()
        self._side_panel_doldur(siparis_id)
        self._dashboard_yenile()

    # ==================================================================
    # Sayfa 5: Dusuk Stok
    # ==================================================================
    def _page_dusuk_olustur(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w); v.setContentsMargins(24, 10, 24, 24); v.setSpacing(12)
        t = QLabel("Dusuk Stoklu Urunler"); t.setObjectName("PageTitle")
        sub = QLabel(f"Esik degeri: {DUSUK_STOK_ESIK} (kritik)")
        sub.setObjectName("PageSubtitle")
        v.addWidget(t); v.addWidget(sub)

        self.dusuk_tablo = QTableWidget()
        self.dusuk_tablo.setColumnCount(4)
        self.dusuk_tablo.setHorizontalHeaderLabels(["ID", "Ad", "Stok", "Fiyat (TL)"])
        self.dusuk_tablo.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self.dusuk_tablo.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.dusuk_tablo.setSortingEnabled(True)
        self.dusuk_tablo.setAlternatingRowColors(True)
        v.addWidget(self.dusuk_tablo, 1)
        return w

    def _dusuk_tablo_yenile(self):
        urunler = DepoController.dusuk_stoklu_urunler()
        t = self.dusuk_tablo
        t.setSortingEnabled(False)
        t.setRowCount(len(urunler))
        kirmizi = QBrush(QColor("#dc2626"))
        for i, u in enumerate(urunler):
            it0 = NumItem(u.urun_id, str(u.urun_id))
            it1 = QTableWidgetItem(u.ad)
            it2 = NumItem(u.stok, str(u.stok))
            it3 = NumItem(u.fiyat, f"{u.fiyat:.2f}")
            for it in (it0, it1, it2, it3):
                it.setForeground(kirmizi)
            t.setItem(i, 0, it0); t.setItem(i, 1, it1)
            t.setItem(i, 2, it2); t.setItem(i, 3, it3)
        t.setSortingEnabled(True)

    # ==================================================================
    # Sayfa 6: Isci Molalari
    # ==================================================================
    def _page_mola_olustur(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w); v.setContentsMargins(24, 10, 24, 24); v.setSpacing(12)
        t = QLabel("Iscilerin Mola Durumu"); t.setObjectName("PageTitle")
        v.addWidget(t)

        kapasite_card = QFrame(); kapasite_card.setObjectName("Card")
        kl = QVBoxLayout(kapasite_card); kl.setContentsMargins(18, 14, 18, 14); kl.setSpacing(8)
        kl_lbl = QLabel("AKTIF MOLA KAPASITESI")
        kl_lbl.setObjectName("CardLabel")
        kl.addWidget(kl_lbl)
        self.cap_bar = CapacityBar(3)
        kl.addWidget(self.cap_bar)
        v.addWidget(kapasite_card)

        self.lbl_mola_ozet = QLabel("-"); self.lbl_mola_ozet.setObjectName("PageSubtitle")
        v.addWidget(self.lbl_mola_ozet)

        self.mola_tablo = QTableWidget()
        self.mola_tablo.setColumnCount(5)
        self.mola_tablo.setHorizontalHeaderLabels(
            ["Isci ID", "Kullanici Adi", "Mola Baslangic", "Sure",
             "Kalan"])
        self.mola_tablo.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self.mola_tablo.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.mola_tablo.setAlternatingRowColors(True)
        v.addWidget(self.mola_tablo, 1)
        return w

    def _mola_tablo_yenile(self):
        rows = self.mola_ctrl.moladaki_isciler()
        self.mola_tablo.setRowCount(len(rows))
        for i, r in enumerate(rows):
            self.mola_tablo.setItem(i, 0, QTableWidgetItem(str(r["id"])))
            self.mola_tablo.setItem(i, 1, QTableWidgetItem(r["kullanici_adi"]))
            self.mola_tablo.setItem(i, 2, QTableWidgetItem(str(r["baslangic_zamani"])))
            sure_dk = int(r.get("sure_dakika") or 15)
            sure_it = QTableWidgetItem(f"{sure_dk} dk")
            sure_it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.mola_tablo.setItem(i, 3, sure_it)
            kalan_sn = max(0, int(r.get("kalan_saniye") or 0))
            dk, sn = divmod(kalan_sn, 60)
            kalan_it = QTableWidgetItem(f"{dk:02d}:{sn:02d}")
            kalan_it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if kalan_sn <= 60:
                kalan_it.setForeground(QBrush(QColor("#ef4444")))
            elif kalan_sn <= 180:
                kalan_it.setForeground(QBrush(QColor("#f59e0b")))
            self.mola_tablo.setItem(i, 4, kalan_it)
        toplam = self.mola_ctrl.toplam_isci_sayisi()
        molada = self.mola_ctrl.moladaki_sayi()
        aktif = self.mola_ctrl.aktif_calisan_sayisi()
        self.cap_bar.set_value(molada)
        self.lbl_mola_ozet.setText(
            f"Toplam isci: {toplam}   •   Aktif calisan: {aktif}   •   Molada: {molada}/3"
        )

    # ==================================================================
    # Sayfa 7: Isci Performansi
    # ==================================================================
    def _page_performans_olustur(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w); v.setContentsMargins(24, 10, 24, 24); v.setSpacing(12)

        ust = QHBoxLayout()
        t = QLabel("Isci Performansi"); t.setObjectName("PageTitle")
        sub = QLabel("Son 30 gun"); sub.setObjectName("PageSubtitle")
        dv = QVBoxLayout(); dv.setSpacing(2); dv.addWidget(t); dv.addWidget(sub)
        ust.addLayout(dv); ust.addStretch(1)
        btn_y = QPushButton("↻  Yenile"); btn_y.setObjectName("SecondaryBtn")
        btn_y.clicked.connect(self._performans_yenile)
        ust.addWidget(btn_y)
        v.addLayout(ust)

        self.perf_tablo = QTableWidget()
        self.perf_tablo.setColumnCount(7)
        self.perf_tablo.setHorizontalHeaderLabels([
            "Isci", "Tamamlanan", "Kismi", "Kalem", "Adet",
            "Ort. Sure (dk)", "Stok Hareket"
        ])
        self.perf_tablo.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self.perf_tablo.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.perf_tablo.setSortingEnabled(True)
        self.perf_tablo.setAlternatingRowColors(True)
        v.addWidget(self.perf_tablo, 1)
        return w

    def _performans_yenile(self):
        try:
            rows = DepoController.isci_performans(self.kullanici, 30)
        except YetkisizIslem:
            return
        t = self.perf_tablo
        t.setSortingEnabled(False)
        t.setRowCount(len(rows))
        for i, r in enumerate(rows):
            t.setItem(i, 0, QTableWidgetItem(r["kullanici_adi"]))
            t.setItem(i, 1, NumItem(r["tamamlanan_siparis"] or 0,
                                    str(r["tamamlanan_siparis"] or 0)))
            t.setItem(i, 2, NumItem(r["kismi_tamamlanan"] or 0,
                                    str(r["kismi_tamamlanan"] or 0)))
            t.setItem(i, 3, NumItem(r["toplam_kalem"] or 0,
                                    str(r["toplam_kalem"] or 0)))
            t.setItem(i, 4, NumItem(r["toplam_adet"] or 0,
                                    str(r["toplam_adet"] or 0)))
            sn = r.get("ortalama_sure_saniye")
            dk_str = f"{sn / 60.0:.1f}" if sn else "—"
            t.setItem(i, 5, NumItem((sn or 0) / 60.0, dk_str))
            t.setItem(i, 6, NumItem(r["stok_hareketi_sayisi"] or 0,
                                    str(r["stok_hareketi_sayisi"] or 0)))
        t.setSortingEnabled(True)

    # ==================================================================
    # Sayfa 8: Raporlar (CSV / PDF export)
    # ==================================================================
    def _page_raporlar_olustur(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w); v.setContentsMargins(24, 10, 24, 24); v.setSpacing(12)

        t = QLabel("Raporlar"); t.setObjectName("PageTitle")
        sub = QLabel("CSV (Excel uyumlu) veya PDF olarak export edin")
        sub.setObjectName("PageSubtitle")
        v.addWidget(t); v.addWidget(sub)

        # Rapor tipi secimleri — her biri ayri kart
        grid = QGridLayout(); grid.setSpacing(14)

        self._rapor_kartlari = []
        for i, (baslik, ipucu, tip) in enumerate([
            ("Tum Siparisler",      "Durum / atanan / tutar / sure",       "siparisler"),
            ("Urun / Stok Durumu",  "Stok, lokasyon ve kritik seviye",     "urunler"),
            ("Dusuk Stok",          f"Stok < {DUSUK_STOK_ESIK}",           "dusuk_stok"),
            ("Isci Performansi",    "Son 30 gun ozet",                     "performans"),
        ]):
            card = QFrame(); card.setObjectName("Card")
            cl = QVBoxLayout(card); cl.setContentsMargins(16, 14, 16, 14); cl.setSpacing(6)
            lbl = QLabel(baslik); lbl.setObjectName("CardValue")
            lbl.setStyleSheet("color:#0f172a; font-size:16px; font-weight:800;")
            tip_lbl = QLabel(ipucu); tip_lbl.setObjectName("CardHint")
            cl.addWidget(lbl); cl.addWidget(tip_lbl)
            btns = QHBoxLayout(); btns.setSpacing(6)
            b_csv = QPushButton("📄  CSV"); b_csv.setObjectName("SecondaryBtn")
            b_pdf = QPushButton("🖨️  PDF"); b_pdf.setObjectName("ActionBtn")
            b_csv.clicked.connect(
                lambda _=False, t=tip, bb=baslik: self._rapor_export(t, bb, "csv")
            )
            b_pdf.clicked.connect(
                lambda _=False, t=tip, bb=baslik: self._rapor_export(t, bb, "pdf")
            )
            btns.addWidget(b_csv); btns.addWidget(b_pdf); btns.addStretch(1)
            cl.addLayout(btns)
            grid.addWidget(card, i // 2, i % 2)
            self._rapor_kartlari.append(card)

        v.addLayout(grid)
        v.addStretch(1)
        return w

    def _raporlar_ozet_yenile(self):
        # Rapor kartlari sabit; yenileme gerektirmez. Sayfaya gelince
        # ileride dinamik ozet eklenebilir.
        pass

    # ---- Rapor veri toplama ------------------------------------------
    def _rapor_veri(self, tip: str) -> tuple[str, list[str], list[list[str]]]:
        """Rapor tipine gore (baslik, kolonlar, satirlar) dondurur."""
        if tip == "siparisler":
            rows = DepoController.tum_siparisler(self.kullanici)
            kolonlar = ["ID", "Olusturan", "Atanan", "Durum", "Adet",
                        "Tutar (TL)", "Hizlandirma", "Baslangic",
                        "Bitis", "Tarih"]
            sat = []
            for r in rows:
                sat.append([
                    str(r["id"]),
                    r.get("olusturan_adi") or "-",
                    r.get("atanan_isci_adi") or "-",
                    r["durum"],
                    str(r["toplam_adet"]),
                    f"{float(r['tutar']):.2f}",
                    "Evet" if int(r.get("hizlandirma_istendi") or 0) else "Hayir",
                    r.get("hazirlanma_baslangic") or "-",
                    r.get("hazirlanma_bitis") or "-",
                    r.get("tarih") or "-",
                ])
            return ("Tum Siparisler", kolonlar, sat)

        if tip == "urunler":
            urunler = DepoController.urunleri_getir()
            kolonlar = ["ID", "Ad", "Stok", "Fiyat (TL)",
                        "Toplam Deger (TL)", "Koridor", "Raf", "Goz"]
            sat = []
            for u in urunler:
                sat.append([
                    str(u.urun_id), u.ad, str(u.stok),
                    f"{u.fiyat:.2f}", f"{u.toplam_deger():.2f}",
                    u.koridor or "-", u.raf or "-", u.goz or "-",
                ])
            return ("Urun / Stok Durumu", kolonlar, sat)

        if tip == "dusuk_stok":
            urunler = DepoController.dusuk_stoklu_urunler()
            kolonlar = ["ID", "Ad", "Stok", "Fiyat (TL)", "Lokasyon"]
            sat = [
                [str(u.urun_id), u.ad, str(u.stok),
                 f"{u.fiyat:.2f}", u.lokasyon() or "-"]
                for u in urunler
            ]
            return (f"Dusuk Stok (<{DUSUK_STOK_ESIK})", kolonlar, sat)

        if tip == "performans":
            rows = DepoController.isci_performans(self.kullanici, 30)
            kolonlar = ["Isci", "Tamamlanan", "Kismi", "Kalem", "Adet",
                        "Ort. Sure (dk)", "Stok Hareket"]
            sat = []
            for r in rows:
                sn = r.get("ortalama_sure_saniye")
                dk_str = f"{sn / 60.0:.1f}" if sn else "-"
                sat.append([
                    r["kullanici_adi"],
                    str(r["tamamlanan_siparis"] or 0),
                    str(r["kismi_tamamlanan"] or 0),
                    str(r["toplam_kalem"] or 0),
                    str(r["toplam_adet"] or 0),
                    dk_str,
                    str(r["stok_hareketi_sayisi"] or 0),
                ])
            return ("Isci Performansi (30 Gun)", kolonlar, sat)

        raise ValueError(f"Bilinmeyen rapor tipi: {tip}")

    def _rapor_export(self, tip: str, baslik: str, format: str) -> None:
        """Secilen rapor tipini CSV veya PDF olarak disari aktar."""
        try:
            t_baslik, kolonlar, satirlar = self._rapor_veri(tip)
        except YetkisizIslem as e:
            self.toast.error("Yetki", str(e)); return
        except Exception as e:
            self.toast.error("Hata", str(e)); return

        from PyQt6.QtWidgets import QFileDialog
        from datetime import datetime
        default_ad = (
            f"rapor_{tip}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )

        if format == "csv":
            yol, _ = QFileDialog.getSaveFileName(
                self, "CSV Kaydet", f"{default_ad}.csv",
                "CSV Dosyasi (*.csv)"
            )
            if not yol:
                return
            try:
                self._export_csv(yol, kolonlar, satirlar)
            except Exception as e:
                self.toast.error("CSV Hatasi", str(e)); return
            self.toast.success("CSV Kaydedildi", yol)
            return

        # PDF — QPrinter ile HTML'den olustur
        yol, _ = QFileDialog.getSaveFileName(
            self, "PDF Kaydet", f"{default_ad}.pdf",
            "PDF Dosyasi (*.pdf)"
        )
        if not yol:
            return
        try:
            self._export_pdf(yol, t_baslik, kolonlar, satirlar)
        except Exception as e:
            self.toast.error("PDF Hatasi", str(e)); return
        self.toast.success("PDF Kaydedildi", yol)

    def _export_csv(self, yol: str, kolonlar, satirlar) -> None:
        import csv
        with open(yol, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(kolonlar)
            for s in satirlar:
                w.writerow(s)

    def _export_pdf(self, yol: str, baslik: str, kolonlar, satirlar) -> None:
        from PyQt6.QtPrintSupport import QPrinter
        from PyQt6.QtGui import QTextDocument, QPageSize, QPageLayout
        from PyQt6.QtCore import QMarginsF
        from datetime import datetime

        # HTML tablosu
        kolon_html = "".join(f"<th>{k}</th>" for k in kolonlar)
        satir_html_parts = []
        for s in satirlar:
            satir_html_parts.append(
                "<tr>" + "".join(f"<td>{x}</td>" for x in s) + "</tr>"
            )
        gövde = (
            f"<h1 style='font-family:Segoe UI,sans-serif;color:#0f172a;'>"
            f"{baslik}</h1>"
            f"<p style='color:#64748b;font-family:Segoe UI,sans-serif;"
            f"font-size:11px;'>Uretim tarihi: "
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  "
            f"— Toplam kayit: {len(satirlar)}</p>"
            "<table cellspacing='0' cellpadding='6' "
            "style='border-collapse:collapse; width:100%; "
            "font-family:Segoe UI, sans-serif; font-size:10px;'>"
            f"<thead><tr style='background:#f1f5f9;'>{kolon_html}</tr></thead>"
            f"<tbody>{''.join(satir_html_parts)}</tbody></table>"
        )
        html = (
            "<html><head><style>"
            "table,th,td{border:1px solid #e2e8f0;} "
            "th{text-align:left;color:#334155;font-weight:700;} "
            "tr:nth-child(even){background:#f8fafc;} "
            "td{color:#0f172a;}"
            "</style></head><body>" + gövde + "</body></html>"
        )

        doc = QTextDocument()
        doc.setHtml(html)
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(yol)
        printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        printer.setPageMargins(QMarginsF(14, 14, 14, 14),
                               QPageLayout.Unit.Millimeter)
        doc.print(printer)

    # ==================================================================
    # Sayfa 9: Kullanicilar (Admin)
    # ==================================================================
    def _page_kullanicilar_olustur(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w); v.setContentsMargins(24, 10, 24, 24); v.setSpacing(12)

        ust = QHBoxLayout()
        t = QLabel("Kullanicilar"); t.setObjectName("PageTitle")
        sub = QLabel("Isci / yonetici yonetimi — ekle / sifre sifirla / sil")
        sub.setObjectName("PageSubtitle")
        dv = QVBoxLayout(); dv.setSpacing(2); dv.addWidget(t); dv.addWidget(sub)
        ust.addLayout(dv); ust.addStretch(1)
        btn_y = QPushButton("↻  Yenile"); btn_y.setObjectName("SecondaryBtn")
        btn_y.clicked.connect(self._kullanicilar_tablosunu_yenile)
        ust.addWidget(btn_y)
        v.addLayout(ust)

        # Tablo
        self.kullanici_tablo = QTableWidget()
        self.kullanici_tablo.setColumnCount(4)
        self.kullanici_tablo.setHorizontalHeaderLabels(
            ["ID", "Kullanici Adi", "Rol", "Islem"]
        )
        self.kullanici_tablo.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self.kullanici_tablo.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.kullanici_tablo.setAlternatingRowColors(True)
        self.kullanici_tablo.verticalHeader().setDefaultSectionSize(36)
        v.addWidget(self.kullanici_tablo, 1)

        # Ekleme formu
        form = QFrame(); form.setObjectName("Card")
        fl = QVBoxLayout(form); fl.setContentsMargins(16, 14, 16, 14); fl.setSpacing(8)
        form_t = QLabel("YENI KULLANICI EKLE"); form_t.setObjectName("CardLabel")
        fl.addWidget(form_t)

        row = QHBoxLayout(); row.setSpacing(8)
        self.uk_ad = QLineEdit(); self.uk_ad.setPlaceholderText("Kullanici adi")
        self.uk_sifre = QLineEdit()
        self.uk_sifre.setPlaceholderText("Sifre (en az 4 karakter)")
        self.uk_sifre.setEchoMode(QLineEdit.EchoMode.Password)
        self.uk_rol = QComboBox()
        self.uk_rol.addItems(["Isci", "Yonetici"])
        self.uk_rol.setMaximumWidth(120)
        b_ekle = QPushButton("➕  Ekle")
        b_ekle.setObjectName("ActionBtn")
        b_ekle.clicked.connect(self._kullanici_ekle)
        row.addWidget(QLabel("Ad:")); row.addWidget(self.uk_ad, 2)
        row.addSpacing(4)
        row.addWidget(QLabel("Sifre:")); row.addWidget(self.uk_sifre, 2)
        row.addSpacing(4)
        row.addWidget(QLabel("Rol:")); row.addWidget(self.uk_rol)
        row.addWidget(b_ekle)
        fl.addLayout(row)
        v.addWidget(form)
        return w

    def _kullanicilar_tablosunu_yenile(self):
        try:
            rows = AuthController.tum_kullanicilar(self.kullanici)
        except Exception as e:
            self.toast.error("Yetki", str(e)); return
        t = self.kullanici_tablo
        t.setRowCount(len(rows))
        for i, r in enumerate(rows):
            t.setItem(i, 0, NumItem(r["id"], str(r["id"])))
            t.setItem(i, 1, QTableWidgetItem(r["kullanici_adi"]))
            # Rol rozeti (basit metin, renkli)
            rol = r["rol"]
            rol_it = QTableWidgetItem(rol)
            rol_it.setForeground(QBrush(QColor(
                "#8b5cf6" if rol == "Yonetici" else "#3b82f6"
            )))
            t.setItem(i, 2, rol_it)
            # Islem butonlari (yan yana)
            wrap = QWidget()
            wl = QHBoxLayout(wrap); wl.setContentsMargins(4, 2, 4, 2)
            wl.setSpacing(6)
            b_sifre = QPushButton("🔑 Sifre")
            b_sifre.setObjectName("SecondaryBtn")
            b_sifre.clicked.connect(
                lambda _=False, uid=r["id"], ad=r["kullanici_adi"]:
                    self._sifre_sifirla(uid, ad)
            )
            b_sil = QPushButton("🗑 Sil")
            b_sil.setObjectName("DangerBtn")
            b_sil.clicked.connect(
                lambda _=False, uid=r["id"], ad=r["kullanici_adi"]:
                    self._kullanici_sil(uid, ad)
            )
            wl.addWidget(b_sifre); wl.addWidget(b_sil); wl.addStretch(1)
            t.setCellWidget(i, 3, wrap)

    def _kullanici_ekle(self):
        ad = self.uk_ad.text().strip()
        sifre = self.uk_sifre.text()
        rol = self.uk_rol.currentText()
        ok, msg = AuthController.kullanici_ekle(
            self.kullanici, ad, sifre, rol,
        )
        if ok:
            self.toast.success("Eklendi", msg)
            self.uk_ad.clear(); self.uk_sifre.clear()
            self._kullanicilar_tablosunu_yenile()
        else:
            self.toast.error("Eklenemedi", msg)

    def _sifre_sifirla(self, uid: int, kullanici_adi: str):
        from PyQt6.QtWidgets import QInputDialog, QLineEdit as _QLE
        yeni, ok = QInputDialog.getText(
            self, "Sifre Sifirla",
            f"'{kullanici_adi}' icin yeni sifre:",
            _QLE.EchoMode.Password,
        )
        if not ok:
            return
        ok2, msg = AuthController.sifre_sifirla(self.kullanici, uid, yeni)
        if ok2:
            self.toast.success("Sifre Sifirlandi", msg)
        else:
            self.toast.error("Islem Basarisiz", msg)

    def _kullanici_sil(self, uid: int, kullanici_adi: str):
        c = QMessageBox.question(
            self, "Kullanici Sil",
            f"'{kullanici_adi}' kullanicisi silinsin mi?\n\n"
            "Bu islem geri alinamaz; mola ve siparis atamalari "
            "silinen kullanici yerine 'None' olarak gorunmeye baslar."
        )
        if c != QMessageBox.StandardButton.Yes:
            return
        ok, msg = AuthController.kullanici_sil(self.kullanici, uid)
        if ok:
            self.toast.success("Silindi", msg)
            self._kullanicilar_tablosunu_yenile()
        else:
            self.toast.error("Silinemedi", msg)

    # ==================================================================
    # Bildirim sistemi
    # ==================================================================
    def _bildirim_kontrol(self):
        try:
            rows = DepoController.tum_siparisler(self.kullanici)
        except YetkisizIslem:
            return
        if not rows:
            return
        max_id = max(int(r["id"]) for r in rows)
        if self._son_siparis_id and max_id > self._son_siparis_id:
            yeni_sayi = max_id - self._son_siparis_id
            self.bell.push(f"Yeni siparis geldi (#{max_id})")
            self.toast.info("Yeni Siparis", f"{yeni_sayi} yeni siparis olustu.")
        self._son_siparis_id = max_id

        # Dusuk stok uyarisi
        dusuk = DepoController.dusuk_stoklu_urunler()
        if dusuk and not getattr(self, "_dusuk_uyari_verildi", False):
            self.bell.push(f"Dusuk stok: {len(dusuk)} urun esik altinda")
            self._dusuk_uyari_verildi = True
        elif not dusuk:
            self._dusuk_uyari_verildi = False

    # ------------------------------------------------------------------
    def _tum_verileri_yenile(self):
        self._urunler_tablosu_yenile()
        self._sepet_sayfasini_yenile()
        self._siparisler_tablosunu_yenile()
        self._dusuk_tablo_yenile()
        self._mola_tablo_yenile()
        self._dashboard_yenile()

    def _sifre_degistir_ac(self):
        dlg = SifreDegistirDialog(self.kullanici, parent=self)
        if dlg.exec():
            self.toast.success(
                "Sifre Guncellendi",
                "Yeni sifreniz aktif; bir sonraki girisinizde gecerli."
            )

    def _cikis_yap(self):
        from .login_ui import LoginWindow
        self._login_ref = LoginWindow()
        self._login_ref.show()
        self.close()
