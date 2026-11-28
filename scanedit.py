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

"""Editar texto en documentos escaneados.

En un escaneo con texto reconocido (OCR), lo que se ve es una imagen y el texto es una capa
invisible encima. Cambiar solo esa capa no cambia lo que se ve. Aquí, para cada palabra
cambiada:
  1. se mide en la imagen la tinta de la palabra antigua (posición, altura, anchura) y el
     color del papel y de la letra;
  2. se elige la fuente que mejor imita la letra escaneada (Courier New, Arial o Times New
     Roman, en negrita si procede) y el tamaño y la escala horizontal que la igualan;
  3. se tapa la palabra antigua con un rectángulo del color del papel y se escribe la nueva
     encima (texto visible y que se puede buscar y copiar);
  4. se quita la capa invisible de las palabras sustituidas.
Las palabras siguientes de la línea no se mueven (son parte de la imagen): si la nueva no
cabe en el hueco, se estrecha un poco o se reescribe también el resto de la línea.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import pymupdf

from . import textedit as te

log = logging.getLogger("novopdf.edicion")
DPI = 200
MIN_SCALE = 0.72


def _visibility(page):
    """(zonas de texto oculto, zonas de texto visible, hay imágenes) según el orden de dibujo."""
    try:
        log = page.get_bboxlog()
    except Exception:
        return [], [], False
    images = [(k, pymupdf.Rect(bb)) for k, (typ, bb) in enumerate(log) if typ in ("fill-image", "fill-imgmask")]
    hidden, visible = [], []
    for k, (typ, bb) in enumerate(log):
        if typ in ("ignore-text", "clip-text", "clip-stroke-text"):
            hidden.append(pymupdf.Rect(bb))
        elif typ in ("fill-text", "stroke-text"):
            r = pymupdf.Rect(bb)
            area = max(r.width * r.height, 1e-6)
            if images and any(j > k and (ir & r).width * (ir & r).height >= 0.9 * area for j, ir in images
                              if not (ir & r).is_empty):
                hidden.append(r)
            else:
                visible.append(r)
    return hidden, visible, bool(images)


def hidden_text_rects(page) -> list:
    """Zonas de texto que no se ven: texto invisible (OCR) o texto tapado por una imagen dibujada
    después (muchos escáneres y programas de OCR ponen el texto reconocido DEBAJO de la imagen)."""
    return _visibility(page)[0]


def is_scanned_block(block, page=None) -> bool:
    """Párrafo de un escaneo: su texto es (sobre todo) la capa del OCR, invisible o tapada por la
    imagen. Puede tener ya alguna palabra visible escrita por una edición anterior."""
    hidden, visible, images = _visibility(page) if page is not None else ([], [], False)
    # en una página con imágenes, el texto que no se dibuja de ninguna forma (p. ej. modo de
    # pintado «solo recorte») tampoco se ve
    vis_known = images and page is not None
    visible = [r + (-1.5, -1.5, 1.5, 1.5) for r in visible]
    n_inv = n_vis = 0
    for ln in (getattr(block, "raw_lines", None) or []):
        for s in ln.get("spans", []):
            alpha0 = int(s.get("alpha", 255)) == 0
            for c in s.get("chars", []):
                if c["c"].isspace():
                    continue
                if alpha0:
                    n_inv += 1
                    continue
                bb = c["bbox"]
                pt = pymupdf.Point((bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2)
                if hidden and any(h.contains(pt) for h in hidden):
                    n_inv += 1
                elif vis_known and not any(v.contains(pt) for v in visible):
                    n_inv += 1
                else:
                    n_vis += 1
    return n_inv > 0 and n_inv >= n_vis * 0.5


# ---------------------------------------------------------------- medidas en la imagen
@dataclass
class Ink:
    rect: pymupdf.Rect          # caja de la tinta (puntos)
    bg: tuple                   # color del papel (0-1)
    fg: tuple                   # color de la letra (0-1)


def _gray_pix(page, rect):
    pix = page.get_pixmap(clip=rect, dpi=DPI, alpha=False, colorspace=pymupdf.csRGB)
    return pix


def measure_ink(page, rect: pymupdf.Rect, base: float | None = None, size: float | None = None) -> Ink | None:
    """Tinta dentro de rect: caja, color de fondo y de la letra.
    Con base/size se queda solo con la franja de tinta de esa línea (sin la de las vecinas)."""
    r = pymupdf.Rect(rect) & page.rect
    if r.is_empty or r.width < 0.5 or r.height < 0.5:
        return None
    pix = _gray_pix(page, r)
    w, h, n = pix.width, pix.height, pix.n
    data = pix.samples
    if w < 2 or h < 2:
        return None
    lum = [0] * (w * h)
    for i in range(w * h):
        o = i * n
        lum[i] = (data[o] * 299 + data[o + 1] * 587 + data[o + 2] * 114) // 1000
    border = [lum[x] for x in range(w)] + [lum[(h - 1) * w + x] for x in range(w)] + \
             [lum[y * w] for y in range(h)] + [lum[y * w + w - 1] for y in range(h)]
    border.sort()
    bg_l = border[int(len(border) * 0.75)]
    srt = sorted(lum)
    fg_l = srt[max(0, int(len(srt) * 0.03))]
    if bg_l - fg_l < 40:
        return None
    thr = bg_l - (bg_l - fg_l) * 0.45
    k = 72.0 / DPI
    rows = [sum(1 for x in range(w) if lum[y * w + x] < thr) for y in range(h)]
    y_lo, y_hi = 0, h - 1
    if base is not None and size:
        # franja de tinta de esta línea: filas con tinta alrededor de la mitad de la letra
        target = int((base - size * 0.3 - r.y0) / k)
        target = max(0, min(h - 1, target))
        if not rows[target]:
            cand = [y for y in range(h) if rows[y]]
            if not cand:
                return None
            target = min(cand, key=lambda y: abs(y - target))
        maxgap = max(1, int(size * 0.14 / k))
        y_lo = y_hi = target
        gap = 0
        y = target
        while y > 0:
            y -= 1
            if rows[y]:
                y_lo, gap = y, 0
            else:
                gap += 1
                if gap > maxgap:
                    break
        gap = 0
        y = target
        while y < h - 1:
            y += 1
            if rows[y]:
                y_hi, gap = y, 0
            else:
                gap += 1
                if gap > maxgap:
                    break
    xs, ys = [], []
    dark_rgb, bg_rgb = [], []
    for y in range(h):
        for x in range(w):
            v = lum[y * w + x]
            o = (y * w + x) * n
            if v < thr:
                if y_lo <= y <= y_hi:
                    xs.append(x)
                    ys.append(y)
                    if v <= fg_l + (bg_l - fg_l) * 0.25:
                        dark_rgb.append(data[o:o + 3])
            elif v >= bg_l - 6:
                bg_rgb.append(data[o:o + 3])
    if not xs:
        return None
    ink = pymupdf.Rect(r.x0 + min(xs) * k, r.y0 + min(ys) * k, r.x0 + (max(xs) + 1) * k, r.y0 + (max(ys) + 1) * k)

    def med(lst, default):
        if not lst:
            return default
        return tuple(sorted(c[i] for c in lst)[len(lst) // 2] / 255 for i in range(3))
    return Ink(ink, med(bg_rgb, (1, 1, 1)), med(dark_rgb, (0, 0, 0)))


def word_ink(page, glyphs) -> Ink | None:
    """Tinta de una palabra del OCR (ventana alrededor de su línea base, ampliable a los lados)."""
    vis = [g for g in glyphs if not g.c.isspace()]
    if not vis:
        return None
    size = max(g.st.size for g in vis)
    base = sorted(g.y for g in vis)[len(vis) // 2]
    x0 = min(g.bbox.x0 for g in vis)
    x1 = max(g.bbox.x1 for g in vis)
    pad_l = pad_r = 1.5
    ink = None
    for _ in range(3):
        win = pymupdf.Rect(x0 - pad_l, base - size * 1.05, x1 + pad_r, base + size * 0.4)
        ink = measure_ink(page, win, base, size)
        if ink is None:
            return None
        grow = False
        if ink.rect.x0 <= win.x0 + 0.4:
            pad_l += 2.5
            grow = True
        if ink.rect.x1 >= win.x1 - 0.4:
            pad_r += 2.5
            grow = True
        if not grow:
            break
    return ink


def _ref_ink(font: pymupdf.Font, text: str, size: float):
    """Caja de la tinta de un texto escrito con font a size, con la línea base en y=0."""
    d = pymupdf.open()
    w = font.text_length(text, fontsize=size) + size * 2
    p = d.new_page(width=w, height=size * 3)
    tw = pymupdf.TextWriter(p.rect)
    tw.append((size, size * 2), text, font=font, fontsize=size)
    tw.write_text(p)
    pix = p.get_pixmap(dpi=DPI, colorspace=pymupdf.csGRAY, alpha=False)
    W, H = pix.width, pix.height
    s = pix.samples
    xs, ys = [], []
    for y in range(H):
        row = s[y * W:(y + 1) * W]
        for x in range(W):
            if row[x] < 128:
                xs.append(x)
                ys.append(y)
    d.close()
    if not xs:
        return None
    k = 72.0 / DPI
    return pymupdf.Rect(min(xs) * k - size, min(ys) * k - size * 2, (max(xs) + 1) * k - size, (max(ys) + 1) * k - size * 2)


@dataclass
class Look:
    font: pymupdf.Font
    font_label: str
    size: float
    hscale: float
    baseline: float
    x0: float
    color: tuple
    bg: tuple


def _candidate_fonts(bold: bool, italic: bool):
    from . import fonts
    out = []
    for fam, kind, b14 in (("couriernew", "mono", "cour"), ("arial", "sans", "helv"), ("timesnewroman", "serif", "tiro")):
        h = fonts._system_file(fam, bold, italic)
        if h:
            out.append((h[1], pymupdf.Font(fontfile=h[0])))
        else:
            name = fonts.BASE14[(kind, bold, italic)]
            out.append(({"cour": "Courier", "helv": "Helvetica", "tiro": "Times"}[b14], pymupdf.Font(name)))
    return out


def match_look(page, glyphs, bold: bool, italic: bool, size_hint: float) -> Look | None:
    """Fuente, tamaño, escala y posición que imitan la palabra escaneada (glifos del OCR)."""
    text = "".join(g.c for g in glyphs).strip()
    ink = word_ink(page, glyphs)
    if ink is None or not text:
        return None
    best = None
    for label, font in _candidate_fonts(bold, italic):
        s0 = max(4.0, size_hint or 10.0)
        ref = _ref_ink(font, text, s0)
        if ref is None or ref.height <= 0 or ref.width <= 0:
            continue
        size = s0 * ink.rect.height / ref.height
        if not 3 <= size <= 72:
            continue
        hs = (ink.rect.width / ref.width) * (s0 / size)
        k = size / s0
        baseline = ink.rect.y1 - ref.y1 * k
        x0 = ink.rect.x0 - ref.x0 * k * hs
        score = abs(1 - hs)
        if best is None or score < best[0]:
            best = (score, Look(font, label, size, max(0.6, min(1.6, hs)), baseline, x0, ink.fg, ink.bg))
    return best[1] if best else None


# ---------------------------------------------------------------- edición
def _word_rect(glyphs) -> pymupdf.Rect:
    r = pymupdf.Rect()
    for g in glyphs:
        if not g.c.isspace():
            r |= g.bbox
    return r


def _union_ink(page, words):
    """Tinta de varias palabras (unión de la de cada una)."""
    out = None
    for w in words:
        ink = word_ink(page, [it.g for it in w])
        if ink is None:
            continue
        if out is None:
            out = Ink(pymupdf.Rect(ink.rect), ink.bg, ink.fg)
        else:
            out.rect |= ink.rect
    return out


def edit_scanned(page, block, new_text: str) -> te.Result:
    ed = te.Editor(page, block, new_text)
    if ed.new == ed.old:
        return te.Result("none")
    per = ed._line_items()
    if per is None:
        raise te.Unsupported("En un documento escaneado solo se pueden cambiar palabras dentro de cada línea "
                             "(sin añadir ni quitar líneas).")
    jobs = []                      # (glifos a quitar, rect a tapar, texto, look, x, baseline, hscale)
    right_limit = max(li.end for li in ed.infos)
    for li, items in zip(ed.infos, per):
        if len(items) == len(li.glyphs) and all(it.g is g for it, g in zip(items, li.glyphs)):
            continue
        old_words = te._words([te.Item(g.c, g.st, g=g) for g in li.glyphs])
        new_words = te._words(items)
        same = lambda a, b: len(a) == len(b) and all(x.g is not None and x.g is y.g for x, y in zip(a, b))
        a = 0
        while a < min(len(old_words), len(new_words)) and same(new_words[a], old_words[a]):
            a += 1
        c = 0
        while (c < min(len(old_words), len(new_words)) - a and
               same(new_words[len(new_words) - 1 - c], old_words[len(old_words) - 1 - c])):
            c += 1
        old_chg = old_words[a:len(old_words) - c]
        new_chg = new_words[a:len(new_words) - c]
        old_g = [it.g for w in old_chg for it in w]
        new_str = " ".join("".join(it.c for it in w) for w in new_chg)
        # palabra de referencia para imitar el aspecto
        ref_words = old_chg or old_words[max(0, a - 1):a] or old_words[a:a + 1]
        ref_w = max(ref_words, key=lambda w: len(w))
        ref_glyphs = [it.g for it in ref_w]
        st = ref_glyphs[0].st
        look = match_look(page, ref_glyphs, st.bold, st.italic, st.size)
        if look is None:
            raise te.Unsupported("No se ha podido medir la letra escaneada de esta línea.")
        # hueco disponible
        if old_chg:
            ink0 = _union_ink(page, old_chg)
            x_start = ink0.rect.x0 if ink0 else _word_rect(old_g).x0
            cover = ink0.rect if ink0 else _word_rect(old_g)
            if ref_w is old_chg[0] or ref_w in old_chg:
                if ref_w is old_chg[0]:
                    x_start = look.x0
        else:
            prev = old_words[a - 1] if a > 0 else None
            if prev is not None:
                pr = word_ink(page, [it.g for it in prev])
                px1 = pr.rect.x1 if pr else _word_rect([it.g for it in prev]).x1
                x_start = px1 + look.font.text_length(" ", fontsize=look.size) * look.hscale
                new_str = new_str
            else:
                x_start = li.start
            cover = None
        nxt = old_words[len(old_words) - c] if c > 0 else None
        if nxt is not None:
            nr = word_ink(page, [it.g for it in nxt])
            nx0 = nr.rect.x0 if nr else _word_rect([it.g for it in nxt]).x0
            gap = look.font.text_length(" ", fontsize=look.size) * look.hscale
            limit = nx0 - gap
        else:
            limit = max(right_limit, page.rect.x1 - 36)
        width = look.font.text_length(new_str, fontsize=look.size) * look.hscale
        hscale = look.hscale
        if new_str and x_start + width > limit + 0.3:
            avail = limit - x_start
            if avail > 0 and width * MIN_SCALE <= avail and nxt is not None and avail / width >= 0.85:
                hscale = look.hscale * avail / width
            elif nxt is not None:
                # reescribir también el resto de la línea
                tail = old_words[len(old_words) - c:]
                old_g += [it.g for w in tail for it in w]
                new_str = (new_str + " " if new_str else "") + " ".join("".join(it.c for it in w) for w in tail)
                tr = _union_ink(page, tail)
                cover = (cover | tr.rect) if (cover is not None and tr) else (tr.rect if tr else cover)
                limit = max(right_limit, page.rect.x1 - 36)
                width = look.font.text_length(new_str, fontsize=look.size) * look.hscale
                if x_start + width > limit + 0.3:
                    avail = limit - x_start
                    if avail <= 0 or width * MIN_SCALE > avail:
                        raise te.NoSpace(0, None)
                    hscale = look.hscale * avail / width
            else:
                avail = limit - x_start
                if avail <= 0 or width * MIN_SCALE > avail:
                    raise te.NoSpace(0, None)
                hscale = look.hscale * avail / width
        jobs.append((old_g, cover, new_str, look, x_start, look.baseline, hscale))
    if not jobs:
        return te.Result("none")

    # aplicar: 1) quitar la capa invisible de lo sustituido
    remove = [g for job in jobs for g in job[0] if g.real]
    before = ed._all_chars()
    for g in remove:
        r = g.bbox
        w, h = r.width, r.height
        rr = pymupdf.Rect(r.x0 + w * 0.3, r.y0 + h * 0.42, r.x1 - w * 0.3, r.y1 - h * 0.42) if w >= 0.6 else \
            pymupdf.Rect(r.x0 + w / 2 - 0.05, r.y0 + h * 0.45, r.x0 + w / 2 + 0.05, r.y1 - h * 0.45)
        page.add_redact_annot(rr, fill=False)
    if remove:
        page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                              graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                              text=pymupdf.PDF_REDACT_TEXT_REMOVE)
    after = ed._all_chars()
    lost = te._lost(before, after)
    want = [(g.x, g.y, g.c) for g in remove]
    pool = list(want)
    extra = []
    for ch in lost:
        k = next((n for n, w in enumerate(pool) if w[2] == ch[2] and abs(w[0] - ch[0]) < 0.3 and abs(w[1] - ch[1]) < 0.3), None)
        if k is None:
            extra.append(ch)
        else:
            pool.pop(k)
    if pool:
        raise te.EditError(f"No se han podido borrar {len(pool)} carácter(es) de la capa de texto.")
    if extra:   # reponer (invisibles, como estaban) lo que MuPDF haya quitado de más
        fc = te.FontCache(page)
        groups = {}
        for ch in extra:
            st = ch[3]
            f = fc.font(st)
            key = id(f)
            tw = groups.setdefault(key, (pymupdf.TextWriter(page.rect), st))[0]
            tw.append((ch[0], ch[1]), ch[2], font=f, fontsize=st.size)
        for tw, st in groups.values():
            tw.write_text(page, render_mode=3)
    # 2) tapar y escribir
    for old_g, cover, new_str, look, x, base, hscale in jobs:
        if cover is not None:
            pad = 0.9
            page.draw_rect(cover + (-pad, -pad, pad, pad), color=None, fill=look.bg, width=0, overlay=True)
        if new_str:
            tw = pymupdf.TextWriter(page.rect)
            tw.append((x, base), new_str, font=look.font, fontsize=look.size)
            morph = (pymupdf.Point(x, base), pymupdf.Matrix(hscale, 1)) if abs(hscale - 1) > 0.01 else None
            tw.write_text(page, color=look.color, morph=morph)
    labels = sorted({j[3].font_label for j in jobs})
    log.info("Edición sobre escaneado: %d cambio(s), fuente %s", len(jobs), ", ".join(labels))
    return te.Result("scan", [f"Documento escaneado: se ha tapado el texto antiguo y escrito el nuevo con {', '.join(labels)}"],
                     len(jobs))
