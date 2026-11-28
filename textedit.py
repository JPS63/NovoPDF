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

"""Edición de párrafos que conserva el aspecto del documento.

Antes (1.3.0 y anteriores) al editar un párrafo se borraba entero y se volvía a escribir
con una sola fuente (la del primer carácter, que en una lista era la de la viñeta), sin
negritas ni cursivas, sin justificar y ocupando a veces más espacio que el original.

Ahora:
  1. Se comparan el texto original y el nuevo palabra a palabra.
  2. Solo se borran y se vuelven a escribir las palabras que cambian y, si hace falta,
     las que van detrás en la misma línea (desplazadas lo justo).
  3. Cada palabra conserva su fuente, tamaño, color, negrita y cursiva; las palabras
     nuevas toman el estilo de las que sustituyen.
  4. Las líneas justificadas siguen justificadas: la diferencia de anchura se reparte
     entre los espacios de la línea.
  5. Si el texto ya no cabe en la línea, se recoloca dentro del mismo párrafo, en las
     mismas líneas. Si sigue sin caber, se estrecha ligeramente (máx. 7 %) o se usa una
     línea más si debajo hay hueco libre. Nunca se escribe encima de otro contenido:
     si no hay sitio se avisa (NoSpace) para que el usuario decida.
  6. Las marcas (resaltado, subrayado, tachado) de las palabras que se mueven se mueven
     con ellas.
  7. Al terminar se comprueba que en la página está exactamente el texto esperado; si no,
     se lanza EditError y quien llama deshace el cambio.
"""
from __future__ import annotations

import difflib
import logging
from dataclasses import dataclass, field

import pymupdf

log = logging.getLogger("novopdf.edicion")

FLAGS = pymupdf.TEXTFLAGS_TEXT | pymupdf.TEXT_INHIBIT_SPACES
MIN_CONDENSE = 0.93


class Unsupported(Exception):
    """El bloque no se puede editar con este método (texto girado, vertical...)."""


class NoSpace(Exception):
    """El texto nuevo no cabe sin tapar otro contenido."""

    def __init__(self, extra_lines: int, shrink: float | None):
        super().__init__("No hay sitio para el texto nuevo.")
        self.extra_lines = extra_lines
        self.shrink = shrink          # factor de reducción de la letra que lo haría caber


class EditError(Exception):
    pass


# ---------------------------------------------------------------- modelo
@dataclass(frozen=True)
class Style:
    font: str
    size: float
    color: int
    flags: int
    asc: float
    desc: float
    alpha: int = 255

    @property
    def bold(self) -> bool:
        return bool(self.flags & 16) or "bold" in self.font.lower() or "black" in self.font.lower()

    @property
    def italic(self) -> bool:
        f = self.font.lower()
        return bool(self.flags & 2) or "italic" in f or "oblique" in f


@dataclass(eq=False)
class Glyph:
    c: str
    x: float
    y: float
    bbox: pymupdf.Rect
    st: Style
    line: int
    real: bool = True          # False: espacio deducido por MuPDF (no existe en la página)
    idx: int = 0               # posición en su línea
    row: list = None           # glifos de su línea

    @property
    def x1(self) -> float:
        return max(self.bbox.x1, self.x)


@dataclass(eq=False)
class Item:
    """Elemento del texto nuevo: un carácter original (g) o uno nuevo (c + estilo)."""
    c: str
    st: Style
    g: Glyph | None = None
    replaced: tuple = ()          # glifos originales a los que sustituye
    brk: str = ""                 # "" | "soft" (salto de línea original) | "hard" (salto nuevo)


@dataclass
class Placed:
    item: Item
    x: float
    y: float
    hscale: float = 1.0
    size_f: float = 1.0
    fix: tuple = (0.0, 0.0)


@dataclass
class Result:
    mode: str                      # inline | reflow | condensed | extra | shrunk
    notes: list = field(default_factory=list)
    lines_changed: int = 0


def _rawdict_lines(page, bbox: pymupdf.Rect):
    """Líneas del bloque de texto cuyo rectángulo coincide con bbox."""
    from .editing import merged_text_blocks
    best, bestd = None, 1e9
    for b in merged_text_blocks(page):
        r = pymupdf.Rect(b["bbox"])
        d = abs(r.x0 - bbox.x0) + abs(r.y0 - bbox.y0) + abs(r.x1 - bbox.x1) + abs(r.y1 - bbox.y1)
        if d < bestd:
            best, bestd = b, d
    if best is None or bestd > 4:
        raise Unsupported("No se ha encontrado el párrafo en la página.")
    return best["lines"]


def _real_spaces(page) -> set:
    out = set()
    for b in page.get_text("rawdict", flags=FLAGS).get("blocks", []):
        if b.get("type") != 0:
            continue
        for ln in b["lines"]:
            for s in ln["spans"]:
                for ch in s["chars"]:
                    if ch["c"].isspace():
                        out.add((round(ch["origin"][0], 2), round(ch["origin"][1], 2)))
    return out


def build_model(page, block) -> tuple[list[list[Glyph]], str]:
    lines_raw = getattr(block, "raw_lines", None) or _rawdict_lines(page, block.bbox)
    real_sp = _real_spaces(page)
    lines: list[list[Glyph]] = []
    for ln in lines_raw:
        d = ln.get("dir", (1, 0))
        glyphs = []
        for s in ln["spans"]:
            asc, desc = s.get("ascender", 0.9), s.get("descender", -0.25)
            st = Style(s.get("font", ""), round(float(s["size"]), 2), int(s.get("color", 0)),
                       int(s.get("flags", 0)), float(asc), float(desc), int(s.get("alpha", 255)))
            for ch in s.get("chars", []):
                o = ch["origin"]
                real = not ch["c"].isspace() or (round(o[0], 2), round(o[1], 2)) in real_sp
                glyphs.append(Glyph(ch["c"], float(o[0]), float(o[1]), pymupdf.Rect(ch["bbox"]), st, 0, real))
        txt = "".join(g.c for g in glyphs)
        if not txt.strip():
            continue
        if abs(d[0] - 1) > 1e-3 or abs(d[1]) > 1e-3:
            raise Unsupported("Texto girado o vertical.")
        glyphs = glyphs[:len(txt.rstrip())]
        k = len(lines)
        for n, g in enumerate(glyphs):
            g.line = k
            g.idx = n
            g.row = glyphs
        lines.append(glyphs)
    if not lines:
        raise Unsupported("Párrafo vacío.")
    text = "\n".join("".join(g.c for g in ln) for ln in lines)
    return lines, text


