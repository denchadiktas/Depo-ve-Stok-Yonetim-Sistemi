"""
frontend/login_ui.py
--------------------
Giriş ekranı. Başarılı girişte kullanıcının rolüne göre Yönetici veya
İşçi panelini açar (rol bazlı yönlendirme). Tüm görsel stiller
`style.qss` içinde tanımlıdır ve QApplication seviyesinde uygulanır.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QLabel, QLineEdit, QPushButton, QVBoxLayout, QHBoxLayout,
    QFrame, QMessageBox, QGraphicsDropShadowEffect,
)

from backend.controllers.auth_controller import AuthController
from backend.models.kullanici import Kullanici


class LoginWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("LoginRoot")
        self.setWindowTitle("Depo ve Stok Yonetim Sistemi - Giris")
        self.resize(960, 640)
        self._kart_ref = None
        self._olustur_ui()

    # ------------------------------------------------------------------
    def _olustur_ui(self):
        outer = QHBoxLayout(self)
        outer.setContentsMargins(40, 40, 40, 40)

        card = QFrame()
        card.setObjectName("LoginCard")
        card.setFixedWidth(440)
        card.setMinimumHeight(520)

        golge = QGraphicsDropShadowEffect(self)
        golge.setBlurRadius(48)
        golge.setOffset(0, 12)
        golge.setColor(QColor(0, 0, 0, 110))
        card.setGraphicsEffect(golge)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(40, 40, 40, 40)
        lay.setSpacing(14)

        logo = QLabel("📦")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setStyleSheet("font-size: 40px;")

        baslik = QLabel("Depo ve Stok Yonetimi")
        baslik.setObjectName("Title")
        baslik.setAlignment(Qt.AlignmentFlag.AlignCenter)

        altyazi = QLabel("Devam etmek icin giris yapiniz")
        altyazi.setObjectName("Subtitle")
        altyazi.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.input_kullanici = QLineEdit()
        self.input_kullanici.setObjectName("LoginInput")
        self.input_kullanici.setPlaceholderText("Kullanici adi")

        self.input_sifre = QLineEdit()
        self.input_sifre.setObjectName("LoginInput")
        self.input_sifre.setPlaceholderText("Sifre")
        self.input_sifre.setEchoMode(QLineEdit.EchoMode.Password)

        btn = QPushButton("Giris Yap")
        btn.setObjectName("Primary")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(self._giris_yap)
        self.input_sifre.returnPressed.connect(self._giris_yap)

        ipucu = QLabel("admin / admin123    •    isci1..isci15 / 1234")
        ipucu.setObjectName("Hint")
        ipucu.setAlignment(Qt.AlignmentFlag.AlignCenter)

        lay.addStretch(1)
        lay.addWidget(logo)
        lay.addWidget(baslik)
        lay.addWidget(altyazi)
        lay.addSpacing(14)
        lay.addWidget(self.input_kullanici)
        lay.addWidget(self.input_sifre)
        lay.addWidget(btn)
        lay.addStretch(1)
        lay.addWidget(ipucu)

        outer.addStretch(1)
        outer.addWidget(card)
        outer.addStretch(1)

    # ------------------------------------------------------------------
    def _giris_yap(self):
        k = self.input_kullanici.text().strip()
        s = self.input_sifre.text()
        kullanici = AuthController.giris_yap(k, s)
        if kullanici is None:
            QMessageBox.warning(self, "Giris Basarisiz",
                                "Kullanici adi veya sifre hatali.")
            return

        if kullanici.rol == Kullanici.ROL_YONETICI:
            from .admin_panel_ui import AdminPanel
            panel = AdminPanel(kullanici)
        else:
            from .isci_panel_ui import IsciPanel
            panel = IsciPanel(kullanici)

        self._kart_ref = panel
        panel.show()
        self.close()
