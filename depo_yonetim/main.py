"""
main.py
-------
Uygulamanın çalıştırma noktası. Şu sırayı izler:
  1) Veritabanını başlat (tabloları oluştur, örnek veriyi yükle)
  2) PyQt6 QApplication'ı ayağa kaldır, tema QSS'ini uygula
  3) Giriş ekranını göster; rol bazlı yönlendirme LoginWindow içinde yapılır

Çalıştırma:
    python main.py

Ön koşul:
    pip install PyQt6
"""

import sys

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFont

from database.db_init import init_database
from frontend.login_ui import LoginWindow
from frontend.styles import apply_app_style


def main() -> int:
    # 1) veritabanı hazırla
    init_database()

    # 2) uygulama
    app = QApplication(sys.argv)
    app.setApplicationName("Depo ve Stok Yonetim Sistemi")

    # modern font
    app.setFont(QFont("Segoe UI", 10))

    # tema (tek stil dosyası — tüm pencerelere uygulanır)
    apply_app_style(app)

    # 3) giriş ekranı
    giris = LoginWindow()
    giris.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
