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

"""Despertar impresoras de red (Wi-Fi) y vigilar la cola de impresión (Windows).

Muchas impresoras Wi-Fi (Epson, HP, Brother…) se duermen y dejan de contestar; Windows
manda el trabajo, no obtiene respuesta y lo deja «Error» o la marca «Sin conexión»
hasta que se apaga y enciende la impresora. Antes de imprimir:
  1. se averigua la dirección de la impresora a partir de su puerto (TCP/IP estándar,
     WSD, EpsonNet Print u otros) o de su ubicación;
  2. si no contesta, se «despierta»: ping y conexiones a sus puertos habituales (9100,
     631, 80, 515…) repetidas hasta que responde (lo que sirve para sacarla del reposo);
  3. se quita «Usar impresora sin conexión» y se reanuda la cola si estaba en pausa
     (si Windows lo permite sin ser administrador);
  4. después de mandar el trabajo se vigila: si se queda con error, se despierta otra
     vez la impresora y se reintenta.
Todo queda en el registro (datos\\novopdf.log) para poder diagnosticar.
"""
from __future__ import annotations

import ipaddress
import logging
import re
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field

log = logging.getLogger("novopdf.impresion")

IS_WINDOWS = sys.platform.startswith("win")
WAKE_PORTS = (9100, 631, 80, 443, 515, 8080, 5357)

# Estados (win32print)
PRINTER_STATUS = {
    0x1: "en pausa", 0x2: "con error", 0x4: "borrando trabajos", 0x8: "atasco de papel",
    0x10: "sin papel", 0x20: "alimentación manual", 0x40: "problema con el papel", 0x80: "sin conexión",
    0x200: "ocupada", 0x400: "imprimiendo", 0x1000: "sin tóner/tinta", 0x4000: "esperando",
    0x10000: "calentando", 0x40000: "poca tinta o tóner", 0x80000: "puerta abierta",
    0x100000: "requiere intervención", 0x400000: "en reposo (ahorro de energía)",
    0x1000000: "en reposo", 0x2000000: "error de servidor",
}
ATTR_WORK_OFFLINE = 0x400
JOB_STATUS_PAUSED, JOB_STATUS_ERROR, JOB_STATUS_OFFLINE = 0x1, 0x2, 0x20
JOB_STATUS_PAPEROUT, JOB_STATUS_BLOCKED, JOB_STATUS_USER_INTERVENTION = 0x40, 0x200, 0x400
JOB_STATUS_PRINTED, JOB_STATUS_COMPLETE, JOB_STATUS_DELETED = 0x80, 0x1000, 0x100
JOB_BAD = JOB_STATUS_ERROR | JOB_STATUS_OFFLINE | JOB_STATUS_PAPEROUT | JOB_STATUS_BLOCKED | JOB_STATUS_USER_INTERVENTION
JOB_CONTROL_RESTART = 4
PRINTER_CONTROL_RESUME = 2


@dataclass
class PrinterState:
    name: str
    port: str = ""
    driver: str = ""
    kind: str = ""                 # tcp, wsd, epson, usb, local, virtual, unknown
    host: str = ""                 # IP o nombre de la impresora en la red
    status: int = 0
    attributes: int = 0
    jobs: list = field(default_factory=list)      # [(id, documento, estado, usuario)]
    network: bool = False

    @property
    def offline_flag(self) -> bool:
        return bool(self.attributes & ATTR_WORK_OFFLINE)

    @property
    def paused(self) -> bool:
        return bool(self.status & 0x1)

    def status_text(self) -> str:
        parts = [txt for bit, txt in PRINTER_STATUS.items() if self.status & bit]
        if self.offline_flag:
            parts.append("«usar sin conexión» activado")
        return ", ".join(parts) or "preparada"

    @property
    def bad_jobs(self) -> list:
        return [j for j in self.jobs if j[2] & JOB_BAD]


