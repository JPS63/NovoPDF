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

"""Cuadro «Imprimir»: impresora, páginas, copias, ajuste a la hoja y vista previa."""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtPrintSupport import QAbstractPrintDialog, QPrintDialog, QPrinter, QPrinterInfo
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QRadioButton, QSpinBox, QToolButton,
                               QVBoxLayout, QWidget)

from ..core import printing
from ..core.export import parse_range
from . import icons, theme
from .dialogs import Dialog

COMPAT_AVAILABLE = sys.platform.startswith("win") or bool(os.environ.get("NOVOPDF_PRINT_COMPAT"))

DUPLEX = [(QPrinter.DuplexNone, "Una cara"),
          (QPrinter.DuplexLongSide, "Doble cara (giro por el borde largo)"),
          (QPrinter.DuplexShortSide, "Doble cara (giro por el borde corto)")]
COMMON_SIZES = ["A4", "A3", "A5", "Letter", "Legal"]


def _enum_int(v) -> int:
    try:
        return int(v)
    except TypeError:
        return int(v.value)


class SheetPreview(QWidget):
    """Dibuja una hoja de papel con la página colocada tal como saldrá impresa."""

    def __init__(self):
        super().__init__()
        self.setMinimumSize(250, 330)
        self.paper = (595.0, 842.0)
        self.area = (0.0, 0.0, 595.0, 842.0)
        self.placement = None
        self.image = None
        self.message = ""

    def sizeHint(self):
        return QSize(270, 360)

    def sheet_rect(self) -> tuple[QRectF, float]:
        pw, ph = self.paper
        m = 14
        s = min((self.width() - 2 * m) / pw, (self.height() - 2 * m) / ph)
        w, h = pw * s, ph * s
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h), s

    def set_sheet(self, paper, area, placement, image, message=""):
        self.paper, self.area, self.placement, self.image, self.message = paper, area, placement, image, message
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        r, s = self.sheet_rect()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 28))
        p.drawRoundedRect(r.translated(2, 3), 2, 2)
        p.setBrush(QColor("white"))
        p.setPen(QPen(QColor(theme.BORDER), 1))
        p.drawRect(r)
        ax, ay, aw, ah = self.area
        if (ax, ay, aw, ah) != (0.0, 0.0) + tuple(self.paper):
            pen = QPen(QColor("#c9cfdb"), 1, Qt.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(r.x() + ax * s, r.y() + ay * s, aw * s, ah * s))
        if self.placement is not None and self.image is not None:
            pl = self.placement
            target = QRectF(r.x() + pl.x * s, r.y() + pl.y * s, pl.w * s, pl.h * s)
            p.save()
            p.setClipRect(r)
            p.drawImage(target, self.image)
            p.restore()
            p.setPen(QPen(QColor(0, 0, 0, 30), 1))
            p.setBrush(Qt.NoBrush)
            p.drawRect(target.intersected(r))
        if self.message:
            p.setPen(QColor(theme.MUTED))
            p.drawText(r.adjusted(16, 16, -16, -16), Qt.AlignCenter | Qt.TextWordWrap, self.message)
        p.end()


