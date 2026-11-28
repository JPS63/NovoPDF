# NovoPDF - aplicación sencilla para trabajar con documentos PDF
# Copyright (C) 2026 Jesús Punzón Suero
# SPDX-License-Identifier: AGPL-3.0-or-later

"""1.7.0: comentarios (notas, cuadros de texto, resaltar y comentar, respuestas, resuelto, panel,
exportar) y Optimizar escaneados desde la ventana."""
import os, sys, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["NOVOPDF_HOME"] = "/tmp/claude-0/comments"
D = "/tmp/claude-0/comments"
shutil.rmtree(D, ignore_errors=True); os.makedirs(D, exist_ok=True); os.makedirs("/tmp/claude-0/shots", exist_ok=True)
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src")); sys.path.insert(0, HERE)
from PySide6.QtWidgets import QApplication, QFileDialog
from PySide6.QtCore import QPoint, QPointF, Qt, QEvent
from PySide6.QtGui import QMouseEvent
app = QApplication(sys.argv); app.setStyle("Fusion")
from novopdf.ui import theme, dialogs
app.setStyleSheet(theme.build_qss())
from novopdf.ui import mainwindow as mw
from novopdf.ui.viewer import T_SELECT, T_C_NOTE, T_C_TEXT, T_C_HIGHLIGHT
from novopdf.core import comments as C
import pymupdf, mk_scans

res = []
ok = lambda c, m: (res.append(bool(c)), print(("OK  " if c else "FAIL"), m, flush=True))
errors, infos = [], []
dialogs.error = lambda parent, title, text: errors.append(text)
dialogs.info = lambda parent, title, text: infos.append(text)
dialogs.warn = lambda parent, title, text: infos.append(text)
dialogs.confirm = lambda *a, **k: True
dialogs.ask_save_changes = lambda parent, name: "discard"


def pump(n=12):
    for _ in range(n):
        app.processEvents(); time.sleep(0.004)


def mouse(pw, kind, pos, buttons=Qt.LeftButton):
    t = {"press": QEvent.MouseButtonPress, "move": QEvent.MouseMove, "release": QEvent.MouseButtonRelease}[kind]
    btn = Qt.LeftButton if kind != "move" else Qt.NoButton
    ev = QMouseEvent(t, QPointF(pos), QPointF(pw.mapToGlobal(pos)), btn, buttons if kind != "release" else Qt.NoButton,
                     Qt.NoModifier)
    {"press": pw.mousePressEvent, "move": pw.mouseMoveEvent, "release": pw.mouseReleaseEvent}[kind](ev)
    pump(3)


# documento de prueba con texto
doc = pymupdf.open()
p = doc.new_page()
p.insert_text((72, 80), "Informe trimestral de la Vicegerencia", fontname="hebo", fontsize=16)
p.insert_textbox(pymupdf.Rect(72, 100, 523, 300), "El presupuesto del ejercicio asciende a 1.250.000 euros, "
                 "de los que se han ejecutado 830.000 euros a fecha de hoy. Las desviaciones se explican en el "
                 "anexo II y se corregirán en el próximo trimestre.", fontname="tiro", fontsize=11)
doc.new_page().insert_text((72, 80), "Página dos", fontsize=14)
doc.save(f"{D}/informe.pdf")

# el nombre se pregunta la primera vez
asked = []
def author_exec(self):
    asked.append(self.name.text()); self.name.setText("Jesús Punzón"); return True
dialogs.AuthorDialog.exec = author_exec
next_text = {"t": "Revisar esta cifra con contabilidad.", "color": None}
def comment_exec(self):
    self.text.setPlainText(next_text["t"])
    if self.colors and next_text["color"] is not None:
        self.colors.group.button(next_text["color"]).setChecked(True)
    return True
dialogs.CommentDialog.exec = comment_exec

w = mw.MainWindow(); w.resize(1350, 900); w.show(); pump()
w.open_file(f"{D}/informe.pdf"); pump(30)
v = w.viewer
ok(w._comment_count == 0, "sin comentarios al principio")
w.tabs[mw.TAB_COMMENT].click(); pump()
ok(w.ribbon.currentIndex() == mw.TAB_COMMENT and "Nota" in w.hint_text.text(), "pestaña Comentar")

# 1) nota con un clic
w.set_tool(T_C_NOTE); pump()
pw = v.pages[0]; s = v.scale
next_text["color"] = 1
mouse(pw, "press", QPoint(int(450 * s), int(120 * s)))
cs = C.all_comments(w.pdf.doc)
ok(asked and len(cs) == 1 and cs[0].kind == C.NOTE and cs[0].author == "Jesús Punzón"
   and cs[0].text.startswith("Revisar"), f"nota creada con autor ({[(c.kind, c.author) for c in cs]})")
