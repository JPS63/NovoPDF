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

"""Escaneo directo a PDF mediante WIA (Windows Image Acquisition) o TWAIN.

WIA es el sistema de escaneo integrado en Windows: funciona con la mayoría de
escáneres y multifunciones de oficina sin instalar nada más que su driver. Los
escáneres que solo tienen controlador TWAIN (p. ej. muchos multifunción en red)
se usan con core/twain.py.

Todas las funciones que usan WIA deben llamarse desde el mismo hilo, después
de `com_init()`.

Para pruebas sin escáner: variable de entorno NOVOPDF_FAKE_SCANNER=<ruta a un PDF>
(cada página del PDF se «escanea» como una imagen).
"""
from __future__ import annotations

import io
import os
import sys
from dataclasses import dataclass

import pymupdf

FAKE = os.environ.get("NOVOPDF_FAKE_SCANNER", "")

# Propiedades WIA
P_DOC_CAPS = 3086          # WIA_DPS_DOCUMENT_HANDLING_CAPABILITIES
P_DOC_STATUS = 3087        # WIA_DPS_DOCUMENT_HANDLING_STATUS
P_DOC_SELECT = 3088        # WIA_DPS_DOCUMENT_HANDLING_SELECT
P_PAGES = 3096             # WIA_DPS_PAGES
P_INTENT = 6146            # WIA_IPS_CUR_INTENT
P_XRES, P_YRES = 6147, 6148
P_XEXT, P_YEXT = 6151, 6152
P_DATATYPE = 4103          # WIA_IPA_DATATYPE
FEEDER, FLATBED, DUPLEX = 0x1, 0x2, 0x4
INTENT = {"color": 1, "gray": 2, "bw": 4}
DATATYPE = {"color": 3, "gray": 2, "bw": 0}
FMT_PNG = "{B96B3CAF-0728-11D3-9D7B-0000F81EF32E}"
FMT_BMP = "{B96B3CAB-0728-11D3-9D7B-0000F81EF32E}"

WIA_ERRORS = {
    0x80210001: "Error general del escáner.",
    0x80210002: "Hay un atasco de papel en el escáner.",
    0x80210003: "No hay papel en el alimentador.",
    0x80210004: "Problema con el papel en el alimentador.",
    0x80210005: "El escáner está apagado o desconectado.",
    0x80210006: "El escáner está ocupado. Espera un momento e inténtalo de nuevo.",
    0x80210007: "El escáner se está calentando. Espera un momento e inténtalo de nuevo.",
    0x80210009: "El escáner se ha desconectado.",
    0x8021000A: "Se ha perdido la conexión con el escáner.",
    0x8021000C: "El escáner no admite esta opción.",
    0x80210015: "No se ha encontrado ningún escáner.",
    0x80210016: "La tapa del escáner está abierta.",
    0x80210017: "La lámpara del escáner está apagada.",
    0x80210064: "Operación cancelada.",
    0x80070005: "Acceso denegado al escáner.",
    0x80040154: "El servicio de escaneo de Windows (WIA) no está disponible en este equipo.",
    0x800401F3: "El servicio de escaneo de Windows (WIA) no está disponible en este equipo.",
}
PAPER_EMPTY = 0x80210003


class ScannerError(Exception):
    def __init__(self, msg, code=0):
        super().__init__(msg)
        self.code = code


class NoPaper(ScannerError):
    pass


@dataclass
class ScanDevice:
    id: str
    name: str
    flatbed: bool = True
    feeder: bool = False
    duplex: bool = False
    kind: str = "wia"           # wia | twain


@dataclass
class ScanSettings:
    device_id: str
    source: str = "flatbed"     # flatbed | feeder | duplex
    mode: str = "gray"          # color | gray | bw
    dpi: int = 300
    show_ui: bool = True        # TWAIN: mostrar la ventana del controlador del escáner


@dataclass
class ScannedImage:
    data: bytes                 # imagen tal como la entrega el escáner (PNG/BMP/...)
    dpi: int


MAC = sys.platform == "darwin"


def available() -> bool:
    if FAKE or MAC or USE_FOLDER_SCAN:
        return True
    from . import twain
    if twain.RUNNER and twain.available():
        return True
    if not sys.platform.startswith("win"):
        return False
    try:
        import win32com.client  # noqa: F401
        return True
    except Exception:
        return False


def com_init():
    if FAKE or MAC or not sys.platform.startswith("win"):
        return
    import pythoncom
    pythoncom.CoInitialize()


def com_uninit():
    if FAKE or not sys.platform.startswith("win"):
        return
    try:
        import pythoncom
        pythoncom.CoUninitialize()
    except Exception:
        pass


