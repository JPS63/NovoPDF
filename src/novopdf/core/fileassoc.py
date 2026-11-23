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

"""Asociar NovoPDF a los documentos PDF (programa predeterminado).

Windows: NovoPDF es portable, así que se registra solo para el usuario actual
(HKCU, sin permisos de administrador): tipo «NovoPDF.Document», lista «Abrir con»
de .pdf y «Aplicaciones predeterminadas». Windows 10/11 no permite que un programa
se ponga como predeterminado por sí mismo; se abre la ventana del sistema para que
el usuario lo confirme con «Siempre».
macOS: la .app ya declara los PDF en su Info.plist; se indica cómo elegirla.
"""
from __future__ import annotations

import logging
import os
import sys
import tempfile

from ..paths import app_dir

log = logging.getLogger("novopdf.asociacion")

IS_WINDOWS = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"
PROGID = "NovoPDF.Document"
APP_KEY = r"Applications\NovoPDF.exe"
BUNDLE_ID = "es.unex.novopdf"
_CLASSES = r"Software\Classes"


def supported() -> bool:
    return (IS_WINDOWS and exe_path() is not None) or IS_MAC


def exe_path() -> str | None:
    """NovoPDF.exe de esta copia portable (None si se ejecuta desde el código fuente)."""
    p = os.path.join(app_dir(), "NovoPDF.exe")
    return p if os.path.isfile(p) else None


def _command(exe: str) -> str:
    return f'"{exe}" "%1"'


# ------------------------------------------------------------------ Windows
def _reg():
    import winreg
    return winreg


def _read(root, path, name=""):
    winreg = _reg()
    try:
        with winreg.OpenKey(root, path) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def _set(path, name, value, kind=None):
    winreg = _reg()
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_WRITE) as k:
        winreg.SetValueEx(k, name, 0, kind if kind is not None else winreg.REG_SZ, value)


def _notify():
    try:
        import ctypes
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)   # SHCNE_ASSOCCHANGED
    except Exception:
        pass


def current_handler() -> str | None:
    """ProgId elegido por el usuario para .pdf (Windows) o bundle id (macOS)."""
    if IS_WINDOWS:
        winreg = _reg()
        return _read(winreg.HKEY_CURRENT_USER,
                     r"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.pdf\UserChoice",
                     "ProgId")
    if IS_MAC:
        return _mac_default_handler()
    return None


def is_default() -> bool | None:
    """True/False si se sabe; None si no se puede saber."""
    try:
        h = current_handler()
    except Exception:
        return None
    if IS_WINDOWS:
        return bool(h) and h.lower() in (PROGID.lower(), APP_KEY.lower())
    if IS_MAC:
        return None if h is None else h.lower() == BUNDLE_ID
    return None


def register(exe: str | None = None) -> None:
    """Registra NovoPDF para el usuario actual (no lo pone como predeterminado)."""
    exe = exe or exe_path()
    if not (IS_WINDOWS and exe):
        return
    winreg = _reg()
    cmd = _command(exe)
    icon = f'"{exe}",0'
    base = _CLASSES + "\\" + PROGID
    _set(base, "", "Documento PDF")
    _set(base, "FriendlyTypeName", "Documento PDF")
    _set(base + r"\DefaultIcon", "", icon)
    _set(base + r"\shell", "", "open")
    _set(base + r"\shell\open", "FriendlyAppName", "NovoPDF")
    _set(base + r"\shell\open\command", "", cmd)
    _set(_CLASSES + r"\.pdf\OpenWithProgids", PROGID, b"", winreg.REG_NONE)
    app = _CLASSES + "\\" + APP_KEY
    _set(app, "FriendlyAppName", "NovoPDF")
    _set(app + r"\DefaultIcon", "", icon)
    _set(app + r"\SupportedTypes", ".pdf", "")
    _set(app + r"\shell\open\command", "", cmd)
    cap = r"Software\NovoPDF\Capabilities"
    _set(cap, "ApplicationName", "NovoPDF")
    _set(cap, "ApplicationDescription", "Ver, editar, firmar y escanear documentos PDF")
    _set(cap + r"\FileAssociations", ".pdf", PROGID)
    _set(r"Software\RegisteredApplications", "NovoPDF", cap)
    _notify()
    log.info("NovoPDF registrado para los PDF: %s", exe)