# ---------------------------------------------------------------- fuentes
class FontCache:
    """Fuente para cada estilo original: la incrustada si sirve, la instalada o la más parecida."""

    def __init__(self, page):
        self.page = page
        self._cands = {}
        self._fonts = {}
        self.choices = {}

    def _candidates(self, st: Style):
        from . import editing, fonts
        k = (st.font, st.bold, st.italic)
        if k not in self._cands:
            kind = editing._guess_family(st.font, st.flags)
            self._cands[k] = fonts.candidates(self.page, st.font, kind, st.bold, st.italic)
        return self._cands[k]

    def prepare(self, needs: dict):
        """needs: {Style: set(caracteres)} -> elige una fuente que tenga todos."""
        from . import fonts
        for st, chars in needs.items():
            k = (st.font, st.bold, st.italic)
            prev = self.choices.get(k)
            text = "".join(sorted(chars | (prev[1] if prev else set())))
            ch = fonts.best_for_text(self._candidates(st), text)
            self.choices[k] = (ch, set(text))

    def font(self, st: Style) -> pymupdf.Font:
        k = (st.font, st.bold, st.italic)
        if k not in self.choices:
            self.prepare({st: set()})
        ch = self.choices[k][0]
        if id(ch) not in self._fonts:
            self._fonts[id(ch)] = ch.font()
        return self._fonts[id(ch)]

    def adv(self, st: Style, c: str) -> float:
        try:
            return self.font(st).text_length(c, fontsize=st.size)
        except Exception:
            return st.size * 0.5

    def approximate(self) -> list[str]:
        out = []
        for (name, _, _), (ch, _) in self.choices.items():
            if ch.kind not in ("embedded", "system"):
                out.append(f"«{name.split('+')[-1]}» → {ch.label}")
        return out


# ---------------------------------------------------------------- diferencias
def _regions(old: str, new: str):
    sm = difflib.SequenceMatcher(None, old, new, autojunk=False)
    regs = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        # Ampliar a palabras completas, salvo que lo insertado o borrado empiece/acabe en espacio
        seg = (old[i1:i2] or "") + (new[j1:j2] or "")
        first_sp = (old[i1:i2][:1].isspace() if i2 > i1 else True) and (new[j1:j2][:1].isspace() if j2 > j1 else True)
        last_sp = (old[i1:i2][-1:].isspace() if i2 > i1 else True) and (new[j1:j2][-1:].isspace() if j2 > j1 else True)
        if not (seg and first_sp):
            while i1 > 0 and j1 > 0 and not old[i1 - 1].isspace() and old[i1 - 1] == new[j1 - 1]:
                i1 -= 1
                j1 -= 1
        if not (seg and last_sp):
            while i2 < len(old) and j2 < len(new) and not old[i2].isspace() and old[i2] == new[j2]:
                i2 += 1
                j2 += 1
        if regs and i1 <= regs[-1][1]:
            regs[-1][1] = max(regs[-1][1], i2)
            regs[-1][3] = max(regs[-1][3], j2)
        else:
            regs.append([i1, i2, j1, j2])
    return regs


def _style_for(new_seg: str, old_glyphs: list, before: Glyph | None, after: Glyph | None) -> list:
    """Estilo de cada carácter nuevo: palabra a palabra si coincide el número de palabras."""
    visible = [g for g in old_glyphs if g is not None and not g.c.isspace()]
    fallback = (visible[0].st if visible else
                (before.st if before is not None else (after.st if after is not None else None)))
    if fallback is None:
        raise Unsupported("Sin estilo de referencia.")
    if not visible:
        return [fallback] * len(new_seg)
    # palabras antiguas y nuevas
    old_words, cur = [], []
    for g in old_glyphs:
        if g is None or g.c.isspace():
            if cur:
                old_words.append(cur)
                cur = []
        else:
            cur.append(g)
    if cur:
        old_words.append(cur)
    nw = new_seg.split()
    out = []
    if len(nw) == len(old_words):
        wi, inword = -1, False
        for c in new_seg:
            if c.isspace():
                inword = False
                out.append(old_words[max(wi, 0)][0].st if wi >= 0 else fallback)
            else:
                if not inword:
                    wi += 1
                    inword = True
                out.append(old_words[wi][0].st)
        return out
    n = max(1, len(new_seg))
    for t, _ in enumerate(new_seg):
        out.append(visible[min(len(visible) - 1, int(t * len(visible) / n))].st)
    return out


def build_items(lines, old: str, new: str) -> list[Item]:
    """Secuencia de elementos del texto nuevo (con los saltos de línea originales marcados)."""
    pos = []                       # glifo de cada posición de old (None = salto de línea)
    for k, ln in enumerate(lines):
        if k:
            pos.append(None)
        pos.extend(ln)
    regs = _regions(old, new)
    items: list[Item] = []
    i = 0

    def emit_old(a, b):
        for t in range(a, b):
            g = pos[t]
            if g is None:
                items.append(Item("\n", None, brk="soft"))
            else:
                items.append(Item(g.c, g.st, g=g))

    for i1, i2, j1, j2 in regs:
        emit_old(i, i1)
        seg_old = pos[i1:i2]
        seg_new = new[j1:j2]
        before = next((pos[t] for t in range(i1 - 1, -1, -1) if pos[t] is not None and not pos[t].c.isspace()), None)
        after = next((pos[t] for t in range(i2, len(pos)) if pos[t] is not None and not pos[t].c.isspace()), None)
        styles = _style_for(seg_new.replace("\n", " "), seg_old, before, after)
        old_breaks = sum(1 for g in seg_old if g is None)
        new_breaks = seg_new.count("\n")
        replaced = tuple(g for g in seg_old if g is not None)
        for t, c in enumerate(seg_new):
            if c == "\n":
                items.append(Item("\n", None, brk="soft" if old_breaks == new_breaks else "hard"))
            else:
                items.append(Item(c, styles[t], replaced=replaced))
        i = i2
    emit_old(i, len(pos))
    return items


