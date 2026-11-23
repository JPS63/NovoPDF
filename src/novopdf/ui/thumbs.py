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

"""Panel de miniaturas: navegación, selección múltiple y reordenación."""
from __future__ import annotations

import pymupdf
from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QAbstractItemView, QListView, QListWidget, QListWidgetItem, QMenu

THUMB_W = 118


class ThumbList(QListWidget):
    pageClicked = Signal(int)
    reordered = Signal(list)          # nuevo orden (lista de índices originales)
    menuAction = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Thumbs")
        self.setViewMode(QListView.IconMode)
        self.setFlow(QListView.TopToBottom)
        self.setWrapping(False)
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Snap)
        self.setIconSize(QSize(THUMB_W, int(THUMB_W * 1.42)))
        self.setSpacing(4)
        self.setUniformItemSizes(False)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setFixedWidth(THUMB_W + 52)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.itemClicked.connect(lambda it: self.pageClicked.emit(self.row(it)))
        self.pdf = None
        self._queue: list[int] = []
        self._timer = QTimer(self)
        self._timer.setInterval(15)
        self._timer.timeout.connect(self._render_some)
        self._placeholder = None

    def set_document(self, pdf):
        self.pdf = pdf
        self.clear()
        self.rebuild()

    def _blank_icon(self, ratio: float) -> QIcon:
        h = int(THUMB_W * ratio)
        pm = QPixmap(THUMB_W, h)
        pm.fill(QColor("#f1f3f7"))
        return QIcon(pm)

    def rebuild(self):
        self._timer.stop()
        sel = self.selected_pages()
        self.clear()
        if not self.pdf:
            return
        n = self.pdf.page_count
        for i in range(n):
            r = self.pdf.doc[i].rect
            ratio = r.height / max(r.width, 1)
            it = QListWidgetItem(self._blank_icon(ratio), str(i + 1))
            it.setData(Qt.UserRole, i)
            it.setTextAlignment(Qt.AlignHCenter)
            it.setFlags(it.flags() | Qt.ItemIsDragEnabled)
            it.setFlags(it.flags() & ~Qt.ItemIsDropEnabled)
            self.addItem(it)
        self._queue = list(range(n))
        self._timer.start()
        for i in sel:
            if i < n:
                self.item(i).setSelected(True)

    def refresh_pages(self, pages):
        for i in pages:
            if i not in self._queue:
                self._queue.insert(0, i)
        if not self._timer.isActive():
            self._timer.start()

    def _render_some(self):
        if not self.pdf or not self._queue:
            self._timer.stop()
            return
        for _ in range(4):
            if not self._queue:
                break
            i = self._queue.pop(0)
            if i >= self.count() or i >= self.pdf.page_count:
                continue
            page = self.pdf.doc[i]
            dpr = self.devicePixelRatioF()
            z = THUMB_W * dpr / max(page.rect.width, 1)
            pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z), alpha=False)
            img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()
            pm = QPixmap.fromImage(img)
            # borde fino
            p = QPainter(pm)
            p.setPen(QPen(QColor("#d5dae4"), 2))
            p.drawRect(0, 0, pm.width() - 1, pm.height() - 1)
            p.end()
            pm.setDevicePixelRatio(dpr)
            ic = QIcon()
            ic.addPixmap(pm, QIcon.Normal)
            ic.addPixmap(pm, QIcon.Selected)
            self.item(i).setIcon(ic)

    def selected_pages(self) -> list[int]:
        return sorted(self.row(it) for it in self.selectedItems())

    def select_page(self, i: int):
        if 0 <= i < self.count():
            it = self.item(i)
            if not it.isSelected() or len(self.selectedItems()) <= 1:
                self.blockSignals(True)
                self.setCurrentItem(it)
                self.blockSignals(False)
            self.scrollToItem(it)

    def dropEvent(self, e):
        super().dropEvent(e)
        order = [self.item(k).data(Qt.UserRole) for k in range(self.count())]
        if order != list(range(len(order))):
            QTimer.singleShot(0, lambda: self.reordered.emit(order))

    def contextMenuEvent(self, e):
        if not self.pdf:
            return
        it = self.itemAt(e.pos())
        if it and not it.isSelected():
            self.clearSelection()
            it.setSelected(True)
        n = len(self.selectedItems())
        m = QMenu(self)
        plural = "s" if n > 1 else ""
        m.addAction(f"Girar a la derecha", lambda: self.menuAction.emit("rot_right"))
        m.addAction(f"Girar a la izquierda", lambda: self.menuAction.emit("rot_left"))
        m.addSeparator()
        m.addAction(f"Extraer página{plural} a un PDF nuevo…", lambda: self.menuAction.emit("extract"))
        m.addAction(f"Duplicar página{plural}", lambda: self.menuAction.emit("duplicate"))
        m.addAction("Insertar página en blanco después", lambda: self.menuAction.emit("blank"))
        m.addAction("Insertar páginas de otro archivo después…", lambda: self.menuAction.emit("insert"))
        m.addSeparator()
        m.addAction(f"Imprimir página{plural}…", lambda: self.menuAction.emit("print"))
        m.addSeparator()
        m.addAction(f"Eliminar página{plural}", lambda: self.menuAction.emit("delete"))
        m.exec(e.globalPos())
