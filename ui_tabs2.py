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

"""1.5.1: el mismo PDF no se abre dos veces; sacar pestañas a otra ventana (como en Acrobat)."""
import os, sys, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["NOVOPDF_HOME"] = "/tmp/claude-0/tabs2"
D = "/tmp/claude-0/tabs2"
shutil.rmtree(D, ignore_errors=True); os.makedirs(D + "/otra", exist_ok=True)
sys.path.insert(0, "/home/claude/novopdf/src")
from PySide6.QtWidgets import QApplication, QMessageBox, QFileDialog, QMenu, QTabBar
from PySide6.QtCore import QPoint, QPointF, Qt, QEvent, QMimeData
from PySide6.QtGui import QMouseEvent, QDropEvent, QCloseEvent, QDrag
app = QApplication(sys.argv); app.setStyle("Fusion")
from novopdf.ui import theme, dialogs
app.setStyleSheet(theme.build_qss())
from novopdf.ui import mainwindow as mw, doctabs
import pymupdf
res = []
ok = lambda c, m: (res.append(bool(c)), print(("OK  " if c else "FAIL"), m, flush=True))
errors = []
dialogs.error = lambda parent, title, text: errors.append(text)
confirm = {"v": True, "asked": []}
dialogs.confirm = lambda parent, title, text, *a, **k: (confirm["asked"].append(text), confirm["v"])[1]
dialogs.ask_save_changes = lambda parent, name: "discard"

def pump(n=15):
    for _ in range(n):
        app.processEvents(); time.sleep(0.005)

files = {}
for name, n in (("uno", 3), ("dos", 10), ("tres", 2)):
    d = pymupdf.open()
    for i in range(n):
        d.new_page().insert_text((72, 100), f"{name} {i + 1}", fontsize=20)
    d.save(f"{D}/{name}.pdf"); files[name] = f"{D}/{name}.pdf"
shutil.copy(files["uno"], f"{D}/otra/copia_de_uno.pdf")
os.symlink(files["uno"], f"{D}/enlace.pdf")
os.link(files["dos"], f"{D}/otra/dos_enlace_duro.pdf")
from PIL import Image
Image.new("RGB", (300, 400), "white").save(f"{D}/foto.png")

w = mw.MainWindow(); w.resize(1200, 800); w.show(); pump()
W = mw.MainWindow
w.open_files([files["uno"], files["dos"], files["tres"]]); pump()
ok(len(w.docs) == 3, "tres documentos abiertos")

# ---------- 1) el mismo archivo por otros caminos
w.open_file(f"{D}/otra/../uno.pdf"); pump()
ok(len(w.docs) == 3 and w.pdf.name == "uno.pdf", "ruta con «..»: no se duplica, se muestra")
ok("ya estaba abierto" in w.msg_label.text(), f"aviso: «{w.msg_label.text()}»")
w.open_file(f"{D}/enlace.pdf"); pump()
ok(len(w.docs) == 3, "acceso directo / enlace al mismo archivo: no se duplica")
w.open_file(f"{D}/otra/dos_enlace_duro.pdf"); pump()
ok(len(w.docs) == 3 and w.pdf.name == "dos.pdf", "mismo archivo (mismo identificador en disco): no se duplica")
QFileDialog.getOpenFileNames = staticmethod(lambda *a, **k: ([files["tres"], files["uno"]], ""))
w.open_file(); pump()
ok(len(w.docs) == 3, "Abrir… con archivos ya abiertos: no se duplican")

# ---------- 2) copia idéntica en otra carpeta: se pregunta
confirm["v"] = True; confirm["asked"].clear()
w.open_file(f"{D}/otra/copia_de_uno.pdf"); pump()
ok(len(w.docs) == 3 and confirm["asked"] and "idéntico" in confirm["asked"][0] and w.pdf.name == "uno.pdf",
   "copia idéntica: pregunta y «Ir al que está abierto» lo muestra")
confirm["v"] = False
w.open_file(f"{D}/otra/copia_de_uno.pdf"); pump()
ok(len(w.docs) == 4 and w.pdf.name == "copia_de_uno.pdf", "«Abrir también este»: se abre la copia")
w.open_file(f"{D}/otra/copia_de_uno.pdf"); pump()
ok(len(w.docs) == 4, "la copia ya abierta tampoco se duplica")
w._close_tab(w._cur, ask=False); pump()
confirm["v"] = True

# ---------- 3) imágenes
w.open_file(f"{D}/foto.png"); pump(); w.open_file(f"{D}/foto.png"); pump()
ok(sum(1 for d in w.docs if d.pdf.name == "foto.pdf") == 1, "una imagen abierta dos veces: una sola pestaña (con su nombre)")
w._close_tab(w._cur, ask=False); pump()

# ---------- 4) no se puede guardar encima de un archivo abierto en otra pestaña
w._switch_tab(0); pump()
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (files["dos"], ""))
errors.clear()
ok(w.save_as() is False and errors and "está abierto en otra pestaña" in errors[-1], "Guardar como sobre otro documento abierto: se impide")
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (f"{D}/uno_bis.pdf", ""))
ok(w.save_as() and w.pdf.path.endswith("uno_bis.pdf"), "Guardar como con otro nombre")
w.open_file(f"{D}/uno_bis.pdf"); pump()
ok(len(w.docs) == 3 and w.pdf.name == "uno_bis.pdf", "el nombre nuevo también se reconoce como abierto")
confirm["v"] = False      # uno_bis.pdf puede ser idéntico byte a byte: «Abrir también este»
w.open_file(files["uno"]); pump()
confirm["v"] = True
ok(len(w.docs) == 4, "el archivo original (ya no abierto) sí se puede abrir")

