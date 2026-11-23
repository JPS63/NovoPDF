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

"""Barra de pestañas de documentos que se pueden sacar a otra ventana (como en Acrobat).

- Arrastrar una pestaña dentro de la barra: cambia el orden.
- Arrastrarla fuera de la barra y soltarla fuera de NovoPDF: el documento pasa a una
  ventana nueva en ese sitio.
- Soltarla sobre otra ventana de NovoPDF: el documento pasa a esa ventana.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QMimeData, QPoint, Qt, Signal
from PySide6.QtGui import QCursor, QDrag, QMouseEvent
from PySide6.QtWidgets import QTabBar

MIME = "application/x-novopdf-tab"


class DragState:
    """Pestaña que se está arrastrando (solo dentro de este proceso)."""
    window = None          # ventana de origen
    doc = None             # DocTab arrastrado
    dropped = False        # True si otra ventana (o la misma barra) la ha recogido


class DocTabBar(QTabBar):
    detachRequested = Signal(object, QPoint)     # DocTab, posición global donde se soltó
    menuRequested = Signal(int, QPoint)          # índice, posición global
    DETACH_MARGIN = 28                           # píxeles fuera de la barra para empezar a sacarla

    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self._press = None
        self._index = -1
        self.setAcceptDrops(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(
            lambda pos: self.tabAt(pos) >= 0 and self.menuRequested.emit(self.tabAt(pos), self.mapToGlobal(pos)))

    # ------------------------------------------------------------------ arrastrar hacia fuera
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press = e.position().toPoint()
            self._index = self.tabAt(self._press)
        elif e.button() == Qt.MiddleButton and self.tabAt(e.position().toPoint()) >= 0:
            self.tabCloseRequested.emit(self.tabAt(e.position().toPoint()))
            return
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        self._press = None
        self._index = -1
        super().mouseReleaseEvent(e)

    def outside(self, pos: QPoint) -> bool:
        m = self.DETACH_MARGIN
        return not self.rect().adjusted(-m, -m, m, m).contains(pos)

    def mouseMoveEvent(self, e):
        if self._press is not None and self._index >= 0 and (e.buttons() & Qt.LeftButton) \
                and self.outside(e.position().toPoint()):
            k = self._index
            self._press, self._index = None, -1
            # terminar el arrastre interno de QTabBar (reordenar) antes de sacar la pestaña
            rel = QMouseEvent(QEvent.MouseButtonRelease, e.position(), e.globalPosition(),
                              Qt.LeftButton, Qt.NoButton, Qt.NoModifier)
            super().mouseReleaseEvent(rel)
            self.start_drag(k)
            return
        super().mouseMoveEvent(e)

    def start_drag(self, k: int):
        if not (0 <= k < len(self.owner.docs)):
            return
        doc = self.owner.docs[k]
        DragState.window, DragState.doc, DragState.dropped = self.owner, doc, False
        drag = QDrag(self)
        md = QMimeData()
        md.setData(MIME, str(id(doc)).encode())
        drag.setMimeData(md)
        pm = self.grab(self.tabRect(k))
        drag.setPixmap(pm)
        drag.setHotSpot(QPoint(pm.width() // 2, pm.height() // 2))
        try:
            drag.exec(Qt.MoveAction)
        finally:
            dropped = DragState.dropped
            DragState.window, DragState.doc, DragState.dropped = None, None, False
        if not dropped:
            self.detachRequested.emit(doc, QCursor.pos())

    # ------------------------------------------------------------------ recibir pestañas
    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(MIME) and DragState.doc is not None:
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if e.mimeData().hasFormat(MIME):
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):
        if not e.mimeData().hasFormat(MIME) or DragState.doc is None:
            return super().dropEvent(e)
        at = self.tabAt(e.position().toPoint())
        receive_tab(self.owner, at if at >= 0 else None, on_bar=True)
        e.acceptProposedAction()


def receive_tab(window, index=None, on_bar=False) -> bool:
    """La ventana recoge la pestaña que se está arrastrando. True si la ha recogido.
    Soltada en su propia barra no cambia nada; en el resto de su propia ventana se saca
    a una ventana nueva (como en Acrobat)."""
    src, doc = DragState.window, DragState.doc
    if src is None or doc is None:
        return False
    if src is window:
        if on_bar:
            DragState.dropped = True
        return on_bar
    DragState.dropped = True
    src.move_doc_to(doc, window, index)
    return True
