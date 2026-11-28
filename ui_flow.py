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

import os, sys, shutil
os.environ["QT_QPA_PLATFORM"]="offscreen"; os.environ["NOVOPDF_HOME"]="/home/claude/novopdf/src"
sys.path.insert(0,"/home/claude/novopdf/src")
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QFileDialog
from PySide6.QtCore import Qt, QPoint, QTimer
from PySide6.QtTest import QTest
app=QApplication(sys.argv); app.setStyle("Fusion")
from novopdf.ui import theme, dialogs
app.setStyleSheet(theme.build_qss())
from novopdf.ui import mainwindow as mw
import pymupdf
ok=lambda c,m: print(("OK  " if c else "FAIL"), m)
# Patch blocking UI
QMessageBox.information=staticmethod(lambda *a,**k: None); QMessageBox.warning=staticmethod(lambda *a,**k: None)
QMessageBox.critical=staticmethod(lambda *a,**k: print("CRITICAL:", a[2] if len(a)>2 else a))
dialogs.confirm=lambda *a,**k: True
w=mw.MainWindow(); w.resize(1300,850); w.show()
shutil.copy("texto.pdf","/tmp/claude-0/t.pdf")
w.open_file("/tmp/claude-0/t.pdf"); app.processEvents()
QTest.qWait(200)
ok(w.pdf and w.pdf.page_count==3, "abrir")
# edit text via mouse
def fake_exec_text(self):
    self.edit.setPlainText("Texto modificado desde la interfaz con ñ"); return True
dialogs.TextDialog.exec=fake_exec_text
w.set_tool("edit_text")
pw=w.viewer.pages[0]; s=w.viewer.scale
b=w.viewer.blocks(0)[1].bbox
QTest.mouseClick(pw, Qt.LeftButton, Qt.NoModifier, QPoint(int((b.x0+10)*s), int((b.y0+5)*s)))
app.processEvents()
ok("modificado desde la interfaz" in w.pdf.doc[0].get_text(), "editar texto con clic")
ok(w.pdf.modified and w.b_undo.isEnabled(), "estado modificado/deshacer")
# add text
w.set_tool("add_text")
def fake_exec_add(self):
    self.edit.setPlainText("Nota añadida"); return True
