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

"""Impresión «compatible» en Windows: directamente con GDI, sin pasar por Qt.

Para impresoras cuyo controlador falla con lo que envía Qt (p. ej. «PCL XL error
Subsystem: xlparse Error: IllegalAttributeDataType» en algunos controladores PCL 6).
Se usa la configuración predeterminada de la impresora (DEVMODE del controlador)
cambiando solo papel, orientación vertical, color y doble cara, y cada página se envía
como imagen RGB de 24 bits a ≤ 300 ppp, en franjas horizontales (StretchDIBits), que es lo
más básico que admite cualquier controlador de impresora de Windows.
"""
from __future__ import annotations

import logging

import pymupdf

from . import printing

log = logging.getLogger("novopdf.impresion")

# win32con
DM_ORIENTATION, DM_PAPERSIZE, DM_COPIES, DM_COLOR, DM_DUPLEX, DM_COLLATE = 0x1, 0x2, 0x100, 0x800, 0x1000, 0x8000
DMORIENT_PORTRAIT = 1
DMCOLOR_MONOCHROME, DMCOLOR_COLOR = 1, 2
DMDUP_SIMPLEX, DMDUP_VERTICAL, DMDUP_HORIZONTAL = 1, 2, 3
DM_IN_BUFFER, DM_OUT_BUFFER = 8, 2
HORZRES, VERTRES, LOGPIXELSX, LOGPIXELSY = 8, 10, 88, 90
PHYSICALWIDTH, PHYSICALHEIGHT, PHYSICALOFFSETX, PHYSICALOFFSETY = 110, 111, 112, 113


def available() -> bool:
    try:
        import win32gui  # noqa: F401
        import win32print  # noqa: F401
        from PIL import ImageWin  # noqa: F401
        return True
    except Exception:
        return False


def devmode_changes(paper_id: int | None, gray: bool, duplex: str) -> dict:
    """Campos del DEVMODE que se cambian (nombre del atributo de PyDEVMODE -> valor) y dmFields."""
    ch = {"Orientation": DMORIENT_PORTRAIT, "Color": DMCOLOR_MONOCHROME if gray else DMCOLOR_COLOR,
          "Copies": 1}
    fields = DM_ORIENTATION | DM_COLOR | DM_COPIES
    if paper_id:
        ch["PaperSize"] = int(paper_id)
        fields |= DM_PAPERSIZE
    if duplex in ("long", "short"):
        ch["Duplex"] = DMDUP_VERTICAL if duplex == "long" else DMDUP_HORIZONTAL
        fields |= DM_DUPLEX
    elif duplex == "none":
        ch["Duplex"] = DMDUP_SIMPLEX
        fields |= DM_DUPLEX
    return {"set": ch, "fields": fields}


def device_rect(pl: printing.Placement, res_x: float, res_y: float, off_x: float, off_y: float):
    """Rectángulo de la página en coordenadas del DC de la impresora (origen en la zona imprimible)."""
    kx, ky = res_x / 72.0, res_y / 72.0
    return pl.x * kx - off_x, pl.y * ky - off_y, pl.w * kx, pl.h * ky


