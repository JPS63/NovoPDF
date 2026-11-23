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

"""1.4.0: exportar a Word y a Excel."""
import os, sys, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["NOVOPDF_HOME"] = "/tmp/claude-0/of"
shutil.rmtree("/tmp/claude-0/of", ignore_errors=True)
os.makedirs("/tmp/claude-0/of", exist_ok=True)
sys.path.insert(0, "/home/claude/novopdf/src")
HERE = os.path.dirname(os.path.abspath(__file__))
from PySide6.QtWidgets import QApplication, QMessageBox
app = QApplication(sys.argv); app.setStyle("Fusion")
from novopdf.ui import theme, dialogs
app.setStyleSheet(theme.build_qss())
from novopdf.ui import mainwindow as mw
from novopdf.core import office
import pymupdf
res = []
ok = lambda c, m: (res.append(bool(c)), print(("OK  " if c else "FAIL"), m))
msgs = []
QMessageBox.information = staticmethod(lambda *a, **k: msgs.append(("info", a[2])))
QMessageBox.critical = staticmethod(lambda *a, **k: msgs.append(("error", a[2])))
dialogs.confirm = lambda *a, **k: True
dialogs.ask_save_changes = lambda *a, **k: "discard"
finished = []
QMessageBox.exec = lambda self: (finished.append((self.windowTitle(), self.text())), 0)[1]

# ---------- documento de prueba: título, párrafos justificados, lista, tabla con importes, imagen
SRC = "/tmp/claude-0/of/informe.pdf"
d = pymupdf.open()
pg = d.new_page()
pg.insert_text((150, 70), "Informe de ejecución 2025", fontname="hebo", fontsize=16)
tw = pymupdf.TextWriter(pg.rect)
txt = ("El presente informe recoge la ejecución del presupuesto de gastos del ejercicio, detallando las "
       "obligaciones reconocidas y los pagos realizados por cada capítulo. ") * 3
tw.fill_textbox(pymupdf.Rect(72, 90, 523, 170), txt, font=pymupdf.Font("tiro"), fontsize=11, align=3)
tw.write_text(pg)
y = 190
for t in ["Capítulo 1: gastos de personal.", "Capítulo 2: gastos corrientes.", "Capítulo 6: inversiones."]:
    pg.insert_text((80, y), "•", fontname="symb", fontsize=11)
    pg.insert_text((98, y), t, fontname="tiro", fontsize=11)
    y += 15
rows = [("Capítulo", "Créditos", "Pagos", "% ejec.", "Fecha"),
        ("1. Personal", "95.230.400,00 €", "92.000.100,50 €", "97,78 %", "31/12/2025"),
        ("2. Corrientes", "22.405.120,35 €", "18.004.211,00 €", "88,71 %", "31/12/2025"),
        ("Total", "117.635.520,35 €", "110.004.311,50 €", "93,51 %", "")]
x = [72, 162, 262, 362, 432, 523]
y0 = 260
font = pymupdf.Font("helv")
for i, r in enumerate(rows):
    for j, v in enumerate(r):
        pg.draw_rect(pymupdf.Rect(x[j], y0 + i * 18, x[j + 1], y0 + (i + 1) * 18), color=(0, 0, 0), width=0.6)
        tw = pymupdf.TextWriter(pg.rect)
        tw.append((x[j] + 3, y0 + i * 18 + 13), v, font=font, fontsize=9)
        tw.write_text(pg)
pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 200, 100), 0); pix.set_rect(pix.irect, (47, 91, 216))
pg.insert_image(pymupdf.Rect(200, 360, 400, 460), pixmap=pix)
r = pg.search_for("obligaciones reconocidas")[0]
pg.add_highlight_annot(r)
d.save(SRC)

w = mw.MainWindow(); w.resize(1300, 850); w.show()
w.open_file(SRC); app.processEvents()

plan = {}
def fake_exec(self):
    if plan.get("setup"):
        plan["setup"](self)
    self.out.setText(plan["path"])
    self._try_accept()
    return self.result is not None
dialogs.OfficeExportDialog.exec = fake_exec

def wait():
    t = time.time()
    while time.time() - t < 60:
        app.processEvents()
        wk = getattr(w, "_office_worker", None)
        if wk is not None and wk.isFinished():
            app.processEvents()
            break
        time.sleep(0.02)
    app.processEvents()

