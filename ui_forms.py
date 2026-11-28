# NovoPDF - aplicación sencilla para trabajar con documentos PDF
# Copyright (C) 2026 Jesús Punzón Suero
# SPDX-License-Identifier: AGPL-3.0-or-later

"""1.6.0: rellenar formularios en la ventana (clic, Tab, casillas, opciones, desplegables),
preparar formularios (crear, mover, propiedades, eliminar), detectar campos, aplanar,
exportar datos a Excel y firmar en un campo de firma."""
import os, sys, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["NOVOPDF_HOME"] = "/tmp/claude-0/forms"
D = "/tmp/claude-0/forms"
shutil.rmtree(D, ignore_errors=True); os.makedirs(D, exist_ok=True); os.makedirs("/tmp/claude-0/shots", exist_ok=True)
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src")); sys.path.insert(0, HERE)
from PySide6.QtWidgets import QApplication, QMessageBox, QFileDialog
from PySide6.QtCore import QPoint, QPointF, Qt, QEvent
from PySide6.QtGui import QMouseEvent, QKeyEvent
from PySide6.QtTest import QTest
app = QApplication(sys.argv); app.setStyle("Fusion")
from novopdf.ui import theme, dialogs
app.setStyleSheet(theme.build_qss())
from novopdf.ui import mainwindow as mw, formfill
from novopdf.ui.viewer import T_SELECT, T_FORM_EDIT, T_F_TEXT, T_F_COMBO, T_F_RADIO, T_F_CHECK
from novopdf.core import forms
import pymupdf, mk_forms

res = []
ok = lambda c, m: (res.append(bool(c)), print(("OK  " if c else "FAIL"), m, flush=True))
errors, infos = [], []
dialogs.error = lambda parent, title, text: errors.append(text)
dialogs.info = lambda parent, title, text: infos.append(text)
dialogs.warn = lambda parent, title, text: infos.append(text)
confirm = {"v": True, "asked": []}
dialogs.confirm = lambda parent, title, text, *a, **k: (confirm["asked"].append(text), confirm["v"])[1]
dialogs.ask_save_changes = lambda parent, name: "discard"
dialogs.ask_password = lambda *a, **k: None


def pump(n=12):
    for _ in range(n):
        app.processEvents(); time.sleep(0.004)


cwd = os.getcwd(); os.chdir(D)
mk_forms.solicitud(); mk_forms.formulario()
os.chdir(cwd)

w = mw.MainWindow(); w.resize(1280, 900); w.show(); pump()
w.open_file(f"{D}/formulario.pdf"); pump(30)
v = w.viewer
ok(w._form_state[1] == 11, f"formulario con 11 widgets ({w._form_state[1]})")
ok("formulario" in w.hint_text.text().lower() and "obligatorio" in w.hint_text.text(), f"barra de ayuda: «{w.hint_text.text()}»")
ok({f.name for f in w._form_state[2]} == {"nombre", "acepto", "sexo"} or {f.name for f in w._form_state[2]} >= {"nombre", "acepto"},
   f"obligatorios sin rellenar: {[f.name for f in w._form_state[2]]}")


def field(name, k=0):
    return [f for f in v.fields(0) if f.name == name][k]


def center(f):
    pw = v.pages[f.page]
    return pw, pw.to_px(f.rect).center().toPoint()


def click(f, at=None):
    pw, p = center(f)
    QTest.mouseClick(pw, Qt.LeftButton, Qt.NoModifier, at or p)
    pump()


def typ(wid, text):
    """Escribir texto (también con tildes: QTest.keyClicks solo admite ASCII)."""
    for ch in text:
        for t in (QEvent.KeyPress, QEvent.KeyRelease):
            QApplication.sendEvent(wid, QKeyEvent(t, 0, Qt.NoModifier, ch))
    pump(2)