def _hresult(e) -> int:
    codes = []
    args = getattr(e, "args", ())
    if args and isinstance(args[0], int):
        codes.append(args[0])
    if len(args) > 2 and args[2] and len(args[2]) > 5 and isinstance(args[2][5], int):
        codes.insert(0, args[2][5])
    for c in codes:
        c &= 0xFFFFFFFF
        if (c >> 16) == 0x8021 or c in WIA_ERRORS:
            return c
    return (codes[0] & 0xFFFFFFFF) if codes else 0


def _wrap(e, default="Error del escáner") -> ScannerError:
    if isinstance(e, ScannerError):
        return e
    code = _hresult(e)
    if code == PAPER_EMPTY:
        return NoPaper(WIA_ERRORS[code], code)
    msg = WIA_ERRORS.get(code)
    if not msg:
        msg = f"{default} (código 0x{code:08X})." if code else f"{default}: {e}"
    return ScannerError(msg, code)


def _props_get(props, pid, default=None):
    try:
        for p in props:
            if p.PropertyID == pid:
                return p.Value
    except Exception:
        pass
    return default


def _props_set(props, pid, value) -> bool:
    try:
        for p in props:
            if p.PropertyID == pid:
                try:
                    p.Value = value
                    return True
                except Exception:
                    return False
    except Exception:
        pass
    return False


def _prop_max(props, pid):
    try:
        for p in props:
            if p.PropertyID == pid:
                return p.SubTypeMax
    except Exception:
        pass
    return None


# ---------------------------------------------------------------- dispositivos
def list_devices() -> list[ScanDevice]:
    """Escáneres WIA y TWAIN. Si WIA falla pero hay escáneres TWAIN, se devuelven estos."""
    if FAKE:
        return [ScanDevice("fake", "Escáner de prueba", True, True, True)]
    from . import twain
    wia, wia_error = [], None
    try:
        wia = _list_wia()
    except ScannerError as e:
        wia_error = e
    except Exception as e:  # noqa
        wia_error = ScannerError(f"No se pudo usar el servicio de escaneo de Windows: {e}")
    tw = []
    if twain.available():
        try:
            for s in twain.list_sources():
                label = s.name if "twain" in s.name.lower() else f"{s.name} (TWAIN)"
                tw.append(ScanDevice(s.id, label, True, True, True, "twain"))
        except Exception as e:  # noqa
            import logging
            logging.getLogger("novopdf.escaner").info("No se pudieron listar los escáneres TWAIN: %s", e)
    if not wia and not tw and wia_error is not None:
        raise wia_error
    return wia + tw


def _list_wia() -> list[ScanDevice]:
    if not sys.platform.startswith("win"):
        return []
    import win32com.client
    try:
        dm = win32com.client.Dispatch("WIA.DeviceManager")
    except Exception as e:
        raise _wrap(e, "No se pudo iniciar el servicio de escaneo de Windows")
    out = []
    try:
        for i in range(1, dm.DeviceInfos.Count + 1):
            info = dm.DeviceInfos.Item(i)
            if info.Type != 1:           # 1 = escáner
                continue
            name = _props_get(info.Properties, 7, None) or info.DeviceID  # WIA_DIP_DEV_NAME
            dev = ScanDevice(info.DeviceID, str(name))
            try:
                d = info.Connect()
                caps = _props_get(d.Properties, P_DOC_CAPS, 0) or 0
                if caps:
                    dev.flatbed = bool(caps & FLATBED)
                    dev.feeder = bool(caps & FEEDER)
                    dev.duplex = bool(caps & DUPLEX)
            except Exception:
                pass   # sin conexión ahora: se intentará al escanear
            out.append(dev)
    except Exception as e:
        raise _wrap(e, "No se pudieron enumerar los escáneres")
    return out


