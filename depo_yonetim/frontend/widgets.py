"""
frontend/widgets.py
-------------------
Paylaşılan UI bileşenleri: StatusBadge, MetricCard, Toast/ToastManager,
LoadingOverlay, CapacityBar, NotificationBell, OrderCard, SidePanel,
MiniLineChart ve tablo yardımcıları.

Tüm görsellik `frontend/style.qss` dosyasında; burada davranış ve
semantik yapı vardır. Yeni widget'lar eklerken QSS'deki objectName ve
dynamic property'lere sadık kal.
"""

from __future__ import annotations

from collections import deque
from typing import Iterable

from PyQt6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QVariantAnimation, QEasingCurve,
    QPoint, QPointF, QRect, QRectF, QEvent, QObject,
)
from PyQt6.QtGui import (
    QColor, QPainter, QPen, QBrush, QPolygonF,
)
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QProgressBar, QGraphicsDropShadowEffect, QTableWidgetItem, QMenu,
    QDialog, QLineEdit, QMessageBox,
)


# ======================================================================
# Re-polish helper
# ======================================================================
def _repolish(w: QWidget) -> None:
    """Dynamic property değişimi sonrası QSS'i yeniden uygula."""
    w.style().unpolish(w)
    w.style().polish(w)
    w.update()


def add_shadow(widget: QWidget, blur: int = 24, y: int = 6,
               alpha: int = 60) -> QGraphicsDropShadowEffect:
    """Bir widget'a yumuşak drop shadow efekti ekler."""
    eff = QGraphicsDropShadowEffect(widget)
    eff.setBlurRadius(blur)
    eff.setOffset(0, y)
    eff.setColor(QColor(0, 0, 0, alpha))
    widget.setGraphicsEffect(eff)
    return eff


# ======================================================================
# Tablo için sayısal sıralanan item
# ======================================================================
class NumItem(QTableWidgetItem):
    """Sayısal değerle sıralanan, metin biçimi ayrı olan tablo öğesi."""

    def __init__(self, value, text: str | None = None):
        super().__init__(text if text is not None else str(value))
        try:
            self._v = float(value)
        except (TypeError, ValueError):
            self._v = 0.0

    def __lt__(self, other):
        if isinstance(other, NumItem):
            return self._v < other._v
        try:
            return self._v < float(other.text())
        except Exception:
            return super().__lt__(other)


# ======================================================================
# Status Badge
# ======================================================================
class StatusBadge(QLabel):
    """Renkli pill şeklinde durum rozeti. QSS üzerinden renklenir."""

    def __init__(self, text: str = "", level: str = "info", parent=None):
        super().__init__(text, parent)
        self.setObjectName("StatusBadge")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(22)
        self.setMaximumHeight(22)
        self.set_level(level)

    def set_level(self, level: str) -> None:
        self.setProperty("level", level)
        _repolish(self)

    def apply_durum(self, durum: str) -> None:
        self.setText(durum.upper() if durum else "-")
        self.set_level(durum or "info")


