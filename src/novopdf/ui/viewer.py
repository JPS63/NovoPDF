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

"""Visor de páginas con herramientas de interacción."""
from __future__ import annotations

import pymupdf
from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QCursor, QGuiApplication, QImage, QKeySequence, QPainter,
                           QPen, QPixmap, QShortcut)
from PySide6.QtWidgets import QMenu, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from ..core import editing, forms
from . import theme

BASE = 96 / 72.0          # 100 % = tamaño real en una pantalla estándar
HANDLE = 9                # tamaño (px) del tirador para redimensionar imágenes

# Herramientas
T_SELECT = "select"
T_EDIT_TEXT = "edit_text"
T_ADD_TEXT = "add_text"
T_IMAGES = "images"
T_ADD_IMAGE = "add_image"
T_ERASE = "erase"
T_SIGN = "sign"
T_HIGHLIGHT = "highlight"
T_UNDERLINE = "underline"
T_STRIKE = "strikeout"
T_UNMARK = "unmark"
MARK_TOOLS = (T_HIGHLIGHT, T_UNDERLINE, T_STRIKE)
# Formularios: editar campos (seleccionar, mover, cambiar tamaño) y crear campos de cada tipo
T_FORM_EDIT = "form_edit"
T_F_TEXT, T_F_CHECK, T_F_RADIO, T_F_COMBO, T_F_LIST, T_F_SIGN = (
    "f_text", "f_check", "f_radio", "f_combo", "f_list", "f_sign")
FORM_CREATE = {T_F_TEXT: forms.TEXT, T_F_CHECK: forms.CHECK, T_F_RADIO: forms.RADIO,
               T_F_COMBO: forms.COMBO, T_F_LIST: forms.LIST, T_F_SIGN: forms.SIGNATURE}
FORM_TOOLS = (T_FORM_EDIT,) + tuple(FORM_CREATE)
RECT_TOOLS = (T_ADD_IMAGE, T_ERASE, T_SIGN) + tuple(FORM_CREATE)
FIELD_FILL = QColor(221, 228, 255)           # campos para rellenar (como «Resaltar campos» de Acrobat),
                                             # en modo «multiplicar»: el texto sigue negro

ACCENT = QColor(theme.ACCENT)


class PageWidget(QWidget):
    def __init__(self, viewer: "Viewer", index: int):
        super().__init__()
        self.viewer = viewer
        self.index = index
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setAttribute(Qt.WA_OpaquePaintEvent, False)

    def sizeHint(self) -> QSize:
        r = self.viewer.page_rect(self.index)
        s = self.viewer.scale
        return QSize(int(r.width * s), int(r.height * s))

    # coordenadas
    def to_pdf(self, pos) -> pymupdf.Point:
        s = self.viewer.scale
        return pymupdf.Point(pos.x() / s, pos.y() / s)

    def to_px(self, r: pymupdf.Rect) -> QRectF:
        s = self.viewer.scale
        return QRectF(r.x0 * s, r.y0 * s, r.width * s, r.height * s)

    def paintEvent(self, ev):
        p = QPainter(self)
        pm = self.viewer.render(self.index)
        if pm is not None:
            p.drawPixmap(self.rect(), pm)
        else:
            p.fillRect(self.rect(), Qt.white)
        p.setPen(QColor("#cfd4de"))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))
        self.viewer.paint_overlay(self, p)
        p.end()

    def mousePressEvent(self, e):
        self.viewer.on_press(self, e)

    def mouseMoveEvent(self, e):
        self.viewer.on_move(self, e)

    def mouseReleaseEvent(self, e):
        self.viewer.on_release(self, e)

    def mouseDoubleClickEvent(self, e):
        self.viewer.on_double(self, e)

    def event(self, e):
        if e.type() == e.Type.ToolTip:
            tip = self.viewer.tooltip_at(self, e.pos())
            if tip:
                from PySide6.QtWidgets import QToolTip
                QToolTip.showText(e.globalPos(), tip, self)
            else:
                from PySide6.QtWidgets import QToolTip
                QToolTip.hideText()
                e.ignore()
            return True
        return super().event(e)

    def contextMenuEvent(self, e):
        self.viewer.on_context(self, e)

    def leaveEvent(self, e):
        self.viewer.on_leave(self)


