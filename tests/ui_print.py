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

"""1.3.0: impresión (diálogo, páginas, copias, pares/impares, gris, giro, permisos, cancelar)."""
import os, sys, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["NOVOPDF_HOME"] = "/tmp/claude-0/pr"
shutil.rmtree("/tmp/claude-0/pr", ignore_errors=True)
os.makedirs("/tmp/claude-0/pr", exist_ok=True); os.makedirs("/tmp/claude-0/shots", exist_ok=True)
sys.path.insert(0, "/home/claude/novopdf/src")
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtPrintSupport import QPrinter, QPrinterInfo
app = QApplication(sys.argv); app.setStyle("Fusion")
from novopdf.ui import theme, dialogs
app.setStyleSheet(theme.build_qss())
from novopdf.ui import mainwindow as mw, printdialog as pd
from novopdf.core import printing
import pymupdf
res = []
ok = lambda c, m: (res.append(bool(c)), print(("OK  " if c else "FAIL"), m))
msgs = []
QMessageBox.information = staticmethod(lambda *a, **k: msgs.append(("info", a[2])))
QMessageBox.warning = staticmethod(lambda *a, **k: msgs.append(("warn", a[2])))
QMessageBox.critical = staticmethod(lambda *a, **k: msgs.append(("error", a[2])))

# --- impresoras simuladas (en el contenedor no hay CUPS)
pd.QPrinterInfo.availablePrinterNames = staticmethod(lambda: ["Oficina color", "Planta 2 BN"])
pd.QPrinterInfo.defaultPrinterName = staticmethod(lambda: "Oficina color")

# --- documento de prueba: A4 vertical, A4 apaisada, A5, A3, A4 con color
src = "/tmp/claude-0/pr/muestra.pdf"
d = pymupdf.open()
for i, (w_, h_) in enumerate([(595, 842), (842, 595), (420, 595), (842, 1191), (595, 842)]):
    p = d.new_page(width=w_, height=h_)
    p.insert_text((50, 80), f"Pagina {i + 1}", fontsize=28)
    p.draw_rect(p.rect + (6, 6, -6, -6), color=(0, 0, 1), width=3)
    if i == 4:
        p.draw_rect(pymupdf.Rect(100, 200, 400, 500), color=(1, 0, 0), fill=(1, 0, 0))
d.save(src)

OUT = "/tmp/claude-0/pr/salida.pdf"
plan = {"setup": None, "accept": True, "shot": None}
seen = {}

def fake_exec(self):
    seen["dialog"] = self
    self.printer.setOutputFormat(QPrinter.PdfFormat)
    self.printer.setOutputFileName(OUT)
    if plan["setup"]:
        plan["setup"](self)
    self._sync()
    if plan["shot"]:
        self.resize(900, 640); self.show(); app.processEvents(); self._sync(); app.processEvents()
        self.grab().save(plan["shot"]); self.hide()
    if not plan["accept"]:
        return False
    self._try_accept()
    return self.result is not None
pd.PrintDialog.exec = fake_exec

def run(setup=None, pages=None, shot=None):
    if os.path.exists(OUT):
        os.remove(OUT)
    plan.update(setup=setup, shot=shot)
    w.print_document(pages)
    app.processEvents()
    return pymupdf.open(OUT) if os.path.exists(OUT) else None

def labels(o):
    """Texto «Pagina N» de cada hoja impresa (vía OCR no: comparamos con el render original)."""
    out = []
    for pg in o:
        info = pg.get_image_info()
        if not info:
            out.append(None)
            continue
        # 1.5.0: cada página va en franjas horizontales; se juntan
        x0 = min(i["bbox"][0] for i in info); y0 = min(i["bbox"][1] for i in info)
        x1 = max(i["bbox"][2] for i in info); y1 = max(i["bbox"][3] for i in info)
        out.append({"bbox": (x0, y0, x1, y1), "width": info[0]["width"],
                    "height": sum(i["height"] for i in info), "bands": len(info)})
    return out

w = mw.MainWindow(); w.resize(1300, 850); w.show()
ok(w.b_print.isEnabled() is False, "botón Imprimir desactivado sin documento")
w.open_file(src); app.processEvents()
ok(w.b_print.isEnabled(), "botón Imprimir activo con documento")
ok(any(isinstance(s, QShortcut) and s.key() == QKeySequence(QKeySequence.Print) for s in w.findChildren(QShortcut)),
   "atajo Ctrl+P")

