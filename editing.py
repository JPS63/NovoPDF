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

"""Edición del contenido de las páginas: texto e imágenes."""
from __future__ import annotations

from dataclasses import dataclass, field

import pymupdf

# Fuentes estándar PDF (incluyen los caracteres del español: áéíóúñü¿¡€)
_FONTS = {
    ("sans", False, False): "helv", ("sans", True, False): "hebo",
    ("sans", False, True): "heit", ("sans", True, True): "hebi",
    ("serif", False, False): "tiro", ("serif", True, False): "tibo",
    ("serif", False, True): "tiit", ("serif", True, True): "tibi",
    ("mono", False, False): "cour", ("mono", True, False): "cobo",
    ("mono", False, True): "coit", ("mono", True, True): "cobi",
}

FAMILIES = [("sans", "Arial / Helvetica"), ("serif", "Times"), ("mono", "Courier")]


def base14(family: str, bold: bool, italic: bool) -> str:
    return _FONTS.get((family, bool(bold), bool(italic)), "helv")


def int_to_rgb(c: int) -> tuple[float, float, float]:
    return (((c >> 16) & 255) / 255, ((c >> 8) & 255) / 255, (c & 255) / 255)


@dataclass
class TextBlock:
    bbox: pymupdf.Rect
    line_rects: list
    text: str
    fontsize: float
    color: tuple
    family: str
    bold: bool
    italic: bool
    lineheight: float
    font_name: str = ""
    raw_lines: list = field(default_factory=list)   # líneas de «rawdict» (para editar sin rehacer el párrafo)


def _guess_family(font: str, flags: int) -> str:
    f = font.lower()
    if flags & 8 or any(k in f for k in ("courier", "mono", "consol")):
        return "mono"
    if flags & 4 or any(k in f for k in ("times", "serif", "roman", "georgia", "garamond", "cambria", "book")):
        if "sans" not in f:
            return "serif"
    return "sans"


def _line_base(ln) -> float:
    for s in ln["spans"]:
        for c in s.get("chars", []):
            return c["origin"][1]
    return ln["bbox"][3]


def _line_text(ln) -> str:
    return "".join(c["c"] for s in ln["spans"] for c in s.get("chars", []))


def _bulletish(ln) -> bool:
    t = _line_text(ln).strip()
    return 0 < len(t) <= 2 and not any(ch.isalnum() for ch in t)


def _join_lines(a, b):
    """Une dos trozos de un mismo renglón; si entre ellos hay hueco y ningún espacio,
    se añade un espacio deducido (como hace MuPDF dentro de una línea)."""
    key = lambda s: (s["chars"][0]["origin"][0] if s.get("chars") else s["bbox"][0])
    spans = sorted(a["spans"] + b["spans"], key=key)
    out = []
    for s in spans:
        if out and s.get("chars") and out[-1].get("chars"):
            last = out[-1]["chars"][-1]
            first = s["chars"][0]
            gap = first["bbox"][0] - last["bbox"][2]
            if gap > 0.2 * s["size"] and not last["c"].isspace() and not first["c"].isspace():
                y0, y1 = last["bbox"][1], last["bbox"][3]
                sp = {"c": " ", "origin": (last["bbox"][2], last["origin"][1]),
                      "bbox": (last["bbox"][2], y0, first["bbox"][0], y1)}
                out.append(dict(out[-1], chars=[sp], bbox=sp["bbox"]))
        out.append(s)
    r = pymupdf.Rect(a["bbox"]) | pymupdf.Rect(b["bbox"])
    return dict(a, spans=out, bbox=tuple(r))


