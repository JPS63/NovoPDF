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

import pymupdf, sys
# Documento con texto "normal"
d = pymupdf.open()
for i in range(3):
    p = d.new_page()
    p.insert_text((72, 80), f"Informe de la Vicegerencia — página {i+1}", fontsize=18, fontname="hebo", color=(0.1,0.2,0.5))
    p.insert_textbox(pymupdf.Rect(72, 110, 520, 260), "La Universidad de Extremadura dispone de un nuevo procedimiento para la gestión económica. Este párrafo sirve para probar la edición de texto con acentos: áéíóú ñ ü ¿¡ €.", fontsize=11, fontname="tiro")
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0,0,120,80), 0); pix.set_rect(pix.irect,(40,120,200))
    p.insert_image(pymupdf.Rect(72, 300, 252, 420), pixmap=pix)
d.save("texto.pdf")
# Documento escaneado: renderizar texto a imagen
src = pymupdf.open("texto.pdf")
sc = pymupdf.open()
for i, pg in enumerate(src):
    pix = pg.get_pixmap(dpi=150, colorspace=pymupdf.csGRAY)
    np_ = sc.new_page(width=pg.rect.width, height=pg.rect.height)
    np_.insert_image(np_.rect, stream=pix.tobytes("jpeg", jpg_quality=80))
sc[1].set_rotation(90)
sc.save("escaneado.pdf")
