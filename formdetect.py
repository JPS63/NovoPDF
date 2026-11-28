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

"""Detección automática de campos en PDF sin formulario (p. ej. un Word convertido a PDF
o un impreso escaneado), al estilo de «Preparar formulario» de Acrobat.

Busca en cada página:
  * rayas de subrayado escritas con el teclado («Nombre: ________», «……………»);
  * líneas horizontales dibujadas (vectoriales o, en escaneados, en la imagen);
  * recuadros y celdas de tablas vacíos o con solo una etiqueta pequeña;
  * casillas: cuadraditos dibujados y los caracteres ☐ □ ❑ o «[ ]».
La etiqueta de cada campo (el texto de al lado, encima o debajo) le da nombre; si dice
«Firma», se propone un campo de firma. Todo se trabaja en coordenadas sin girar y se
devuelve en coordenadas visibles (las del visor).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import pymupdf

from . import forms

MIN_LINE = 36          # longitud mínima (pt) de una raya para ser campo
TOL = 2.0              # tolerancia (pt) al unir líneas
BOX_GLYPHS = "☐□❏❑❒▢▭⬜◻"
SIG_RE = re.compile(r"\b(firma|firmado|fdo|signature|sign\.?)\b", re.I)
DATE_RE = re.compile(r"\b(fecha|date)\b", re.I)


@dataclass
class Proposal:
    kind: str                  # forms.TEXT, CHECK o SIGNATURE
    rect: pymupdf.Rect         # coordenadas sin girar (se convierten al final)
    label: str = ""
    multiline: bool = False
    source: str = ""           # underscore, line, box, cell, check, glyph
    score: int = 0             # prioridad al resolver solapes

    @property
    def name(self) -> str:
        return forms.clean_name(self.label, "Campo" if self.kind != forms.CHECK else "Casilla")


# ====================================================================== utilidades
def _words(page, exclude=()) -> list:
    out = []
    for w in page.get_text("words"):
        r = pymupdf.Rect(w[:4])
        if r.is_empty or not w[4].strip():
            continue
        if any(_overlap(r, e) > 0.6 for e in exclude):
            continue                    # texto de un campo ya existente
        out.append((r, w[4], (w[5], w[6])))
    return out


def _overlap(a: pymupdf.Rect, b: pymupdf.Rect) -> float:
    """Fracción del área de a que cae dentro de b."""
    i = pymupdf.Rect(a) & b
    if i.is_empty or a.is_empty:
        return 0.0
    return i.get_area() / max(a.get_area(), 1e-6)


def _hoverlap(a0, a1, b0, b1) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _is_filler(text: str) -> bool:
    t = text.strip()
    return bool(t) and bool(re.fullmatch(r"[_.…·\-–—]+", t)) and (t.count("_") >= 3 or len(t) >= 5 or t.count("…") >= 2)


def _join_label(ws) -> str:
    return " ".join(w[1] for w in sorted(ws, key=lambda w: (round(w[0].y0 / 4), w[0].x0)))


def _label_left(words, r: pymupdf.Rect, max_gap=160) -> str:
    """Texto en la misma línea, justo a la izquierda del campo."""
    cy = (r.y0 + r.y1) / 2
    cands = [w for w in words if w[0].x1 <= r.x0 + 2 and r.x0 - w[0].x1 < max_gap
             and w[0].y0 - 3 <= cy + r.height * 0.3 and w[0].y1 + 3 >= cy - r.height * 0.3
             and not _is_filler(w[1])]
    if not cands:
        return ""
    # palabras contiguas desde el campo hacia la izquierda (mismo renglón)
    cands.sort(key=lambda w: -w[0].x1)
    line = cands[0][2]
    out, x = [], r.x0
    for w in cands:
        if w[2] != line and abs(w[0].y1 - cands[0][0].y1) > 3:
            continue
        if x - w[0].x1 > 40:
            break
        out.append(w)
        x = w[0].x0
        if w is not cands[0] and w[1].rstrip().endswith((".", ";")):
            out.pop()
            break
    return _join_label(out)


def _label_right(words, r: pymupdf.Rect, max_gap=40) -> str:
    cy = (r.y0 + r.y1) / 2
    cands = sorted([w for w in words if w[0].x0 >= r.x1 - 1 and w[0].x0 - r.x1 < max_gap + 200
                    and w[0].y0 - 2 <= cy <= w[0].y1 + 2 and not _is_filler(w[1])],
                   key=lambda w: w[0].x0)
    if not cands or cands[0][0].x0 - r.x1 > max_gap:
        return ""
    out, x = [], cands[0][0].x0
    for w in cands:
        if w[0].x0 - x > 12 or w[1] in BOX_GLYPHS:
            break
        out.append(w)
        x = w[0].x1
        if len(out) >= 8:
            break
    return _join_label(out)


def _label_above(words, r: pymupdf.Rect, max_gap=14) -> str:
    cands = [w for w in words if r.y0 - max_gap <= w[0].y1 <= r.y0 + 2
             and _hoverlap(w[0].x0, w[0].x1, r.x0, r.x1) > 0.5 * w[0].width and not _is_filler(w[1])]
    if not cands:
        return ""
    y = max(w[0].y1 for w in cands)
    return _join_label([w for w in cands if abs(w[0].y1 - y) < 4][:8])


def _label_below(words, r: pymupdf.Rect, max_gap=14) -> str:
    cands = [w for w in words if r.y1 - 2 <= w[0].y0 <= r.y1 + max_gap
             and _hoverlap(w[0].x0, w[0].x1, r.x0, r.x1) > 0.5 * w[0].width and not _is_filler(w[1])]
    if not cands:
        return ""
    y = min(w[0].y0 for w in cands)
    return _join_label([w for w in cands if abs(w[0].y0 - y) < 4][:8])


def _room_above(words, segs_h, x0, x1, y, default=18.0) -> float:
    """Altura libre por encima de y (hasta el texto o la línea anterior)."""
    top = y - 40
    for w in words:
        if w[0].y1 <= y - 1 and _hoverlap(w[0].x0, w[0].x1, x0, x1) > 1:
            top = max(top, w[0].y1)
    for s in segs_h:
        if s[1] < y - 3 and _hoverlap(s[0], s[2], x0, x1) > 4:
            top = max(top, s[1])
    return max(8.0, min(default, y - top - 1.5))


# ====================================================================== geometría de la página
def _vector_geometry(page, exclude=()):
    """Segmentos horizontales y verticales y recuadros pequeños (casillas) dibujados."""
    segs_h, segs_v, squares, boxes = [], [], [], []
    try:
        drawings = page.get_drawings()
    except Exception:
        return segs_h, segs_v, squares, boxes
    if len(drawings) > 6000:
        drawings = drawings[:6000]
    grown = [pymupdf.Rect(e) + (-1.5, -1.5, 1.5, 1.5) for e in exclude]
    for d in drawings:
        if grown and any(pymupdf.Rect(d["rect"]) in g for g in grown):
            continue                    # aspecto de un campo ya existente
        stroke = d.get("color") is not None and d.get("type") in ("s", "fs")
        fill = d.get("fill")
        for it in d.get("items", []):
            op = it[0]
            if op == "l":
                p, q = it[1], it[2]
                if abs(p.y - q.y) <= 1.0 and abs(p.x - q.x) >= 4:
                    segs_h.append((min(p.x, q.x), (p.y + q.y) / 2, max(p.x, q.x)))
                elif abs(p.x - q.x) <= 1.0 and abs(p.y - q.y) >= 4:
                    segs_v.append((min(p.y, q.y), (p.x + q.x) / 2, max(p.y, q.y)))
            elif op in ("re", "qu"):
                r = it[1].rect if op == "qu" else pymupdf.Rect(it[1])
                r.normalize()
                if r.is_empty and r.width < 1 and r.height < 1:
                    continue
                if r.height <= 2.5 and r.width >= 4:          # raya dibujada como rectángulo fino
                    if stroke or fill is not None:
                        segs_h.append((r.x0, (r.y0 + r.y1) / 2, r.x1))
                    continue
                if r.width <= 2.5 and r.height >= 4:
                    if stroke or fill is not None:
                        segs_v.append((r.y0, (r.x0 + r.x1) / 2, r.y1))
                    continue
                if 5 <= r.width <= 20 and 5 <= r.height <= 20 and abs(r.width - r.height) <= 3.5 and stroke:
                    squares.append(r)
                    continue
                if stroke:
                    segs_h += [(r.x0, r.y0, r.x1), (r.x0, r.y1, r.x1)]
                    segs_v += [(r.y0, r.x0, r.y1), (r.y0, r.x1, r.y1)]
                elif fill is not None and sum(fill[:3]) / 3 > 0.93 and r.width >= 20 and r.height >= 8:
                    boxes.append(r)                           # recuadro blanco sobre fondo de color
    return segs_h, segs_v, squares, boxes


def _binary_rows(buf: bytes, w: int, h: int, stride: int, thr: int) -> list[bytes]:
    """Filas de la imagen como b"1" (oscuro) / b"0" (claro): se buscan tramos con regex (rápido)."""
    table = bytes(49 if v < thr else 48 for v in range(256))
    return [buf[y * stride: y * stride + w].translate(table) for y in range(h)]


def _runs(rows: list[bytes], lo: int, hi: int, gap: int = 0) -> list[tuple[int, int, int]]:
    """(fila, inicio, fin) de los tramos oscuros de longitud lo..hi (admitiendo huecos de «gap»)."""
    pat = re.compile(rb"1(?:1|0{1,%d}(?=1))*" % gap if gap else rb"1+")
    out = []
    for y, row in enumerate(rows):
        if b"1" not in row:
            continue
        for m in pat.finditer(row):
            n = m.end() - m.start()
            if lo <= n <= hi:
                out.append((y, m.start(), m.end()))
    return out


def _stack(runs, max_thick: int):
    """Une tramos de filas contiguas (grosor de la línea): (centro, inicio, fin, grosor)."""
    runs = sorted(runs)
    used = [False] * len(runs)
    out = []
    for a in range(len(runs)):
        if used[a]:
            continue
        y, x0, x1 = runs[a]
        ys = [y]
        for b in range(a + 1, len(runs)):
            yb, bx0, bx1 = runs[b]
            if yb > ys[-1] + 1:
                break
            if not used[b] and _hoverlap(x0, x1, bx0, bx1) > 0.8 * min(x1 - x0, bx1 - bx0):
                used[b] = True
                ys.append(yb)
                x0, x1 = min(x0, bx0), max(x1, bx1)
        if len(ys) <= max_thick:
            out.append(((ys[0] + ys[-1]) / 2, x0, x1, len(ys)))
    return out


def _clear_beside(rows, c, thick, a, b) -> bool:
    """Una línea de verdad tiene a los lados (arriba y abajo) filas casi vacías; en una
    línea de texto, las filas vecinas también tienen tinta."""
    half = thick / 2
    n = len(rows)
    fracs = []
    for off in (-half - 2, half + 2):
        r = int(round(c + off))
        if 0 <= r < n:
            seg = rows[r][a:b]
            fracs.append(seg.count(b"1") / max(1, len(seg)))
    # una de las dos caras puede tener texto encima (lo ya escrito, una etiqueta)…
    return bool(fracs) and min(fracs) < 0.15


def _raster_geometry(page, dpi=100):
    """Líneas y casillas de una página escaneada (a partir de la imagen)."""
    segs_h, segs_v, squares = [], [], []
    try:
        pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY, alpha=False, annots=False)
    except Exception:
        return segs_h, segs_v, squares
    w, h = pix.width, pix.height
    k = 72.0 / dpi
    thr = 190                       # líneas finas (0,5 pt) quedan grises al reducir la imagen
    rows = _binary_rows(pix.samples, w, h, pix.stride, thr)
    # columnas = filas de la imagen girada
    try:
        from PIL import Image
        im = Image.frombytes("L", (w, h), bytes(pix.samples), "raw", "L", pix.stride)
        t = im.transpose(Image.Transpose.TRANSPOSE)
        cols = _binary_rows(t.tobytes(), h, w, h, thr)
    except Exception:
        cols = []
    big = int(MIN_LINE / k * 0.9)
    for yc, x0, x1, t in _stack(_runs(rows, big, w, gap=1), 6):
        if _clear_beside(rows, yc, t, x0, x1):
            segs_h.append((x0 * k, (yc + 0.5) * k, x1 * k))
    for xc, y0, y1, t in _stack(_runs(cols, int(10 / k), h, gap=1), 6):
        if _clear_beside(cols, xc, t, y0, y1):
            segs_v.append((y0 * k, (xc + 0.5) * k, y1 * k))
    # casillas pequeñas: cuadrados de 5–20 pt formados por tramos cortos
    lo, hi = int(6.5 / k), int(20 / k) + 2
    sh = [(yc * k, x0 * k, x1 * k) for yc, x0, x1, _ in _stack(_runs(rows, lo, hi), 4)]
    sv = [(xc * k, y0 * k, y1 * k) for xc, y0, y1, _ in _stack(_runs(cols, lo, hi), 4)] if cols else []
    sh.sort()
    for i, (y, x0, x1) in enumerate(sh):
        for (yb, x0b, x1b) in sh[i + 1:]:
            hgt = yb - y
            if hgt > 21:
                break
            if hgt >= 6 and abs(x0b - x0) < 2 and abs(x1b - x1) < 2 and abs(hgt - (x1 - x0)) < 2.5:
                left = any(abs(vx - x0) < 2 and vy0 <= y + 2 and vy1 >= yb - 2 for (vx, vy0, vy1) in sv)
                right = any(abs(vx - x1) < 2 and vy0 <= y + 2 and vy1 >= yb - 2 for (vx, vy0, vy1) in sv)
                if left and right and _isolated_box(pix, x0 / k, y / k, x1 / k, yb / k):
                    squares.append(pymupdf.Rect(x0, y, x1, yb))
    return segs_h, segs_v, _dedup_rects(squares)


def _isolated_box(pix, x0, y0, x1, y1, thr=190) -> bool:
    """Una casilla de verdad está vacía por dentro y sin nada pegado arriba ni abajo
    (así no se confunden letras como «D» u «O» con casillas). x0/x1: píxeles del borde
    (fin exclusivo); y0/y1: centro de las líneas de arriba y abajo."""
    buf, s, w, h = pix.samples, pix.stride, pix.width, pix.height

    def dark_frac(ax0, ay0, ax1, ay1):
        n = d = 0
        for yy in range(max(0, int(round(ay0))), min(h, int(round(ay1)))):
            row = yy * s
            for xx in range(max(0, int(round(ax0))), min(w, int(round(ax1)))):
                n += 1
                d += buf[row + xx] < thr
        return d / n if n else 0
    if dark_frac(x0 + 2.5, y0 + 2, x1 - 2.5, y1 - 1.5) > 0.06:
        return False
    # bandas alrededor: arriba y abajo libres, y al menos un lado libre
    # (la etiqueta suele ir pegada a un lado)
    top = dark_frac(x0 - 2, y0 - 4, x1 + 2, y0 - 1.5)
    bottom = dark_frac(x0 - 2, y1 + 2, x1 + 2, y1 + 4.5)
    left = dark_frac(x0 - 4, y0, x0 - 1, y1)
    right = dark_frac(x1 + 1, y0, x1 + 4, y1)
    return top < 0.05 and bottom < 0.05 and min(left, right) < 0.05


def _dedup_rects(rs):
    out = []
    for r in rs:
        if not any(_overlap(r, o) > 0.5 for o in out):
            out.append(r)
    return out


def _merge_segments(segs):
    """Une segmentos colineales que se tocan (y, x0, x1 ordenados)."""
    segs = sorted(segs, key=lambda s: (round(s[1] / TOL), s[0]))
    out = []
    for s in segs:
        if out and abs(out[-1][1] - s[1]) <= TOL and s[0] <= out[-1][2] + TOL:
            o = out[-1]
            out[-1] = (o[0], (o[1] + s[1]) / 2, max(o[2], s[2]))
        else:
            out.append(s)
    return out


def _cells(segs_h, segs_v, limit=400):
    """Celdas mínimas cerradas por líneas horizontales y verticales."""
    if len(segs_h) > limit or len(segs_v) > limit:
        return []
    xs = sorted({round(v[1], 1) for v in segs_v})
    ys = sorted({round(h[1], 1) for h in segs_h})
    xs = _cluster(xs)
    ys = _cluster(ys)

    def has_h(y, x0, x1):
        return any(abs(s[1] - y) <= TOL and s[0] <= x0 + TOL and s[2] >= x1 - TOL for s in segs_h)

    def has_v(x, y0, y1):
        return any(abs(s[1] - x) <= TOL and s[0] <= y0 + TOL and s[2] >= y1 - TOL for s in segs_v)

    cells = []
    for a, y0 in enumerate(ys):
        for xa_i, x0 in enumerate(xs):
            # buscar la celda más pequeña que empieza en (x0, y0)
            found = None
            for x1 in xs[xa_i + 1:]:
                if not has_h(y0, x0, x1):
                    break
                for y1 in ys[a + 1:]:
                    if not has_v(x0, y0, y1):
                        break
                    if has_v(x1, y0, y1) and has_h(y1, x0, x1):
                        found = pymupdf.Rect(x0, y0, x1, y1)
                        break
                if found:
                    break
            if found and found.width >= 5 and found.height >= 5:
                cells.append(found)
    return cells


def _cluster(vals, tol=TOL):
    out = []
    for v in vals:
        if out and v - out[-1] <= tol:
            continue
        out.append(v)
    return out


# ====================================================================== detección
def detect_page(page: pymupdf.Page, scanned: bool | None = None) -> list[Proposal]:
    pr = page.rect if not page.rotation else pymupdf.Rect(0, 0, page.mediabox.width, page.mediabox.height)
    existing = [pymupdf.Rect(w.rect) for w in (page.widgets() or [])]
    words = _words(page, existing)
    props: list[Proposal] = []

    # --- 1. rayas escritas con el teclado («____», «……», «.......»)
    props += _underscore_fields(page, words)

    # --- 2. geometría dibujada
    segs_h, segs_v, squares, boxes = _vector_geometry(page, existing)
    if scanned is None:
        scanned = len(segs_h) + len(segs_v) < 2 and bool(page.get_images()) and _image_covers(page)
    if scanned:
        rh, rv, rsq = _raster_geometry(page)
        segs_h += rh
        segs_v += rv
        squares += rsq
    segs_h = [s for s in _merge_segments(segs_h)]
    segs_v = [(s[0], s[1], s[2]) for s in _merge_vsegments(segs_v)]

    # casillas
    for r in _dedup_rects(squares):
        if any(_overlap(r, w[0]) > 0.5 for w in words if w[1] not in BOX_GLYPHS):
            continue
        props.append(Proposal(forms.CHECK, pymupdf.Rect(r), _label_right(words, r) or _label_left(words, r, 60),
                              source="check", score=5))
    props += _glyph_checks(page, words)

    # celdas y recuadros
    cells = _cells(segs_h, segs_v) + [b for b in boxes]
    cell_edges = []
    for c in cells:
        cell_edges.append((c.x0, c.y0, c.x1))
        cell_edges.append((c.x0, c.y1, c.x1))
        p = _cell_field(c, words, pr, cells)
        if p:
            props.append(p)

    # --- 3. líneas horizontales sueltas (no son borde de una celda)
    for s in segs_h:
        x0, y, x1 = s
        if x1 - x0 < MIN_LINE:
            continue
        if any(abs(e[1] - y) <= TOL and e[0] <= x0 + TOL and e[2] >= x1 - TOL for e in cell_edges):
            continue
        if any(abs(v[0] - y) <= TOL or abs(v[2] - y) <= TOL for v in segs_v if x0 - TOL <= v[1] <= x1 + TOL):
            # está unida a una línea vertical: borde de un recuadro abierto o de una tabla
            if sum(1 for v in segs_v if x0 - TOL <= v[1] <= x1 + TOL and (abs(v[0] - y) <= TOL or abs(v[2] - y) <= TOL)) >= 2:
                continue
        if x1 - x0 > pr.width * (0.85 if not words else 0.92):
            continue                             # filete de página (separador)
        spans = _free_spans(words, x0, x1, y)
        if x1 - x0 > pr.width * 0.7 and (len(spans) != 1 or spans[0] != (x0, x1)):
            continue                             # raya larga bajo un título o un párrafo: separador
        for a, b in spans:
            if b - a < MIN_LINE:
                continue
            p = _line_field(a, b, y, words, segs_h)
            if p:
                props.append(p)

    # --- 4. resolver solapes y descartar lo ya ocupado por campos existentes
    props = [p for p in props if not any(_overlap(p.rect, e) > 0.3 or _overlap(e, p.rect) > 0.3 for e in existing)]
    props.sort(key=lambda p: (-p.score, p.rect.y0, p.rect.x0))
    out = []
    for p in props:
        p.rect = pymupdf.Rect(p.rect) & pr
        if p.rect.is_empty or p.rect.width < 5 or p.rect.height < 5:
            continue
        if any(_overlap(p.rect, o.rect) > 0.25 or _overlap(o.rect, p.rect) > 0.25 for o in out):
            continue
        out.append(p)
    out.sort(key=lambda p: (round(p.rect.y0 / 6), p.rect.x0))
    return out


def _merge_vsegments(segs):
    segs = sorted(segs, key=lambda s: (round(s[1] / TOL), s[0]))
    out = []
    for s in segs:
        if out and abs(out[-1][1] - s[1]) <= TOL and s[0] <= out[-1][2] + TOL:
            o = out[-1]
            out[-1] = (o[0], (o[1] + s[1]) / 2, max(o[2], s[2]))
        else:
            out.append(s)
    return out


def _image_covers(page) -> bool:
    try:
        area = page.rect.get_area()
        for img in page.get_image_info():
            if pymupdf.Rect(img["bbox"]).get_area() > 0.5 * area:
                return True
    except Exception:
        pass
    return False


def _underscore_fields(page, words) -> list[Proposal]:
    """Campos sobre «______» o «………» (a nivel de carácter: el relleno puede ir pegado a la etiqueta)."""
    out = []
    try:
        raw = page.get_text("rawdict", flags=0)
    except Exception:
        return out
    for b in raw.get("blocks", []):
        for ln in b.get("lines", []):
            chars = []
            for sp in ln.get("spans", []):
                for ch in sp.get("chars", []):
                    chars.append((ch["c"], pymupdf.Rect(ch["bbox"]), sp.get("size", 10), sp.get("ascender", 1), sp.get("descender", -0.2)))
            if not chars:
                continue
            line_text = "".join(c[0] for c in chars)
            date_names = _date_parts(line_text)
            for m in re.finditer(r"_{3,}|\.{5,}|…{2,}|(?:\. ){4,}\.?", line_text):
                a, z = m.start(), m.end()
                seg = chars[a:z]
                r = pymupdf.Rect(seg[0][1])
                for c in seg:
                    r |= c[1]
                if r.width < 12:
                    continue
                after = line_text[z:].strip()
                before = line_text[:a].strip()
                # índice («Capítulo 3 ........ 12»): relleno seguido solo de un número
                if m.group(0)[0] in ".…" and re.fullmatch(r"\d{1,4}", after or "-") and before:
                    continue
                size = seg[0][2]
                base = max(c[1].y1 for c in seg) if m.group(0)[0] == "_" else max(c[1].y1 for c in seg) - size * 0.18
                h = min(max(size * 1.45, 12), 20)
                rect = pymupdf.Rect(r.x0, base - h, r.x1, base + 1)
                label = before.rstrip("_.… ").strip()
                if label:
                    # la etiqueta es el final del texto anterior (tras el último relleno o punto)
                    label = re.split(r"[_…]{2,}|\.{3,}", label)[-1].strip()
                    label = re.split(r"(?<=[.;])\s+", label)[-1].strip() if len(label) > 50 else label
                if not label and after:
                    label = re.split(r"[_…]{2,}|\.{3,}", after)[0].strip()[:40]
                if not label:
                    label = _label_above(words, rect, 16) or _label_below(words, rect, 12)
                if a in date_names:
                    label = date_names[a]
                elif label.lower() in STOPWORDS or len(label) <= 2:
                    label = ""                    # «de», «a»… no sirven de nombre
                if not label:
                    label = _label_above(words, rect, 16) or _label_below(words, rect, 12)
                kind = forms.SIGNATURE if SIG_RE.search(label or "") else forms.TEXT
                if kind == forms.SIGNATURE:
                    rect = pymupdf.Rect(rect.x0, base - max(36, h), rect.x1, base + 1)
                out.append(Proposal(kind, rect, label, source="underscore", score=8))
    return out


STOPWORDS = {"de", "del", "a", "al", "y", "e", "o", "u", "en", "el", "la", "los", "las", "por", "con", "que", "the", "of", "and"}


def _date_parts(text: str) -> dict:
    """«a ___ de ______ de 20__» → {posición: «Día» / «Mes» / «Año»}."""
    out = {}
    m = re.search(r"(?:\ba|\bel d[ií]a)\s*(_{2,}|\.{3,}|…+)\s*de\s*(_{2,}|\.{3,}|…+)\s*(?:de|del)\s*(?:20|19)?\s*(_{2,}|\.{3,}|…+)", text, re.I)
    if m:
        for g, name in zip((1, 2, 3), ("Día", "Mes", "Año")):
            out[m.start(g)] = name
    return out


def _glyph_checks(page, words) -> list[Proposal]:
    out = []
    try:
        raw = page.get_text("rawdict", flags=0)
    except Exception:
        return out
    for b in raw.get("blocks", []):
        for ln in b.get("lines", []):
            chars = [(ch["c"], pymupdf.Rect(ch["bbox"]), sp.get("size", 10))
                     for sp in ln.get("spans", []) for ch in sp.get("chars", [])]
            text = "".join(c[0] for c in chars)
            for m in re.finditer(r"[%s]|\[\s?\]|\(\s{1,2}\)" % re.escape(BOX_GLYPHS), text):
                seg = chars[m.start():m.end()]
                r = pymupdf.Rect(seg[0][1])
                for c in seg:
                    r |= c[1]
                size = seg[0][2]
                side = min(max(size * 0.8, 7), 16)
                cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2 + size * 0.05
                box = pymupdf.Rect(cx - side / 2, cy - side / 2, cx + side / 2, cy + side / 2)
                label = text[m.end():].strip()
                label = re.split(r"\s{2,}|[%s]|\[\s?\]" % re.escape(BOX_GLYPHS), label)[0].strip()[:50]
                if not label:
                    label = _label_left(words, box, 60)
                out.append(Proposal(forms.CHECK, box, label, source="glyph", score=9))
    return out


def _words_in(words, r: pymupdf.Rect, frac=0.5):
    return [w for w in words if _overlap(w[0], r) > frac]


def _cell_field(c: pymupdf.Rect, words, pr, cells) -> Proposal | None:
    """Campo dentro de una celda o recuadro: vacío, o con una etiqueta pequeña arriba o a la izquierda."""
    if c.width < 12 or c.height < 7:
        return None
    if c.get_area() > 0.45 * pr.get_area() or c.height > 260:
        return None
    # una celda que contiene otras no es un campo (es un marco)
    if any(o != c and _overlap(o, c) > 0.95 and o.get_area() < c.get_area() * 0.9 for o in cells):
        return None
    inside = _words_in(words, c)
    if 5 <= c.width <= 20 and 5 <= c.height <= 20 and abs(c.width - c.height) <= 3.5 and not inside:
        return Proposal(forms.CHECK, pymupdf.Rect(c), _label_right(words, c) or _label_left(words, c, 60),
                        source="check", score=6)
    pad = 1.5
    if not inside:
        if c.width < 24:
            return None
        label = _label_left(words, c, 120) or _label_above(words, c, 16) or _column_header(words, c, cells)
        kind = forms.SIGNATURE if SIG_RE.search(label or "") and c.height >= 24 else forms.TEXT
        r = pymupdf.Rect(c.x0 + pad, c.y0 + pad, c.x1 - pad, c.y1 - pad)
        return Proposal(kind, r, label, multiline=kind == forms.TEXT and c.height > 34, source="cell", score=6)
    if len(inside) > 8:
        return None
    lab = pymupdf.Rect(inside[0][0])
    for w in inside:
        lab |= w[0]
    label = _join_label(inside)
    if _is_filler(label):
        return None
    # etiqueta arriba y espacio libre debajo
    free_below = c.y1 - lab.y1
    free_right = c.x1 - lab.x1
    if free_below >= 11 and lab.y0 - c.y0 < c.height * 0.5:
        r = pymupdf.Rect(c.x0 + pad, lab.y1 + 0.5, c.x1 - pad, c.y1 - pad)
        kind = forms.SIGNATURE if SIG_RE.search(label) and r.height >= 22 else forms.TEXT
        return Proposal(kind, r, label, multiline=kind == forms.TEXT and r.height > 34, source="cell", score=6)
    # etiqueta a la izquierda y espacio libre a la derecha (no en la cabecera de una columna
    # de celdas vacías: ahí el campo va en las celdas de debajo)
    header = any(abs(o.x0 - c.x0) <= TOL and abs(o.x1 - c.x1) <= TOL and abs(o.y0 - c.y1) <= TOL
                 and not _words_in(words, o) for o in cells)
    if free_right >= 40 and lab.x0 - c.x0 < c.width * 0.5 and not header:
        r = pymupdf.Rect(lab.x1 + 3, c.y0 + pad, c.x1 - pad, c.y1 - pad)
        kind = forms.SIGNATURE if SIG_RE.search(label) and r.height >= 22 else forms.TEXT
        return Proposal(kind, r, label, multiline=kind == forms.TEXT and r.height > 34, source="cell", score=6)
    return None


def _column_header(words, c: pymupdf.Rect, cells) -> str:
    """En una tabla, el texto de la celda de cabecera de la misma columna."""
    above = [o for o in cells if abs(o.x0 - c.x0) <= TOL and abs(o.x1 - c.x1) <= TOL and o.y1 <= c.y0 + TOL]
    for o in sorted(above, key=lambda o: -o.y0):
        ins = _words_in(words, o)
        if ins:
            return _join_label(ins)
    return ""


def _free_spans(words, x0, x1, y):
    """Partes de una raya que no tienen texto escrito encima (si lo tienen, ya está rellena
    o es un subrayado de texto)."""
    occ = []
    for w in words:
        r = w[0]
        if y - 16 <= r.y1 <= y + 2.5 and r.y0 < y and _hoverlap(r.x0, r.x1, x0, x1) > 0.3 * r.width:
            if _is_filler(w[1]):
                continue
            occ.append((r.x0 - 2, r.x1 + 2))
    occ.sort()
    spans, cur = [], x0
    for a, b in occ:
        if a > cur:
            spans.append((cur, min(a, x1)))
        cur = max(cur, b)
    if cur < x1:
        spans.append((cur, x1))
    return spans


def _line_field(x0, x1, y, words, segs_h) -> Proposal | None:
    r = pymupdf.Rect(x0, y - 1, x1, y)
    label = _label_left(words, pymupdf.Rect(x0, y - 14, x1, y))
    below = _label_below(words, r, 14)
    above = ""
    if not label:
        above = _label_above(words, pymupdf.Rect(x0, y - 22, x1, y - 21), 8)
    lab = label or below or above
    sig = bool(SIG_RE.search(lab or ""))
    h = _room_above(words, segs_h, x0, x1, y, 40 if sig else 18)
    if sig and h < 22:
        sig = False
    rect = pymupdf.Rect(x0, y - h, x1, y - 0.8)
    return Proposal(forms.SIGNATURE if sig else forms.TEXT, rect, lab, source="line", score=4)


# ====================================================================== documento
def detect(doc: pymupdf.Document, pages=None, progress=None) -> dict[int, list[Proposal]]:
    """{página: [propuestas en coordenadas visibles]}."""
    pages = range(doc.page_count) if pages is None else pages
    out = {}
    pages = list(pages)
    for k, i in enumerate(pages):
        page = doc[i]
        try:
            props = detect_page(page)
        except Exception:
            props = []
        if page.rotation:
            for p in props:
                p.rect = pymupdf.Rect(p.rect * page.rotation_matrix).normalize()
        if props:
            out[i] = props
        if progress:
            progress(k + 1, len(pages))
    return out


def apply(doc: pymupdf.Document, found: dict[int, list[Proposal]]) -> int:
    """Crea los campos propuestos. Devuelve cuántos."""
    taken = forms.existing_names(doc)
    n = 0
    for i, props in sorted(found.items()):
        for p in props:
            label = p.label
            if p.kind == forms.TEXT and DATE_RE.search(label or "") and not label:
                label = "Fecha"
            try:
                forms.add_field(doc, i, p.kind, p.rect, name=p.name, label=_tooltip(p.label),
                                multiline=p.multiline, border=False, taken=taken)
                n += 1
            except Exception:
                continue
    return n


def _tooltip(label: str) -> str:
    t = re.sub(r"\s+", " ", (label or "")).strip(" :_.…")
    return t[:80]


def suggest_label(page: pymupdf.Page, rect: pymupdf.Rect, kind: str) -> str:
    """Etiqueta para un campo dibujado a mano (rect visible): el texto de al lado."""
    r = pymupdf.Rect(rect * page.derotation_matrix).normalize() if page.rotation else pymupdf.Rect(rect)
    existing = [pymupdf.Rect(w.rect) for w in (page.widgets() or [])]
    words = _words(page, existing)
    if kind in (forms.CHECK, forms.RADIO):
        return _label_right(words, r) or _label_left(words, r, 60)
    return (_label_left(words, r, 160) or _label_above(words, r, 16) or _label_below(words, r, 14))