ok(cs[0].color and abs(cs[0].color[2] - C.NOTE_COLORS[1][1][2]) < 0.05, "con el color elegido")
ok(abs(cs[0].rect.x0 - 450) < 1 and abs(cs[0].rect.y0 - 120) < 1, "en el sitio del clic")
ok(w.settings.value("comments/author") == "Jesús Punzón", "el nombre se recuerda")
asked.clear()

# 2) cuadro de texto
def ft_exec(self):
    self.text.setPlainText("Pendiente de la firma del director"); self.size.setValue(12); return True
dialogs.FreeTextDialog.exec = ft_exec
w.set_tool(T_C_TEXT); pump()
a, b = QPoint(int(300 * s), int(330 * s)), QPoint(int(520 * s), int(370 * s))
mouse(pw, "press", a); mouse(pw, "move", b); mouse(pw, "release", b)
ft = [c for c in C.all_comments(w.pdf.doc) if c.kind == C.FREETEXT]
ok(ft and ft[0].text == "Pendiente de la firma del director" and not asked, "cuadro de texto (sin volver a preguntar el nombre)")

# 3) resaltar y comentar
w.set_tool(T_C_HIGHLIGHT); pump()
ws = v.words(0)
k0 = next(n for n, x in enumerate(ws) if x[4].startswith("1.250.000"))
r0 = pymupdf.Rect(ws[k0][:4]); r1 = pymupdf.Rect(ws[k0 + 1][:4])
next_text["t"] = "¿Incluye el IVA?"
mouse(pw, "press", QPoint(int((r0.x0 + 1) * s), int(r0.y0 * s + 3)))
mouse(pw, "move", QPoint(int((r1.x1 - 1) * s), int(r1.y0 * s + 3)))
mouse(pw, "release", QPoint(int((r1.x1 - 1) * s), int(r1.y0 * s + 3)))
hl = [c for c in C.all_comments(w.pdf.doc) if c.kind == C.HIGHLIGHT]
ok(hl and hl[0].text == "¿Incluye el IVA?" and "1.250.000" in hl[0].quoted, f"resaltado con comentario ({hl[0].quoted if hl else None})")

# 4) panel: abrir, responder, editar, resolver
w.set_tool(T_SELECT); pump()
ok("3 comentarios" in w.hint_text.text(), f"aviso de comentarios: «{w.hint_text.text()}»")
note = [c for c in C.all_comments(w.pdf.doc) if c.kind == C.NOTE][0]
mouse(pw, "press", QPoint(int((note.rect.x0 + 6) * s), int((note.rect.y0 + 6) * s)))
mouse(pw, "release", QPoint(int((note.rect.x0 + 6) * s), int((note.rect.y0 + 6) * s)))
ok(w.cpanel.isVisible() and w.cpanel.selected == (0, note.xref), "clic en la nota: se abre el panel con ella")
ok(len(w.cpanel.cards) == 3, f"tres comentarios en el panel ({len(w.cpanel.cards)})")
card = w.cpanel.card_for(0, note.xref)
card._reply(); pump()
card._editor.edit.setPlainText("Ya está revisada.")
w.cpanel.replyRequested.emit(0, note.xref, "Ya está revisada."); pump()
c2 = [c for c in C.all_comments(w.pdf.doc) if c.xref == note.xref][0]
ok(len(c2.replies) == 1 and c2.replies[0].text == "Ya está revisada." and c2.replies[0].author == "Jesús Punzón", "responder")
w.cpanel.editRequested.emit(0, note.xref, "Revisar la cifra (corregido)"); pump()
ok([c for c in C.all_comments(w.pdf.doc) if c.xref == note.xref][0].text == "Revisar la cifra (corregido)", "editar el comentario")
w.cpanel.resolveRequested.emit(0, note.xref, True); pump()
ok([c for c in C.all_comments(w.pdf.doc) if c.xref == note.xref][0].resolved, "marcar como resuelto")
ok("1 de" not in w.cpanel.title.text() and "2 de 3" in w.cpanel.title.text(), f"título del panel: {w.cpanel.title.text()}")
w.cpanel.show_resolved.setChecked(False); pump()
ok(len(w.cpanel.cards) == 2, "ocultar los resueltos")
w.cpanel.show_resolved.setChecked(True); pump(20)
s = v.scale            # el panel estrecha la vista: cambia el zoom (ajustar al ancho)
tip = v.tooltip_at(pw, QPoint(int((note.rect.x0 + 6) * s), int((note.rect.y0 + 6) * s)))
ok("Jesús Punzón" in tip and "corregido" in tip and "1 respuesta" in tip, f"información al pasar el ratón ({tip!r})")
w.grab().save("/tmp/claude-0/shots/comentarios.png")