# 1) todas las páginas, ajuste por defecto (reducir solo las grandes), giro automático
o = run(shot="/tmp/claude-0/shots/imprimir_dialogo.png")
dlg = seen["dialog"]
ok(o is not None and o.page_count == 5, f"todas: 5 hojas (hay {o.page_count if o else 0})")
ok(all((round(p.rect.width), round(p.rect.height)) == (595, 842) for p in o), "todas las hojas en A4 vertical")
inf = labels(o)
ok(abs(inf[0]["bbox"][2] - inf[0]["bbox"][0] - 595) < 1, "A4 a tamaño real en A4")
ok(inf[0]["bands"] > 1, f"la página se envía en franjas ({inf[0]['bands']})")
ok(inf[1]["width"] < inf[1]["height"], "página apaisada girada para aprovechar la hoja")
b = inf[2]["bbox"]
ok(abs((b[2] - b[0]) - 420) < 1 and abs((b[0] + b[2]) / 2 - 297.5) < 1, "A5 sin ampliar y centrada")
b = inf[3]["bbox"]
ok(abs((b[3] - b[1]) - 842) < 1 and (b[2] - b[0]) < 596, "A3 reducida para caber en A4")
ok("Enviado a" in w.msg_label.text(), f"aviso en la barra de estado: {w.msg_label.text()!r}")
# contenido igual al documento
ref = d[4].get_pixmap(dpi=40)
got = o[4].get_pixmap(dpi=40)
diff = sum(abs(a - c) for a, c in zip(ref.samples, got.samples)) / len(ref.samples)
ok(ref.width == got.width and diff < 6, f"la hoja impresa coincide con la página (dif. media {diff:.2f})")
ok(dlg.printer_combo.currentData() == "Oficina color", "impresora predeterminada elegida")
ok(dlg.printer.docName() == "muestra.pdf", "nombre del trabajo en la cola de impresión")

# 2) intervalo + copias intercaladas (la impresora PDF no hace copias: las hace NovoPDF)
def s2(dl):
    dl.rng.setText("1, 3"); dl.r_rng.setChecked(True); dl.copies.setValue(2); dl.collate.setChecked(True)
o = run(s2)
ok(o.page_count == 4, "intervalo 1, 3 × 2 copias = 4 hojas")
ok("4 páginas (2 × 2 copias)" in seen["dialog"].summary.text(), f"resumen: {seen['dialog'].summary.text()!r}")
sizes = [round(i["bbox"][2] - i["bbox"][0]) for i in labels(o)]
ok(sizes[0] == sizes[2] and sizes[1] == sizes[3] and sizes[0] != sizes[1], f"copias intercaladas 1,2,1,2 {sizes}")
def s2b(dl):
    dl.rng.setText("1, 3"); dl.r_rng.setChecked(True); dl.copies.setValue(2); dl.collate.setChecked(False)
o = run(s2b)
sizes = [round(i["bbox"][2] - i["bbox"][0]) for i in labels(o)]
ok(sizes[0] == sizes[1] and sizes[2] == sizes[3] and sizes[0] != sizes[2], f"sin intercalar 1,1,2,2 {sizes}")
ok(printing.sheets([0, 1], 2, True) == [0, 1, 0, 1] and printing.sheets([0, 1], 2, False) == [0, 0, 1, 1], "orden de copias")

# 3) solo pares / impares
def s3(dl):
    dl.subset.setCurrentIndex(dl.subset.findData("even"))
o = run(s3)
ok(o.page_count == 2, "solo pares: 2 hojas (págs. 2 y 4)")
def s3b(dl):
    dl.rng.setText("2"); dl.r_rng.setChecked(True); dl.subset.setCurrentIndex(dl.subset.findData("odd"))
plan["accept"] = True
o = run(s3b)
ok(o is None and not seen["dialog"].ok_btn.isEnabled(), "intervalo sin impares: no deja imprimir")
ok("No hay páginas" in seen["dialog"].summary.text(), "explica por qué no hay páginas")

# 4) intervalo mal escrito
def s4(dl):
    dl.rng.setText("1-x"); dl.r_rng.setChecked(True)
o = run(s4)
ok(o is None and "No se entiende" in seen["dialog"].error.text(), "intervalo incorrecto: mensaje claro")

# 5) blanco y negro
def s5(dl):
    dl.r_cur.setChecked(True); dl.color.setCurrentIndex(dl.color.findData("gray"))
w.viewer.go_to(4); app.processEvents()
o = run(s5)
ok(o.page_count == 1, "página actual: 1 hoja")
img = o[0].get_images(full=True)[0]
ok(img[5] in ("DeviceGray", "ICCBased") and pymupdf.Pixmap(o, img[0]).n == 1, f"impresión en escala de grises ({img[5]})")
ok(seen["dialog"].printer.colorMode() == QPrinter.GrayScale, "modo de color de la impresora: gris")

# 6) ajustes recordados
plan["setup"] = None
o = run()
ok(seen["dialog"].color.currentData() == "gray", "recuerda blanco y negro")
def s6(dl):
    dl.color.setCurrentIndex(dl.color.findData("color")); dl.fit.setCurrentIndex(dl.fit.findData("fit"))
    dl.printer_combo.setCurrentIndex(dl.printer_combo.findData("Planta 2 BN"))
    dl.printer.setOutputFormat(QPrinter.PdfFormat); dl.printer.setOutputFileName(OUT)
