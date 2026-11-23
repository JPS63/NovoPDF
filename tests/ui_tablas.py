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

"""1.4.2: tablas reconocidas por la alineación del texto (sin líneas, OCR) y exportación a Excel/Word."""
import os, sys
os.environ["NOVOPDF_HOME"] = "/tmp/claude-0/tb"
os.makedirs("/tmp/claude-0/tb", exist_ok=True)
sys.path.insert(0, "/home/claude/novopdf/src")
import pymupdf, openpyxl
from novopdf.core import office, tablas

res = []
ok = lambda c, m: (res.append(bool(c)), print(("OK  " if c else "FAIL"), m))
F = 9
R = lambda p, x, y, t: p.insert_text((x - pymupdf.get_text_length(t, "helv", F), y), t, fontsize=F)   # alineado a la derecha
L = lambda p, x, y, t: p.insert_text((x, y), t, fontsize=F)

# ---------- 1) tabla sin líneas: celdas de dos renglones, palabra partida, importe partido
doc = pymupdf.open(); p = doc.new_page()
p.insert_text((60, 60), "Ejecución del presupuesto", fontsize=14)
p.insert_textbox(pymupdf.Rect(60, 70, 540, 110),
                 "Los importes se expresan en euros y recogen los créditos definitivos y las obligaciones reconocidas.",
                 fontsize=10)
y = 130
L(p, 60, y, "Código"); L(p, 100, y, "Concepto"); R(p, 260, y, "Créditos"); R(p, 330, y, "Obligacion"); R(p, 400, y, "% ejec.")
R(p, 330, y + 11, "es")      # «Obligaciones» partida en dos renglones
DATA = [("2200", ["Material de", "oficina"], "214.930,20", "165.950,75", "77,21 %"),
        ("2201", ["Mantenimie", "nto de", "edificios"], "234.159,26", "144.515,01", "61,72 %"),
        ("2202", ["Seguros"], "517.046,44", "396.601,27", "76,71 %")]
y += 30
for code, conc, a, b, c in DATA:
    L(p, 60, y, code); R(p, 260, y, a); R(p, 330, y, b); R(p, 400, y, c)
    for k, t in enumerate(conc):
        L(p, 100, y + k * 11, t)
    y += 11 * len(conc) + 6
L(p, 100, y, "Total"); R(p, 260, y, "966.135,9"); R(p, 260, y + 11, "0"); R(p, 330, y, "707.067,03")
y += 40
p.insert_textbox(pymupdf.Rect(60, y, 540, y + 120), ("La Universidad desarrollará durante el ejercicio las actuaciones previstas "
                 "en el plan estratégico con especial atención a la transparencia. ") * 4, fontsize=10, align=3)
for k, t in enumerate(["Capítulo 1: personal.", "Capítulo 2: gastos corrientes.", "Capítulo 6: inversiones."]):
    L(p, 72, y + 140 + k * 13, "•"); L(p, 84, y + 140 + k * 13, t)
SRC = "/tmp/claude-0/tb/sin_lineas.pdf"
doc.save(SRC)

tt = tablas.text_tables(doc[0])
ok(len(tt) == 1, f"una sola tabla (ni el párrafo justificado ni la lista lo son): {len(tt)}")
rows = tt[0].rows
ok(len(rows[0]) == 5 and rows[0][3] == "Obligaciones", f"cabecera de 5 columnas, «Obligaciones» unida: {rows[0]}")
ok(rows[1][1] == "Material de oficina", f"celda de dos renglones en una celda: {rows[1][1]!r}")
ok(rows[2][1] == "Mantenimiento de edificios", f"palabra partida al final del renglón se une: {rows[2][1]!r}")
ok(len(rows) == 5, f"una fila por concepto + cabecera + total: {len(rows)}")
ok(rows[4][1] == "Total" and rows[4][2] == "966.135,90", f"importe partido en dos renglones: {rows[4][2]!r}")

