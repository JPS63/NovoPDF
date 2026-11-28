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

"""Panel lateral de comentarios: lista de hilos (comentario, respuestas y estado) con
responder, editar, marcar como resuelto y eliminar."""
from __future__ import annotations

from html import escape

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
                               QScrollArea, QToolButton, QVBoxLayout, QWidget)

from ..core import comments as C
from . import icons, theme

PANEL_CSS = f"""
QFrame#CommentsPanel {{ background: #f6f8fc; border-left: 1px solid {theme.BORDER}; }}
QFrame#CommentCard {{ background: white; border: 1px solid {theme.BORDER}; border-radius: 8px; }}
QFrame#CommentCard[selected="true"] {{ border: 2px solid {theme.ACCENT}; }}
QFrame#CommentCard[resolved="true"] {{ background: #f3f6f4; }}
QLabel#CAuthor {{ font-weight: 600; }}
QLabel#CMeta {{ color: {theme.MUTED}; font-size: 8.5pt; }}
QLabel#CQuote {{ color: #4a5160; font-style: italic; border-left: 3px solid #d5dbe6; padding-left: 6px; }}
QLabel#CBadge {{ color: white; background: {theme.SUCCESS}; border-radius: 7px; padding: 1px 7px; font-size: 8pt; }}
QPushButton#CLink {{ border: none; background: transparent; color: {theme.ACCENT}; padding: 1px 4px; }}
QPushButton#CLink:hover {{ text-decoration: underline; }}
QPushButton#CDanger {{ border: none; background: transparent; color: {theme.DANGER}; padding: 1px 4px; }}
"""


def _dot(color) -> str:
    c = QColor.fromRgbF(*color) if color else QColor(theme.ACCENT)
    return f"<span style='color:{c.name()}; font-size: 13pt;'>●</span>"