# ---------------------------------------------------------------- utilidades de maquetación
def _words(items: list[Item]) -> list[list[Item]]:
    return _split(items)[0]


def _split(items: list[Item]):
    """Palabras y, entre cada dos, los espacios que las separan."""
    words, seps, cur, sep = [], [], [], []
    for it in items:
        if it.c.isspace():
            if cur:
                words.append(cur)
                cur = []
            if words:
                sep.append(it)
        else:
            if not cur and words:
                seps.append(sep)
            if not cur:
                sep = []
            cur.append(it)
    if cur:
        words.append(cur)
    return words, seps


def _is_old_word(w: list[Item]) -> bool:
    """Palabra formada por glifos originales consecutivos de una misma línea."""
    if not all(it.g is not None for it in w):
        return False
    gs = [it.g for it in w]
    ln = gs[0].line
    return all(g.line == ln for g in gs) and all(gs[k + 1].x >= gs[k].x - 0.01 for k in range(len(gs) - 1))


def _word_shape(w: list[Item], fc: FontCache) -> tuple[list[float], float]:
    """Posiciones relativas de cada carácter y anchura total de la palabra."""
    if _is_old_word(w):
        x0 = w[0].g.x
        rel = [it.g.x - x0 for it in w]
        last = w[-1]
        width = last.g.x1 - x0 if last.g.x1 > last.g.x + 0.05 else rel[-1] + fc.adv(last.st, last.c)
        return rel, width
    rel, x = [], 0.0
    for it in w:
        rel.append(x)
        x += fc.adv(it.st, it.c)
    return rel, x


def _space_w(st: Style, fc: FontCache) -> float:
    w = fc.adv(st, " ")
    return w if w > 0.5 else st.size * 0.25


@dataclass
class LineInfo:
    index: int
    glyphs: list
    start: float
    end: float
    y: float
    bullet: bool = False
    para_end: bool = False
    justified: bool = False


