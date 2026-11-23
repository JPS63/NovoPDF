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

"""1.3.1: editar un párrafo sin alterar la página (viñetas, negritas, justificado, marcas)
y resaltar / subrayar / tachar."""
import os, sys, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["NOVOPDF_HOME"] = "/tmp/claude-0/em"
shutil.rmtree("/tmp/claude-0/em", ignore_errors=True)
os.makedirs("/tmp/claude-0/em", exist_ok=True); os.makedirs("/tmp/claude-0/shots", exist_ok=True)
sys.path.insert(0, "/home/claude/novopdf/src")
from PySide6.QtWidgets import QApplication, QMessageBox
app = QApplication(sys.argv); app.setStyle("Fusion")
from novopdf.ui import theme, dialogs
app.setStyleSheet(theme.build_qss())
from novopdf.ui import mainwindow as mw
from novopdf.ui.viewer import T_HIGHLIGHT, T_UNDERLINE, T_STRIKE, T_UNMARK, T_SELECT
from novopdf.core import editing, textedit, markup
import pymupdf
res = []
ok = lambda c, m: (res.append(bool(c)), print(("OK  " if c else "FAIL"), m))
msgs = []
QMessageBox.information = staticmethod(lambda *a, **k: msgs.append(("info", a[2])))
QMessageBox.warning = staticmethod(lambda *a, **k: msgs.append(("warn", a[2])))
QMessageBox.critical = staticmethod(lambda *a, **k: msgs.append(("error", a[2])))
dialogs.confirm = lambda *a, **k: True
dialogs.ask_save_changes = lambda *a, **k: "discard"

# ---------- documento de prueba: lista con viñetas (Symbol), negrita + normal, justificado
SRC = "/tmp/claude-0/em/lista.pdf"
LOREM = ("en ellos una tercera persona garantiza que se hará cargo de las obligaciones del prestamista "
         "si éste incumple. Esta tercera persona se denomina avalista y es titular y responsable del "
         "préstamo junto con el prestamista. El avalista si se ha visto obligado al pago de las cuotas "
         "del préstamo en lugar del prestatario, podrá realizar las acciones legales pertinentes para "
         "cobrar del prestatario las cantidades así pagadas.")
doc = pymupdf.open()
page = doc.new_page()
fb, fr = pymupdf.Font("tibo"), pymupdf.Font("tiro")
y = 90
for k, title in enumerate(["Préstamos con aval personal:", "Préstamos con garantía real:"]):
    page.insert_text((72, y), "•", fontname="symb", fontsize=11)
    # primera línea: título en negrita + texto normal; resto justificado
    tw = pymupdf.TextWriter(page.rect)
    words = LOREM.split()
    lines, cur = [], [title]
    x_lim = 520 - 90
    def width(ws, first):
        s = 0
        for n, w in enumerate(ws):
            f = fb if (first and n < len(title.split())) else fr
            s += f.text_length(w, 11) + (fr.text_length(" ", 11) if n else 0)
        return s
    cur = title.split()
    first = True
    for w in words:
        if width(cur + [w], first) > x_lim:
            lines.append((cur, first)); cur, first = [w], False
        else:
            cur.append(w)
    lines.append((cur, first))
    for n, (ws, first) in enumerate(lines):
        last = n == len(lines) - 1
        nat = width(ws, first)
        extra = 0 if last or len(ws) < 2 else (x_lim - nat) / (len(ws) - 1)
        x = 90
        for m, w in enumerate(ws):
            f = fb if (first and m < len(title.split())) else fr
            tw.append((x, y), w, font=f, fontsize=11)
            x += f.text_length(w, 11)
            if m < len(ws) - 1:
                tw.append((x, y), " ", font=fr, fontsize=11)
                x += fr.text_length(" ", 11) + extra
        y += 14
    tw.write_text(page)
    y += 12