class _Editor(QWidget):
    """Cuadro para escribir una respuesta o cambiar un comentario."""

    def __init__(self, text, ok_text, on_ok, on_cancel, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(4)
        self.edit = QPlainTextEdit(text)
        self.edit.setFixedHeight(64)
        self.edit.setPlaceholderText("Escribe aquí…")
        lay.addWidget(self.edit)
        row = QHBoxLayout()
        row.addStretch(1)
        c = QPushButton("Cancelar")
        c.setObjectName("Small")
        c.clicked.connect(on_cancel)
        ok = QPushButton(ok_text)
        ok.setObjectName("Primary")
        ok.setStyleSheet("padding: 3px 12px;")
        ok.clicked.connect(lambda: on_ok(self.edit.toPlainText().strip()))
        row.addWidget(c)
        row.addWidget(ok)
        lay.addLayout(row)
        QTimer.singleShot(0, self.edit.setFocus)


class CommentCard(QFrame):
    def __init__(self, panel: "CommentsPanel", c: C.Comment):
        super().__init__()
        self.panel, self.c = panel, c
        self.setObjectName("CommentCard")
        self.setProperty("resolved", c.resolved)
        self.setCursor(Qt.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(4)
        head = QHBoxLayout()
        head.setSpacing(6)
        dot = QLabel(_dot(c.color))
        head.addWidget(dot)
        a = QLabel(escape(c.author or "Sin autor"))
        a.setObjectName("CAuthor")
        head.addWidget(a)
        head.addStretch(1)
        if c.resolved:
            b = QLabel("Resuelto")
            b.setStyleSheet(f"color: white; background-color: {theme.SUCCESS}; border-radius: 7px; "
                            "padding: 1px 7px; font-size: 8pt;")
            b.setToolTip(f"Marcado como resuelto por {c.state_author}" if c.state_author else "")
            head.addWidget(b)
        lay.addLayout(head)
        meta = QLabel(f"{c.kind_name} · pág. {c.page + 1}" + (f" · {C.format_date(c.when)}" if c.when else ""))
        meta.setObjectName("CMeta")
        lay.addWidget(meta)
        if c.quoted:
            q = QLabel(escape(c.quoted if len(c.quoted) < 160 else c.quoted[:157] + "…"))
            q.setObjectName("CQuote")
            q.setWordWrap(True)
            lay.addWidget(q)
        self.text = QLabel(escape(c.text).replace("\n", "<br>") if c.text else
                           f"<span style='color:{theme.MUTED}'>(sin comentario)</span>")
        self.text.setWordWrap(True)
        self.text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.text)
        for r in c.replies:
            rw = QWidget()
            rl = QVBoxLayout(rw)
            rl.setContentsMargins(14, 2, 0, 2)
            rl.setSpacing(1)
            rh = QLabel(f"<b>{escape(r.author or 'Sin autor')}</b> "
                        f"<span style='color:{theme.MUTED}; font-size:8.5pt'>{C.format_date(r.when)}</span>")
            rl.addWidget(rh)
            rt = QLabel(escape(r.text).replace("\n", "<br>"))
            rt.setWordWrap(True)
            rt.setTextInteractionFlags(Qt.TextSelectableByMouse)
            rl.addWidget(rt)
            rw.setStyleSheet("QWidget { border-left: 2px solid #dfe4ee; }  QLabel { border: none; }")
            lay.addWidget(rw)
        self.btns = QHBoxLayout()
        self.btns.setSpacing(2)
        for label, fn, name in (("Responder", self._reply, "CLink"),
                                ("Editar", self._edit, "CLink"),
                                ("Reabrir" if c.resolved else "Resolver", self._resolve, "CLink"),
                                ("Eliminar", self._delete, "CDanger")):
            b = QPushButton(label)
            b.setObjectName(name)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(fn)
            self.btns.addWidget(b)
        self.btns.addStretch(1)
        lay.addLayout(self.btns)
        self.editor_slot = QVBoxLayout()
        lay.addLayout(self.editor_slot)
        self._editor = None

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.panel.select(self.c.page, self.c.xref, go=True)
        super().mousePressEvent(e)

    def _close_editor(self):
        if self._editor is not None:
            self._editor.setParent(None)
            self._editor.deleteLater()
            self._editor = None

    def _reply(self):
        self._close_editor()
        self._editor = _Editor("", "Responder", lambda t: self.panel.replyRequested.emit(self.c.page, self.c.xref, t)
                               if t else None, self._close_editor)
        self.editor_slot.addWidget(self._editor)

    def _edit(self):
        if self.c.kind == C.FREETEXT:
            self.panel.editFreeTextRequested.emit(self.c.page, self.c.xref)
            return
        self._close_editor()
        self._editor = _Editor(self.c.text, "Guardar", lambda t: self.panel.editRequested.emit(self.c.page, self.c.xref, t),
                               self._close_editor)
        self.editor_slot.addWidget(self._editor)

    def _resolve(self):
        self.panel.resolveRequested.emit(self.c.page, self.c.xref, not self.c.resolved)

    def _delete(self):
        self.panel.deleteRequested.emit(self.c.page, self.c.xref)

    def set_selected(self, on: bool):
        self.setProperty("selected", on)
        self.style().unpolish(self)
        self.style().polish(self)


class CommentsPanel(QFrame):
    replyRequested = Signal(int, int, str)
    editRequested = Signal(int, int, str)
    editFreeTextRequested = Signal(int, int)
    resolveRequested = Signal(int, int, bool)
    deleteRequested = Signal(int, int)
    gotoRequested = Signal(int, object)          # página, rectángulo visible
    exportRequested = Signal()
    closeRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("CommentsPanel")
        self.setStyleSheet(PANEL_CSS)
        self.setFixedWidth(330)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 6, 6)
        lay.setSpacing(6)
        head = QHBoxLayout()
        ic = QLabel()
        ic.setPixmap(icons.pixmap("comment", 20, theme.ACCENT))
        head.addWidget(ic)
        self.title = QLabel("Comentarios")
        self.title.setStyleSheet("font-weight: 700; font-size: 11pt;")
        head.addWidget(self.title)
        head.addStretch(1)
        exp = QToolButton()
        exp.setIcon(icons.icon("sheet_doc"))
        exp.setToolTip("Exportar la lista de comentarios a Excel")
        exp.setAutoRaise(True)
        exp.clicked.connect(self.exportRequested)
        head.addWidget(exp)
        close = QToolButton()
        close.setIcon(icons.icon("close"))
        close.setToolTip("Cerrar el panel de comentarios")
        close.setAutoRaise(True)
        close.clicked.connect(self.closeRequested)
        head.addWidget(close)
        lay.addLayout(head)
        self.show_resolved = QCheckBox("Mostrar los resueltos")
        self.show_resolved.setChecked(True)
        self.show_resolved.toggled.connect(lambda _: self._rebuild())
        lay.addWidget(self.show_resolved)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; }")
        self.inner = QWidget()
        self.inner.setStyleSheet("background: transparent;")
        self.list = QVBoxLayout(self.inner)
        self.list.setContentsMargins(0, 0, 4, 0)
        self.list.setSpacing(8)
        self.list.addStretch(1)
        self.scroll.setWidget(self.inner)
        lay.addWidget(self.scroll, 1)
        self.empty = QLabel("Este documento no tiene comentarios.\n\nUsa «Nota», «Cuadro de texto» o "
                            "«Resaltar y comentar» en la pestaña Comentar.")
        self.empty.setWordWrap(True)
        self.empty.setObjectName("Muted")
        self.empty.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.empty)
        self.comments: list[C.Comment] = []
        self.cards: list[CommentCard] = []
        self.selected = None                       # (página, xref)

    def set_comments(self, comments: list[C.Comment]):
        self.comments = list(comments)
        self._rebuild()

    def _rebuild(self):
        bar = self.scroll.verticalScrollBar().value()
        for card in self.cards:
            card.setParent(None)
            card.deleteLater()
        self.cards = []
        n = len(self.comments)
        open_n = sum(1 for c in self.comments if not c.resolved)
        self.title.setText(f"Comentarios ({n})" if n == open_n or not n else f"Comentarios ({open_n} de {n} abiertos)")
        shown = [c for c in self.comments if self.show_resolved.isChecked() or not c.resolved]
        for c in shown:
            card = CommentCard(self, c)
            self.list.insertWidget(self.list.count() - 1, card)
            self.cards.append(card)
            if self.selected == (c.page, c.xref):
                card.set_selected(True)
        self.empty.setVisible(not self.comments)
        self.scroll.setVisible(bool(self.comments))
        QTimer.singleShot(0, lambda: self.scroll.verticalScrollBar().setValue(bar))

    def select(self, page, xref, go=False, scroll=True):
        """Selecciona el hilo que contiene esa anotación (comentario o respuesta)."""
        target = None
        for card in self.cards:
            c = card.c
            hit = (c.page == page and (c.xref == xref or any(r.xref == xref for r in c.replies)))
            card.set_selected(hit)
            if hit:
                target = card
        if target is None:
            self.selected = None
            return False
        self.selected = (target.c.page, target.c.xref)
        if scroll:
            QTimer.singleShot(0, lambda: self.scroll.ensureWidgetVisible(target, 0, 40))
        if go:
            self.gotoRequested.emit(target.c.page, target.c.rect)
        return True

    def card_for(self, page, xref):
        for card in self.cards:
            if card.c.page == page and card.c.xref == xref:
                return card
        return None
