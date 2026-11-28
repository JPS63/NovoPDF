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

"""Iconos vectoriales propios (SVG de trazo, 24x24)."""
from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_P = {
    "open": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v1"/><path d="M3 7v10a2 2 0 0 0 2 2h13.5a2 2 0 0 0 1.9-1.4L22 11H7.5a2 2 0 0 0-1.9 1.4L3 19"/>',
    "save": '<path d="M5 3h11l5 5v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/><path d="M7 3v5h8V3"/><rect x="7" y="13" width="10" height="8" rx="1"/>',
    "save_as": '<path d="M13 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v4"/><path d="M7 3v5h8V3"/><path d="M19 15v6M16 18h6"/>',
    "lock": '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/><circle cx="12" cy="16" r="1.3"/>',
    "unlock": '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 7.8-1.2"/>',
    "undo": '<path d="M9 14L4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
    "redo": '<path d="M15 14l5-5-5-5"/><path d="M20 9H9.5a5.5 5.5 0 0 0 0 11H13"/>',
    "close": '<path d="M6 6l12 12M18 6L6 18"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>',
    "file": '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/>',
    "file_plus": '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/><path d="M12 12v6M9 15h6"/>',
    "file_in": '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/><path d="M8 15h7M12 12l3 3-3 3"/>',
    "file_out": '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h4"/><path d="M14 3v6h6v3"/><path d="M14 18h8M19 15l3 3-3 3"/>',
    "trash": '<path d="M4 7h16"/><path d="M10 11v6M14 11v6"/><path d="M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12"/><path d="M9 7V4h6v3"/>',
    "copy": '<rect x="8" y="8" width="13" height="13" rx="2"/><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3"/>',
    "rot_left": '<path d="M3 4v6h6"/><path d="M3.5 15a9 9 0 1 0 2.1-9.4L3 10"/>',
    "rot_right": '<path d="M21 4v6h-6"/><path d="M20.5 15a9 9 0 1 1-2.1-9.4L21 10"/>',
    "up": '<path d="M12 19V5M5 12l7-7 7 7"/>',
    "down": '<path d="M12 5v14M19 12l-7 7-7-7"/>',
    "text_edit": '<path d="M4 7V4h12v3M10 4v16M7 20h6"/><path d="M15.5 20l1-3.5 5-5a1.4 1.4 0 0 1 2 2l-5 5z"/>',
    "text_add": '<path d="M4 7V4h12v3M10 4v16M7 20h6"/><path d="M19 13v8M15 17h8"/>',
    "image": '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="M21 16l-5-5-9 9"/>',
    "image_add": '<path d="M14 4H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><circle cx="9" cy="10" r="2"/><path d="M21 17l-4-4-8 8"/><path d="M19 2v6M16 5h6"/>',
    "eraser": '<path d="M7 21h13"/><path d="M5.5 14.5l9-9a2 2 0 0 1 2.8 0l2.2 2.2a2 2 0 0 1 0 2.8L11 19H7.5z"/><path d="M9.5 10.5l5 5"/>',
    "sign": '<path d="M3 17c3-1 4-7 6-7 2.5 0-1 8 2 8 2 0 3-4 5-4 1.5 0 1 2.5 3 2.5"/><path d="M3 21h18"/>',
    "pen": '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
    "shield": '<path d="M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6z"/><path d="M8.5 12l2.5 2.5 4.5-5"/>',
    "scan": '<path d="M3 7V5a2 2 0 0 1 2-2h2M17 3h2a2 2 0 0 1 2 2v2M21 17v2a2 2 0 0 1-2 2h-2M7 21H5a2 2 0 0 1-2-2v-2"/><path d="M7 8h10M7 12h10M7 16h6"/>',
    "zoom_in": '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4M11 8v6M8 11h6"/>',
    "zoom_out": '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4M8 11h6"/>',
    "fit": '<path d="M4 9V5a1 1 0 0 1 1-1h4M15 4h4a1 1 0 0 1 1 1v4M20 15v4a1 1 0 0 1-1 1h-4M9 20H5a1 1 0 0 1-1-1v-4"/>',
    "images": '<rect x="7" y="3" width="14" height="14" rx="2"/><path d="M3 7v12a2 2 0 0 0 2 2h12"/><circle cx="12" cy="8" r="1.5"/><path d="M21 13l-4-4-6 6"/>',
    "merge": '<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/>',
    "pages": '<rect x="7" y="3" width="13" height="16" rx="2"/><path d="M4 7v12a2 2 0 0 0 2 2h10"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 7"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.5"/>',
    "warning": '<path d="M12 3l10 18H2z"/><path d="M12 10v5M12 18v.5"/>',
    "error": '<circle cx="12" cy="12" r="9"/><path d="M9 9l6 6M15 9l-6 6"/>',
    "cursor": '<path d="M5 3l14 7-6 2-2 6z"/>',
    "home": '<path d="M3 11l9-8 9 8"/><path d="M5 10v10h14V10"/>',
    "blank": '<rect x="5" y="3" width="14" height="18" rx="2"/>',
    "eye": '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    "help": '<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.7.3-1 1-1 1.7v.5M12 17v.5"/>',
    "word_doc": '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/><path d="M8 12.5l1.3 5 1.7-4 1.7 4 1.3-5"/>',
    "sheet_doc": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18M3 14h18M9 4v16M15 4v16"/>',
    "export": '<path d="M12 3v12M7 8l5-5 5 5"/><path d="M5 14v5a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-5"/>',
    "highlighter": '<path d="M15.5 4.5l4 4L11 17H7v-4z"/><path d="M7 17l-3 3h6"/><path d="M13 7l4 4"/>',
    "underline": '<path d="M7 4v7a5 5 0 0 0 10 0V4"/><path d="M5 20h14"/>',
    "strike": '<path d="M16.5 7.5A4.5 4.5 0 0 0 12 5c-2.5 0-4.2 1.4-4.2 3.2 0 1.5 1 2.4 2.6 3"/><path d="M8 16.5c.7 1.6 2.2 2.5 4.2 2.5 2.5 0 4.3-1.4 4.3-3.3 0-.9-.3-1.6-1-2.2"/><path d="M4 12h16"/>',
    "unmark": '<path d="M15.5 4.5l4 4L11 17H7v-4z"/><path d="M7 17l-3 3h6"/><path d="M3 3l18 18"/>',
    "printer": '<path d="M7 9V3h10v6"/><path d="M7 18H5a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><rect x="7" y="14" width="10" height="7" rx="1"/><path d="M17.5 12h.01"/>',
    "sliders": '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
    "left": '<path d="M15 18l-6-6 6-6"/>',
    "right": '<path d="M9 18l6-6-6-6"/>',
    "export_img": '<path d="M13 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v7"/><circle cx="8.5" cy="8.5" r="1.8"/><path d="M21 15l-5-5L5 21"/><path d="M16 19h6M19 16l3 3-3 3"/>',
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "scanner": '<path d="M4 13h16a2 2 0 0 1 2 2v3a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-3a2 2 0 0 1 2-2z"/><path d="M3 13l2.5-8.5A2 2 0 0 1 7.4 3H18"/><path d="M6 17h4M17 17h.5"/>',
    "form": '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/><rect x="7" y="12" width="10" height="3" rx=".5"/><path d="M7 18.5h1.5M10 18.5h7"/>',
    "f_text": '<rect x="2.5" y="7" width="19" height="10" rx="1.5"/><path d="M7 10v4M5.8 10h2.4M5.8 14h2.4"/>',
    "f_check": '<rect x="4" y="4" width="16" height="16" rx="2.5"/><path d="M8 12.3l2.8 2.8L16.5 9"/>',
    "f_radio": '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3.2" fill="currentColor"/>',
    "f_combo": '<rect x="2.5" y="7" width="19" height="10" rx="1.5"/><path d="M15 7v10"/><path d="M16.8 11l1.5 1.6 1.5-1.6"/>',
    "f_list": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M7 8h10M7 12h10M7 16h6"/><rect x="5.5" y="10.4" width="13" height="3.2" rx=".6"/>',
    "f_sign": '<rect x="2.5" y="5" width="19" height="14" rx="1.5"/><path d="M5.5 14.5c1.6-.5 2.2-4 3.3-4 1.4 0-.6 4.5 1.1 4.5 1.1 0 1.7-2.2 2.8-2.2.8 0 .6 1.4 1.7 1.4"/><path d="M5 16.8h14"/>',
    "f_edit": '<rect x="3" y="3" width="13" height="9" rx="1.5" stroke-dasharray="2.5 2"/><path d="M11 10l9 3.6-3.8 1.3-1.4 3.9z"/>',
    "wand": '<path d="M4 20L15 9"/><path d="M14 4v3M17.5 5.5l-2 2M19 9h-3M17.5 12.5l-2-2M10.5 5.5l2 2"/><path d="M13.5 10.5l-2-2"/>',
    "flatten": '<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 16l9 5 9-5"/><path d="M8 13.5L12 16l4-2.5" stroke-dasharray="2 2"/>',
    "form_reset": '<rect x="2.5" y="8" width="13" height="8" rx="1.5"/><path d="M14 4.5a7.5 7.5 0 0 1 7 9"/><path d="M21.5 10.5l-.5 3-2.8-1.4"/>',
    "fields_on": '<rect x="3" y="5" width="18" height="5" rx="1" fill="currentColor" fill-opacity=".25"/><rect x="3" y="14" width="18" height="5" rx="1" fill="currentColor" fill-opacity=".25"/>',
    "comment": '<path d="M4 5h16a1.5 1.5 0 0 1 1.5 1.5v9A1.5 1.5 0 0 1 20 17h-9l-4.5 3.5V17H4a1.5 1.5 0 0 1-1.5-1.5v-9A1.5 1.5 0 0 1 4 5z"/><path d="M7 9.5h10M7 13h6"/>',
    "note": '<path d="M5 3h14a1 1 0 0 1 1 1v11l-5 5H5a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z"/><path d="M15 20v-4a1 1 0 0 1 1-1h4"/><path d="M8 8h8M8 11.5h5"/>',
    "textbox": '<rect x="3" y="4" width="18" height="16" rx="1.5" stroke-dasharray="3 2"/><path d="M8 9V8h8v1M12 8v8M10.5 16h3"/>',
    "hl_comment": '<path d="M13.5 4.5l3.5 3.5-7 7H6.5v-3.5z"/><path d="M6.5 15l-2.5 2.5h5"/><path d="M15 13h5.5a1 1 0 0 1 1 1v4a1 1 0 0 1-1 1h-2l-2 2v-2H15a1 1 0 0 1-1-1v-4a1 1 0 0 1 1-1z"/>',
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4.5 20.5c1-4 4-6 7.5-6s6.5 2 7.5 6"/>',
    "optimize": '<path d="M3 7V5a2 2 0 0 1 2-2h2M17 3h2a2 2 0 0 1 2 2v2M21 17v2a2 2 0 0 1-2 2h-2M7 21H5a2 2 0 0 1-2-2v-2"/><path d="M8 15.5l2.5-7 2.5 7M9 13.2h3"/><path d="M16.5 7.5v3M15 9h3"/><path d="M15.5 14.5l.6 1.4 1.4.6-1.4.6-.6 1.4-.6-1.4-1.4-.6 1.4-.6z"/>',
    "printer_v": '<path d="M7 9V3h10v6"/><path d="M7 18H5a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><rect x="7" y="14" width="10" height="7" rx="1"/><path d="M10 17.5h4"/>',
    "browser": '<rect x="2.5" y="4" width="19" height="16" rx="2"/><path d="M2.5 8.5h19"/><circle cx="5.5" cy="6.3" r=".5"/><circle cx="7.5" cy="6.3" r=".5"/><path d="M9 12h6M9 15.5h4"/>',
    "replace": '<rect x="3" y="3" width="8" height="8" rx="1.5"/><rect x="13" y="13" width="8" height="8" rx="1.5"/><path d="M15 4h3a2 2 0 0 1 2 2v3M17 7l3 2 2-3"/><path d="M9 20H6a2 2 0 0 1-2-2v-3M7 17l-3-2-2 3"/>',
}


