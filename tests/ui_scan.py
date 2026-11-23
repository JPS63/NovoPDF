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

import os, sys
import pymupdf
src=pymupdf.open("texto.pdf"); fake=pymupdf.open(); fake.insert_pdf(src, from_page=0, to_page=0); fake.new_page(); fake.insert_pdf(src, from_page=2, to_page=2); fake.save("/tmp/claude-0/fake_scan.pdf")
os.environ["QT_QPA_PLATFORM"]="offscreen"; os.environ["NOVOPDF_HOME"]="/tmp/claude-0/fh"; os.environ["NOVOPDF_FAKE_SCANNER"]="/tmp/claude-0/fake_scan.pdf"
sys.path.insert(0,"/home/claude/novopdf/src")
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QEventLoop, QTimer
app=QApplication(sys.argv); app.setStyle("Fusion")
from novopdf.ui import theme, dialogs
app.setStyleSheet(theme.build_qss())
from novopdf.ui import mainwindow as mw
from novopdf.core import scanner
ok=lambda c,m: print(("OK  " if c else "FAIL"), m)
def wait(ms=200):
    lp=QEventLoop(); QTimer.singleShot(ms, lp.quit); lp.exec()
# core
imgs=[]; scanner.scan(scanner.ScanSettings("fake","duplex","gray",300), imgs.append)
ok(len(imgs)==3 and [scanner.is_blank(i.data) for i in imgs]==[False,True,False], "detección de páginas en blanco")
data,removed=scanner.images_to_pdf(imgs,"gray",True); d=pymupdf.open(stream=data)
ok(d.page_count==2 and removed==1 and abs(d[0].rect.width-595)<3, f"PDF desde escaneo: {d.page_count} págs, {d[0].rect}")
data2,_=scanner.images_to_pdf(imgs,"bw",False); ok(pymupdf.open(stream=data2).page_count==3, f"blanco y negro {len(data2)//1024} KB vs grises {len(data)//1024} KB")
os.environ["NOVOPDF_FAKE_START"]="0"
# UI
answers=[]
QMessageBox.information=staticmethod(lambda *a,**k: answers.append(("info",a[2] if len(a)>2 else "")))
def fake_box_exec(self): self._shown_text=self.text()
QMessageBox.exec=fake_box_exec
choice=[]
def clicked(self):
    want=choice.pop(0) if choice else "Terminar"
    return next(b for b in self.buttons() if b.text()==want)
QMessageBox.clickedButton=clicked
w=mw.MainWindow(); w.resize(1360,860); w.show(); wait(300)
w.grab().save("/tmp/claude-0/shots/14_welcome_scan.png")
def dlg_exec(src):
    def f(self):
        {"flatbed":self.r_flat,"feeder":self.r_feed,"duplex":self.r_dup}[src].setChecked(True)
        self.show(); app.processEvents(); self.adjustSize(); self.grab().save("/tmp/claude-0/shots/t_scan.png")
        return self.validate()
    return f
dialogs.ScanDialog.exec=dlg_exec("duplex")
w.scan_document(False)
for _ in range(150):
    wait(200)
    if w.pdf and not getattr(w,"_ocr_worker",None) is None and not w._ocr_worker.isRunning() and answers: break
ok(w.pdf and w.pdf.page_count==2, f"alimentador doble cara -> PDF nuevo de {w.pdf.page_count if w.pdf else 0} páginas")
ok(w.pdf and w.pdf.name.startswith("Escaneo "), f"nombre propuesto: {w.pdf.name if w.pdf else ''}")
ok(w.pdf and "procedimiento" in w.pdf.doc[0].get_text(), "OCR automático tras escanear")
ok(any("Se han escaneado 2" in a[1] and "en blanco" in a[1] for a in answers), f"resumen: {answers[-1:]}")
w.grab().save("/tmp/claude-0/shots/15_scanned_doc.png")
# flatbed: add 2 pages to current doc
answers.clear(); os.environ["NOVOPDF_FAKE_START"]="0"
dialogs.ScanDialog.exec=dlg_exec("flatbed")
choice[:]=["Escanear otra página","Terminar"]
import novopdf.ui.dialogs as dd
dd.confirm=lambda *a,**k: True
w.thumbs.clearSelection(); w.viewer.go_to(0); wait(100)
w.scan_document(True)
for _ in range(150):
    wait(200)
    if answers: break
ok(w.pdf.page_count==3, f"cristal: añadir páginas al documento -> {w.pdf.page_count} págs (1 en blanco quitada)")
print("resumen2:", answers)
