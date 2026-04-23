"""
frontend/isci_panel_ui.py
-------------------------
İşçi paneli (premium tema).
  1) Urunler          : goruntule, ara, stok +/-; renkli stok rozeti
  2) Gelen Siparisler : kart gorunumu + 'Hazirlamaya Basla' dialog +
                        otomatik tazeleme (5s) + toast bildirimler
  3) Mola Durumu      : kapasite bar (0/3 renklendirilmis) + butonlar

Sipariş hazırlama akışı artık "tek tık → tamamlandı" değil: işçi
`HazirlamaDialog` içinde her kalemi rafta topladıkça tek tek
işaretler (veri tabanına `hazirlandi=1` yazılır). Tüm kalemler
işaretlendiğinde "Siparisi Tamamla" butonu aktif olur; butona
basıldığında son-stok kontrolü + stok düşümü + durum=tamamlandi
tek transaction içinde yapılır.
"""

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QBrush
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QLineEdit, QSpinBox, QMessageBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QStackedWidget, QStatusBar, QGridLayout, QAbstractItemView,
    QDialog, QScrollArea, QProgressBar,
)

from backend.controllers.depo_controller import (
    DepoController, StokYetersizHatasi, SiparisZatenIslendi,
    KalemlerEksikHatasi,
)
from backend.controllers.mola_controller import MolaController

from .widgets import (
    MetricCard, StatusBadge, ToastManager, LoadingOverlay, NotificationBell,
    OrderCard, Sidebar, CapacityBar, NumItem, SifreDegistirDialog,
    ProfileAvatarButton, EmptyState, _repolish,
)


DUSUK_STOK_ESIK = 25
YUKSEK_STOK_ESIK = 100


def _stok_rengi(stok: int) -> QColor | None:
    if stok < DUSUK_STOK_ESIK:
        return QColor("#dc2626")
    if stok >= YUKSEK_STOK_ESIK:
        return QColor("#059669")
    return None


# ----------------------------------------------------------------------
# Koridor bazli renk paleti — toplama rotasinda gorsel ipucu icin.
# Koridor ilk harfine gore sabit renk atar; boylece ayni koridordaki
# kalemler ayni renge boyanir ve isci raf degisimini kolay anlar.
# ----------------------------------------------------------------------
_KORIDOR_RENK = {
    "A": "#6366f1",  # indigo
    "B": "#10b981",  # emerald
    "C": "#f59e0b",  # amber
    "D": "#ef4444",  # rose
    "E": "#3b82f6",  # blue
    "F": "#8b5cf6",  # violet
    "G": "#14b8a6",  # teal
    "H": "#f97316",  # orange
}


def _koridor_renk(koridor: str) -> str:
    """Verilen koridorun ilk harfine gore renk kodu dondurur."""
    if not koridor:
        return "#64748b"  # nötr gri
    return _KORIDOR_RENK.get(koridor.strip()[:1].upper(), "#64748b")


def _lokasyon_str(koridor: str, raf: str, goz: str) -> str:
    parcalar = [p for p in (
        (koridor or "").strip(),
        (raf or "").strip(),
        (goz or "").strip(),
    ) if p]
    return "-".join(parcalar) if parcalar else "—"


# ----------------------------------------------------------------------
# Hazirlama Dialog'u — depoda toplama ekrani
# ----------------------------------------------------------------------
_SATIR_RENK_HAZIR = QColor("#d1fae5")   # yesilimsi
_SATIR_RENK_BOS   = QColor("#ffffff")