# ---------- Excel
out = "/tmp/claude-0/tb/sin_lineas.xlsx"
st = office.to_xlsx(doc, [0], out)
ws = openpyxl.load_workbook(out).worksheets[0]
ok(st["tables"] == 1 and ws.max_column == 5, f"Excel: una tabla de 5 columnas ({st}, {ws.max_column})")
ok(ws["C2"].value == 214930.2 and ws["E2"].value == 0.7721 and ws["A2"].value == 2200, "Excel: números y porcentajes como números")
ok(ws["A1"].font.bold and ws.freeze_panes == "A2", "Excel: cabecera en negrita y fija")
# modo texto: el párrafo en la columna A y la tabla con sus columnas, en orden
out2 = "/tmp/claude-0/tb/sin_lineas_texto.xlsx"
office.to_xlsx(doc, [0], out2, office.ExcelOptions("text"))
ws = openpyxl.load_workbook(out2).worksheets[0]
vals = [r for r in ws.iter_rows(values_only=True) if any(v is not None for v in r)]
ok(vals[0][0] == "Ejecución del presupuesto" and all(v is None for v in vals[0][1:]), "modo texto: título en la columna A")
hdr = next(i for i, r in enumerate(vals) if r[0] == "Código")
ok(vals[hdr + 1][1] == "Material de oficina" and vals[hdr + 1][2] == 214930.2, "modo texto: la tabla con sus columnas")
just = [r for r in vals if r[0] and str(r[0]).startswith("La Universidad")]
ok(just and all(v is None for v in just[0][1:]), "modo texto: renglón justificado en una sola celda")

# ---------- Word
outd = "/tmp/claude-0/tb/sin_lineas.docx"
office.to_docx(doc, [0], outd)
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
dd = Document(outd)
ok(len(dd.tables) == 1, f"Word: una tabla ({len(dd.tables)})")
tb = dd.tables[0]
ok(tb.style is None or tb.style.name != "Table Grid", "Word: tabla sin cuadrícula (como en el PDF)")
c = tb.rows[1].cells[2]
ok(c.text == "214.930,20" and c.paragraphs[0].alignment == WD_ALIGN_PARAGRAPH.RIGHT, "Word: importes alineados a la derecha")
ok(tb.rows[0].cells[0].paragraphs[0].runs[0].font.bold, "Word: cabecera en negrita")
ok(any(p.text.startswith("•") for p in dd.paragraphs), "Word: la lista sigue siendo lista")

# ---------- 2) OCR: barras «|» de las líneas de la tabla y espacios entre columnas
doc2 = pymupdf.open(); p2 = doc2.new_page()
OCR = [("Código", "Concepto", "Importe", "Fecha"), ("001", "Sueldo base", "1.353,60", "01/10/2026"),
       ("010", "Complemento", "626,40", "01/10/2026"), ("020", "Antigüedad", "78,00", "01/10/2026")]
for k, r in enumerate(OCR):
    y = 100 + 16 * k
    # como el OCR: un solo renglón con espacios y barras entre las celdas
    tw = pymupdf.TextWriter(p2.rect)
    x = {0: 60, 1: 100, 2: 180, 3: 250}
    for j, t in enumerate(r):
        tw.append((x[j], y), t + (" |" if j < 3 else ""), fontsize=10)
    tw.write_text(p2)
tt = tablas.text_tables(doc2[0])
ok(tt and len(tt[0].rows[0]) == 4 and tt[0].rows[1] == ["001", "Sueldo base", "1.353,60", "01/10/2026"],
   f"OCR: las barras «|» separan columnas: {tt[0].rows[1] if tt else '-'}")

# ---------- 3) dos importes muy juntos son dos celdas
doc3 = pymupdf.open(); p3 = doc3.new_page()
for k in range(4):
    y = 100 + 12 * k
    L(p3, 60, y, f"00{k}"); R(p3, 200, y, f"{k + 1}.234,5{k}"); L(p3, 204, y, f"{10 + k},00 %"); L(p3, 300, y, "Texto")
tt = tablas.text_tables(doc3[0])
ok(tt and len(tt[0].rows[0]) == 4, f"importe y porcentaje pegados: dos columnas ({tt[0].rows[0] if tt else '-'})")

# ---------- 4) como en Windows: find_tables avanzado no disponible
orig = pymupdf.Page.find_tables
pymupdf.Page.find_tables = lambda self, **kw: None if not kw else orig(self, **kw)
try:
    st = office.to_xlsx(doc, [0], "/tmp/claude-0/tb/win.xlsx")
    ok(st["tables"] == 1, "sin el análisis avanzado de PyMuPDF se reconoce igual")
finally:
    pymupdf.Page.find_tables = orig

print(f"\n{sum(res)}/{len(res)} correctas")
sys.exit(0 if all(res) else 1)
