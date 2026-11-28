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

"""1.4.1: editar texto en un documento escaneado (imagen + capa de texto invisible del OCR)."""
import os, sys, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["NOVOPDF_HOME"] = "/tmp/claude-0/se"
shutil.rmtree("/tmp/claude-0/se", ignore_errors=True)
os.makedirs("/tmp/claude-0/se", exist_ok=True)
sys.path.insert(0, "/home/claude/novopdf/src")
from PySide6.QtWidgets import QApplication, QMessageBox
app = QApplication(sys.argv); app.setStyle("Fusion")
from novopdf.ui import theme, dialogs
app.setStyleSheet(theme.build_qss())
from novopdf.ui import mainwindow as mw
from novopdf.core import editing, scanedit
import pymupdf
res = []
ok = lambda c, m: (res.append(bool(c)), print(("OK  " if c else "FAIL"), m))
QMessageBox.critical = staticmethod(lambda *a, **k: print("ERROR", a[2]))
QMessageBox.warning = staticmethod(lambda *a, **k: print("WARN", a[2]))
dialogs.confirm = lambda *a, **k: True
dialogs.ask_save_changes = lambda *a, **k: "discard"

# --- «escaneo»: página impresa en Courier, convertida en imagen con fondo crema, + OCR invisible
LINES = [("Sueldo", "1.179,96"), ("Complemento de Destino", "620,19"), ("Productividad Fija", "481,22")]
src = pymupdf.open(); sp = src.new_page()
sp.draw_rect(sp.rect, color=None, fill=(0.97, 0.96, 0.92))
y = 120
for a, b in LINES:
    sp.insert_text((60, y), a, fontname="cour", fontsize=11, color=(0.15, 0.15, 0.2))
    w = pymupdf.get_text_length(b, fontname="cour", fontsize=11)
    sp.insert_text((300 - w, y), b, fontname="cour", fontsize=11, color=(0.15, 0.15, 0.2))
    y += 14
pix = sp.get_pixmap(dpi=200)
doc = pymupdf.open(); pg = doc.new_page()
pg.insert_image(pg.rect, pixmap=pix)
y = 120
for a, b in LINES:     # capa OCR invisible (Helvetica, como hace Adobe Scan)
    pg.insert_text((60, y), a, fontname="helv", fontsize=11, render_mode=3)
    w = pymupdf.get_text_length(b, fontname="cour", fontsize=11)
    pg.insert_text((300 - w, y), b, fontname="helv", fontsize=11, render_mode=3)
    y += 14
SRC = "/tmp/claude-0/se/escaneo.pdf"
doc.save(SRC)

w = mw.MainWindow(); w.resize(1300, 850); w.show()
w.open_file(SRC); app.processEvents()
plan = {}
seen = {}
def fake(self):
    seen["scanned"] = self.scanned
    seen["family_enabled"] = self.family.isEnabled()
    seen["note"] = self.font_note.text()
    self.edit.setPlainText(self.edit.toPlainText().replace(plan["a"], plan["b"], 1))
    self._try_accept()
    return True
dialogs.TextDialog.exec = fake

def edit(a, b):
    plan.update(a=a, b=b)
    blk = next(x for x in editing.text_blocks(w.pdf.doc[0]) if a in x.text)
    ok(scanedit.is_scanned_block(blk), f"«{a}»: se reconoce como texto de un escaneo")
    w._viewer_action("edit_block", 0, blk); app.processEvents()
    return blk

def vis_spans(page):
    return [s for b in page.get_text("rawdict")["blocks"] if b["type"] == 0 for l in b["lines"] for s in l["spans"]
            if int(s.get("alpha", 255)) > 0]

b1 = edit("Sueldo", "Salario base")
p = w.pdf.doc[0]
ok(seen["scanned"] and not seen["family_enabled"] and "escaneado" in seen["note"], "la ventana avisa de que es un escaneo")
txt = " ".join(p.get_text().split())
ok("Salario base" in txt and "Sueldo" not in txt, "el texto (buscable) cambia")
vs = vis_spans(p)
ok(vs and "Salario" in "".join(c["c"] for s in vs for c in s["chars"]), "el texto nuevo es VISIBLE")
ok(any("Cour" in s["font"] or "cour" in s["font"].lower() or "Mono" in s["font"] for s in vs),
   f"se imita la letra de máquina (fuente: {[s['font'] for s in vs]})")
