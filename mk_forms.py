# NovoPDF - aplicación sencilla para trabajar con documentos PDF
# Copyright (C) 2026 Jesús Punzón Suero
# SPDX-License-Identifier: AGPL-3.0-or-later

"""1.6.0: documentos de prueba para formularios (en la carpeta actual).

  solicitud.pdf             impreso sin campos (como un Word pasado a PDF): rayas «____»,
                            puntos «……», líneas dibujadas, recuadros con etiqueta, tabla,
                            casillas dibujadas y ☐, línea de firma; y trampas (índice con
                            puntos, texto subrayado, filete de página) que NO son campos.
  solicitud_escaneada.pdf   la misma página escaneada (imagen a 150 ppp)
  formulario.pdf            formulario rellenable con todos los tipos de campo, grupo de
                            opciones, campo repetido, obligatorios, solo lectura y XFA híbrido.
"""
import pymupdf


def solicitud(path="solicitud.pdf"):
    doc = pymupdf.open()
    p = doc.new_page()                     # A4 595 x 842
    F, B = "helv", "hebo"
    p.insert_text((72, 60), "SOLICITUD DE AYUDA PARA ESTUDIOS", fontname=B, fontsize=14)
    p.draw_line((40, 70), (555, 70), color=(0, 0, 0), width=0.6)       # filete: no es campo
    # 1. rayas con el teclado
    p.insert_text((72, 100), "Nombre: ______________________________", fontname=F, fontsize=11)
    p.insert_text((330, 100), "DNI: ________________", fontname=F, fontsize=11)
    p.insert_text((72, 124), "Domicilio ..............................................................", fontname=F, fontsize=11)
    # 2. líneas dibujadas con etiqueta a la izquierda
    p.insert_text((72, 150), "Correo electrónico:", fontname=F, fontsize=11)
    p.draw_line((175, 152), (400, 152), width=0.7)
    p.insert_text((410, 150), "Teléfono:", fontname=F, fontsize=11)
    p.draw_line((462, 152), (540, 152), width=0.7)
    # 3. recuadros con etiqueta pequeña arriba (estilo impreso oficial)
    for x0, x1, lab in ((72, 300, "Primer apellido"), (305, 540, "Segundo apellido")):
        p.draw_rect(pymupdf.Rect(x0, 170, x1, 200), width=0.6)
        p.insert_text((x0 + 3, 178), lab, fontname=F, fontsize=7)
    p.draw_rect(pymupdf.Rect(72, 205, 540, 225), width=0.6)
    p.insert_text((76, 218), "Centro:", fontname=F, fontsize=9)
    # 4. tabla con cabecera y filas vacías
    xs = [72, 250, 400, 540]
    ys = [245, 262, 280, 298]
    for y in ys:
        p.draw_line((xs[0], y), (xs[-1], y), width=0.5)
    for x in xs:
        p.draw_line((x, ys[0]), (x, ys[-1]), width=0.5)
    for x, h in zip(xs, ("Asignatura", "Curso", "Créditos")):
        p.insert_text((x + 4, 257), h, fontname=B, fontsize=9)
    # 5. casillas dibujadas y glifos
    p.insert_text((72, 325), "Situación:", fontname=F, fontsize=11)
    for k, lab in enumerate(("Matrícula ordinaria", "Familia numerosa", "Discapacidad")):
        x = 140 + k * 140
        p.draw_rect(pymupdf.Rect(x, 315, x + 10, 325), width=0.7)
        p.insert_text((x + 14, 324), lab, fontname=F, fontsize=10)
    tw = pymupdf.TextWriter(p.rect)
    sym = pymupdf.Font(fontbuffer=open(_dejavu(), "rb").read())       # tiene ☐
    tw.append((72, 350), "☐ Acepto las bases de la convocatoria", font=sym, fontsize=10)
    tw.append((300, 350), "☐ Autorizo la consulta de datos", font=sym, fontsize=10)
    tw.write_text(p)
    # 6. texto multilínea en recuadro grande vacío con etiqueta encima
    p.insert_text((72, 375), "Observaciones:", fontname=F, fontsize=11)
    p.draw_rect(pymupdf.Rect(72, 380, 540, 440), width=0.6)
    # 7. trampas: índice con puntos, texto subrayado
    p.insert_text((72, 470), "Capítulo 1. Requisitos ........................................ 12", fontname=F, fontsize=10)
    p.insert_text((72, 490), "Lea atentamente las instrucciones", fontname=F, fontsize=10)
    w = pymupdf.get_text_length("Lea atentamente las instrucciones", fontname=F, fontsize=10)
    p.draw_line((72, 492), (72 + w, 492), width=0.5)       # subrayado de texto: no es campo
    # 8. fecha y firma
    p.insert_text((72, 540), "En Mérida, a ____ de ______________ de 20___", fontname=F, fontsize=11)
    p.draw_line((330, 620), (520, 620), width=0.7)
    p.insert_text((380, 634), "Firma del solicitante", fontname=F, fontsize=9)
    doc.save(path)
    return path