# ---------- 5) sacar una pestaña a una ventana nueva
k = next(i for i, d in enumerate(w.docs) if d.pdf.name == "dos.pdf")
w._switch_tab(k); pump(); w.viewer.go_to(6); pump()
doc_dos = w.docs[k]
w2 = w.detach_doc(doc_dos, QPoint(500, 300))
for _ in range(8): pump(10)
ok(w2 is not None and len(W.windows) == 2 and len(w.docs) == 3 and [d.pdf.name for d in w2.docs] == ["dos.pdf"],
   "«Abrir en una ventana nueva»: el documento pasa a otra ventana")
ok(w2.isVisible() and w2.pdf is doc_dos.pdf and w2.viewer.current_page() == 6, f"conserva la página ({w2.viewer.current_page() + 1})")
ok(all(d.pdf.name != "dos.pdf" for d in w.docs) and w.pdf is not None, "la ventana original sigue con las demás")
# abrir desde la primera ventana un archivo que está en la segunda
w.bring_to_front()
w.open_file(files["dos"]); pump()
ok(len(w.docs) == 3 and len(w2.docs) == 1 and W.last_active is w2, "abrir un PDF que está en otra ventana: se muestra esa ventana")
# los archivos que llegan del Explorador van a la última ventana usada
W.last_active = w2
W.target().open_files([f"{D}/foto.png"]); pump()
ok(len(w2.docs) == 2 and W.target() is w2, "lo abierto desde fuera va a la última ventana activa")
ok(w2.detach_doc(w2.docs[0]) is not None and len(W.windows) == 3, "se puede sacar otra pestaña a una tercera ventana")
w3 = W.windows[-1]
ok(w3.detach_doc(w3.docs[0]) is None and len(W.windows) == 3, "con una sola pestaña no se saca (ya está sola)")

# ---------- 6) mover entre ventanas y juntar
w3.move_doc_to(w3.docs[0], w); pump()
ok(w3 not in W.windows and len(W.windows) == 2 and any(d.pdf.name == "dos.pdf" for d in w.docs),
   "mover la única pestaña a otra ventana: la ventana vacía se cierra")
w.gather_windows(); pump()
ok(len(W.windows) == 1 and any(d.pdf.name == "dos.pdf" for d in w.docs), "«Traer aquí las pestañas de las otras ventanas»")

# ---------- 7) arrastrar con el ratón
bar = w.doc_tabs
started = []
orig_start = bar.start_drag
bar.start_drag = lambda k: started.append(k)
r = bar.tabRect(1)
p0 = QPointF(r.center()); p1 = QPointF(r.center().x(), r.center().y() + 120)
bar.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress, p0, bar.mapToGlobal(p0), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
bar.mouseMoveEvent(QMouseEvent(QEvent.MouseMove, QPointF(r.center().x() + 5, r.center().y()), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
ok(not started, "mover la pestaña dentro de la barra no la saca")
bar.mouseMoveEvent(QMouseEvent(QEvent.MouseMove, p1, bar.mapToGlobal(p1), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
ok(started == [1], "arrastrarla fuera de la barra empieza a sacarla")
bar.start_drag = orig_start
# soltarla fuera de NovoPDF: ventana nueva donde se suelta
n0 = len(w.docs)
QDrag.exec = lambda self, *a, **k: Qt.IgnoreAction
bar.start_drag(0); pump(20)
ok(len(W.windows) == 2 and len(w.docs) == n0 - 1, "soltada fuera: el documento pasa a una ventana nueva")
w4 = W.windows[-1]
# soltarla sobre otra ventana de NovoPDF: pasa a esa ventana
def drop_on_w4(self, *a, **k):
    md = QMimeData(); md.setData(doctabs.MIME, b"1")
    ev = QDropEvent(QPointF(20, 10), Qt.MoveAction, md, Qt.LeftButton, Qt.NoModifier)
    w4.doc_tabs.dropEvent(ev)
    return Qt.MoveAction
QDrag.exec = drop_on_w4
n0, m0 = len(w.docs), len(w4.docs)
bar.start_drag(0); pump(20)
ok(len(w.docs) == n0 - 1 and len(w4.docs) == m0 + 1 and len(W.windows) == 2, "soltada sobre otra ventana: pasa a ella")
# soltarla en su propia barra: no cambia nada
def drop_on_own(self, *a, **k):
    md = QMimeData(); md.setData(doctabs.MIME, b"1")
    bar.dropEvent(QDropEvent(QPointF(20, 10), Qt.MoveAction, md, Qt.LeftButton, Qt.NoModifier))
    return Qt.MoveAction
QDrag.exec = drop_on_own
n0 = len(w.docs)
bar.start_drag(0); pump()
ok(len(w.docs) == n0 and len(W.windows) == 2, "soltada en su propia barra: se queda donde estaba")

# ---------- 8) menú de la pestaña
menu = w._build_tab_menu(0)
acts = [x.text() for x in menu.actions()]
ok("Abrir en una ventana nueva" in acts and "Mover a otra ventana" in acts and "Cerrar las demás pestañas" in acts
   and "Mostrar en la carpeta" in acts, f"menú de la pestaña: {acts}")

# ---------- 9) cerrar una ventana secundaria con cambios: pregunta
asked = []
dialogs.ask_save_changes = lambda parent, name: (asked.append(name), "discard")[1]
w4.docs[0].pdf.modified = True
ce = QCloseEvent(); w4.closeEvent(ce); pump()
ok(ce.isAccepted() and asked and w4 not in W.windows and len(W.windows) == 1, "cerrar otra ventana con cambios: pregunta y se cierra")
ok(W.target() is w, "la ventana que queda recibe los archivos nuevos")

print(f"\n{sum(res)}/{len(res)} correctas")
sys.exit(0 if all(res) else 1)