# ====================================================================== dirección de la impresora
_IP = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d{1,3}){3})(?![\d.])")
_URL_HOST = re.compile(r"(?i)\b(?:https?|ipp|ipps|lpd|socket)://\[?([A-Za-z0-9_.:-]+?)\]?(?::\d+)?(?:/|$)")


def host_from_text(text: str) -> str:
    """IP o nombre que aparece en un nombre de puerto, una URL o una ubicación."""
    if not text:
        return ""
    m = _URL_HOST.search(text)
    if m:
        return m.group(1)
    for ip in _IP.findall(text):
        try:
            a = ipaddress.ip_address(ip)
            if not (a.is_loopback or a.is_unspecified or a.is_multicast):
                return ip
        except ValueError:
            continue
    return ""


def port_kind(port: str, driver: str = "") -> str:
    p = (port or "").upper()
    d = (driver or "").lower()
    if p.startswith("WSD"):
        return "wsd"
    if p.startswith(("USB", "DOT4", "LPT", "COM")):
        return "usb"
    if p.startswith(("PORTPROMPT", "FILE:", "NUL", "XPSPORT", "\\\\.\\PIPE")) or "print to pdf" in d \
            or "xps" in d or "onenote" in d:
        return "virtual"
    if p.startswith("EP") or "epson" in p.lower() and ":" in p:
        return "epson"
    if host_from_text(port) or p.startswith("IP_"):
        return "tcp"
    if p.startswith("\\\\"):
        return "shared"
    return "unknown"


def _reg_values(root, path, depth=2) -> list[str]:
    """Todos los textos de una clave del registro (y sus subclaves)."""
    import winreg
    out = []
    try:
        with winreg.OpenKey(root, path) as k:
            i = 0
            while True:
                try:
                    _, v, _ = winreg.EnumValue(k, i)
                except OSError:
                    break
                if isinstance(v, str):
                    out.append(v)
                elif isinstance(v, list):
                    out.extend(x for x in v if isinstance(x, str))
                i += 1
            if depth > 0:
                j = 0
                while True:
                    try:
                        sub = winreg.EnumKey(k, j)
                    except OSError:
                        break
                    out.extend(_reg_values(root, path + "\\" + sub, depth - 1))
                    j += 1
    except OSError:
        pass
    return out


def _monitor_port_texts(port: str) -> list[str]:
    """Datos que guarda el monitor del puerto (TCP/IP estándar, EpsonNet, WSD…)."""
    import winreg
    base = r"SYSTEM\CurrentControlSet\Control\Print\Monitors"
    out = []
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as k:
            i = 0
            while True:
                try:
                    mon = winreg.EnumKey(k, i)
                except OSError:
                    break
                i += 1
                out.extend(_reg_values(winreg.HKEY_LOCAL_MACHINE, f"{base}\\{mon}\\Ports\\{port}", 1))
    except OSError:
        pass
    return out


def _wsd_texts(printer: str) -> list[str]:
    """Las impresoras WSD guardan su URL (LocationInformation) en el árbol de dispositivos."""
    import winreg
    out = []
    norm = re.sub(r"[^a-z0-9]", "", printer.lower())
    for base in (r"SYSTEM\CurrentControlSet\Enum\SWD\DAFWSDProvider", r"SYSTEM\CurrentControlSet\Enum\SWD\PRINTENUM"):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as k:
                i = 0
                while True:
                    try:
                        sub = winreg.EnumKey(k, i)
                    except OSError:
                        break
                    i += 1
                    vals = {}
                    try:
                        with winreg.OpenKey(k, sub) as s:
                            for name in ("FriendlyName", "LocationInformation", "DeviceDesc"):
                                try:
                                    vals[name] = str(winreg.QueryValueEx(s, name)[0])
                                except OSError:
                                    pass
                    except OSError:
                        continue
                    fn = re.sub(r"[^a-z0-9]", "", (vals.get("FriendlyName", "") + vals.get("DeviceDesc", "")).lower())
                    if fn and (fn in norm or norm in fn or fn[:12] == norm[:12]):
                        out.append(vals.get("LocationInformation", ""))
        except OSError:
            continue
    return out


