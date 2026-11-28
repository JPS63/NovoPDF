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
os.environ["QT_QPA_PLATFORM"]="offscreen"; os.environ["NOVOPDF_HOME"]="/tmp/claude-0/fh"
sys.path.insert(0,"/home/claude/novopdf/src")
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest
app=QApplication(sys.argv); app.setStyle("Fusion")
from novopdf.ui import theme, dialogs
app.setStyleSheet(theme.build_qss())
from novopdf.ui import mainwindow as mw
import pymupdf
ok=lambda c,m: print(("OK  " if c else "FAIL"), m)
QMessageBox.information=staticmethod(lambda *a,**k: None)
QMessageBox.exec=lambda self: 0
dialogs.confirm=lambda *a,**k: True
w=mw.MainWindow(); w.resize(1300,850); w.show()
w.open_file("/tmp/claude-0/full.pdf"); QTest.qWait(300)
captured={}
orig_init=dialogs.TextDialog.__init__
def fake_exec(self):
    self.edit.setPlainText("Nuevo párrafo con la fuente del documento: QXZ ñ €")
    self._update_choice(); captured['note']=self.font_note.text()
    self.show(); app.processEvents(); self.grab().save("/tmp/claude-0/shots/t_text2.png")
    return True
dialogs.TextDialog.exec=fake_exec
w.set_tool("edit_text"); s=w.viewer.scale; b=w.viewer.blocks(0)[0].bbox
QTest.mouseClick(w.viewer.pages[0], Qt.LeftButton, Qt.NoModifier, QPoint(int((b.x0+10)*s), int((b.y0+5)*s)))
ok("QXZ ñ €" in w.pdf.doc[0].get_text(), "editar con fuente original")
ok("la del documento" in captured.get('note',''), f"aviso de fuente: {captured.get('note')}")
fn=[f[3] for f in w.pdf.doc[0].get_fonts()]; ok(any("Liberation Serif" in f for f in fn), f"fuentes de la página: {fn}")
w.pdf.doc[0].get_pixmap(dpi=110, clip=pymupdf.Rect(60,60,520,130)).save("/tmp/claude-0/shots/edited_font.png")
# export
w.set_tool("select")
def fake_export_exec(self):
    self.fmt.setCurrentIndex(self.fmt.findData("tif")); self.multi.setChecked(True)
    self.folder.setText("/tmp/claude-0/exp_ui"); self.dpi.setCurrentIndex(1)
    self.show(); app.processEvents(); self.adjustSize(); self.grab().save("/tmp/claude-0/shots/t_export.png")
    r=self.validate(); print("validate", r, getattr(self,"error").text()); return r
dialogs.ExportDialog.exec=fake_export_exec
shutil.rmtree("/tmp/claude-0/exp_ui", ignore_errors=True)
w.export_images()
print("opts", getattr(w,"_export_worker",None) and w._export_worker.opts)
from PySide6.QtCore import QEventLoop, QTimer
for _ in range(100):
    lp=QEventLoop(); QTimer.singleShot(100, lp.quit); lp.exec()
    if not w._export_worker.isRunning(): break
QTest.qWait(200)
ok(os.path.exists("/tmp/claude-0/exp_ui/full.tif"), f"exportar TIFF desde la interfaz: {os.listdir('/tmp/claude-0/exp_ui') if os.path.isdir('/tmp/claude-0/exp_ui') else '-'}")
w.grab().save("/tmp/claude-0/shots/13_ribbon.png")
