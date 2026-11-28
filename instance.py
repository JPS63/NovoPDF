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

"""Una sola ventana de NovoPDF.

Si NovoPDF ya está abierto y se abre otro PDF (doble clic en el Explorador, «Abrir con»,
arrastrar al icono), el programa nuevo pasa los archivos al que ya está abierto, que los
muestra en pestañas, y termina. Varias selecciones abiertas a la vez desde el Explorador
lanzan varios procesos casi a la vez: el primero se queda como «servidor» y el resto le
envían sus archivos.

Comunicación local con multiprocessing.connection (biblioteca estándar): tubería con nombre
en Windows, socket de dominio Unix en Linux. En macOS no hace falta: el sistema ya envía
los archivos a la aplicación abierta (evento FileOpen).
"""
from __future__ import annotations

import getpass
import hashlib
import logging
import os
import sys
import tempfile
import threading
import time

log = logging.getLogger("novopdf.instancia")

ENABLED = not sys.platform.startswith("darwin") and os.environ.get("NOVOPDF_NUEVA_VENTANA", "") != "1"


def _tag() -> str:
    try:
        user = getpass.getuser()
    except Exception:
        user = os.environ.get("USERNAME", "") or os.environ.get("USER", "")
    home = os.path.expanduser("~")
    sess = os.environ.get("NOVOPDF_INSTANCE_TAG", "")      # para pruebas
    return hashlib.sha256(f"NovoPDF|{user}|{home}|{sess}".encode("utf-8")).hexdigest()


def _address():
    t = _tag()
    if sys.platform.startswith("win"):
        return rf"\\.\pipe\NovoPDF-{t[:20]}", "AF_PIPE"
    return os.path.join(tempfile.gettempdir(), f"novopdf-{t[:20]}.sock"), "AF_UNIX"


def _authkey() -> bytes:
    return hashlib.sha256(("clave|" + _tag()).encode("utf-8")).digest()


def _allow_foreground():
    """Deja que la ventana ya abierta se ponga delante (Windows lo impide si no)."""
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.user32.AllowSetForegroundWindow(-1)    # ASFW_ANY
        except Exception:
            pass


def send_to_running(paths: list[str], timeout: float = 3.0) -> bool:
    """Envía los archivos a la ventana ya abierta. True si la había y los ha recibido."""
    from multiprocessing.connection import Client
    addr, family = _address()
    if family == "AF_UNIX" and not os.path.exists(addr):
        return False
    try:
        conn = Client(addr, family=family, authkey=_authkey())
    except Exception:
        return False
    try:
        _allow_foreground()
        conn.send({"open": list(paths)})
        if conn.poll(timeout):
            return conn.recv() == "ok"
        return False
    except Exception as e:  # noqa
        log.info("No se pudo pasar los archivos a la ventana abierta: %s", e)
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass


class Server:
    """Escucha a los procesos nuevos y entrega sus archivos con on_open(lista) (en otro hilo)."""

    def __init__(self, listener):
        self.listener = listener
        self.on_open = None
        self.pending: list[list[str]] = []
        self._stop = False
        self.thread = threading.Thread(target=self._run, name="NovoPDF-instancia", daemon=True)
        self.thread.start()

    def _run(self):
        while not self._stop:
            try:
                conn = self.listener.accept()
            except Exception as e:  # noqa
                if self._stop:
                    return
                log.info("Conexión rechazada: %s", e)
                time.sleep(0.05)
                continue
            try:
                if conn.poll(5):
                    msg = conn.recv()
                    paths = [str(p) for p in (msg or {}).get("open", [])] if isinstance(msg, dict) else []
                    if self.on_open is not None:
                        self.on_open(paths)
                    else:
                        self.pending.append(paths)
                    conn.send("ok")
            except Exception as e:  # noqa
                log.info("Mensaje de otra ventana no válido: %s", e)
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

    def close(self):
        self._stop = True
        try:
            self.listener.close()
        except Exception:
            pass


def claim(paths: list[str]):
    """Devuelve («forwarded», None) si otra ventana se ha quedado los archivos, o
    («server», Server) si esta es la ventana principal (o («alone», None) si no se puede)."""
    if not ENABLED:
        return "alone", None
    from multiprocessing.connection import Listener
    addr, family = _address()
    for attempt in range(6):
        if send_to_running(paths):
            return "forwarded", None
        try:
            if family == "AF_UNIX" and os.path.exists(addr):
                os.unlink(addr)          # quedó de una ejecución anterior que no terminó bien
            listener = Listener(addr, family=family, authkey=_authkey())
            return "server", Server(listener)
        except OSError:
            # otro proceso acaba de crearla: reintentar como cliente
            time.sleep(0.15 + 0.1 * attempt)
        except Exception as e:  # noqa
            log.info("Sin ventana única: %s", e)
            return "alone", None
    return "alone", None