# ======================================================================
# Metric Card
# ======================================================================
class MetricCard(QFrame):
    """Dashboard metric kartı. İkon + etiket + değer + opsiyonel ipucu.

    - Hover'da QSS border'ı değişir + shadow yoğunluğu artar (pop).
    - `set_value()`: yeni değer sayısal ise eski değerden yeni değere
      QVariantAnimation ile yumuşak sayac animasyonu yapar. Format
      (ondalik / binlik ayrac) korunur. Sayisal degilse direkt set.
    """

    ANIM_MS = 500

    def __init__(self, baslik: str, deger: str = "-",
                 emoji: str = "•", accent: str = "indigo",
                 ipucu: str = ""):
        super().__init__()
        self.setObjectName("Card")
        self.setProperty("accent", accent)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._shadow = add_shadow(self, blur=24, y=6, alpha=50)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(6)

        ust = QHBoxLayout()
        self._lbl = QLabel(baslik); self._lbl.setObjectName("CardLabel")
        self._ic = QLabel(emoji);   self._ic.setObjectName("CardIcon")
        ust.addWidget(self._lbl, 1)
        ust.addWidget(self._ic, 0, Qt.AlignmentFlag.AlignRight)
        lay.addLayout(ust)

        self._val = QLabel(deger); self._val.setObjectName("CardValue")
        lay.addWidget(self._val)

        self._hint = QLabel(ipucu); self._hint.setObjectName("CardHint")
        self._hint.setVisible(bool(ipucu))
        lay.addWidget(self._hint)

        # Animasyon altyapisi
        self._anim: QPropertyAnimation | None = None
        self._anim_eski = 0.0

    # ------------------------------------------------------------------
    @staticmethod
    def _parse_num(s: str) -> float | None:
        """Basit numerik parse: "1,234.56" → 1234.56. Parse edilemezse
        None dondurur (ornegin "2 / 3" gibi bilesik degerler)."""
        if not s:
            return None
        t = str(s).strip()
        if not t or t == "—" or t == "-":
            return None
        # "2 / 3" gibi durumlari animate etme
        if any(ch in t for ch in (" ", "/", ":", "—")):
            return None
        # 1,234.56 -> 1234.56; "45%" -> 45
        t2 = t.replace(",", "").rstrip("%").strip()
        try:
            return float(t2)
        except ValueError:
            return None

    def _bicim(self, x: float, hedef_str: str) -> str:
        """Hedef metnin bicimini koruyarak bir sayi formatla."""
        ond = "." in hedef_str
        ayrac = "," in hedef_str
        if ond:
            # Ondalik basamak sayisini hedef stringden al
            bas = hedef_str.split(".")[-1]
            n_ond = len(bas.rstrip("%").strip())
            if ayrac:
                return f"{x:,.{n_ond}f}"
            return f"{x:.{n_ond}f}"
        # Integer
        if ayrac:
            return f"{int(round(x)):,}"
        return f"{int(round(x))}"

    def set_value(self, v: str) -> None:
        yeni_str = str(v)
        yeni_num = self._parse_num(yeni_str)
        eski_num = self._parse_num(self._val.text())

        # Numerik degil -> direkt set, animasyon yok
        if yeni_num is None or eski_num is None:
            if self._anim is not None:
                self._anim.stop()
                self._anim = None
            self._val.setText(yeni_str)
            return

        # Ayni deger -> kalirsin
        if abs(yeni_num - eski_num) < 1e-9:
            self._val.setText(yeni_str)
            return

        # Animasyon baslat — QVariantAnimation (Q_PROPERTY gerektirmez)
        if self._anim is not None:
            self._anim.stop()
        anim = QVariantAnimation(self)
        anim.setDuration(self.ANIM_MS)
        anim.setStartValue(float(eski_num))
        anim.setEndValue(float(yeni_num))
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.valueChanged.connect(
            lambda x, h=yeni_str: self._val.setText(self._bicim(float(x), h))
        )
        anim.finished.connect(lambda h=yeni_str: self._val.setText(h))
        anim.start()
        self._anim = anim

    def set_hint(self, v: str) -> None:
        self._hint.setText(v)
        self._hint.setVisible(bool(v))

    def enterEvent(self, ev):
        self._shadow.setBlurRadius(32)
        self._shadow.setOffset(0, 10)
        self._shadow.setColor(QColor(99, 102, 241, 80))
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        self._shadow.setBlurRadius(24)
        self._shadow.setOffset(0, 6)
        self._shadow.setColor(QColor(0, 0, 0, 50))
        super().leaveEvent(ev)


# ======================================================================
# Toast sistemi
# ======================================================================
class _Toast(QFrame):
    ICONS = {"success": "✓", "error": "✕", "info": "ⓘ", "warn": "!"}

    def __init__(self, parent: QWidget, title: str, message: str,
                 kind: str = "info"):
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setProperty("kind", kind if kind in self.ICONS else "info")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumWidth(320)
        self.setMaximumWidth(420)

        add_shadow(self, blur=30, y=10, alpha=140)

        h = QHBoxLayout(self)
        h.setContentsMargins(14, 12, 14, 12)
        h.setSpacing(12)

        ic = QLabel(self.ICONS.get(kind, "ⓘ"))
        ic.setObjectName("ToastIcon")
        ic.setFixedWidth(28)
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h.addWidget(ic)

        metin = QVBoxLayout(); metin.setSpacing(2)
        t = QLabel(title); t.setObjectName("ToastTitle")
        m = QLabel(message); m.setObjectName("ToastMessage")
        m.setWordWrap(True)
        metin.addWidget(t)
        metin.addWidget(m)
        h.addLayout(metin, 1)

        self.adjustSize()


class ToastManager:
    """Bir üst pencereye (panel) bağlı toast kuyruğunu yönetir.

    Kullanım:
        self.toast = ToastManager(self)
        self.toast.success("Basarili", "Siparis tamamlandi")
    """

    MARGIN = 18
    GAP = 10
    DURATION = 3500  # ms

    def __init__(self, host: QWidget):
        self._host = host
        self._items: list[tuple[_Toast, QTimer]] = []
        # host resize olunca toastları yeniden hizala
        self._filter = _ToastHostFilter(self, host)
        host.installEventFilter(self._filter)

    # -- API --
    def success(self, title: str, message: str = "") -> None:
        self._push(title, message, "success")

    def error(self, title: str, message: str = "") -> None:
        self._push(title, message, "error")

    def info(self, title: str, message: str = "") -> None:
        self._push(title, message, "info")

    def warn(self, title: str, message: str = "") -> None:
        self._push(title, message, "warn")

    # -- internals --
    def _push(self, title: str, message: str, kind: str) -> None:
        toast = _Toast(self._host, title, message, kind)
        toast.show()
        timer = QTimer(self._host)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda t=toast: self._remove(t))
        timer.start(self.DURATION)
        self._items.append((toast, timer))
        self._yerlestir()

    def _remove(self, toast: _Toast) -> None:
        for i, (t, timer) in enumerate(self._items):
            if t is toast:
                timer.stop()
                t.hide()
                t.deleteLater()
                self._items.pop(i)
                break
        self._yerlestir()

    def _yerlestir(self) -> None:
        if not self._items:
            return
        host_rect = self._host.rect()
        # alt-sağdan başla, yukarı doğru yığ
        y = host_rect.height() - self.MARGIN
        for toast, _ in reversed(self._items):
            toast.adjustSize()
            x = host_rect.width() - toast.width() - self.MARGIN
            y -= toast.height()
            toast.move(x, y)
            toast.raise_()
            y -= self.GAP