# ---------------------------------------------------------------- escaneo
def _fake_scan(settings: ScanSettings, on_page, cancelled, max_pages):
    src = pymupdf.open(FAKE)
    n = src.page_count if settings.source != "flatbed" else 1
    start = int(os.environ.get("NOVOPDF_FAKE_START", "0"))
    count = 0
    for k in range(n):
        if cancelled and cancelled():
            break
        idx = (start + k) % src.page_count
        cs = pymupdf.csRGB if settings.mode == "color" else pymupdf.csGRAY
        pix = src[idx].get_pixmap(dpi=settings.dpi // 2, colorspace=cs)
        on_page(ScannedImage(pix.tobytes("png"), settings.dpi // 2))
        count += 1
        if max_pages and count >= max_pages:
            break
    os.environ["NOVOPDF_FAKE_START"] = str(start + count)
    if settings.source != "flatbed" and count == 0:
        raise NoPaper(WIA_ERRORS[PAPER_EMPTY], PAPER_EMPTY)
    return count


def scan(settings: ScanSettings, on_page, cancelled=None, max_pages: int = 0) -> int:
    """Escanea. Cristal: una página. Alimentador: hasta que se vacía.
    on_page(ScannedImage) se llama por cada página. Devuelve el nº de páginas."""
    if FAKE:
        return _fake_scan(settings, on_page, cancelled, max_pages)
    if settings.device_id.startswith("twain"):
        from . import twain
        try:
            return twain.scan(settings.device_id, settings.source, settings.mode, settings.dpi,
                              settings.show_ui, lambda data, dpi: on_page(ScannedImage(data, dpi)), cancelled)
        except twain.TwainError as e:
            if e.code == twain.NO_MEDIA:
                raise NoPaper(str(e), PAPER_EMPTY)
            raise ScannerError(str(e), e.code)
    import win32com.client
    try:
        dm = win32com.client.Dispatch("WIA.DeviceManager")
        info = None
        for i in range(1, dm.DeviceInfos.Count + 1):
            if dm.DeviceInfos.Item(i).DeviceID == settings.device_id:
                info = dm.DeviceInfos.Item(i)
                break
        if info is None:
            raise ScannerError("No se encuentra el escáner seleccionado. Comprueba que está encendido y conectado.")
        device = info.Connect()
    except Exception as e:
        raise _wrap(e, "No se pudo conectar con el escáner")

    # Origen del papel
    dprops = device.Properties
    if settings.source == "feeder":
        _props_set(dprops, P_DOC_SELECT, FEEDER)
    elif settings.source == "duplex":
        if not _props_set(dprops, P_DOC_SELECT, FEEDER | DUPLEX):
            _props_set(dprops, P_DOC_SELECT, FEEDER)
    else:
        _props_set(dprops, P_DOC_SELECT, FLATBED)
    if settings.source != "flatbed":
        _props_set(dprops, P_PAGES, 1)

    try:
        item = device.Items.Item(1)
    except Exception as e:
        raise _wrap(e, "El escáner no ofrece ninguna fuente de imagen")
    iprops = item.Properties
    _props_set(iprops, P_INTENT, INTENT[settings.mode])
    _props_set(iprops, P_DATATYPE, DATATYPE[settings.mode])
    _props_set(iprops, P_XRES, settings.dpi)
    _props_set(iprops, P_YRES, settings.dpi)
    # Área de escaneo: A4 (si el escáner lo permite)
    dpi_real = int(_props_get(iprops, P_XRES, settings.dpi) or settings.dpi)
    for pid, inches in ((P_XEXT, 8.27), (P_YEXT, 11.69)):
        want = int(inches * dpi_real)
        mx = _prop_max(iprops, pid)
        if mx:
            want = min(want, int(mx))
        _props_set(iprops, pid, want)

    count = 0
    while True:
        if cancelled and cancelled():
            break
        try:
            try:
                img = item.Transfer(FMT_PNG)
            except Exception as e:
                code = _hresult(e)
                if code in (0x8021000C, 0x80070057):   # formato no admitido -> BMP
                    img = item.Transfer(FMT_BMP)
                else:
                    raise
        except Exception as e:
            err = _wrap(e, "No se pudo escanear")
            if isinstance(err, NoPaper) and count > 0:
                break                       # alimentador vacío: fin normal
            raise err
        data = bytes(img.FileData.BinaryData)
        on_page(ScannedImage(data, dpi_real))
        count += 1
        if settings.source == "flatbed" or (max_pages and count >= max_pages):
            break
    return count


def acquire_with_windows_dialog() -> list[ScannedImage]:
    """Usa el asistente de escaneo de Windows (compatible con casi cualquier escáner)."""
    if FAKE:
        out = []
        _fake_scan(ScanSettings("fake", "flatbed", "gray", 300), out.append, None, 1)
        return out
    import win32com.client
    try:
        dlg = win32com.client.Dispatch("WIA.CommonDialog")
        # DeviceType=1 escáner, Intent=0, Bias=0, Format PNG, AlwaysSelectDevice, UseCommonUI, CancelError
        img = dlg.ShowAcquireImage(1, 0, 0, FMT_PNG, False, True, False)
    except Exception as e:
        raise _wrap(e, "No se pudo usar el asistente de escaneo de Windows")
    if img is None:
        return []
    try:
        dpi = int(round(img.HorizontalResolution)) or 200
    except Exception:
        dpi = 200
    return [ScannedImage(bytes(img.FileData.BinaryData), dpi)]


# ---------------------------------------------------------------- imágenes -> PDF
def is_blank(data: bytes) -> bool:
    """Página en blanco: casi todos los píxeles son claros."""
    from PIL import Image, ImageStat
    im = Image.open(io.BytesIO(data)).convert("L")
    im.thumbnail((400, 400))
    # Ignorar bordes (sombras del escáner)
    w, h = im.size
    im = im.crop((int(w * 0.05), int(h * 0.05), int(w * 0.95), int(h * 0.95)))
    dark = sum(im.point(lambda v: 255 if v < 200 else 0).convert("L").histogram()[255:])
    return dark / max(1, im.size[0] * im.size[1]) < 0.002


def images_to_pdf(images: list[ScannedImage], mode: str, remove_blank: bool = False) -> tuple[bytes, int]:
    """Crea un PDF con una página por imagen, del tamaño real escaneado.
    Las imágenes en color/grises se comprimen en JPEG; las de blanco y negro sin pérdida.
    Devuelve (bytes del PDF, nº de páginas en blanco eliminadas)."""
    from PIL import Image
    doc = pymupdf.open()
    removed = 0
    for s in images:
        if remove_blank and is_blank(s.data):
            removed += 1
            continue
        im = Image.open(io.BytesIO(s.data))
        im.load()
        dpi = s.dpi or 200
        try:
            info_dpi = im.info.get("dpi")
            if info_dpi and info_dpi[0] > 30:
                dpi = int(round(info_dpi[0]))
        except Exception:
            pass
        buf = io.BytesIO()
        if mode == "bw":
            im = im.convert("L").point(lambda v: 255 if v > 150 else 0).convert("1")
            im.save(buf, format="PNG", optimize=True)
        else:
            im = im.convert("RGB" if mode == "color" else "L")
            im.save(buf, format="JPEG", quality=85, optimize=True)
        wpt = im.size[0] / dpi * 72
        hpt = im.size[1] / dpi * 72
        page = doc.new_page(width=wpt, height=hpt)
        page.insert_image(page.rect, stream=buf.getvalue())
    if doc.page_count == 0:
        doc.close()
        return b"", removed
    out = doc.tobytes(garbage=3, deflate=True)
    doc.close()
    return out, removed


# ---------------------------------------------------------------- macOS: Captura de Imagen
# macOS no tiene WIA. Se usa la aplicación «Captura de Imagen» de Apple, que
# funciona con cualquier escáner compatible con el Mac: NovoPDF vigila una
# carpeta y va recogiendo las páginas que se escanean en ella.
SCAN_EXT = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".pdf")


USE_FOLDER_SCAN = MAC or bool(os.environ.get("NOVOPDF_FORCE_FOLDER_SCAN"))


def mac_scan_folder() -> str:
    d = os.environ.get("NOVOPDF_SCAN_FOLDER") or os.path.join(os.path.expanduser("~/Documents"), "Escaneos NovoPDF")
    os.makedirs(d, exist_ok=True)
    return d


def open_image_capture(folder: str | None = None):
    import subprocess
    if FAKE and not MAC:
        return
    try:
        subprocess.Popen(["open", "-b", "com.apple.Image_Capture"])
    except Exception:
        subprocess.Popen(["open", "-a", "Image Capture"])


def new_files(folder: str, since: float, known: set) -> list[str]:
    """Archivos de imagen nuevos y ya terminados de escribir (por orden de llegada)."""
    import time
    out = []
    try:
        names = os.listdir(folder)
    except OSError:
        return out
    now = time.time()
    for n in names:
        p = os.path.join(folder, n)
        if p in known or n.startswith(".") or not n.lower().endswith(SCAN_EXT):
            continue
        try:
            st = os.stat(p)
        except OSError:
            continue
        if st.st_mtime < since - 1 or st.st_size == 0 or now - st.st_mtime < 1.5:
            continue          # anterior a esta sesión, vacío o todavía escribiéndose
        out.append((st.st_mtime, n, p))
    return [p for _, _, p in sorted(out)]


def files_to_images(paths: list[str], dpi_default: int = 300) -> list[ScannedImage]:
    out = []
    for p in paths:
        if p.lower().endswith(".pdf"):
            src = pymupdf.open(p)
            for page in src:
                imgs = page.get_images(full=True)
                pix = None
                if len(imgs) == 1:
                    # página escaneada: extraer la imagen original
                    try:
                        info = src.extract_image(imgs[0][0])
                        r = page.get_image_rects(imgs[0][0])[0]
                        dpi = int(round(info["width"] / max(r.width, 1) * 72))
                        out.append(ScannedImage(info["image"], max(72, dpi)))
                        continue
                    except Exception:
                        pass
                pix = page.get_pixmap(dpi=dpi_default)
                out.append(ScannedImage(pix.tobytes("png"), dpi_default))
            src.close()
        else:
            with open(p, "rb") as fh:
                out.append(ScannedImage(fh.read(), dpi_default))
    return out
