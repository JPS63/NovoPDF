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

"""1.5.0: varios documentos en pestañas de la misma ventana y ventana única."""
import os, sys, shutil, subprocess, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["NOVOPDF_HOME"] = "/tmp/claude-0/tabs"
os.environ["NOVOPDF_INSTANCE_TAG"] = "prueba-%d" % os.getpid()
shutil.rmtree("/tmp/claude-0/tabs", ignore_errors=True)
os.makedirs("/tmp/claude-0/tabs", exist_ok=True)
sys.path.insert(0, "/home/claude/novopdf/src")
from PySide6.QtWidgets import QApplication, QMessageBox, QFileDialog
from PySide6.QtCore import QMimeData, QUrl, QPointF, Qt
from PySide6.QtGui import QDropEvent, QCloseEvent
app = QApplication(sys.argv); app.setStyle("Fusion")
from novopdf.ui import theme, dialogs
app.setStyleSheet(theme.build_qss())
from novopdf.ui import mainwindow as mw
from novopdf import instance
import pymupdf
res = []
ok = lambda c, m: (res.append(bool(c)), print(("OK  " if c else "FAIL"), m))
QMessageBox.critical = staticmethod(lambda *a, **k: print("ERROR", a[2]))
asked = []
answer = {"v": "discard"}
dialogs.ask_save_changes = lambda parent, name: (asked.append(name), answer["v"])[1]

def pump(n=20):
    for _ in range(n):
        app.processEvents(); time.sleep(0.01)

files = []
for k, (name, n) in enumerate([("uno", 3), ("dos", 12), ("tres", 2)]):
    d = pymupdf.open()
    for i in range(n):
        d.new_page().insert_text((72, 100), f"{name} página {i + 1}", fontsize=20)
    p = f"/tmp/claude-0/tabs/{name}.pdf"
    d.save(p); files.append(p)

w = mw.MainWindow(); w.resize(1200, 800); w.show(); pump()
ok(not w.doc_bar.isVisible() and w.stack.currentIndex() == 0, "sin documentos: pantalla de inicio, sin pestañas")
# Abrir… con varios archivos a la vez
QFileDialog.getOpenFileNames = staticmethod(lambda *a, **k: (files[:2], ""))
w.open_file(); pump()
ok(w.doc_tabs.count() == 2 and len(w.docs) == 2, f"Abrir con dos archivos: dos pestañas ({w.doc_tabs.count()})")
ok(w.doc_bar.isVisible() and w.doc_tabs.currentIndex() == 1 and w.pdf.name == "dos.pdf", "se muestra el último abierto")
ok([w.doc_tabs.tabText(k) for k in range(2)] == ["uno.pdf", "dos.pdf"], "nombres en las pestañas")
# la página de cada pestaña se conserva al cambiar
w.viewer.go_to(7); pump()
ok(w.viewer.current_page() == 7, "en «dos» vamos a la página 8")
w.doc_tabs.setCurrentIndex(0); pump()
ok(w.pdf.name == "uno.pdf" and w.viewer.pdf is w.pdf and w.thumbs.count() == 3, "cambiar de pestaña muestra el otro documento")
w.doc_tabs.setCurrentIndex(1); pump(40)
ok(w.pdf.name == "dos.pdf" and w.viewer.current_page() == 7, f"al volver sigue en la página 8 ({w.viewer.current_page() + 1})")
ok(w.page_total.text() == "de 12", "barra de estado del documento visible")
# abrir otra vez un archivo ya abierto: solo se muestra su pestaña
w.open_file(files[0]); pump()
ok(w.doc_tabs.count() == 2 and w.pdf.name == "uno.pdf", "un archivo ya abierto no se duplica")
# cambios: marca en la pestaña
w.pdf.checkpoint(); w.pdf.doc[0].insert_text((72, 200), "cambio", fontsize=12); w.pdf.modified = True; w.after_change([0])
pump()
ok(w.doc_tabs.tabText(0).endswith("•"), f"pestaña con cambios marcada: {w.doc_tabs.tabText(0)!r}")
# nuevo PDF en blanco: pestaña nueva (sin preguntar por el anterior)
asked.clear()
w._set_document(mw.PdfDocument.new_blank(1, 595, 842)); pump()
ok(w.doc_tabs.count() == 3 and not asked, "documento nuevo en otra pestaña sin preguntar por el anterior")
# Ctrl+Tab
w._cycle_tab(1); pump()
ok(w._cur == 0 and w.pdf.name == "uno.pdf", "Ctrl+Tab pasa a la pestaña siguiente")
# mover pestañas
w.doc_tabs.moveTab(0, 2); pump()
ok([d.pdf.name for d in w.docs][2] == "uno.pdf" and w.docs[w._cur].pdf is w.pdf, "mover pestañas mantiene el orden de los documentos")
# cerrar una pestaña con cambios (no es la actual): se muestra y se pregunta; cancelar no cierra
w._switch_tab(0); pump()
answer["v"] = "cancel"; asked.clear()
k_uno = next(k for k, d in enumerate(w.docs) if d.pdf.name == "uno.pdf")
w._close_tab(k_uno); pump()
ok(asked == ["uno.pdf"] and w.doc_tabs.count() == 3 and w.pdf.name == "uno.pdf", "cerrar con cambios: se muestra y pregunta; Cancelar no cierra")
answer["v"] = "discard"
w._close_tab(w._cur); pump()
ok(w.doc_tabs.count() == 2 and all(d.pdf.name != "uno.pdf" for d in w.docs) and w.pdf is w.docs[w._cur].pdf,
   "Descartar: se cierra y se muestra la vecina")