def _dejavu():
    import glob
    for pat in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/**/DejaVuSans.ttf"):
        g = glob.glob(pat, recursive=True)
        if g:
            return g[0]
    raise FileNotFoundError("DejaVuSans.ttf")


def escaneada(src="solicitud.pdf", path="solicitud_escaneada.pdf", dpi=150):
    s = pymupdf.open(src)
    pix = s[0].get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
    d = pymupdf.open()
    p = d.new_page(width=s[0].rect.width, height=s[0].rect.height)
    p.insert_image(p.rect, pixmap=pix)
    d.save(path)
    return path


def formulario(path="formulario.pdf"):
    doc = pymupdf.open()
    p = doc.new_page()
    p.insert_text((72, 60), "Formulario de inscripción", fontname="hebo", fontsize=14)
    W = pymupdf.Widget

    def add(kind, name, rect, **kw):
        w = W()
        w.field_type = kind
        w.field_name = name
        w.rect = pymupdf.Rect(rect)
        for k, v in kw.items():
            setattr(w, k, v)
        p.add_widget(w)
        return w
    labels = [("Nombre", 90), ("Apellidos", 115), ("Observaciones", 140), ("Provincia", 210), ("Idiomas", 235),
              ("Sexo", 310), ("Acepto", 340), ("Código", 365), ("Nombre (repetido)", 390), ("Firma", 420)]
    for t, y in labels:
        p.insert_text((72, y + 12), t + ":", fontname="helv", fontsize=10)
    add(pymupdf.PDF_WIDGET_TYPE_TEXT, "nombre", (180, 90, 450, 108), field_value="", text_font="Helv",
        text_fontsize=0, field_flags=pymupdf.PDF_FIELD_IS_REQUIRED, field_label="Nombre del solicitante")
    add(pymupdf.PDF_WIDGET_TYPE_TEXT, "apellidos", (180, 115, 450, 133), field_value="García", text_font="Helv", text_fontsize=11)
    add(pymupdf.PDF_WIDGET_TYPE_TEXT, "observaciones", (180, 140, 450, 200), field_value="",
        field_flags=pymupdf.PDF_TX_FIELD_IS_MULTILINE, text_font="Helv", text_fontsize=10)
    add(pymupdf.PDF_WIDGET_TYPE_COMBOBOX, "provincia", (180, 210, 330, 228), choice_values=["Badajoz", "Cáceres"],
        field_value="Badajoz", text_font="Helv", text_fontsize=10)
    add(pymupdf.PDF_WIDGET_TYPE_LISTBOX, "idiomas", (180, 235, 330, 295), choice_values=["Español", "Inglés", "Portugués"],
        field_value="", text_font="Helv", text_fontsize=10)
    add(pymupdf.PDF_WIDGET_TYPE_CHECKBOX, "acepto", (180, 340, 192, 352), field_value=False,
        field_flags=pymupdf.PDF_FIELD_IS_REQUIRED)
    add(pymupdf.PDF_WIDGET_TYPE_TEXT, "codigo", (180, 365, 300, 383), field_value="X-001",
        field_flags=pymupdf.PDF_FIELD_IS_READ_ONLY, text_font="Helv", text_fontsize=10)
    add(pymupdf.PDF_WIDGET_TYPE_TEXT, "nombre", (180, 390, 450, 408), field_value="", text_font="Helv", text_fontsize=0)
    add(pymupdf.PDF_WIDGET_TYPE_SIGNATURE, "firma", (180, 420, 400, 480))
    doc.save(path)
    doc.close()
    # grupo de opciones (con forms.add_field, que pone bien los valores) y XFA híbrido
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
    from novopdf.core import forms
    doc = pymupdf.open(path)
    forms.add_field(doc, 0, forms.RADIO, pymupdf.Rect(180, 310, 192, 322), name="sexo", export="Mujer")
    forms.add_field(doc, 0, forms.RADIO, pymupdf.Rect(260, 310, 272, 322), name="sexo", export="Hombre")
    p = doc[0]
    p.insert_text((196, 320), "Mujer", fontname="helv", fontsize=10)
    p.insert_text((276, 320), "Hombre", fontname="helv", fontsize=10)
    xfa = doc.get_new_xref()
    doc.update_object(xfa, "<<>>")
    doc.update_stream(xfa, b"<xdp:xdp xmlns:xdp='http://ns.adobe.com/xdp/'></xdp:xdp>")
    doc.xref_set_key(doc.pdf_catalog(), "AcroForm/XFA", f"{xfa} 0 R")
    doc.save(path + ".tmp", garbage=3)
    doc.close()
    os.replace(path + ".tmp", path)
    return path


if __name__ == "__main__":
    solicitud()
    escaneada()
    formulario()
    print("ok")