def svg(name: str, color: str = "#1f2430", stroke: float = 1.8) -> bytes:
    body = _P.get(name, _P["file"]).replace("currentColor", color)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
            f'stroke="{color}" stroke-width="{stroke}" stroke-linecap="round" '
            f'stroke-linejoin="round">{body}</svg>').encode()


def pixmap(name: str, size: int = 24, color: str = "#1f2430", ratio: float = 2.0) -> QPixmap:
    r = QSvgRenderer(QByteArray(svg(name, color)))
    px = QPixmap(int(size * ratio), int(size * ratio))
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)
    r.render(p, QRectF(0, 0, size * ratio, size * ratio))
    p.end()
    px.setDevicePixelRatio(ratio)
    return px


def icon(name: str, color: str = "#2b3245", active: str = "#2f5bd8", disabled: str = "#b4bac8") -> QIcon:
    ic = QIcon()
    ic.addPixmap(pixmap(name, 24, color), QIcon.Normal, QIcon.Off)
    ic.addPixmap(pixmap(name, 24, active), QIcon.Active, QIcon.Off)
    ic.addPixmap(pixmap(name, 24, disabled), QIcon.Disabled, QIcon.Off)
    ic.addPixmap(pixmap(name, 24, active), QIcon.Normal, QIcon.On)
    ic.addPixmap(pixmap(name, 24, active), QIcon.Active, QIcon.On)
    ic.addPixmap(pixmap(name, 24, disabled), QIcon.Disabled, QIcon.On)
    return ic