def merged_text_blocks(page: pymupdf.Page) -> list[dict]:
    """Bloques de «rawdict» con el texto añadido al editar reunido en su párrafo.

    El texto que se escribe al editar va al final del contenido de la página y MuPDF lo
    devuelve como un bloque aparte; aquí se vuelve a unir con su párrafo (mismo renglón y
    dentro de su anchura) para que el párrafo se pueda volver a editar entero."""
    raw = page.get_text("rawdict", flags=pymupdf.TEXTFLAGS_TEXT)
    blocks = [dict(b, lines=[dict(ln) for ln in b["lines"]]) for b in raw.get("blocks", [])
              if b.get("type") == 0 and b.get("lines")]
    horiz = lambda ln: abs(ln.get("dir", (1, 0))[0] - 1) < 1e-3

    def fits(small, big):
        """small es parte del mismo párrafo que big: comparte renglón con él (pegado o dentro
        de su anchura) y el resto de sus líneas siguen dentro de la columna de big."""
        bb, sb = pymupdf.Rect(big["bbox"]), pymupdf.Rect(small["bbox"])
        blines = [ln for ln in big["lines"] if horiz(ln)]
        if not blines or not all(horiz(ln) for ln in small["lines"]):
            return False
        col = min(bb.x1, sb.x1) - max(bb.x0, sb.x0)
        if col < 0.5 * min(bb.width, sb.width) and not (sb.x0 >= bb.x0 - 2 and sb.x1 <= bb.x1 + 2):
            shared_needed = True
        else:
            shared_needed = False
        shared = False
        for ln in small["lines"]:
            y = _line_base(ln)
            lr = pymupdf.Rect(ln["bbox"])
            size = max((s["size"] for s in ln["spans"]), default=10)
            same = [b0 for b0 in blines if abs(_line_base(b0) - y) < 0.8]
            for b0 in same:
                r0 = pymupdf.Rect(b0["bbox"])
                if (lr.x0 - r0.x1 < 0.8 * size and r0.x0 - lr.x1 < 0.8 * size) or (
                        lr.x0 >= bb.x0 - 2 and lr.x1 <= bb.x1 + 2):
                    shared = True
        if not shared:
            return False
        if shared_needed:
            # bloques en columnas distintas que solo coinciden en un renglón: no
            return len(small["lines"]) == 1
        return True

    changed = True
    while changed:
        changed = False
        for i, big in enumerate(blocks):
            for j, small in enumerate(blocks):
                if i == j or not small["lines"] or not big["lines"]:
                    continue
                if fits(small, big):
                    big["lines"] = big["lines"] + small["lines"]
                    big["bbox"] = tuple(pymupdf.Rect(big["bbox"]) | pymupdf.Rect(small["bbox"]))
                    small["lines"] = []
                    changed = True
        blocks = [b for b in blocks if b["lines"]]
    # dentro de cada bloque, unir los trozos de un mismo renglón (salvo viñetas)
    for b in blocks:
        lines = sorted(b["lines"], key=lambda ln: (round(_line_base(ln), 1), ln["bbox"][0]))
        out = []
        for ln in lines:
            if out and horiz(ln) and horiz(out[-1]) and abs(_line_base(ln) - _line_base(out[-1])) < 0.8 \
                    and not _bulletish(ln) and not _bulletish(out[-1]):
                out[-1] = _join_lines(out[-1], ln)
            else:
                out.append(ln)
        b["lines"] = out
    blocks.sort(key=lambda b: (b["bbox"][1], b["bbox"][0]))
    return blocks


def text_blocks(page: pymupdf.Page) -> list[TextBlock]:
    """Párrafos de la página. El estilo de referencia es el predominante (por número de
    caracteres), no el del primer carácter: en una lista el primero es la viñeta."""
    out = []
    for b in merged_text_blocks(page):
        lines, rects, raw_lines = [], [], []
        weight = {}
        for ln in b.get("lines", []):
            txt = "".join(c["c"] for s in ln["spans"] for c in s.get("chars", []))
            if not txt.strip():
                continue
            lines.append(txt.rstrip())
            rects.append(pymupdf.Rect(ln["bbox"]))
            raw_lines.append(ln)
            for s in ln["spans"]:
                n = sum(1 for c in s.get("chars", []) if not c["c"].isspace())
                if not n:
                    continue
                k = (s.get("font", ""), round(s["size"], 1), s.get("flags", 0), s.get("color", 0))
                weight[k] = weight.get(k, 0) + n
        if not lines or not weight:
            continue
        fontname, fs, flags, color = max(weight, key=weight.get)
        bold = bool(flags & 16) or "bold" in fontname.lower()
        italic = bool(flags & 2) or "italic" in fontname.lower() or "oblique" in fontname.lower()
        if len(rects) > 1:
            ys = sorted({round(r.y0, 1) for r in rects})
            gaps = [ys[i + 1] - ys[i] for i in range(len(ys) - 1)]
            gaps = [g for g in gaps if g > 0]
            lh = (sum(gaps) / len(gaps) / fs) if gaps else 1.2
            lh = min(max(lh, 1.0), 2.5)
        else:
            lh = 1.2
        out.append(TextBlock(
            bbox=pymupdf.Rect(b["bbox"]), line_rects=rects, text="\n".join(lines),
            fontsize=float(fs), color=int_to_rgb(color),
            family=_guess_family(fontname, flags), bold=bold, italic=italic, lineheight=lh,
            font_name=fontname, raw_lines=raw_lines))
    return out