o = run(s6)
b = labels(o)[2]["bbox"]
ok(abs((b[2] - b[0]) - 595) < 1, "«Ajustar a la hoja» amplía el A5 a A4")
o = run()
ok(seen["dialog"].printer_combo.currentData() == "Planta 2 BN", "recuerda la última impresora")

# 7) menú contextual de miniaturas: imprimir una página
w.thumbs.clearSelection(); w.thumbs.item(3).setSelected(True)
o = run(pages=[3])
ok(o.page_count == 1 and seen["dialog"].rng.text() == "4", "imprimir desde la miniatura (página 4)")
for i in (1, 2):
    w.thumbs.item(i).setSelected(True)
o = run(pages=w.thumbs.selected_pages())
ok(o.page_count == 3 and seen["dialog"].r_sel.isChecked(), "imprimir las miniaturas seleccionadas (3)")

# 8) cancelar a mitad
orig = printing.print_pages
def cancel_at_2(*a, **k):
    prog = k["progress"]
    k["progress"] = lambda i, t: prog(i, t) and i < 2
    return orig(*a, **k)
printing.print_pages = cancel_at_2
w.thumbs.clearSelection()
o = run(lambda dl: dl.r_all.setChecked(True))
printing.print_pages = orig
ok("cancelada" in w.msg_label.text(), "cancelar la impresión")

# 9) cambios sin guardar también se imprimen
w.pdf.doc[0].insert_text((50, 400), "CAMBIO SIN GUARDAR", fontsize=40, color=(1, 0, 0))
w.pdf.modified = True
o = run(lambda dl: (dl.r_cur.setChecked(True), dl.color.setCurrentIndex(0)) and None)
w.viewer.go_to(0); app.processEvents()
o = run(lambda dl: (dl.rng.setText("1"), dl.r_rng.setChecked(True), dl.color.setCurrentIndex(0)) and None)
pix = o[0].get_pixmap(dpi=30)
reds = sum(1 for k in range(0, len(pix.samples), 3) if pix.samples[k] > 180 and pix.samples[k + 1] < 90)
ok(reds > 20, f"se imprime el texto añadido sin guardar ({reds} píxeles rojos)")

# 10) documento con impresión prohibida por el autor
lim = "/tmp/claude-0/pr/limitado.pdf"
d.save(lim, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="jefe", user_pw="",
       permissions=pymupdf.PDF_PERM_ACCESSIBILITY | pymupdf.PDF_PERM_COPY)
w.pdf.modified = False
w.open_file(lim); app.processEvents()
ok(not w.pdf.print_allowed, "detecta que el autor no permite imprimir")
asked = []
dialogs.confirm = lambda *a, **k: (asked.append(a[2]), False)[1]
seen.clear()
o = run()
ok(asked and "no permite imprimirlo" in asked[0] and "dialog" not in seen and o is None,
   "avisa y no abre el diálogo")
dialogs.confirm = lambda *a, **k: True
dialogs.ask_password = lambda *a, **k: "jefe"
o = run()
ok(w.pdf.print_allowed and o is not None and o.page_count == 5, "con la contraseña de permisos sí imprime")
lim2 = "/tmp/claude-0/pr/permitido.pdf"
d.save(lim2, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="jefe", user_pw="",
       permissions=pymupdf.PDF_PERM_PRINT)
w.open_file(lim2); app.processEvents()
ok(w.pdf.print_allowed, "documento protegido que sí permite imprimir")

# 11) sin impresoras
pd.QPrinterInfo.availablePrinterNames = staticmethod(lambda: [])
def s11(dl):
    seen["noprinters"] = (dl.no_printers, dl.ok_btn.isEnabled(), dl.error.text())
plan["accept"] = False
run(s11)
plan["accept"] = True
np_ = seen["noprinters"]
ok(np_[0] and not np_[1] and "No hay ninguna impresora" in np_[2], "sin impresoras: aviso y botón desactivado")

# 12) colocación (cálculos puros)
P = printing.place
pl = P(842, 595, 595, 842, (12, 12, 571, 818), "shrink", True)
ok(pl.rotate and abs(pl.w - 571) < 0.6 and pl.h <= 818 and pl.scale < 1, "A4 apaisado en A4 con márgenes físicos: gira y reduce")
pl = P(842, 595, 595, 842, (12, 12, 571, 818), "shrink", False)
ok(not pl.rotate and abs(pl.w - 571) < 0.6, "sin giro automático: reduce al ancho")
pl = P(595, 842, 595, 842, (12, 12, 571, 818), "actual", True)
ok(pl.x == 0 and pl.y == 0 and pl.scale == 1, "tamaño real centrado en la hoja")
pl = P(600, 600, 595, 842, (0, 0, 595, 842), "fit", True)
ok(not pl.rotate, "página cuadrada: no se gira")
ok(printing.apply_subset([0, 1, 2, 3, 4], "odd") == [0, 2, 4] and printing.apply_subset([0, 1, 2, 3, 4], "even") == [1, 3],
   "pares e impares por número de página")