class _ToastHostFilter(QObject):
    """Host widget resize olunca toastları yeniden hizalar."""

    def __init__(self, mgr: "ToastManager", parent: QObject | None = None):
        super().__init__(parent)
        self._mgr = mgr

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.Resize:
            self._mgr._yerlestir()
        return False


# ======================================================================
# Loading Overlay (spinner)
# ======================================================================
class LoadingOverlay(QWidget):
    """Ebeveynin üzerine yarı saydam bir perde + dönen nokta dizisi."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.hide()
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)

    def _tick(self):
        self._angle = (self._angle + 18) % 360
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(8, 14, 32, 160))
        cx = self.width() / 2
        cy = self.height() / 2
        p.translate(cx, cy)
        p.rotate(self._angle)
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(10):
            alpha = max(40, 255 - i * 22)
            p.setBrush(QBrush(QColor(99, 102, 241, alpha)))
            p.drawRoundedRect(QRect(18, -3, 12, 6), 3, 3)
            p.rotate(36)

    def start(self):
        if self.parent():
            self.setGeometry(self.parent().rect())
        self.raise_()
        self.show()
        self._timer.start()

    def stop(self):
        self._timer.stop()
        self.hide()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)


# ======================================================================
# Capacity bar (mola 0/3 vs)
# ======================================================================
class CapacityBar(QWidget):
    """Renk seviyeli kapasite göstergesi (progress bar + metin)."""

    def __init__(self, max_value: int = 3, parent=None):
        super().__init__(parent)
        self._max = max(1, int(max_value))
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)

        ust = QHBoxLayout()
        self._lbl = QLabel("0 / " + str(self._max))
        self._lbl.setStyleSheet("color:#e2e8f0; font-weight:700;")
        ust.addWidget(self._lbl)
        ust.addStretch(1)
        self._dur = QLabel("Bos")
        self._dur.setStyleSheet("color:#94a3b8; font-size:11px;")
        ust.addWidget(self._dur)
        v.addLayout(ust)

        self._bar = QProgressBar()
        self._bar.setMinimum(0)
        self._bar.setMaximum(self._max)
        self._bar.setValue(0)
        self._bar.setTextVisible(False)
        v.addWidget(self._bar)

    def set_value(self, value: int) -> None:
        v = max(0, min(int(value), self._max))
        self._bar.setValue(v)
        self._lbl.setText(f"{v} / {self._max}")
        oran = v / self._max
        if v >= self._max:
            level = "high"; durum = "Dolu"
        elif oran >= 0.6:
            level = "mid";  durum = "Yogun"
        elif v > 0:
            level = "low";  durum = "Uygun"
        else:
            level = "low";  durum = "Bos"
        self._bar.setProperty("level", level)
        self._dur.setText(durum)
        _repolish(self._bar)


# ======================================================================
# Notification Bell
# ======================================================================
class NotificationBell(QPushButton):
    """Sağ üstte duran bildirim zili. Numerik rozet ve dropdown menü.

    Bildirim eklemek için `push(text)` çağırın. Kullanıcı tıklayınca
    dropdown açılır ve rozet sıfırlanır."""

    def __init__(self, parent=None):
        super().__init__("🔔", parent)
        self.setObjectName("BellBtn")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._unread = 0
        self._items: deque[str] = deque(maxlen=20)
        self.clicked.connect(self._ac)
        self._refresh()

    def push(self, text: str) -> None:
        self._items.appendleft(text)
        self._unread += 1
        self._refresh()

    def _refresh(self):
        if self._unread > 0:
            self.setText(f"🔔 {self._unread}")
            self.setProperty("unread", True)
        else:
            self.setText("🔔")
            self.setProperty("unread", False)
        _repolish(self)

    def _ac(self):
        self._unread = 0
        self._refresh()
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background:#0f172a; color:#e2e8f0; border:1px solid #1e293b;"
            " border-radius:10px; padding:6px; }"
            "QMenu::item { padding:8px 16px; border-radius:8px; }"
            "QMenu::item:selected { background:#1e293b; color:white; }"
        )
        if not self._items:
            menu.addAction("Henuz bildirim yok").setEnabled(False)
        else:
            for it in self._items:
                menu.addAction(it)
        menu.exec(self.mapToGlobal(self.rect().bottomRight()) + QPoint(-240, 4))


# ======================================================================
# OrderCard (işçi kart görünümü için)
# ======================================================================
class OrderCard(QFrame):
    """Siparis özet karti — tek butonlu 'Hazirlamaya Basla'. Kalem ve
    hazirlanmis kalem sayisini progress bar ile gosterir.
    """

    def __init__(self, data: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("OrderCard")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.siparis_id = int(data["id"])
        self._on_open = None

        acil = bool(int(data.get("hizlandirma_istendi") or 0))
        if acil:
            self.setProperty("acil", True)
        add_shadow(self, blur=18, y=4, alpha=40)

        kalem = int(data.get("kalem_sayisi") or 0)
        hazir = int(data.get("hazir_sayisi") or 0)

        v = QVBoxLayout(self)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(8)

        ust = QHBoxLayout()
        sol = QVBoxLayout(); sol.setSpacing(2)
        baslik_row = QHBoxLayout(); baslik_row.setSpacing(8)
        oid = QLabel(f"Siparis #{self.siparis_id}")
        oid.setObjectName("OrderId")
        baslik_row.addWidget(oid)
        if acil:
            acil_badge = StatusBadge("⚡  HIZLANDIR", "acil")
            baslik_row.addWidget(acil_badge)
        baslik_row.addStretch(1)
        sol.addLayout(baslik_row)
        meta = QLabel(f"Olusturan: {data.get('olusturan_adi') or '-'}   •   "
                      f"{data.get('tarih') or ''}")
        meta.setObjectName("OrderMeta")
        sol.addWidget(meta)
        ust.addLayout(sol, 1)

        badge = StatusBadge()
        badge.apply_durum(str(data.get("durum", "beklemede")))
        ust.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
        v.addLayout(ust)

        # meta metrics
        bilgi = QHBoxLayout(); bilgi.setSpacing(16)
        lbl_adet = QLabel(
            f"<span style='color:#64748b;'>Adet:</span> "
            f"<span style='color:#0f172a;font-weight:700;'>"
            f"{int(data.get('toplam_adet') or 0)}</span>"
        )
        lbl_atanan = QLabel(
            f"<span style='color:#64748b;'>Atanan:</span> "
            f"<span style='color:#0f172a;font-weight:700;'>"
            f"{data.get('atanan_isci_adi') or '-'}</span>"
        )
        lbl_adet.setStyleSheet("font-size:12px;")
        lbl_atanan.setStyleSheet("font-size:12px;")
        bilgi.addWidget(lbl_adet); bilgi.addWidget(lbl_atanan)
        bilgi.addStretch(1)

        tutar = QLabel(f"{float(data.get('tutar') or 0):,.2f} TL")
        tutar.setObjectName("OrderAmount")
        bilgi.addWidget(tutar)
        v.addLayout(bilgi)

        # ilerleme (kalem hazirlama)
        if kalem > 0:
            pbar_row = QHBoxLayout(); pbar_row.setSpacing(10)
            pb = QProgressBar()
            pb.setRange(0, kalem); pb.setValue(hazir)
            pb.setTextVisible(False)
            if hazir == kalem and kalem > 0:
                pb.setProperty("level", "low")
            elif hazir > 0:
                pb.setProperty("level", "mid")
            else:
                pb.setProperty("level", "high")
            pbar_row.addWidget(pb, 1)
            ilerleme_lbl = QLabel(f"{hazir}/{kalem} hazir")
            ilerleme_lbl.setStyleSheet(
                "color:#0f172a; font-size:11px; font-weight:700;"
            )
            pbar_row.addWidget(ilerleme_lbl, 0)
            v.addLayout(pbar_row)

        # actions
        alt = QHBoxLayout(); alt.setSpacing(8)
        b_hazir = QPushButton("📋  Hazirlamaya Basla")
        b_hazir.setObjectName("ActionBtn")
        b_hazir.setCursor(Qt.CursorShape.PointingHandCursor)
        b_hazir.clicked.connect(
            lambda: self._on_open and self._on_open(self.siparis_id)
        )
        alt.addStretch(1)
        alt.addWidget(b_hazir)
        v.addLayout(alt)

    def set_handlers(self, on_open=None, **_legacy) -> None:
        """`on_open(siparis_id)` callback'i belirle. Legacy imzayla
        çagrilirsa (on_click / on_prepare), bunlarin ikisi de ayni open
        aksiyonunu acar — geri uyum icin korunur."""
        if on_open is not None:
            self._on_open = on_open
            return
        cb = _legacy.get("on_prepare") or _legacy.get("on_click")
        if cb is not None:
            self._on_open = cb

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        _repolish(self)


# ======================================================================
# Side Panel (admin sipariş detay)
# ======================================================================
class SidePanel(QFrame):
    """Sağ taraftan açılan modern detay panel. Kapat düğmesiyle gizlenir."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SidePanel")
        add_shadow(self, blur=26, y=0, alpha=70)
        self.setFixedWidth(0)   # başlangıçta kapalı (genişlik = 0)
        self._hedef = 360

        self._anim = QPropertyAnimation(self, b"minimumWidth")
        self._anim.setDuration(260)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim2 = QPropertyAnimation(self, b"maximumWidth")
        self._anim2.setDuration(260)
        self._anim2.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(16, 16, 16, 16)
        self._root.setSpacing(10)

        ust = QHBoxLayout()
        self._title = QLabel("Detay"); self._title.setObjectName("PanelTitle")
        self._close = QPushButton("✕")
        self._close.setObjectName("GhostBtn")
        self._close.setFixedSize(30, 30)
        self._close.clicked.connect(self.kapat)
        ust.addWidget(self._title, 1)
        ust.addWidget(self._close, 0, Qt.AlignmentFlag.AlignRight)
        self._root.addLayout(ust)

        self._govde = QVBoxLayout(); self._govde.setSpacing(8)
        self._root.addLayout(self._govde, 1)

    def set_title(self, t: str) -> None:
        self._title.setText(t)

    def clear_body(self) -> None:
        while self._govde.count():
            it = self._govde.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()

    def add_body(self, w: QWidget) -> None:
        self._govde.addWidget(w)

    def ac(self, width: int = 360) -> None:
        self._hedef = width
        self._anim.stop(); self._anim2.stop()
        self._anim.setStartValue(self.width())
        self._anim.setEndValue(width)
        self._anim2.setStartValue(self.width())
        self._anim2.setEndValue(width)
        self._anim.start(); self._anim2.start()

    def kapat(self) -> None:
        self._anim.stop(); self._anim2.stop()
        self._anim.setStartValue(self.width())
        self._anim.setEndValue(0)
        self._anim2.setStartValue(self.width())
        self._anim2.setEndValue(0)
        self._anim.start(); self._anim2.start()

    def acik_mi(self) -> bool:
        return self.width() > 4