class PrintDialog(Dialog):
    def __init__(self, parent, doc, name: str, current: int, selected: list[int], settings):
        super().__init__(parent, "Imprimir", "Elige la impresora y qué páginas quieres imprimir.", "printer",
                         ok_text="Imprimir", width=820)
        self.doc = doc
        self.settings = settings
        self._pc, self._cur, self._sel = doc.page_count, current, list(selected)
        self._preview_index = 0
        self._preview_cache = {}
        self._caps = {}
        self.result = None
        self.printer = QPrinter(QPrinter.HighResolution)
        self.printer.setDocName(name)
        self.printer.setFullPage(True)

        cols = QHBoxLayout()
        cols.setSpacing(18)
        left = QVBoxLayout()
        f = QFormLayout()
        f.setLabelAlignment(Qt.AlignRight)
        f.setVerticalSpacing(9)

        # --- impresora
        prow = QHBoxLayout()
        self.printer_combo = QComboBox()
        self.printer_combo.setMinimumWidth(250)
        names = QPrinterInfo.availablePrinterNames()
        default = QPrinterInfo.defaultPrinterName()
        for n in names:
            self.printer_combo.addItem(icons.icon("printer"), n + ("  (predeterminada)" if n == default else ""), n)
        self.no_printers = not names
        if self.no_printers:
            self.printer_combo.addItem("No hay ninguna impresora instalada", "")
            self.printer_combo.setEnabled(False)
        prow.addWidget(self.printer_combo, 1)
        self.more_btn = QPushButton(icons.icon("sliders"), " Ajustes…")
        self.more_btn.setToolTip("Abrir el cuadro de impresión del sistema: bandeja, calidad, grapado "
                                 "y demás opciones propias de la impresora")
        self.more_btn.setEnabled(not self.no_printers)
        self.more_btn.clicked.connect(self._system_dialog)
        prow.addWidget(self.more_btn)
        f.addRow("Impresora:", prow)
        self.printer_state = QLabel()
        self.printer_state.setObjectName("Muted")
        self.printer_state.setWordWrap(True)
        f.addRow("", self.printer_state)

        # --- páginas
        pw = QWidget()
        pl = QVBoxLayout(pw)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(4)
        self.r_all = QRadioButton(f"Todas ({self._pc})")
        self.r_cur = QRadioButton(f"Página actual ({current + 1})")
        self.r_sel = QRadioButton(f"Seleccionadas en el panel ({len(self._sel)})")
        self.r_sel.setEnabled(len(self._sel) > 1)
        rr = QHBoxLayout()
        self.r_rng = QRadioButton("Intervalo:")
        self.rng = QLineEdit()
        self.rng.setPlaceholderText("p. ej. 1-3, 5, 8")
        self.rng.textEdited.connect(lambda _: self.r_rng.setChecked(True))
        rr.addWidget(self.r_rng)
        rr.addWidget(self.rng, 1)
        (self.r_sel if len(self._sel) > 1 else self.r_all).setChecked(True)
        for r in (self.r_all, self.r_cur, self.r_sel):
            pl.addWidget(r)
        pl.addLayout(rr)
        self.subset = QComboBox()
        for k, lab in printing.SUBSETS:
            self.subset.addItem(lab, k)
        pl.addWidget(self.subset)
        f.addRow("Páginas:", pw)

        # --- copias
        crow = QHBoxLayout()
        self.copies = QSpinBox()
        self.copies.setRange(1, 999)
        self.copies.setValue(1)
        self.copies.setFixedWidth(90)
        self.collate = QCheckBox("Intercalar (1, 2, 3… 1, 2, 3…)")
        self.collate.setChecked(settings.value("print/collate", "true") in (True, "true"))
        crow.addWidget(self.copies)
        crow.addWidget(self.collate)
        crow.addStretch(1)
        f.addRow("Copias:", crow)

        # --- papel, ajuste, color, doble cara
        self.paper = QComboBox()
        f.addRow("Papel:", self.paper)
        self.fit = QComboBox()
        for k, lab in printing.FIT_MODES:
            self.fit.addItem(lab, k)
        self.fit.setCurrentIndex(max(0, self.fit.findData(settings.value("print/fit", printing.FIT_SHRINK))))
        f.addRow("Tamaño:", self.fit)
        self.rotate = QCheckBox("Girar las páginas apaisadas para aprovechar la hoja")
        self.rotate.setChecked(settings.value("print/rotate", "true") in (True, "true"))
        f.addRow("", self.rotate)
        self.color = QComboBox()
        self.color.addItem("Color", "color")
        self.color.addItem("Blanco y negro (escala de grises)", "gray")
        self.color.setCurrentIndex(max(0, self.color.findData(settings.value("print/color", "color"))))
        f.addRow("Color:", self.color)
        self.duplex = QComboBox()
        for mode, lab in DUPLEX:
            self.duplex.addItem(lab, _enum_int(mode))
        f.addRow("Caras:", self.duplex)
        # Modo compatible (Windows): imprime con GDI directamente, sin Qt
        from ..core import printing_win
        self.compat = QCheckBox("Modo compatible (si la impresora saca una hoja con «PCL XL error» o no imprime)")
        self.compat.setToolTip("Envía cada página como una imagen sencilla directamente al controlador de "
                               "Windows, con la configuración predeterminada de la impresora (se aplican el "
                               "papel, el color, la doble cara y las copias de esta ventana, pero no los "
                               "«Ajustes…»). Se recuerda para cada impresora.")
        self.compat.setVisible(COMPAT_AVAILABLE and printing_win.available())
        f.addRow("", self.compat)
        # Despertar impresoras de red (Wi-Fi) que se quedan dormidas
        import sys as _sys
        self.wake = QCheckBox("Despertar la impresora si está en reposo y vigilar el trabajo")
        self.wake.setToolTip("Para impresoras Wi-Fi o de red que se duermen y no imprimen hasta apagarlas y "
                             "encenderlas: NovoPDF comprueba que contestan, las despierta, quita «sin conexión» "
                             "y reintenta el trabajo si se queda atascado.")
        self.wake.setChecked(self.settings.value("print/wake", True, type=bool))
        self.wake.setVisible(_sys.platform.startswith("win"))
        f.addRow("", self.wake)
        left.addLayout(f)
        self.summary = QLabel()
        self.summary.setObjectName("Muted")
        self.summary.setWordWrap(True)
        left.addWidget(self.summary)
        left.addStretch(1)
        cols.addLayout(left, 3)

        # --- vista previa
        right = QVBoxLayout()
        right.setSpacing(6)
        self.preview = SheetPreview()
        right.addWidget(self.preview, 1)
        nav = QHBoxLayout()
        nav.addStretch(1)
        self.prev_btn = QToolButton()
        self.prev_btn.setIcon(icons.icon("left"))
        self.prev_btn.setToolTip("Hoja anterior")
        self.prev_btn.clicked.connect(lambda: self._move_preview(-1))
        self.next_btn = QToolButton()
        self.next_btn.setIcon(icons.icon("right"))
        self.next_btn.setToolTip("Hoja siguiente")
        self.next_btn.clicked.connect(lambda: self._move_preview(1))
        self.preview_label = QLabel()
        self.preview_label.setObjectName("Muted")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumWidth(150)
        nav.addWidget(self.prev_btn)
        nav.addWidget(self.preview_label)
        nav.addWidget(self.next_btn)
        nav.addStretch(1)
        right.addLayout(nav)
        cols.addLayout(right, 2)
        self.body.addLayout(cols)

        # --- impresora inicial
        last = settings.value("print/printer", "")
        k = self.printer_combo.findData(last) if last else -1
        if k < 0:
            k = self.printer_combo.findData(default)
        self.printer_combo.setCurrentIndex(max(0, k))
        self._printer_changed(first=True)

        self.printer_combo.currentIndexChanged.connect(lambda _: self._printer_changed())
        self.paper.currentIndexChanged.connect(lambda _: self._paper_changed())
        for w in (self.fit, self.color, self.duplex, self.subset):
            w.currentIndexChanged.connect(lambda _: self._sync())
        for w in (self.r_all, self.r_cur, self.r_sel, self.r_rng, self.rotate, self.collate):
            w.toggled.connect(lambda _: self._sync(reset_preview=True))
        self.rng.textChanged.connect(lambda _: self._sync(reset_preview=True))
        self.copies.valueChanged.connect(lambda _: self._sync())
        if self.no_printers:
            self.ok_btn.setEnabled(False)
            self.show_error("No hay ninguna impresora instalada en este equipo. Añádela en la "
                            "configuración del sistema («Impresoras y escáneres») y vuelve a intentarlo.")
        self._sync(reset_preview=True)

    # ------------------------------------------------------------------ impresora
    def _printer_changed(self, first=False):
        name = self.printer_combo.currentData() or ""
        if not name:
            self.printer_state.setText("")
            self._fill_paper(None)
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            if self.printer.printerName() != name:
                self.printer.setPrinterName(name)
            info = QPrinterInfo.printerInfo(name)
            self._caps = self._read_caps(info)
        finally:
            QApplication.restoreOverrideCursor()
        state = []
        if self._caps.get("remote"):
            state.append("Impresora de red")
        if self._caps.get("location"):
            state.append(self._caps["location"])
        if self._caps.get("state") == "error":
            state.append("⚠ La impresora indica un problema (sin papel, apagada, atasco…)")
        self.printer_state.setText(" · ".join(state))
        self.printer_state.setVisible(bool(state))
        self._fill_paper(info)
        # Doble cara
        sup = self._caps.get("duplex") or []
        m = self.duplex.model()
        for i in range(self.duplex.count()):
            mode = self.duplex.itemData(i)
            ok = (mode == _enum_int(QPrinter.DuplexNone)) or not sup or mode in sup
            m.item(i).setEnabled(ok)
        want = self.settings.value("print/duplex", None)
        want = int(want) if want not in (None, "") else self._caps.get("duplex_default", _enum_int(QPrinter.DuplexNone))
        k = self.duplex.findData(want)
        if k < 0 or not m.item(k).isEnabled():
            k = 0
        self.duplex.setCurrentIndex(k)
        self.duplex.setEnabled(any(m.item(i).isEnabled() for i in range(1, self.duplex.count())))
        # Color
        only_gray = self._caps.get("only_gray", False)
        if only_gray:
            self.color.setCurrentIndex(1)
        self.color.setEnabled(not only_gray)
        self.compat.setChecked(self.settings.value(self._compat_key(name), "false") in (True, "true"))
        if not first:
            self._sync(reset_preview=True)

    @staticmethod
    def _compat_key(name: str) -> str:
        import hashlib
        return "print/compat_" + hashlib.sha1(name.encode("utf-8")).hexdigest()[:12]

    @staticmethod
    def _read_caps(info: QPrinterInfo) -> dict:
        caps = {}
        if info.isNull():
            return caps
        try:
            caps["remote"] = info.isRemote()
            caps["location"] = info.location()
            caps["state"] = "error" if info.state() == QPrinter.Error else ""
        except Exception:
            pass
        try:
            caps["duplex"] = [_enum_int(d) for d in info.supportedDuplexModes()]
            caps["duplex_default"] = _enum_int(info.defaultDuplexMode())
        except Exception:
            caps["duplex"] = []
        try:
            modes = [_enum_int(c) for c in info.supportedColorModes()]
            caps["only_gray"] = bool(modes) and _enum_int(QPrinter.Color) not in modes
        except Exception:
            caps["only_gray"] = False
        return caps

    def _fill_paper(self, info):
        from PySide6.QtGui import QPageSize
        self.paper.blockSignals(True)
        self.paper.clear()
        self._sizes = []
        sizes = []
        default = None
        if info is not None:
            try:
                sizes = list(info.supportedPageSizes())
                default = info.defaultPageSize()
            except Exception:
                sizes = []
        if not sizes:
            sizes = [QPageSize(getattr(QPageSize, n)) for n in COMMON_SIZES]
        seen = set()
        for ps in sizes:
            if not ps.isValid():
                continue
            key = (ps.name(), round(ps.sizePoints().width()), round(ps.sizePoints().height()))
            if key in seen:
                continue
            seen.add(key)
            self._sizes.append(ps)
            sp = ps.size(QPageSize.Millimeter)
            self.paper.addItem(f"{ps.name()}  ({sp.width():.0f} × {sp.height():.0f} mm)")
        k = -1
        cur = self.printer.pageLayout().pageSize()
        for want in (default, cur):
            if want is None or not want.isValid():
                continue
            for i, ps in enumerate(self._sizes):
                if ps.isEquivalentTo(want):
                    k = i
                    break
            if k >= 0:
                break
        if k < 0:
            k = next((i for i, ps in enumerate(self._sizes) if ps.id() == QPageSize.A4), 0)
        self.paper.setCurrentIndex(k)
        self.paper.blockSignals(False)
        self._apply_paper()

    def _apply_paper(self):
        from PySide6.QtGui import QPageLayout
        i = self.paper.currentIndex()
        if 0 <= i < len(self._sizes):
            ps = self._sizes[i]
            if not self.printer.pageLayout().pageSize().isEquivalentTo(ps):
                self.printer.setPageSize(ps)
        if self.printer.pageLayout().orientation() != QPageLayout.Portrait:
            self.printer.setPageOrientation(QPageLayout.Portrait)

    def _paper_changed(self):
        self._apply_paper()
        self._sync(reset_preview=True)

    def _system_dialog(self):
        """Cuadro de impresión del sistema (bandejas, calidad, opciones del controlador)."""
        self._apply_to_printer()
        try:
            pages = self._selected_pages()
        except ValueError:
            pages = list(range(self._pc))
        self.printer.setCopyCount(self.copies.value())
        self.printer.setCollateCopies(self.collate.isChecked())
        self.printer.setFromTo(0, 0)
        if self.r_cur.isChecked():
            self.printer.setPrintRange(QPrinter.CurrentPage)
        elif self.r_sel.isChecked():
            self.printer.setPrintRange(QPrinter.Selection)
        elif self.r_rng.isChecked() and pages == list(range(min(pages), max(pages) + 1)):
            self.printer.setPrintRange(QPrinter.PageRange)
            self.printer.setFromTo(min(pages) + 1, max(pages) + 1)
        else:
            self.printer.setPrintRange(QPrinter.AllPages)
        d = QPrintDialog(self.printer, self)
        d.setWindowTitle("Imprimir")
        d.setMinMax(1, self._pc)
        d.setOption(QAbstractPrintDialog.PrintToFile, False)
        d.setOption(QAbstractPrintDialog.PrintPageRange, True)
        d.setOption(QAbstractPrintDialog.PrintCurrentPage, True)
        d.setOption(QAbstractPrintDialog.PrintSelection, len(self._sel) > 1)
        d.setOption(QAbstractPrintDialog.PrintCollateCopies, True)
        if not d.exec():
            return
        # Recoger lo que se haya cambiado en el cuadro del sistema.
        name = self.printer.printerName()
        k = self.printer_combo.findData(name)
        if k >= 0 and k != self.printer_combo.currentIndex():
            self.printer_combo.blockSignals(True)
            self.printer_combo.setCurrentIndex(k)
            self.printer_combo.blockSignals(False)
            self._caps = self._read_caps(QPrinterInfo.printerInfo(name))
            self._fill_paper(QPrinterInfo.printerInfo(name))
        ps = self.printer.pageLayout().pageSize()
        for i, s in enumerate(self._sizes):
            if s.isEquivalentTo(ps):
                self.paper.blockSignals(True)
                self.paper.setCurrentIndex(i)
                self.paper.blockSignals(False)
                break
        self.copies.blockSignals(True)
        self.copies.setValue(max(1, self.printer.copyCount()))
        self.copies.blockSignals(False)
        self.collate.setChecked(self.printer.collateCopies())
        k = self.duplex.findData(_enum_int(self.printer.duplex()))
        if k >= 0:
            self.duplex.setCurrentIndex(k)
        self.color.setCurrentIndex(1 if self.printer.colorMode() == QPrinter.GrayScale else 0)
        rng = self.printer.printRange()
        if rng == QPrinter.CurrentPage:
            self.r_cur.setChecked(True)
        elif rng == QPrinter.Selection and self.r_sel.isEnabled():
            self.r_sel.setChecked(True)
        elif rng == QPrinter.PageRange and self.printer.fromPage() > 0:
            self.rng.setText(f"{self.printer.fromPage()}-{self.printer.toPage()}")
            self.r_rng.setChecked(True)
        else:
            self.r_all.setChecked(True)
        self._sync(reset_preview=True)

    def _apply_to_printer(self):
        self._apply_paper()
        mode = self.duplex.currentData()
        for d, _ in DUPLEX:
            if _enum_int(d) == mode and self.printer.duplex() != d:
                self.printer.setDuplex(d)
        cm = QPrinter.GrayScale if self.color.currentData() == "gray" else QPrinter.Color
        if self.printer.colorMode() != cm:
            self.printer.setColorMode(cm)

    # ------------------------------------------------------------------ páginas
    def _selected_pages(self) -> list[int]:
        if self.r_cur.isChecked():
            pages = [self._cur]
        elif self.r_sel.isChecked():
            pages = sorted(self._sel)
        elif self.r_rng.isChecked():
            pages = parse_range(self.rng.text(), self._pc)
        else:
            pages = list(range(self._pc))
        return printing.apply_subset(pages, self.subset.currentData())

    def _move_preview(self, d):
        self._preview_index += d
        self._sync()

    def _sync(self, reset_preview=False):
        if reset_preview:
            self._preview_index = 0
        try:
            pages = self._selected_pages()
            err = "" if pages else "No hay páginas que cumplan esa condición en el intervalo elegido."
        except ValueError as e:
            pages, err = [], str(e)
        copies = self.copies.value()
        self.collate.setEnabled(copies > 1)
        duplex = self.duplex.currentData() != _enum_int(QPrinter.DuplexNone)
        if err:
            self.summary.setText(err)
        else:
            n = len(pages) * copies
            txt = f"Se imprimirán {n} página{'s' if n != 1 else ''}"
            if copies > 1:
                txt += f" ({len(pages)} × {copies} copias)"
            if duplex and len(pages) > 1:
                hojas = ((len(pages) + 1) // 2) * copies
                txt += f" en {hojas} hoja{'s' if hojas != 1 else ''} a doble cara"
            self.summary.setText(txt + ".")
        self.ok_btn.setEnabled(bool(pages) and not self.no_printers)
        # vista previa
        paper_w, paper_h, area = printing.printable_area_points(self.printer)
        if not pages:
            self.preview.set_sheet((paper_w, paper_h), area, None, None, "Sin páginas")
            self.preview_label.setText("")
            self.prev_btn.setEnabled(False)
            self.next_btn.setEnabled(False)
            return
        self._preview_index = max(0, min(self._preview_index, len(pages) - 1))
        pno = pages[self._preview_index]
        page = self.doc[pno]
        fit = self.fit.currentData()
        pl = printing.place(page.rect.width, page.rect.height, paper_w, paper_h, area, fit,
                            self.rotate.isChecked())
        gray = self.color.currentData() == "gray"
        _, s = self.preview.sheet_rect()
        s *= max(1.0, self.devicePixelRatioF())
        key = (pno, pl.rotate, round(pl.w * s), round(pl.h * s), gray)
        img = self._preview_cache.get(key)
        if img is None:
            try:
                img = printing.render_qimage(page, max(1, round(pl.w * s)), max(1, round(pl.h * s)), pl.rotate, gray)
            except Exception:
                img = None
            if len(self._preview_cache) > 24:
                self._preview_cache.clear()
            self._preview_cache[key] = img
        note = ""
        if fit == printing.FIT_ACTUAL and (pl.w > area[2] + 0.5 or pl.h > area[3] + 0.5):
            note = "La página es más grande que la zona imprimible: se cortarán los bordes."
        self.preview.set_sheet((paper_w, paper_h), area, pl, img)
        self.preview.setToolTip(note)
        pct = round(pl.scale * 100)
        self.preview_label.setText(f"Hoja {self._preview_index + 1} de {len(pages)}\n"
                                   f"Página {pno + 1} del documento · {pct} %")
        self.prev_btn.setEnabled(self._preview_index > 0)
        self.next_btn.setEnabled(self._preview_index < len(pages) - 1)
        if note and not err:
            self.summary.setText(self.summary.text() + "\n" + note)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, "preview"):
            self._sync()

    # ------------------------------------------------------------------ aceptar
    def validate(self) -> bool:
        if self.no_printers:
            self.show_error("No hay ninguna impresora instalada.")
            return False
        try:
            pages = self._selected_pages()
        except ValueError as e:
            self.show_error(str(e))
            return False
        if not pages:
            self.show_error("No hay páginas que cumplan esa condición en el intervalo elegido.")
            return False
        self._apply_to_printer()
        s = self.settings
        s.setValue("print/printer", self.printer_combo.currentData())
        s.setValue("print/fit", self.fit.currentData())
        s.setValue("print/rotate", self.rotate.isChecked())
        s.setValue("print/color", self.color.currentData())
        s.setValue("print/duplex", self.duplex.currentData())
        s.setValue("print/collate", self.collate.isChecked())
        name = self.printer_combo.currentData() or ""
        compat = not self.compat.isHidden() and self.compat.isChecked()
        s.setValue(self._compat_key(name), compat)
        s.setValue("print/wake", self.wake.isChecked())
        dmode = self.duplex.currentData()
        duplex = "none" if dmode == _enum_int(QPrinter.DuplexNone) else \
            "short" if dmode == _enum_int(QPrinter.DuplexShortSide) else "long"
        i = self.paper.currentIndex()
        paper_id = self._sizes[i].windowsId() if 0 <= i < len(self._sizes) else 0
        self.result = dict(pages=pages, fit=self.fit.currentData(), auto_rotate=self.rotate.isChecked(),
                           gray=self.color.currentData() == "gray", copies=self.copies.value(),
                           collate=self.collate.isChecked(), compat=compat, printer=name,
                           duplex=duplex, paper_id=paper_id,
                           wake=not self.wake.isHidden() and self.wake.isChecked())
        return True
