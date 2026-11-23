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

"""Reconocimiento de tablas por la posición del texto (sin depender de que estén dibujadas).

Sirve para tablas sin líneas, con solo líneas horizontales o verticales, y para documentos
escaneados con OCR, donde no hay nada dibujado. Funciona igual en Windows y macOS: no usa
el análisis de maquetación opcional de PyMuPDF (que necesita numpy y otros módulos).

Idea:
1. Palabras → renglones visuales → «frases» (palabras separadas por un hueco normal).
   Un hueco grande, una línea vertical dibujada o una barra «|» del OCR separa frases.
2. Zonas de tabla: renglones seguidos con dos o más frases (más los renglones cortos que
   son continuación de una celda partida en varias líneas).
3. Columnas: huecos verticales que ninguna frase atraviesa. Las frases que abarcan varias
   columnas (cabeceras pegadas, títulos centrados) no cuentan para decidir los huecos.
4. Filas: un renglón sin primera columna, sin números y que solo continúa celdas con texto
   de la fila anterior se une a ella (celdas de varias líneas).
"""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field

import pymupdf

TEXT_FLAGS = pymupdf.TEXT_PRESERVE_WHITESPACE | pymupdf.TEXT_MEDIABOX_CLIP
SEP_CHARS = "|¦│┃"
NOISE_RE = re.compile(r"^[-_—–=~.·•]{3,}$")       # filetes reconocidos por el OCR como texto
NUMLIKE_RE = re.compile(r"^[-−–+(]?\s*[€$£]?\s*\d[\d.,\s]*\s*%?\s*(?:€|EUR)?\)?$|^\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}$", re.I)


_LIST_MARK = re.compile(r"^(?:[•·∙◦▪▫■□●○‣⁃*\-–—>»✓✔\ue000-\uf8ff]|\(?[a-zA-Z][.)]|[ivxIVX]{1,4}[.)])$")
_NUM_MARK = re.compile(r"^\(?\d{1,2}(?:\.\d{1,2})*[.)]?$")      # 1.  1)  5.1  2.3.1


@dataclass
class Word:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    size: float
    base: float
    space_left: float | None = None     # x del espacio que la precede en el mismo renglón del PDF
    seq: int = 0                        # renglón del PDF (orden de lectura)
    space_kind: int = 0                 # 2: espacio entre palabras; 1: espacio final del renglón anterior


@dataclass
class Phrase:
    words: list

    @property
    def x0(self):
        return self.words[0].x0

    @property
    def x1(self):
        return self.words[-1].x1

    @property
    def text(self):
        return " ".join(w.text for w in self.words)


@dataclass
class VLine:
    words: list
    size: float
    phrases: list = field(default_factory=list)
    y0: float = 0
    y1: float = 0

    @property
    def x0(self):
        return min(w.x0 for w in self.words)

    @property
    def x1(self):
        return max(w.x1 for w in self.words)


def is_numeric(t: str) -> bool:
    return bool(NUMLIKE_RE.match((t or "").strip()))


def is_amount(t: str) -> bool:
    """Importe o porcentaje (se alinea a la derecha); no códigos ni fechas."""
    t = (t or "").strip()
    return is_numeric(t) and ("," in t or "%" in t or "€" in t or re.search(r"\d\.\d{3}", t) is not None) \
        and "/" not in t


def has_header(rows) -> bool:
    """¿La primera fila es una cabecera? No en listas «Etiqueta: valor»."""
    if len(rows) < 2:
        return False
    first = [c for c in rows[0] if c]
    ncol = max(len(r) for r in rows)
    if len(first) < max(2, 0.6 * ncol) or any(is_numeric(c) for c in first):
        return False
    labels = sum(1 for r in rows for c in r[:1] if c and c.rstrip().endswith(":"))
    return labels < 0.5 * len(rows)