# ======================================================================
# Mini Line Chart (dashboard)
# ======================================================================
class MiniLineChart(QWidget):
    """Basit line/area chart — 7 günlük sipariş sayısı için yeterli."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(160)
        self._data: list[tuple[str, float]] = []
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

    def set_data(self, data: Iterable[tuple[str, float]]) -> None:
        self._data = list(data)
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)

            rect = QRectF(self.rect().adjusted(0, 0, -1, -1))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor("#ffffff")))
            p.drawRoundedRect(rect, 12.0, 12.0)
            p.setPen(QPen(QColor("#e2e8f0"), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(rect, 12.0, 12.0)

            if not self._data:
                p.setPen(QPen(QColor("#94a3b8")))
                p.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), "Veri yok")
                return

            pad_l, pad_r, pad_t, pad_b = 36, 16, 16, 28
            cw = self.width() - pad_l - pad_r
            ch = self.height() - pad_t - pad_b
            if cw <= 0 or ch <= 0:
                return
            chart = QRectF(pad_l, pad_t, cw, ch)

            vals = [float(v) for _, v in self._data]
            vmax = max(max(vals), 1.0)
            vmin = 0.0
            vspan = max(vmax - vmin, 1e-6)

            # grid
            p.setPen(QPen(QColor("#eef2f7"), 1, Qt.PenStyle.DashLine))
            for i in range(4):
                y = chart.top() + i * chart.height() / 3.0
                p.drawLine(
                    QPointF(chart.left(), y),
                    QPointF(chart.right(), y),
                )

            # y etiketleri (üst, orta, alt)
            p.setPen(QPen(QColor("#94a3b8")))
            p.setFont(self.font())
            for i, t in enumerate([vmax, vmax / 2.0, 0.0]):
                y = chart.top() + i * chart.height() / 2.0
                p.drawText(
                    QRectF(0, y - 8, pad_l - 6, 16),
                    int(Qt.AlignmentFlag.AlignRight
                        | Qt.AlignmentFlag.AlignVCenter),
                    f"{int(round(t))}",
                )

            # veri noktalari (QPointF)
            n = len(self._data)
            step = chart.width() / max(n - 1, 1)
            pts: list[QPointF] = []
            for i, (_lbl, v) in enumerate(self._data):
                x = chart.left() + (i * step if n > 1 else chart.width() / 2.0)
                y = chart.bottom() - (float(v) - vmin) / vspan * chart.height()
                pts.append(QPointF(x, y))

            # area fill
            if len(pts) >= 2:
                area_pts = list(pts) + [
                    QPointF(pts[-1].x(), chart.bottom()),
                    QPointF(pts[0].x(),  chart.bottom()),
                ]
                area = QPolygonF(area_pts)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(99, 102, 241, 50))
                p.drawPolygon(area)

            # çizgi
            p.setPen(QPen(QColor("#6366f1"), 2.4))
            p.setBrush(Qt.BrushStyle.NoBrush)
            for i in range(len(pts) - 1):
                p.drawLine(pts[i], pts[i + 1])

            # noktalar
            p.setBrush(QBrush(QColor("#ffffff")))
            p.setPen(QPen(QColor("#6366f1"), 2))
            for pt in pts:
                p.drawEllipse(pt, 4.0, 4.0)

            # x etiketleri
            p.setPen(QPen(QColor("#64748b")))
            for i, (lbl, _) in enumerate(self._data):
                x = chart.left() + (i * step if n > 1 else chart.width() / 2.0)
                p.drawText(
                    QRectF(x - 30, chart.bottom() + 4, 60, 16),
                    int(Qt.AlignmentFlag.AlignCenter),
                    str(lbl),
                )
        finally:
            p.end()


# ======================================================================
# Mini Bar Chart (kategori/durum dagilimlari)
# ======================================================================
class MiniBarChart(QWidget):
    """Yatay etiketli bar chart — durum dagilimi vs icin uygun.

    set_data([(etiket, deger, renk_hex), ...]) ile veri gir. renk_hex
    None olabilir; default indigo kullanilir.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(160)
        self._data: list[tuple[str, float, str | None]] = []

    def set_data(self, data) -> None:
        normalized: list[tuple[str, float, str | None]] = []
        for t in data:
            lbl, val, *rest = t
            renk = rest[0] if rest else None
            normalized.append((str(lbl), float(val), renk))
        self._data = normalized
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            rect = QRectF(self.rect().adjusted(0, 0, -1, -1))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor("#ffffff")))
            p.drawRoundedRect(rect, 12.0, 12.0)
            p.setPen(QPen(QColor("#e2e8f0"), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(rect, 12.0, 12.0)

            if not self._data:
                p.setPen(QPen(QColor("#94a3b8")))
                p.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), "Veri yok")
                return

            pad_l, pad_r, pad_t, pad_b = 110, 24, 14, 14
            cw = self.width() - pad_l - pad_r
            ch = self.height() - pad_t - pad_b
            if cw <= 0 or ch <= 0:
                return

            vmax = max(max((v for _, v, _ in self._data), default=0.0), 1.0)
            n = len(self._data)
            bar_h = min(22.0, (ch - (n - 1) * 8) / n) if n > 0 else 12.0
            gap = 8.0 if n > 1 else 0
            top = pad_t + (ch - (n * bar_h + (n - 1) * gap)) / 2

            for i, (lbl, val, renk) in enumerate(self._data):
                y = top + i * (bar_h + gap)
                # etiket
                p.setPen(QPen(QColor("#334155")))
                p.drawText(
                    QRectF(8, y - 2, pad_l - 14, bar_h + 4),
                    int(Qt.AlignmentFlag.AlignRight
                        | Qt.AlignmentFlag.AlignVCenter),
                    lbl,
                )
                # track
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor("#f1f5f9"))
                p.drawRoundedRect(
                    QRectF(pad_l, y, cw, bar_h), bar_h / 2.0, bar_h / 2.0
                )
                # bar
                barw = max(4.0, cw * (val / vmax))
                p.setBrush(QColor(renk or "#6366f1"))
                p.drawRoundedRect(
                    QRectF(pad_l, y, barw, bar_h), bar_h / 2.0, bar_h / 2.0
                )
                # deger
                p.setPen(QPen(QColor("#0f172a")))
                p.drawText(
                    QRectF(pad_l + barw + 6, y - 2,
                           self.width() - (pad_l + barw + 6) - 6, bar_h + 4),
                    int(Qt.AlignmentFlag.AlignLeft
                        | Qt.AlignmentFlag.AlignVCenter),
                    f"{int(val) if val == int(val) else val}",
                )
        finally:
            p.end()


