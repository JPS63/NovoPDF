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

import pymupdf, os, sys
sys.path.insert(0, "/home/claude/novopdf/src"); os.environ["NOVOPDF_HOME"]="/home/claude/novopdf/src"
from novopdf.core import ocr, editing
from novopdf.core.document import PdfDocument, Protection, PasswordRequired
ok=lambda c,m: print(("OK  " if c else "FAIL"), m)
# OCR rotated
for r in (90,270):
    d = pymupdf.open(f"rot{r}.pdf"); p=d[0]
    n = ocr.ocr_page(p, "spa")
    s = p.search_for("procedimiento")
    ok(n>20 and s and abs(s[0].height-12)<6, f"OCR rot{r}: {n} palabras, {s}")
# Editing text
d = PdfDocument.open("texto.pdf"); pg = d.doc[0]
blocks = editing.text_blocks(pg)
ok(len(blocks)>=2, f"bloques {len(blocks)}: {[b.text[:20] for b in blocks]} fam={[b.family for b in blocks]} bold={[b.bold for b in blocks]}")
b = blocks[1]
d.checkpoint()
editing.replace_block(pg, b, b.text.replace("nuevo procedimiento", "procedimiento renovado y mejorado"), b.fontsize, b.color, editing.base14(b.family, b.bold, b.italic))
t = pg.get_text()
ok("renovado y mejorado" in t and "Vicegerencia" in t and "nuevo procedimiento" not in t.replace("\n"," "), "editar párrafo")
ok(len(editing.page_images(pg))==1, "imagen sigue presente tras editar texto")
editing.add_text(pg, pymupdf.Point(72, 500), "Texto añadido: ñandú €", 14, (1,0,0), "hebo")
ok("ñandú" in pg.get_text(), "añadir texto")
# images
img = editing.page_images(pg)[0]
editing.move_image(pg, img, pymupdf.Rect(300, 600, 400, 700))
ims = editing.page_images(pg); ok(len(ims)==1 and abs(ims[0].bbox.x0-300)<1, f"mover imagen {ims[0].bbox}")
pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0,0,64,64), 0).save("/tmp/claude-0/x.png")
editing.replace_image(pg, ims[0], "/tmp/claude-0/x.png"); ok(len(editing.page_images(pg))==1, "reemplazar imagen")
editing.add_image(pg, pymupdf.Rect(72,720,140,790), "/tmp/claude-0/x.png"); ok(len(editing.page_images(pg))==2, "añadir imagen")
editing.delete_image(pg, editing.page_images(pg)[0]); ok(len(editing.page_images(pg))==1, "eliminar imagen")
editing.erase_area(pg, pymupdf.Rect(60,60,600,95)); ok("Vicegerencia" not in pg.get_text(), "borrar zona")
# undo
d.undo(); ok("nuevo procedimiento" in d.doc[0].get_text().replace("\n"," "), "deshacer")
d.redo(); ok("Vicegerencia" not in d.doc[0].get_text(), "rehacer")
# pages
d = PdfDocument.open("texto.pdf")
d.insert_blank(1); ok(d.page_count==4 and not d.doc[1].get_text(), "insertar en blanco")
d.delete_pages([1]); ok(d.page_count==3, "eliminar")
d.rotate_pages([0], 90); ok(d.doc[0].rotation==90, "girar")
d.move_pages([2], 0); ok("página 3" in d.doc[0].get_text(), "mover página")
d.duplicate_pages([0]); ok(d.page_count==4, "duplicar")
n=d.insert_file(4, "escaneado.pdf"); ok(n==3 and d.page_count==7, "insertar PDF")
n=d.insert_file(0, "/tmp/claude-0/x.png"); ok(n==1 and d.page_count==8, "insertar imagen como página")
d.extract_pages([0,1], "/tmp/claude-0/ext.pdf"); ok(pymupdf.open("/tmp/claude-0/ext.pdf").page_count==2, "extraer")
# passwords
d.protection = Protection(enabled=True, user_pw="abrir123", owner_pw="admin", allow_copy=False, allow_modify=False)
d.save("/tmp/claude-0/prot.pdf")
x = pymupdf.open("/tmp/claude-0/prot.pdf"); ok(x.needs_pass, "cifrado AES-256")
try: PdfDocument.open("/tmp/claude-0/prot.pdf"); ok(False,"pide contraseña")
except PasswordRequired: ok(True,"pide contraseña")
try: PdfDocument.open("/tmp/claude-0/prot.pdf", "mala"); ok(False,"rechaza mala")
except PasswordRequired: ok(True,"rechaza contraseña incorrecta")
e = PdfDocument.open("/tmp/claude-0/prot.pdf", "abrir123"); ok(e.page_count==8 and e.protection.enabled and not e.protection.allow_copy and e.restricted, f"abre con contraseña usuario, restringido={e.restricted}")
e2 = PdfDocument.open("/tmp/claude-0/prot.pdf", "admin"); ok(not e2.restricted, "propietario sin restricciones")
# new docs
ok(PdfDocument.new_blank(3).page_count==3, "nuevo en blanco")
ok(PdfDocument.from_images(["/tmp/claude-0/x.png","/tmp/claude-0/x.png"]).page_count==2, "desde imágenes")
ok(PdfDocument.merge([("texto.pdf",None),("escaneado.pdf",None)]).page_count==6, "combinar")
ok(PdfDocument.open("escaneado.pdf").looks_scanned() and not PdfDocument.open("texto.pdf").looks_scanned(), "detección escaneado")