def print_pages(doc: "pymupdf.Document", printer_name: str, pages: list[int], fit: str = printing.FIT_SHRINK,
                auto_rotate: bool = True, gray: bool = False, copies: int = 1, collate: bool = True,
                duplex: str = "", paper_id: int | None = None, doc_name: str = "NovoPDF",
                progress=None) -> int:
    """Imprime con GDI. Las copias se hacen repitiendo páginas (no depende del controlador)."""
    import win32gui
    import win32print
    from PIL import Image, ImageWin
    if not pages:
        raise printing.PrintError("No hay ninguna página que imprimir.")
    order = printing.sheets(pages, copies, collate)
    try:
        h = win32print.OpenPrinter(printer_name)
    except Exception as e:
        raise printing.PrintError(f"No se puede usar la impresora «{printer_name}»: {e}")
    hdc = None
    started = False
    total = len(order)
    try:
        dm = win32print.GetPrinter(h, 2)["pDevMode"]
        if dm is None:
            dm = win32print.DocumentProperties(0, h, printer_name, None, None, 0)
        ch = devmode_changes(paper_id, gray, duplex)
        for k, v in ch["set"].items():
            try:
                setattr(dm, k, v)
            except Exception:
                pass
        dm.Fields = dm.Fields | ch["fields"]
        try:   # que el controlador valide y complete el DEVMODE
            win32print.DocumentProperties(0, h, printer_name, dm, dm, DM_IN_BUFFER | DM_OUT_BUFFER)
        except Exception as e:  # noqa
            log.info("DocumentProperties: %s", e)
        hdc = win32gui.CreateDC("WINSPOOL", printer_name, dm)
        res_x = win32print.GetDeviceCaps(hdc, LOGPIXELSX) or 300
        res_y = win32print.GetDeviceCaps(hdc, LOGPIXELSY) or res_x
        phys_w = win32print.GetDeviceCaps(hdc, PHYSICALWIDTH)
        phys_h = win32print.GetDeviceCaps(hdc, PHYSICALHEIGHT)
        off_x = win32print.GetDeviceCaps(hdc, PHYSICALOFFSETX)
        off_y = win32print.GetDeviceCaps(hdc, PHYSICALOFFSETY)
        hres = win32print.GetDeviceCaps(hdc, HORZRES)
        vres = win32print.GetDeviceCaps(hdc, VERTRES)
        paper_w, paper_h = phys_w * 72.0 / res_x, phys_h * 72.0 / res_y
        area = (off_x * 72.0 / res_x, off_y * 72.0 / res_y, hres * 72.0 / res_x, vres * 72.0 / res_y)
        dpi = max(printing.MIN_DPI, min(printing.MAX_DPI, res_x))
        log.info("Imprimir (modo compatible GDI): %d hoja(s) en «%s», %dx%d ppp (imagen %d ppp), hoja %.0fx%.0f pt",
                 total, printer_name, res_x, res_y, dpi, paper_w, paper_h)
        win32print.StartDoc(hdc, (doc_name, None, None, 0))
        started = True
        for k, pno in enumerate(order):
            if progress is not None and progress(k, total) is False:
                win32print.AbortDoc(hdc)
                started = False
                raise printing.PrintCancelled()
            page = doc[pno]
            pl = printing.place(page.rect.width, page.rect.height, paper_w, paper_h, area, fit, auto_rotate)
            k_img = dpi / 72.0
            mat = pymupdf.Matrix(1, 1)
            base_w = page.rect.height if pl.rotate else page.rect.width
            zoom = round(pl.w * k_img) / max(base_w, 1e-3)
            mat = pymupdf.Matrix(zoom, zoom)
            if pl.rotate:
                mat = mat.prerotate(-90)
            pix = page.get_pixmap(matrix=mat, colorspace=pymupdf.csRGB, alpha=False, annots=True)
            img = Image.frombuffer("RGB", (pix.width, pix.height), pix.samples, "raw", "RGB", pix.stride, 1)
            if gray:
                img = img.convert("L").convert("RGB")
            x, y, w, hh = device_rect(pl, res_x, res_y, off_x, off_y)
            win32print.StartPage(hdc)
            x0, x1 = round(x), round(x + w)
            for a, b, t0, t1 in printing.band_targets(y, hh, img.height):
                if t1 > t0:
                    ImageWin.Dib(img.crop((0, a, img.width, b))).draw(hdc, (x0, t0, x1, t1))
            win32print.EndPage(hdc)
            del img, pix
        if progress is not None:
            progress(total, total)
        win32print.EndDoc(hdc)
        started = False
    except printing.PrintCancelled:
        raise
    except printing.PrintError:
        raise
    except Exception as e:  # noqa
        log.exception("Error al imprimir en modo compatible")
        raise printing.PrintError(f"Error al imprimir: {e}")
    finally:
        if started:
            try:
                win32print.AbortDoc(hdc)
            except Exception:
                pass
        if hdc is not None:
            try:
                win32gui.DeleteDC(hdc)
            except Exception:
                pass
        try:
            win32print.ClosePrinter(h)
        except Exception:
            pass
    return total