# ======================================================================
# Sidebar yardımcıları
# ======================================================================
# ======================================================================
# Empty State — bos sayfalarda gosterilen placeholder
# ======================================================================
class EmptyState(QFrame):
    """Bos liste/sayfa durumlari icin standart placeholder bileseni.

    Kullanim:
        e = EmptyState("📭", "Henuz siparis yok",
                       "Yonetici siparis olusturdugunda burada gorunecek.")
        layout.addWidget(e)

    Opsiyonel aksiyon butonu:
        e = EmptyState(..., eylem_metni="Yenile", eylem_cb=self.yenile)
    """

    def __init__(self, emoji: str, baslik: str, aciklama: str = "",
                 eylem_metni: str = "", eylem_cb=None, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("background: transparent;")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 40, 24, 40); lay.setSpacing(10)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        ic = QLabel(emoji)
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ic.setStyleSheet("font-size: 56px; opacity: 0.8;")
        lay.addWidget(ic)

        t = QLabel(baslik)
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t.setStyleSheet(
            "color:#e2e8f0; font-size:17px; font-weight:700;"
        )
        lay.addWidget(t)

        if aciklama:
            a = QLabel(aciklama)
            a.setAlignment(Qt.AlignmentFlag.AlignCenter)
            a.setWordWrap(True)
            a.setStyleSheet("color:#94a3b8; font-size:12px; max-width:420px;")
            lay.addWidget(a)

        if eylem_metni and eylem_cb is not None:
            btn_row = QHBoxLayout()
            btn_row.addStretch(1)
            b = QPushButton(eylem_metni); b.setObjectName("ActionBtn")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(eylem_cb)
            btn_row.addWidget(b)
            btn_row.addStretch(1)
            lay.addLayout(btn_row)


