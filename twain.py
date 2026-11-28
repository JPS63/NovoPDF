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

"""Escaneo con controladores TWAIN (Windows).

Muchos escáneres de oficina, sobre todo los multifunción en red (p. ej. Ricoh Aficio con
«Network TWAIN»), solo tienen controlador TWAIN de 32 bits y no aparecen en WIA. Un proceso
de 64 bits como NovoPDF no puede cargar un controlador de 32 bits, así que el escaneo lo
hace un ayudante pequeño (bin/novopdf_twain32.exe; y novopdf_twain64.exe para los
controladores TWAIN de 64 bits), que guarda cada página como BMP y avisa por su salida.
Código del ayudante: build/twain/novopdf_twain.c.

Pruebas en Linux: NOVOPDF_TWAIN_RUNNER=wine ejecuta los ayudantes con Wine.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass

log = logging.getLogger("novopdf.escaner")

BIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")
HELPERS = (("32", "novopdf_twain32.exe"), ("64", "novopdf_twain64.exe"))
RUNNER = os.environ.get("NOVOPDF_TWAIN_RUNNER", "")       # «wine» en las pruebas

# Códigos de condición TWAIN (TWCC_*) -> mensaje
TWCC = {
    2: "El escáner no tiene memoria suficiente para esta resolución. Prueba con una resolución menor.",
    3: "No se encuentra el escáner. Comprueba que el controlador está instalado.",
    4: "El escáner está ocupado con otro programa. Ciérralo y vuelve a intentarlo.",
    5: "El escáner ha informado de un error. Comprueba la pantalla del escáner.",
    16: "El escáner ha rechazado la operación.",
    20: "Hay un atasco de papel en el escáner.",
    21: "El escáner ha cogido dos hojas a la vez.",
    23: "El escáner no responde. Comprueba que está encendido y conectado a la red.",
    24: "Hay una tapa o puerta del escáner abierta.",
    29: "No hay papel en el alimentador.",
}
NO_MEDIA = 29
STAGES = {
    "nodsm": "No está instalado el componente TWAIN de Windows (twain_32.dll).",
    "opendsm": "No se pudo iniciar el sistema TWAIN de Windows.",
    "opends": "No se pudo conectar con el escáner.",
    "enable": "El escáner no pudo empezar a escanear.",
    "xfer": "El escáner no pudo entregar la página.",
    "save": "No se pudo guardar la página escaneada en la carpeta temporal.",
}


class TwainError(Exception):
    def __init__(self, msg, code=0):
        super().__init__(msg)
        self.code = code


@dataclass
class Source:
    bits: str
    name: str
    manufacturer: str = ""

    @property
    def id(self) -> str:
        return f"twain{self.bits}:{self.name}"


def helper(bits: str) -> str | None:
    for b, name in HELPERS:
        if b == bits:
            p = os.path.join(BIN, name)
            return p if os.path.isfile(p) else None
    return None


def available() -> bool:
    if not (sys.platform.startswith("win") or RUNNER):
        return False
    return any(helper(b) for b, _ in HELPERS)


def _cmd(exe: str, args: list[str]) -> list[str]:
    return ([RUNNER] if RUNNER else []) + [exe] + args


def _to_helper(path: str) -> str:
    if RUNNER and not sys.platform.startswith("win"):
        return "Z:" + os.path.abspath(path).replace("/", "\\")
    return path


def _from_helper(path: str) -> str:
    if RUNNER and not sys.platform.startswith("win") and path[:2].upper() == "Z:":
        return path[2:].replace("\\", "/")
    return path


def _decode(b: bytes) -> str:
    for enc in (("mbcs",) if sys.platform.startswith("win") else ()) + ("utf-8", "cp1252"):
        try:
            return b.decode(enc)
        except Exception:
            continue
    return b.decode("latin-1", "replace")


def _popen(args, **kw):
    flags = 0
    if sys.platform.startswith("win"):
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                            creationflags=flags, **kw)


def list_sources(timeout: float = 30.0) -> list[Source]:
    """Escáneres TWAIN instalados (de 32 y de 64 bits)."""
    out: list[Source] = []
    seen = set()
    for bits, _name in HELPERS:
        exe = helper(bits)
        if not exe:
            continue
        try:
            p = _popen(_cmd(exe, ["list"]))
            data, _ = p.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            p.kill()
            log.warning("TWAIN %s bits: la lista de escáneres no respondió", bits)
            continue
        except Exception as e:  # noqa
            log.info("TWAIN %s bits no disponible: %s", bits, e)
            continue
        for line in _decode(data).splitlines():
            f = line.rstrip("\r").split("\t")
            if f[0] == "SOURCE" and len(f) >= 2 and f[1].strip():
                name = f[1].strip()
                # los «WIA-…» son los mismos escáneres que ya salen por WIA
                if name.upper().startswith("WIA-") or name in seen:
                    continue
                seen.add(name)
                out.append(Source(bits, name, f[2].strip() if len(f) > 2 else ""))
            elif f[0] == "ERROR":
                log.info("TWAIN %s bits: %s", bits, line)
    log.info("Escáneres TWAIN: %s", [(s.bits, s.name) for s in out])
    return out


def parse_id(device_id: str) -> tuple[str, str] | None:
    if device_id.startswith("twain") and ":" in device_id:
        head, name = device_id.split(":", 1)
        return head[5:] or "32", name
    return None


def scan(device_id: str, source: str, mode: str, dpi: int, show_ui: bool, on_page, cancelled=None) -> int:
    """Escanea con el controlador TWAIN. on_page(datos, ppp) por cada página. Devuelve el nº de páginas."""
    pid = parse_id(device_id)
    if pid is None:
        raise TwainError("Escáner TWAIN no válido.")
    bits, name = pid
    exe = helper(bits)
    if not exe:
        raise TwainError("Falta el componente de escaneo TWAIN de NovoPDF (novopdf_twain%s.exe). "
                         "Vuelve a instalar la aplicación." % bits)
    tmp = tempfile.mkdtemp(prefix="novopdf_twain_")
    cancel_file = os.path.join(tmp, "cancelar")
    args = ["scan", "--source", name, "--out", _to_helper(tmp), "--cancel", _to_helper(cancel_file),
            "--mode", mode, "--dpi", str(int(dpi))]
    if source in ("feeder", "duplex"):
        args.append("--feeder")
    if source == "duplex":
        args.append("--duplex")
    if show_ui:
        args.append("--ui")
    log.info("TWAIN %s bits: escanear con «%s» (%s, %s, %d ppp, ventana del controlador: %s)",
             bits, name, source, mode, dpi, show_ui)
    try:
        proc = _popen(_cmd(exe, args))
    except OSError as e:
        shutil.rmtree(tmp, ignore_errors=True)
        raise TwainError(f"No se pudo iniciar el escaneo TWAIN: {e}")
    if sys.platform.startswith("win"):
        try:  # que la ventana del controlador pueda ponerse delante
            import ctypes
            ctypes.windll.user32.AllowSetForegroundWindow(proc.pid)
        except Exception:
            pass
    stop = threading.Event()

    def watch():
        asked = None
        while not stop.wait(0.3):
            if asked is None and cancelled is not None and cancelled():
                asked = time.time()
                try:
                    open(cancel_file, "w").close()
                except OSError:
                    pass
            if asked is not None and time.time() - asked > 20 and proc.poll() is None:
                log.warning("TWAIN: el controlador no atiende la cancelación; se cierra")
                proc.kill()
                return

    threading.Thread(target=watch, daemon=True, name="NovoPDF-twain").start()
    count, error, finished = 0, None, False
    try:
        for raw in proc.stdout:
            f = _decode(raw).rstrip("\r\n").split("\t")
            if f[0] == "PAGE" and len(f) >= 2:
                path = _from_helper(f[1])
                try:
                    with open(path, "rb") as fh:
                        data = fh.read()
                    os.remove(path)
                except OSError as e:
                    error = TwainError(f"No se pudo leer la página escaneada: {e}")
                    continue
                dpi_page = int(f[2]) if len(f) > 2 and f[2].isdigit() else dpi
                count += 1
                on_page(data, dpi_page)
                if cancelled is not None and cancelled() and not os.path.exists(cancel_file):
                    try:
                        open(cancel_file, "w").close()      # avisar ya, sin esperar al vigilante
                    except OSError:
                        pass
            elif f[0] in ("DONE", "CANCEL"):
                finished = True
            elif f[0] == "ERROR":
                code = int(f[1]) if len(f) > 1 and f[1].isdigit() else 0
                stage = f[2] if len(f) > 2 else ""
                if stage == "opends" and code not in (4, 23, 24):
                    # el código lo da el gestor TWAIN, no el escáner: mejor el mensaje general
                    msg = (STAGES["opends"] + " Comprueba que está encendido y, si es un escáner en red, "
                           "que este equipo lo ve (por ejemplo, que el escáner tiene la misma dirección "
                           "de red que se configuró en su controlador).")
                else:
                    msg = TWCC.get(code) or STAGES.get(stage) or "Error del escáner."
                log.warning("TWAIN: %s (código %s, %s)", msg, code, stage)
                error = TwainError(msg, code)
        proc.wait(timeout=30)
    finally:
        stop.set()
        if proc.poll() is None:
            proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)
    if error is not None and not (error.code == NO_MEDIA and count):
        raise error            # las páginas ya entregadas se conservan (on_page)
    if not finished and not count and not (cancelled and cancelled()):
        raise TwainError("El escaneo TWAIN terminó sin entregar ninguna página "
                         f"(código de salida {proc.returncode}).")
    return count