page.insert_text((72, y + 10), "Texto siguiente que no se debe tocar.", fontname="tiro", fontsize=11)
# un resaltado sobre la primera «prestamista»
r = page.search_for("prestamista")[0]
page.add_highlight_annot(r)
doc.save(SRC)

def all_chars(p, skip=None):
    out = set()
    for b in p.get_text("rawdict", flags=textedit.FLAGS)["blocks"]:
        if b["type"]:
            continue
        for ln in b["lines"]:
            for s in ln["spans"]:
                for c in s["chars"]:
                    pt = pymupdf.Point(c["origin"])
                    if skip is not None and skip.contains(pt):
                        continue
                    out.add((round(c["origin"][0], 1), round(c["origin"][1], 1), c["c"], s["font"]))
    return out

w = mw.MainWindow(); w.resize(1300, 850); w.show()
w.open_file(SRC); app.processEvents()

# ---------- 1) editar una palabra en el párrafo con viñeta
plan = {"text": None, "fmt": None}
def fake_text_exec(self):
    if plan["fmt"]:
        plan["fmt"](self)
    self.edit.setPlainText(plan["text"](self.edit.toPlainText()))
    self._try_accept()
    return True
dialogs.TextDialog.exec = fake_text_exec

p = w.pdf.doc[0]
blocks = editing.text_blocks(p)
b = next(b for b in blocks if "aval personal" in b.text)
ok(b.font_name.endswith("Times-Roman") or "Roman" in b.font_name, f"fuente de referencia del párrafo: {b.font_name} (no la de la viñeta)")
area = b.bbox + (-30, -2, 2, 2)
before_out = all_chars(p, area)
fonts_before = {s["font"] for bl in p.get_text("dict")["blocks"] if bl["type"] == 0 for ln in bl["lines"] for s in ln["spans"]}
plan["text"] = lambda t: t.replace("prestamista", "prestatario", 1)
w._viewer_action("edit_block", 0, b); app.processEvents()
p = w.pdf.doc[0]
ok("prestatario si" in " ".join(p.get_text(sort=True).split()), "la palabra se ha cambiado")
ok(all_chars(p, area) == before_out, "el resto de la página no ha cambiado ni un carácter")
bl = next(x for x in editing.text_blocks(p) if "aval personal" in x.text)
lines_txt = bl.text.split("\n")
orig_lines = b.text.split("\n")
ok(len(lines_txt) == len(orig_lines) and lines_txt[0] == orig_lines[0] and lines_txt[3:] == orig_lines[3:],
   "las demás líneas del párrafo quedan igual")
spans = [s for x in p.get_text("dict")["blocks"] if x["type"] == 0 for ln in x["lines"] for s in ln["spans"]]
bullet = [s for s in spans if len(s["text"].strip()) == 1 and s["origin"][0] < 80]
ok(len(bullet) == 2 and all("Symbol" in s["font"] for s in bullet), "las viñetas conservan su fuente (Symbol)")
bold = [s for s in spans if s["text"].strip() == "Préstamos"]
ok(bold and "Bold" in bold[0]["font"], "el título en negrita sigue en negrita")
new_spans = [s for s in spans if "prestatario si" in s["text"] or s["text"].strip() == "prestatario"]
ok(new_spans and all("Bold" not in s["font"] and "Symbol" not in s["font"] for s in new_spans),
   f"la palabra nueva usa la fuente normal del texto ({new_spans[0]['font'] if new_spans else '-'})")
# justificación: los finales de línea siguen alineados
ends = [r.x1 for r in bl.line_rects[:-1] if r.x1 > 100]
ok(max(ends) - min(ends) < 1.5, f"líneas justificadas al mismo margen ({min(ends):.1f}–{max(ends):.1f})")
hl = [a for a in p.annots(types=[pymupdf.PDF_ANNOT_HIGHLIGHT])]
hr = markup._quad_rects(hl[0])[0] if hl else None
target = next(t for t in p.search_for("prestatario") if t.y0 < 110)
ok(hl and abs(hr.x0 - target.x0) < 1.5 and abs(hr.x1 - target.x1) < 2.5, "el resaltado acompaña a la palabra cambiada")
ok("Texto cambiado" in w.msg_label.text(), f"aviso: {w.msg_label.text()!r}")
w.pdf.doc.save("/tmp/claude-0/em/editado1.pdf")