# ======================================================================
# Profil Avatar Butonu — top bar icin
# ======================================================================
class ProfileAvatarButton(QPushButton):
    """Top bar'da kullanicinin adi + baslangic-harfi avatar ile beraber
    gosteren butondan. Tiklandiginda parent'in saglamis oldugu menu acilir
    (kullanici handler'i set_menu_handlers ile baglar)."""

    RENK_PALET = [
        "#6366f1", "#10b981", "#f59e0b", "#ef4444", "#3b82f6",
        "#8b5cf6", "#14b8a6", "#f97316",
    ]

    def __init__(self, kullanici, parent=None):
        super().__init__(parent)
        self.kullanici = kullanici
        self.setObjectName("AvatarBtn")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setText(
            f"  {kullanici.kullanici_adi}  ▾"
        )
        self.setStyleSheet(self._uret_stil())
        self._on_sifre = None
        self._on_cikis = None
        self.clicked.connect(self._menu_ac)

    def _avatar_renk(self) -> str:
        idx = (sum(ord(c) for c in self.kullanici.kullanici_adi)
               % len(self.RENK_PALET))
        return self.RENK_PALET[idx]

    def _uret_stil(self) -> str:
        renk = self._avatar_renk()
        return (
            "QPushButton#AvatarBtn {"
            " background: #1e293b; color: #e2e8f0;"
            " border: 1px solid #334155; border-radius: 20px;"
            " padding: 6px 14px 6px 8px; font-weight: 600;"
            "}"
            "QPushButton#AvatarBtn:hover { background: #334155; }"
        )

    def set_menu_handlers(self, on_sifre=None, on_cikis=None):
        self._on_sifre = on_sifre
        self._on_cikis = on_cikis

    def _menu_ac(self):
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background:#0f172a; color:#e2e8f0;"
            " border:1px solid #1e293b; border-radius:10px; padding:6px; }"
            "QMenu::item { padding:8px 20px; border-radius:6px; }"
            "QMenu::item:selected { background:#1e293b; color:white; }"
        )
        # Profil basligi — tiklanmaz
        baslik = menu.addAction(
            f"👤 {self.kullanici.kullanici_adi} · {self.kullanici.rol}"
        )
        baslik.setEnabled(False)
        menu.addSeparator()
        act_sifre = menu.addAction("🔑  Sifre Degistir")
        menu.addSeparator()
        act_cikis = menu.addAction("↩  Cikis Yap")

        secilen = menu.exec(
            self.mapToGlobal(self.rect().bottomLeft()) + QPoint(0, 4)
        )
        if secilen == act_sifre and self._on_sifre:
            self._on_sifre()
        elif secilen == act_cikis and self._on_cikis:
            self._on_cikis()