# ------------------------------------------------------------------ palabras y renglones
def _words(page, clip=None, exclude=()):
    """Palabras con su tamaño de letra; las barras «|» del OCR se devuelven aparte (x)."""
    words, bars = [], []
    seqn = 0
    # espacio pendiente (x, línea base): algunos PDF escriben cada palabra y cada espacio
    # como renglones distintos
    state = {"space": None, "base": None, "seq": 0, "solo": False}
    try:
        d = page.get_text("rawdict", flags=TEXT_FLAGS, clip=clip)
    except Exception:
        return words, bars
    for b in d.get("blocks", []):
        if b.get("type") != 0:
            continue
        for ln in b["lines"]:
            if abs(ln.get("dir", (1, 0))[0] - 1) > 1e-3:
                continue
            cur = []
            seqn += 1
            only_space = all(c["c"].isspace() for s in ln["spans"] for c in s.get("chars", []))

            def flush():
                if not cur:
                    return
                t = "".join(c[0] for c in cur)
                if NOISE_RE.match(t):
                    cur.clear()
                    return
                sizes = [c[4] for c in cur]
                words.append(Word(cur[0][1], min(c[2] for c in cur), cur[-1][3], max(c[5] for c in cur), t,
                                  statistics.median(sizes), statistics.median(c[6] for c in cur),
                                  cur[0][7], seqn, cur[0][8]))
                cur.clear()

            for s in ln["spans"]:
                size = s.get("size", 10) or 10
                for c in s.get("chars", []):
                    ch = c["c"]
                    bb = c["bbox"]
                    if exclude:
                        cx, cy = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
                        if any(r.x0 <= cx <= r.x1 and r.y0 <= cy <= r.y1 for r in exclude):
                            flush()
                            continue
                    if ch in SEP_CHARS:
                        flush()
                        state["space"] = None
                        bars.append(((bb[0] + bb[2]) / 2, bb[1], bb[3]))
                        continue
                    if ch.isspace():
                        flush()
                        if state["space"] is None or abs(state["base"] - c["origin"][1]) > 1:
                            state["space"], state["base"], state["seq"] = bb[0], c["origin"][1], seqn
                            state["solo"] = only_space
                        continue
                    if cur and bb[0] - cur[-1][3] > size * 0.25:
                        flush()
                    sp = None
                    kind = 0
                    if cur:
                        sp, kind = cur[0][7], cur[0][8]
                    elif state["space"] is not None and abs(state["base"] - c["origin"][1]) <= 1 \
                            and state["space"] <= bb[0]:
                        sp = state["space"]
                        # un espacio suelto o del mismo renglón separa palabras; el espacio final
                        # de otro renglón puede ser el de una celda anterior
                        kind = 2 if (state["seq"] == seqn or state["solo"]) else 1
                    state["space"] = None
                    cur.append((ch, bb[0], bb[1], bb[2], size, bb[3], c["origin"][1], sp, kind))
            flush()
    return words, bars


def _vrules(page):
    """Líneas verticales dibujadas (x, y0, y1)."""
    out = []
    try:
        drawings = page.get_drawings()
    except Exception:
        return out
    for dr in drawings:
        for it in dr.get("items", []):
            if it[0] == "l":
                p, q = it[1], it[2]
                if abs(p.x - q.x) < 1 and abs(p.y - q.y) > 5:
                    out.append(((p.x + q.x) / 2, min(p.y, q.y), max(p.y, q.y)))
            elif it[0] == "re":
                r = it[1]
                if r.width < 2 and r.height > 5:
                    out.append(((r.x0 + r.x1) / 2, r.y0, r.y1))
    return out