# ---------- 2) deshacer
w.undo(); app.processEvents()
ok("prestamista si" in " ".join(w.pdf.doc[0].get_text(sort=True).split()), "Deshacer recupera el texto original")

# ---------- 3) texto más largo: se recoloca dentro del párrafo sin tocar lo de debajo
p = w.pdf.doc[0]
b = next(b for b in editing.text_blocks(p) if "aval personal" in b.text)
area = b.bbox + (-30, -2, 2, 2)
before_out = all_chars(p, area)
plan["text"] = lambda t: t.replace("pertinentes", "pertinentes ante los juzgados", 1)
w._viewer_action("edit_block", 0, b); app.processEvents()
p = w.pdf.doc[0]
txt = " ".join(p.get_text(sort=True).split())
ok("pertinentes ante los juzgados para" in txt, "texto largo insertado")
ok(all_chars(p, area) == before_out, "lo de fuera del párrafo no se mueve")
bl = next(x for x in editing.text_blocks(p) if "aval personal" in x.text)
ok(bl.bbox.y1 <= b.bbox.y1 + 0.5, "el párrafo no crece hacia abajo (cabe en sus líneas)")

# ---------- 4) texto mucho más largo: pregunta y reduce la letra del párrafo
p = w.pdf.doc[0]
b = next(b for b in editing.text_blocks(p) if "aval personal" in b.text)
area = b.bbox + (-30, -2, 2, 2)
before_out = all_chars(p, area)
asked = []
w._ask_no_space = lambda ns: (asked.append(ns), "shrink")[1]
plan["text"] = lambda t: t + " Además, el avalista puede exigir al deudor principal el reembolso de los gastos, los intereses y los daños sufridos por el pago."
w._viewer_action("edit_block", 0, b); app.processEvents()
p = w.pdf.doc[0]
ok(asked and asked[0].shrink, f"pregunta antes de tapar contenido (propone reducir al {round(asked[0].shrink*100) if asked else 0} %)")
ok("reembolso de los gastos" in " ".join(p.get_text(sort=True).split()), "con la letra reducida, el texto cabe")
ok(all_chars(p, area) == before_out, "y no tapa ni mueve lo de debajo")
# cancelar: no cambia nada
undo_n = len(w.pdf._undo)
b = next(b for b in editing.text_blocks(p) if "aval personal" in b.text)
w._ask_no_space = lambda ns: "cancel"
plan["text"] = lambda t: t + " " + "Texto larguísimo que no cabe de ninguna manera. " * 12
snap = lambda: (w.pdf.doc[0].get_text("rawdict"), [a.rect for a in w.pdf.doc[0].annots()])
data_before = snap()
w._viewer_action("edit_block", 0, b); app.processEvents()
ok(len(w.pdf._undo) == undo_n and snap() == data_before, "si se cancela no cambia nada ni deja un paso de deshacer")

# ---------- 5) cambiar el formato: se reescribe el párrafo con el formato pedido
b = next(b for b in editing.text_blocks(w.pdf.doc[0]) if "Texto siguiente" in b.text)
plan["text"] = lambda t: t.replace("siguiente", "posterior")
plan["fmt"] = lambda d: d.bold.setChecked(True)
w._viewer_action("edit_block", 0, b); app.processEvents()
plan["fmt"] = None
spans = [s for x in w.pdf.doc[0].get_text("dict")["blocks"] if x["type"] == 0 for ln in x["lines"] for s in ln["spans"]]
ok(any("posterior" in s["text"] and (s["flags"] & 16 or "Bold" in s["font"] or "bold" in s["font"].lower()) for s in spans),
   "con el formato cambiado (negrita) se aplica a todo el párrafo")