# ======================================================================
# Sifre Degistir Dialog
# ======================================================================
class SifreDegistirDialog(QDialog):
    """Kullanicinin kendi sifresini degistirmesi icin modern dialog."""

    def __init__(self, kullanici, parent=None):
        super().__init__(parent)
        self.kullanici = kullanici
        self.setWindowTitle("Sifre Degistir")
        self.setModal(True)
        self.setFixedSize(420, 320)

        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 20); v.setSpacing(10)

        baslik = QLabel("Sifre Degistir")
        baslik.setStyleSheet(
            "color:#f8fafc; font-size:20px; font-weight:800;"
        )
        v.addWidget(baslik)

        alt = QLabel(f"Kullanici: <b>{kullanici.kullanici_adi}</b>")
        alt.setStyleSheet("color:#94a3b8; font-size:12px;")
        v.addWidget(alt)
        v.addSpacing(6)

        self.eski = QLineEdit()
        self.eski.setPlaceholderText("Mevcut sifre")
        self.eski.setEchoMode(QLineEdit.EchoMode.Password)
        v.addWidget(self.eski)

        self.yeni = QLineEdit()
        self.yeni.setPlaceholderText("Yeni sifre (en az 4 karakter)")
        self.yeni.setEchoMode(QLineEdit.EchoMode.Password)
        v.addWidget(self.yeni)

        self.yeni2 = QLineEdit()
        self.yeni2.setPlaceholderText("Yeni sifre (tekrar)")
        self.yeni2.setEchoMode(QLineEdit.EchoMode.Password)
        v.addWidget(self.yeni2)

        self.hata = QLabel("")
        self.hata.setStyleSheet(
            "color:#ef4444; font-size:12px; min-height:16px;"
        )
        v.addWidget(self.hata)

        v.addStretch(1)

        btns = QHBoxLayout()
        btns.addStretch(1)
        b_iptal = QPushButton("Iptal"); b_iptal.setObjectName("SecondaryBtn")
        b_iptal.clicked.connect(self.reject)
        btns.addWidget(b_iptal)
        self.b_tamam = QPushButton("Degistir")
        self.b_tamam.setObjectName("ActionBtn")
        self.b_tamam.clicked.connect(self._degistir)
        btns.addWidget(self.b_tamam)
        v.addLayout(btns)

        self.eski.setFocus()

    def _degistir(self):
        from backend.controllers.auth_controller import AuthController
        eski = self.eski.text()
        y1 = self.yeni.text()
        y2 = self.yeni2.text()
        if not eski or not y1:
            self.hata.setText("Tum alanlari doldurun."); return
        if y1 != y2:
            self.hata.setText("Yeni sifreler ayni degil."); return
        if len(y1) < 4:
            self.hata.setText("Yeni sifre en az 4 karakter olmalidir."); return
        ok, msg = AuthController.sifre_degistir(self.kullanici, eski, y1)
        if not ok:
            self.hata.setText(msg); return
        QMessageBox.information(self, "Basarili", msg)
        self.accept()