def _remove_text(page: pymupdf.Page, rects: list):
    for r in rects:
        # Se reduce la altura para no tocar líneas vecinas
        h = r.height
        rr = pymupdf.Rect(r.x0, r.y0 + h * 0.25, r.x1, r.y1 - h * 0.25)
        page.add_redact_annot(rr, fill=False)
    page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                          graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                          text=pymupdf.PDF_REDACT_TEXT_REMOVE)


def _fit_textbox(page, rect, text, fontsize, font: pymupdf.Font, color, align, lineheight):
    """Inserta texto en un rectángulo; si no cabe, lo amplía hacia abajo y
    después reduce el tamaño de letra. Devuelve el tamaño usado."""
    page_bottom = page.rect.y1 - 10
    page_right = page.rect.x1 - 10
    trial_rects = [rect,
                   pymupdf.Rect(rect.x0, rect.y0, rect.x1, page_bottom),
                   pymupdf.Rect(rect.x0, rect.y0, max(rect.x1, page_right), page_bottom)]

    def attempt(r, fs):
        tw = pymupdf.TextWriter(page.rect, color=color)
        rest = tw.fill_textbox(r, text, font=font, fontsize=fs, lineheight=lineheight, align=align)
        if rest:
            return False
        tw.write_text(page, color=color)
        return True

    for r in trial_rects:
        if attempt(r, fontsize):
            return fontsize
    fs = fontsize
    while fs > 4:
        fs -= 0.5
        if attempt(trial_rects[1], fs):
            return fs
    raise ValueError("El texto es demasiado largo para caber en la página.")


def _as_font(font_or_choice) -> pymupdf.Font:
    if isinstance(font_or_choice, pymupdf.Font):
        return font_or_choice
    if isinstance(font_or_choice, str):          # nombre base14 («helv», «tiro»...)
        return pymupdf.Font(font_or_choice)
    return font_or_choice.font()                 # FontChoice


def _insert_image(page, rect, **kw):
    """Inserta una imagen usando coordenadas visibles (respeta la rotación de página)."""
    page.insert_image(rect * page.derotation_matrix, rotate=page.rotation, **kw)


def replace_block(page: pymupdf.Page, block: TextBlock, new_text: str, fontsize: float,
                  color: tuple, font, align: int = 0):
    """Sustituye el texto de un bloque (párrafo) por otro.
    font: FontChoice, pymupdf.Font o nombre de fuente estándar."""
    f = _as_font(font)
    _remove_text(page, block.line_rects)
    if not new_text.strip():
        return
    rect = pymupdf.Rect(block.bbox)
    rect.x1 += 2   # pequeño margen para evitar cortes por redondeo
    rect.y0 -= 1
    _fit_textbox(page, rect, new_text, fontsize, f, color, align, block.lineheight)


def add_text(page: pymupdf.Page, point: pymupdf.Point, text: str, fontsize: float,
             color: tuple, font):
    f = _as_font(font)
    lines = text.split("\n")
    width = max(f.text_length(ln, fontsize=fontsize) for ln in lines)
    rect = pymupdf.Rect(point.x, point.y, point.x + width + fontsize, point.y + fontsize * 1.3 * len(lines) + 4)
    if rect.x1 > page.rect.x1 - 5:
        rect.x1 = page.rect.x1 - 5
    _fit_textbox(page, rect, text, fontsize, f, color, 0, 1.2)


