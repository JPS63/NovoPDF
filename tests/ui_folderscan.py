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

import faulthandler; faulthandler.dump_traceback_later(25, exit=True)
import os, sys, time, shutil, threading
import pymupdf
F="/tmp/claude-0/scanfolder"; shutil.rmtree(F, ignore_errors=True); os.makedirs(F)
os.environ.update(QT_QPA_PLATFORM="offscreen", NOVOPDF_HOME="/tmp/claude-0/fh", NOVOPDF_FORCE_FOLDER_SCAN="1", NOVOPDF_SCAN_FOLDER=F)
sys.path.insert(0,"/home/claude/novopdf/src")
open(os.path.join(F,"viejo.jpg"),"wb").write(b"x")   # anterior: debe ignorarse
os.utime(os.path.join(F,"viejo.jpg"), (time.time()-3600,)*2)
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QEventLoop, QTimer
app=QApplication(sys.argv); app.setStyle("Fusion")
from novopdf.ui import theme, dialogs
app.setStyleSheet(theme.build_qss())
from novopdf.ui import mainwindow as mw
from novopdf.core import scanner
ok=lambda c,m: print(("OK  " if c else "FAIL"), m)
def wait(ms):
    lp=QEventLoop(); QTimer.singleShot(ms, lp.quit); lp.exec()
answers=[]
QMessageBox.information=staticmethod(lambda *a,**k: answers.append(a[2] if len(a)>2 else ""))
w=mw.MainWindow(); w.resize(1300,850); w.show()
def drop_pages():
    src=pymupdf.open("texto.pdf")
    # página 1 como JPEG (como Captura de Imagen), página en blanco PNG, y un PDF escaneado de 1 página
    from PIL import Image
    pix=src[0].get_pixmap(dpi=150); Image.frombytes("RGB",(pix.width,pix.height),pix.samples).save(os.path.join(F,"Escaneo.jpeg"), dpi=(150,150))
    blank=pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0,0,1240,1754), 0); blank.set_rect(blank.irect,(255,255,255)); blank.save(os.path.join(F,"Escaneo 1.png"))
    sc=pymupdf.open(); p=sc.new_page(); p.insert_image(p.rect, pixmap=src[2].get_pixmap(dpi=150)); sc.save(os.path.join(F,"Escaneo 2.pdf"))
def fake_exec(self):
    self.show(); app.processEvents()
    drop_pages(); print("archivos creados", os.listdir(F), flush=True)
    for _ in range(20):
        wait(250)
        if len(self.files)>=3: break
    self.grab().save("/tmp/claude-0/shots/t_folderscan.png")
    print("recibidos:", [os.path.basename(f) for f in self.files])
    return self.validate()
dialogs.FolderScanDialog.exec=fake_exec
w.scan_document(False)
for _ in range(150):
    wait(200)
    if answers: break
ok(w.pdf and w.pdf.page_count==2, f"PDF desde carpeta: {w.pdf.page_count if w.pdf else 0} páginas (blanco quitado, viejo ignorado)")
t0=w.pdf.doc[0].get_text(); t1=w.pdf.doc[1].get_text(); ok("procedimiento" in t0 and "procedimiento" in t1, f"OCR de las páginas recogidas: {t0[:40]!r} | {t1[:40]!r}")
print(answers)
