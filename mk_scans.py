# NovoPDF - aplicación sencilla para trabajar con documentos PDF
# Copyright (C) 2026 Jesús Punzón Suero
# SPDX-License-Identifier: AGPL-3.0-or-later

"""1.7.0: escaneados «malos» para probar Optimizar escaneados (en la carpeta actual).

  escaneo_malo.pdf   4 páginas a 200 ppp, papel grisáceo con sombra de lomo, desenfoque y ruido:
                     1) inclinada 2,3°; 2) inclinada -1,2° y al revés (180°);
                     3) de lado (90°) e inclinada 0,8°; 4) con un sello de color, inclinada 3,5°.
  Devuelve los ángulos y giros esperados.
"""
import io
import random

import pymupdf
from PIL import Image, ImageDraw, ImageFilter

PARRAFOS = [
    "La Universidad dispone de un procedimiento para la gestión económica de los proyectos de "
    "investigación. Las solicitudes se presentarán en el registro general dentro del plazo "
    "establecido en la convocatoria, acompañadas de la documentación justificativa.",
    "El órgano instructor comprobará que las solicitudes reúnen los requisitos exigidos y, en su "
    "caso, requerirá a los interesados para que subsanen la falta o acompañen los documentos "
    "preceptivos en el plazo de diez días hábiles.",
    "La resolución se publicará en el tablón electrónico y contra ella podrá interponerse recurso "
    "de alzada ante el Rector en el plazo de un mes desde el día siguiente a su publicación.",
    "Los beneficiarios deberán justificar la aplicación de los fondos recibidos mediante la "
    "presentación de las facturas originales y de una memoria de las actividades realizadas.",
]
EXPECT = [(2.3, 0), (-1.2, 180), (0.8, 90), (3.5, 0)]


def _page_image(k, dpi=200):
    doc = pymupdf.open()
    p = doc.new_page()
    p.insert_text((72, 70), f"RESOLUCIÓN N.º {k + 1}/2026", fontname="hebo", fontsize=14)
    y = 100
    for n in range(3):
        for par in PARRAFOS:
            r = pymupdf.Rect(72, y, 523, y + 90)
            p.insert_textbox(r, par, fontname="tiro", fontsize=10.5, align=pymupdf.TEXT_ALIGN_JUSTIFY)
            y += 62
            if y > 760:
                break
    pix = p.get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    if k == 3:     # sello de color
        d = ImageDraw.Draw(img)
        cx, cy = int(img.width * 0.72), int(img.height * 0.85)
        d.ellipse((cx - 140, cy - 140, cx + 140, cy + 140), outline=(30, 60, 200), width=10)
        d.text((cx - 70, cy - 10), "REGISTRO", fill=(30, 60, 200))
    return img


def _degrade(img, angle, turn, seed):
    rnd = random.Random(seed)
    w, h = img.size
    # papel grisáceo con sombra (más oscuro hacia el lomo, a la izquierda)
    shade = Image.linear_gradient("L").rotate(90, expand=True).resize((w, h))
    shade = shade.point(lambda v: int(150 + v * 0.38))       # 150 (lomo) … 247
    paper = Image.merge("RGB", [shade, shade.point(lambda v: int(v * 0.98)), shade.point(lambda v: int(v * 0.92))])
    from PIL import ImageChops
    img = ImageChops.multiply(img, paper)
    img = img.rotate(angle, resample=Image.Resampling.BICUBIC, expand=False, fillcolor=(235, 233, 225))
    img = img.filter(ImageFilter.GaussianBlur(1.1))
    noise = Image.effect_noise((w, h), 18).convert("L").point(lambda v: v // 8)
    img = ImageChops.subtract(img, Image.merge("RGB", [noise] * 3))
    if turn:
        img = img.rotate(-turn, expand=True)                  # escaneada girada en el sentido de las agujas
    return img


def escaneo_malo(path="escaneo_malo.pdf", dpi=200):
    out = pymupdf.open()
    for k, (ang, turn) in enumerate(EXPECT):
        img = _degrade(_page_image(k, dpi), -ang, turn, k)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=85)
        w, h = img.size
        page = out.new_page(width=w * 72 / dpi, height=h * 72 / dpi)
        page.insert_image(page.rect, stream=buf.getvalue())
    out.save(path)
    return path, EXPECT


if __name__ == "__main__":
    print(escaneo_malo())
