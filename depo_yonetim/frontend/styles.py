"""
frontend/styles.py
------------------
Qt stil dosyasını (`style.qss`) tek bir yerden yükler. Tüm görsellik
QSS'de; Python tarafı yalnızca dosyayı okur. `apply_app_style(app)` ile
QApplication seviyesinde uygulanır — böylece login, adminer, işçi
panelleri otomatik tema alır.
"""

from pathlib import Path

from PyQt6.QtWidgets import QApplication

_QSS_PATH = Path(__file__).with_name("style.qss")


def load_qss() -> str:
    """style.qss içeriğini döndürür. Dosya yoksa bos string döner."""
    try:
        return _QSS_PATH.read_text(encoding="utf-8")
    except OSError:
        return ""


def apply_app_style(app: QApplication) -> None:
    """QApplication'a tema uygula."""
    app.setStyleSheet(load_qss())


# Geriye dönük kullanım için (eski kodlar setStyleSheet ile cagrilabilir)
APP_QSS = load_qss()
LOGIN_QSS = APP_QSS
PANEL_QSS = APP_QSS