def _lines(words):
    """Agrupa las palabras en renglones visuales (por solapamiento vertical)."""
    lines = []
    for w in sorted(words, key=lambda w: (w.base, w.x0)):
        h = max(w.y1 - w.y0, 1)
        for ln in reversed(lines[-4:]):
            ov = min(ln.y1, w.y1) - max(ln.y0, w.y0)
            if ov > 0.5 * min(h, ln.y1 - ln.y0) and abs(ln.words[-1].base - w.base) < max(w.size, ln.size) * 0.6:
                ln.words.append(w)
                ln.y0, ln.y1 = min(ln.y0, w.y0), max(ln.y1, w.y1)
                break
        else:
            lines.append(VLine([w], w.size, y0=w.y0, y1=w.y1))
    for ln in lines:
        ln.words.sort(key=lambda w: w.x0)
        ln.size = statistics.median(w.size for w in ln.words)
    lines.sort(key=lambda l: (l.y0 + l.y1) / 2)
    return lines


def _phrases(line: VLine, cuts):
    """Frases del renglón: se corta en huecos grandes y en las separaciones (líneas, «|»).
    Un hueco con un espacio de por medio (texto justificado, OCR) solo separa si es muy
    grande o mucho mayor que los espacios normales de ese trozo de renglón."""
    size = line.size
    ws = line.words
    mid = (line.y0 + line.y1) / 2
    gaps = []
    for a, b in zip(ws, ws[1:]):
        g = b.x0 - a.x1
        sp = b.space_kind if (b.space_left is not None and a.x1 - 1 <= b.space_left < b.x0) else 0
        cut = any(a.x1 - 1 <= x <= b.x0 + 1 and y0 <= mid <= y1 for x, y0, y1 in cuts)
        gaps.append((g, sp, cut))
    # 1) cortes seguros: separadores, huecos sin espacio, huecos enormes
    full = re.compile(r"^[-−(]?\d[\d.]*,\d+\)?$|^\d{1,2}/\d{1,2}/\d{2,4}$")
    hard = []
    for k, (g, sp, cut) in enumerate(gaps):
        a, b = ws[k].text, ws[k + 1].text
        nums = is_numeric(a) and is_numeric(b) and not b.startswith("%")
        hard.append(cut or g > 3 * size or (not sp and g > max(size * 0.6, 3.0))
                    # dos importes seguidos son dos celdas aunque estén muy juntos
                    or (nums and not sp and g > size * 0.25)
                    or (nums and full.match(a) is not None and full.match(b) is not None and g > size * 0.2))
    out = []
    start = 0
    for i in range(len(ws)):
        if i == len(ws) - 1 or hard[i]:
            seg = list(range(start, i + 1))
            sg = [gaps[k] for k in seg[:-1]]
            sp_gaps = [g for g, sp, _c in sg if sp and g > 0]
            pos = [g for g, _sp, _c in sg if g > 0]
            small = min(sp_gaps) if sp_gaps else None
            # trozo justificado: todos los espacios estirados por igual; no es una fila de tabla
            justified = (len(sp_gaps) >= 2 and len(sp_gaps) >= 0.6 * len(sg)
                         and max(pos) < 1.25 * min(pos)
                         and sum(is_numeric(ws[k].text) for k in seg) * 3 <= len(seg))
            cur = Phrase([ws[seg[0]]])
            for k in seg[1:]:
                g, sp, _c = gaps[k - 1]
                if justified:
                    split = False
                elif sp == 1:
                    split = g > max(size * 0.6, 3.0)
                elif sp:
                    split = g > 1.5 * size or (g > 0.6 * size and g > 2.5 * small)
                else:
                    split = False
                if split:
                    out.append(cur)
                    cur = Phrase([ws[k]])
                else:
                    cur.words.append(ws[k])
            out.append(cur)
            start = i + 1
    line.phrases = out
    return out


# ------------------------------------------------------------------ columnas
def _segments(intervals, lo, hi):
    """Tramos horizontales cubiertos por algún intervalo (huecos = separación de columnas)."""
    if not intervals:
        return []
    iv = sorted(intervals)
    segs = [list(iv[0])]
    for a, b in iv[1:]:
        if a <= segs[-1][1] + 0.5:
            segs[-1][1] = max(segs[-1][1], b)
        else:
            segs.append([a, b])
    return segs