def refresh_if_moved() -> bool:
    """Si la carpeta portable se ha movido, actualiza la ruta registrada.
    Solo cuando el ejecutable registrado ya no existe (para no pelearse con otra copia)."""
    if not IS_WINDOWS:
        return False
    exe = exe_path()
    if not exe:
        return False
    winreg = _reg()
    changed = False
    try:
        for key in (PROGID, APP_KEY):
            cur = _read(winreg.HKEY_CURRENT_USER, _CLASSES + "\\" + key + r"\shell\open\command")
            if not cur:
                continue
            old = cur.split('"')[1] if cur.startswith('"') else cur.split(" ")[0]
            if os.path.normcase(old) != os.path.normcase(exe) and not os.path.isfile(old):
                changed = True
        if changed:
            register(exe)
            log.info("Ruta de NovoPDF actualizada en la asociación de PDF")
    except Exception as e:
        log.warning("No se pudo comprobar la asociación de PDF: %s", e)
    return changed


def _sample_pdf() -> str:
    d = os.path.join(tempfile.gettempdir(), "NovoPDF")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "documento.pdf")
    if not os.path.isfile(p):
        with open(p, "wb") as fh:
            fh.write(b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
                     b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
                     b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]>>endobj\n"
                     b"trailer<</Root 1 0 R>>\n%%EOF\n")
    return p


def show_system_chooser(hwnd: int | None, sample: str | None = None) -> bool:
    """Abre la ventana de Windows «¿Cómo quieres abrir los archivos .pdf?»
    (con «Siempre» / «Usar siempre esta aplicación»). Devuelve False si no se pudo."""
    import ctypes
    from ctypes import wintypes as wt

    class OPENASINFO(ctypes.Structure):
        _fields_ = [("pcszFile", wt.LPCWSTR), ("pcszClass", wt.LPCWSTR), ("oaifInFlags", ctypes.c_int)]

    OAIF_ALLOW_REGISTRATION, OAIF_REGISTER_EXT = 0x1, 0x2
    info = OPENASINFO(sample if sample and os.path.isfile(sample) else _sample_pdf(), None,
                      OAIF_ALLOW_REGISTRATION | OAIF_REGISTER_EXT)
    fn = ctypes.windll.shell32.SHOpenWithDialog
    fn.argtypes = [wt.HWND, ctypes.POINTER(OPENASINFO)]
    fn.restype = ctypes.c_long
    hr = fn(hwnd, ctypes.byref(info)) & 0xFFFFFFFF
    if hr in (0, 0x800704C7):          # S_OK o cancelado por el usuario
        return True
    log.warning("SHOpenWithDialog devolvió 0x%08X", hr)
    return False


def open_default_apps_settings() -> None:
    try:
        os.startfile("ms-settings:defaultapps")      # noqa: S606
    except Exception as e:
        log.warning("No se pudo abrir Configuración: %s", e)


# ------------------------------------------------------------------ macOS
def _mac_default_handler() -> str | None:
    try:
        import ctypes
        import ctypes.util
        cf = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreFoundation"))
        cs = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreServices"))
        cf.CFStringCreateWithCString.restype = ctypes.c_void_p
        cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
        cf.CFStringGetCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32]
        cf.CFRelease.argtypes = [ctypes.c_void_p]
        cs.LSCopyDefaultRoleHandlerForContentType.restype = ctypes.c_void_p
        cs.LSCopyDefaultRoleHandlerForContentType.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        uti = cf.CFStringCreateWithCString(None, b"com.adobe.pdf", 0x08000100)
        try:
            h = cs.LSCopyDefaultRoleHandlerForContentType(uti, 0x00000002)   # kLSRolesViewer
            if not h:
                return None
            buf = ctypes.create_string_buffer(512)
            ok = cf.CFStringGetCString(h, buf, 512, 0x08000100)
            cf.CFRelease(h)
            return buf.value.decode("utf-8") if ok else None
        finally:
            cf.CFRelease(uti)
    except Exception:
        return None


MAC_STEPS = ("1. En el Finder, selecciona cualquier PDF.\n"
             "2. Menú Archivo > Obtener información (⌘I).\n"
             "3. En «Abrir con», elige NovoPDF.\n"
             "4. Pulsa «Cambiar todo…» y confirma con «Continuar».")