def mouse(pw, kind, pos, buttons=Qt.LeftButton, mods=Qt.NoModifier):
    t = {"press": QEvent.MouseButtonPress, "move": QEvent.MouseMove, "release": QEvent.MouseButtonRelease}[kind]
    btn = Qt.LeftButton if kind != "move" else Qt.NoButton
    ev = QMouseEvent(t, QPointF(pos), QPointF(pw.mapToGlobal(pos)), btn, buttons if kind != "release" else Qt.NoButton, mods)
    {"press": pw.mousePressEvent, "move": pw.mouseMoveEvent, "release": pw.mouseReleaseEvent}[kind](ev)
    pump(3)


# ------------------------------------------------------------------ 1) rellenar texto con clic y Tab
ed = v.editor
v.setFocus(); pump()
QTest.keyClick(v, Qt.Key_Tab); pump()
ok(ed.active and ed.field.name == "nombre", "Tab en la página: va al primer campo")
QTest.keyClick(ed.widget, Qt.Key_Escape); pump()
ok(not ed.active, "Esc sale del campo")
click(field("nombre"))
ok(ed.active and isinstance(ed.widget, formfill._Line) and ed.field.name == "nombre", "clic en un campo de texto: se escribe encima")
typ(ed.widget, "Ana Núñez")
QTest.keyClick(ed.widget, Qt.Key_Tab); pump()
ok(forms.values(w.pdf.doc)["nombre"] == "Ana Núñez", "Tab guarda el valor en el PDF")
ok(ed.active and ed.field.name == "apellidos", f"Tab pasa al siguiente campo ({ed.field.name if ed.active else None})")
ok(w.pdf.modified and w.pdf.can_undo(), "documento modificado y se puede deshacer")
ok("•" in w.doc_label.text(), "título con marca de cambios")
typ(ed.widget, "XXXX")
QTest.keyClick(ed.widget, Qt.Key_Escape); pump()
ok(not ed.active and forms.values(w.pdf.doc)["apellidos"] == "García", "Esc descarta lo escrito")
click(field("observaciones"))
ok(isinstance(ed.widget, formfill._Multi), "campo de varias líneas: editor de párrafos")
typ(ed.widget, "Primera línea"); QTest.keyClick(ed.widget, Qt.Key_Return); typ(ed.widget, "Segunda")
# clic fuera de los campos: se guarda
pw = v.pages[0]
QTest.mouseClick(pw, Qt.LeftButton, Qt.NoModifier, QPoint(20, 20)); pump(20)
ok(not ed.active and forms.values(w.pdf.doc)["observaciones"] == "Primera línea\nSegunda", "clic fuera guarda (multilínea)")
# el mismo dato repetido
ok([f.value for f in v.fields(0) if f.name == "nombre"] == ["Ana Núñez", "Ana Núñez"], "el campo repetido se actualiza")

# ------------------------------------------------------------------ 2) casillas y opciones
click(field("acepto"))
ok(field("acepto").value is True, "clic en la casilla la marca")
ok(isinstance(ed.widget, formfill._Box), "la casilla queda con el foco (Espacio la cambia)")
QTest.keyClick(ed.widget, Qt.Key_Space); pump()
ok(field("acepto").value is False, "Espacio desmarca")
QTest.keyClick(ed.widget, Qt.Key_Space); pump()
ok(field("acepto").value is True, "Espacio vuelve a marcar")
mujer = [f for f in v.fields(0) if f.name == "sexo" and f.on_state == "Mujer"][0]
hombre = [f for f in v.fields(0) if f.name == "sexo" and f.on_state == "Hombre"][0]
click(mujer)
ok(forms.values(w.pdf.doc)["sexo"] == "Mujer", "opción Mujer")
click(hombre)
ok(forms.values(w.pdf.doc)["sexo"] == "Hombre", "opción Hombre (Mujer se desmarca)")
click(hombre)
ok(forms.values(w.pdf.doc)["sexo"] == "Hombre", "clic otra vez en la opción marcada: sigue marcada")
w.undo(); pump()
ok(forms.values(w.pdf.doc)["sexo"] == "Mujer", f"Ctrl+Z deshace la última opción ({forms.values(w.pdf.doc)['sexo']})")