# Ctrl+W en las dos restantes -> pantalla de inicio
w.close_document(); pump(); w.close_document(); pump()
ok(w.doc_tabs.count() == 0 and w.pdf is None and w.stack.currentIndex() == 0 and not w.doc_bar.isVisible(),
   "al cerrar todas: pantalla de inicio")
# arrastrar varios archivos con un documento abierto -> pestañas nuevas
w.open_file(files[2]); pump()
QMessageBox.exec = lambda self: None
QMessageBox.clickedButton = lambda self: self.buttons()[0] if self.buttons() else None
md = QMimeData(); md.setUrls([QUrl.fromLocalFile(files[0]), QUrl.fromLocalFile(files[1])])
ev = QDropEvent(QPointF(10, 10), Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier)
w.dropEvent(ev); pump()
ok(w.doc_tabs.count() == 3, f"arrastrar dos PDF: se abren en pestañas ({w.doc_tabs.count()})")
from PySide6.QtWidgets import QTabBar
w.open_file(files[1]); pump()       # mostrar «dos» y cerrar «tres» con su ✕
k3 = next(k for k, d in enumerate(w.docs) if d.pdf.name == "tres.pdf")
w.doc_tabs.tabButton(k3, QTabBar.RightSide).click(); pump()
ok(w.doc_tabs.count() == 2 and w.pdf.name == "dos.pdf" and all(d.pdf.name != "tres.pdf" for d in w.docs),
   "la ✕ de una pestaña que no es la actual la cierra y sigue mostrándose la actual")
# cerrar la ventana con dos documentos con cambios: Cancelar no cierra; Descartar pregunta por cada uno
for d in w.docs[:2]:
    d.pdf.modified = True
names = sorted(d.pdf.name for d in w.docs[:2])
n_docs = len(w.docs)
answer["v"] = "cancel"; asked.clear()
ce = QCloseEvent(); w.closeEvent(ce)
ok(len(asked) == 1 and not ce.isAccepted() and len(w.docs) == n_docs, "Cancelar al salir: no se cierra")
asked.clear(); answer["v"] = "discard"
ce = QCloseEvent(); w.closeEvent(ce)
ok(sorted(asked) == names and ce.isAccepted(), f"al salir pregunta por cada documento con cambios: {asked}")

# ---------- ventana única
role, server = instance.claim([])
ok(role == "server" and server is not None, f"primera ventana: se queda como principal ({role})")
got = []
server.on_open = got.append
code = ("import sys; sys.path.insert(0, '/home/claude/novopdf/src'); from novopdf import instance;"
        "r, s = instance.claim(sys.argv[1:]); print(r)")
outs = []
procs = [subprocess.Popen([sys.executable, "-c", code, f], stdout=subprocess.PIPE, text=True,
                          env=dict(os.environ)) for f in files]
for p in procs:
    outs.append(p.communicate(timeout=30)[0].strip())
time.sleep(0.2)
ok(outs == ["forwarded"] * 3, f"tres procesos a la vez pasan sus archivos y terminan: {outs}")
ok(sorted(x for g in got for x in g) == sorted(files), f"la ventana principal recibe los tres: {got}")
server.close()

print(f"\n{sum(res)}/{len(res)} correctas")
sys.exit(0 if all(res) else 1)