def printer_state(name: str) -> PrinterState:
    st = PrinterState(name=name)
    if not IS_WINDOWS:
        return st
    import win32print
    h = win32print.OpenPrinter(name)
    try:
        info = win32print.GetPrinter(h, 2)
        st.port = info.get("pPortName") or ""
        st.driver = info.get("pDriverName") or ""
        st.status = int(info.get("Status") or 0)
        st.attributes = int(info.get("Attributes") or 0)
        location = (info.get("pLocation") or "") + " " + (info.get("pComment") or "")
        try:
            for j in win32print.EnumJobs(h, 0, 50, 1):
                st.jobs.append((j["JobId"], j.get("pDocument") or "", int(j.get("Status") or 0), j.get("pUserName") or ""))
        except Exception:
            pass
    finally:
        win32print.ClosePrinter(h)
    st.kind = port_kind(st.port, st.driver)
    port0 = st.port.split(",")[0].strip()
    texts = [port0]
    try:
        texts += _monitor_port_texts(port0)
        if st.kind == "wsd" or not host_from_text(" ".join(texts)):
            texts += _wsd_texts(name)
    except Exception as e:  # noqa
        log.info("No se pudo leer el registro del puerto %s: %s", port0, e)
    texts.append(location)
    for t in texts:
        h_ = host_from_text(t)
        if h_:
            st.host = h_
            break
    if not st.host and st.kind == "tcp":
        st.host = port0[3:] if port0.upper().startswith("IP_") else port0
    st.network = bool(st.host) or st.kind in ("wsd", "epson", "tcp")
    return st


# ====================================================================== despertar
def reachable(host: str, ports=WAKE_PORTS, timeout: float = 1.0) -> int:
    """Primer puerto que contesta (0 si ninguno)."""
    for p in ports:
        try:
            with socket.create_connection((host, p), timeout=timeout):
                return p
        except OSError:
            continue
    return 0


def _ping(host: str, timeout_ms: int = 800):
    try:
        if IS_WINDOWS:
            subprocess.run(["ping", "-n", "1", "-w", str(timeout_ms), host], capture_output=True,
                           timeout=timeout_ms / 1000 + 2, creationflags=0x08000000)    # sin ventana
        else:
            subprocess.run(["ping", "-c", "1", "-W", "1", host], capture_output=True, timeout=3)
    except Exception:
        pass


def wake(host: str, timeout: float = 45.0, progress=None, cancelled=None, ports=WAKE_PORTS) -> bool:
    """Insiste hasta que la impresora contesta (o se acaba el tiempo). Devuelve si contesta."""
    t0 = time.monotonic()
    n = 0
    while True:
        n += 1
        _ping(host)
        p = reachable(host, ports, timeout=1.2)
        if p:
            log.info("La impresora %s contesta (puerto %d) tras %.1f s y %d intento(s)", host, p,
                     time.monotonic() - t0, n)
            return True
        el = time.monotonic() - t0
        if progress:
            progress(el, timeout)
        if el >= timeout or (cancelled and cancelled()):
            log.warning("La impresora %s no contesta tras %.0f s", host, el)
            return False
        time.sleep(0.6)


# ====================================================================== arreglar la cola
def _open_admin(name):
    import win32print
    for access in (0x000F000C, 0x00000004 | 0x00000008):      # PRINTER_ALL_ACCESS, ADMINISTER|USE
        try:
            return win32print.OpenPrinter(name, {"DesiredAccess": access})
        except Exception:
            continue
    return None


