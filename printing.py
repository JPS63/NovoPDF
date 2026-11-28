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

"""Impresión de documentos.

Las páginas se dibujan con PyMuPDF (con las anotaciones, los formularios y los cambios
sin guardar) y se envían a un QPrinter de Qt, que usa el sistema de impresión del equipo
(Windows: controlador GDI; macOS: CUPS/AppKit). Así el resultado es igual en las dos
plataformas y no depende de qué programa tenga asociado el sistema a los PDF.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import pymupdf

log = logging.getLogger("novopdf.impresion")

# Modos de ajuste a la hoja
FIT_SHRINK = "shrink"
FIT_PAGE = "fit"
FIT_ACTUAL = "actual"
FIT_MODES = [
    (FIT_SHRINK, "Reducir solo las páginas que no caben (recomendado)"),
    (FIT_PAGE, "Ajustar cada página a la hoja"),
    (FIT_ACTUAL, "Tamaño real (100 %)"),
]

# Subconjuntos de páginas
SUBSETS = [("all", "Todas las páginas del intervalo"), ("odd", "Solo las impares (1, 3, 5…)"),
           ("even", "Solo las pares (2, 4, 6…)")]

MAX_DPI = 300           # resolución máxima a la que se rasteriza cada página
MIN_DPI = 150
BAND_PX = 512           # alto de cada franja de imagen enviada a la impresora (píxeles)


class PrintCancelled(Exception):
    pass


class PrintError(Exception):
    pass


@dataclass
class Placement:
    """Dónde se coloca una página en la hoja (en puntos, origen en la esquina de la hoja)."""
    rotate: bool
    x: float
    y: float
    w: float
    h: float
    scale: float


def apply_subset(pages: list[int], subset: str) -> list[int]:
    """Filtra por número de página (1, 3, 5… son impares)."""
    if subset == "odd":
        return [p for p in pages if (p + 1) % 2 == 1]
    if subset == "even":
        return [p for p in pages if (p + 1) % 2 == 0]
    return list(pages)


def place(page_w: float, page_h: float, paper_w: float, paper_h: float,
          printable: tuple[float, float, float, float], fit: str = FIT_SHRINK,
          auto_rotate: bool = True) -> Placement:
    """Calcula el giro, la escala y la posición de una página en la hoja.

    page_w/page_h: tamaño visible de la página (ya con su rotación).
    printable: (x, y, ancho, alto) de la zona imprimible de la hoja.
    """
    ax, ay, aw, ah = printable
    if aw <= 0 or ah <= 0:
        ax, ay, aw, ah = 0.0, 0.0, paper_w, paper_h
    rotate = False
    if auto_rotate and page_w > 0 and page_h > 0:
        page_land = page_w > page_h * 1.01
        page_port = page_h > page_w * 1.01
        area_land = aw > ah
        rotate = (page_land and not area_land) or (page_port and area_land)
    pw, ph = (page_h, page_w) if rotate else (page_w, page_h)
    pw, ph = max(pw, 1e-3), max(ph, 1e-3)
    fit_scale = min(aw / pw, ah / ph)
    if fit == FIT_PAGE:
        s = fit_scale
    elif fit == FIT_ACTUAL:
        s = 1.0
    else:
        s = min(1.0, fit_scale)
    w, h = pw * s, ph * s
    if fit == FIT_ACTUAL:
        # Tamaño real: centrada en la hoja (como en el papel original).
        x, y = (paper_w - w) / 2, (paper_h - h) / 2
    else:
        x, y = ax + (aw - w) / 2, ay + (ah - h) / 2
    return Placement(rotate, x, y, w, h, s)


def sheets(pages: list[int], copies: int, collate: bool) -> list[int]:
    """Orden de las páginas cuando las copias las hace el programa (no la impresora)."""
    copies = max(1, int(copies))
    if collate:
        return list(pages) * copies
    return [p for p in pages for _ in range(copies)]


def render_qimage(page: "pymupdf.Page", width_px: int, height_px: int, rotate: bool, gray: bool):
    """Dibuja una página al tamaño indicado (en píxeles) y la devuelve como QImage."""
    from PySide6.QtGui import QImage
    r = page.rect
    base_w = r.height if rotate else r.width
    zoom = max(width_px, 1) / max(base_w, 1e-3)
    m = pymupdf.Matrix(zoom, zoom)
    if rotate:
        m = m.prerotate(-90)   # la parte de arriba de la página queda a la izquierda de la hoja
    cs = pymupdf.csGRAY if gray else pymupdf.csRGB
    pix = page.get_pixmap(matrix=m, colorspace=cs, alpha=False, annots=True)
    fmt = QImage.Format_Grayscale8 if gray else QImage.Format_RGB888
    img = QImage(pix.samples, pix.width, pix.height, pix.stride, fmt)
    return img.copy()   # copia propia: los datos de PyMuPDF se liberan al salir


def bands(height_px: int, band: int = BAND_PX) -> list[tuple[int, int]]:
    """Franjas horizontales (y0, y1) en que se divide una imagen de height_px filas."""
    out, y = [], 0
    while y < height_px:
        out.append((y, min(height_px, y + band)))
        y += band
    return out


def band_targets(top: float, height_dev: float, height_px: int, band: int = BAND_PX) -> list[tuple[int, int, int, int]]:
    """(y0, y1, destino_y0, destino_y1): cada franja de la imagen y dónde va en la impresora,
    en píxeles enteros y sin huecos ni solapes entre franjas."""
    k = height_dev / max(height_px, 1)
    return [(a, b, round(top + a * k), round(top + b * k)) for a, b in bands(height_px, band)]


def draw_banded(painter, img, x_dev: float, y_dev: float, w_dev: float, h_dev: float):
    """Dibuja la imagen en franjas horizontales opacas (RGB de 32 bits, sin transparencia).

    Algunos controladores PCL 6 (PCL XL) fallan con imágenes de página entera
    («PCL XL error … IllegalAttributeDataType»): en franjas cada imagen es pequeña y
    sencilla, que es lo que mejor entienden todas las impresoras."""
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QImage
    x0, x1 = round(x_dev), round(x_dev + w_dev)
    for a, b, t0, t1 in band_targets(y_dev, h_dev, img.height()):
        if t1 <= t0:
            continue
        part = img.copy(0, a, img.width(), b - a).convertToFormat(QImage.Format_RGB32)
        painter.drawImage(QRect(x0, t0, x1 - x0, t1 - t0), part)


def printable_area_points(printer) -> tuple[float, float, tuple[float, float, float, float]]:
    """Tamaño de la hoja y zona imprimible (márgenes físicos de la impresora) en puntos."""
    from PySide6.QtGui import QPageLayout
    lay = QPageLayout(printer.pageLayout())
    lay.setUnits(QPageLayout.Point)
    full = lay.fullRect(QPageLayout.Point)
    mm = lay.minimumMargins()
    pw, ph = full.width(), full.height()
    x, y = max(0.0, mm.left()), max(0.0, mm.top())
    w = pw - x - max(0.0, mm.right())
    h = ph - y - max(0.0, mm.bottom())
    if w < pw * 0.5 or h < ph * 0.5:     # márgenes absurdos: usar la hoja entera
        x, y, w, h = 0.0, 0.0, pw, ph
    return pw, ph, (x, y, w, h)


def print_pages(doc: "pymupdf.Document", printer, pages: list[int], fit: str = FIT_SHRINK,
                auto_rotate: bool = True, gray: bool = False, copies: int = 1, collate: bool = True,
                progress=None) -> int:
    """Envía las páginas al QPrinter ya configurado. Devuelve el número de hojas enviadas.

    progress(k, total) -> bool: se llama antes de cada hoja; si devuelve False se cancela.
    Las copias las hace la impresora si puede; si no, se repiten aquí las páginas.
    """
    from PySide6.QtGui import QPainter
    if not pages:
        raise PrintError("No hay ninguna página que imprimir.")
    copies = max(1, int(copies))
    if copies > 1 and printer.supportsMultipleCopies():
        printer.setCopyCount(copies)
        printer.setCollateCopies(collate)
        order = list(pages)
    else:
        printer.setCopyCount(1)
        order = sheets(pages, copies, collate)
    printer.setFullPage(True)
    res = printer.resolution() or 300
    dpi = max(MIN_DPI, min(MAX_DPI, res))
    k_dev = res / 72.0                     # puntos -> píxeles de la impresora
    k_img = dpi / 72.0                     # puntos -> píxeles de la imagen
    log.info("Imprimir: %d hoja(s) en «%s», %d ppp (imagen %d ppp), ajuste=%s, giro=%s, gris=%s, copias=%d%s",
             len(order), printer.printerName() or printer.outputFileName(), res, dpi, fit, auto_rotate,
             gray, copies, " (impresora)" if printer.copyCount() > 1 else "")
    painter = QPainter()
    if not painter.begin(printer):
        raise PrintError("No se pudo empezar a imprimir. Comprueba que la impresora está encendida "
                         "y disponible, y vuelve a intentarlo.")
    total = len(order)
    try:
        # sin suavizado: el escalado lo hace el controlador (más sencillo para la impresora)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
        for k, pno in enumerate(order):
            if progress is not None and progress(k, total) is False:
                printer.abort()
                raise PrintCancelled()
            if k > 0 and not printer.newPage():
                raise PrintError("La impresora no aceptó una página nueva.")
            paper_w, paper_h, area = printable_area_points(printer)
            page = doc[pno]
            pl = place(page.rect.width, page.rect.height, paper_w, paper_h, area, fit, auto_rotate)
            img = render_qimage(page, round(pl.w * k_img), round(pl.h * k_img), pl.rotate, gray)
            draw_banded(painter, img, pl.x * k_dev, pl.y * k_dev, pl.w * k_dev, pl.h * k_dev)
            del img
        if progress is not None:
            progress(total, total)
    except PrintCancelled:
        raise
    except PrintError:
        printer.abort()
        raise
    except Exception as e:  # noqa
        log.exception("Error al imprimir")
        printer.abort()
        raise PrintError(f"Error al imprimir: {e}")
    finally:
        if painter.isActive():
            painter.end()
    return total