# ------------------------------------------------------------------ 3) desplegable y lista
click(field("provincia"))
ok(isinstance(ed.widget, formfill._Combo) and ed.widget.count() == 2, "desplegable con sus opciones")
ed.widget.setCurrentIndex(1); ed.widget.activated.emit(1); pump(20)
ok(forms.values(w.pdf.doc)["provincia"] == "Cáceres", "elegir en el desplegable")
click(field("idiomas"))
ok(isinstance(ed.widget, formfill._List), "cuadro de lista")
it = ed.widget.item(2); ed.widget.setCurrentItem(it); it.setSelected(True); ed.widget.itemClicked.emit(it); pump(20)
ok(forms.values(w.pdf.doc)["idiomas"] == "Portugués", f"elegir en la lista ({forms.values(w.pdf.doc)['idiomas']})")
click(field("codigo"))
ok(not ed.active, "solo lectura: no se abre editor")

# ------------------------------------------------------------------ 4) obligatorios, guardar, zoom
ok(not w._form_state[2], f"ya no faltan obligatorios ({[f.name for f in w._form_state[2]]})")
click(field("apellidos"))
typ(ed.widget, " Pérez")
v.zoom_in(); pump(30)
ok(ed.active and abs(ed.widget.width() - v.pages[0].to_px(field('apellidos').rect).width()) < 3, "al hacer zoom el editor se recoloca")
w.save(); pump()   # guarda también lo que se estaba escribiendo
x = pymupdf.open(f"{D}/formulario.pdf")
vals = forms.values(x)
ok(vals["apellidos"] == "García Pérez" and vals["nombre"] == "Ana Núñez" and vals["acepto"] == "Sí" and vals["sexo"] == "Mujer",
   f"Guardar incluye el campo que se estaba escribiendo ({vals['apellidos']})")
ok(forms.form_kind(x) == "acro", "se guarda sin la parte XFA")
ok(not w.pdf.modified, "guardado")
w.grab().save("/tmp/claude-0/shots/form_relleno.png")

# ------------------------------------------------------------------ 5) firmar en un campo de firma
signed = []
w.sign = lambda i, rect, field_name=None: signed.append((i, rect, field_name))
click(field("firma"))
ok(signed and signed[0][2] == "firma", "clic en el campo de firma: firmar en él")
w.sign = mw.MainWindow.sign.__get__(w)

# ------------------------------------------------------------------ 6) preparar formulario: crear, mover, propiedades, eliminar
w.tabs[mw.TAB_FORM].click(); pump()
ok(w.ribbon.currentIndex() == mw.TAB_FORM, "pestaña Formulario")
w.set_tool(T_FORM_EDIT); pump()
f = field("apellidos")
pw, c = center(f)
mouse(pw, "press", c)
ok(v.sel_field and v.sel_field[1].name == "apellidos", "seleccionar un campo")
ok("seleccionado" in w.hint_text.text(), "barra de ayuda del campo seleccionado")
mouse(pw, "move", c + QPoint(0, 40), Qt.LeftButton)
mouse(pw, "release", c + QPoint(0, 40))
nf = field("apellidos")
ok(nf.rect.y0 > f.rect.y0 + 10, f"arrastrar mueve el campo ({f.rect.y0:.0f} → {nf.rect.y0:.0f})")
w.undo(); pump()
ok(abs(field("apellidos").rect.y0 - f.rect.y0) < 0.5, "Ctrl+Z lo devuelve a su sitio")
# propiedades
orig_exec = dialogs.FieldDialog.exec
def fake_exec(self):
    self.name.setText("Apellidos del solicitante") if hasattr(self.name, "setText") else None
    self.required.setChecked(True)
    return True
