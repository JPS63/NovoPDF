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

import sys, os, pymupdf
sys.path.insert(0, "/home/claude/novopdf/src"); os.environ["NOVOPDF_HOME"]="/home/claude/novopdf/src"
from novopdf.core import signing
from novopdf.core.document import PdfDocument, Protection
choice, s = signing.load_pfx("prueba.pfx", "1234")
print("holder", choice.holder, "|", signing.holder_details(choice.cert), "| issuer", choice.issuer, choice.expired)
try: signing.load_pfx("prueba.pfx","mal"); print("FAIL bad pw accepted")
except signing.SigningError as e: print("OK bad pw:", e)
d = PdfDocument.open("texto.pdf")
d.rotate_pages([1], 90)
signer = signing.signer_for(choice, s)
signing.sign_pdf(d.output_bytes(), "/tmp/claude-0/firmado.pdf", signer, page_index=0, rect=pymupdf.Rect(330, 700, 540, 770), reason="Conformidad", location="Mérida")
data=open("/tmp/claude-0/firmado.pdf","rb").read()
for r in signing.verify_pdf(data): print(r)
# second signature on rotated page
_, s2 = signing.load_pfx("prueba.pfx", "1234")
signing.sign_pdf(data, "/tmp/claude-0/firmado2.pdf", signing.signer_for(choice, s2), page_index=1, rect=pymupdf.Rect(50, 50, 260, 120), reason="Visto bueno")
data2=open("/tmp/claude-0/firmado2.pdf","rb").read()
for r in signing.verify_pdf(data2): print(r.field, r.intact, r.covers_all, r.summary)
x=pymupdf.open("/tmp/claude-0/firmado2.pdf")
for i in (0,1):
    print([ (w.field_name, w.rect) for w in x[i].widgets()])
    x[i].get_pixmap(dpi=60).save(f"/tmp/claude-0/sig{i}.png")
x[0].get_pixmap(dpi=200, clip=pymupdf.Rect(320,690,550,780)).save("/tmp/claude-0/sigzoom.png")
d2 = PdfDocument.open("/tmp/claude-0/firmado2.pdf"); print("has_signatures", d2.has_signatures(), PdfDocument.open("texto.pdf").has_signatures())
# tamper
t = bytearray(data); i = t.find(b"Vicegerencia"); 
# encrypted doc signing
d.protection = Protection(enabled=True, user_pw="abc", owner_pw="own")
enc, pw = d.bytes_for_signing(); print("pw", pw)
_, s3 = signing.load_pfx("prueba.pfx", "1234")
signing.sign_pdf(enc, "/tmp/claude-0/firmado_enc.pdf", signing.signer_for(choice, s3), page_index=0, rect=pymupdf.Rect(330, 700, 540, 770), password=pw)
e = pymupdf.open("/tmp/claude-0/firmado_enc.pdf"); print("enc needs pass", e.needs_pass)
for r in signing.verify_pdf(open("/tmp/claude-0/firmado_enc.pdf","rb").read(), "abc"): print("enc", r.intact, r.summary)

d3 = PdfDocument.open("/tmp/claude-0/firmado2.pdf"); b, p = d3.bytes_for_signing(); print("incremental reuse original:", b == open("/tmp/claude-0/firmado2.pdf","rb").read())
d3.save("/tmp/claude-0/copia.pdf"); print("save copy keeps sigs:", [r.intact for r in signing.verify_pdf(open("/tmp/claude-0/copia.pdf","rb").read())])
x=pymupdf.open("/tmp/claude-0/firmado2.pdf"); x[1].get_pixmap(dpi=60).save("/tmp/claude-0/sig1.png"); x[0].get_pixmap(dpi=150, clip=pymupdf.Rect(320,690,550,780)).save("/tmp/claude-0/sigzoom.png")
