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

"""Rellenar campos de formulario directamente sobre la página.

Al hacer clic en un campo se coloca encima un control de Qt (cuadro de texto,
desplegable, lista) del mismo tamaño; al salir de él (Tab, Intro, clic fuera) el
valor se pasa al PDF. Las casillas y botones de opción cambian con un clic o con
la barra espaciadora. Tab y Mayús+Tab recorren los campos en orden de lectura.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QLineEdit, QListWidget,
                               QPlainTextEdit, QWidget)

from ..core import forms
from . import theme

EDIT_CSS = (f"border: 1.5px solid {theme.ACCENT}; background: #fffef4; color: #111;"
            "border-radius: 2px; padding: 0px 2px; selection-background-color: #b9ccff;"
            "selection-color: #111;")


def _keys(host, w, ev) -> bool:
    """Teclas comunes: Tab / Mayús+Tab (siguiente / anterior), Esc (cancelar)."""
    if ev.type() != QEvent.KeyPress:
        return False
    k = ev.key()
    if k == Qt.Key_Tab and not (ev.modifiers() & Qt.ControlModifier):
        host.move(1)
        return True
    if k == Qt.Key_Backtab:
        host.move(-1)
        return True
    if k == Qt.Key_Escape:
        host.close(commit=False)
        return True
    return False


class _Line(QLineEdit):
    def __init__(self, host, parent):
        super().__init__(parent)
        self.host = host
        self.setStyleSheet(f"QLineEdit {{ {EDIT_CSS} }}")

    def event(self, ev):
        if _keys(self.host, self, ev):
            return True
        if ev.type() == QEvent.KeyPress and ev.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.host.close(commit=True)
            return True
        return super().event(ev)

    def focusOutEvent(self, ev):
        super().focusOutEvent(ev)
        self.host.focus_lost(self)


class _Multi(QPlainTextEdit):
    def __init__(self, host, parent):
        super().__init__(parent)
        self.host = host
        self.setStyleSheet(f"QPlainTextEdit {{ {EDIT_CSS} }}")
        self.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    def event(self, ev):
        if _keys(self.host, self, ev):
            return True
        if (ev.type() == QEvent.KeyPress and ev.key() in (Qt.Key_Return, Qt.Key_Enter)
                and ev.modifiers() & Qt.ControlModifier):
            self.host.close(commit=True)
            return True
        return super().event(ev)

    def focusOutEvent(self, ev):
        super().focusOutEvent(ev)
        self.host.focus_lost(self)


class _Combo(QComboBox):
    def __init__(self, host, parent):
        super().__init__(parent)
        self.host = host
        self.setStyleSheet(f"QComboBox {{ {EDIT_CSS} }}")

    def event(self, ev):
        if _keys(self.host, self, ev):
            return True
        return super().event(ev)

    def focusOutEvent(self, ev):
        super().focusOutEvent(ev)
        if not self.view().isVisible():
            self.host.focus_lost(self)


class _List(QListWidget):
    def __init__(self, host, parent):
        super().__init__(parent)
        self.host = host
        self.setStyleSheet(f"QListWidget {{ {EDIT_CSS} }}")

    def event(self, ev):
        if _keys(self.host, self, ev):
            return True
        return super().event(ev)

    def focusOutEvent(self, ev):
        super().focusOutEvent(ev)
        self.host.focus_lost(self)


class _Box(QWidget):
    """Marco de foco para casillas y botones de opción (Espacio cambia el valor)."""

    def __init__(self, host, parent):
        super().__init__(parent)
        self.host = host
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

    def event(self, ev):
        if _keys(self.host, self, ev):
            return True
        if ev.type() == QEvent.KeyPress and ev.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            self.host.toggle()
            return True
        return super().event(ev)

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(theme.ACCENT), 1.5, Qt.DashLine))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(self.rect().adjusted(1, 1, -2, -2), 2, 2)
        p.end()

    def focusOutEvent(self, ev):
        super().focusOutEvent(ev)
        self.host.focus_lost(self)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self.host.toggle()


class FieldEditor:
    """El control que está rellenando un campo (como mucho uno a la vez)."""

    def __init__(self, viewer):
        self.viewer = viewer
        self.widget = None
        self.page = -1
        self.xref = 0
        self.field: forms.Field | None = None
        self._closing = False

    # ------------------------------------------------------------------ estado
    @property
    def active(self) -> bool:
        return self.widget is not None

    def dirty(self) -> bool:
        return self.active and self._value() != self.field.value

    def is_on(self, page, xref) -> bool:
        return self.active and self.page == page and self.xref == xref

    # ------------------------------------------------------------------ abrir y cerrar
    def open(self, f: forms.Field, focus=True, select_all=False):
        """select_all: al llegar con Tab se selecciona lo escrito (como en Acrobat);
        con un clic, el cursor va al final."""
        self.close(commit=True)
        v = self.viewer
        if f.page >= len(v.pages):
            return
        v.ensure_field_visible(f)
        pw = v.pages[f.page]
        self.page, self.xref, self.field = f.page, f.xref, f
        r = pw.to_px(f.rect).toAlignedRect()
        k = f.kind
        if k == forms.TEXT:
            if f.multiline:
                w = _Multi(self, pw)
                w.setPlainText(str(f.value or ""))
                if select_all:
                    w.selectAll()
                else:
                    w.moveCursor(w.textCursor().MoveOperation.End)
            else:
                w = _Line(self, pw)
                w.setText(str(f.value or ""))
                if f.max_len:
                    w.setMaxLength(f.max_len)
                if f.password:
                    w.setEchoMode(QLineEdit.Password)
                w.setAlignment({1: Qt.AlignHCenter, 2: Qt.AlignRight}.get(f.align, Qt.AlignLeft) | Qt.AlignVCenter)
                if select_all:
                    w.selectAll()
                else:
                    w.end(False)
            w.setFont(self._font(f))
        elif k == forms.COMBO:
            w = _Combo(self, pw)
            w.addItems(f.options)
            w.setEditable(f.editable)
            if f.value in f.options:
                w.setCurrentIndex(f.options.index(f.value))
            elif f.editable:
                w.setEditText(str(f.value or ""))
            else:
                w.setCurrentIndex(-1)
            w.setFont(self._font(f, 0.9))
            w.activated.connect(lambda _=0: QTimer.singleShot(0, lambda: self.close(commit=True)))
            r.setHeight(max(r.height(), 20))
        elif k == forms.LIST:
            w = _List(self, pw)
            w.addItems(f.options)
            w.setSelectionMode(QAbstractItemView.MultiSelection if f.multiselect else QAbstractItemView.SingleSelection)
            cur = f.value if isinstance(f.value, list) else ([f.value] if f.value else [])
            for n, o in enumerate(f.options):
                if o in cur:
                    w.item(n).setSelected(True)
            w.setFont(self._font(f, 0.9))
            if not f.multiselect:
                w.itemClicked.connect(lambda _=None: QTimer.singleShot(0, lambda: self.close(commit=True)))
        elif k in (forms.CHECK, forms.RADIO):
            w = _Box(self, pw)
            r.adjust(-3, -3, 3, 3)
        else:
            self.field = None
            return
        r.setHeight(max(r.height(), 14))
        r.setWidth(max(r.width(), 14))
        w.setGeometry(r)
        w.setToolTip(f.display_name)
        w.show()
        self.widget = w
        if focus:
            w.setFocus(Qt.MouseFocusReason)
        if k == forms.COMBO and not f.editable:
            QTimer.singleShot(0, lambda: self.widget is w and w.showPopup())
        v.update_page(f.page)

    def place(self):
        """Recoloca el control (tras un cambio de zoom)."""
        if not self.active or self.page >= len(self.viewer.pages):
            return
        f = self.viewer.field_by_xref(self.page, self.xref)
        if f is None:
            return
        pw = self.viewer.pages[self.page]
        r = pw.to_px(f.rect).toAlignedRect()
        if isinstance(self.widget, _Box):
            r.adjust(-3, -3, 3, 3)
        r.setHeight(max(r.height(), 20 if isinstance(self.widget, _Combo) else 14))
        r.setWidth(max(r.width(), 14))
        self.widget.setGeometry(r)
        if not isinstance(self.widget, _Box):
            self.widget.setFont(self._font(f, 0.9 if isinstance(self.widget, (_Combo, _List)) else 1))

    def _font(self, f: forms.Field, k=1.0) -> QFont:
        pt = f.fontsize or (min(12.0, max(7.0, f.rect.height * 0.62)) if not f.multiline else 10.0)
        font = QFont("Arial")
        font.setPixelSize(max(8, int(pt * self.viewer.scale * k)))
        return font

    def _value(self):
        w, f = self.widget, self.field
        if isinstance(w, _Line):
            return w.text()
        if isinstance(w, _Multi):
            return w.toPlainText()
        if isinstance(w, _Combo):
            if f.editable:
                return w.currentText()
            return w.currentText() if w.currentIndex() >= 0 else f.value
        if isinstance(w, _List):
            sel = [i.text() for i in w.selectedItems()]
            sel.sort(key=lambda t: f.options.index(t) if t in f.options else 0)
            return sel if f.multiselect else (sel[0] if sel else "")
        return f.value

    def close(self, commit=True):
        """Cierra el control; con commit, pasa el valor al PDF si ha cambiado."""
        if not self.active or self._closing:
            return
        self._closing = True
        w, f, page, xref = self.widget, self.field, self.page, self.xref
        value = self._value()
        self.widget = None
        self.field = None
        try:
            if w.hasFocus():
                self.viewer.setFocus(Qt.OtherFocusReason)   # antes de ocultarlo (si no, Qt pasa el foco solo)
            w.hide()
            w.deleteLater()
        except RuntimeError:
            pass
        if f.kind == forms.LIST and not f.multiselect:
            cur = f.value[0] if isinstance(f.value, list) and f.value else (f.value or "")
            changed = value != cur
        elif f.kind == forms.LIST:
            cur = f.value if isinstance(f.value, list) else ([f.value] if f.value else [])
            changed = value != cur
        else:
            changed = value != f.value
        try:
            if commit and changed:
                self.viewer.action.emit("form_value", page, (xref, value))
        finally:
            self._closing = False
        self.viewer.update_page(page)

    def discard(self):
        """Cierra sin guardar y sin tocar nada (el documento ya no es el mismo)."""
        if self.widget is not None:
            try:
                if self.widget.hasFocus():
                    self.viewer.setFocus(Qt.OtherFocusReason)
                self.widget.hide()
                self.widget.deleteLater()
            except RuntimeError:
                pass
        self.widget = None
        self.field = None

    def focus_lost(self, w):
        """Al hacer clic fuera: se guarda (si el foco no ha ido a la ventana emergente)."""
        def later():
            if self.widget is w and not w.hasFocus():
                fw = w.window().focusWidget() if w.window() else None
                if fw is not None and (fw is w or w.isAncestorOf(fw)):
                    return
                self.close(commit=True)
        QTimer.singleShot(0, later)

    # ------------------------------------------------------------------ casillas y teclado
    def toggle(self):
        f = self.field
        if not f or f.kind not in (forms.CHECK, forms.RADIO):
            return
        page, xref = self.page, self.xref
        new = (not f.value) if f.kind == forms.CHECK else True
        if f.kind == forms.RADIO and f.value:
            return
        self.viewer.action.emit("form_value", page, (xref, new))
        nf = self.viewer.field_by_xref(page, xref)
        if nf is not None and self.active:
            self.field = nf

    def move(self, step: int):
        page, xref = self.page, self.xref
        self.close(commit=True)
        nxt = self.viewer.neighbour_field(page, xref, step)
        if nxt is not None:
            self.open(nxt, select_all=True)