def _columns(lines):
    """Columnas de una zona: lista de (x0, x1). Ignora las frases que abarcan varias."""
    phrases = [(p, ln) for ln in lines for p in ln.phrases]
    multi = [ln for ln in lines if len(ln.phrases) >= 2]
    spanning = set()
    for _ in range(4):
        use = [(p.x0, p.x1) for p, ln in phrases if id(p) not in spanning]
        segs = _segments(use, 0, 0)
        changed = False
        # una frase que «une» dos tramos que, sin ella, estarían separados
        for p, ln in phrases:
            if id(p) in spanning:
                continue
            others = [(q.x0, q.x1) for q, l2 in phrases if q is not p and id(q) not in spanning]
            sub = _segments(others, 0, 0)
            inside = [s for s in sub if s[1] > p.x0 + 1 and s[0] < p.x1 - 1]
            if len(inside) >= 2:
                # cada tramo debe estar respaldado por al menos dos renglones distintos
                ok = 0
                for s in inside:
                    rows = {id(l2) for q, l2 in phrases if q is not p and id(q) not in spanning
                            and q.x1 > s[0] and q.x0 < s[1]}
                    ok += len(rows) >= 2
                if ok >= 2:
                    spanning.add(id(p))
                    changed = True
        if not changed:
            break
    segs = _segments([(p.x0, p.x1) for p, ln in phrases if id(p) not in spanning], 0, 0)
    # tramos que solo tienen renglones de continuación (una frase) no forman columna propia
    good = []
    for s in segs:
        n = sum(1 for ln in multi if any(p.x1 > s[0] and p.x0 < s[1] for p in ln.phrases))
        if n >= 1:
            good.append(s)
        elif good:
            good[-1][1] = max(good[-1][1], s[1])
    return [tuple(s) for s in good], spanning


def _assign(line, cols, spanning):
    """Texto de cada columna en el renglón."""
    cells = [[] for _ in cols]
    if not cols:
        return cells

    def best(a, b):
        ov = [min(b, c[1]) - max(a, c[0]) for c in cols]
        k = max(range(len(cols)), key=lambda i: ov[i])
        if ov[k] <= 0:
            cx = (a + b) / 2
            k = min(range(len(cols)), key=lambda i: min(abs(cols[i][0] - cx), abs(cols[i][1] - cx)))
        return k

    for p in line.phrases:
        ks = {best(w.x0, w.x1) for w in p.words}
        if len(ks) == 1:
            cells[ks.pop()].append(p.words)
            continue
        for w in p.words:
            k = best(w.x0, w.x1)
            if cells[k] and cells[k][-1] and cells[k][-1][-1] in p.words:
                cells[k][-1].append(w)
            else:
                cells[k].append([w])
    return cells


def _cell_str(groups):
    return " ".join(" ".join(w.text for w in g) for g in groups).strip()


_FUNCTION_WORDS = {"de", "del", "la", "las", "el", "los", "y", "e", "o", "u", "en", "a", "al", "con", "por",
                   "para", "sin", "un", "una", "que", "se", "su", "sus", "of", "the", "and", "to", "in"}


def join_wrapped(prev: str, nxt: str, prev_fills: bool) -> str:
    """Une dos renglones de una misma celda: sin espacio si una palabra se partió."""
    if not prev:
        return nxt
    if not nxt:
        return prev
    if prev.endswith("-") and nxt[:1].islower() and not prev.endswith(" -"):
        return prev[:-1] + nxt
    if (prev_fills and " " not in prev.strip() and prev[-1:].isalpha() and nxt[:1].islower()
            and nxt.split()[0].lower() not in _FUNCTION_WORDS):
        return prev + nxt
    if prev_fills and prev[-1:].isdigit() and re.fullmatch(r"\d{1,3}\s*%?", nxt) and is_numeric(prev):
        return prev + nxt            # importe partido: «4.655.040,5» + «1»
    return prev + " " + nxt