class HazirlamaDialog(QDialog):
    """Profesyonel toplama ekrani: tablo + kalem-basi checkbox +
    progress bar + 'Siparisi Tamamla' butonu. Siparis `tamamlandi`
    durumuna gecince tum kontroller kilitlenir.
    """

    def __init__(self, siparis_id: int, kullanici, toast_mgr,
                 on_state_change=None, parent=None):
        super().__init__(parent)
        self.siparis_id = siparis_id
        self.kullanici = kullanici
        self.toast = toast_mgr
        self._on_state_change = on_state_change
        self._readonly = False
        self._suppress_change = False
        self._detay_id_by_row: list[int] = []

        self.setWindowTitle(f"Siparis Hazirlama — #{siparis_id}")
        self.resize(720, 580)

        self._loader = LoadingOverlay(self)

        v = QVBoxLayout(self); v.setContentsMargins(18, 18, 18, 18); v.setSpacing(10)

        # Üst şerit: siparis bilgisi + durum badge
        baslik = QLabel(f"Siparis #{siparis_id}")
        baslik.setStyleSheet("color:#f8fafc; font-size:18px; font-weight:800;")
        v.addWidget(baslik)

        self.bilgi = QLabel("-"); self.bilgi.setWordWrap(True)
        self.bilgi.setStyleSheet("color:#cbd5e1; font-size:12px;")
        v.addWidget(self.bilgi)

        self.badge = StatusBadge()
        v.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignLeft)

        # Toplama rotasi banner — koridor renkli adimli yol haritasi
        self.rota_banner = QLabel()
        self.rota_banner.setWordWrap(True)
        self.rota_banner.setTextFormat(Qt.TextFormat.RichText)
        self.rota_banner.setStyleSheet(
            "background:#0f172a; border:1px solid #1e293b; "
            "border-radius:12px; padding:12px;"
        )
        v.addWidget(self.rota_banner)

        # Kalem tablosu — toplama rotasi (koridor/raf/goz) sirali
        # Kolonlar: # | Hazir | Lokasyon (renkli rozet) | Urun | Istenen |
        #           Stok | B.Fiyat | Tutar
        self.tablo = QTableWidget()
        self.tablo.setColumnCount(8)
        self.tablo.setHorizontalHeaderLabels(
            ["#", "Hazir", "Lokasyon", "Urun", "Istenen", "Stok",
             "B.Fiyat", "Tutar"]
        )
        hdr = self.tablo.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        hdr.resizeSection(0, 44)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        hdr.resizeSection(1, 68)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        hdr.resizeSection(2, 140)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)
        # Satir yuksekligi: rozetler ve checkbox'lar icin rahat alan
        self.tablo.verticalHeader().setDefaultSectionSize(38)
        self.tablo.verticalHeader().setVisible(False)
        self.tablo.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tablo.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.tablo.setAlternatingRowColors(False)
        self.tablo.itemChanged.connect(self._on_item_changed)
        v.addWidget(self.tablo, 1)

        # İlerleme
        ilerleme_row = QHBoxLayout(); ilerleme_row.setSpacing(10)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100); self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setProperty("level", "high")
        _repolish(self.progress)
        ilerleme_row.addWidget(self.progress, 1)
        self.ilerleme_lbl = QLabel("0 / 0 urun hazirlandi")
        self.ilerleme_lbl.setStyleSheet(
            "color:#f8fafc; font-size:13px; font-weight:700;"
        )
        ilerleme_row.addWidget(self.ilerleme_lbl)
        v.addLayout(ilerleme_row)

        # Alt satır: toplam + butonlar
        alt = QHBoxLayout()
        self.toplam_lbl = QLabel("Toplam: 0.00 TL")
        self.toplam_lbl.setStyleSheet(
            "color:#f8fafc; font-size:16px; font-weight:800;"
        )
        alt.addWidget(self.toplam_lbl); alt.addStretch(1)

        self.btn_kapat = QPushButton("Kapat")
        self.btn_kapat.setObjectName("SecondaryBtn")
        self.btn_kapat.clicked.connect(self.reject)
        alt.addWidget(self.btn_kapat)

        self.btn_kismi = QPushButton("⋯  Kismi Tamamla")
        self.btn_kismi.setObjectName("WarnBtn")
        self.btn_kismi.setEnabled(False)
        self.btn_kismi.setToolTip(
            "Isaretli kalemleri dus, kalanlar beklemede kalir."
        )
        self.btn_kismi.clicked.connect(self._kismi_tamamla)
        alt.addWidget(self.btn_kismi)

        self.btn_tamamla = QPushButton("✔  Siparisi Tamamla")
        self.btn_tamamla.setObjectName("SuccessBtn")
        self.btn_tamamla.setEnabled(False)
        self.btn_tamamla.clicked.connect(self._tamamla)
        alt.addWidget(self.btn_tamamla)
        v.addLayout(alt)

        self._yukle()

    # ------------------------------------------------------------------
    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if hasattr(self, "_loader"):
            self._loader.setGeometry(self.rect())

    # ------------------------------------------------------------------
    def _yukle(self) -> None:
        """Veritabanından sipariş ve kalemleri yükle, tabloyu doldur."""
        d = DepoController.siparis_detayi(self.siparis_id)
        if not d:
            self.bilgi.setText("Siparis bulunamadi.")
            self.btn_tamamla.setEnabled(False)
            return

        s = d["siparis"]
        durum = str(s["durum"])
        acil = bool(int(s.get("hizlandirma_istendi") or 0))
        self._readonly = (durum != "beklemede")
        self.badge.apply_durum(durum)
        meta = (
            f"<b>Olusturan:</b> {s.get('olusturan_adi') or '-'}   •   "
            f"<b>Atanan:</b> {s.get('atanan_isci_adi') or '-'}   •   "
            f"<b>Tarih:</b> {s.get('tarih') or '-'}"
        )
        if acil and durum == "beklemede":
            meta = (
                "<span style='color:#fbbf24;font-weight:800;'>"
                "⚡ YONETICI HIZLANDIRMA ISTEDI</span><br>"
                + meta
            )
        self.bilgi.setText(meta)

        dets = d["detaylar"]
        self._suppress_change = True
        self.tablo.setRowCount(len(dets))
        self._detay_id_by_row = []
        rota_html_parts = []
        for i, dt in enumerate(dets):
            detay_id = int(dt["detay_id"])
            self._detay_id_by_row.append(detay_id)
            hazir_seviye = int(dt.get("hazirlandi") or 0)

            koridor = (dt.get("koridor") or "").strip()
            raf = (dt.get("raf") or "").strip()
            goz = (dt.get("goz") or "").strip()
            lok = _lokasyon_str(koridor, raf, goz)
            renk = _koridor_renk(koridor)

            # Kolon 0: Sira numarasi (buyuk, okunakli)
            sira_it = NumItem(i + 1, str(i + 1))
            sira_it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            f = sira_it.font()
            f.setBold(True); f.setPointSize(f.pointSize() + 1)
            sira_it.setFont(f)
            sira_it.setForeground(QBrush(QColor("#334155")))
            self.tablo.setItem(i, 0, sira_it)

            # Kolon 1: checkbox (hazirlandi=2 tamamlanan ise salt okunur)
            chk = QTableWidgetItem()
            flags = Qt.ItemFlag.ItemIsEnabled
            if not self._readonly and hazir_seviye != 2:
                flags |= Qt.ItemFlag.ItemIsUserCheckable
            chk.setFlags(flags)
            if hazir_seviye == 2:
                chk.setCheckState(Qt.CheckState.Checked)
                chk.setToolTip("Bu kalem tamamlandi — stoktan dusuldu.")
            else:
                chk.setCheckState(
                    Qt.CheckState.Checked if hazir_seviye == 1
                    else Qt.CheckState.Unchecked
                )
            chk.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.tablo.setItem(i, 1, chk)

            # Kolon 2: Renkli LOKASYON rozeti (cellWidget ile pill)
            # Sorting icin arka plan item ayrica yerlestirilir.
            lok_arkaplan = QTableWidgetItem(lok)
            lok_arkaplan.setFlags(Qt.ItemFlag.ItemIsEnabled)
            lok_arkaplan.setToolTip(
                f"📍 Koridor {koridor or '—'}  •  "
                f"Raf {raf or '—'}  •  Goz {goz or '—'}"
            )
            self.tablo.setItem(i, 2, lok_arkaplan)

            lok_pill = QLabel(lok)
            lok_pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lok_pill.setStyleSheet(
                f"background:{renk}; color:white; "
                f"padding:6px 12px; border-radius:12px; "
                f"font-weight:800; font-size:12px; letter-spacing:0.5px;"
            )
            wrap = QWidget()
            wl = QHBoxLayout(wrap)
            wl.setContentsMargins(6, 2, 6, 2); wl.setSpacing(0)
            wl.addWidget(lok_pill, 0, Qt.AlignmentFlag.AlignCenter)
            self.tablo.setCellWidget(i, 2, wrap)

            # Kolon 3: Urun adi (hazirsa hafif soluk yesil arka plan)
            urun_it = QTableWidgetItem(dt["urun_adi"])
            urun_it.setToolTip(
                f"📍 Lokasyon: {lok}\n"
                f"Koridor {koridor or '—'} → Raf {raf or '—'} → "
                f"Goz {goz or '—'}\n"
                f"Adet: {dt['adet']}"
            )
            if hazir_seviye == 2:
                urun_it.setToolTip(urun_it.toolTip() + "\n(Tamamlandi)")
            f2 = urun_it.font(); f2.setBold(True)
            urun_it.setFont(f2)
            self.tablo.setItem(i, 3, urun_it)

            # Kolon 4: Istenen adet
            adet_it = NumItem(dt["adet"], str(dt["adet"]))
            adet_it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            fa = adet_it.font(); fa.setBold(True)
            adet_it.setFont(fa)
            self.tablo.setItem(i, 4, adet_it)

            # Kolon 5: Mevcut stok (yetersizse kirmizi)
            mevcut_stok = int(dt.get("mevcut_stok") or 0)
            stok_it = NumItem(mevcut_stok, str(mevcut_stok))
            stok_it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if mevcut_stok < int(dt["adet"]):
                stok_it.setForeground(QBrush(QColor("#dc2626")))
                stok_it.setToolTip(
                    "Yetersiz stok — tamamlamaya calisirken hata alacaksiniz."
                )
            self.tablo.setItem(i, 5, stok_it)

            # Kolon 6/7: B.Fiyat / Tutar
            bf = NumItem(dt["fiyat"], f"{float(dt['fiyat']):.2f}")
            bf.setTextAlignment(Qt.AlignmentFlag.AlignRight
                                 | Qt.AlignmentFlag.AlignVCenter)
            self.tablo.setItem(i, 6, bf)

            tutar = NumItem(dt["tutar"], f"{float(dt['tutar']):,.2f}")
            tutar.setTextAlignment(Qt.AlignmentFlag.AlignRight
                                    | Qt.AlignmentFlag.AlignVCenter)
            self.tablo.setItem(i, 7, tutar)

            self._satir_renklendir(i, hazir_seviye in (1, 2))

            # Rota banner pariliisi
            ok_isareti = "✓" if hazir_seviye in (1, 2) else f"{i + 1}"
            rota_html_parts.append(
                f"<span style='background:{renk}; color:white; "
                f"padding:5px 12px; border-radius:14px; "
                f"font-weight:700; font-size:12px; "
                f"white-space:nowrap;'>"
                f"&nbsp;{ok_isareti}&nbsp; "
                f"{dt['urun_adi']} "
                f"<span style='opacity:0.85;'>@ {lok}</span>"
                f"</span>"
            )

        # Rota banner'i yerlestir
        if rota_html_parts:
            koridor_set = {(d.get("koridor") or "").strip() or "?"
                           for d in dets}
            rota = (" &nbsp;→&nbsp; ".join(rota_html_parts))
            self.rota_banner.setText(
                "<div style='color:#cbd5e1; font-size:11px; "
                "letter-spacing:1px; font-weight:700; margin-bottom:6px;'>"
                f"📋 TOPLAMA ROTASI "
                f"<span style='color:#94a3b8; font-weight:600; "
                f"letter-spacing:0; text-transform:none;'>"
                f"&nbsp;·&nbsp; {len(dets)} durak &nbsp;·&nbsp; "
                f"{len(koridor_set)} koridor ({', '.join(sorted(koridor_set))})"
                f"</span></div>"
                f"<div style='line-height:2.4;'>{rota}</div>"
            )
        else:
            self.rota_banner.setText("")
            self.rota_banner.setVisible(False)

        self.toplam_lbl.setText(f"Toplam: {d['toplam_tutar']:,.2f} TL")
        self._suppress_change = False
        self._ilerleme_guncelle()

        if self._readonly:
            self.btn_tamamla.setEnabled(False)
            self.btn_kismi.setEnabled(False)
            if durum == "iptal":
                self.btn_tamamla.setText("✕  Iptal Edildi")
            elif durum == "kismi_tamamlandi":
                self.btn_tamamla.setText("⋯  Kismi Tamamlandi")
            else:
                self.btn_tamamla.setText("✔  Tamamlandi")

    # ------------------------------------------------------------------
    def _satir_renklendir(self, row: int, hazir: bool) -> None:
        renk = _SATIR_RENK_HAZIR if hazir else _SATIR_RENK_BOS
        brush = QBrush(renk)
        # kilitli sipariste biraz soluk
        for col in range(self.tablo.columnCount()):
            it = self.tablo.item(row, col)
            if it is not None:
                it.setBackground(brush)
                if self._readonly:
                    it.setForeground(QBrush(QColor("#475569")))

    # ------------------------------------------------------------------
    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._suppress_change:
            return
        if item.column() != 1:  # 1 = Hazir checkbox kolonu
            return
        row = item.row()
        if row < 0 or row >= len(self._detay_id_by_row):
            return
        hazir = (item.checkState() == Qt.CheckState.Checked)
        detay_id = self._detay_id_by_row[row]

        try:
            ozet = DepoController.kalem_hazir_isaretle(
                self.kullanici, detay_id, hazir
            )
        except SiparisZatenIslendi as e:
            self.toast.warn("Kilitli", str(e))
            self._yukle()  # durumu tekrar yukle
            return
        except PermissionError as e:
            self.toast.error("Yetki", str(e))
            self._geri_al(row, not hazir)
            return
        except Exception as e:
            self.toast.error("Hata", str(e))
            self._geri_al(row, not hazir)
            return

        self._satir_renklendir(row, hazir)
        self._ilerleme_guncelle_from(ozet)
        # Karti listeye yansit — dis taraf siparis listesini yenilesin
        if self._on_state_change:
            self._on_state_change()

    def _geri_al(self, row: int, eski_hazir: bool) -> None:
        self._suppress_change = True
        it = self.tablo.item(row, 1)  # 1 = Hazir checkbox kolonu
        if it is not None:
            it.setCheckState(
                Qt.CheckState.Checked if eski_hazir else Qt.CheckState.Unchecked
            )
        self._suppress_change = False

    # ------------------------------------------------------------------
    def _ilerleme_guncelle(self) -> None:
        toplam = self.tablo.rowCount()
        hazir = 0
        for r in range(toplam):
            it = self.tablo.item(r, 1)  # 1 = Hazir checkbox kolonu
            if it is not None and it.checkState() == Qt.CheckState.Checked:
                hazir += 1
        self._ilerleme_uygula(hazir, toplam)

    def _ilerleme_guncelle_from(self, ozet: dict) -> None:
        self._ilerleme_uygula(
            int(ozet.get("hazir_sayisi") or 0),
            int(ozet.get("kalem_sayisi") or 0),
        )

    def _ilerleme_uygula(self, hazir: int, toplam: int) -> None:
        self.progress.setRange(0, max(toplam, 1))
        self.progress.setValue(hazir)
        oran = (hazir / toplam) if toplam else 0.0
        if toplam and hazir == toplam:
            self.progress.setProperty("level", "low")   # yesil
        elif oran >= 0.5:
            self.progress.setProperty("level", "mid")   # sari
        else:
            self.progress.setProperty("level", "high")  # kirmizi
        _repolish(self.progress)
        self.ilerleme_lbl.setText(f"{hazir} / {toplam} urun hazirlandi")
        # Tamamla: hepsi hazirsa; Kismi: en az biri hazir + en az biri
        # eksikse
        tumu_hazir = toplam > 0 and hazir == toplam
        kismi_uygun = toplam > 0 and 0 < hazir < toplam
        self.btn_tamamla.setEnabled(not self._readonly and tumu_hazir)
        self.btn_kismi.setEnabled(not self._readonly and kismi_uygun)

    # ------------------------------------------------------------------
    def _tamamla(self) -> None:
        if self._readonly:
            return
        c = QMessageBox.question(
            self, "Onay",
            "Tum kalemler isaretlendi. Siparis tamamlansin mi?\n\n"
            "• Son stok kontrolu yapilacak.\n"
            "• Tum urunlerin stoklari topluca dusurulecek.\n"
            "• Islem atomik (hepsi ya da hic) calisir."
        )
        if c != QMessageBox.StandardButton.Yes:
            return

        self._loader.start()
        try:
            s = DepoController.siparisi_tamamla(
                self.kullanici, self.siparis_id
            )
        except KalemlerEksikHatasi as e:
            self._loader.stop(); self.toast.warn("Eksik", str(e)); return
        except StokYetersizHatasi as e:
            self._loader.stop()
            self.toast.error("Stok Yetersiz",
                             "Bazi urunlerde stok yetersiz: " + str(e))
            return
        except SiparisZatenIslendi as e:
            self._loader.stop()
            self.toast.warn("Islem yapilamadi", str(e))
            self._yukle()
            return
        except PermissionError as e:
            self._loader.stop(); self.toast.error("Yetki", str(e)); return
        except Exception as e:
            self._loader.stop(); self.toast.error("Hata", str(e)); return

        self._loader.stop()
        self.toast.success(
            "Siparis Tamamlandi",
            f"#{s.siparis_id} tamamlandi ve stoklar dusuldu."
        )
        if self._on_state_change:
            self._on_state_change()
        self.accept()

    # ------------------------------------------------------------------
    def _kismi_tamamla(self) -> None:
        """Isaretli kalemleri dus, kalanlari beklemede birak."""
        if self._readonly:
            return
        c = QMessageBox.question(
            self, "Kismi Tamamla",
            "Yalnizca isaretli kalemler stoktan dusulecek ve siparis "
            "'kismi_tamamlandi' olarak isaretlenecek.\n\n"
            "Kalan kalemler sonradan hazirlanamaz; yonetici iptal "
            "edebilir (o durumda dusen stoklar geri yuklenir).\n\n"
            "Devam edilsin mi?"
        )
        if c != QMessageBox.StandardButton.Yes:
            return

        self._loader.start()
        try:
            s = DepoController.siparisi_kismi_tamamla(
                self.kullanici, self.siparis_id
            )
        except KalemlerEksikHatasi as e:
            self._loader.stop(); self.toast.warn("Eksik", str(e)); return
        except StokYetersizHatasi as e:
            self._loader.stop()
            self.toast.error("Stok Yetersiz", str(e)); return
        except SiparisZatenIslendi as e:
            self._loader.stop()
            self.toast.warn("Islem yapilamadi", str(e))
            self._yukle()
            return
        except PermissionError as e:
            self._loader.stop(); self.toast.error("Yetki", str(e)); return
        except Exception as e:
            self._loader.stop(); self.toast.error("Hata", str(e)); return

        self._loader.stop()
        self.toast.success(
            "Kismi Tamamlandi",
            f"#{s.siparis_id} kismi tamamlandi — isaretli kalemler dusuldu."
        )
        if self._on_state_change:
            self._on_state_change()
        self.accept()


