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

"""1.5.0: escáneres TWAIN de 32 bits mediante el ayudante novopdf_twain32.exe.

Se ejecuta con Wine y un escáner TWAIN de prueba (build/twain/test/fake_ds.c), instalado en el
prefijo de Wine como «gphoto2.ds» (Wine solo busca fuentes con ese nombre o sane.ds):
  xvfb-run -a env WINEPREFIX=/tmp/claude-0/wine32 WINEARCH=win32 WINEDLLOVERRIDES=gphoto2.ds=n \\
      NOVOPDF_TWAIN_RUNNER=wine python3 tests/ui_twain.py
"""
import os, sys, shutil, time, threading
os.environ.setdefault("WINEDEBUG", "-all")
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["NOVOPDF_HOME"] = "/tmp/claude-0/tw"
shutil.rmtree("/tmp/claude-0/tw", ignore_errors=True); os.makedirs("/tmp/claude-0/tw", exist_ok=True)
sys.path.insert(0, "/home/claude/novopdf/src")
PREFIX = os.environ.get("WINEPREFIX", "/tmp/claude-0/wine32")
DS = os.path.join(PREFIX, "drive_c/windows/twain_32/gphoto2.ds")
shutil.copy("/home/claude/novopdf/build/twain/test/NovoFake.ds", DS)
LOG = os.path.join(PREFIX, "drive_c/fake.log")
os.environ["FAKEDS_LOG"] = r"C:\fake.log"

import pymupdf
from novopdf.core import scanner, twain
res = []
ok = lambda c, m: (res.append(bool(c)), print(("OK  " if c else "FAIL"), m, flush=True))

def caps():
    try:
        return open(LOG).read()
    except OSError:
        return ""

def reset(**env):
    for k in ("FAKEDS_PAGES", "FAKEDS_FAIL"):
        os.environ.pop(k, None)
    os.environ.update(env)
    if os.path.exists(LOG):
        os.remove(LOG)

ok(twain.available() and scanner.available(), "ayudante TWAIN disponible")
devs = scanner.list_devices()
tw = [d for d in devs if d.kind == "twain"]
ok(len(tw) == 1 and tw[0].name == "Escaner de prueba TWAIN" and tw[0].id == "twain32:Escaner de prueba TWAIN",
   f"el escáner TWAIN de 32 bits aparece en la lista: {[(d.id, d.name) for d in devs]}")
dev = tw[0]

# 1) alimentador, grises, 150 ppp, sin la ventana del controlador
reset()
pages = []
n = scanner.scan(scanner.ScanSettings(dev.id, "feeder", "gray", 150, show_ui=False), pages.append)
ok(n == 3 and len(pages) == 3, f"alimentador: 3 páginas ({n})")
c = caps()
ok("cap 0101=1" in c and "cap 1118=150" in c and "cap 1002=1" in c and "enable ui=0" in c,
   "se piden grises, 150 ppp, alimentador y sin ventana")
ok("disable" in c and "close" in c, "se cierra el escáner al terminar")
data, removed = scanner.images_to_pdf(pages, "gray", remove_blank=False)
d = pymupdf.open(stream=data, filetype="pdf")
ok(d.page_count == 3 and abs(d[0].rect.width - 8.5 * 72) < 2, f"PDF con 3 páginas del tamaño real ({d[0].rect})")

# 2) cristal, color, con la ventana del controlador
reset()
pages = []
n = scanner.scan(scanner.ScanSettings(dev.id, "flatbed", "color", 100, show_ui=True), pages.append)
from PIL import Image
import io
im = Image.open(io.BytesIO(pages[0].data)) if pages else None
ok(n == 1 and im is not None and im.mode == "RGB" and pages[0].dpi == 100, f"cristal en color: 1 página RGB a 100 ppp ({n})")
ok("enable ui=1" in caps() and "cap 1002=0" in caps(), "con la ventana del controlador y sin alimentador")

# 3) doble cara, blanco y negro
reset(FAKEDS_PAGES="2")
pages = []
n = scanner.scan(scanner.ScanSettings(dev.id, "duplex", "bw", 100, show_ui=False), pages.append)
ok(n == 4 and "cap 1013=1" in caps() and "cap 0101=0" in caps(), f"doble cara en blanco y negro: 4 caras ({n})")
data, _ = scanner.images_to_pdf(pages, "bw")
ok(pymupdf.open(stream=data, filetype="pdf").page_count == 4, "PDF en blanco y negro")

# 4) escáner apagado
reset(FAKEDS_FAIL="open")
try:
    scanner.scan(scanner.ScanSettings(dev.id, "flatbed", "gray", 100, show_ui=False), lambda p: None)
    ok(False, "escáner apagado: debería dar error")
except scanner.ScannerError as e:
    ok("No se pudo conectar" in str(e) and "encendido" in str(e), f"escáner apagado: «{e}»")

# 5) atasco en la 2.ª hoja: error, pero la 1.ª página ya está entregada
reset(FAKEDS_FAIL="xfer")
pages = []
try:
    scanner.scan(scanner.ScanSettings(dev.id, "feeder", "gray", 100, show_ui=False), pages.append)
    ok(False, "atasco: debería dar error")
except scanner.ScannerError as e:
    ok(len(pages) == 1 and "atasco" in str(e), f"atasco: error «{e}» y se conserva la página ya escaneada ({len(pages)})")
ok("reset" in caps(), "tras el error se vacía la cola de hojas pendientes")

# 6) cancelar desde NovoPDF durante el escaneo
reset(FAKEDS_PAGES="40", FAKEDS_DELAY="150")
pages = []
flag = {"c": False}
def on_page(p):
    pages.append(p)
    flag["c"] = True          # cancelar tras la primera página
n = scanner.scan(scanner.ScanSettings(dev.id, "feeder", "gray", 100, show_ui=False), on_page, cancelled=lambda: flag["c"])
ok(1 <= n < 40, f"cancelar: se detiene ({n} de 40 páginas)")

# 7) cancelado en la ventana del controlador: sin error ni páginas
reset(FAKEDS_FAIL="cancel")
n = scanner.scan(scanner.ScanSettings(dev.id, "flatbed", "gray", 100, show_ui=True), lambda p: None)
ok(n == 0, "cancelar en la ventana del escáner: 0 páginas, sin error")

# 8) ventana de opciones: casilla de la ventana del controlador solo para TWAIN
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)
from PySide6.QtCore import QSettings
from novopdf.ui import dialogs
st = QSettings("/tmp/claude-0/tw/s.ini", QSettings.IniFormat)
dl = dialogs.ScanDialog(None, st, False)
k = dl.device.findData(dev.id)
dl.device.setCurrentIndex(k)
ok(k >= 0 and not dl.twain_ui.isHidden() and dl.r_feed.isEnabled() and dl.r_dup.isEnabled(),
   "ventana de escaneo: el TWAIN se puede elegir, con alimentador, doble cara y «Mostrar la ventana del escáner»")
dl.twain_ui.setChecked(False)
ok(dl.validate() and dl.options.show_ui is False and dl.options.device_id == dev.id, "las opciones llegan al escaneo")

print(f"\n{sum(res)}/{len(res)} correctas")
sys.exit(0 if all(res) else 1)