# menú Exportar
acts = [a.text() for a in w.b_export.menu().actions() if a.text()]
ok(any("Word" in a for a in acts) and any("Excel" in a for a in acts) and any("Imágenes" in a for a in acts),
   f"menú Exportar: {acts}")

# ---------- Word
plan.update(path="/tmp/claude-0/of/informe.docx", setup=None)
w.export_office("docx"); wait()
ok(os.path.exists(plan["path"]), "se crea el .docx")
ok(finished and "Word" in finished[-1][1], f"mensaje final: {finished[-1][1][:60] if finished else '-'}")
from docx import Document
doc = Document(plan["path"])
text = "\n".join(p.text for p in doc.paragraphs)
ok("Informe de ejecución 2025" in text and "obligaciones reconocidas" in text, "el texto está en el Word")
ok(any(p.text.startswith("•") or p.text.startswith("•") for p in doc.paragraphs), "viñetas")
just = [p for p in doc.paragraphs if p.alignment is not None and int(p.alignment) == 3]
ok(just, "párrafo justificado")
bold = [r for p in doc.paragraphs for r in p.runs if r.bold and "Informe" in r.text]
ok(bold, "título en negrita")
hl = [r for p in doc.paragraphs for r in p.runs if r.font.highlight_color is not None]
ok(hl and "obligaciones" in "".join(r.text for r in hl), "resaltado del PDF → resaltado de Word")
ok(len(doc.tables) == 1 and doc.tables[0].cell(1, 1).text == "95.230.400,00 €", "tabla como tabla de Word")
ok(len(doc.inline_shapes) == 1, "imagen incluida")
fonts = {r.font.name for p in doc.paragraphs for r in p.runs if r.text.strip()}
ok("Times New Roman" in fonts, f"fuentes con nombre de Word: {fonts}")

# ---------- Excel
finished.clear()
plan.update(path="/tmp/claude-0/of/informe.xlsx", setup=None)
w.export_office("xlsx"); wait()
import openpyxl
wb = openpyxl.load_workbook(plan["path"])
ws = wb.worksheets[0]
ok(ws.title.startswith("Pág 1"), f"hoja de la tabla: {ws.title}")
ok(ws["B2"].value == 95230400 and "€" in ws["B2"].number_format, f"importe como número: {ws['B2'].value!r} {ws['B2'].number_format}")
ok(abs(ws["D2"].value - 0.9778) < 1e-9 and "%" in ws["D2"].number_format, "porcentaje como número")
ok(hasattr(ws["E2"].value, "year") and ws["E2"].value.year == 2025, "fecha como fecha")
ok(ws["A1"].font.bold and ws.freeze_panes == "A2", "cabecera en negrita y fija")
ok("1 tabla" in finished[-1][1], f"mensaje: {finished[-1][1][:50]}")
# sin convertir
plan.update(path="/tmp/claude-0/of/informe_txt.xlsx", setup=lambda dl: dl.o_convert.setChecked(False))
w.export_office("xlsx"); wait()
ws = openpyxl.load_workbook(plan["path"]).worksheets[0]
ok(ws["B2"].value == "95.230.400,00 €", "sin convertir: se deja el texto tal cual")
# tabla sin líneas (solo texto alineado): se reconoce como tabla
d2 = pymupdf.open(); p2 = d2.new_page()
for k, (a, b) in enumerate([("Concepto", "Importe"), ("Material", "1.234,56"), ("Viajes", "890,00")]):
    p2.insert_text((72, 100 + k * 16), a, fontsize=10); p2.insert_text((400, 100 + k * 16), b, fontsize=10)
d2.save("/tmp/claude-0/of/sin_tablas.pdf")
w.open_file("/tmp/claude-0/of/sin_tablas.pdf"); app.processEvents()
finished.clear()
plan.update(path="/tmp/claude-0/of/sin_tablas.xlsx", setup=lambda dl: dl.o_convert.setChecked(True))
w.export_office("xlsx"); wait()
ws = openpyxl.load_workbook(plan["path"]).worksheets[0]
ok(ws["A2"].value == "Material" and ws["B2"].value == 1234.56, f"tabla sin líneas: columnas ({ws['A2'].value!r}, {ws['B2'].value!r})")
ok(ws.title.startswith("Pág 1") and ws["A1"].font.bold, f"tabla sin líneas como tabla con cabecera: {ws.title}")
# documento sin tablas (texto corrido): una hoja por página, texto en la columna A
d3 = pymupdf.open(); p3 = d3.new_page()
p3.insert_textbox(pymupdf.Rect(72, 72, 520, 400), "La Universidad desarrollará las actuaciones previstas en el plan. " * 12, fontsize=11)
d3.save("/tmp/claude-0/of/prosa.pdf")
w.open_file("/tmp/claude-0/of/prosa.pdf"); app.processEvents()
finished.clear()
plan.update(path="/tmp/claude-0/of/prosa.xlsx")
w.export_office("xlsx"); wait()
ws = openpyxl.load_workbook(plan["path"]).worksheets[0]
ok(ws.max_column == 1 and ws["A1"].value.startswith("La Universidad"), f"texto corrido: columna A ({ws.max_column} columnas)")
ok("No se han encontrado tablas" in finished[-1][1], "explica que no había tablas")