# ---------- 6) resaltar / subrayar / tachar
w._close_tab(w._cur, ask=False)   # 1.5.0: abrir de nuevo el mismo archivo solo mostraría su pestaña
w.open_file(SRC); app.processEvents()
v = w.viewer
p = w.pdf.doc[0]
n0 = len(list(p.annots()))
ws = v.words(0)
k0 = next(k for k, x in enumerate(ws) if x[4] == "tercera")
v.set_tool(T_SELECT)
v.text_sel = (0, k0, k0 + 1)
w.set_tool(T_HIGHLIGHT); app.processEvents()
p = w.pdf.doc[0]
hls = [a for a in p.annots(types=[pymupdf.PDF_ANNOT_HIGHLIGHT])]
ok(len(hls) == 2, "seleccionar texto y pulsar «Resaltar» lo resalta")
ok(w.tool_buttons[T_HIGHLIGHT].isChecked(), "queda activa la herramienta Resaltar")
r = markup._quad_rects(hls[-1])[0]
t = p.search_for("tercera persona")[0]
ok(abs(r.x0 - t.x0) < 1 and abs(r.x1 - t.x1) < 1, "el resaltado cubre exactamente «tercera persona»")
# arrastrar con la herramienta Subrayar
from PySide6.QtCore import QPointF, Qt, QEvent
from PySide6.QtGui import QMouseEvent
pw = v.pages[0]
def mouse(kind, wx):
    pt = QPointF(wx[0] * v.scale, wx[1] * v.scale)
    ev = QMouseEvent(kind, pt, pt, Qt.LeftButton, Qt.LeftButton if kind != QEvent.MouseButtonRelease else Qt.NoButton, Qt.NoModifier)
    {QEvent.MouseButtonPress: v.on_press, QEvent.MouseMove: v.on_move, QEvent.MouseButtonRelease: v.on_release}[kind](pw, ev)
