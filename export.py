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

"""Exportación de páginas a formatos de imagen."""
from __future__ import annotations

import os
import re

import pymupdf

# (extensión, nombre, descripción)
FORMATS = [
    ("png", "PNG", "Sin pérdida de calidad. Recomendado para documentos con texto."),
    ("jpg", "JPEG", "Archivos pequeños. Ideal para fotografías y para enviar por correo."),
    ("tif", "TIFF", "Formato habitual en archivo y digitalización. Admite varias páginas en un archivo."),
    ("bmp", "BMP", "Mapa de bits de Windows sin comprimir (archivos grandes)."),
    ("gif", "GIF", "Máximo 256 colores. Útil para web o gráficos sencillos."),
    ("webp", "WebP", "Formato moderno para web, archivos muy pequeños."),
    ("svg", "SVG", "Vectorial: se puede ampliar sin perder calidad (no usa resolución)."),
]
COLOR_MODES = [("color", "Color"), ("gray", "Escala de grises"), ("bw", "Blanco y negro")]


def parse_range(text: str, page_count: int) -> list[int]:
    """'1-3, 5, 8-' -> [0, 1, 2, 4, 7, 8, ...] (índices desde 0)."""
    pages: list[int] = []
    for part in re.split(r"[,;\s]+", text.strip()):
        if not part:
            continue
        m = re.fullmatch(r"(\d*)\s*-\s*(\d*)", part)
        if m:
            a = int(m.group(1)) if m.group(1) else 1
            b = int(m.group(2)) if m.group(2) else page_count
        elif part.isdigit():
            a = b = int(part)
        else:
            raise ValueError(f"No se entiende «{part}». Usa por ejemplo: 1-3, 5, 8")
        if a < 1 or b > page_count or a > b:
            raise ValueError(f"El intervalo «{part}» no es válido (el documento tiene {page_count} páginas).")
        for p in range(a - 1, b):
            if p not in pages:
                pages.append(p)
    if not pages:
        raise ValueError("Indica al menos una página.")
    return pages


def planned_files(folder: str, base: str, fmt: str, pages: list[int], page_count: int,
                  multipage_tiff: bool) -> list[str]:
    if fmt == "tif" and multipage_tiff:
        return [os.path.join(folder, f"{base}.tif")]
    width = max(2, len(str(page_count)))
    return [os.path.join(folder, f"{base}_p{str(p + 1).zfill(width)}.{fmt}") for p in pages]


def _to_pil(page: pymupdf.Page, dpi: int, mode: str):
    from PIL import Image
    cs = pymupdf.csGRAY if mode in ("gray", "bw") else pymupdf.csRGB
    pix = page.get_pixmap(dpi=dpi, colorspace=cs, alpha=False)
    img = Image.frombytes("L" if cs is pymupdf.csGRAY else "RGB", (pix.width, pix.height), pix.samples)
    if mode == "bw":
        img = img.point(lambda v: 255 if v > 165 else 0).convert("1", dither=Image.Dither.NONE)
    return img


def export_pages(data: bytes, pages: list[int], folder: str, base: str, fmt: str, dpi: int = 300,
                 mode: str = "color", quality: int = 90, multipage_tiff: bool = False,
                 progress=None, cancelled=None, password: str | None = None) -> list[str]:
    """Exporta las páginas indicadas. Se ejecuta sobre una copia (bytes) del documento."""
    from PIL import Image
    doc = pymupdf.open(stream=data, filetype="pdf")
    if doc.needs_pass:
        doc.authenticate(password or "")
    os.makedirs(folder, exist_ok=True)
    files = planned_files(folder, base, fmt, pages, doc.page_count, multipage_tiff)
    written: list[str] = []
    tiff_comp = {"color": "tiff_lzw", "gray": "tiff_lzw", "bw": "group4"}[mode]
    try:
        if fmt == "tif" and multipage_tiff:
            path = files[0]

            def rest():
                for k, p in enumerate(pages[1:], start=1):
                    if cancelled and cancelled():
                        return
                    if progress:
                        progress(k, len(pages))
                    yield _to_pil(doc[p], dpi, mode)

            if progress:
                progress(0, len(pages))
            first = _to_pil(doc[pages[0]], dpi, mode)
            first.save(path, format="TIFF", save_all=True, append_images=rest(),
                       compression=tiff_comp, dpi=(dpi, dpi))
            written.append(path)
        else:
            for k, (p, path) in enumerate(zip(pages, files)):
                if cancelled and cancelled():
                    break
                if progress:
                    progress(k, len(pages))
                page = doc[p]
                if fmt == "svg":
                    with open(path, "w", encoding="utf-8") as fh:
                        fh.write(page.get_svg_image(text_as_path=True))
                    written.append(path)
                    continue
                img = _to_pil(page, dpi, mode)
                kw = {}
                if fmt == "jpg":
                    if img.mode == "1":
                        img = img.convert("L")
                    kw = dict(format="JPEG", quality=int(quality), optimize=True, dpi=(dpi, dpi))
                elif fmt == "png":
                    kw = dict(format="PNG", optimize=False, dpi=(dpi, dpi))
                elif fmt == "tif":
                    kw = dict(format="TIFF", compression=tiff_comp, dpi=(dpi, dpi))
                elif fmt == "bmp":
                    kw = dict(format="BMP", dpi=(dpi, dpi))
                elif fmt == "gif":
                    if img.mode == "RGB":
                        img = img.convert("P", palette=Image.Palette.ADAPTIVE, colors=256)
                    kw = dict(format="GIF")
                elif fmt == "webp":
                    if img.mode == "1":
                        img = img.convert("L")
                    kw = dict(format="WEBP", quality=int(quality), method=4)
                img.save(path, **kw)
                written.append(path)
        if progress:
            progress(len(pages), len(pages))
    finally:
        doc.close()
    return written