# 5) mover la nota arrastrándola
w.set_tool(T_C_NOTE); pump()
c0 = QPoint(int((note.rect.x0 + 6) * s), int((note.rect.y0 + 6) * s))
mouse(pw, "press", c0); mouse(pw, "move", c0 + QPoint(0, int(60 * s))); mouse(pw, "release", c0 + QPoint(0, int(60 * s)))
moved = [c for c in C.all_comments(w.pdf.doc) if c.xref == note.xref][0]
ok(abs(moved.rect.y0 - note.rect.y0 - 60) < 2 and len(moved.replies) == 1, "arrastrar mueve la nota (con su respuesta)")
w.undo(); pump()
ok(abs([c for c in C.all_comments(w.pdf.doc) if c.xref == note.xref][0].rect.y0 - note.rect.y0) < 1, "Ctrl+Z la devuelve")

# 6) guardar y volver a abrir (otro lector vería lo mismo)
w.set_tool(T_SELECT)
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (f"{D}/informe_comentado.pdf", ""))
mw.MainWindow.save_as(w); pump()
x = pymupdf.open(f"{D}/informe_comentado.pdf")
cs = C.all_comments(x)
ok(len(cs) == 3 and any(c.resolved for c in cs) and sum(len(c.replies) for c in cs) == 1, "guardados en el PDF")
sub = {a.type[1]: a for a in x[0].annots()}
ok({"Text", "FreeText", "Highlight"} <= set(sub), f"anotaciones estándar ({sorted(sub)})")
irt = [a for a in x[0].annots() if x.xref_get_key(a.xref, "IRT")[0] == "xref"]
ok(len(irt) == 2 and any(x.xref_get_key(a.xref, "State")[1] == "Completed" for a in irt), "respuesta y estado con /IRT (como Acrobat)")
ok(all(x.xref_get_key(a.xref, "M")[0] == "string" and x.xref_get_key(a.xref, "CreationDate")[0] == "string"
       for a in x[0].annots() if a.type[1] in ("Text", "FreeText")), "con fechas de creación y modificación")

# 7) exportar a Excel
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (f"{D}/comentarios.xlsx", ""))
w.export_comments(); pump()
from openpyxl import load_workbook
ws_ = load_workbook(f"{D}/comentarios.xlsx").active
rows = [[c.value for c in r] for r in ws_.iter_rows()]
ok(rows[0][:3] == ["Página", "Tipo", "Autor"] and len(rows) == 4 and any("Ya está revisada" in str(r[6]) for r in rows),
   "exportar la lista de comentarios a Excel")

# 8) eliminar
ftc = [c for c in C.all_comments(w.pdf.doc) if c.kind == C.FREETEXT][0]
w.cpanel.deleteRequested.emit(0, ftc.xref); pump()
ok(not [c for c in C.all_comments(w.pdf.doc) if c.kind == C.FREETEXT], "eliminar un comentario")
w.cpanel.deleteRequested.emit(0, note.xref); pump()
ok(len(C.all_comments(w.pdf.doc)) == 1 and len(list(w.pdf.doc[0].annots())) == 1, "eliminar la nota con su respuesta y su estado")

# 9) optimizar escaneados desde la ventana
cwd = os.getcwd(); os.chdir(D)
mk_scans.escaneo_malo()
os.chdir(cwd)
w.open_file(f"{D}/escaneo_malo.pdf"); pump(30)
from PySide6.QtWidgets import QPushButton
ok(w._scanned and "Optimizar" in [b.text() for b in w.hint.findChildren(QPushButton) if b.isVisible()],
   "documento escaneado: se ofrece Optimizar")
def opt_exec(self):
    self.update_preview(); pump()
    opt_exec.info = self.info.text()
    self.ocr.setChecked(True)
    return True
dialogs.OptimizeDialog.exec = opt_exec
w.optimize_scans()
t0 = time.time()
while time.time() - t0 < 240 and not any("optimizado" in i for i in infos):
    pump(5)
ok("enderezada 2,3°" in opt_exec.info, f"vista previa ({opt_exec.info})")
msg = next((i for i in infos if "optimizado" in i), "")
ok("4 páginas" in msg and "Enderezadas: 4" in msg and "Giradas" in msg, f"resumen: {msg!r}")
ok("Texto reconocido" in msg and len(w.pdf.doc[0].get_text().split()) > 50, "y el texto reconocido después")
ok([w.pdf.doc[i].rotation for i in range(4)] == [0, 180, 270, 0], "páginas giradas a su sitio")
ok("procedimiento" in w.pdf.doc[1].get_text() and "procedimiento" in w.pdf.doc[2].get_text(),
   "el OCR lee bien las páginas que estaban al revés y de lado")
w.grab().save("/tmp/claude-0/shots/optimizado.png")
w.undo(); pump(10); w.undo(); pump(10)
ok(not w.pdf.doc[0].get_text().strip(), "Ctrl+Z deshace el OCR y la optimización")

ok(not errors, f"sin errores ({errors[:2]})")
print(f"\n{sum(res)}/{len(res)}")
sys.exit(0 if all(res) else 1)