# ------------------------------------------------------------------ zonas y filas
@dataclass
class TextTable:
    rect: pymupdf.Rect
    rows: list
    widths: list
    lines: list


def _zones(lines):
    """Zonas candidatas a tabla: [primer renglón, último renglón]."""
    zones = []
    cur = None
    for i, ln in enumerate(lines):
        multi = len(ln.phrases) >= 2
        if cur is not None:
            prev = lines[cur[-1]]
            gap = ln.y0 - prev.y1
            close = gap < max(ln.size, prev.size) * 2.2
            ext0 = min(lines[j].x0 for j in cur if len(lines[j].phrases) >= 2)
            ext1 = max(lines[j].x1 for j in cur if len(lines[j].phrases) >= 2)
            width = max(ext1 - ext0, 1)
            if close and multi:
                cur.append(i)
                continue
            if close and ln.x0 >= ext0 - 3 and ln.x1 <= ext1 + 3 and (ln.x1 - ln.x0) < 0.55 * width:
                cur.append(i)
                continue
            zones.append(cur)
            cur = None
        if multi:
            cur = [i]
    if cur is not None:
        zones.append(cur)
    out = []
    for z in zones:
        if sum(1 for j in z if len(lines[j].phrases) >= 2) >= 2:
            out.append(z)
    return out


def _build(zl):
    cols, spanning = _columns(zl)
    if len(cols) < 2:
        return None
    rows = []          # cada fila: lista de celdas (texto) + datos para unir renglones
    for ln in zl:
        cells = _assign(ln, cols, spanning)
        texts = [_cell_str(g) for g in cells]
        ends = [max((w.x1 for g in cells[k] for w in g), default=0) for k in range(len(cols))]
        filled = [k for k, t in enumerate(texts) if t]
        if rows:
            prev = rows[-1]
            first = next((k for k in range(len(cols)) if any(r["t"][k] for r in rows)), 0)
            def fills(k):
                # la palabra se partió si el primer carácter del renglón siguiente no cabía
                g = cells[k][0] if cells[k] else None
                cw = ((g[0].x1 - g[0].x0) / max(len(g[0].text), 1)) if g else ln.size * 0.5
                if is_numeric(prev["t"][k] or ""):
                    cw = max(cw, ln.size * 0.6) * 1.1     # importes alineados a la derecha
                return prev["end"][k] + cw * 0.9 > cols[k][1]

            def goes_on(k):
                a, b = prev["t"][k], texts[k]
                if not a:
                    return False
                if not is_numeric(a) and not is_numeric(b):
                    return True
                # trozo final de un importe que no cabía en la celda
                return is_numeric(a) and re.fullmatch(r"\d{1,3}\s*%?", b) is not None and fills(k)

            fragments = all(is_numeric(prev["t"][k] or "") and is_numeric(texts[k]) for k in filled)
            cont = (filled and first not in filled and (prev["t"][first] or fragments)
                    and all(goes_on(k) for k in filled)
                    and ln.y0 - prev["y1"] < ln.size * 1.2)
            if cont:
                for k in filled:
                    prev["t"][k] = join_wrapped(prev["t"][k], texts[k], fills(k))
                    prev["end"][k] = ends[k]
                prev["y1"] = ln.y1
                continue
        rows.append({"t": texts, "end": ends, "y1": ln.y1, "single": len(ln.phrases) < 2})
    # renglones sueltos al final que no continuaban ninguna celda: no son de la tabla
    while rows and rows[-1]["single"]:
        rows.pop()
    table = [r["t"] for r in rows]
    # quitar columnas vacías
    keep = [k for k in range(len(cols)) if any(r[k] for r in table)]
    table = [[r[k] or None for k in keep] for r in table]
    cols = [cols[k] for k in keep]
    if len(cols) < 2 or len(table) < 2:
        return None
    return table, cols


