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

"""Reconocimiento óptico de caracteres (OCR).

Usa el motor Tesseract integrado en MuPDF; solo necesita los ficheros de
idioma (*.traineddata) que se distribuyen en la carpeta «tessdata».
El texto reconocido se añade como capa invisible sobre la imagen original,
de modo que el aspecto del documento no cambia pero se puede buscar,
seleccionar y copiar.
"""
from __future__ import annotations

import os

import pymupdf

LANGUAGES = [("spa", "Español"), ("eng", "Inglés"), ("spa+eng", "Español + Inglés")]


def tessdata_dir() -> str | None:
    from ..paths import resource_dir
    cand = os.path.join(resource_dir(), "tessdata")
    if os.path.isfile(os.path.join(cand, "spa.traineddata")):
        return cand
    try:
        return pymupdf.get_tessdata()
    except Exception:
        return None


def page_needs_ocr(page: pymupdf.Page) -> bool:
    return len(page.get_text("text").strip()) < 20


def ocr_page(page: pymupdf.Page, language: str = "spa", dpi: int = 300, tessdata: str | None = None) -> int:
    """Añade capa de texto invisible a la página. Devuelve nº de palabras reconocidas."""
    tessdata = tessdata or tessdata_dir()
    # Se reconoce la página tal como se ve (con su rotación), en un documento temporal
    pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
    tmp = pymupdf.open()
    tpage = tmp.new_page(width=page.rect.width, height=page.rect.height)
    tpage.insert_image(tpage.rect, pixmap=pix)
    pix = None
    tp = tpage.get_textpage_ocr(flags=0, language=language, dpi=dpi, full=True, tessdata=tessdata)
    data = tpage.get_text("dict", textpage=tp)
    tmp.close()
    words = 0
    shape = page.new_shape()
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span.get("text", "")
                if not text.strip():
                    continue
                bbox = pymupdf.Rect(span["bbox"])
                if bbox.is_empty:
                    continue
                fs = max(bbox.height * 0.85, 2)
                natural = pymupdf.get_text_length(text, fontname="helv", fontsize=fs)
                if natural <= 0:
                    continue
                # punto de inicio (línea base)
                origin = pymupdf.Point(bbox.x0, bbox.y1 - bbox.height * 0.2)
                sx = bbox.width / natural
                # render_mode=3 -> texto invisible; escalado horizontal al ancho real
                shape.insert_text(origin, text, fontsize=fs, fontname="helv", render_mode=3,
                                  morph=(origin, pymupdf.Matrix(sx, 1)))
                words += len(text.split())
    shape.commit()
    return words


def ocr_document_bytes(data: bytes, pages: list[int], language: str, dpi: int = 300,
                       progress=None, cancelled=None, only_needed: bool = True) -> tuple[bytes, int]:
    """Procesa una copia del documento (para ejecutarse en segundo plano).
    Devuelve (bytes del PDF, nº de palabras)."""
    doc = pymupdf.open(stream=data, filetype="pdf")
    tess = tessdata_dir()
    total = 0
    for k, i in enumerate(pages):
        if cancelled and cancelled():
            break
        page = doc[i]
        if progress:
            progress(k, len(pages), i)
        if only_needed and not page_needs_ocr(page):
            continue
        total += ocr_page(page, language=language, dpi=dpi, tessdata=tess)
    if progress:
        progress(len(pages), len(pages), -1)
    out = doc.tobytes(garbage=3, deflate=True)
    doc.close()
    return out, total
