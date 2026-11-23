# NovoPDF - aplicación sencilla para trabajar con documentos PDF
# Copyright (C) 2026 Jesús Punzón Suero
# SPDX-License-Identifier: AGPL-3.0-or-later

"""1.6.0: núcleo de formularios (core/forms.py y core/formdetect.py).
Ejecutar en una carpeta de trabajo: crea allí los PDF de prueba (mk_forms.py)."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
sys.path.insert(0, HERE)
import pymupdf
import mk_forms
from novopdf.core import formdetect, forms
from novopdf.core.document import PdfDocument

res = []


def ok(c, m):
    res.append(bool(c))
    print(("OK  " if c else "FAIL"), m)


mk_forms.solicitud()
mk_forms.escaneada()
mk_forms.formulario()

# ------------------------------------------------------------------ lectura
pdf = PdfDocument.open("formulario.pdf")
doc = pdf.doc
ok(forms.form_kind(doc) == "xfa_hybrid", f"XFA híbrido detectado ({forms.form_kind(doc)})")
fs = forms.all_fields(doc)
by = {}
for f in fs:
    by.setdefault(f.name, []).append(f)
ok({f.kind for f in fs} == {forms.TEXT, forms.CHECK, forms.RADIO, forms.COMBO, forms.LIST, forms.SIGNATURE},
   "todos los tipos de campo")
ok(by["nombre"][0].required and by["nombre"][0].label == "Nombre del solicitante", "obligatorio y descripción")
ok(by["codigo"][0].readonly and not by["codigo"][0].fillable, "solo lectura")
ok(by["observaciones"][0].multiline, "multilínea")
ok(by["provincia"][0].options == ["Badajoz", "Cáceres"] and by["provincia"][0].value == "Badajoz", "desplegable")
ok(len(by["sexo"]) == 2 and {f.on_state for f in by["sexo"]} == {"Mujer", "Hombre"}, "grupo de opciones con sus valores")
ok(not any(f.value for f in by["sexo"]), "ninguna opción marcada al principio")
order = [f.name for f in fs]
ok(order.index("nombre") < order.index("apellidos") < order.index("provincia") < order.index("firma"), "orden de lectura")

# ------------------------------------------------------------------ rellenar
x = by["nombre"][0]
ok(forms.set_value(doc, 0, x.xref, "María Ñúñez"), "texto rellenado")
ok(not forms.set_value(doc, 0, x.xref, "María Ñúñez"), "mismo valor: sin cambios")
ok(forms.form_kind(doc) == "acro", "al rellenar se quita la parte XFA (Acrobat mostraría los datos viejos)")
vals = forms.values(doc)
ok(vals["nombre"] == "María Ñúñez", "valor leído")
dup = [f for f in forms.all_fields(doc) if f.name == "nombre"]
ok(len(dup) == 2 and all(f.value == "María Ñúñez" for f in dup), "el campo repetido muestra el mismo dato")
txt = doc[0].get_text()
ok(txt.count("María Ñúñez") == 2, "las dos apariciones se ven en la página")
mujer = [f for f in by["sexo"] if f.on_state == "Mujer"][0]
hombre = [f for f in by["sexo"] if f.on_state == "Hombre"][0]
forms.set_value(doc, 0, mujer.xref, True)
s = {f.on_state: f.value for f in forms.all_fields(doc) if f.name == "sexo"}
ok(s == {"Mujer": True, "Hombre": False}, f"opción Mujer ({s})")
forms.set_value(doc, 0, hombre.xref, True)
s = {f.on_state: f.value for f in forms.all_fields(doc) if f.name == "sexo"}
ok(s == {"Mujer": False, "Hombre": True}, f"opción Hombre desmarca Mujer ({s})")
ok(forms.values(doc)["sexo"] == "Hombre", "valor del grupo")
forms.set_value(doc, 0, by["acepto"][0].xref, True)
ok([f for f in forms.all_fields(doc) if f.name == "acepto"][0].value is True, "casilla marcada")
forms.set_value(doc, 0, by["provincia"][0].xref, "Cáceres")
ok([f for f in forms.all_fields(doc) if f.name == "provincia"][0].value == "Cáceres", "desplegable cambiado")
forms.set_value(doc, 0, by["idiomas"][0].xref, ["Inglés"])
ok([f for f in forms.all_fields(doc) if f.name == "idiomas"][0].value in ("Inglés", ["Inglés"]), "lista")
forms.set_value(doc, 0, by["observaciones"][0].xref, "Línea uno\nLínea dos")
ok("Línea dos" in doc[0].get_text(), "multilínea con salto de línea")
try:
    forms.set_value(doc, 0, by["codigo"][0].xref, "otro")
    ok(False, "solo lectura no se cambia")
except forms.FormError:
    ok(True, "solo lectura no se cambia")
ok(not forms.missing_required(doc), "obligatorios completos")

# guardar y volver a abrir (como hace NovoPDF: copia sin cifrar y guardado con garbage=3)
pdf.modified = True
pdf.save("/tmp/claude-0/relleno.pdf")
re_ = PdfDocument.open("/tmp/claude-0/relleno.pdf")
v2 = forms.values(re_.doc)
ok(v2["nombre"] == "María Ñúñez" and v2["sexo"] == "Hombre" and v2["acepto"] == "Sí" and v2["provincia"] == "Cáceres",
   f"los valores se conservan al guardar ({v2})")

# vaciar
n = forms.reset(re_.doc)
v3 = forms.values(re_.doc)
ok(n >= 5 and v3["nombre"] == "" and v3["sexo"] == "" and v3["acepto"] == "No", f"vaciar el formulario ({n})")
ok({f.name for f in forms.missing_required(re_.doc)} == {"nombre", "acepto"}, "obligatorios sin rellenar")

# aplanar
pdf2 = PdfDocument.open("/tmp/claude-0/relleno.pdf")
k = forms.flatten(pdf2.doc)
left = forms.all_fields(pdf2.doc)
ok(k >= 9 and [f.kind for f in left] == [forms.SIGNATURE], f"aplanar deja solo la firma vacía ({k}, {[f.name for f in left]})")
ok("María Ñúñez" in pdf2.doc[0].get_text(), "el texto rellenado queda en la página")

# ------------------------------------------------------------------ crear y modificar
d = pymupdf.open()
p = d.new_page()
x1 = forms.add_field(d, 0, forms.TEXT, pymupdf.Rect(100, 100, 300, 118), name="Nombre:", label="Nombre")
x2 = forms.add_field(d, 0, forms.TEXT, pymupdf.Rect(100, 130, 300, 148), name="Nombre")
ok([f.name for f in forms.all_fields(d)] == ["Nombre", "Nombre 2"], "nombres únicos y limpios")
r1 = forms.add_field(d, 0, forms.RADIO, pymupdf.Rect(100, 160, 112, 172), name="Opción", export="Sí")
r2 = forms.add_field(d, 0, forms.RADIO, pymupdf.Rect(150, 160, 162, 172), name="Opción", export="No")
grp = [f for f in forms.all_fields(d) if f.kind == forms.RADIO]
ok(len(grp) == 2 and {f.name for f in grp} == {"Opción"} and {f.on_state for f in grp} == {"Si", "No"},
   f"grupo de opciones creado ({[(f.name, f.on_state) for f in grp]})")
forms.set_value(d, 0, r2, True)
forms.set_value(d, 0, r1, True)
ok([f.value for f in forms.all_fields(d) if f.kind == forms.RADIO] == [True, False], "las opciones creadas se excluyen")
c = forms.add_field(d, 0, forms.COMBO, pymupdf.Rect(100, 190, 250, 208), name="Provincia", options=["Badajoz", "Cáceres"])
l = forms.add_field(d, 0, forms.LIST, pymupdf.Rect(100, 220, 250, 280), name="Idioma", options=["Español", "Inglés"])
ch = forms.add_field(d, 0, forms.CHECK, pymupdf.Rect(100, 300, 112, 312), name="Acepto")
sg = forms.add_field(d, 0, forms.SIGNATURE, pymupdf.Rect(100, 330, 300, 390), name="Firma")
ok(len(forms.all_fields(d)) == 8, "todos los tipos creados")
forms.update_field(d, 0, c, options=["Badajoz", "Cáceres", "Otra"], required=True, label="Provincia de residencia")
f = [f for f in forms.all_fields(d) if f.xref == c][0]
ok(f.options == ["Badajoz", "Cáceres", "Otra"] and f.required and f.label == "Provincia de residencia", "propiedades cambiadas")
forms.update_field(d, 0, x1, multiline=True, fontsize=9, max_len=20)
f = [f for f in forms.all_fields(d) if f.xref == x1][0]
ok(f.multiline and f.fontsize == 9 and f.max_len == 20, "multilínea, tamaño y longitud")
try:
    forms.update_field(d, 0, x2, name="Nombre")
    ok(False, "no se permiten nombres repetidos")
except forms.FormError:
    ok(True, "no se permiten nombres repetidos")
forms.move_field(d, 0, x2, pymupdf.Rect(320, 130, 500, 150))
ok(abs([f for f in forms.all_fields(d) if f.xref == x2][0].rect.x0 - 320) < 0.5, "campo movido")
forms.move_field(d, 0, x2, pymupdf.Rect(560, 130, 740, 150))
ok([f for f in forms.all_fields(d) if f.xref == x2][0].rect.x1 <= d[0].rect.x1 + 0.5, "no sale de la página")
nx = forms.duplicate_field(d, 0, ch)
ok(len(forms.all_fields(d)) == 9 and [f for f in forms.all_fields(d) if f.xref == nx][0].name == "Acepto 2", "duplicar")
forms.delete_field(d, 0, nx)
forms.delete_field(d, 0, l)
ok(len(forms.all_fields(d)) == 7, "eliminar")
af = d.xref_get_key(d.pdf_catalog(), "AcroForm/Fields")[1]
ok(str(l) not in af.replace(" ", " "), "el campo eliminado sale de la lista del formulario")
forms.update_field(d, 0, r2, export="Quizá")
ok({f.on_state for f in forms.all_fields(d) if f.kind == forms.RADIO} == {"Si", "Quiza"}, "valor de una opción cambiado")
# página girada: el campo aparece donde se dibuja
p.set_rotation(90)
xr = forms.add_field(d, 0, forms.TEXT, pymupdf.Rect(50, 60, 250, 80), name="Girado")
f = [f for f in forms.all_fields(d) if f.xref == xr][0]
ok(abs(f.rect.x0 - 50) < 0.5 and abs(f.rect.y0 - 60) < 0.5, f"página girada ({f.rect})")
data = d.tobytes(garbage=3)
d2 = pymupdf.open(stream=data)
ok(len(forms.all_fields(d2)) == 8, "se conserva al guardar")

# ------------------------------------------------------------------ detección automática
d = pymupdf.open("solicitud.pdf")
found = formdetect.detect(d)[0]
names = [p.name for p in found]
kinds = {p.name: p.kind for p in found}
print("   detectados:", names)
for n in ("Nombre", "DNI", "Domicilio", "Correo electrónico", "Teléfono", "Primer apellido", "Segundo apellido",
          "Centro", "Observaciones", "Día", "Mes", "Año"):
    ok(n in names, f"detecta «{n}»")
ok(kinds.get("Firma del solicitante") == forms.SIGNATURE, "detecta la firma")
ok(sum(1 for p in found if p.kind == forms.CHECK) == 5, "detecta 3 casillas dibujadas y 2 ☐")
ok(names.count("Asignatura") == 2 and names.count("Curso") == 2 and names.count("Créditos") == 2,
   "celdas vacías de la tabla con el nombre de su columna (y no la cabecera)")
ok(not any("Capítulo" in n or "Requisitos" in n or "instrucciones" in n or "ESTUDIOS" in n for n in names),
   "no confunde el índice, el texto subrayado ni el filete con campos")
ok([p for p in found if p.name == "Observaciones"][0].multiline, "recuadro grande: multilínea")
n = formdetect.apply(d, {0: found})
fs = forms.all_fields(d)
ok(n == len(found) == len(fs), f"campos creados ({n})")
ok(len({f.name for f in fs}) == len(fs), "nombres únicos al crear (Asignatura, Asignatura 2…)")
again = formdetect.detect(d).get(0, [])
ok(not again, f"volver a detectar no repite los campos ya creados ({len(again)})")

d = pymupdf.open("solicitud_escaneada.pdf")
found = formdetect.detect(d)[0]
ok(sum(1 for p in found if p.kind == forms.CHECK) == 5, "escaneado: 5 casillas")
ok(sum(1 for p in found if p.kind == forms.TEXT) >= 15, f"escaneado: líneas y celdas ({len(found)})")

# página girada en detección
d = pymupdf.open("solicitud.pdf")
d[0].set_rotation(90)
fr = formdetect.detect(d)[0]
nm = [p for p in fr if p.name == "Nombre"][0]
ok(nm.rect.x0 > 600 and nm.rect.width < nm.rect.height, f"detección en página girada en coordenadas visibles ({nm.rect})")

print(f"\n{sum(res)}/{len(res)}")
sys.exit(0 if all(res) else 1)