def text_tables(page, exclude=(), min_rows=3, extracted=None) -> list[TextTable]:
    """Tablas reconocidas por la alineación del texto en la página."""
    words, bars = extracted if extracted is not None else _words(page, exclude=exclude)
    if not words:
        return []
    cuts = [(x, y0 - 2, y1 + 2) for x, y0, y1 in bars] + _vrules(page)
    lines = _lines(words)
    for ln in lines:
        _phrases(ln, cuts)
    out = []
    for z in _zones(lines):
        zl = [lines[j] for j in z]
        res = _build(zl)
        if res is None:
            continue
        rows, cols = res
        ncell = sum(len(r) for r in rows)
        nfull = sum(1 for r in rows for c in r if c)
        multi_rows = sum(1 for r in rows if sum(1 for c in r if c) >= 2)
        if len(rows) < min_rows or nfull < 0.5 * ncell or multi_rows < 0.6 * len(rows):
            continue
        # listas con viñetas o numeradas: la «primera columna» son solo las marcas
        marks = [r[0] for r in rows if r[0]]
        if marks and len(marks) >= 0.8 * len(rows) and (
                all(_LIST_MARK.match(m) or (len(cols) == 2 and _NUM_MARK.match(m)) for m in marks)):
            continue
        # texto a dos columnas (artículos, boletines): celdas largas, no es una tabla
        nwords = sorted(len(c.split()) for r in rows for c in r if c)
        if nwords[len(nwords) // 2] > 5 or (len(cols) == 2 and nwords[len(nwords) // 2] > 3
                                            and not any(is_numeric(c) for r in rows for c in r if c)):
            continue
        rect = pymupdf.Rect(min(l.x0 for l in zl), min(l.y0 for l in zl), max(l.x1 for l in zl), max(l.y1 for l in zl))
        widths = [max(c[1] - c[0], 10) + 13 for c in cols]   # + márgenes interiores de la celda
        out.append(TextTable(rect, rows, widths, zl))
    return out


def page_layout(page, tables=()):
    """Contenido de la página en filas para una hoja: lista de (filas, es_tabla), en orden
    de lectura (el texto a varias columnas sale columna a columna).
    tables: tablas dibujadas ya reconocidas (rect, filas); su texto no se repite."""
    rects = [pymupdf.Rect(t[0]) for t in tables]
    words, bars = _words(page, exclude=rects)
    tt = text_tables(page, min_rows=2, extracted=(words, bars))
    in_table = {id(w) for t in tt for l in t.lines for w in l.words}
    # renglones del texto normal, en el orden del PDF (une los trozos de un mismo renglón)
    groups = []
    for w in words:
        if id(w) in in_table:
            continue
        if groups:
            g = groups[-1]
            last = g[-1]
            if w.seq == last.seq or (abs(w.base - last.base) < 0.3 * max(w.size, last.size)
                                     and -1 <= w.x0 - last.x1 < 3 * max(w.size, last.size)):
                g.append(w)
                continue
        groups.append([w])
    prose = []
    for g in groups:
        ln = VLine(sorted(g, key=lambda w: w.x0), statistics.median(w.size for w in g),
                   y0=min(w.y0 for w in g), y1=max(w.y1 for w in g))
        _phrases(ln, ())
        prose.append((ln.y0, [[p.text for p in ln.phrases]]))
    tabs = sorted([(pymupdf.Rect(t[0]).y0, t[1]) for t in tables] + [(t.rect.y0, t.rows) for t in tt],
                  key=lambda t: t[0])
    out = []
    for y, rows in prose:
        while tabs and tabs[0][0] <= y:
            out.append((tabs.pop(0)[1], True))
        out.append((rows, False))
    out.extend((rows, True) for _y, rows in tabs)
    return out
