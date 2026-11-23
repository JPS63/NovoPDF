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
sys.path.insert(0,"/home/claude/novopdf/src")
from novopdf.core import export
from PIL import Image
ok=lambda c,m: print(("OK  " if c else "FAIL"), m)
data=open("texto.pdf","rb").read()
out="/tmp/claude-0/exp"; shutil.rmtree(out, ignore_errors=True)
ok(export.parse_range("1-2, 3", 3)==[0,1,2] and export.parse_range("2-",3)==[1,2], "rangos")
try: export.parse_range("5",3); ok(False,"rango inválido")
except ValueError as e: ok(True, f"rango inválido: {e}")
for fmt,_,_ in export.FORMATS:
    for mode in ("color","gray","bw"):
        fs=export.export_pages(data,[0,2],out,f"doc_{mode}",fmt,dpi=100,mode=mode)
        good=len(fs)==2 and all(os.path.getsize(f)>0 for f in fs)
        if fmt!="svg":
            im=Image.open(fs[0]); good = good and im.size[0] in (826,827) 
        ok(good, f"{fmt} {mode} {[os.path.basename(f) for f in fs]} {os.path.getsize(fs[0])//1024} KB")
fs=export.export_pages(data,[0,1,2],out,"multi","tif",dpi=150,mode="bw",multipage_tiff=True)
im=Image.open(fs[0]); ok(im.n_frames==3, f"TIFF multipágina {im.n_frames} páginas, {os.path.getsize(fs[0])//1024} KB")
fs=export.export_pages(data,[0],out,"alta","jpg",dpi=300,quality=85); ok(Image.open(fs[0]).info.get("dpi",(0,))[0]>=299, f"jpg 300 ppp {Image.open(fs[0]).size}")
