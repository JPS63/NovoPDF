# NovoPDF - aplicación sencilla para trabajar con documentos PDF
# Copyright (C) 2026 Jesús Punzón Suero
#
# Este programa es software libre: puede redistribuirlo y/o modificarlo bajo
# los términos de la Licencia Pública General Affero de GNU publicada por la
# Free Software Foundation, ya sea la versión 3 de la Licencia o (a su
# elección) cualquier versión posterior.
#
# Este programa se distribuye con la esperanza de que sea útil, pero SIN
# NINGUNA GARANTÍA; ni siquiera la garantía implícita de COMERCIABILIDAD o
# IDONEIDAD PARA UN PROPÓSITO PARTICULAR. Consulte la Licencia Pública
# General Affero de GNU (archivo LICENSE) para más detalles.
#
# Código fuente: https://github.com/JPS63/NovoPDF
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Aspecto visual: colores y hoja de estilos."""

ACCENT = "#2f5bd8"
ACCENT_DARK = "#2447b0"
ACCENT_SOFT = "#e8eefc"
BG = "#f3f5f9"
PANEL = "#ffffff"
BORDER = "#e1e5ee"
TEXT = "#1f2430"
MUTED = "#6b7385"
SUCCESS = "#1f9d6b"
WARNING = "#c27c0e"
DANGER = "#d64545"
VIEWER_BG = "#e6e9f0"

QSS = f"""
* {{ font-size: 10pt; color: {TEXT}; }}
QMainWindow, QDialog {{ background: {BG}; }}
QWidget#Header {{ background: {PANEL}; border-bottom: 1px solid {BORDER}; }}
QLabel#AppTitle {{ font-size: 13pt; font-weight: 700; color: {TEXT}; }}
QLabel#DocTitle {{ color: {MUTED}; }}
QPushButton#TabButton {{
    border: none; border-radius: 8px; padding: 7px 16px; background: transparent;
    font-weight: 600; color: {MUTED};
}}
QPushButton#TabButton:hover {{ background: {BG}; color: {TEXT}; }}
QPushButton#TabButton:checked {{ background: {ACCENT_SOFT}; color: {ACCENT}; }}
QWidget#Ribbon {{ background: {PANEL}; border-bottom: 1px solid {BORDER}; }}
QToolButton#RibbonButton {{
    border: 1px solid transparent; border-radius: 8px; padding: 4px 6px;
    background: transparent; min-width: 74px; font-size: 9pt;
}}
QToolButton#RibbonButton:hover {{ background: {BG}; border-color: {BORDER}; }}
QToolButton#RibbonButton:pressed {{ background: {ACCENT_SOFT}; }}
QToolButton#RibbonButton:checked {{ background: {ACCENT_SOFT}; border-color: #c6d4f7; color: {ACCENT}; }}
QToolButton#RibbonButton:disabled {{ color: #b4bac8; }}
QFrame#RibbonSep {{ background: {BORDER}; border: none; min-width: 1px; max-width: 1px; margin: 8px 8px; }}
QLabel#GroupLabel {{ color: {MUTED}; font-size: 8pt; }}
QWidget#DocTabs {{ background: {BG}; border-bottom: 1px solid {BORDER}; }}
QTabBar#DocTabBar {{ background: transparent; }}
QTabBar#DocTabBar::tab {{ background: #e9edf4; color: {MUTED}; border: 1px solid {BORDER}; border-bottom: none;
    border-top-left-radius: 7px; border-top-right-radius: 7px; padding: 6px 10px 6px 12px; margin-right: 3px;
    min-width: 90px; max-width: 260px; }}