def _analyze(lines) -> list[LineInfo]:
    infos = []
    for k, ln in enumerate(lines):
        infos.append(LineInfo(k, ln, ln[0].x, max(g.x1 for g in ln), ln[0].y))
    # viñetas: línea corta sin letras que comparte renglón con la siguiente
    for li in infos:
        t = "".join(g.c for g in li.glyphs).strip()
        if len(t) <= 2 and not any(ch.isalnum() for ch in t):
            if any(o is not li and abs(o.y - li.y) < 1.0 and o.start > li.end for o in infos):
                li.bullet = True
    flow = [li for li in infos if not li.bullet]
    if not flow:
        return infos
    R = max(li.end for li in flow)
    sizes = [g.st.size for li in flow for g in li.glyphs if not g.c.isspace()]
    fs = sorted(sizes)[len(sizes) // 2] if sizes else 10
    for n, li in enumerate(flow):
        nxt = flow[n + 1] if n + 1 < len(flow) else None
        li.para_end = (nxt is None or li.end < R - 2.5 * fs
                       or any(b.bullet and abs(b.y - nxt.y) < 1.0 for b in infos)
                       or (nxt.start > li.start + 3 and n > 0 and abs(flow[n - 1].start - li.start) < 1.5
                           and not flow[n - 1].para_end))
    # justificación por párrafo
    para = []
    for li in flow:
        para.append(li)
        if li.para_end:
            body = [p for p in para if not p.para_end]
            if body:
                pr = max(p.end for p in para)
                just = all(abs(p.end - pr) < 2.0 for p in body)
                for p in body:
                    p.justified = just
            para = []
    return infos


def _paragraphs(infos) -> list[list[LineInfo]]:
    out, cur = [], []
    for li in infos:
        if li.bullet:
            continue
        cur.append(li)
        if li.para_end:
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


# ---------------------------------------------------------------- obstáculos
def _obstacles(page, exclude_glyphs: set, exclude_rect: pymupdf.Rect) -> list[pymupdf.Rect]:
    """Rectángulos de lo que hay en la página (texto, imágenes, dibujos) salvo el párrafo editado."""
    out = []
    raw = page.get_text("rawdict", flags=FLAGS)
    for b in raw.get("blocks", []):
        if b.get("type") != 0:
            continue
        for ln in b["lines"]:
            for s in ln["spans"]:
                for ch in s["chars"]:
                    if ch["c"].isspace():
                        continue
                    r = pymupdf.Rect(ch["bbox"])
                    key = (round(ch["origin"][0], 2), round(ch["origin"][1], 2), ch["c"])
                    if key in exclude_glyphs:
                        continue
                    out.append(r)
    try:
        for info in page.get_image_info():
            r = pymupdf.Rect(info["bbox"])
            if not r.is_empty and not r.contains(exclude_rect):
                out.append(r)
    except Exception:
        pass
    try:
        for d in page.get_drawings():
            r = pymupdf.Rect(d["rect"])
            if r.is_empty and r.width < 0.1 and r.height < 0.1:
                continue
            if r.contains(exclude_rect):        # fondos y marcos que rodean el párrafo
                continue
            out.append(r)
    except Exception:
        pass
    return out


def _lost(before, after, tol=0.3):
    """Caracteres de before que no están en after (misma letra a menos de tol puntos)."""
    from collections import defaultdict
    idx = defaultdict(list)
    for c in after:
        idx[(c[2], round(c[1]))].append(c)
    out = []
    for c in before:
        cands = idx.get((c[2], round(c[1])), []) + idx.get((c[2], round(c[1]) + (1 if c[1] - round(c[1]) > 0 else -1)), [])
        hit = next((a for a in cands if abs(a[0] - c[0]) < tol and abs(a[1] - c[1]) < tol), None)
        if hit is None:
            out.append(c)
        else:
            for lst in idx.values():
                if hit in lst:
                    lst.remove(hit)
                    break
    return out


def _free(rect: pymupdf.Rect, obstacles) -> bool:
    shrunk = rect + (0.5, 0.5, -0.5, -0.5)
    return not any(shrunk.intersects(o) for o in obstacles)


# ---------------------------------------------------------------- maquetación de una línea
def _layout_line(words, start, y, fc, gap_of, target_end=None, min_ratio=0.45, max_ratio=4.0, seps=None):
    """Coloca palabras desde start. gap_of(k) -> hueco natural tras la palabra k.
    Si target_end, los huecos se ajustan para terminar ahí (justificado).
    seps[k]: espacios originales entre la palabra k y la k+1 (se reutilizan)."""
    shapes = [_word_shape(w, fc) for w in words]
    gaps = [gap_of(k) for k in range(len(words) - 1)]
    natural_end = start + sum(s[1] for s in shapes) + sum(gaps)
    if target_end is not None and gaps:
        extra = (target_end - natural_end) / len(gaps)
        sw = [_space_w(words[k][-1].st, fc) for k in range(len(gaps))]
        newg = [g + extra for g in gaps]
        if any(ng < min_ratio * s or ng > max_ratio * s + 6 for ng, s in zip(newg, sw)):
            return None
        gaps = newg
    placed, x = [], start
    for k, (w, (rel, width)) in enumerate(zip(words, shapes)):
        for it, r in zip(w, rel):
            placed.append(Placed(it, x + r, y))
        x += width
        if k < len(gaps):
            sep = seps[k] if seps and k < len(seps) else []
            old_sp = [it for it in sep if it.g is not None]
            prev = w[-1]
            nxt = words[k + 1][0]
            between = (prev.g is not None and nxt.g is not None and prev.g.row is nxt.g.row and old_sp
                       and prev.g.idx < nxt.g.idx
                       and all(prev.g.row[t].c.isspace() for t in range(prev.g.idx + 1, nxt.g.idx)))
            if between:
                # los espacios originales conservan su posición relativa a la palabra anterior
                for it in old_sp:
                    placed.append(Placed(it, x + (it.g.x - prev.g.x1), y))
            elif old_sp:
                placed.append(Placed(old_sp[0], x, y))
            else:
                placed.append(Placed(Item(" ", prev.st), x, y))   # espacio (para copiar y buscar)
            x += gaps[k]
    return placed, x


def _orig_gaps(li: LineInfo):
    """Huecos originales entre palabras consecutivas de una línea: {(id ult glifo, id primer glifo sig): hueco}."""
    out = {}
    words, cur = [], []
    for g in li.glyphs:
        if g.c.isspace():
            if cur:
                words.append(cur)
                cur = []
        else:
            cur.append(g)
    if cur:
        words.append(cur)
    for a, b in zip(words, words[1:]):
        out[(id(a[-1]), id(b[0]))] = b[0].x - a[-1].x1
    vals = list(out.values())
    med = sorted(vals)[len(vals) // 2] if vals else None
    return out, med


# ---------------------------------------------------------------- motor
class Editor:
    def __init__(self, page, block, new_text: str):
        if page.rotation % 360:
            raise Unsupported("Página girada.")
        self.page = page
        self.lines, self.old = build_model(page, block)
        self.new = new_text.replace("\r\n", "\n").replace("\r", "\n").rstrip()
        self.infos = _analyze(self.lines)
        self.fc = FontCache(page)
        self.items = build_items(self.lines, self.old, self.new)

    # -------------------------------------------------- planificación
    def _line_items(self):
        """Elementos por línea original (solo si se conservan todos los saltos originales)."""
        per, cur = [], []
        for it in self.items:
            if it.brk == "hard":
                return None
            if it.brk == "soft":
                per.append(cur)
                cur = []
            else:
                cur.append(it)
        per.append(cur)
        if len(per) != len(self.lines):
            return None
        return per

    def _prepare_fonts(self, placed_items):
        needs = {}
        for it in placed_items:
            if it.st is not None:
                needs.setdefault(it.st, set()).add(it.c)
        self.fc.prepare(needs)

    def plan_inline(self):
        """Modo A: cada línea conserva sus palabras; solo cambian las líneas tocadas."""
        per = self._line_items()
        if per is None:
            return None
        self._prepare_fonts([it for line in per for it in line if it.g is None])
        plan = {}
        for li, items in zip(self.infos, per):
            if len(items) == len(li.glyphs) and all(it.g is g for it, g in zip(items, li.glyphs)):
                continue
            if li.bullet:
                return None
            words, seps = _split(items)
            if not words:
                plan[li.index] = []
                continue
            og, med = _orig_gaps(li)
            old_words = _words([Item(g.c, g.st, g=g) for g in li.glyphs])
            f = 0
            while (f < min(len(words), len(old_words)) and len(words[f]) == len(old_words[f]) and
                   all(a.g is b.g for a, b in zip(words[f], old_words[f]))):
                f += 1
            if f >= len(words):
                f = len(words) - 1

            def gap_of(k, words=words, og=og, med=med):
                a, b = words[k][-1], words[k + 1][0]
                if a.g is not None and b.g is not None and (id(a.g), id(b.g)) in og:
                    return og[(id(a.g), id(b.g))]
                return med if med is not None else _space_w(a.st, self.fc)

            def attempt(anchor):
                """anchor = índice de la primera palabra que se coloca (queda en su sitio)."""
                sub = words[anchor:]
                sub_seps = seps[anchor:]
                start = sub[0][0].g.x if (anchor > 0 or sub[0][0].g is not None) and sub[0][0].g is not None else li.start
                if anchor == 0:
                    start = li.start if sub[0][0].g is None else sub[0][0].g.x

                def g2(k):
                    return gap_of(k + anchor)
                if li.justified:
                    res = _layout_line(sub, start, li.y, self.fc, g2, target_end=li.end, seps=sub_seps)
                else:
                    res = _layout_line(sub, start, li.y, self.fc, g2, seps=sub_seps)
                if res is None:
                    return None
                placed, end = res
                if not li.justified:
                    if end > self._limit(li) + 0.5:
                        return None
                    if end > li.end + 0.5 and not self._room_right(li, li.end, end):
                        return None
                first_g = sub[0][0].g if sub[0][0].g is not None else None
                if anchor > 0 and first_g is not None:
                    k = li.glyphs.index(first_g)
                    keep = [Placed(Item(g.c, g.st, g=g), g.x, g.y) for g in li.glyphs[:k]]
                else:
                    keep = []
                return keep + placed

            placed = None
            # 1) la palabra anterior al cambio queda fija y se recoloca lo de detrás
            if f > 0 and _is_old_word(words[f - 1]):
                placed = attempt(f - 1)
            # 2) toda la línea
            if placed is None:
                placed = attempt(0)
            if placed is None:
                return None
            plan[li.index] = placed
        return plan

    def _limit(self, li):
        para = next((p for p in _paragraphs(self.infos) if li in p), [li])
        R = max(p.end for p in para)
        if len(para) > 1:
            return R + 1.0
        return self.page.rect.x1 - max(18.0, min(li.start, 72.0))

    def _room_right(self, li, x0, x1):
        g = li.glyphs[0]
        r = pymupdf.Rect(x0 + 0.5, li.y - g.st.size * 0.8, x1, li.y + 0.1)
        excl = {(round(g.x, 2), round(g.y, 2), g.c) for ln in self.lines for g in ln}
        return _free(r, _obstacles(self.page, excl, self._block_rect()))

    def _block_rect(self):
        r = pymupdf.Rect()
        for ln in self.lines:
            for g in ln:
                r |= g.bbox
        return r

    def plan_reflow(self, condense=1.0, shrink=1.0, extra_ok=0, whole=False):
        """Modo B: recolocar las palabras dentro del párrafo (mismas líneas y sangrías)."""
        paras = _paragraphs(self.infos)
        # primera línea cambiada
        changed_lines = set()
        cur_line = 0
        for it in self.items:
            if it.brk:
                if it.brk == "soft":
                    cur_line += 1
                else:
                    changed_lines.add(cur_line)
                continue
            if it.g is None:
                changed_lines.add(cur_line)
        # líneas originales cuyo contenido desaparece (borrados)
        kept = {id(it.g) for it in self.items if it.g is not None}
        for li in self.infos:
            if any(id(g) not in kept for g in li.glyphs):
                changed_lines.add(li.index)
        if not changed_lines:
            return {}, 0
        first = min(changed_lines)
        last = max(changed_lines)
        sel = []
        for p in paras:
            idx = [li.index for li in p]
            if idx[-1] >= first and idx[0] <= last:
                sel.extend(p)
        if not sel:
            return None
        start_line = sel[0] if whole else next((li for li in sel if li.index >= first), sel[0])
        lines_avail = [li for li in sel if li.index >= start_line.index]
        # elementos que entran en el recolocado: desde el principio de start_line hasta el final de sel
        per_line_start = {}
        cur, line_no = [], 0
        seq = []
        for it in self.items:
            if it.brk:
                if it.brk == "soft":
                    line_no += 1
                    if start_line.index <= line_no <= sel[-1].index:
                        seq.append(Item(" ", None))
                    continue
                if start_line.index <= line_no <= sel[-1].index:
                    seq.append(Item("\n", None, brk="hard"))
                continue
            if start_line.index <= line_no <= sel[-1].index:
                if it.g is not None and self.infos[it.g.line].bullet:
                    continue
                seq.append(it)
        # palabras y saltos forzados
        tokens, curw = [], []
        for it in seq:
            if it.brk == "hard":
                if curw:
                    tokens.append(curw)
                    curw = []
                tokens.append("\n")
            elif it.c.isspace():
                if curw:
                    tokens.append(curw)
                    curw = []
            else:
                curw.append(it)
        if curw:
            tokens.append(curw)
        self._prepare_fonts([it for t in tokens if t != "\n" for it in t if it.g is None])
        R = max(li.end for li in sel)
        justified = any(li.justified for li in sel)
        lead = self._leading(sel)
        cont_x = sel[1].start if len(sel) > 1 else sel[0].start
        slots = [(li.start, li.y) for li in lines_avail]
        base_y = lines_avail[-1].y
        for k in range(extra_ok):
            slots.append((cont_x, base_y + lead * (k + 1)))
        f = condense * shrink
        # reparto voraz
        rows, row, width = [], [], 0.0
        k = 0
        shapes = {}

        def shape(w):
            if id(w) not in shapes:
                rel, wd = _word_shape(w, self.fc)
                shapes[id(w)] = ([r * f for r in rel], wd * f)
            return shapes[id(w)]

        for t in tokens:
            if k >= len(slots):
                k += 1
                break
            avail = R - slots[k][0]
            if t == "\n":
                rows.append((row, True))
                row, width = [], 0.0
                k += 1
                continue
            wd = shape(t)[1]
            gap = _space_w(t[0].st, self.fc) * f if row else 0.0
            if row and width + gap + wd > avail + 0.3:
                rows.append((row, False))
                k += 1
                row, width = [t], wd
                if k < len(slots) and wd > R - slots[k][0] + 0.3:
                    return None
                continue
            if not row and wd > avail + 0.3:
                return None
            row.append(t)
            width += gap + wd
        if row:
            rows.append((row, True))
        needed = len(rows)
        if needed > len(slots):
            return ("short", needed - len(lines_avail))
        plan = {}
        for n, (li_slot, (row, hard_end)) in enumerate(zip(slots, rows)):
            x0, y = li_slot
            is_last = (n == len(rows) - 1) or hard_end
            placed, x = [], x0
            shp = [shape(w) for w in row]
            natural = [(_space_w(w[-1].st, self.fc) * f) for w in row[:-1]]
            gaps = list(natural)
            if justified and not is_last and gaps:
                extra = (R - x0 - sum(s[1] for s in shp) - sum(gaps)) / len(gaps)
                gaps = [g + extra for g in gaps]
            for j, (w, (rel, wd)) in enumerate(zip(row, shp)):
                for it, r in zip(w, rel):
                    placed.append(Placed(it, x + r, y, size_f=shrink))
                x += wd
                if j < len(gaps):
                    placed.append(Placed(Item(" ", w[-1].st), x, y, size_f=shrink))
                    x += gaps[j]
            if condense != 1.0:
                for p in placed:
                    p.hscale = condense
                    p.fix = (x0, y)
            key = lines_avail[n].index if n < len(lines_avail) else ("extra", n - len(lines_avail))
            plan[key] = placed
        for li in lines_avail[len(rows):]:
            plan[li.index] = []
        return plan, max(0, needed - len(lines_avail))

    def _leading(self, sel):
        ys = [li.y for li in sel]
        gaps = [b - a for a, b in zip(ys, ys[1:]) if b - a > 0.5]
        if gaps:
            return sorted(gaps)[len(gaps) // 2]
        sz = sel[0].glyphs[0].st.size
        return sz * 1.17

    # -------------------------------------------------- aplicar
    def _collides(self, plan) -> bool:
        """¿Alguna línea nueva taparía texto, imágenes o dibujos que no son de este párrafo?"""
        if not hasattr(self, "_obs"):
            excl = {(round(g.x, 2), round(g.y, 2), g.c) for ln in self.lines for g in ln}
            self._obs = _obstacles(self.page, excl, self._block_rect())
            # los dibujos que ya se cruzaban con el párrafo (subrayados, recuadros) no cuentan
            br = self._block_rect()
            self._obs = [o for o in self._obs if not o.intersects(br) or o.height > 3 and o.width > 3
                         and not br.intersects(o)]
        for placed in plan.values():
            vis = [p for p in placed if not p.item.c.isspace()]
            if not vis:
                continue
            st = vis[0].item.st
            y = vis[0].y
            x0 = min(p.x for p in vis)
            x1 = max(p.x + self.fc.adv(p.item.st, p.item.c) * p.hscale * p.size_f for p in vis)
            r = pymupdf.Rect(x0 + 0.3, y - st.size * 0.6 * vis[0].size_f, x1 - 0.3, y - 0.3)
            if not _free(r, self._obs):
                return True
        return False

    def run(self, allow_shrink: float | None = None) -> Result:
        if self.new == self.old:
            return Result("none")
        res = self._run(allow_shrink)
        return res

    def _ok(self, out):
        """Plan válido (no «short», no None) y que no tapa nada."""
        if out is None:
            return None
        if isinstance(out, tuple):
            if out and out[0] == "short":
                return None
            out = out[0]
        if self._collides(out):
            return None
        return out

    def _run(self, allow_shrink):
        plan = self._ok(self.plan_inline())
        if plan is not None:
            return self._apply(plan, Result("inline"))
        if allow_shrink:
            o = self._ok(self.plan_reflow(shrink=allow_shrink, whole=True))
            if o is not None:
                return self._apply(o, Result("shrunk", [f"Letra del párrafo al {round(allow_shrink * 100)} %"]))
            raise NoSpace(0, None)
        out = self.plan_reflow()
        if out is None:
            raise Unsupported("Una palabra no cabe en la línea.")
        o = self._ok(out)
        if o is not None:
            return self._apply(o, Result("reflow"))
        o = self._ok(self.plan_reflow(whole=True))
        if o is not None:
            return self._apply(o, Result("reflow"))
        # estrechar ligeramente todo el párrafo
        c = 0.99
        while c >= MIN_CONDENSE - 1e-9:
            o = self._ok(self.plan_reflow(condense=c, whole=True))
            if o is not None:
                return self._apply(o, Result("condensed", [f"Texto del párrafo estrechado al {round(c * 100)} %"]))
            c -= 0.01
        extra = out[1] if out[0] == "short" else 0
        # ¿hay hueco debajo para una línea más?
        o = self.plan_reflow(extra_ok=extra) if extra else None
        if o and o[0] != "short" and not self._collides(o[0]):
            new_rows = [v for k, v in o[0].items() if isinstance(k, tuple)]
            excl = {(round(g.x, 2), round(g.y, 2), g.c) for ln in self.lines for g in ln}
            obs = _obstacles(self.page, excl, self._block_rect())
            ok = True
            for row in new_rows:
                if not row:
                    continue
                st = row[0].item.st
                y = row[0].y
                r = pymupdf.Rect(min(p.x for p in row), y - st.size * 0.95, max(p.x for p in row) + st.size, y + st.size * 0.3)
                if not _free(r, obs) or r.y1 > self.page.rect.y1 - 10:
                    ok = False
            if ok:
                return self._apply(o[0], Result("extra", [f"El párrafo ocupa {extra} línea(s) más"]))
        # proponer reducir la letra de todo el párrafo
        s = 0.98
        while s >= 0.70:
            if self._ok(self.plan_reflow(shrink=s, whole=True)) is not None:
                raise NoSpace(extra, round(s, 2))
            s -= 0.01
        raise NoSpace(extra, None)

    def _apply(self, plan: dict, res: Result) -> Result:
        page = self.page
        # 1) qué glifos se quitan y qué se dibuja
        remove, draw = [], []
        new_pos = {id(p.item.g): p for placed in plan.values() for p in placed if p.item.g is not None}
        for key in plan:
            orig = self.lines[key] if isinstance(key, int) else []
            for g in orig:
                p = new_pos.get(id(g))
                if p is None or abs(p.x - g.x) > 0.02 or abs(p.y - g.y) > 0.02 or p.hscale != 1.0 or p.size_f != 1.0:
                    remove.append(g)
        removed_ids = {id(g) for g in remove}
        for key, placed in plan.items():
            for p in placed:
                if p.item.g is None:
                    if p.item.c.isspace():
                        # el espacio solo se dibuja si alguna de sus palabras vecinas se redibuja
                        draw.append(p)
                    else:
                        draw.append(p)
                elif id(p.item.g) in removed_ids:
                    draw.append(p)
        # espacios originales que ya están donde se iba a escribir uno nuevo: se dejan
        new_spaces = [p for p in draw if p.item.g is None and p.item.c.isspace()]
        if new_spaces:
            rem2 = []
            for g in remove:
                if g.c.isspace():
                    hit = next((p for p in new_spaces if abs(p.y - g.y) < 0.05 and abs(p.x - g.x) < 0.05
                                and p.hscale == 1.0 and p.size_f == 1.0), None)
                    if hit is not None:
                        new_spaces.remove(hit)
                        draw.remove(hit)
                        continue
                rem2.append(g)
            remove = rem2
        # glifos eliminados que no estaban en líneas planificadas (no debería ocurrir)
        kept = {id(it.g) for it in self.items if it.g is not None}
        for ln in self.lines:
            for g in ln:
                if id(g) not in kept and g not in remove:
                    remove.append(g)
        # espacios dibujados: descartar los que caen entre dos palabras sin tocar
        draw = self._trim_spaces(draw, plan)
        res.lines_changed = sum(1 for v in plan.values())
        # 2) fuentes
        self._prepare_fonts([p.item for p in draw])
        res.notes += [f"Fuente aproximada: {a}" for a in self.fc.approximate()]
        before = self._all_chars()
        marks = self._marks_affected(remove)
        remove = [g for g in remove if g.real]
        # 3) borrar
        for g in remove:
            r = g.bbox
            w, h = r.width, r.height
            if w < 0.6:
                rr = pymupdf.Rect(r.x0 + w / 2 - 0.05, r.y0 + h * 0.45, r.x0 + w / 2 + 0.05, r.y1 - h * 0.45)
            else:
                rr = pymupdf.Rect(r.x0 + w * 0.3, r.y0 + h * 0.42, r.x1 - w * 0.3, r.y1 - h * 0.42)
            page.add_redact_annot(rr, fill=False)
        if remove:
            page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                                  graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                                  text=pymupdf.PDF_REDACT_TEXT_REMOVE)
        after = self._all_chars()
        lost_chars = _lost(before, after)
        # qué se quería borrar y qué se ha borrado realmente (con tolerancia de posición)
        want = [(g.x, g.y, g.c) for g in remove]
        extra_chars = []
        pool = list(want)
        for c in lost_chars:
            k = next((n for n, w in enumerate(pool) if w[2] == c[2] and abs(w[0] - c[0]) < 0.3
                      and abs(w[1] - c[1]) < 0.3), None)
            if k is None:
                if any(w[2] == c[2] and abs(w[0] - c[0]) < 0.3 and abs(w[1] - c[1]) < 0.3 for w in want):
                    continue           # duplicado (negrita simulada) de algo que sí se quería borrar
                extra_chars.append(c)
            else:
                pool.pop(k)
        if pool:
            raise EditError(f"No se han podido borrar {len(pool)} carácter(es) del texto original.")
        if extra_chars:
            # MuPDF a veces quita algún carácter de más al aplicar el borrado (PDF de Word con
            # TJ y recortes): se vuelve a escribir exactamente igual, con su fuente y posición.
            n_extra = 0
            for c in extra_chars:
                draw.append(Placed(Item(c[2], c[3]), c[0], c[1]))
                n_extra += 1
            res.notes.append(f"Repuestos {n_extra} carácter(es) que MuPDF había quitado de más")
            log.info("Edición: %d carácter(es) repuestos tras el borrado", n_extra)
            self._prepare_fonts([p.item for p in draw])
        # 4) escribir
        writers = {}
        for p in draw:
            it = p.item
            st = it.st
            if st is None:
                continue
            font = self.fc.font(st)
            if it.c.isspace() and not font.has_glyph(32):
                continue
            k = (id(font), st.color, st.alpha, p.hscale, p.fix if p.hscale != 1.0 else None)
            tw = writers.get(k)
            if tw is None:
                tw = writers[k] = (pymupdf.TextWriter(page.rect), st, p)
            x = p.x
            if p.hscale != 1.0:
                x = p.fix[0] + (p.x - p.fix[0]) / p.hscale
            tw[0].append((x, p.y), it.c, font=font, fontsize=st.size * p.size_f)
        for tw, st, p in writers.values():
            col = pymupdf.sRGB_to_pdf(st.color) if hasattr(pymupdf, "sRGB_to_pdf") else (
                ((st.color >> 16) & 255) / 255, ((st.color >> 8) & 255) / 255, (st.color & 255) / 255)
            morph = None
            if p.hscale != 1.0:
                morph = (pymupdf.Point(*p.fix), pymupdf.Matrix(p.hscale, 1))
            opacity = st.alpha / 255 if st.alpha < 255 else -1
            tw.write_text(page, color=col, morph=morph, opacity=opacity)
        # 5) comprobar
        self._verify(plan)
        # 6) mover las marcas
        self._move_marks(marks, plan)
        log.info("Edición %s: %d glifos quitados, %d escritos, %d línea(s)", res.mode, len(remove),
                 len(draw), res.lines_changed)
        return res

    def _trim_spaces(self, draw, plan):
        out = []
        drawn_ids = {id(p) for p in draw}
        for key, placed in plan.items():
            for n, p in enumerate(placed):
                if id(p) not in drawn_ids:
                    continue
                if p.item.g is None and p.item.c.isspace():
                    prev = placed[n - 1] if n > 0 else None
                    nxt = placed[n + 1] if n + 1 < len(placed) else None
                    if not ((prev is not None and id(prev) in drawn_ids) or (nxt is not None and id(nxt) in drawn_ids)):
                        continue
                out.append(p)
        return out

    def _all_chars(self):
        """(x, y, carácter, estilo) de todos los caracteres reales de la página."""
        out = []
        raw = self.page.get_text("rawdict", flags=FLAGS)
        for b in raw.get("blocks", []):
            if b.get("type") != 0:
                continue
            for ln in b["lines"]:
                for s in ln["spans"]:
                    st = Style(s.get("font", ""), round(float(s["size"]), 2), int(s.get("color", 0)),
                               int(s.get("flags", 0)), float(s.get("ascender", 0.9)),
                               float(s.get("descender", -0.25)), int(s.get("alpha", 255)))
                    for ch in s["chars"]:
                        out.append((ch["origin"][0], ch["origin"][1], ch["c"], st))
        return out

    def _verify(self, plan):
        """Las palabras escritas en las líneas modificadas deben ser exactamente las previstas."""
        from collections import Counter
        expected, rects = [], []
        for key, placed in plan.items():
            if not placed:
                continue
            cur = ""
            for p in placed:
                if p.item.c.isspace():
                    if cur:
                        expected.append(cur)
                        cur = ""
                else:
                    cur += p.item.c
            if cur:
                expected.append(cur)
            st = placed[0].item.st
            y = placed[0].y
            x0 = min(p.x for p in placed)
            x1 = max(p.x + self.fc.adv(p.item.st, p.item.c) * p.hscale * p.size_f for p in placed)
            rects.append(pymupdf.Rect(x0 - 0.5, y - st.size * 0.9, x1 + 0.5, y + st.size * 0.25))
        if not expected:
            return
        got = []
        for w in self.page.get_text("words"):
            r = pymupdf.Rect(w[:4])
            cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
            if any(rr.contains(pymupdf.Point(cx, cy)) for rr in rects):
                got.append(w[4])
        # Se comparan las letras (sin espacios): MuPDF puede partir una palabra en dos si una
        # parte se escribió después, y eso no es un error.
        if Counter("".join(got)) != Counter("".join(expected)):
            raise EditError("El texto escrito no coincide con el previsto:\n"
                            f"esperado: {' '.join(expected)[:200]}\nobtenido: {' '.join(got)[:200]}")

    # -------------------------------------------------- marcas de texto
    def _marks_affected(self, removed):
        out = []
        if not removed:
            return out
        types = (pymupdf.PDF_ANNOT_HIGHLIGHT, pymupdf.PDF_ANNOT_UNDERLINE,
                 pymupdf.PDF_ANNOT_STRIKE_OUT, pymupdf.PDF_ANNOT_SQUIGGLY)
        all_glyphs = [g for ln in self.lines for g in ln]
        rem = {id(g) for g in removed}
        for a in self.page.annots(types=types):
            v = a.vertices or []
            quads = [pymupdf.Quad(v[k:k + 4]).rect for k in range(0, len(v) - 3, 4)]
            covered = []
            for q in quads:
                cov = [g for g in all_glyphs if not g.c.isspace()
                       and q.contains(pymupdf.Point((g.bbox.x0 + g.bbox.x1) / 2, (g.bbox.y0 + g.bbox.y1) / 2))]
                covered.append((q, cov))
            if any(id(g) in rem for _, cov in covered for g in cov):
                out.append((a.xref, a.type[0], covered))
        return out

    def _move_marks(self, marks, plan):
        if not marks:
            return
        newpos = {}
        repl = {}
        for placed in plan.values():
            for p in placed:
                if p.item.g is not None:
                    newpos[id(p.item.g)] = p
                for g in p.item.replaced:
                    repl.setdefault(id(g), []).append(p)
        page = self.page
        for xref, atype, covered in marks:
            annot = next((a for a in page.annots() if a.xref == xref), None)
            if annot is None:
                continue
            rects = []
            for q, cov in covered:
                pts = []
                for g in cov:
                    if id(g) in newpos:
                        pts.append(newpos[id(g)])
                    elif id(g) in repl:
                        pts.extend(repl[id(g)])
                    else:
                        pts.append(Placed(Item(g.c, g.st, g=g), g.x, g.y))
                if not cov:
                    rects.append(q)
                    continue
                if not pts:
                    continue
                by_line = {}
                for p in pts:
                    by_line.setdefault(round(p.y, 1), []).append(p)
                for y, ps in by_line.items():
                    x0 = min(p.x for p in ps)
                    x1 = max(p.x + self.fc.adv(p.item.st, p.item.c) * p.hscale * p.size_f for p in ps)
                    dy = ps[0].y - cov[0].y
                    rects.append(pymupdf.Rect(x0, q.y0 + dy, x1, q.y1 + dy))
            info = annot.info
            colors = annot.colors
            opacity = annot.opacity
            page.delete_annot(annot)
            if not rects:
                continue
            quads = [r.quad for r in rects]
            add = {pymupdf.PDF_ANNOT_HIGHLIGHT: page.add_highlight_annot,
                   pymupdf.PDF_ANNOT_UNDERLINE: page.add_underline_annot,
                   pymupdf.PDF_ANNOT_STRIKE_OUT: page.add_strikeout_annot,
                   pymupdf.PDF_ANNOT_SQUIGGLY: page.add_squiggly_annot}[atype]
            na = add(quads=quads)
            if colors.get("stroke"):
                na.set_colors(stroke=colors["stroke"])
            if opacity is not None and 0 <= opacity < 1:
                na.set_opacity(opacity)
            try:
                na.set_info(info)
            except Exception:
                pass
            na.update()


def edit_paragraph(page, block, new_text: str, allow_shrink: float | None = None) -> Result:
    """Punto de entrada. Lanza Unsupported (usar el método clásico), NoSpace o EditError."""
    from . import scanedit
    if scanedit.is_scanned_block(block, page):
        return scanedit.edit_scanned(page, block, new_text)
    return Editor(page, block, new_text).run(allow_shrink)