# ======================================================================
# Sidebar yardımcıları (devam)
# ======================================================================
class SidebarToggleButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__("☰", parent)
        self.setObjectName("SidebarToggle")
        self.setFixedSize(34, 30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)


class Sidebar(QFrame):
    """Ortak sidebar. ('Icon Name', callback) çiftleri alır ve üstte
    toggle ile 240 <-> 68 genişlikleri arası animasyonlu daralır."""

    GENIS = 244
    DAR = 68

    def __init__(self, baslik: str, alt_metin: str, parent=None):
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(self.GENIS)

        self._anim = QPropertyAnimation(self, b"minimumWidth")
        self._anim.setDuration(220)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._anim2 = QPropertyAnimation(self, b"maximumWidth")
        self._anim2.setDuration(220)
        self._anim2.setEasingCurve(QEasingCurve.Type.InOutCubic)

        self._acik = True
        self._buttons: list[QPushButton] = []

        v = QVBoxLayout(self)
        v.setContentsMargins(12, 18, 12, 18)
        v.setSpacing(4)

        ust = QHBoxLayout()
        self._baslik_lbl = QLabel(baslik)
        self._baslik_lbl.setObjectName("SidebarTitle")
        ust.addWidget(self._baslik_lbl, 1)
        self._toggle = SidebarToggleButton()
        self._toggle.clicked.connect(self.toggle)
        ust.addWidget(self._toggle, 0, Qt.AlignmentFlag.AlignRight)
        v.addLayout(ust)

        self._user_lbl = QLabel(alt_metin)
        self._user_lbl.setObjectName("SidebarUser")
        v.addWidget(self._user_lbl)
        v.addSpacing(10)

        self._nav_vbox = QVBoxLayout(); self._nav_vbox.setSpacing(4)
        v.addLayout(self._nav_vbox)
        v.addStretch(1)

        self._footer_vbox = QVBoxLayout(); self._footer_vbox.setSpacing(6)
        v.addLayout(self._footer_vbox)

    # -- items --
    def add_nav(self, icon: str, label: str, idx: int, callback) -> QPushButton:
        b = QPushButton(f"  {icon}   {label}")
        b.setObjectName("NavBtn")
        b.setCheckable(True)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.clicked.connect(lambda _=False, i=idx: callback(i))
        b.setProperty("icon", icon)
        b.setProperty("label", label)
        self._nav_vbox.addWidget(b)
        self._buttons.append(b)
        return b

    def add_footer(self, w: QWidget) -> None:
        self._footer_vbox.addWidget(w)

    def set_active(self, idx: int) -> None:
        for i, b in enumerate(self._buttons):
            b.setChecked(i == idx)

    # -- collapse --
    def toggle(self) -> None:
        hedef = self.DAR if self._acik else self.GENIS
        self._acik = not self._acik
        self._anim.stop(); self._anim2.stop()
        self._anim.setStartValue(self.width()); self._anim.setEndValue(hedef)
        self._anim2.setStartValue(self.width()); self._anim2.setEndValue(hedef)
        self._anim.start(); self._anim2.start()
        for b in self._buttons:
            ic = b.property("icon") or "•"
            lb = b.property("label") or ""
            b.setText(f"  {ic}   {lb}" if self._acik else f"  {ic}")
        self._baslik_lbl.setVisible(self._acik)
        self._user_lbl.setVisible(self._acik)
