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

"""Exportar a Word (.docx) y a Excel (.xlsx).

Word: el documento se reconstruye como texto que fluye (no como cuadros colocados a mano),
para que se pueda seguir editando con comodidad:
  - párrafos con su fuente, tamaño, negrita, cursiva, color, superíndice;
  - alineación (izquierda, centrada, derecha, justificada), sangrías y espacio entre párrafos;
  - viñetas y listas numeradas con sangría francesa;
  - resaltados, subrayados y tachados (anotaciones del PDF y subrayados dibujados por Word);
  - tablas (detectadas por PyMuPDF) como tablas de Word;
  - imágenes en su sitio;
  - lo que se repite arriba y abajo de cada página va al encabezado y pie de Word
    (el número de página como campo);
  - un salto de página por cada página del PDF (opcional).
Excel: las tablas del PDF pasan a celdas; los números, importes, porcentajes y fechas en
formato español se convierten en valores de verdad. Si el PDF no tiene tablas con líneas,
el texto se reparte en columnas según su posición.
"""
from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass, field

import pymupdf

log = logging.getLogger("novopdf.exportar")

TEXT_FLAGS = (pymupdf.TEXT_PRESERVE_LIGATURES | pymupdf.TEXT_PRESERVE_WHITESPACE
              | pymupdf.TEXT_MEDIABOX_CLIP | pymupdf.TEXT_DEHYPHENATE)
BULLETS = set("•●○◦▪■□◆◇►▸‣⁃–-*·o")
BULLET_MAP = {"": "•", "": "▪", "": "►", "": "❖", "": "✓", "·": "•"}


class Cancelled(Exception):
    pass


# ---------------------------------------------------------------- nombres de fuente
def word_font_name(pdf_font: str) -> str:
    """'ABCDEF+TimesNewRomanPS-BoldMT' -> 'Times New Roman'."""
    from . import fonts
    k, disp = fonts.pdf_font_family(pdf_font or "")
    k2 = fonts.SYNONYMS.get(k, k)
    known = {"timesnewroman": "Times New Roman", "arial": "Arial", "couriernew": "Courier New",
             "calibri": "Calibri", "cambria": "Cambria", "symbol": "Symbol"}
    if k2 in known:
        return known[k2]
    low = (pdf_font or "").lower()
    if "nimbusroman" in low or low.startswith("times"):
        return "Times New Roman"
    if "nimbussans" in low or "helvetica" in low:
        return "Arial"
    if "nimbusmono" in low or "courier" in low:
        return "Courier New"
    return disp or "Calibri"


# ---------------------------------------------------------------- modelo de página
@dataclass
class Ch:
    c: str
    x0: float
    x1: float
    y: float          # línea base
    font: str
    size: float
    color: int
    flags: int
    hl: tuple | None = None      # color de resaltado
    ul: bool = False
    st: bool = False