def clear_offline(name: str) -> bool:
    """Quita «Usar impresora sin conexión». Necesita permiso para administrar la impresora
    (lo tiene quien la instaló); si no, devuelve False."""
    if not IS_WINDOWS:
        return False
    import win32print
    h = _open_admin(name)
    if h is None:
        return False
    try:
        info = win32print.GetPrinter(h, 2)
        if not info["Attributes"] & ATTR_WORK_OFFLINE:
            return True
        info["Attributes"] &= ~ATTR_WORK_OFFLINE
        info["pSecurityDescriptor"] = None
        win32print.SetPrinter(h, 2, info, 0)
        log.info("Quitado «usar sin conexión» de %s", name)
        return True
    except Exception as e:  # noqa
        log.info("No se pudo quitar «sin conexión» de %s: %s", name, e)
        return False
    finally:
        win32print.ClosePrinter(h)


def resume(name: str) -> bool:
    if not IS_WINDOWS:
        return False
    import win32print
    h = _open_admin(name)
    if h is None:
        return False
    try:
        win32print.SetPrinter(h, 0, None, PRINTER_CONTROL_RESUME)
        log.info("Cola de %s reanudada", name)
        return True
    except Exception as e:  # noqa
        log.info("No se pudo reanudar %s: %s", name, e)
        return False
    finally:
        win32print.ClosePrinter(h)


def restart_jobs(name: str, job_ids) -> int:
    """Vuelve a mandar trabajos atascados (los propios se pueden sin ser administrador)."""
    if not IS_WINDOWS or not job_ids:
        return 0
    import win32print
    n = 0
    h = win32print.OpenPrinter(name)
    try:
        for jid in job_ids:
            try:
                win32print.SetJob(h, jid, 0, None, JOB_CONTROL_RESTART)
                n += 1
            except Exception as e:  # noqa
                log.info("No se pudo reintentar el trabajo %s: %s", jid, e)
    finally:
        win32print.ClosePrinter(h)
    if n:
        log.info("Reintentados %d trabajo(s) en %s", n, name)
    return n


def prepare(name: str, progress=None, cancelled=None, timeout: float = 45.0) -> tuple[bool, str, PrinterState | None]:
    """Antes de imprimir. Devuelve (seguir, aviso para el usuario, estado)."""
    try:
        st = printer_state(name)
    except Exception as e:  # noqa
        log.info("No se pudo consultar la impresora %s: %s", name, e)
        return True, "", None
    log.info("Impresora «%s»: puerto %s (%s), dirección %s, estado %s, %d trabajo(s) en cola",
             name, st.port or "?", st.kind or "?", st.host or "desconocida", st.status_text(), len(st.jobs))
    notes = []
    if st.offline_flag and clear_offline(name):
        notes.append("se ha quitado «usar impresora sin conexión»")
    if st.paused and resume(name):
        notes.append("se ha reanudado la cola, que estaba en pausa")
    if st.host and st.kind != "virtual":
        if not reachable(st.host, timeout=0.8):
            log.info("La impresora %s (%s) no contesta: se intenta despertar", name, st.host)
            ok = wake(st.host, timeout=timeout, progress=progress, cancelled=cancelled)
            if cancelled and cancelled():
                return False, "", st
            if not ok:
                return True, (f"La impresora «{name}» no contesta en la red ({st.host}). Comprueba que está "
                              "encendida y conectada a la Wi-Fi."), st
            notes.append("se ha despertado la impresora")
    if st.bad_jobs:
        own = [j[0] for j in st.bad_jobs]
        if restart_jobs(name, own):
            notes.append(f"se han vuelto a mandar {len(own)} trabajo(s) que estaban atascados")
    return True, ("; ".join(notes).capitalize() + ".") if notes else "", st


def job_problem(name: str, doc_name: str) -> tuple[int, int] | None:
    """(id, estado) del trabajo de NovoPDF si se ha quedado con error; None si va bien o ya salió."""
    try:
        st = printer_state(name)
    except Exception:
        return None
    for jid, doc, status, _ in st.jobs:
        if doc == doc_name and status & JOB_BAD:
            return jid, status
    return None


def job_pending(name: str, doc_name: str) -> bool:
    try:
        st = printer_state(name)
    except Exception:
        return False
    return any(doc == doc_name for _, doc, _, _ in st.jobs)
