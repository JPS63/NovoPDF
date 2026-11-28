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

"""Impresora virtual «NovoPDF»: imprimir desde cualquier programa abre el resultado en NovoPDF.

Windows: una impresora con el controlador «Microsoft Print To PDF» (viene con Windows 10
y 11) cuyo puerto es la tubería con nombre \\\\.\\pipe\\NovoPDF-impresora. El receptor es el
propio lanzador (NovoPDF.exe --impresora, en C, muy ligero), que se arranca al iniciar
sesión: guarda cada trabajo en %LOCALAPPDATA%\\NovoPDF\\Impresiones y lo abre con NovoPDF.
Crear la impresora y el puerto necesita permiso de administrador (una vez); el arranque
automático va en HKCU (sin permisos).

macOS: un «servicio PDF» (~/Library/PDF Services/Abrir en NovoPDF): en el cuadro de impresión
de cualquier programa, menú «PDF» › «Abrir en NovoPDF». No necesita permisos.
"""
from __future__ import annotations

import base64
import logging
import os
import subprocess
import sys

from ..paths import app_dir

log = logging.getLogger("novopdf.impresora")

IS_WINDOWS = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"
PRINTER = "NovoPDF"
PIPE = r"\\.\pipe\NovoPDF-impresora"
DRIVER = "Microsoft Print To PDF"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "NovoPDF impresora"
MAC_SERVICE = os.path.expanduser("~/Library/PDF Services/Abrir en NovoPDF")


class PrinterSetupError(Exception):
    pass


def supported() -> bool:
    return (IS_WINDOWS and exe_path() is not None) or (IS_MAC and mac_app() is not None)


def exe_path() -> str | None:
    p = os.path.join(app_dir(), "NovoPDF.exe")
    return p if os.path.isfile(p) else None


def mac_app() -> str | None:
    """Ruta de NovoPDF.app (si se ejecuta desde la aplicación empaquetada)."""
    p = os.path.abspath(sys.executable)
    while p and p != "/":
        if p.endswith(".app"):
            return p
        p = os.path.dirname(p)
    return None


def jobs_dir() -> str:
    if IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(base, "NovoPDF", "Impresiones")
    return os.path.expanduser("~/Library/Caches/NovoPDF/Impresiones")


def is_print_job(path: str) -> bool:
    """¿Viene de la impresora NovoPDF? (se trata como documento nuevo, sin guardar)."""
    try:
        return os.path.normcase(os.path.dirname(os.path.abspath(path))) == os.path.normcase(jobs_dir())
    except Exception:
        return False


# ====================================================================== estado
def is_installed() -> bool:
    if IS_MAC:
        return os.path.isfile(MAC_SERVICE)
    if not IS_WINDOWS:
        return False
    try:
        import win32print
        for flags, desc, name, comment in win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL, None, 1):
            if name.lower() == PRINTER.lower():
                return True
    except Exception as e:  # noqa
        log.info("No se pudo consultar las impresoras: %s", e)
    return False


def listener_running() -> bool:
    if not IS_WINDOWS:
        return False
    try:
        import ctypes
        return bool(ctypes.windll.kernel32.WaitNamedPipeW(PIPE, 1)) or ctypes.windll.kernel32.GetLastError() == 121
    except Exception:
        return False


def _run_value() -> str:
    return f'"{exe_path()}" --impresora'


def ensure_listener():
    """Al abrir NovoPDF: si la impresora está instalada, que el receptor arranque con la
    sesión desde ESTA carpeta (por si se ha movido) y que esté en marcha."""
    if not IS_WINDOWS or exe_path() is None or not is_installed():
        return
    try:
        import winreg
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ | winreg.KEY_WRITE) as k:
            try:
                cur = winreg.QueryValueEx(k, RUN_NAME)[0]
            except OSError:
                cur = ""
            if cur != _run_value():
                winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, _run_value())
                log.info("Arranque del receptor de la impresora: %s", _run_value())
    except Exception as e:  # noqa
        log.info("No se pudo registrar el arranque del receptor: %s", e)
    if not listener_running():
        start_listener()


def start_listener():
    exe = exe_path()
    if not exe:
        return
    try:
        subprocess.Popen([exe, "--impresora"], close_fds=True,
                         creationflags=0x00000008 | 0x00000200)     # DETACHED_PROCESS | NEW_PROCESS_GROUP
        log.info("Receptor de la impresora NovoPDF iniciado")
    except Exception as e:  # noqa
        log.warning("No se pudo iniciar el receptor de la impresora: %s", e)