w.set_tool(T_UNDERLINE)
a1 = p.search_for("avalista")[0]
a2 = p.search_for("titular")[0]
mouse(QEvent.MouseButtonPress, ((a1.x0 + a1.x1) / 2, (a1.y0 + a1.y1) / 2))
mouse(QEvent.MouseMove, ((a2.x0 + a2.x1) / 2, (a2.y0 + a2.y1) / 2))
mouse(QEvent.MouseButtonRelease, ((a2.x0 + a2.x1) / 2, (a2.y0 + a2.y1) / 2))
app.processEvents()
p = w.pdf.doc[0]
uls = list(p.annots(types=[pymupdf.PDF_ANNOT_UNDERLINE]))
ok(len(uls) == 1, "arrastrar con «Subrayar» subraya")
ok(abs(uls[0].colors["stroke"][0] - markup.LINE_COLORS[0][1][0]) < 0.02, "color por defecto del subrayado: rojo")
# color elegido
w._set_mark_color(T_STRIKE, markup.LINE_COLORS[1][1])
ok(v.tool == T_STRIKE, "elegir un color activa la herramienta correspondiente")
k1 = next(k for k, x in enumerate(v.words(0)) if x[4] == "incumple.")
v.text_sel = (0, k1, k1)
i_, words = v.selected_words()
w._viewer_action("mark", 0, (T_STRIKE, words)); app.processEvents()
p = w.pdf.doc[0]
sts = list(p.annots(types=[pymupdf.PDF_ANNOT_STRIKE_OUT]))
ok(len(sts) == 1 and abs(sts[0].colors["stroke"][2] - 0.85) < 0.02, "tachado en el color elegido (azul)")
ok(w.settings.value("mark/strikeout"), "recuerda el color")
# cambiar color y quitar desde el menú contextual
w._viewer_action("mark_color", 0, (hls[-1].xref, markup.HIGHLIGHT_COLORS[1][1])); app.processEvents()
p = w.pdf.doc[0]
g = [a for a in p.annots(types=[pymupdf.PDF_ANNOT_HIGHLIGHT]) if a.xref == hls[-1].xref][0]
ok(abs(g.colors["stroke"][1] - 0.9) < 0.02, "cambiar el color de una marca")
c = (r.x0 + 3, (r.y0 + r.y1) / 2)
mk = v.mark_at(0, pymupdf.Point(c))
ok(mk and mk[0] == hls[-1].xref, "detecta la marca bajo el ratón")
w.set_tool(T_UNMARK)
mouse(QEvent.MouseButtonPress, c); app.processEvents()
p = w.pdf.doc[0]
ok(len(list(p.annots(types=[pymupdf.PDF_ANNOT_HIGHLIGHT]))) == 1, "«Quitar marca» elimina la marca pulsada")
w.undo(); app.processEvents()
ok(len(list(w.pdf.doc[0].annots(types=[pymupdf.PDF_ANNOT_HIGHLIGHT]))) == 2, "Deshacer vuelve a ponerla")
# quitar marcas de una selección
k2 = next(k for k, x in enumerate(v.words(0)) if x[4] == "avalista")
v.text_sel = (0, k2, k2 + 4)
i_, words = v.selected_words()
w._viewer_action("unmark_words", 0, words); app.processEvents()
ok(not list(w.pdf.doc[0].annots(types=[pymupdf.PDF_ANNOT_UNDERLINE])), "quitar las marcas del texto seleccionado")
# las marcas se guardan en el PDF y el texto no cambia
out = "/tmp/claude-0/em/marcado.pdf"
w.pdf.doc.save(out)
o = pymupdf.open(out)
ok(len(list(o[0].annots())) >= 2 and " ".join(o[0].get_text(sort=True).split()) == " ".join(pymupdf.open(SRC)[0].get_text(sort=True).split()),
   "las marcas se guardan y el texto del documento no cambia")
# página girada: la marca cae sobre la palabra
d2 = pymupdf.open(); pg = d2.new_page(); pg.insert_text((72, 100), "Hola mundo bonito", fontsize=14); pg.set_rotation(90)
d2.save("/tmp/claude-0/em/girada.pdf")
w.open_file("/tmp/claude-0/em/girada.pdf"); app.processEvents()
ws = v.words(0)
k = next(k for k, x in enumerate(ws) if x[4] == "mundo")
vis = pymupdf.Rect(ws[k][:4])
ok(w.pdf.doc[0].rect.contains(vis) and vis.width < vis.height, "página girada: palabras en coordenadas visibles")
v.text_sel = (0, k, k)
i_, words = v.selected_words()
w._viewer_action("mark", 0, (T_HIGHLIGHT, words)); app.processEvents()
pg = w.pdf.doc[0]
pix = pg.get_pixmap(dpi=72)
cx, cy = int((vis.x0 + vis.x1) / 2), int((vis.y0 + vis.y1) / 2)
px = pix.pixel(cx + 2, cy)
ok(px[2] < 200 and px[0] > 200, f"página girada: el resaltado se ve sobre la palabra (píxel {px})")
w.grab().save("/tmp/claude-0/shots/marcas.png")

# ---------- 7) duplicar la última página (fallo de 1.3.0)
w._close_tab(w._cur, ask=False)   # 1.5.0: abrir de nuevo el mismo archivo solo mostraría su pestaña
w.open_file(SRC); app.processEvents()
w.thumbs.clearSelection(); w.thumbs.item(0).setSelected(True)
w.duplicate_pages(); app.processEvents()
ok(w.pdf.page_count == 2, "duplicar la última página ya no falla")

print(f"\n{sum(res)}/{len(res)} correctas")
sys.exit(0 if all(res) else 1)