# ---------- documento escaneado: ofrece reconocer el texto
d3 = pymupdf.open(); p3 = d3.new_page()
src = pymupdf.open(SRC)
p3.insert_image(p3.rect, pixmap=src[0].get_pixmap(dpi=100))
d3.save("/tmp/claude-0/of/escaneado.pdf")
w.open_file("/tmp/claude-0/of/escaneado.pdf"); app.processEvents()
asked = []
def scan_box(self):
    asked.append(self.text())
    for b in self.buttons():
        if "sin reconocer" in b.text():
            self._clicked = b
    return 0
QMessageBox.exec = lambda self: (scan_box(self) if "escaneado" in self.text() else finished.append((self.windowTitle(), self.text()))) and 0
QMessageBox.clickedButton = lambda self: getattr(self, "_clicked", None)
finished.clear()
plan.update(path="/tmp/claude-0/of/escaneado.docx", setup=None)
w.export_office("docx"); wait()
ok(asked and "escaneado" in asked[0], "con un documento escaneado ofrece reconocer el texto")
dd = Document(plan["path"]) if os.path.exists(plan["path"]) else None
ok(dd is not None and len(dd.inline_shapes) == 1, "si no se reconoce, la página va como imagen")

# ---------- copia no permitida
d.save("/tmp/claude-0/of/sin_copia.pdf", encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="jefe", user_pw="",
       permissions=pymupdf.PDF_PERM_PRINT)
w.open_file("/tmp/claude-0/of/sin_copia.pdf"); app.processEvents()
ok(not w.pdf.copy_allowed, "detecta que no se permite copiar")
said = []
dialogs.confirm = lambda *a, **k: (said.append(a[2]), False)[1]
plan.update(path="/tmp/claude-0/of/sin_copia.docx")
w.export_office("docx"); wait()
ok(said and not os.path.exists(plan["path"]), "no exporta sin la contraseña de permisos")

# ---------- find_tables que falla por dentro (devuelve None, visto en Windows con PyMuPDF 2.1)
calls = []
orig_ft = pymupdf.Page.find_tables
def bad_ft(self, **kw):
    calls.append(kw)
    return None if kw.get("use_layout") is False else orig_ft(self, **kw)
pymupdf.Page.find_tables = bad_ft
r = office.find_tables(pymupdf.open(SRC)[0])
ok(len(calls) >= 2 and calls[0].get("use_layout") is False and calls[1] == {} and len(r) == 1,
   "si find_tables falla (devuelve None), se reintenta de la otra forma")
pymupdf.Page.find_tables = lambda self, **kw: None
ok(office.find_tables(pymupdf.open(SRC)[0]) == [], "si sigue fallando, la página se trata sin tablas")
st = office.to_docx(pymupdf.open(SRC), [0], "/tmp/claude-0/of/sin_ft.docx")
ok(st["pages"] == 1 and os.path.exists("/tmp/claude-0/of/sin_ft.docx"), "y la exportación a Word termina igual")
pymupdf.Page.find_tables = orig_ft

# ---------- valores sueltos
P = office.parse_value
ok(P("1.234,56 €") == (1234.56, '#,##0.00 "€"') and P("(1.234,56)")[0] == -1234.56 and P("06071")[1] is None
   and P("2025") == (2025, "0") and P("12,5 %")[0] == 0.125 and P("ES91 2100")[1] is None
   and P("1.119 , 26")[0] == 1119.26, "conversión de valores (también con espacios del OCR)")

print(f"\n{sum(res)}/{len(res)} correctas")
sys.exit(0 if all(res) else 1)