dialogs.FieldDialog.exec = fake_exec
w._viewer_action("form_props", 0, field("apellidos").xref); pump()
nf = [f for f in v.fields(0) if f.name == "Apellidos del solicitante"]
ok(nf and nf[0].required and nf[0].value == "García Pérez", "propiedades: nombre y obligatorio cambiados, valor conservado")
# eliminar con Supr
x0 = nf[0]
pw, c = center(x0)
mouse(pw, "press", c); mouse(pw, "release", c)
n0 = len(v.fields(0))
v._delete_key(); pump()
ok(len(v.fields(0)) == n0 - 1, "Supr elimina el campo seleccionado")
w.undo(); pump()
ok(len(v.fields(0)) == n0, "Ctrl+Z lo recupera")
dialogs.FieldDialog.exec = orig_exec

# crear en el impreso sin formulario
w.open_file(f"{D}/solicitud.pdf"); pump(30)
v = w.viewer; ed = v.editor
ok(w._form_state[1] == 0 and "no tiene campos" in w.hint_text.text(), "documento sin campos: invita a detectarlos")
w.set_tool(T_F_TEXT); pump()
pw = v.pages[0]
s = v.scale
a, b = QPoint(int(118 * s), int(88 * s)), QPoint(int(300 * s), int(104 * s))   # sobre «______» de Nombre
mouse(pw, "press", a); mouse(pw, "move", b, Qt.LeftButton); mouse(pw, "release", b)
fs = v.fields(0)
ok(len(fs) == 1 and fs[0].name == "Nombre" and fs[0].kind == forms.TEXT, f"campo de texto dibujado toma su etiqueta ({[f.name for f in fs]})")
ok(v.sel_field and v.sel_field[1].name == "Nombre", "el campo nuevo queda seleccionado")
# casilla con un clic
w.set_tool(T_F_CHECK); pump()
p = QPoint(int(145 * s), int(320 * s))
mouse(pw, "press", p); mouse(pw, "release", p)
ok(any(f.kind == forms.CHECK and f.name == "Matrícula ordinaria" for f in v.fields(0)), "casilla con un clic, con el nombre de su etiqueta")
# desplegable: pide las opciones
def combo_exec(self):
    self.options.setPlainText("Grado\nMáster\nDoctorado")
    return True
dialogs.FieldDialog.exec = combo_exec
w.set_tool(T_F_COMBO); pump()
a, b = QPoint(int(120 * s), int(600 * s)), QPoint(int(260 * s), int(616 * s))
mouse(pw, "press", a); mouse(pw, "move", b, Qt.LeftButton); mouse(pw, "release", b)
cb = [f for f in v.fields(0) if f.kind == forms.COMBO]
ok(cb and cb[0].options == ["Grado", "Máster", "Doctorado"], "desplegable con las opciones escritas")
# botones de opción del mismo grupo
def radio_exec(self):
    self.name.setEditText("Turno"); self.export.setText("Mañana" if not radio_exec.n else "Tarde"); radio_exec.n += 1
    return True
radio_exec.n = 0
dialogs.FieldDialog.exec = radio_exec
w.set_tool(T_F_RADIO); pump()
for x in (120, 200):
    p = QPoint(int(x * s), int(660 * s)); mouse(pw, "press", p); mouse(pw, "release", p)
rd = [f for f in v.fields(0) if f.kind == forms.RADIO]
ok(len(rd) == 2 and {f.name for f in rd} == {"Turno"} and {f.on_state for f in rd} == {"Manana", "Tarde"},
   f"dos opciones en el grupo «Turno» ({[(f.name, f.on_state) for f in rd]})")
dialogs.FieldDialog.exec = orig_exec
w.set_tool(T_SELECT); pump()
click(rd[1]); click(rd[0])
ok(forms.values(w.pdf.doc)["Turno"] in ("Manana", "Tarde") and sum(f.value for f in v.fields(0) if f.kind == forms.RADIO) == 1,
   "las opciones creadas se excluyen al rellenar")

# ------------------------------------------------------------------ 7) detectar campos
for _ in range(10):
    if w.pdf.can_undo():
        w.undo(); pump()