def stop_listener():
    """Pide al receptor que se cierre (le manda un mensaje por la tubería)."""
    if not IS_WINDOWS:
        return
    try:
        with open(PIPE, "wb") as fh:
            fh.write(b"NOVOPDF-SALIR")
    except Exception:
        pass


# ====================================================================== Windows: instalar y quitar
_PS_INSTALL = r"""
$ErrorActionPreference = 'Stop'
$log = Join-Path $env:ProgramData 'NovoPDF\impresora.log'
New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null
try {
  $port = '\\.\pipe\NovoPDF-impresora'
  if (-not (Get-PrinterDriver -Name 'Microsoft Print To PDF' -ErrorAction SilentlyContinue)) {
    Add-PrinterDriver -Name 'Microsoft Print To PDF'
  }
  if (-not (Get-PrinterPort -Name $port -ErrorAction SilentlyContinue)) { Add-PrinterPort -Name $port }
  if (Get-Printer -Name 'NovoPDF' -ErrorAction SilentlyContinue) { Remove-Printer -Name 'NovoPDF' }
  Add-Printer -Name 'NovoPDF' -DriverName 'Microsoft Print To PDF' -PortName $port -Comment 'Abre lo impreso en NovoPDF'
  "$(Get-Date -Format s) instalada" | Out-File -FilePath $log -Append -Encoding utf8
  exit 0
} catch {
  "$(Get-Date -Format s) ERROR: $($_.Exception.Message)" | Out-File -FilePath $log -Append -Encoding utf8
  exit 1
}
"""

_PS_REMOVE = r"""
$ErrorActionPreference = 'Continue'
$log = Join-Path $env:ProgramData 'NovoPDF\impresora.log'
New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null
Remove-Printer -Name 'NovoPDF' -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1
Remove-PrinterPort -Name '\\.\pipe\NovoPDF-impresora' -ErrorAction SilentlyContinue
"$(Get-Date -Format s) quitada" | Out-File -FilePath $log -Append -Encoding utf8
exit 0
"""


def _log_tail() -> str:
    try:
        p = os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), "NovoPDF", "impresora.log")
        with open(p, encoding="utf-8-sig", errors="replace") as fh:
            lines = [ln.strip() for ln in fh if ln.strip()]
        return lines[-1] if lines else ""
    except OSError:
        return ""


def _run_elevated_powershell(script: str, timeout_ms: int = 180000) -> int:
    """Ejecuta PowerShell como administrador (Windows pide permiso) y espera. Código de salida,
    o -1 si el usuario no ha dado permiso."""
    import ctypes
    from ctypes import wintypes
    enc = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    params = f"-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -EncodedCommand {enc}"

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND),
                    ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
                    ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
                    ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
                    ("dwHotKey", wintypes.DWORD), ("hIconOrMonitor", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]
    sei = SHELLEXECUTEINFOW()
    sei.cbSize = ctypes.sizeof(sei)
    sei.fMask = 0x00000040                      # SEE_MASK_NOCLOSEPROCESS
    sei.lpVerb = "runas"
    sei.lpFile = "powershell.exe"
    sei.lpParameters = params
    sei.nShow = 0
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(sei)):
        err = ctypes.windll.kernel32.GetLastError()
        if err == 1223:                         # ERROR_CANCELLED: no se dio permiso
            return -1
        raise PrinterSetupError(f"No se pudo pedir permiso de administrador (error {err}).")
    try:
        ctypes.windll.kernel32.WaitForSingleObject(sei.hProcess, timeout_ms)
        code = wintypes.DWORD()
        ctypes.windll.kernel32.GetExitCodeProcess(sei.hProcess, ctypes.byref(code))
        return int(code.value)
    finally:
        ctypes.windll.kernel32.CloseHandle(sei.hProcess)


def install() -> str:
    """Instala la impresora. Devuelve un mensaje para el usuario; lanza PrinterSetupError si falla."""
    if IS_MAC:
        return _mac_install()
    if not IS_WINDOWS or exe_path() is None:
        raise PrinterSetupError("La impresora NovoPDF solo se puede instalar desde la versión portable para "
                                "Windows o desde NovoPDF.app en el Mac.")
    code = _run_elevated_powershell(_PS_INSTALL)
    if code == -1:
        raise PrinterSetupError("No se ha instalado: hace falta aceptar el permiso de administrador que pide Windows.")
    if code != 0 or not is_installed():
        detail = _log_tail()
        log.warning("Instalación de la impresora fallida (código %s): %s", code, detail)
        raise PrinterSetupError("Windows no ha podido crear la impresora."
                                + (f"\n\nDetalle: {detail.split('ERROR:', 1)[-1].strip()}" if detail else "")
                                + "\n\nComprueba que «Microsoft Print to PDF» está activado en «Características "
                                  "de Windows».")
    ensure_listener()
    log.info("Impresora NovoPDF instalada")
    return ("Ya está instalada la impresora «NovoPDF». Al imprimir desde cualquier programa (Word, el navegador…) "
            "elige «NovoPDF» y el documento se abrirá aquí, listo para revisar, firmar o guardar.")