QTabBar#DocTabBar::tab:selected {{ background: {PANEL}; color: {TEXT}; font-weight: 600; border-top: 2px solid {ACCENT}; }}
QTabBar#DocTabBar::tab:hover:!selected {{ background: #f4f6fa; color: {TEXT}; }}
QToolButton#TabClose {{ border: none; border-radius: 4px; padding: 2px; margin-left: 4px; }}
QToolButton#TabClose:hover {{ background: #f6dede; }}
QToolButton#NewTab {{ border: none; border-radius: 6px; padding: 3px; }}
QToolButton#NewTab:hover {{ background: {ACCENT_SOFT}; }}
QWidget#HintBar {{ background: #fff8e6; border-bottom: 1px solid #f1e2b8; }}
QWidget#HintBar[kind="info"] {{ background: {ACCENT_SOFT}; border-bottom: 1px solid #cdd9f6; }}
QWidget#HintBar[kind="success"] {{ background: #e6f6ef; border-bottom: 1px solid #bfe6d4; }}
QWidget#HintBar[kind="warning"] {{ background: #fff4e0; border-bottom: 1px solid #f0d9a8; }}
QLabel#HintText {{ font-size: 10pt; }}
QPushButton {{
    background: {PANEL}; border: 1px solid {BORDER}; border-radius: 7px; padding: 6px 14px;
}}
QPushButton:hover {{ border-color: #c3cad8; background: #fafbfd; }}
QPushButton:pressed {{ background: {ACCENT_SOFT}; }}
QPushButton:disabled {{ color: #b4bac8; }}
QPushButton#Primary {{ background: {ACCENT}; border: 1px solid {ACCENT}; color: white; font-weight: 600; }}
QPushButton#Primary:hover {{ background: {ACCENT_DARK}; }}
QPushButton#Primary:disabled {{ background: #9fb3ea; border-color: #9fb3ea; color: white; }}
QPushButton#Link {{ border: none; background: transparent; color: {ACCENT}; padding: 2px 4px; text-align: left; }}
QPushButton#Link:hover {{ text-decoration: underline; }}
QPushButton#Small {{ padding: 3px 10px; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
    background: white; border: 1px solid {BORDER}; border-radius: 6px; padding: 5px 7px;
    selection-background-color: {ACCENT};
}}
QSpinBox QLineEdit, QDoubleSpinBox QLineEdit, QComboBox QLineEdit {{ border: none; padding: 0; background: transparent; }}
QAbstractSpinBox {{ padding-right: 18px; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ subcontrol-origin: border; width: 16px; border: none; background: transparent; }}
QAbstractSpinBox::up-button {{ subcontrol-position: top right; }}
QAbstractSpinBox::down-button {{ subcontrol-position: bottom right; }}
QAbstractSpinBox::up-arrow {{ image: url(@UP@); width: 10px; height: 10px; }}
QAbstractSpinBox::down-arrow {{ image: url(@DOWN@); width: 10px; height: 10px; }}


QComboBox {{ padding-right: 24px; }}
QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right; width: 22px; border: none; }}
QComboBox::down-arrow {{ image: url(@DOWN@); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{ background: white; border: 1px solid {BORDER}; selection-background-color: {ACCENT_SOFT}; selection-color: {TEXT}; outline: none; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{ border-color: {ACCENT}; }}
QListWidget#Thumbs {{ background: {PANEL}; border: none; border-right: 1px solid {BORDER}; outline: none; }}
QListWidget#Thumbs::item {{ border-radius: 6px; padding: 4px; margin: 2px 6px; color: {MUTED}; }}
QListWidget#Thumbs::item:selected {{ background: {ACCENT_SOFT}; color: {ACCENT}; }}
QListWidget#Thumbs::item:hover:!selected {{ background: {BG}; }}
QScrollArea#Viewer {{ background: {VIEWER_BG}; border: none; }}
QWidget#ViewerCanvas {{ background: {VIEWER_BG}; }}
QStatusBar {{ background: {PANEL}; border-top: 1px solid {BORDER}; }}
QStatusBar QLabel {{ color: {MUTED}; padding: 0 6px; }}
QToolButton#StatusButton {{ border: none; padding: 3px; border-radius: 5px; }}
QToolButton#StatusButton:hover {{ background: {BG}; }}
QWidget#Welcome {{ background: {BG}; }}
QFrame#Card {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 14px; }}
QToolButton#BigAction {{
    background: {PANEL}; border: 1px solid {BORDER}; border-radius: 12px; padding: 14px 10px;
    font-size: 10.5pt; font-weight: 600; min-width: 150px; min-height: 104px;
}}
QToolButton#BigAction:hover {{ border-color: {ACCENT}; background: #f8faff; color: {ACCENT}; }}
QLabel#WelcomeTitle {{ font-size: 22pt; font-weight: 700; }}
QLabel#WelcomeSub {{ color: {MUTED}; font-size: 11pt; }}
QLabel#SectionTitle {{ font-weight: 700; font-size: 10.5pt; }}
QLabel#Muted {{ color: {MUTED}; }}
QListWidget#Recent {{ background: transparent; border: none; outline: none; }}
QListWidget#Recent::item {{ padding: 7px 8px; border-radius: 6px; }}
QListWidget#Recent::item:hover {{ background: {ACCENT_SOFT}; }}
QListWidget {{ background: white; border: 1px solid {BORDER}; border-radius: 8px; }}
QListWidget::item {{ padding: 6px; }}
QListWidget::item:selected {{ background: {ACCENT_SOFT}; color: {TEXT}; }}
QGroupBox {{ border: 1px solid {BORDER}; border-radius: 8px; margin-top: 12px; padding: 10px 8px 8px 8px; background: white; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; font-weight: 600; }}
QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 8px; background: white; top: -1px; }}
QTabBar::tab {{ padding: 7px 14px; border: 1px solid transparent; border-bottom: none; margin-right: 2px;
               border-top-left-radius: 7px; border-top-right-radius: 7px; color: {MUTED}; }}