# 13) «Ajustes…»: cuadro de impresión del sistema; lo elegido allí vuelve al diálogo
pd.QPrinterInfo.availablePrinterNames = staticmethod(lambda: ["Oficina color", "Planta 2 BN"])
w.open_file(src); app.processEvents()
def fake_sys_exec(self):
    pr = self.printer()
    seen["sys_range"] = (pr.printRange(), pr.fromPage(), pr.toPage(), pr.copyCount())
    pr.setCopyCount(3); pr.setPrintRange(QPrinter.PageRange); pr.setFromTo(2, 3)
    pr.setColorMode(QPrinter.GrayScale)
    return True
pd.QPrintDialog.exec = fake_sys_exec
def s13(dl):
    dl.rng.setText("1-4"); dl.r_rng.setChecked(True)
    dl._system_dialog()
    dl.printer.setOutputFormat(QPrinter.PdfFormat); dl.printer.setOutputFileName(OUT)
o = run(s13)
dl = seen["dialog"]
ok(seen["sys_range"][:3] == (QPrinter.PageRange, 1, 4), f"el cuadro del sistema recibe el intervalo {seen['sys_range']}")
ok(dl.copies.value() == 3 and dl.rng.text() == "2-3" and dl.color.currentData() == "gray",
   "recoge copias, intervalo y color del cuadro del sistema")
ok(o is not None and o.page_count == 6, f"imprime 2 páginas × 3 copias ({o.page_count if o else 0})")

# 14) modo compatible (Windows, GDI directo): casilla por impresora y parámetros que se envían
from novopdf.core import printing_win
pd.COMPAT_AVAILABLE = True
printing_win.available = lambda: True
calls = []
printing_win.print_pages = lambda doc, name, pages, **kw: (calls.append((name, list(pages), kw)), len(pages))[1]
def s14(dl):
    ok(not dl.compat.isHidden() and not dl.compat.isChecked(), "casilla «Modo compatible» visible y desactivada al principio")
    dl.printer_combo.setCurrentIndex(dl.printer_combo.findData("Planta 2 BN"))
    dl.compat.setChecked(True)
    dl.r_all.setChecked(True); dl.copies.setValue(2)
    dl.color.setCurrentIndex(dl.color.findData("gray"))
o = run(s14)
ok(calls and calls[-1][0] == "Planta 2 BN" and calls[-1][1] == [0, 1, 2, 3, 4], f"modo compatible: imprime por GDI en la impresora elegida {calls[-1][:2] if calls else '-'}")
kw = calls[-1][2] if calls else {}
ok(kw.get("gray") is True and kw.get("copies") == 2 and kw.get("paper_id") == 9 and kw.get("duplex") in ("none", "long", "short"),
   f"con gris, copias, papel A4 (9) y caras: {kw.get('gray'), kw.get('copies'), kw.get('paper_id'), kw.get('duplex')}")
def s14b(dl):
    seen["compat_planta"] = dl.compat.isChecked()
    dl.printer_combo.setCurrentIndex(dl.printer_combo.findData("Oficina color"))
    seen["compat_oficina"] = dl.compat.isChecked()
    dl.printer.setOutputFormat(QPrinter.PdfFormat); dl.printer.setOutputFileName(OUT)
n0 = len(calls)
o = run(s14b)
ok(seen["compat_planta"] and not seen["compat_oficina"], "se recuerda para cada impresora")
ok(len(calls) == n0 and o is not None, "sin la casilla se imprime por el camino normal")
from novopdf.core.printing_win import devmode_changes, device_rect, DM_DUPLEX, DM_PAPERSIZE
ch = devmode_changes(9, True, "long")
ok(ch["set"] == {"Orientation": 1, "Color": 1, "Copies": 1, "PaperSize": 9, "Duplex": 2} and ch["fields"] & DM_DUPLEX
   and ch["fields"] & DM_PAPERSIZE, "DEVMODE: vertical, gris, 1 copia, A4 y doble cara")
x, y, w_, h_ = device_rect(printing.Placement(False, 10, 20, 100, 200, 1), 600, 600, 50, 60)
ok((round(x), round(y), round(w_), round(h_)) == (33, 107, 833, 1667), "posición en el DC (origen en la zona imprimible)")

print(f"\n{sum(res)}/{len(res)} correctas")
sys.exit(0 if all(res) else 1)