@dataclass
class Line:
    chars: list
    x0: float
    x1: float
    y: float
    top: float
    bottom: float

    @property
    def text(self) -> str:
        return "".join(c.c for c in self.chars)

    @property
    def size(self) -> float:
        s = [c.size for c in self.chars if not c.c.isspace()]
        return sorted(s)[len(s) // 2] if s else 10.0


@dataclass
class Para:
    lines: list
    kind: str = "text"            # text | bullet
    marker: list = field(default_factory=list)   # caracteres de la viñeta / número
    align: str = "left"
    left: float = 0.0
    first: float = 0.0
    space_before: float = 0.0
    leading: float = 0.0

    @property
    def top(self):
        return min(l.top for l in self.lines)

    @property
    def y(self):
        return self.lines[0].y


@dataclass
class Item:
    """Elemento de una página en orden de lectura: párrafo, tabla o imagen."""
    kind: str                     # para | table | image
    top: float
    obj: object
    x0: float = 0.0
    x1: float = 0.0
    bottom: float = 0.0


def _annot_marks(page):
    """Rectángulos de resaltado / subrayado / tachado del PDF."""
    out = []
    try:
        for a in page.annots(types=(pymupdf.PDF_ANNOT_HIGHLIGHT, pymupdf.PDF_ANNOT_UNDERLINE,
                                    pymupdf.PDF_ANNOT_STRIKE_OUT, pymupdf.PDF_ANNOT_SQUIGGLY)):
            v = a.vertices or []
            rects = [pymupdf.Quad(v[k:k + 4]).rect for k in range(0, len(v) - 3, 4)] or [a.rect]
            col = (a.colors or {}).get("stroke") or (1, 1, 0)
            kind = {pymupdf.PDF_ANNOT_HIGHLIGHT: "hl", pymupdf.PDF_ANNOT_UNDERLINE: "ul",
                    pymupdf.PDF_ANNOT_SQUIGGLY: "ul", pymupdf.PDF_ANNOT_STRIKE_OUT: "st"}[a.type[0]]
            for r in rects:
                out.append((kind, r, tuple(col)))
    except Exception:
        pass
    return out


def _drawn_underlines(page):
    """Líneas horizontales finas dibujadas (subrayados de Word) y rellenos de color (resaltados)."""
    lines, fills = [], []
    try:
        for d in page.get_drawings():
            r = pymupdf.Rect(d["rect"])
            if r.width < 3:
                continue
            if r.height <= 1.6 and (d.get("color") or d.get("fill")) is not None:
                lines.append(r)
            elif d.get("fill") and r.height < 30 and d.get("type") in ("f", "fs"):
                col = tuple(d["fill"])
                if len(col) == 3 and not all(x > 0.97 for x in col):
                    fills.append((r, col))
    except Exception:
        pass
    return lines, fills


def _lines_of_page(page, exclude: list):
    """Líneas de texto de la página (las que están dentro de tablas se excluyen)."""
    from .editing import merged_text_blocks
    marks = _annot_marks(page)
    ulines, fills = _drawn_underlines(page)
    out = []
    for b in merged_text_blocks(page):
        for ln in b["lines"]:
            d = ln.get("dir", (1, 0))
            if abs(d[0] - 1) > 1e-3:
                continue
            chars = []
            for s in ln["spans"]:
                for c in s.get("chars", []):
                    bb = c["bbox"]
                    chars.append(Ch(c["c"], bb[0], bb[2], c["origin"][1], s.get("font", ""),
                                    float(s.get("size", 10)), int(s.get("color", 0)), int(s.get("flags", 0))))
            if not chars or not "".join(ch.c for ch in chars).strip():
                continue
            x0 = min(ch.x0 for ch in chars)
            x1 = max(ch.x1 for ch in chars)
            r = pymupdf.Rect(ln["bbox"])
            cy = (r.y0 + r.y1) / 2
            if any(t.contains(pymupdf.Point((x0 + x1) / 2, cy)) for t in exclude):
                continue
            # marcas
            for ch in chars:
                if ch.c.isspace():
                    continue
                pt = pymupdf.Point((ch.x0 + ch.x1) / 2, ch.y - ch.size * 0.3)
                for kind, mr, col in marks:
                    if mr.contains(pt):
                        if kind == "hl":
                            ch.hl = col
                        elif kind == "ul":
                            ch.ul = True
                        else:
                            ch.st = True
                for fr, col in fills:
                    if fr.contains(pt):
                        ch.hl = col
                for u in ulines:
                    if u.x0 - 0.5 <= (ch.x0 + ch.x1) / 2 <= u.x1 + 0.5 and ch.y - 0.5 <= u.y0 <= ch.y + ch.size * 0.35:
                        ch.ul = True
            # espacios subrayados entre palabras subrayadas
            for k in range(1, len(chars) - 1):
                if chars[k].c.isspace():
                    if chars[k - 1].ul and chars[k + 1].ul:
                        chars[k].ul = True
                    if chars[k - 1].hl is not None and chars[k - 1].hl == chars[k + 1].hl:
                        chars[k].hl = chars[k - 1].hl
            out.append(Line(chars, x0, x1, chars[0].y, r.y0, r.y1))
    out.sort(key=lambda l: (round(l.y, 0), l.x0))
    # unir los trozos de un mismo renglón separados (p. ej. «1.» + tabulador + texto)
    merged = []
    for l in out:
        if merged and abs(merged[-1].y - l.y) < 1.0 and l.x0 >= merged[-1].x1 - 1:
            m = merged[-1]
            gap = l.x0 - m.x1
            sep = []
            if gap > 0.25 * l.size and not m.text.endswith(" ") and not l.text.startswith(" "):
                sep = [Ch("\t" if gap > 1.5 * l.size else " ", m.x1, l.x0, m.y, m.chars[-1].font,
                          m.chars[-1].size, m.chars[-1].color, m.chars[-1].flags)]
            merged[-1] = Line(m.chars + sep + l.chars, m.x0, l.x1, m.y, min(m.top, l.top), max(m.bottom, l.bottom))
        else:
            merged.append(l)
    return merged


def _strip_lead(line: Line) -> Line:
    k = 0
    while k < len(line.chars) and line.chars[k].c.isspace():
        k += 1
    ch = line.chars[k:]
    return Line(ch, ch[0].x0 if ch else line.x0, line.x1, line.y, line.top, line.bottom)


def _split_marker(line: Line):
    """Separa una viñeta o número inicial («•», «1.», «a)», «iii.») del texto."""
    t = line.text.lstrip()
    m = re.match(r"^(\d{1,3}[.)]|[a-zA-Z][.)]|[ivxIVX]{1,5}[.)]|\S)(\s+|(?=\S))", t)
    if not m:
        return None, line
    tok = m.group(1)
    is_bullet = len(tok) == 1 and tok in BULLETS
    is_num = bool(re.match(r"^(\d{1,3}[.)]|[a-zA-Z][.)]|[ivxIVX]{1,5}[.)])$", tok))
    if not (is_bullet or is_num):
        return None, line
    chars = _strip_lead(line).chars
    n = len(tok)
    marker = chars[:n]
    rest = chars[n:]
    while rest and rest[0].c.isspace():
        rest = rest[1:]
    if not rest:
        return None, line
    gap = rest[0].x0 - marker[-1].x1
    if is_num and gap < 0.45 * line.size:
        return None, line              # «1.5 millones», no es una lista
    if tok in ("o", "-", "*") and gap < 0.8 * line.size:
        return None, line              # «o» o «-» seguidos de texto normal
    return marker, Line(rest, rest[0].x0, line.x1, line.y, line.top, line.bottom)


def _paragraphs(lines: list, left_margin: float, right_edge: float, page_w: float) -> list[Para]:
    """Agrupa líneas en párrafos (por sangría, separación y longitud de la línea anterior)."""
    paras: list[Para] = []
    cur: Para | None = None
    prev: Line | None = None
    for ln in lines:
        marker, body = _split_marker(ln)
        size = ln.size
        new = True
        if cur is not None and prev is not None and marker is None:
            gap = ln.y - prev.y
            lead = cur.leading or size * 1.2
            same_flow = 0 < gap <= max(lead, size * 1.2) * 1.35
            prev_full = prev.x1 >= right_edge - max(2.5 * size, 18)
            cont_x = cur.lines[1].x0 if len(cur.lines) > 1 else None
            if cur.kind == "bullet":
                aligned = abs(ln.x0 - cur.lines[0].x0) < 3 or (cont_x is not None and abs(ln.x0 - cont_x) < 3)
            else:
                aligned = abs(ln.x0 - (cont_x if cont_x is not None else cur.lines[0].x0)) < 3 or (
                    cont_x is None and ln.x0 < cur.lines[0].x0 + 1 and ln.x0 > cur.lines[0].x0 - 40)
            if same_flow and prev_full and aligned and abs(size - cur.lines[0].size) < 1.5:
                new = False
        if new:
            cur = Para([body if marker else ln], kind="bullet" if marker else "text", marker=marker or [])
            if prev is not None:
                cur.space_before = max(0.0, ln.top - prev.bottom)
            paras.append(cur)
        else:
            if len(cur.lines) == 1:
                cur.leading = ln.y - cur.lines[0].y
            cur.lines.append(ln)
        prev = ln
    # alineación y sangrías
    for p in paras:
        first = p.lines[0]
        cont = p.lines[1] if len(p.lines) > 1 else first
        text_left = cont.x0 if len(p.lines) > 1 else first.x0
        if p.kind == "bullet":
            p.left = max(0.0, first.x0 - left_margin)
            p.first = (p.marker[0].x0 - first.x0) if p.marker else 0.0
        else:
            p.left = max(0.0, text_left - left_margin)
            p.first = first.x0 - text_left
        R = max(l.x1 for l in p.lines)
        body = p.lines[:-1]
        if len(p.lines) >= 2 and all(abs(l.x1 - right_edge) < 3 for l in body) and \
                any(len(l.text.split()) > 3 for l in body):
            p.align = "justify"
        else:
            mid_page = (left_margin + right_edge) / 2
            centers = [(l.x0 + l.x1) / 2 for l in p.lines]
            widths = [l.x1 - l.x0 for l in p.lines]
            if all(abs(c - mid_page) < 6 for c in centers) and max(widths) < (right_edge - left_margin) * 0.85 \
                    and first.x0 > left_margin + 15:
                p.align = "center"
                p.left = p.first = 0.0
            elif all(abs(l.x1 - right_edge) < 3 for l in p.lines) and first.x0 > mid_page:
                p.align = "right"
                p.left = p.first = 0.0
        if not p.leading:
            p.leading = first.size * 1.2
    return paras


def _repeated_lines(doc, pages: list[int]):
    """Textos que se repiten arriba o abajo en la mayoría de páginas (encabezado y pie)."""
    if len(pages) < 2:
        return set(), None, None
    from collections import Counter
    seen = Counter()
    sample = {}
    for pno in pages:
        page = doc[pno]
        h = page.rect.height
        keys = set()
        for b in page.get_text("dict", flags=TEXT_FLAGS)["blocks"]:
            if b.get("type") != 0:
                continue
            for ln in b["lines"]:
                r = pymupdf.Rect(ln["bbox"])
                if r.y1 < h * 0.11 or r.y0 > h * 0.90:
                    t = "".join(s["text"] for s in ln["spans"]).strip()
                    if not t:
                        continue
                    k = ("top" if r.y1 < h * 0.11 else "bottom", re.sub(r"\d+", "#", t), round(r.y0 / 4))
                    keys.add(k)
                    sample.setdefault(k, (t, ln))
        seen.update(keys)
    rep = {k for k, n in seen.items() if n >= max(2, int(len(pages) * 0.5 + 0.5))}
    head = sorted([k for k in rep if k[0] == "top"], key=lambda k: k[2])
    foot = sorted([k for k in rep if k[0] == "bottom"], key=lambda k: k[2])
    return rep, [sample[k] for k in head], [sample[k] for k in foot]


def _is_repeated(line: Line, rep: set, page_h: float) -> bool:
    if not rep:
        return False
    pos = "top" if line.bottom < page_h * 0.11 else ("bottom" if line.top > page_h * 0.90 else None)
    if pos is None:
        return False
    k = (pos, re.sub(r"\d+", "#", line.text.strip()), round(line.top / 4))
    return k in rep or any(r[0] == pos and r[1] == k[1] and abs(r[2] - k[2]) <= 1 for r in rep)


# ---------------------------------------------------------------- tablas
def _page_chars(page):
    out = []
    for b in page.get_text("rawdict", flags=TEXT_FLAGS).get("blocks", []):
        if b.get("type") != 0:
            continue
        for ln in b["lines"]:
            if abs(ln.get("dir", (1, 0))[0] - 1) > 1e-3:
                continue
            for s in ln["spans"]:
                for c in s.get("chars", []):
                    bb = c["bbox"]
                    out.append((c["c"], bb[0], bb[2], c["origin"][1], s.get("size", 10)))
    return out


def cell_text(chars, rect) -> str:
    """Texto de una celda: caracteres dentro del rectángulo, por renglones y de izquierda a derecha.
    Los renglones se unen con espacio salvo que una palabra se partiera al no caber."""
    from .tablas import join_wrapped
    inside = [c for c in chars if rect.x0 - 0.5 <= (c[1] + c[2]) / 2 <= rect.x1 + 0.5
              and rect.y0 - 0.5 <= c[3] - c[4] * 0.3 <= rect.y1 + 0.5]
    if not inside:
        return ""
    inside.sort(key=lambda c: (round(c[3], 0), c[1]))
    rows = []
    for c in inside:
        if rows and abs(rows[-1][-1][3] - c[3]) < c[4] * 0.4:
            rows[-1].append(c)
        else:
            rows.append([c])
    out = ""
    # margen interior de la celda (el mismo a ambos lados): borde derecho útil del texto
    pad = max(0.0, min(min(c[1] for c in r) for r in rows) - rect.x0) if rows else 0.0
    right = rect.x1 - min(pad, rect.width * 0.25)
    for r in rows:
        r.sort(key=lambda c: c[1])
        t = ""
        prev = None
        for c in r:
            if prev is not None and not c[0].isspace() and not t.endswith(" ") and c[1] - prev[2] > c[4] * 0.2:
                t += " "
            t += c[0]
            prev = c
        t = " ".join(t.split())
        if not t:
            continue
        ink = [c for c in r if not c[0].isspace()]
        fills = bool(ink) and ink[-1][2] >= right - ink[-1][4] * 0.6
        out = join_wrapped(out, t, prev_fills) if out else t
        prev_fills = fills
    return out


def find_tables(page, strategy="lines"):
    """Tablas de la página: lista de (rect, filas[list[list[str|None]]])."""
    out = []
    tabs = None
    # find_tables devuelve None si falla por dentro (p. ej. el análisis de maquetación en
    # algunos PDF): se reintenta sin él y, si aun así falla, la página se trata sin tablas.
    # Sin el análisis de maquetación (use_layout): da el mismo resultado en Windows y macOS y
    # solo reconoce tablas dibujadas; las demás las reconoce tablas.text_tables.
    attempts = [{"use_layout": False}, {}]
    if strategy != "lines":
        attempts = [dict(a, strategy=strategy) for a in attempts]
    for kw in attempts:
        try:
            tabs = page.find_tables(**kw)
        except TypeError:
            continue           # PyMuPDF antiguo sin ese parámetro
        except Exception as e:  # noqa
            log.info("find_tables falló en la página %d (%s): %s", page.number + 1, kw, e)
            tabs = None
        if tabs is not None and getattr(tabs, "tables", None) is not None:
            break
        log.info("find_tables sin resultado en la página %d (%s)", page.number + 1, kw)
        tabs = None
    if tabs is None:
        return out
    chars = None
    for t in tabs.tables:
        try:
            if chars is None:
                chars = _page_chars(page)
            rows = [[(cell_text(chars, pymupdf.Rect(c)) if c is not None else None) for c in row.cells]
                    for row in t.rows]
        except Exception:
            try:
                rows = [[(c.replace("\n", " ").strip() if isinstance(c, str) else c) for c in r] for r in t.extract()]
            except Exception:
                continue
        # descartar «tablas» falsas: una sola fila o columna, o casi vacías (rellenos de color,
        # subrayados o recuadros que forman una cuadrícula por casualidad)
        allc = [c for r in rows for c in r]
        cells = [c for c in allc if c]
        if len(rows) < 2 or max(len(r) for r in rows) < 2 or len(cells) < 3:
            continue
        if len(cells) < 0.6 * len(allc):
            continue
        widths = []
        try:
            xs = sorted({round(c[0], 1) for c in t.cells if c} | {round(c[2], 1) for c in t.cells if c})
            widths = [b - a for a, b in zip(xs, xs[1:]) if b - a > 2][:max(len(r) for r in rows)]
        except Exception:
            pass
        out.append((pymupdf.Rect(t.bbox), rows, widths))
    return out


def all_tables(page, min_rows=3):
    """Tablas dibujadas (find_tables) y tablas reconocidas por la alineación del texto."""
    from . import tablas
    out = [(r, rows, w, True) for r, rows, w in find_tables(page)]
    try:
        for t in tablas.text_tables(page, exclude=[t[0] for t in out], min_rows=min_rows):
            out.append((t.rect, t.rows, t.widths, False))
    except Exception as e:  # noqa
        log.info("Tablas por alineación no disponibles en la página %d: %s", page.number + 1, e)
    out.sort(key=lambda t: (t[0].y0, t[0].x0))
    return out


# ---------------------------------------------------------------- Word
def _hl_index(col):
    from docx.enum.text import WD_COLOR_INDEX as W
    r, g, b = col[:3]
    table = [((1, 1, 0), W.YELLOW), ((0, 1, 0), W.BRIGHT_GREEN), ((0, 1, 1), W.TURQUOISE),
             ((1, 0, 1), W.PINK), ((0, 0, 1), W.BLUE), ((1, 0, 0), W.RED), ((0.5, 0.5, 0.5), W.GRAY_25),
             ((0.55, 0.9, 0.4), W.BRIGHT_GREEN), ((0.5, 0.78, 1.0), W.TURQUOISE), ((1.0, 0.6, 0.8), W.PINK),
             ((1.0, 0.72, 0.3), W.YELLOW), ((0.75, 0.75, 0.75), W.GRAY_25)]
    best = min(table, key=lambda t: sum((a - b2) ** 2 for a, b2 in zip(t[0], (r, g, b))))
    return best[1]


def _run_groups(chars: list):
    """Agrupa caracteres consecutivos con el mismo formato."""
    groups, cur, key = [], [], None
    for ch in chars:
        k = (ch.font, round(ch.size * 2) / 2, ch.color, ch.flags & (1 | 2 | 16), ch.hl, ch.ul, ch.st)
        if ch.c.isspace() and cur and key is not None and key[4] == ch.hl and key[5] == ch.ul:
            k = key          # los espacios van con el texto anterior
        if k != key and cur:
            groups.append((key, cur))
            cur = []
        key = k
        cur.append(ch)
    if cur:
        groups.append((key, cur))
    return groups


def _add_runs(par, chars, base_size=None):
    from docx.shared import Pt, RGBColor
    for (font, size, color, flags, hl, ul, st), cs in _run_groups(chars):
        text = "".join(BULLET_MAP.get(c.c, c.c) for c in cs)
        if not text:
            continue
        run = par.add_run(text)
        f = run.font
        name = word_font_name(font)
        if name in ("Symbol", "Wingdings") or (text.strip() and all(ch in "•▪►❖✓" for ch in text.strip())
                                                and name not in ("Arial", "Times New Roman", "Calibri")):
            name = "Arial"          # la viñeta Unicode «•» no está en Symbol ni en Wingdings
        f.name = name
        try:
            from docx.oxml.ns import qn
            rfonts = run._element.get_or_add_rPr().get_or_add_rFonts()
            rfonts.set(qn("w:cs"), name)
            rfonts.set(qn("w:eastAsia"), name)
        except Exception:
            pass
        f.size = Pt(size)
        low = font.lower()
        if flags & 16 or "bold" in low or "black" in low or "heavy" in low:
            f.bold = True
        if flags & 2 or "italic" in low or "oblique" in low:
            f.italic = True
        if flags & 1:
            f.superscript = True
        if color:
            f.color.rgb = RGBColor((color >> 16) & 255, (color >> 8) & 255, color & 255)
        if hl is not None:
            f.highlight_color = _hl_index(hl)
        if ul:
            f.underline = True
        if st:
            f.strike = True


def _para_text_chars(p: Para) -> list:
    """Caracteres del párrafo con las líneas unidas por un espacio (o nada tras guion)."""
    out = []
    for n, ln in enumerate(p.lines):
        cs = list(ln.chars)
        while cs and cs[-1].c.isspace():
            cs.pop()
        if n > 0 and out:
            last = out[-1]
            if not (last.c == "-" and cs and cs[0].c.islower()):
                out.append(Ch(" ", last.x1, last.x1, last.y, last.font, last.size, last.color, last.flags,
                              last.hl if (cs and cs[0].hl == last.hl) else None,
                              last.ul and bool(cs and cs[0].ul)))
            else:
                out.pop()        # palabra partida con guion al final de línea
        out.extend(cs)
    return out


def _docx_field(par, instr):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    run = par.add_run()
    b = OxmlElement("w:fldChar")
    b.set(qn("w:fldCharType"), "begin")
    t = OxmlElement("w:instrText")
    t.set(qn("xml:space"), "preserve")
    t.text = instr
    e = OxmlElement("w:fldChar")
    e.set(qn("w:fldCharType"), "end")
    run._r.append(b)
    run._r.append(t)
    run._r.append(e)
    return run


def _hf_rules(doc, pages):
    """¿Hay una raya horizontal bajo el encabezado / sobre el pie en casi todas las páginas?"""
    top = bottom = 0
    for pno in pages:
        page = doc[pno]
        w, h = page.rect.width, page.rect.height
        t = b = False
        try:
            for d in page.get_drawings():
                r = pymupdf.Rect(d["rect"])
                if r.height <= 2 and r.width > w * 0.5:
                    if r.y1 < h * 0.12:
                        t = True
                    elif r.y0 > h * 0.88:
                        b = True
        except Exception:
            pass
        top += t
        bottom += b
    n = max(1, len(pages))
    return top >= max(2, n * 0.5) if n > 1 else top == 1, bottom >= max(2, n * 0.5) if n > 1 else bottom == 1


def _border(par, side):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    ppr = par._p.get_or_add_pPr()
    bdr = OxmlElement("w:pBdr")
    e = OxmlElement(f"w:{side}")
    e.set(qn("w:val"), "single")
    e.set(qn("w:sz"), "8")
    e.set(qn("w:space"), "1")
    e.set(qn("w:color"), "000000")
    bdr.append(e)
    ppr.append(bdr)


def _cell_border(cell, side):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    tcPr = cell._tc.get_or_add_tcPr()
    borders = tcPr.find(qn("w:tcBorders"))
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        tcPr.append(borders)
    b = OxmlElement(f"w:{side}")
    b.set(qn("w:val"), "single")
    b.set(qn("w:sz"), "6")
    b.set(qn("w:color"), "808080")
    borders.append(b)


def _fill_hf(container, samples, page_w, left, right):
    """Encabezado o pie con los textos repetidos; los números de página como campo PAGE."""
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt
    first = True
    for text, ln in samples:
        par = container.paragraphs[0] if first and container.paragraphs else container.add_paragraph()
        first = False
        x0, x1 = ln["bbox"][0], ln["bbox"][2]
        mid = (x0 + x1) / 2
        if abs(mid - page_w / 2) < 20:
            par.alignment = WD_ALIGN_PARAGRAPH.CENTER
        elif x1 > page_w - right - 20 and x0 > page_w / 2:
            par.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        span = ln["spans"][0] if ln["spans"] else {"font": "", "size": 10, "flags": 0}
        if re.fullmatch(r"\d+", text):
            r = _docx_field(par, "PAGE")
            r.font.name = word_font_name(span.get("font", ""))
            r.font.size = Pt(round(span.get("size", 10) * 2) / 2)
            continue
        parts = re.split(r"(\d+)", text) if re.search(r"(?i)p[áa]g", text) else [text]
        for part in parts:
            if part.isdigit():
                r = _docx_field(par, "PAGE")
            else:
                r = par.add_run(part)
            r.font.name = word_font_name(span.get("font", ""))
            r.font.size = Pt(round(span.get("size", 10) * 2) / 2)
            if span.get("flags", 0) & 16:
                r.font.bold = True
            if span.get("flags", 0) & 2:
                r.font.italic = True


def _image_items(doc, page, exclude):
    out = []
    try:
        infos = page.get_image_info(xrefs=True)
    except Exception:
        return out
    for info in infos:
        r = pymupdf.Rect(info["bbox"]) & page.rect
        if r.is_empty or r.width < 12 or r.height < 12:
            continue
        if any(t.contains(r) for t in exclude):
            continue
        xref = info.get("xref", 0)
        data = None
        try:
            if xref:
                info2 = doc.extract_image(xref)
                if info2 and not info2.get("smask") and info2.get("ext") in ("jpeg", "jpg", "png") \
                        and info2.get("colorspace", 3) in (1, 3):
                    data = info2["image"]
            if xref and data is None:
                pix = pymupdf.Pixmap(doc, xref)
                if pix.alpha or (pix.colorspace and pix.colorspace.n not in (1, 3)):
                    pix = pymupdf.Pixmap(pymupdf.csRGB, pix) if pix.colorspace and pix.colorspace.n > 3 else pix
                    if pix.alpha:
                        pix = pymupdf.Pixmap(pix, 0)
                data = pix.tobytes("png")
        except Exception:
            data = None
        if data is None:
            try:
                data = page.get_pixmap(clip=r, dpi=150).tobytes("png")
            except Exception:
                continue
        out.append(Item("image", r.y0, (data, r), r.x0, r.x1))
    return out


def _rect_bottom(it) -> float:
    return it.bottom if it.bottom else it.top


@dataclass
class WordOptions:
    page_breaks: bool = True
    images: bool = True
    header_footer: bool = True


def to_docx(doc: pymupdf.Document, pages: list[int], path: str, opts: WordOptions | None = None,
            progress=None) -> dict:
    """Crea el .docx. progress(k, total) -> False para cancelar. Devuelve estadísticas."""
    from docx import Document
    from docx.enum.section import WD_ORIENT
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
    from docx.shared import Pt
    opts = opts or WordOptions()
    stats = {"pages": 0, "paragraphs": 0, "tables": 0, "images": 0, "scanned": 0}
    wd = Document()
    # estilo base sin espacios añadidos
    st = wd.styles["Normal"]
    st.paragraph_format.space_after = Pt(0)
    st.paragraph_format.space_before = Pt(0)
    rep, head, foot = _repeated_lines(doc, pages) if opts.header_footer else (set(), None, None)
    # márgenes comunes (por la caja de texto de las páginas)
    first_page = doc[pages[0]]
    pw, ph = first_page.rect.width, first_page.rect.height
    lefts, rights, tops, bottoms = [], [], [], []
    page_lines = {}
    page_tables = {}
    for n, pno in enumerate(pages):
        if progress is not None and progress(n, len(pages) * 2) is False:
            raise Cancelled()
        page = doc[pno]
        tables = all_tables(page)
        page_tables[pno] = tables
        lines = [l for l in _lines_of_page(page, [t[0] for t in tables])
                 if not _is_repeated(l, rep, page.rect.height)]
        page_lines[pno] = lines
        if lines:
            lefts.append(min(l.x0 for l in lines))
            rights.append(page.rect.width - max(l.x1 for l in lines))
            tops.append(min(l.top for l in lines))
            bottoms.append(page.rect.height - max(l.bottom for l in lines))
    med = lambda v, d: sorted(v)[len(v) // 2] if v else d
    left_m = max(28.0, min(med(lefts, 72), 144))
    right_m = max(28.0, min(med(rights, 72), 144))
    top_m = max(28.0, min(min(tops) if tops else 72, 144))
    bot_m = max(28.0, min(min(bottoms) if bottoms else 72, 144))
    sec = wd.sections[0]
    sec.page_width, sec.page_height = Pt(pw), Pt(ph)
    if pw > ph:
        sec.orientation = WD_ORIENT.LANDSCAPE
    sec.left_margin, sec.right_margin = Pt(left_m), Pt(right_m)
    sec.top_margin, sec.bottom_margin = Pt(top_m), Pt(bot_m)
    sec.header_distance = Pt(max(12, top_m * 0.4))
    sec.footer_distance = Pt(max(12, bot_m * 0.4))
    if head:
        _fill_hf(sec.header, head, pw, left_m, right_m)
    if foot:
        _fill_hf(sec.footer, foot, pw, left_m, right_m)
    if opts.header_footer and (head or foot):
        rule_top, rule_bottom = _hf_rules(doc, pages)
        if head and rule_top and sec.header.paragraphs:
            _border(sec.header.paragraphs[-1], "bottom")
        if foot and rule_bottom and sec.footer.paragraphs:
            _border(sec.footer.paragraphs[0], "top")
    text_width = pw - left_m - right_m
    body = wd.element.body
    # el documento nuevo trae un párrafo vacío: se quita
    for p0 in list(wd.paragraphs):
        p0._element.getparent().remove(p0._element)

    for n, pno in enumerate(pages):
        if progress is not None and progress(len(pages) + n, len(pages) * 2) is False:
            raise Cancelled()
        page = doc[pno]
        page_chars = page_fonts = None
        lines = page_lines[pno]
        tables = page_tables[pno]
        right_edge = page.rect.width - right_m if lines else page.rect.width - 72
        if lines:
            # borde derecho real del texto de esta página
            right_edge = max(l.x1 for l in lines)
        items: list[Item] = []
        for p in _paragraphs(lines, left_m, right_edge, page.rect.width):
            items.append(Item("para", p.top, p))
        for rect, rows, widths, ruled in tables:
            items.append(Item("table", rect.y0, (rows, widths, ruled), rect.x0, rect.x1, rect.y1))
        if opts.images:
            imgs = _image_items(doc, page, [t[0] for t in tables])
            if lines:
                # página escaneada con texto reconocido: la imagen de fondo no se copia (el texto ya está)
                parea = page.rect.width * page.rect.height
                imgs = [im for im in imgs if (im.obj[1].width * im.obj[1].height) < 0.6 * parea]
            items += imgs
        if not lines and not tables:
            # página escaneada o solo imagen: la página entera como imagen
            stats["scanned"] += 1
            if not any(i.kind == "image" for i in items):
                data = page.get_pixmap(dpi=150).tobytes("png")
                items.append(Item("image", 0, (data, page.rect), 0, page.rect.width))
        items.sort(key=lambda i: (i.top, i.x0))
        prev_bottom = None
        for it in items:
            if it.kind == "para":
                p = it.obj
                par = wd.add_paragraph()
                pf = par.paragraph_format
                gap = p.space_before
                if prev_bottom is not None and prev_bottom > (p.lines[0].top - gap - 1):
                    gap = max(0.0, p.lines[0].top - prev_bottom)
                elif prev_bottom is None:
                    gap = 0.0
                pf.space_before = Pt(min(round(gap * 0.8), 36)) if gap > 2 else Pt(0)
                prev_bottom = max(l.bottom for l in p.lines)
                size = p.lines[0].size
                ratio = p.leading / (size * 1.15) if size else 1.0
                if len(p.lines) > 1 and 1.1 < ratio < 3:
                    pf.line_spacing = round(ratio, 2)
                pf.alignment = {"left": WD_ALIGN_PARAGRAPH.LEFT, "center": WD_ALIGN_PARAGRAPH.CENTER,
                                "right": WD_ALIGN_PARAGRAPH.RIGHT,
                                "justify": WD_ALIGN_PARAGRAPH.JUSTIFY}[p.align]
                if p.align in ("left", "justify"):
                    if p.left > 1:
                        pf.left_indent = Pt(round(min(p.left, text_width * 0.6), 1))
                    if abs(p.first) > 1:
                        pf.first_line_indent = Pt(round(max(p.first, -p.left - 0.0), 1)) if p.first < 0 else Pt(round(p.first, 1))
                if p.kind == "bullet":
                    # viñeta + tabulador hasta el texto (sangría francesa)
                    _add_runs(par, p.marker)
                    tab_r = par.add_run("\t")
                    tab_r.font.size = Pt(size)
                    if pf.left_indent is not None:
                        pf.tab_stops.add_tab_stop(pf.left_indent)
                _add_runs(par, _para_text_chars(p))
                stats["paragraphs"] += 1
            elif it.kind == "table":
                rows, widths, ruled = it.obj
                ncol = max(len(r) for r in rows)
                tb = wd.add_table(rows=len(rows), cols=ncol)
                # tablas dibujadas: con cuadrícula; reconocidas por alineación: como en el PDF,
                # sin líneas salvo la de debajo de la cabecera
                if ruled:
                    tb.style = "Table Grid"
                tb.alignment = WD_TABLE_ALIGNMENT.CENTER
                from docx.table import _Cell
                from .tablas import has_header, is_amount
                head = has_header(rows)
                # tamaño de letra de la tabla en el PDF (entre 7 y 11 pt)
                if page_chars is None:
                    page_chars = _page_chars(page)
                trect = pymupdf.Rect(it.x0, it.top, it.x1, it.bottom)
                sizes = sorted(c[4] for c in page_chars if trect is not None
                               and trect.x0 - 1 <= c[1] <= trect.x1 + 1 and trect.y0 - 1 <= c[3] <= trect.y1 + 3
                               and not c[0].isspace())
                tsize = round(min(11.0, max(7.0, sizes[len(sizes) // 2])) * 2) / 2 if sizes else 9
                # tipo de letra más usado en la tabla (para que las columnas midan lo mismo)
                if page_fonts is None:
                    page_fonts = []
                    for blk in page.get_text("dict", flags=TEXT_FLAGS).get("blocks", []):
                        for ln_ in blk.get("lines", []):
                            for sp_ in ln_.get("spans", []):
                                if sp_.get("text", "").strip():
                                    page_fonts.append((pymupdf.Rect(sp_["bbox"]), sp_.get("font", ""), len(sp_["text"])))
                cnt = {}
                for r_, f_, n_ in page_fonts:
                    if trect.intersects(r_) and f_ and "glyphless" not in f_.lower():
                        cnt[f_] = cnt.get(f_, 0) + n_
                tfont = word_font_name(max(cnt, key=cnt.get)) if cnt else None
                cw = None
                if len(widths) == ncol:
                    scale = min(1.0, text_width / max(1.0, sum(widths)))
                    tb.autofit = False
                    cw = [Pt(wdt * scale) for wdt in widths]
                # acceso directo a las celdas: tb.cell(i, j) recorre la tabla entera cada vez
                trs = tb._tbl.tr_lst
                for i, r in enumerate(rows):
                    tcs = trs[i].tc_lst
                    for j in range(ncol):
                        v = r[j] if j < len(r) else None
                        cell = _Cell(tcs[j], tb)
                        if cw is not None:
                            cell.width = cw[j]
                        cell.text = v or ""
                        para = cell.paragraphs[0]
                        if i == 0 and head:
                            for rr in para.runs:
                                rr.font.bold = True
                            if not ruled:
                                _cell_border(cell, "bottom")
                        elif v and is_amount(v):
                            para.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                        for rr in para.runs:
                            rr.font.size = Pt(tsize)
                            if tfont:
                                rr.font.name = tfont
                prev_bottom = it.obj and max(prev_bottom or 0, _rect_bottom(it))
                stats["tables"] += 1
            elif it.kind == "image":
                data, r = it.obj
                par = wd.add_paragraph()
                w = min(r.width, text_width)
                h = r.height * (w / r.width)
                if abs((r.x0 + r.x1) / 2 - page.rect.width / 2) < 30:
                    par.alignment = WD_ALIGN_PARAGRAPH.CENTER
                elif r.x0 - left_m > 5:
                    par.paragraph_format.left_indent = Pt(min(r.x0 - left_m, text_width - w))
                if prev_bottom is not None and r.y0 - prev_bottom > 4:
                    par.paragraph_format.space_before = Pt(min(round((r.y0 - prev_bottom) * 0.8), 36))
                prev_bottom = r.y1
                try:
                    par.add_run().add_picture(io.BytesIO(data), width=Pt(w), height=Pt(h))
                    stats["images"] += 1
                except Exception as e:  # noqa
                    log.info("Imagen no insertada: %s", e)
        if opts.page_breaks and n < len(pages) - 1:
            br = wd.add_paragraph()
            br.add_run().add_break(WD_BREAK.PAGE)
        stats["pages"] += 1
    if progress is not None:
        progress(len(pages) * 2, len(pages) * 2)
    wd.core_properties.title = (doc.metadata or {}).get("title") or ""
    wd.core_properties.comments = "Convertido con NovoPDF"
    wd.save(path)
    log.info("Word: %s", stats)
    return stats


# ---------------------------------------------------------------- Excel
NUM_RE = re.compile(r"^(?P<sign>[-−–+]?)\s*(?P<cur1>[€$£])?\s*(?P<num>\d{1,3}(?:[.\s  ]\d{3})+(?:,\d+)?|\d+(?:,\d+)?)"
                    r"\s*(?P<pct>%)?\s*(?P<cur2>€|EUR|euros?)?$", re.I)
DATE_RE = re.compile(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2}|\d{4})$")


def parse_value(text: str):
    """Convierte «1.234,56 €», «(1.234,56)», «12,5 %», «03/11/2025» en valores de Excel.
    Devuelve (valor, formato_numero) o (texto, None)."""
    import datetime as dt
    t = (text or "").strip()
    if not t:
        return None, None
    if re.fullmatch(r"[-−–+(]?\s*[\d\s.,]+\s*[)%€]?\s*(?:€|EUR)?", t) and re.search(r"\d\s*[.,]\s+\d|\d\s+[.,]\s*\d", t):
        t = re.sub(r"\s*([.,])\s*", r"\1", t)        # espacios metidos por el OCR: «1.119 , 26»
    neg = False
    if t.startswith("(") and t.endswith(")") and len(t) > 2:
        neg, t = True, t[1:-1].strip()
    if t.endswith("-") and re.match(r"^[\d.,\s]+-$", t):
        neg, t = True, t[:-1].strip()
    m = NUM_RE.match(t)
    if m:
        num = re.sub(r"[.\s  ]", "", m.group("num")).replace(",", ".")
        try:
            v = float(num)
        except ValueError:
            return text, None
        if m.group("sign") in ("-", "−", "–") or neg:
            v = -v
        decimals = len(m.group("num").split(",")[1]) if "," in m.group("num") else 0
        if m.group("num").isdigit() and len(m.group("num")) > 1 and m.group("num").startswith("0"):
            return text, None        # códigos con ceros a la izquierda (CP, cuentas): texto
        if m.group("num").isdigit() and len(m.group("num")) >= 12:
            return text, None        # números largos (IBAN, expedientes): texto
        if m.group("pct"):
            return round(v / 100, decimals + 4), "0" + ("." + "0" * decimals if decimals else "") + "%"
        fmt = "#,##0" + ("." + "0" * decimals if decimals else "")
        if m.group("cur1") or m.group("cur2"):
            sym = m.group("cur1") or "€"
            fmt = "#,##0.00 \"" + ("€" if sym.upper().startswith(("€", "EUR")) else sym) + "\""
            return v, fmt
        if v == int(v) and not decimals:
            return int(v), ("#,##0" if re.search(r"[.\s\u00a0\u202f]", m.group("num")) else "0")
        return v, fmt
    m = DATE_RE.match(t)
    if m:
        d, mo, y = (int(x) for x in m.groups())
        if y < 100:
            y += 2000 if y < 70 else 1900
        try:
            return dt.datetime(y, mo, d), "dd/mm/yyyy"
        except ValueError:
            return text, None
    return text, None


@dataclass
class ExcelOptions:
    mode: str = "tables"          # tables (una hoja por tabla) | one_sheet | text (una hoja por página)
    convert: bool = True


def _text_rows(page):
    """Contenido de la página como filas: el texto normal en la columna A y las tablas
    (dibujadas o alineadas) con sus columnas."""
    from . import tablas
    rows = []
    for part, is_table in tablas.page_layout(page, find_tables(page)):
        if is_table and rows and rows[-1]:
            rows.append([])
        rows.extend(part)
        if is_table:
            rows.append([])
    while rows and not rows[-1]:
        rows.pop()
    return rows


def _write_rows(ws, rows, start_row, convert, header=True, title=None, borders=True):
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    thin = Side(style="thin", color="BFC5D2")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    r0 = start_row
    if title:
        c = ws.cell(row=r0, column=1, value=title)
        c.font = Font(bold=True, size=12, color="2F5BD8")
        r0 += 1
    ncol = max((len(r) for r in rows), default=0)
    for i, row in enumerate(rows):
        for j in range(ncol):
            v = row[j] if j < len(row) else None
            fmt = None
            if convert and isinstance(v, str) and not (header and i == 0):
                v, fmt = parse_value(v)
            c = ws.cell(row=r0 + i, column=j + 1, value=v)
            if fmt:
                c.number_format = fmt
            if borders:
                c.border = border
            if isinstance(v, str) and len(v) > 40:
                c.alignment = Alignment(wrap_text=True, vertical="top")
            if header and i == 0:
                c.font = Font(bold=True)
                c.fill = PatternFill("solid", fgColor="E8EEFC")
                c.alignment = Alignment(wrap_text=True, vertical="center")
    return r0, r0 + len(rows) - 1, ncol


def _autosize(ws):
    from openpyxl.utils import get_column_letter
    widths = {}
    for row in ws.iter_rows():
        for c in row:
            if c.value is None:
                continue
            v = c.value
            if isinstance(v, float):
                n = len(f"{v:,.2f}")
            elif hasattr(v, "strftime"):
                n = 10
            else:
                n = max(len(x) for x in str(v).split("\n"))
            widths[c.column] = max(widths.get(c.column, 0), min(n, 60))
    for col, n in widths.items():
        ws.column_dimensions[get_column_letter(col)].width = max(8, n + 2)


def _sheet_name(base, used):
    name = re.sub(r"[\[\]:*?/\\]", "-", base)[:31] or "Hoja"
    k, cand = 2, name
    while cand in used:
        suffix = f" ({k})"
        cand = name[:31 - len(suffix)] + suffix
        k += 1
    used.add(cand)
    return cand


def to_xlsx(doc: pymupdf.Document, pages: list[int], path: str, opts: ExcelOptions | None = None,
            progress=None) -> dict:
    """Crea el .xlsx. Devuelve estadísticas (tablas encontradas, hojas, modo usado)."""
    from openpyxl import Workbook
    opts = opts or ExcelOptions()
    wb = Workbook()
    wb.remove(wb.active)
    used = set()
    stats = {"tables": 0, "sheets": 0, "mode": opts.mode, "fallback": False}
    found = []
    if opts.mode in ("tables", "one_sheet"):
        for n, pno in enumerate(pages):
            if progress is not None and progress(n, len(pages)) is False:
                raise Cancelled()
            for k, (rect, rows, _w, _ruled) in enumerate(all_tables(doc[pno])):
                found.append((pno, k, rows))
        if not found:
            stats["fallback"] = True
            opts = ExcelOptions("text", opts.convert)
            stats["mode"] = "text"
    if opts.mode == "tables":
        for pno, k, rows in found:
            ws = wb.create_sheet(_sheet_name(f"Pág {pno + 1} - Tabla {k + 1}", used))
            from .tablas import has_header
            head = has_header(rows)
            a, b, ncol = _write_rows(ws, rows, 1, opts.convert, header=head)
            if head:
                ws.freeze_panes = "A2"
            if head and ncol and b > a:
                from openpyxl.utils import get_column_letter
                ws.auto_filter.ref = f"A{a}:{get_column_letter(ncol)}{b}"
            _autosize(ws)
            stats["tables"] += 1
    elif opts.mode == "one_sheet":
        ws = wb.create_sheet(_sheet_name("Tablas", used))
        r = 1
        for pno, k, rows in found:
            from .tablas import has_header
            a, b, _ = _write_rows(ws, rows, r, opts.convert, header=has_header(rows),
                                  title=f"Página {pno + 1} · Tabla {k + 1}")
            r = b + 3
            stats["tables"] += 1
        _autosize(ws)
    else:
        for n, pno in enumerate(pages):
            if progress is not None and progress(n, len(pages)) is False:
                raise Cancelled()
            rows = _text_rows(doc[pno])
            ws = wb.create_sheet(_sheet_name(f"Página {pno + 1}", used))
            if rows:
                _write_rows(ws, rows, 1, opts.convert, header=False, borders=False)
            _autosize(ws)
    if not wb.sheetnames:
        wb.create_sheet("Hoja1")
    stats["sheets"] = len(wb.sheetnames)
    wb.properties.creator = "NovoPDF"
    wb.save(path)
    if progress is not None:
        progress(len(pages), len(pages))
    log.info("Excel: %s", stats)
    return stats