ok(not v.fields(0), "deshacer todo: sin campos")
dialogs.DetectFieldsDialog.exec = lambda self: True
w.form_detect(); pump(20)
n = len(v.fields(0))
ok(n >= 20, f"detectar campos crea los campos ({n})")
ok(v.tool == T_FORM_EDIT and w.ribbon.currentIndex() == mw.TAB_FORM, "y deja «Editar campos» para revisarlos")
w.grab().save("/tmp/claude-0/shots/form_detectados.png")
mouse(v.pages[0], "press", center(field("DNI"))[1]); mouse(v.pages[0], "release", center(field("DNI"))[1])
w.grab().save("/tmp/claude-0/shots/form_seleccionado.png")
w.set_tool(T_SELECT); pump()
click(field("Nombre"))
typ(ed.widget, "María José")
for txt in ("12345678Z", "C/ Mayor, 1", "mjose@example.com", "924 000 000"):
    QTest.keyClick(ed.widget, Qt.Key_Tab); pump(); typ(ed.widget, txt)
QTest.keyClick(ed.widget, Qt.Key_Return); pump()
vals = forms.values(w.pdf.doc)
ok(vals["DNI"] == "12345678Z" and vals["Correo electrónico"] == "mjose@example.com" and vals["Teléfono"] == "924 000 000",
   f"rellenar los campos detectados con Tab ({vals.get('DNI')}, {vals.get('Teléfono')})")
w.grab().save("/tmp/claude-0/shots/form_detectados_rellenos.png")

# ------------------------------------------------------------------ 8) exportar datos y aplanar
out = f"{D}/datos.xlsx"
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (out, ""))
w.export_form_data(False); pump()
from openpyxl import load_workbook
ws = load_workbook(out).active
hdr = [c.value for c in ws[1]]
row = [c.value for c in ws[2]]
ok(hdr[0] == "Archivo" and "DNI" in hdr and row[hdr.index("DNI")] == "12345678Z", "exportar datos a Excel")
w.save_as = lambda: True
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (f"{D}/solicitud_rellena.pdf", ""))
mw.MainWindow.save_as(w); pump()
QFileDialog.getOpenFileNames = staticmethod(lambda *a, **k: ([f"{D}/solicitud_rellena.pdf", f"{D}/formulario.pdf"], ""))
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (f"{D}/varios.xlsx", ""))
w.export_form_data(True); pump()
ws = load_workbook(f"{D}/varios.xlsx").active
ok(ws.max_row == 3 and ws.cell(2, 1).value == "solicitud_rellena.pdf", "datos de varios formularios: una fila por archivo")
w.form_flatten(); pump()
ok(forms.count(w.pdf.doc) == 1 and "12345678Z" in w.pdf.doc[0].get_text(), "aplanar: queda el texto y solo el campo de firma")
w.undo(); pump()
ok(forms.count(w.pdf.doc) > 20, "Ctrl+Z deshace el aplanado")

# ------------------------------------------------------------------ 9) documento protegido que permite rellenar
d = pymupdf.open(f"{D}/formulario.pdf")
perm = pymupdf.PDF_PERM_PRINT | pymupdf.PDF_PERM_FORM
d.save(f"{D}/protegido.pdf", encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="dueño", user_pw="", permissions=perm)
w.open_file(f"{D}/protegido.pdf"); pump(30)
v = w.viewer; ed = v.editor
ok(w.pdf.restricted and w.pdf.form_allowed and v.form_fill, "protegido contra edición pero permite rellenar")
click(field("nombre"))
ed.widget.selectAll(); typ(ed.widget, "Luis"); QTest.keyClick(ed.widget, Qt.Key_Return); pump()
ok(forms.values(w.pdf.doc)["nombre"] == "Luis", "se puede rellenar aunque esté limitada la edición")
w.set_tool(T_FORM_EDIT); pump()
ok(v.tool == T_SELECT, "pero no se pueden cambiar los campos sin la contraseña")

ok(not errors, f"sin errores ({errors[:2]})")
print(f"\n{sum(res)}/{len(res)}")
sys.exit(0 if all(res) else 1)