fills = [d for d in p.get_drawings() if d.get("fill") and abs(d["fill"][0] - 0.97) < 0.03 and abs(d["fill"][2] - 0.92) < 0.04]
ok(fills, f"se tapa la palabra antigua con el color del papel ({[d['fill'] for d in p.get_drawings()][:2]})")
col = vs[0]["color"]
r, g, bb = (col >> 16) & 255, (col >> 8) & 255, col & 255
ok(max(r, g, bb) < 90 and bb >= r, f"color de la letra parecido al del escaneo ({r},{g},{bb})")
# la palabra antigua ya no se ve: en su zona solo hay tinta de la nueva
w2 = pymupdf.get_text_length("Sueldo", fontname="cour", fontsize=11)
clip = pymupdf.Rect(60 + 7 * 6.6, 108, 60 + 12 * 6.6, 124)    # zona de «base», donde antes no había nada
ink = scanedit.measure_ink(p, clip)
ok(ink is not None, "se ve la palabra nueva")
before_ink = scanedit.measure_ink(pymupdf.open(SRC)[0], clip)
ok(before_ink is None, "(antes no había tinta en esa zona)")
# 2) cifra
edit("1.179,96", "1.250,00")
p = w.pdf.doc[0]
ok("1.250,00" in p.get_text() and "1.179,96" not in p.get_text(), "importe cambiado")
# 3) deshacer
w.undo(); app.processEvents()
ok("1.179,96" in w.pdf.doc[0].get_text(), "Deshacer")
# 4) palabra mucho más larga en mitad de línea: se reescribe el resto o se estrecha
edit("Complemento de Destino", "Complemento extraordinario de Destino")
t = " ".join(w.pdf.doc[0].get_text().split())
ok("Complemento extraordinario de Destino" in t and "620,19" in t, "texto más largo en mitad de la línea")
# 5) OCR con el texto DEBAJO de la imagen (texto visible tapado por el escaneo; muy habitual)
doc2 = pymupdf.open(); pg2 = doc2.new_page()
y = 120
for a, b in LINES:
    pg2.insert_text((60, y), a, fontname="helv", fontsize=11)
    wd = pymupdf.get_text_length(b, fontname="cour", fontsize=11)
    pg2.insert_text((300 - wd, y), b, fontname="helv", fontsize=11)
    y += 14
pg2.insert_image(pg2.rect, pixmap=pix)          # la imagen se pinta encima del texto
SRC2 = "/tmp/claude-0/se/escaneo_debajo.pdf"
doc2.save(SRC2)
w.open_file(SRC2); app.processEvents()
pg = w.pdf.doc[0]
blk = next(x for x in editing.text_blocks(pg) if "Productividad" in x.text)
ok(scanedit.is_scanned_block(blk, pg), "texto bajo la imagen: se reconoce como escaneo")
clip = pymupdf.Rect(55, 140, 200, 152)
before = pg.get_pixmap(dpi=150, clip=clip).samples
plan.update(a="Productividad Fija", b="Plus de transporte")
w._viewer_action("edit_block", 0, blk); app.processEvents()
pg = w.pdf.doc[0]
t = " ".join(pg.get_text().split())
ok("Plus de transporte" in t and "Productividad" not in t, "texto bajo la imagen: el texto cambia")
ok(pg.get_pixmap(dpi=150, clip=clip).samples != before, "texto bajo la imagen: el cambio SE VE en la página")
log = pg.get_bboxlog()
last_img = max(k for k, (typ, _b) in enumerate(log) if typ in ("fill-image", "fill-imgmask"))
ok(any(typ == "fill-text" and k > last_img for k, (typ, _b) in enumerate(log)), "el texto nuevo se pinta encima de la imagen")
w.grab().save("/tmp/claude-0/se/ventana.png")
w.pdf.doc[0].get_pixmap(dpi=120, clip=pymupdf.Rect(50, 100, 320, 160)).save("/tmp/claude-0/se/resultado.png")

print(f"\n{sum(res)}/{len(res)} correctas")
sys.exit(0 if all(res) else 1)