QTabBar::tab:selected {{ background: white; border-color: {BORDER}; color: {TEXT}; font-weight: 600; }}
QProgressBar {{ border: 1px solid {BORDER}; border-radius: 6px; background: white; text-align: center; height: 18px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 5px; }}
QMenu {{ background: white; border: 1px solid {BORDER}; padding: 4px; }}
QMenu::item {{ padding: 6px 22px 6px 10px; border-radius: 5px; }}
QMenu::item:selected {{ background: {ACCENT_SOFT}; color: {TEXT}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 6px; }}
QToolTip {{ background: {TEXT}; color: white; border: none; padding: 5px 8px; border-radius: 5px; }}
QCheckBox, QRadioButton {{ spacing: 7px; }}
QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #c3c9d6; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #a7afc0; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #c3c9d6; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
"""


def build_qss() -> str:
    """Hoja de estilos con las flechas dibujadas como SVG temporales."""
    import os
    import tempfile
    d = os.path.join(tempfile.gettempdir(), "novopdf_ui")
    os.makedirs(d, exist_ok=True)
    arrows = {"@UP@": "M6 15l6-6 6 6", "@DOWN@": "M6 9l6 6 6-6"}
    css = QSS
    for key, path in arrows.items():
        fn = os.path.join(d, key.strip("@").lower() + ".svg")
        with open(fn, "w", encoding="utf-8") as fh:
            fh.write('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
                     f'stroke="{MUTED}" stroke-width="2.4" stroke-linecap="round" '
                     f'stroke-linejoin="round"><path d="{path}"/></svg>')
        css = css.replace(key, fn.replace("\\", "/"))
    import sys
    if sys.platform == "darwin":
        # En macOS el punto tipográfico es más pequeño en pantalla: se escalan los tamaños
        import re
        css = re.sub(r"(\d+(?:\.\d+)?)pt", lambda m: f"{float(m.group(1)) * 1.3:.1f}pt", css)
    return css


def keys(text: str) -> str:
    """Adapta los atajos de teclado mostrados al usuario (⌘ en macOS)."""
    import sys
    if sys.platform != "darwin" or not text:
        return text
    for a, b in (("Ctrl+Mayús+", "⇧⌘"), ("Ctrl/Mayús", "⌘/⇧"), ("Ctrl o Mayús", "⌘ o ⇧"),
                 ("Ctrl+rueda", "⌘+rueda"), ("Ctrl+", "⌘"), ("Ctrl ", "⌘"), ("Supr ", "⌫ ")):
        text = text.replace(a, b)
    return text
