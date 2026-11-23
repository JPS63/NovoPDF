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

"""Marcas sobre el texto: resaltar, subrayar y tachar (anotaciones PDF estándar).

Son anotaciones normales del PDF: se ven en cualquier lector (Acrobat, navegador, Vista
Previa), se pueden quitar y no modifican el texto del documento.
"""
from __future__ import annotations

import getpass

import pymupdf

HIGHLIGHT, UNDERLINE, STRIKEOUT = "highlight", "underline", "strikeout"
KINDS = {
    HIGHLIGHT: ("Resaltado", pymupdf.PDF_ANNOT_HIGHLIGHT),
    UNDERLINE: ("Subrayado", pymupdf.PDF_ANNOT_UNDERLINE),
    STRIKEOUT: ("Tachado", pymupdf.PDF_ANNOT_STRIKE_OUT),
}
MARK_TYPES = (pymupdf.PDF_ANNOT_HIGHLIGHT, pymupdf.PDF_ANNOT_UNDERLINE,
              pymupdf.PDF_ANNOT_STRIKE_OUT, pymupdf.PDF_ANNOT_SQUIGGLY)

HIGHLIGHT_COLORS = [("Amarillo", (1.0, 0.91, 0.18)), ("Verde", (0.55, 0.9, 0.4)),
                    ("Azul", (0.5, 0.78, 1.0)), ("Rosa", (1.0, 0.6, 0.8)), ("Naranja", (1.0, 0.72, 0.3))]
LINE_COLORS = [("Rojo", (0.85, 0.12, 0.12)), ("Azul", (0.12, 0.35, 0.85)), ("Verde", (0.1, 0.6, 0.3)),
               ("Negro", (0.0, 0.0, 0.0))]


def default_color(kind: str):
    return (HIGHLIGHT_COLORS if kind == HIGHLIGHT else LINE_COLORS)[0][1]


def colors_for(kind: str):
    return HIGHLIGHT_COLORS if kind == HIGHLIGHT else LINE_COLORS


def line_rects(words: list) -> list[pymupdf.Rect]:
    """Une las palabras seleccionadas en un rectángulo por línea.
    words: tuplas de page.get_text("words") (x0, y0, x1, y1, texto, bloque, línea, n)."""
    rects: list[pymupdf.Rect] = []
    keys: list = []
    for w in words:
        r = pymupdf.Rect(w[:4])
        k = (w[5], w[6])
        if rects:
            last = rects[-1]
            same_line = k == keys[-1] or (
                min(last.y1, r.y1) - max(last.y0, r.y0) > 0.6 * min(last.height, r.height)
                and r.x0 >= last.x0 - 1)
            if same_line:
                rects[-1] = last | r
                continue
        rects.append(r)
        keys.append(k)
    return rects


def add_mark(page: pymupdf.Page, kind: str, rects: list, color=None, author: str | None = None):
    """Añade una marca que cubre los rectángulos dados (coordenadas de la página visible)."""
    if not rects:
        return None
    color = tuple(color or default_color(kind))
    quads = [r.quad for r in rects]
    add = {HIGHLIGHT: page.add_highlight_annot, UNDERLINE: page.add_underline_annot,
           STRIKEOUT: page.add_strikeout_annot}[kind]
    a = add(quads=quads)
    a.set_colors(stroke=color)
    if kind == HIGHLIGHT:
        a.set_opacity(0.55)
    try:
        a.set_info(title=author or getpass.getuser(), subject=KINDS[kind][0])
    except Exception:
        pass
    a.update()
    return a


def _quad_rects(annot) -> list[pymupdf.Rect]:
    v = annot.vertices or []
    out = [pymupdf.Quad(v[k:k + 4]).rect for k in range(0, len(v) - 3, 4)]
    return out or [annot.rect]


def marks(page: pymupdf.Page) -> list[tuple[int, int, list]]:
    """(xref, tipo, rectángulos) de las marcas de texto de la página."""
    return [(a.xref, a.type[0], _quad_rects(a)) for a in page.annots(types=MARK_TYPES)]


def mark_at(page: pymupdf.Page, pt: pymupdf.Point):
    """Marca de texto bajo el punto (la más pequeña si hay varias)."""
    best, area = None, 1e18
    for xref, t, rects in marks(page):
        for r in rects:
            rr = r + (-1, -2, 1, 2)
            if rr.contains(pt):
                a = sum(x.width * x.height for x in rects)
                if a < area:
                    best, area = (xref, t, rects), a
    return best


def _annot(page, xref):
    return next((a for a in page.annots() if a.xref == xref), None)


def remove_mark(page: pymupdf.Page, xref: int) -> bool:
    a = _annot(page, xref)
    if a is None:
        return False
    page.delete_annot(a)
    return True


def recolor(page: pymupdf.Page, xref: int, color) -> bool:
    a = _annot(page, xref)
    if a is None:
        return False
    a.set_colors(stroke=tuple(color))
    a.update()
    return True


def remove_marks_in(page: pymupdf.Page, rects: list) -> int:
    """Quita las marcas que tocan los rectángulos (p. ej. el texto seleccionado)."""
    n = 0
    for xref, _, qr in marks(page):
        if any(q.intersects(r) for q in qr for r in rects):
            if remove_mark(page, xref):
                n += 1
    return n