dialogs.TextDialog.exec=fake_exec_add
QTest.mouseClick(w.viewer.pages[0], Qt.LeftButton, Qt.NoModifier, QPoint(int(100*s), int(600*s)))
ok("Nota añadida" in w.pdf.doc[0].get_text(), "añadir texto con clic")
# image drag move
w.set_tool("images")
im=w.viewer.images(0)[0].bbox
pw=w.viewer.pages[0]
start=QPoint(int((im.x0+20)*s), int((im.y0+20)*s)); end=QPoint(start.x()+int(100*s), start.y()+int(50*s))
QTest.mousePress(pw, Qt.LeftButton, Qt.NoModifier, start)
for k in range(1,6):
    p=QPoint(start.x()+(end.x()-start.x())*k//5, start.y()+(end.y()-start.y())*k//5)
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtCore import QPointF, QEvent
    ev=QMouseEvent(QEvent.MouseMove, QPointF(p), QPointF(pw.mapToGlobal(p)), Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
    app.sendEvent(pw, ev)
QTest.mouseRelease(pw, Qt.LeftButton, Qt.NoModifier, end)
app.processEvents()
nb=pymupdf.Rect(w.viewer.images(0)[0].bbox) if w.viewer.images(0) else None
ok(nb is not None and abs(nb.x0-(im.x0+100))<3 and abs(nb.y0-(im.y0+50))<3, f"mover imagen arrastrando {im} -> {nb}")
# select image and delete with key
QTest.mouseClick(pw, Qt.LeftButton, Qt.NoModifier, QPoint(int((nb.x0+10)*s), int((nb.y0+10)*s)))
ok(w.viewer.sel_image is not None and w.hint_buttons.count()==3, "seleccionar imagen muestra botones")
w.viewer._delete_key(); app.processEvents()
ok(len(w.viewer.images(0))==0, "eliminar imagen (Supr)")
# erase zone
w.set_tool("erase")
QTest.mousePress(pw, Qt.LeftButton, Qt.NoModifier, QPoint(int(60*s), int(60*s)))
ev=QMouseEvent(QEvent.MouseMove, QPointF(int(560*s), int(95*s)), QPointF(0,0), Qt.NoButton, Qt.LeftButton, Qt.NoModifier); app.sendEvent(pw, ev)
QTest.mouseRelease(pw, Qt.LeftButton, Qt.NoModifier, QPoint(int(560*s), int(95*s)))
ok("Vicegerencia" not in w.pdf.doc[0].get_text(), "borrar zona")
# undo all 5
for _ in range(5): w.undo()
ok("Vicegerencia" in w.pdf.doc[0].get_text() and len(editing_imgs:=w.viewer.images(0))==1, "deshacer x5")
w.set_tool("select")
# select text drag + copy
pw=w.viewer.pages[0]; s=w.viewer.scale
wd=w.viewer.words(0)
a=pymupdf.Rect(wd[0][:4]); bq=pymupdf.Rect(wd[3][:4])
QTest.mousePress(pw, Qt.LeftButton, Qt.NoModifier, QPoint(int((a.x0+2)*s), int((a.y0+a.height/2)*s)))
ev=QMouseEvent(QEvent.MouseMove, QPointF((bq.x0+2)*s, (bq.y0+bq.height/2)*s), QPointF(0,0), Qt.NoButton, Qt.LeftButton, Qt.NoModifier); app.sendEvent(pw, ev)
QTest.mouseRelease(pw, Qt.LeftButton, Qt.NoModifier, QPoint(int((bq.x0+2)*s), int((bq.y0+5)*s)))
w.viewer.copy_selection()
ok(QApplication.clipboard().text().startswith("Informe de la"), f"seleccionar y copiar: {QApplication.clipboard().text()!r}")
# pages
w.thumbs.clearSelection(); w.thumbs.item(2).setSelected(True)
w.move_pages(-1); ok("página 3" in w.pdf.doc[1].get_text(), "mover página arriba")
w.thumbs.clearSelection(); w.thumbs.item(0).setSelected(True)
w.rotate_pages(90); ok(w.pdf.doc[0].rotation==90, "girar")
w.insert_blank(1); ok(w.pdf.page_count==4, "insertar en blanco")
w.thumbs.clearSelection(); w.thumbs.item(1).setSelected(True)
w.delete_pages(); ok(w.pdf.page_count==3, "eliminar seleccionada")
w._reorder([2,1,0]); ok("página 1" in w.pdf.doc[2].get_text(), "reordenar arrastrando (simulado)")
QFileDialog.getSaveFileName=staticmethod(lambda *a,**k: ("/tmp/claude-0/extra.pdf",""))
w.thumbs.clearSelection(); w.thumbs.item(0).setSelected(True); w.thumbs.item(1).setSelected(True)
dialogs.confirm=lambda *a,**k: False
w.extract_pages(); ok(pymupdf.open("/tmp/claude-0/extra.pdf").page_count==2 and w.pdf.page_count==3, "extraer 2 páginas")
dialogs.confirm=lambda *a,**k: True
QFileDialog.getOpenFileName=staticmethod(lambda *a,**k: ("/home/claude/novopdf/tests/escaneado.pdf",""))
w.insert_file(at=3); ok(w.pdf.page_count==6, "insertar archivo")
# protect + save
from novopdf.core.document import Protection
w.pdf.protection=Protection(enabled=True,user_pw="clave1"); w.pdf.modified=True
w._save_to("/tmp/claude-0/ui_saved.pdf"); x=pymupdf.open("/tmp/claude-0/ui_saved.pdf"); ok(x.needs_pass and x.authenticate("clave1"), "guardar con contraseña")
# reopen with password via dialog patch
dialogs.ask_password=lambda *a,**k: "clave1"
w.open_file("/tmp/claude-0/ui_saved.pdf"); ok(w.pdf.page_count==6 and w.pdf.protection.enabled, "abrir protegido desde la UI")
# OCR via worker
w.open_file("/home/claude/novopdf/tests/escaneado.pdf")
ok(w._scanned and w.hint.isVisible(), "aviso de documento escaneado")
class FakeOcr:
    def __init__(s,*a): pass
dialogs.OcrDialog.exec=lambda self: True
w.run_ocr()
for _ in range(200):
    QTest.qWait(100)
    if not w._ocr_worker.isRunning(): break
QTest.qWait(300)
ok("procedimiento" in w.pdf.doc[0].get_text(), "OCR desde la interfaz")
# search after OCR
w.search.setText("Extremadura"); w.search_next(); ok(len(w.search_results)>=3, f"buscar tras OCR ({len(w.search_results)})")
# Sign via UI with pfx
w._save_to("/tmp/claude-0/ocr_ok.pdf")
def fake_sign_exec(self):
    self.r_pfx.setChecked(True); self.pfx_path.setText("/home/claude/novopdf/tests/prueba.pfx"); self.pfx_pw.setText("1234")
    self.out.setText("/tmp/claude-0/ui_firmado.pdf"); self.reason.setCurrentText("Conformidad")
    return self.validate()
dialogs.SignDialog.exec=fake_sign_exec
w.sign(0, pymupdf.Rect(330,700,540,770))
ok(w.pdf.path=="/tmp/claude-0/ui_firmado.pdf" and w.pdf.has_signatures(), "firmar desde la UI")
from novopdf.core import signing
r=signing.verify_pdf(open("/tmp/claude-0/ui_firmado.pdf","rb").read()); ok(r and r[0].intact, "firma válida")
dialogs.SignaturesDialog.exec=lambda self: (self.grab().save("/tmp/claude-0/shots/12_verify.png"), 1)[1]
w.verify()
w.grab().save("/tmp/claude-0/shots/10_signed.png")
# can_edit warns on signed doc
called=[]
dialogs.confirm=lambda *a,**k: called.append(1) or False
ok(not w._can_edit() and called, "aviso al editar documento firmado")
print("done")