# ---------------------------------------------------------------- imágenes
@dataclass
class ImageItem:
    xref: int
    bbox: pymupdf.Rect
    width: int
    height: int


def page_images(page: pymupdf.Page) -> list[ImageItem]:
    out = []
    page._image_info = None   # PyMuPDF guarda en caché esta información; forzar lectura nueva
    for info in page.get_image_info(xrefs=True):
        # get_image_info devuelve coordenadas sin rotar -> pasarlas a las visibles
        r = pymupdf.Rect(info["bbox"]) * page.rotation_matrix
        if r.is_empty or r.is_infinite:
            continue
        if info.get("width", 0) <= 1 and info.get("height", 0) <= 1:
            continue   # marcador transparente que deja una imagen eliminada
        out.append(ImageItem(info.get("xref", 0), r & page.rect, info.get("width", 0), info.get("height", 0)))
    # las más pequeñas primero para que se puedan seleccionar las que están encima
    out.sort(key=lambda i: i.bbox.width * i.bbox.height)
    return out


def _xref_usage(doc: pymupdf.Document, xref: int) -> int:
    n = 0
    for p in doc:
        n += sum(1 for im in p.get_images(full=True) if im[0] == xref)
    return n


def _remove_image(page: pymupdf.Page, item: ImageItem):
    doc = page.parent
    if item.xref and _xref_usage(doc, item.xref) <= 1:
        page.delete_image(item.xref)
    else:
        # La imagen se usa en otras páginas o es interna: se elimina solo de esta zona
        r = item.bbox
        page.add_redact_annot(r, fill=False)
        page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_REMOVE,
                              graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                              text=pymupdf.PDF_REDACT_TEXT_NONE)


def _image_source(doc: pymupdf.Document, xref: int) -> dict:
    """Devuelve kwargs para insert_image conservando la transparencia."""
    info = doc.extract_image(xref)
    smask = info.get("smask", 0)
    if not smask and info.get("ext") in ("jpeg", "jpg", "png"):
        return {"stream": info["image"]}
    pix = pymupdf.Pixmap(doc, xref)
    if smask:
        mask = pymupdf.Pixmap(doc, smask)
        try:
            pix = pymupdf.Pixmap(pix, mask)
        except Exception:
            pass
    if pix.colorspace and pix.colorspace.n > 3:
        pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
    return {"pixmap": pix}


def delete_image(page: pymupdf.Page, item: ImageItem):
    _remove_image(page, item)


def move_image(page: pymupdf.Page, item: ImageItem, new_rect: pymupdf.Rect):
    if not item.xref:
        raise ValueError("Esta imagen no se puede mover (imagen incrustada en el contenido).")
    src = _image_source(page.parent, item.xref)
    _remove_image(page, item)
    _insert_image(page, new_rect, keep_proportion=False, **src)


def replace_image(page: pymupdf.Page, item: ImageItem, filename: str):
    _remove_image(page, item)
    _insert_image(page, item.bbox, filename=filename, keep_proportion=True)


def add_image(page: pymupdf.Page, rect: pymupdf.Rect, filename: str):
    if rect.width < 20 or rect.height < 20:
        pix = pymupdf.Pixmap(filename)
        w, h = pix.width, pix.height
        scale = min(200 / w, 200 / h, 1.0) if w and h else 1
        rect = pymupdf.Rect(rect.x0, rect.y0, rect.x0 + w * scale * 0.75, rect.y0 + h * scale * 0.75)
    _insert_image(page, rect, filename=filename, keep_proportion=True)


def erase_area(page: pymupdf.Page, rect: pymupdf.Rect):
    """Borra todo lo que hay en una zona (texto, imágenes y dibujos) y la deja en blanco."""
    page.add_redact_annot(rect, fill=(1, 1, 1))
    page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_PIXELS,
                          graphics=pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED,
                          text=pymupdf.PDF_REDACT_TEXT_REMOVE)