# ----------------------------------------------------------------------
class IsciPanel(QMainWindow):
    def __init__(self, kullanici):
        super().__init__()
        self.kullanici = kullanici
        self.mola_ctrl = MolaController()

        self.setWindowTitle("Isci Paneli - Depo ve Stok Yonetimi")
        self.resize(1240, 780)

        self.toast = ToastManager(self)
        self._login_ref = None
        self._bilinen_siparis_idler: set[int] = set()
        # Hangi siparislerde hizlandirma istegi zaten bildirildi (yeni
        # istek algılandığında tekrar bildirilmemesi için).
        self._bilinen_acil_idler: set[int] = set()

        self._olustur_ui()
        self._urunler_yenile()
        self._siparisler_yenile()
        self._mola_ozet_yenile()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._periyodik_yenile)
        self._timer.start(5000)

    # ------------------------------------------------------------------
    def _olustur_ui(self):
        kok = QWidget(); kok.setObjectName("PanelRoot")
        self.setCentralWidget(kok)
        lay = QHBoxLayout(kok)
        lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)

        self.sidebar = Sidebar("DEPO YONETIMI",
                               f"👷 {self.kullanici.kullanici_adi} • Isci")
        self.sidebar.add_nav("📦", "Urunler",          0, self._nav_goster)
        self.sidebar.add_nav("📥", "Gelen Siparisler", 1, self._nav_goster)
        self.sidebar.add_nav("☕", "Mola Durumu",      2, self._nav_goster)
        sifre_btn = QPushButton("🔑  Sifre Degistir")
        sifre_btn.setObjectName("GhostBtn")
        sifre_btn.clicked.connect(self._sifre_degistir_ac)
        self.sidebar.add_footer(sifre_btn)

        cikis = QPushButton("↩  Cikis Yap"); cikis.setObjectName("DangerBtn")
        cikis.clicked.connect(self._cikis_yap)
        self.sidebar.add_footer(cikis)
        lay.addWidget(self.sidebar)

        icerik = QWidget(); icerik.setObjectName("PanelRoot")
        il = QVBoxLayout(icerik); il.setContentsMargins(0, 0, 0, 0); il.setSpacing(0)

        top = QFrame(); top.setStyleSheet("background: transparent;")
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

        self.stack = QStackedWidget()
        il.addWidget(self.stack, 1)

        self.page_urunler = self._page_urunler()
        self.page_siparis = self._page_siparis()
        self.page_mola    = self._page_mola()
        for p in (self.page_urunler, self.page_siparis, self.page_mola):
            self.stack.addWidget(p)

        lay.addWidget(icerik, 1)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage(
            f"Giris: {self.kullanici.kullanici_adi} ({self.kullanici.rol})"
        )

        self._loader = LoadingOverlay(self)
        self._nav_goster(0)

    def _nav_goster(self, idx: int):
        self.stack.setCurrentIndex(idx)
        self.sidebar.set_active(idx)
        if idx == 0:   self._urunler_yenile()
        elif idx == 1: self._siparisler_yenile()
        elif idx == 2: self._mola_ozet_yenile()

    def _periyodik_yenile(self):
        self._mola_ozet_yenile()
        idx = self.stack.currentIndex()
        if idx == 1:
            self._siparisler_yenile()
        self._yeni_siparis_bildirim()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if hasattr(self, "_loader"):
            self._loader.setGeometry(self.rect())

    # ==================================================================
    # Sayfa 1: Urunler
    # ==================================================================
    def _page_urunler(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w); v.setContentsMargins(24, 10, 24, 24); v.setSpacing(12)

        ust = QHBoxLayout()
        t = QLabel("Urunler"); t.setObjectName("PageTitle")
        ust.addWidget(t); ust.addStretch(1)
        self.arama = QLineEdit()
        self.arama.setObjectName("SearchInput")
        self.arama.setPlaceholderText("🔍  Urun ara…")
        self.arama.setFixedWidth(280)
        self.arama.textChanged.connect(self._urunler_yenile)
        ust.addWidget(self.arama)
        v.addLayout(ust)

        self.tablo = QTableWidget()
        self.tablo.setColumnCount(5)
        self.tablo.setHorizontalHeaderLabels(
            ["ID", "Ad", "Stok", "Fiyat (TL)", "Lokasyon"]
        )
        self.tablo.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self.tablo.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tablo.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.tablo.setSortingEnabled(True)
        self.tablo.setAlternatingRowColors(True)
        v.addWidget(self.tablo, 1)

        form = QFrame(); form.setObjectName("Card")
        fl = QHBoxLayout(form)
        fl.setContentsMargins(16, 12, 16, 12); fl.setSpacing(10)
        self.miktar = QSpinBox(); self.miktar.setRange(1, 10_000); self.miktar.setValue(1)
        b_giris = QPushButton("+  Urun Girisi"); b_giris.setObjectName("SuccessBtn")
        b_cikis = QPushButton("-  Urun Cikisi"); b_cikis.setObjectName("WarnBtn")
        b_giris.clicked.connect(lambda: self._hareket(+1))
        b_cikis.clicked.connect(lambda: self._hareket(-1))
        fl.addWidget(QLabel("Miktar:")); fl.addWidget(self.miktar)
        fl.addSpacing(8); fl.addWidget(b_giris); fl.addWidget(b_cikis)
        fl.addStretch(1)
        self.lbl_bugun = QLabel("Bugunku islem sayiniz: -")
        self.lbl_bugun.setStyleSheet("color:#0f172a;")
        fl.addWidget(self.lbl_bugun)
        v.addWidget(form)
        return w

    def _secili_id(self) -> int | None:
        r = self.tablo.currentRow()
        if r < 0:
            return None
        it = self.tablo.item(r, 0)
        return int(it.text()) if it else None

    def _urunler_yenile(self):
        self.tablo.setSortingEnabled(False)
        q = self.arama.text().strip() if hasattr(self, "arama") else ""
        urunler = DepoController.ara(q) if q else DepoController.urunleri_getir()
        # Isci icin varsayilan siralama: lokasyona gore (toplama rotasi)
        if not q:
            urunler = sorted(urunler, key=lambda u: u.lokasyon_key())
        self.tablo.setRowCount(len(urunler))
        for i, u in enumerate(urunler):
            self.tablo.setItem(i, 0, NumItem(u.urun_id, str(u.urun_id)))
            self.tablo.setItem(i, 1, QTableWidgetItem(u.ad))
            stok_it = NumItem(u.stok, str(u.stok))
            renk = _stok_rengi(u.stok)
            if renk is not None:
                stok_it.setForeground(QBrush(renk))
                stok_it.setToolTip(
                    "Dusuk stok" if u.stok < DUSUK_STOK_ESIK else "Stok yuksek"
                )
            self.tablo.setItem(i, 2, stok_it)
            self.tablo.setItem(i, 3, NumItem(u.fiyat, f"{u.fiyat:.2f}"))
            lok_it = QTableWidgetItem(u.lokasyon() or "—")
            lok_it.setToolTip(f"Koridor/Raf/Goz = {u.lokasyon() or '—'}")
            self.tablo.setItem(i, 4, lok_it)
        self.tablo.setSortingEnabled(True)
        self.lbl_bugun.setText(
            f"Bugunku islem sayiniz: "
            f"{DepoController.bugunku_islem_sayisi(self.kullanici.kullanici_id)}"
        )

    def _hareket(self, yon: int):
        uid = self._secili_id()
        if uid is None:
            self.toast.info("Secim", "Lutfen bir urun secin."); return
        m = self.miktar.value()
        try:
            if yon > 0:
                DepoController.stok_arttir(self.kullanici, uid, m)
                self.toast.success("Stok +", f"{m} adet eklendi.")
            else:
                DepoController.stok_azalt(self.kullanici, uid, m)
                self.toast.info("Stok -", f"{m} adet dusuldu.")
        except StokYetersizHatasi as e:
            self.toast.error("Stok Yetersiz", str(e)); return
        except Exception as e:
            self.toast.error("Hata", str(e)); return
        self._urunler_yenile()

    # ==================================================================
    # Sayfa 2: Gelen Siparisler
    # ==================================================================
    def _page_siparis(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w); v.setContentsMargins(24, 10, 24, 24); v.setSpacing(10)

        ust = QHBoxLayout()
        t = QLabel("Gelen Siparisler"); t.setObjectName("PageTitle")
        sub = QLabel("Otomatik tazeleme: 5 sn"); sub.setObjectName("PageSubtitle")
        dv = QVBoxLayout(); dv.setSpacing(2); dv.addWidget(t); dv.addWidget(sub)
        ust.addLayout(dv); ust.addStretch(1)
        btn_y = QPushButton("↻  Yenile"); btn_y.setObjectName("SecondaryBtn")
        btn_y.clicked.connect(self._siparisler_yenile)
        ust.addWidget(btn_y)
        v.addLayout(ust)

        self._kart_scroll = QScrollArea()
        self._kart_scroll.setWidgetResizable(True)
        self._kart_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._kart_host = QWidget()
        self._kart_lay = QVBoxLayout(self._kart_host)
        self._kart_lay.setContentsMargins(0, 0, 0, 0)
        self._kart_lay.setSpacing(10)
        self._kart_lay.addStretch(1)
        self._kart_scroll.setWidget(self._kart_host)
        v.addWidget(self._kart_scroll, 1)

        self._bos_lbl = EmptyState(
            "📭",
            "Gelen siparis yok",
            "Yonetici size bir siparis atadiginda burada gorunecek. "
            "Panel 5 saniyede bir tazeleniyor — yeni geldiginde bildirim de alacaksiniz.",
        )
        self._kart_lay.insertWidget(0, self._bos_lbl)
        return w

    def _siparisler_yenile(self):
        rows = DepoController.bana_atanan_siparisler(
            self.kullanici, sadece_bekleyen=True)

        for i in reversed(range(self._kart_lay.count())):
            it = self._kart_lay.itemAt(i)
            w = it.widget() if it else None
            if w is not None and w is not self._bos_lbl:
                self._kart_lay.removeWidget(w); w.deleteLater()

        if not rows:
            self._bos_lbl.setVisible(True)
            return
        self._bos_lbl.setVisible(False)

        for r in rows:
            card = OrderCard(r)
            card.set_handlers(on_open=self._hazirlama_ac)
            self._kart_lay.insertWidget(self._kart_lay.count() - 1, card)

    def _hazirlama_ac(self, siparis_id: int):
        dlg = HazirlamaDialog(
            siparis_id,
            self.kullanici,
            self.toast,
            on_state_change=self._siparisler_yenile,
            parent=self,
        )
        dlg.exec()
        # dialog kapandiktan sonra her durumda tazele
        self._siparisler_yenile()
        self._urunler_yenile()

    # ==================================================================
    # Sayfa 3: Mola (gunluk 2x15 + 1x30 duzeni + geri sayim)
    # ==================================================================
    def _page_mola(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w); v.setContentsMargins(24, 10, 24, 24); v.setSpacing(14)

        ust = QHBoxLayout()
        t = QLabel("Mola Durumu"); t.setObjectName("PageTitle")
        sub = QLabel("Gunluk hakkiniz: 2 × 15 dk  +  1 × 30 dk")
        sub.setObjectName("PageSubtitle")
        dv = QVBoxLayout(); dv.setSpacing(2); dv.addWidget(t); dv.addWidget(sub)
        ust.addLayout(dv); ust.addStretch(1)
        v.addLayout(ust)

        # --- Buyuk geri sayim karti ---
        self.sayim_card = QFrame(); self.sayim_card.setObjectName("Card")
        self.sayim_card.setProperty("accent", "indigo")
        scl = QVBoxLayout(self.sayim_card)
        scl.setContentsMargins(20, 18, 20, 18); scl.setSpacing(6)
        self.sayim_baslik = QLabel("KENDI DURUMUNUZ")
        self.sayim_baslik.setObjectName("CardLabel")
        scl.addWidget(self.sayim_baslik)
        self.sayim_lbl = QLabel("Aktif")
        self.sayim_lbl.setStyleSheet(
            "color:#0f172a; font-size:48px; font-weight:800; "
            "letter-spacing:2px; padding:4px 0;"
        )
        self.sayim_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scl.addWidget(self.sayim_lbl)
        self.sayim_alt = QLabel("Mola almak icin asagidan tipini secin.")
        self.sayim_alt.setObjectName("CardHint")
        self.sayim_alt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scl.addWidget(self.sayim_alt)
        v.addWidget(self.sayim_card)

        # --- Kapasite + hak kartlari ---
        grid = QGridLayout(); grid.setSpacing(14)
        self.k_kisa     = MetricCard("Kisa Mola (15 dk)",  "—", "☕",  "green")
        self.k_uzun     = MetricCard("Uzun Mola (30 dk)",  "—", "🍽️", "blue")
        self.k_aktif    = MetricCard("Es Zamanli Moladaki","—", "👥", "amber")
        self.k_bugun    = MetricCard("Bugunku Toplam",     "—", "📅", "violet")
        grid.addWidget(self.k_kisa,  0, 0)
        grid.addWidget(self.k_uzun,  0, 1)
        grid.addWidget(self.k_aktif, 1, 0)
        grid.addWidget(self.k_bugun, 1, 1)
        v.addLayout(grid)

        # --- Aktif mola kapasitesi bar ---
        cap_card = QFrame(); cap_card.setObjectName("Card")
        cl = QVBoxLayout(cap_card); cl.setContentsMargins(18, 12, 18, 12); cl.setSpacing(6)
        cl_lbl = QLabel("AKTIF MOLA KAPASITESI (ES ZAMANLI)")
        cl_lbl.setObjectName("CardLabel")
        cl.addWidget(cl_lbl)
        self.cap_bar = CapacityBar(3)
        cl.addWidget(self.cap_bar)
        v.addWidget(cap_card)

        # --- Butonlar ---
        btns = QHBoxLayout(); btns.setSpacing(10)
        self.b_15 = QPushButton("☕  15 dk Mola")
        self.b_15.setObjectName("SuccessBtn")
        self.b_15.setCursor(Qt.CursorShape.PointingHandCursor)
        self.b_15.clicked.connect(lambda: self._molaya_cik(15))

        self.b_30 = QPushButton("🍽️  30 dk Mola")
        self.b_30.setObjectName("ActionBtn")
        self.b_30.setCursor(Qt.CursorShape.PointingHandCursor)
        self.b_30.clicked.connect(lambda: self._molaya_cik(30))

        self.b_don = QPushButton("⏎  Erken Don")
        self.b_don.setObjectName("WarnBtn")
        self.b_don.setCursor(Qt.CursorShape.PointingHandCursor)
        self.b_don.clicked.connect(self._moladan_don)
        self.b_don.setVisible(False)

        btns.addWidget(self.b_15); btns.addWidget(self.b_30)
        btns.addWidget(self.b_don); btns.addStretch(1)
        v.addLayout(btns)
        v.addStretch(1)

        # Geri sayim timer'i — 1 saniye
        self._gerisayim_timer = QTimer(self)
        self._gerisayim_timer.setInterval(1000)
        self._gerisayim_timer.timeout.connect(self._gerisayim_tick)
        return w

    # ------------------------------------------------------------------
    def _mola_ozet_yenile(self):
        kullanici_id = self.kullanici.kullanici_id
        aktif_mola = self.mola_ctrl.aktif_mola(kullanici_id)
        molada = aktif_mola is not None
        aktif_moladaki = self.mola_ctrl.moladaki_sayi()
        kalan = self.mola_ctrl.kalan_haklar(kullanici_id)
        kullanim = self.mola_ctrl.gunluk_kullanim(kullanici_id)
        kapasite_var = self.mola_ctrl.kalan_kapasite() > 0

        # Kart degerleri
        self.k_kisa.set_value(
            f"{kalan['kisa']} / {self.mola_ctrl.GUN_MAKS_KISA}"
        )
        self.k_kisa.set_hint(f"Kullanilan: {kullanim['kisa']}")
        self.k_uzun.set_value(
            f"{kalan['uzun']} / {self.mola_ctrl.GUN_MAKS_UZUN}"
        )
        self.k_uzun.set_hint(f"Kullanilan: {kullanim['uzun']}")
        self.k_aktif.set_value(f"{aktif_moladaki} / {self.mola_ctrl.MAKS_MOLA}")
        self.k_bugun.set_value(
            f"{kullanim['toplam']} / "
            f"{self.mola_ctrl.GUN_MAKS_KISA + self.mola_ctrl.GUN_MAKS_UZUN}"
        )
        self.cap_bar.set_value(aktif_moladaki)

        # Buton gorunurluk ve durumu
        self.b_don.setVisible(molada)
        self.b_15.setVisible(not molada)
        self.b_30.setVisible(not molada)
        if not molada:
            # Kota + kapasite kontrolu
            can_kisa = kalan["kisa"] > 0 and kapasite_var
            can_uzun = kalan["uzun"] > 0 and kapasite_var
            self.b_15.setEnabled(can_kisa)
            self.b_30.setEnabled(can_uzun)
            self.b_15.setToolTip(
                "Kota doldu" if kalan["kisa"] <= 0 else
                ("Kapasite dolu (3/3)" if not kapasite_var else "")
            )
            self.b_30.setToolTip(
                "Kota doldu" if kalan["uzun"] <= 0 else
                ("Kapasite dolu (3/3)" if not kapasite_var else "")
            )

        # Buyuk sayim karti
        self._gerisayim_guncelle(aktif_mola)

    # ------------------------------------------------------------------
    def _gerisayim_guncelle(self, aktif_mola: dict | None):
        """Buyuk sayim kartini ve timer'i aktif molaya gore yonet."""
        if aktif_mola is None:
            # Molada degil
            self.sayim_card.setProperty("accent", "indigo")
            _repolish(self.sayim_card)
            self.sayim_baslik.setText("KENDI DURUMUNUZ")
            self.sayim_lbl.setText("Aktif")
            self.sayim_lbl.setStyleSheet(
                "color:#0f172a; font-size:36px; font-weight:800;"
            )
            self.sayim_alt.setText("Mola almak icin asagidan tipini secin.")
            if self._gerisayim_timer.isActive():
                self._gerisayim_timer.stop()
            return

        # Molada — geri sayim goster
        self._gerisayim_guncel_render(aktif_mola)
        if not self._gerisayim_timer.isActive():
            self._gerisayim_timer.start()

    def _gerisayim_guncel_render(self, aktif_mola: dict):
        kalan_sn = max(0, int(aktif_mola.get("kalan_saniye") or 0))
        sure_dk = int(aktif_mola.get("sure_dakika") or 15)
        dk, sn = divmod(kalan_sn, 60)
        mmss = f"{dk:02d}:{sn:02d}"

        # Renk: son 60 sn kirmizi, son 3 dk amber, digerinde yesil
        if kalan_sn <= 60:
            renk = "#ef4444"; aksent = "rose"
        elif kalan_sn <= 180:
            renk = "#f59e0b"; aksent = "amber"
        else:
            renk = "#10b981"; aksent = "green"

        self.sayim_card.setProperty("accent", aksent)
        _repolish(self.sayim_card)
        self.sayim_baslik.setText(f"MOLADA — {sure_dk} DK")
        self.sayim_lbl.setText(mmss)
        self.sayim_lbl.setStyleSheet(
            f"color:{renk}; font-size:56px; font-weight:800; "
            f"letter-spacing:6px; padding:4px 0;"
        )
        self.sayim_alt.setText(
            "Sure dolunca sistem otomatik geri alacak — "
            "dilerseniz 'Erken Don' tusu ile daha erken bitirin."
        )

    def _gerisayim_tick(self):
        kullanici_id = self.kullanici.kullanici_id
        aktif = self.mola_ctrl.aktif_mola(kullanici_id)
        if aktif is None:
            # Mola sona ermis (backend lazy expire tetikledi)
            self._gerisayim_timer.stop()
            self.toast.success(
                "Mola Sona Erdi",
                "Sure doldu — calismaya devam edebilirsiniz."
            )
            self._mola_ozet_yenile()
            return
        # Kalan saniye 0 ise bir tick bekle; backend expire etsin
        kalan_sn = max(0, int(aktif.get("kalan_saniye") or 0))
        if kalan_sn <= 0:
            # Manuel tetikle
            self.mola_ctrl.expireli_bitir()
            self._gerisayim_timer.stop()
            self.toast.success(
                "Mola Sona Erdi",
                "Sure doldu — calismaya devam edebilirsiniz."
            )
            self._mola_ozet_yenile()
            return
        self._gerisayim_guncel_render(aktif)

    # ------------------------------------------------------------------
    def _molaya_cik(self, sure_dk: int = 15):
        ok, msg = self.mola_ctrl.molaya_cik(
            self.kullanici.kullanici_id, sure_dk
        )
        (self.toast.success if ok else self.toast.warn)("Mola", msg)
        self._mola_ozet_yenile()

    def _moladan_don(self):
        ok, msg = self.mola_ctrl.moladan_don(self.kullanici.kullanici_id)
        (self.toast.success if ok else self.toast.warn)("Mola", msg)
        self._mola_ozet_yenile()

    # ==================================================================
    # Bildirim
    # ==================================================================
    def _yeni_siparis_bildirim(self):
        rows = DepoController.bana_atanan_siparisler(
            self.kullanici, sadece_bekleyen=True)
        simdiki = {int(r["id"]) for r in rows}
        acil_simdiki = {
            int(r["id"]) for r in rows
            if int(r.get("hizlandirma_istendi") or 0) == 1
        }

        # Ilk calisma: sessizce mevcut durumu kaydet
        ilk_calisma = (not self._bilinen_siparis_idler and
                       not self._bilinen_acil_idler)

        if not ilk_calisma:
            yeni = simdiki - self._bilinen_siparis_idler
            for sid in yeni:
                self.bell.push(f"Yeni siparis atandi: #{sid}")
                self.toast.info("Yeni Siparis", f"#{sid} size atandi.")

            # Hizlandirma: daha once acil olmayan ama simdi acil olanlar
            yeni_acil = acil_simdiki - self._bilinen_acil_idler
            for sid in yeni_acil:
                self.bell.push(f"⚡ Hizlandirma istendi: #{sid}")
                self.toast.warn(
                    "⚡ Hizlandirma",
                    f"#{sid} icin yonetici hizlandirma istedi."
                )

        self._bilinen_siparis_idler = simdiki
        self._bilinen_acil_idler = acil_simdiki

    # ------------------------------------------------------------------
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