def app_icon_pixmap(size: int = 256) -> QPixmap:
    """Icono de la aplicación: documento azul con una «N» y una pluma."""
    from PySide6.QtGui import QColor, QFont, QPainterPath, QPen, QBrush, QLinearGradient
    px = QPixmap(size, size)
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)
    s = size / 256.0
    # sombra suave
    path = QPainterPath()
    path.addRoundedRect(QRectF(28 * s, 14 * s, 200 * s, 228 * s), 34 * s, 34 * s)
    g = QLinearGradient(0, 0, 0, size)
    g.setColorAt(0, QColor("#3d6cf0"))
    g.setColorAt(1, QColor("#2343b5"))
    p.fillPath(path, QBrush(g))
    # esquina doblada
    fold = QPainterPath()
    fold.moveTo(170 * s, 14 * s)
    fold.lineTo(228 * s, 72 * s)
    fold.lineTo(186 * s, 72 * s)
    fold.quadTo(170 * s, 72 * s, 170 * s, 56 * s)
    fold.closeSubpath()
    p.fillPath(fold, QColor(255, 255, 255, 90))
    # letra N
    f = QFont("Segoe UI", int(118 * s))
    f.setBold(True)
    f.setPixelSize(int(130 * s))
    p.setFont(f)
    p.setPen(QColor("white"))
    p.drawText(QRectF(28 * s, 40 * s, 200 * s, 150 * s), Qt.AlignCenter, "N")
    # línea de firma
    pen = QPen(QColor("#9fe3c4"), 12 * s)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    sig = QPainterPath()
    sig.moveTo(66 * s, 200 * s)
    sig.cubicTo(96 * s, 170 * s, 110 * s, 222 * s, 140 * s, 196 * s)
    sig.cubicTo(160 * s, 180 * s, 170 * s, 206 * s, 192 * s, 192 * s)
    p.drawPath(sig)
    p.end()
    return px