class Viewer(QScrollArea):
    pageChanged = Signal(int)
    zoomChanged = Signal(float)
    action = Signal(str, int, object)     # tipo, página, datos
    imageSelected = Signal(bool)
    fieldSelected = Signal(object)     # campo seleccionado al editar campos (o None)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Viewer")
        self.setWidgetResizable(True)
        self.setAlignment(Qt.AlignHCenter)
        self.canvas = QWidget()
        self.canvas.setObjectName("ViewerCanvas")
        self.lay = QVBoxLayout(self.canvas)
        self.lay.setContentsMargins(24, 24, 24, 24)
        self.lay.setSpacing(18)
        self.lay.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.setWidget(self.canvas)
        self.pdf = None
        self.zoom = 1.0
        self.fit_mode = "width"
        self.pages: list[PageWidget] = []
        self._cache: dict[int, tuple[float, QPixmap]] = {}
        self._blocks: dict[int, list] = {}
        self._images: dict[int, list] = {}
        self._words: dict[int, list] = {}
        self.tool = T_SELECT
        self.hover = None              # (page, Rect)
        self.drag = None               # estado de arrastre
        self.sel_image = None          # (page, ImageItem, Rect actual)
        self.text_sel = None           # (page, i0, i1)
        self.mark_colors = {}          # herramienta de marca -> color (r, g, b)
        self.search_hits: dict[int, list] = {}
        self.current_hit = None
        self._fields: dict[int, list] = {}
        self.show_fields = True        # resaltar los campos del formulario
        self.form_fill = True          # se pueden rellenar (permisos)
        self.sel_field = None          # (página, Field, Rect actual) al editar campos
        from .formfill import FieldEditor
        self.editor = FieldEditor(self)
        self._last_page = -1
        self.verticalScrollBar().valueChanged.connect(self._on_scroll)
        QShortcut(QKeySequence.Copy, self, self.copy_selection)
        QShortcut(QKeySequence.Delete, self, self._delete_key)
        QShortcut(QKeySequence(Qt.Key_Backspace), self, self._delete_key)
        QShortcut(QKeySequence(Qt.Key_Escape), self, self.clear_selection)

    # ------------------------------------------------------------------ documento
    @property
    def scale(self) -> float:
        return self.zoom * BASE

    def set_document(self, pdf):
        self.editor.discard()
        self.pdf = pdf
        self.clear_selection()
        self.search_hits = {}
        self.rebuild()
        QTimer.singleShot(0, self.fit_width)

    def rebuild(self):
        self.editor.discard()
        for w in self.pages:
            w.setParent(None)
            w.deleteLater()
        self.pages = []
        self.invalidate()
        if not self.pdf:
            return
        for i in range(self.pdf.page_count):
            w = PageWidget(self, i)
            self.lay.addWidget(w, 0, Qt.AlignHCenter)
            self.pages.append(w)
        self._resize_pages()

    def invalidate(self, pages=None):
        if pages is None:
            self._cache.clear()
            self._blocks.clear()
            self._images.clear()
            self._words.clear()
            self._fields.clear()
        else:
            for i in pages:
                for c in (self._cache, self._blocks, self._images, self._words, self._fields):
                    c.pop(i, None)

    def refresh(self, pages=None, structure=False):
        """Volver a pintar tras un cambio en el documento."""
        self.hover = None
        self.sel_image = None
        self.text_sel = None
        self.imageSelected.emit(False)
        if self.sel_field is not None:
            self.sel_field = None
            self.fieldSelected.emit(None)
        if structure or len(self.pages) != (self.pdf.page_count if self.pdf else 0):
            keep = self.current_page()
            self.rebuild()
            QTimer.singleShot(0, lambda: self.go_to(min(keep, max(0, len(self.pages) - 1))))
        else:
            self.invalidate(pages)
            self._resize_pages()
            for w in self.pages:
                w.update()

    def page_rect(self, i) -> pymupdf.Rect:
        try:
            return self.pdf.doc[i].rect
        except Exception:
            return pymupdf.Rect(0, 0, 595, 842)

    def _resize_pages(self):
        for w in self.pages:
            w.setFixedSize(w.sizeHint())
        if self.editor.active:
            QTimer.singleShot(0, self.editor.place)

    def render(self, i):
        if not self.pdf or i >= self.pdf.page_count:
            return None
        dpr = self.devicePixelRatioF()
        key = self.scale * dpr
        hit = self._cache.get(i)
        if hit and abs(hit[0] - key) < 1e-6:
            return hit[1]
        page = self.pdf.doc[i]
        pix = page.get_pixmap(matrix=pymupdf.Matrix(key, key), alpha=False, annots=True)
        img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()
        pm = QPixmap.fromImage(img)
        pm.setDevicePixelRatio(dpr)
        # Limitar memoria: conservar solo páginas cercanas a la actual
        if len(self._cache) > 24:
            cur = self.current_page()
            for k in sorted(self._cache, key=lambda k: -abs(k - cur))[:8]:
                self._cache.pop(k, None)
        self._cache[i] = (key, pm)
        return pm

    # ------------------------------------------------------------------ zoom / navegación
    def set_zoom(self, z: float, keep_mode=False):
        z = max(0.2, min(5.0, z))
        if not keep_mode:
            self.fit_mode = None
        cur = self.current_page()
        rel = self._relative_offset()
        self.zoom = z
        self._cache.clear()
        self._resize_pages()
        self.canvas.adjustSize()
        QTimer.singleShot(0, lambda: self._restore_offset(cur, rel))
        self.zoomChanged.emit(self.zoom)

    def _relative_offset(self):
        cur = self.current_page()
        if not self.pages:
            return 0
        w = self.pages[cur]
        return (self.verticalScrollBar().value() - w.y()) / max(1, w.height())

    def _restore_offset(self, cur, rel):
        if cur < len(self.pages):
            w = self.pages[cur]
            self.verticalScrollBar().setValue(int(w.y() + rel * w.height()))

    def zoom_in(self):
        self.set_zoom(self.zoom * 1.2)

    def zoom_out(self):
        self.set_zoom(self.zoom / 1.2)

    def fit_width(self):
        if not self.pdf or not self.pdf.page_count:
            return
        avail = self.viewport().width() - 48 - 4
        widest = max(self.page_rect(i).width for i in range(min(self.pdf.page_count, 50)))
        z = avail / (widest * BASE)
        self.fit_mode = "width"
        self.set_zoom(min(z, 1.5), keep_mode=True)

    def fit_page(self):
        if not self.pdf or not self.pdf.page_count:
            return
        r = self.page_rect(self.current_page())
        zw = (self.viewport().width() - 52) / (r.width * BASE)
        zh = (self.viewport().height() - 40) / (r.height * BASE)
        self.fit_mode = "page"
        self.set_zoom(min(zw, zh), keep_mode=True)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.fit_mode == "width":
            QTimer.singleShot(0, self.fit_width)

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            if e.angleDelta().y() > 0:
                self.zoom_in()
            else:
                self.zoom_out()
            e.accept()
            return
        super().wheelEvent(e)

    def current_page(self) -> int:
        if not self.pages:
            return 0
        center = self.verticalScrollBar().value() + self.viewport().height() // 3
        for w in self.pages:
            if w.y() + w.height() + 9 >= center:
                return w.index
        return len(self.pages) - 1

    def go_to(self, i: int, rect: pymupdf.Rect | None = None):
        if not self.pages:
            return
        i = max(0, min(i, len(self.pages) - 1))
        w = self.pages[i]
        y = w.y() - 12
        if rect is not None:
            y = w.y() + int(rect.y0 * self.scale) - self.viewport().height() // 3
        self.verticalScrollBar().setValue(max(0, y))
        self._on_scroll()

    def _on_scroll(self, *_):
        c = self.current_page()
        if c != self._last_page:
            self._last_page = c
            self.pageChanged.emit(c)

    # ------------------------------------------------------------------ herramientas
    def set_tool(self, tool: str):
        self.editor.close(commit=True)
        self.tool = tool
        self.clear_selection()
        cursors = {T_SELECT: Qt.IBeamCursor, T_EDIT_TEXT: Qt.IBeamCursor, T_ADD_TEXT: Qt.CrossCursor,
                   T_IMAGES: Qt.ArrowCursor, T_ADD_IMAGE: Qt.CrossCursor, T_ERASE: Qt.CrossCursor,
                   T_SIGN: Qt.CrossCursor, T_HIGHLIGHT: Qt.IBeamCursor, T_UNDERLINE: Qt.IBeamCursor,
                   T_STRIKE: Qt.IBeamCursor, T_UNMARK: Qt.PointingHandCursor,
                   T_FORM_EDIT: Qt.ArrowCursor}
        for t in FORM_CREATE:
            cursors[t] = Qt.CrossCursor
        for w in self.pages:
            w.setCursor(cursors.get(tool, Qt.ArrowCursor))

    def clear_selection(self):
        self.editor.close(commit=False)
        self.hover = None
        self.drag = None
        self.text_sel = None
        if self.sel_image is not None:
            self.sel_image = None
            self.imageSelected.emit(False)
        if self.sel_field is not None:
            self.sel_field = None
            self.fieldSelected.emit(None)
        for w in self.pages:
            w.update()

    def blocks(self, i):
        if i not in self._blocks:
            self._blocks[i] = editing.text_blocks(self.pdf.doc[i])
        return self._blocks[i]

    def images(self, i):
        if i not in self._images:
            self._images[i] = editing.page_images(self.pdf.doc[i])
        return self._images[i]

    def words(self, i):
        """Palabras con su rectángulo en la página visible (índice 8: el original, sin girar)."""
        if i not in self._words:
            page = self.pdf.doc[i]
            m = page.rotation_matrix
            out = []
            for w in page.get_text("words", sort=True):
                r = pymupdf.Rect(w[:4]) * m if page.rotation else pymupdf.Rect(w[:4])
                out.append((r.x0, r.y0, r.x1, r.y1) + tuple(w[4:8]) + (tuple(w[:4]),))
            self._words[i] = out
        return self._words[i]

    def selected_words(self):
        """(página, palabras seleccionadas con coordenadas sin girar) para marcarlas."""
        if not self.text_sel or self.text_sel[1] is None:
            return None, []
        i, a, b = self.text_sel
        a, b = min(a, b), max(a, b)
        return i, [w[8] + tuple(w[4:8]) for w in self.words(i)[a:b + 1]]

    def mark_at(self, i, pt):
        """Marca de texto (resaltado, subrayado, tachado) bajo un punto visible."""
        from ..core import markup
        page = self.pdf.doc[i]
        p0 = pt * page.derotation_matrix if page.rotation else pt
        return markup.mark_at(page, p0)

    def _mark_rect(self, i, rects):
        page = self.pdf.doc[i]
        r = pymupdf.Rect()
        for x in rects:
            r |= x
        return r * page.rotation_matrix if page.rotation else r

    def _block_at(self, i, pt):
        for b in self.blocks(i):
            if (b.bbox + (-2, -2, 2, 2)).contains(pt):
                return b
        return None

    def _image_at(self, i, pt):
        for im in self.images(i):
            if im.bbox.contains(pt):
                return im
        return None

    def _word_index(self, i, pt, nearest=True):
        ws = self.words(i)
        best, bestd = None, 1e9
        for k, w in enumerate(ws):
            r = pymupdf.Rect(w[:4])
            if r.contains(pt):
                return k
            if nearest:
                # distancia preferente por línea
                dy = 0 if r.y0 <= pt.y <= r.y1 else min(abs(pt.y - r.y0), abs(pt.y - r.y1))
                dx = 0 if r.x0 <= pt.x <= r.x1 else min(abs(pt.x - r.x0), abs(pt.x - r.x1))
                d = dy * 4 + dx
                if d < bestd:
                    best, bestd = k, d
        return best if bestd < 60 else None

    def selected_text(self) -> str:
        if not self.text_sel:
            return ""
        i, a, b = self.text_sel
        a, b = min(a, b), max(a, b)
        ws = self.words(i)[a:b + 1]
        out, last = [], None
        for w in ws:
            key = (w[5], w[6])
            if last is not None:
                out.append("\n" if key != last else " ")
            out.append(w[4])
            last = key
        return "".join(out)

    def copy_selection(self):
        t = self.selected_text()
        if t:
            QGuiApplication.clipboard().setText(t)

    def _delete_key(self):
        if self.sel_field:
            i, f, _ = self.sel_field
            self.action.emit("form_delete", i, f.xref)
            return
        if self.sel_image:
            i, item, _ = self.sel_image
            self.action.emit("image_delete", i, item)

    def focusNextPrevChild(self, nxt: bool) -> bool:
        """Tab en el visor (sin estar rellenando): ir al primer (o último) campo."""
        if self.pdf and self.tool == T_SELECT and not self.editor.active and self.hasFocus():
            f = self.first_field()
            if f is not None:
                if not nxt:
                    f = self.neighbour_field(f.page, f.xref, -1) or f
                self.open_field(f)
                return True
        return super().focusNextPrevChild(nxt)

    # ------------------------------------------------------------------ formularios
    def fields(self, i) -> list:
        if not self.pdf or i >= self.pdf.page_count:
            return []
        if i not in self._fields:
            self._fields[i] = forms.page_fields(self.pdf.doc, i)
        return self._fields[i]

    def has_fields(self) -> bool:
        return bool(self.pdf) and any(self.fields(i) for i in range(min(self.pdf.page_count, 400)))

    def field_by_xref(self, i, xref):
        for f in self.fields(i):
            if f.xref == xref:
                return f
        return None

    def _field_at(self, i, pt, grow=1.0):
        for f in reversed(self.fields(i)):
            if (f.rect + (-grow, -grow, grow, grow)).contains(pt):
                return f
        return None

    def update_page(self, i):
        if 0 <= i < len(self.pages):
            self.pages[i].update()

    def ensure_field_visible(self, f):
        if f.page >= len(self.pages):
            return
        w = self.pages[f.page]
        r = w.to_px(f.rect)
        self.ensureVisible(int(w.x() + r.center().x()), int(w.y() + r.center().y()),
                           int(r.width() / 2 + 40), int(r.height() / 2 + 60))

    def neighbour_field(self, i, xref, step):
        """Campo anterior o siguiente para rellenar (en orden de lectura; da la vuelta)."""
        order = [f for k in range(self.pdf.page_count) for f in self.fields(k)
                 if f.fillable and not (f.kind == forms.RADIO and f.group_size > 1 and not self._first_of_group(f))]
        if not order:
            return None
        pos = next((n for n, f in enumerate(order) if f.page == i and f.xref == xref), None)
        if pos is None:
            # un botón de opción que no es el primero de su grupo: buscar el del grupo
            cur = self.field_by_xref(i, xref)
            pos = next((n for n, f in enumerate(order) if cur and f.kind == forms.RADIO and f.name == cur.name), 0)
        return order[(pos + step) % len(order)]

    def _first_of_group(self, f):
        """En los grupos de opciones, Tab va solo al primero (o al marcado)."""
        group = [g for k in range(self.pdf.page_count) for g in self.fields(k) if g.kind == forms.RADIO and g.name == f.name]
        on = [g for g in group if g.value]
        first = on[0] if on else group[0]
        return first.xref == f.xref and first.page == f.page

    def first_field(self):
        if not self.pdf:
            return None
        for k in range(self.pdf.page_count):
            for f in self.fields(k):
                if f.fillable:
                    return f
        return None

    def open_field(self, f):
        if f.kind == forms.SIGNATURE:
            self.action.emit("form_sign", f.page, f)
            return
        if not f.fillable:
            return
        if not self.form_fill:
            self.action.emit("form_locked", f.page, f)
            return
        self.editor.open(f)

    def tooltip_at(self, w, pos):
        if not self.pdf:
            return ""
        f = self._field_at(w.index, w.to_pdf(pos))
        if f is None:
            return ""
        if self.tool in FORM_TOOLS:
            extra = f" · grupo «{f.name}», valor «{f.on_state}»" if f.kind == forms.RADIO else ""
            return f"{f.kind_name}: «{f.name}»{extra}" + (f"\n{f.label}" if f.label and f.label != f.name else "")
        if f.kind == forms.SIGNATURE:
            return "Firma realizada (clic para comprobarla)" if f.signed else "Campo de firma: haz clic para firmar aquí"
        tip = f.label or f.name
        if f.required:
            tip += " (obligatorio)"
        if f.readonly:
            tip += " (solo lectura)"
        return tip

    def select_field(self, i, xref):
        f = self.field_by_xref(i, xref)
        if f is None:
            return
        self.sel_field = (i, f, pymupdf.Rect(f.rect))
        self.fieldSelected.emit(f)
        self.update_page(i)

    # ------------------------------------------------------------------ eventos de ratón
    def on_press(self, w: PageWidget, e):
        if e.button() != Qt.LeftButton or not self.pdf:
            return
        pt = w.to_pdf(e.position())
        i = w.index
        t = self.tool
        if t == T_SELECT:
            f = self._field_at(i, pt)
            if f is not None:
                self.text_sel = None
                if f.kind in (forms.CHECK, forms.RADIO) and f.fillable and self.form_fill:
                    self.editor.close(commit=True)
                    f = self.field_by_xref(i, f.xref) or f
                    if not (f.kind == forms.RADIO and f.value):
                        self.action.emit("form_value", i, (f.xref, not f.value if f.kind == forms.CHECK else True))
                    nf = self.field_by_xref(i, f.xref)
                    if nf is not None:
                        self.editor.open(nf)
                elif not self.editor.is_on(i, f.xref):
                    self.open_field(f)
                w.update()
                return
            self.editor.close(commit=True)
        if t == T_FORM_EDIT:
            if self.sel_field and self.sel_field[0] == i:
                r = self.sel_field[2]
                if self._handle_rect(r).contains(pt):
                    self.drag = ("fresize", i, pt, pymupdf.Rect(r))
                    return
                if r.contains(pt):
                    self.drag = ("fmove", i, pt, pymupdf.Rect(r))
                    return
            f = self._field_at(i, pt, 2)
            if f is not None:
                self.sel_field = (i, f, pymupdf.Rect(f.rect))
                self.fieldSelected.emit(f)
                self.drag = ("fmove", i, pt, pymupdf.Rect(f.rect))
            elif self.sel_field is not None:
                self.sel_field = None
                self.fieldSelected.emit(None)
            for pw in self.pages:
                pw.update()
            return
        if t == T_SELECT or t in MARK_TOOLS:
            k = self._word_index(i, pt)
            self.text_sel = (i, k, k) if k is not None else None
            self.drag = ("text", i)
        elif t == T_UNMARK:
            m = self.mark_at(i, pt)
            if m:
                self.action.emit("unmark", i, m[0])
        elif t == T_EDIT_TEXT:
            b = self._block_at(i, pt)
            if b:
                self.action.emit("edit_block", i, b)
        elif t == T_ADD_TEXT:
            self.action.emit("add_text", i, pt)
        elif t == T_IMAGES:
            if self.sel_image and self.sel_image[0] == i:
                r = self.sel_image[2]
                hr = self._handle_rect(r)
                if hr.contains(pt):
                    self.drag = ("resize", i, pt, pymupdf.Rect(r))
                    return
                if r.contains(pt):
                    self.drag = ("move", i, pt, pymupdf.Rect(r))
                    return
            im = self._image_at(i, pt)
            if im:
                self.sel_image = (i, im, pymupdf.Rect(im.bbox))
                self.imageSelected.emit(True)
                self.drag = ("move", i, pt, pymupdf.Rect(im.bbox))
            else:
                if self.sel_image:
                    self.sel_image = None
                    self.imageSelected.emit(False)
        elif t in RECT_TOOLS:
            self.drag = ("rect", i, pt, pymupdf.Rect(pt, pt))
        w.update()

    def _handle_rect(self, r: pymupdf.Rect) -> pymupdf.Rect:
        h = HANDLE / self.scale
        return pymupdf.Rect(r.x1 - h, r.y1 - h, r.x1 + h, r.y1 + h)

    def on_move(self, w: PageWidget, e):
        if not self.pdf:
            return
        pt = w.to_pdf(e.position())
        i = w.index
        pr = self.page_rect(i)
        pt = pymupdf.Point(min(max(pt.x, 0), pr.width), min(max(pt.y, 0), pr.height))
        t = self.tool
        d = self.drag
        if d and e.buttons() & Qt.LeftButton:
            if d[0] == "text" and d[1] == i and self.text_sel:
                k = self._word_index(i, pt)
                if k is not None:
                    self.text_sel = (i, self.text_sel[1], k)
            elif d[0] == "move" and d[1] == i and self.sel_image:
                dx, dy = pt.x - d[2].x, pt.y - d[2].y
                r = d[3] + (dx, dy, dx, dy)
                # no salir de la página
                if r.x0 < 0:
                    r += (-r.x0, 0, -r.x0, 0)
                if r.y0 < 0:
                    r += (0, -r.y0, 0, -r.y0)
                if r.x1 > pr.width:
                    r += (pr.width - r.x1, 0, pr.width - r.x1, 0)
                if r.y1 > pr.height:
                    r += (0, pr.height - r.y1, 0, pr.height - r.y1)
                self.sel_image = (i, self.sel_image[1], r)
            elif d[0] == "resize" and d[1] == i and self.sel_image:
                r0 = d[3]
                nw = max(10, pt.x - r0.x0)
                nh = max(10, pt.y - r0.y0)
                if not (e.modifiers() & Qt.ShiftModifier):
                    ratio = r0.width / max(r0.height, 1e-3)
                    if nw / ratio > nh:
                        nh = nw / ratio
                    else:
                        nw = nh * ratio
                self.sel_image = (i, self.sel_image[1], pymupdf.Rect(r0.x0, r0.y0, r0.x0 + nw, r0.y0 + nh))
            elif d[0] == "rect" and d[1] == i:
                self.drag = ("rect", i, d[2], pymupdf.Rect(d[2], pt).normalize())
            elif d[0] == "fmove" and d[1] == i and self.sel_field:
                dx, dy = pt.x - d[2].x, pt.y - d[2].y
                r = forms.clamp(d[3] + (dx, dy, dx, dy), pr)
                self.sel_field = (i, self.sel_field[1], r)
            elif d[0] == "fresize" and d[1] == i and self.sel_field:
                r0 = d[3]
                nw = max(6, pt.x - r0.x0)
                nh = max(6, pt.y - r0.y0)
                if self.sel_field[1].kind in (forms.CHECK, forms.RADIO) and not (e.modifiers() & Qt.ShiftModifier):
                    nw = nh = max(nw, nh)
                self.sel_field = (i, self.sel_field[1], pymupdf.Rect(r0.x0, r0.y0, r0.x0 + nw, r0.y0 + nh))
            w.update()
            return
        # sin botón: resaltar lo que hay bajo el cursor
        new = None
        if t == T_SELECT:
            f = self._field_at(i, pt)
            if f is not None:
                if f.kind == forms.TEXT and f.fillable:
                    w.setCursor(Qt.IBeamCursor)
                elif f.fillable or f.kind == forms.SIGNATURE:
                    w.setCursor(Qt.PointingHandCursor)
                else:
                    w.setCursor(Qt.ForbiddenCursor)
                new = (i, f.rect) if f.fillable or f.kind == forms.SIGNATURE else None
            else:
                w.setCursor(Qt.IBeamCursor)
        elif t == T_FORM_EDIT:
            f = self._field_at(i, pt, 2)
            new = (i, f.rect) if f is not None else None
            sf = self.sel_field
            if sf and sf[0] == i and self._handle_rect(sf[2]).contains(pt):
                w.setCursor(Qt.SizeFDiagCursor)
            elif (sf and sf[0] == i and sf[2].contains(pt)) or f is not None:
                w.setCursor(Qt.SizeAllCursor)
            else:
                w.setCursor(Qt.ArrowCursor)
        elif t == T_EDIT_TEXT:
            b = self._block_at(i, pt)
            new = (i, b.bbox) if b else None
        elif t == T_UNMARK:
            m = self.mark_at(i, pt)
            new = (i, self._mark_rect(i, m[2])) if m else None
        elif t == T_IMAGES:
            im = self._image_at(i, pt)
            new = (i, im.bbox) if im else None
            if self.sel_image and self.sel_image[0] == i and self._handle_rect(self.sel_image[2]).contains(pt):
                w.setCursor(Qt.SizeFDiagCursor)
            elif (self.sel_image and self.sel_image[0] == i and self.sel_image[2].contains(pt)) or im:
                w.setCursor(Qt.SizeAllCursor)
            else:
                w.setCursor(Qt.ArrowCursor)
        if new != self.hover:
            old = self.hover
            self.hover = new
            for k in {x[0] for x in (old, new) if x}:
                if k < len(self.pages):
                    self.pages[k].update()

    def on_release(self, w: PageWidget, e):
        d = self.drag
        self.drag = None
        if not d or e.button() != Qt.LeftButton:
            return
        if d[0] == "text" and self.tool in MARK_TOOLS:
            i, words = self.selected_words()
            if words:
                self.action.emit("mark", i, (self.tool, words))
            self.text_sel = None
            w.update()
            return
        if d[0] in ("fmove", "fresize") and self.sel_field:
            i, f, r = self.sel_field
            if any(abs(a - b) > 0.5 for a, b in zip(r, f.rect)):
                self.action.emit("form_move", i, (f.xref, pymupdf.Rect(r)))
            w.update()
            return
        if d[0] in ("move", "resize") and self.sel_image:
            i, item, r = self.sel_image
            if (abs(r.x0 - item.bbox.x0) > 0.5 or abs(r.y0 - item.bbox.y0) > 0.5
                    or abs(r.x1 - item.bbox.x1) > 0.5 or abs(r.y1 - item.bbox.y1) > 0.5):
                self.action.emit("image_move", i, (item, pymupdf.Rect(r)))
        elif d[0] == "rect":
            i, r = d[1], d[3]
            if self.tool in FORM_CREATE:
                small = r.width < 6 or r.height < 6
                self.action.emit("form_add", i, (FORM_CREATE[self.tool], d[2] if small else r, small))
                w.update()
                return
            kind = {T_ADD_IMAGE: "add_image", T_ERASE: "erase", T_SIGN: "sign"}[self.tool]
            small = r.width < 8 or r.height < 8
            if kind == "erase" and small:
                w.update()
                return
            if kind == "sign" and small:
                r = pymupdf.Rect(r.x0, r.y0, r.x0 + 200, r.y0 + 70)
                pr = self.page_rect(i)
                if r.x1 > pr.width:
                    r += (pr.width - r.x1 - 10, 0, pr.width - r.x1 - 10, 0)
                if r.y1 > pr.height:
                    r += (0, pr.height - r.y1 - 10, 0, pr.height - r.y1 - 10)
            self.action.emit(kind, i, r)
        w.update()

    def on_double(self, w, e):
        if self.tool == T_FORM_EDIT:
            f = self._field_at(w.index, w.to_pdf(e.position()), 2)
            if f is not None:
                self.action.emit("form_props", w.index, f.xref)
            return
        if self.tool == T_SELECT and self._field_at(w.index, w.to_pdf(e.position())) is not None:
            return
        if self.tool == T_SELECT:
            pt = w.to_pdf(e.position())
            k = self._word_index(w.index, pt, nearest=False)
            if k is not None:
                self.text_sel = (w.index, k, k)
                w.update()
        elif self.tool == T_IMAGES and self.sel_image:
            self.action.emit("image_replace", self.sel_image[0], self.sel_image[1])

    def on_leave(self, w):
        if self.hover and self.hover[0] == w.index:
            self.hover = None
            w.update()

    def on_context(self, w: PageWidget, e):
        m = QMenu(self)
        i = w.index
        if self.tool in FORM_TOOLS and self.pdf:
            f = self._field_at(i, w.to_pdf(e.pos()), 2)
            if f is not None:
                self.sel_field = (i, f, pymupdf.Rect(f.rect))
                self.fieldSelected.emit(f)
                w.update()
                m.addSection(f"{f.kind_name}: {f.name}")
                m.addAction("Propiedades…", lambda: self.action.emit("form_props", i, f.xref))
                m.addAction("Duplicar", lambda: self.action.emit("form_dup", i, f.xref))
                m.addAction(self._swatch_icon(None, "trash"), "Eliminar", lambda: self.action.emit("form_delete", i, f.xref))
                m.exec(e.globalPos())
                return
        if self.tool == T_IMAGES and self.sel_image and self.sel_image[0] == i:
            item = self.sel_image[1]
            m.addAction("Reemplazar imagen…", lambda: self.action.emit("image_replace", i, item))
            m.addAction("Eliminar imagen", lambda: self.action.emit("image_delete", i, item))
            m.addSeparator()
        pt = w.to_pdf(e.pos())
        mk = self.mark_at(i, pt) if self.pdf else None
        if mk:
            from ..core import markup
            xref, typ = mk[0], mk[1]
            kind = {v[1]: k for k, v in markup.KINDS.items()}.get(typ, markup.HIGHLIGHT)
            m.addAction(self._swatch_icon(None, "unmark"), "Quitar esta marca", lambda: self.action.emit("unmark", i, xref))
            sub = m.addMenu("Cambiar el color de la marca")
            for name, col in markup.colors_for(kind):
                sub.addAction(self._swatch_icon(col), name, lambda col=col: self.action.emit("mark_color", i, (xref, col)))
            m.addSeparator()
        if self.text_sel:
            m.addAction("Copiar texto", self.copy_selection)
            sel_i, words = self.selected_words()
            if words:
                m.addAction(self._swatch_icon(None, "highlighter"), "Resaltar", lambda: self.action.emit("mark", sel_i, (T_HIGHLIGHT, words)))
                m.addAction(self._swatch_icon(None, "underline"), "Subrayar", lambda: self.action.emit("mark", sel_i, (T_UNDERLINE, words)))
                m.addAction(self._swatch_icon(None, "strike"), "Tachar", lambda: self.action.emit("mark", sel_i, (T_STRIKE, words)))
                m.addAction("Quitar las marcas del texto seleccionado", lambda: self.action.emit("unmark_words", sel_i, words))
            m.addSeparator()
        m.addAction("Girar esta página a la derecha", lambda: self.action.emit("rotate_page", i, 90))
        m.addAction("Eliminar esta página", lambda: self.action.emit("delete_page", i, None))
        m.exec(e.globalPos())

    @staticmethod
    def _swatch_icon(color, icon_name=None):
        from PySide6.QtGui import QIcon
        from . import icons
        if icon_name:
            return icons.icon(icon_name)
        pm = QPixmap(16, 16)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor.fromRgbF(*color))
        p.setPen(QColor("#9aa3b5"))
        p.drawRoundedRect(QRectF(1.5, 1.5, 13, 13), 3, 3)
        p.end()
        return QIcon(pm)

    # ------------------------------------------------------------------ dibujo de capas
    def paint_overlay(self, w: PageWidget, p: QPainter):
        i = w.index
        p.setRenderHint(QPainter.Antialiasing)
        self._paint_fields(w, p, i)
        # resultados de búsqueda
        for r in self.search_hits.get(i, []):
            cur = self.current_hit == (i, r)
            p.fillRect(w.to_px(r), QColor(255, 140, 0, 120) if cur else QColor(255, 210, 0, 110))
        # selección de texto
        if self.text_sel and self.text_sel[0] == i and self.text_sel[1] is not None:
            a, b = sorted(self.text_sel[1:])
            col = QColor(47, 91, 216, 70)
            if self.tool in MARK_TOOLS and self.mark_colors.get(self.tool):
                col = QColor.fromRgbF(*self.mark_colors[self.tool])
                col.setAlpha(110)
            for wd in self.words(i)[a:b + 1]:
                r = w.to_px(pymupdf.Rect(wd[:4]))
                if self.tool == T_UNDERLINE:
                    p.fillRect(QRectF(r.left(), r.bottom() - 2, r.width(), 2), col)
                elif self.tool == T_STRIKE:
                    p.fillRect(QRectF(r.left(), r.center().y() - 1, r.width(), 2), col)
                else:
                    p.fillRect(r, col)
        # elemento bajo el cursor
        if self.hover and self.hover[0] == i:
            r = w.to_px(self.hover[1]).adjusted(-3, -3, 3, 3)
            col = QColor(214, 69, 69) if self.tool == T_UNMARK else ACCENT
            p.setPen(QPen(col, 1.5, Qt.DashLine))
            fill = QColor(col)
            fill.setAlpha(22)
            p.setBrush(fill)
            p.drawRoundedRect(r, 3, 3)
        # imagen seleccionada
        if self.sel_image and self.sel_image[0] == i:
            r = w.to_px(self.sel_image[2])
            p.setPen(QPen(ACCENT, 2))
            p.setBrush(Qt.NoBrush)
            p.drawRect(r)
            hr = QRectF(r.right() - HANDLE, r.bottom() - HANDLE, HANDLE * 2, HANDLE * 2)
            p.setBrush(Qt.white)
            p.drawRect(hr)
        # campo seleccionado (editar campos)
        if self.sel_field and self.sel_field[0] == i:
            r = w.to_px(self.sel_field[2])
            p.setPen(QPen(ACCENT, 2))
            p.setBrush(Qt.NoBrush)
            p.drawRect(r)
            hr = QRectF(r.right() - HANDLE / 2, r.bottom() - HANDLE / 2, HANDLE, HANDLE)
            p.setBrush(Qt.white)
            p.drawRect(hr)
        # rectángulo en curso
        if self.drag and self.drag[0] == "rect" and self.drag[1] == i:
            r = w.to_px(self.drag[3])
            col = {T_ERASE: QColor(214, 69, 69), T_SIGN: QColor(31, 157, 107),
                   T_F_SIGN: QColor(31, 157, 107)}.get(self.tool, ACCENT)
            p.setPen(QPen(col, 1.5, Qt.DashLine))
            fill = QColor(col)
            fill.setAlpha(30)
            p.setBrush(fill)
            p.drawRect(r)

    def _paint_fields(self, w: PageWidget, p: QPainter, i: int):
        fs = self.fields(i) if self.pdf else []
        if not fs:
            return
        if self.tool in FORM_TOOLS:
            # preparar formulario: todos los campos con su nombre
            from PySide6.QtGui import QFont, QFontMetrics
            font = QFont(p.font())
            font.setPixelSize(10)
            p.setFont(font)
            fm = QFontMetrics(font)
            for f in fs:
                r = w.to_px(f.rect)
                col = QColor(31, 157, 107) if f.kind == forms.SIGNATURE else QColor(ACCENT)
                fill = QColor(col)
                fill.setAlpha(34)
                p.setPen(QPen(col, 1))
                p.setBrush(fill)
                p.drawRect(r)
                label = f.name if f.kind != forms.RADIO else f"{f.name}: {f.on_state}"
                tw = fm.horizontalAdvance(label) + 6
                th = fm.height()
                if r.height() >= th + 3 and r.width() >= tw + 2:
                    tag = QRectF(r.left() + 1, r.top() + 1, tw, th)      # dentro del campo, arriba a la izquierda
                elif r.top() > th + 2:
                    tag = QRectF(r.left(), r.top() - th - 1, tw, th)     # encima
                else:
                    tag = QRectF(r.left(), r.bottom() + 1, tw, th)       # debajo
                bg = QColor(col)
                bg.setAlpha(205)
                p.setPen(Qt.NoPen)
                p.setBrush(bg)
                p.drawRoundedRect(tag, 2, 2)
                p.setPen(Qt.white)
                p.drawText(tag.adjusted(3, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, label)
            return
        if not self.show_fields or self.tool != T_SELECT:
            return
        for f in fs:
            if self.editor.is_on(i, f.xref) and f.kind not in (forms.CHECK, forms.RADIO):
                continue
            r = w.to_px(f.rect)
            if f.kind == forms.SIGNATURE:
                if f.signed:
                    continue
                c = QColor(31, 157, 107)
                p.setPen(QPen(c, 1, Qt.DashLine))
                c.setAlpha(28)
                p.setBrush(c)
                p.drawRect(r.adjusted(0.5, 0.5, -0.5, -0.5))
                continue
            if not f.fillable:
                continue
            p.setPen(Qt.NoPen)
            p.setBrush(FIELD_FILL)
            p.setCompositionMode(QPainter.CompositionMode_Multiply)
            p.drawRect(r)
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)
            empty = (f.kind in (forms.TEXT, forms.COMBO) and not str(f.value).strip()) or \
                    (f.kind in (forms.CHECK, forms.LIST) and not f.value)
            if f.required and empty and f.kind != forms.RADIO:
                p.setPen(QPen(QColor(214, 69, 69), 1.2))
                p.setBrush(Qt.NoBrush)
                p.drawRect(r.adjusted(0.5, 0.5, -0.5, -0.5))
