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

import os, sys, pymupdf
sys.path.insert(0,"/home/claude/novopdf/src"); os.environ["NOVOPDF_HOME"]="/tmp/claude-0/fh"; os.makedirs("/tmp/claude-0/fh", exist_ok=True)
from novopdf.core import fonts, editing
ok=lambda c,m: print(("OK  " if c else "FAIL"), m)
import time; t=time.time(); idx=fonts.installed(); print("índice", len(idx), "familias", round(time.time()-t,2),"s")
t=time.time(); fonts._INDEX=None; fonts.installed(); print("caché", round(time.time()-t,3),"s")
ok("liberationserif" in idx, "Liberation Serif indexada")
print("comunes:", fonts.common_families())
for n in ["ABCDEF+TimesNewRomanPS-BoldMT","ArialMT","Calibri-Bold","Helvetica","BCDEEE+Cambria","Garamond,Italic","CourierNewPSMT"]:
    print("  ", n, "->", fonts.pdf_font_family(n))
SERIF="/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf"
# 1) fuente completa incrustada
d=pymupdf.open(); p=d.new_page()
p.insert_font(fontname="F0", fontfile=SERIF)
p.insert_textbox(pymupdf.Rect(72,72,500,200), "Párrafo con fuente completa incrustada para la prueba.", fontname="F0", fontsize=12)
d.save("/tmp/claude-0/full.pdf"); d=pymupdf.open("/tmp/claude-0/full.pdf"); p=d[0]
b=editing.text_blocks(p)[0]; print("span font:", b.font_name, b.family)
c=fonts.candidates(p, b.font_name, b.family, b.bold, b.italic)
ch=fonts.best_for_text(c, "Texto nuevo con QXZ ¿ñ? €")
ok(ch.kind=="embedded", f"completa -> {ch.label}")
editing.replace_block(p, b, "Texto nuevo con QXZ ¿ñ? €", b.fontsize, b.color, ch)
ok("QXZ ¿ñ? €" in p.get_text() and any("Liberation Serif" in f[3] for f in p.get_fonts()), f"insertado con la fuente: {[f[3] for f in p.get_fonts()]}")
# 2) subconjunto
d=pymupdf.open(); p=d.new_page()
tw=pymupdf.TextWriter(p.rect); tw.fill_textbox(pymupdf.Rect(72,72,500,200),"Hola mundo desde Mérida", font=pymupdf.Font(fontfile=SERIF), fontsize=12); tw.write_text(p)
d.subset_fonts(); d.save("/tmp/claude-0/sub.pdf"); d=pymupdf.open("/tmp/claude-0/sub.pdf"); p=d[0]
print("fonts:", [f[3] for f in p.get_fonts()])
b=editing.text_blocks(p)[0]; print("span font:", b.font_name)
c=fonts.candidates(p, b.font_name, b.family, b.bold, b.italic)
ch1=fonts.best_for_text(c, "Mundo de Hola"); ok(ch1.kind in ("embedded","system"), f"subconjunto (CID sin tabla Unicode), mismas letras -> {ch1.label}")
ch2=fonts.best_for_text(c, "Zaragoza y Kiev"); ok(ch2.kind in ("system","similar") and "Liberation Serif" in ch2.family, f"subconjunto, letras nuevas -> {ch2.label}")
editing.replace_block(p, b, "Zaragoza y Kiev", b.fontsize, b.color, ch2); ok("Zaragoza y Kiev" in p.get_text(), "inserción con la instalada")
# 3) nombres tipo Word sin fuente instalada
c=fonts.candidates(None, "ABCDEF+Calibri", "sans", False, False); print("Calibri ->", [x.label for x in c])
c=fonts.candidates(None, "ArialMT", "sans", True, False); print("ArialMT bold ->", [x.label for x in c])
c=fonts.candidates(None, "FuturaBT-Book", "sans", False, False); print("Futura ->", [x.label for x in c])
# 4) cambio de estilo
c=fonts.candidates(p, b.font_name, b.family, True, False, use_embedded=False); print("negrita ->", [x.label for x in c])
# 5) subset on save
from novopdf.core.document import PdfDocument
pd=PdfDocument.open("/tmp/claude-0/full.pdf"); pg=pd.doc[0]; bb=editing.text_blocks(pg)[0]
ch=fonts.choice_for_family("DejaVu Sans", False, False); editing.add_text(pg, pymupdf.Point(72,400), "Añadido con DejaVu", 14, (0,0,1), ch)
pd.fonts_added=True; pd.modified=True
n1=len(pd.doc.tobytes()); n2=len(pd.output_bytes()); ok(n2 < n1, f"subconjunto al guardar {n1} -> {n2} bytes")
x=pymupdf.open(stream=pd.output_bytes()); ok("Añadido con DejaVu" in x[0].get_text(), "texto intacto tras subconjunto")
x[0].get_pixmap(dpi=100).save("/tmp/claude-0/fonts_render.png")
