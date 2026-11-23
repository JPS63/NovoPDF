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

import sys, logging
logging.basicConfig(level=logging.INFO, format="LOG %(message)s")
sys.path.insert(0, r"Z:\home\claude\src\NovoPDF_codigo\src")
import pymupdf
from novopdf.core import printing, printing_win
print("available", printing_win.available())
d = pymupdf.open()
p = d.new_page(); p.insert_text((72, 100), "Pagina vertical NovoPDF", fontsize=24); p.draw_rect((72,150,300,400), color=(1,0,0), fill=(0,0,1))
p2 = d.new_page(width=842, height=595); p2.insert_text((72, 100), "Pagina apaisada", fontsize=24)
n = printing_win.print_pages(d, "NovoPDF_Test", [0, 1], gray=False, copies=2, collate=True, duplex="long", paper_id=9,
                             doc_name="prueba_gdi", progress=lambda k, t: print("prog", k, t) or True)
print("hojas", n)