def uninstall() -> str:
    if IS_MAC:
        try:
            os.remove(MAC_SERVICE)
        except FileNotFoundError:
            pass
        return "Se ha quitado «Abrir en NovoPDF» del menú PDF del cuadro de impresión."
    if not IS_WINDOWS:
        return ""
    stop_listener()
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, RUN_NAME)
    except OSError:
        pass
    code = _run_elevated_powershell(_PS_REMOVE)
    if code == -1:
        raise PrinterSetupError("No se ha quitado: hace falta aceptar el permiso de administrador que pide Windows.")
    if is_installed():
        raise PrinterSetupError("Windows no ha podido quitar la impresora. Puedes quitarla en Configuración › "
                                "Bluetooth y dispositivos › Impresoras y escáneres.")
    log.info("Impresora NovoPDF quitada")
    return "Se ha quitado la impresora «NovoPDF»."


# ====================================================================== macOS
_MAC_SCRIPT = """#!/bin/sh
# Servicio PDF de NovoPDF: el cuadro de impresión de macOS pasa el título ($1), las opciones ($2)
# y el PDF temporal ($3). Se copia (macOS lo borra al terminar) y se abre con NovoPDF.
DIR="$HOME/Library/Caches/NovoPDF/Impresiones"
mkdir -p "$DIR"
NAME=$(printf '%s' "$1" | tr '/:' '__' | cut -c1-80)
[ -z "$NAME" ] && NAME="Impreso $(date '+%Y-%m-%d %H.%M.%S')"
DEST="$DIR/$NAME.pdf"
N=2
while [ -e "$DEST" ]; do DEST="$DIR/$NAME ($N).pdf"; N=$((N+1)); done
cp "$3" "$DEST"
open -a "{app}" "$DEST"
"""


def _mac_install() -> str:
    app = mac_app()
    if not app:
        raise PrinterSetupError("Solo se puede activar desde NovoPDF.app.")
    os.makedirs(os.path.dirname(MAC_SERVICE), exist_ok=True)
    with open(MAC_SERVICE, "w", encoding="utf-8") as fh:
        fh.write(_MAC_SCRIPT.replace("{app}", app.replace('"', '\\"')))
    os.chmod(MAC_SERVICE, 0o755)
    return ("Listo. En el cuadro de impresión de cualquier programa, abre el menú «PDF» (abajo a la izquierda) y "
            "elige «Abrir en NovoPDF».")


# ====================================================================== navegadores
BROWSER_HELP = (
    "<p>Los navegadores tienen su propio visor de PDF y no dejan que otro programa se meta dentro, "
    "pero se les puede pedir que <b>abran los PDF con NovoPDF</b>:</p>"
    "<p><b>1. NovoPDF como programa predeterminado</b> para los PDF (botón de abajo).</p>"
    "<p><b>Microsoft Edge</b>: Configuración › Cookies y permisos del sitio › Documentos PDF › activa "
    "<i>«Abrir siempre los archivos PDF externamente»</i>.</p>"
    "<p><b>Google Chrome</b>: Configuración › Privacidad y seguridad › Configuración de sitios › Configuración "
    "de contenido adicional › Documentos PDF › <i>«Descargar archivos PDF»</i>. Después, en la lista de "
    "descargas, menú ⋮ del PDF › <i>«Abrir siempre archivos de este tipo»</i>.</p>"
    "<p><b>Mozilla Firefox</b>: Ajustes › General › Aplicaciones › «Documento PDF (PDF)» › "
    "<i>«Usar NovoPDF»</i> (o «Usar otra…» y elegir NovoPDF.exe).</p>"
    "<p><b>Safari</b> (Mac): descarga el PDF (clic derecho en el enlace › «Descargar archivo enlazado») y "
    "ábrelo. Para que los PDF se abran siempre con NovoPDF: en el Finder, «Obtener información» de un PDF › "
    "«Abrir con» › NovoPDF › «Cambiar todo».</p>"
)
