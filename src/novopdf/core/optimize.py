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

"""Optimizar escaneados (como «Mejorar escaneos» de Acrobat): deja cada página escaneada
lista para leerla, imprimirla, reconocer su texto (OCR) o exportarla.

Para cada página escaneada (una imagen que ocupa la página):
  1. orientación: corrige páginas de lado o al revés (giro de la página, sin pérdida);
  2. enderezar: mide la inclinación (perfil de proyección de las líneas de texto, con
     precisión de 0,05°) y gira la imagen;
  3. limpiar el fondo: iguala la iluminación (sombras del lomo, papel amarillento) y deja
     el papel blanco y el texto negro;
  4. nitidez: máscara de enfoque proporcional a la resolución;
  5. color, grises o blanco y negro (auto: grises salvo que la página tenga color) y
     compresión (JPEG o 1 bit), lo que suele reducir mucho el tamaño.
La capa de texto que tuviera (OCR anterior) se quita, porque ya no coincidiría con la
imagen enderezada: después se vuelve a reconocer el texto. Las anotaciones se conservan.

Todo con Pillow (sin numpy, que no va en el portable de Windows).
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

import pymupdf
from PIL import Image, ImageFilter, ImageMath, ImageOps, ImageStat

AUTO, COLOR, GRAY, BW = "auto", "color", "gray", "bw"


@dataclass
class Options:
    orient: bool = True          # páginas de lado o al revés
    deskew: bool = True          # enderezar
    clean: bool = True           # fondo blanco, iluminación uniforme
    sharpen: int = 2             # 0 no, 1 suave, 2 normal, 3 fuerte
    mode: str = AUTO             # auto | color | gray | bw
    dpi: int = 300               # resolución máxima de salida
    quality: int = 80            # calidad JPEG (color y grises)
    despeckle: bool = True       # quitar puntitos (blanco y negro)
    only_scanned: bool = True    # no tocar páginas que no son escaneadas
    language: str = "spa+eng"    # idioma para comprobar la orientación


@dataclass
class PageResult:
    page: int
    done: bool = False
    reason: str = ""             # por qué no se ha tocado
    angle: float = 0.0           # grados enderezados
    turned: int = 0              # giro de orientación aplicado (0, 90, 180, 270)
    mode: str = ""
    dpi: int = 0


@dataclass
class Report:
    pages: list = field(default_factory=list)
    size_before: int = 0
    size_after: int = 0

    @property
    def done(self) -> list:
        return [p for p in self.pages if p.done]


# ====================================================================== análisis de la página
def page_image_info(page: pymupdf.Page):
    """(fracción de la página que cubre la imagen mayor, ppp de esa imagen)."""
    try:
        infos = page.get_image_info()
    except Exception:
        return 0.0, 0
    area = abs(page.rect) or 1
    best, dpi = 0.0, 0
    for im in infos:
        r = pymupdf.Rect(im["bbox"]) & page.rect
        frac = abs(r) / area
        if frac > best:
            best = frac
            w = max(1e-3, pymupdf.Rect(im["bbox"]).width / 72)
            h = max(1e-3, pymupdf.Rect(im["bbox"]).height / 72)
            px_w, px_h = im.get("width", 0), im.get("height", 0)
            # la imagen puede estar girada dentro de la página
            dpi = int(round(max(px_w / w, px_h / h) if w and h else 0))
            if page.rotation in (90, 270) or (px_w > px_h) != (w > h):
                dpi = int(round(max(px_w / h, px_h / w, dpi)))
    return best, dpi


def visible_text_chars(page: pymupdf.Page) -> int:
    """Caracteres de texto que se VEN (no cuenta la capa invisible de un OCR)."""
    n = 0
    try:
        for span in page.get_texttrace():
            if span.get("type", 0) != 3 and not span.get("opacity", 1) == 0:
                n += len(span.get("chars", ()))
    except Exception:
        n = len(page.get_text("text").strip())
    return n


def is_scanned(page: pymupdf.Page) -> bool:
    frac, _ = page_image_info(page)
    return frac >= 0.6 and visible_text_chars(page) < 40


def _render(page: pymupdf.Page, dpi: int, color: bool) -> Image.Image:
    """La página SIN su giro (el giro se conserva y se corrige aparte)."""
    rot = page.rotation
    if rot:
        page.set_rotation(0)
    try:
        cs = pymupdf.csRGB if color else pymupdf.csGRAY
        pix = page.get_pixmap(dpi=dpi, colorspace=cs, alpha=False, annots=False)
    finally:
        if rot:
            page.set_rotation(rot)
    mode = "RGB" if color else "L"
    return Image.frombytes(mode, (pix.width, pix.height), pix.samples, "raw", mode, pix.stride, 1)


def is_colorful(img_rgb: Image.Image) -> bool:
    """¿Tiene color de verdad (sellos, logotipos, subrayados) o es papel con texto?"""
    small = img_rgb.copy()
    small.thumbnail((400, 400))
    hsv = small.convert("HSV")
    s = hsv.getchannel("S")
    v = hsv.getchannel("V")
    # píxeles con saturación clara y no demasiado oscuros ni blancos
    from PIL import ImageChops
    mask = Image.eval(v, lambda x: 255 if 40 < x < 250 else 0)
    sat = Image.eval(s, lambda x: 255 if x > 70 else 0)
    both = ImageChops.multiply(mask, sat)
    frac = ImageStat.Stat(both).mean[0] / 255
    return frac > 0.0008            # un sello o un logotipo pequeño ya cuentan


# ---------------------------------------------------------------------- inclinación
def _ink(img_l: Image.Image, width=900) -> Image.Image:
    """Imagen reducida con la «tinta» en blanco (para medir la inclinación)."""
    w, h = img_l.size
    k = width / max(w, 1)
    small = img_l.resize((max(50, int(w * k)), max(50, int(h * k))), Image.Resampling.BOX) if k < 1 else img_l.copy()
    small = ImageOps.autocontrast(small, cutoff=1)
    return small.point(lambda v: 0 if v > 170 else 255 - v)


def _profile_score(ink: Image.Image, angle: float) -> float:
    r = ink.rotate(angle, resample=Image.Resampling.BILINEAR, expand=False, fillcolor=0)
    prof = r.resize((1, r.height), Image.Resampling.BOX).tobytes()
    return float(sum((prof[i] - prof[i - 1]) ** 2 for i in range(1, len(prof))))


def estimate_skew(img_l: Image.Image, max_angle: float = 10.0) -> tuple[float, float]:
    """(ángulo en grados para enderezar con Image.rotate, confianza). Confianza baja =
    página sin líneas de texto (foto, página en blanco)."""
    ink = _ink(img_l)
    if ImageStat.Stat(ink).mean[0] < 0.6:            # casi en blanco
        return 0.0, 0.0
    base = _profile_score(ink, 0.0)
    best_a, best_s = 0.0, base
    a = -max_angle
    while a <= max_angle + 1e-9:
        s = _profile_score(ink, a)
        if s > best_s:
            best_a, best_s = a, s
        a += 0.5
    lo, hi = best_a - 0.5, best_a + 0.5
    a = lo
    while a <= hi + 1e-9:
        s = _profile_score(ink, a)
        if s > best_s:
            best_a, best_s = a, s
        a += 0.05
    conf = (best_s - base) / base if base else 0.0
    if abs(best_a) < 0.05:
        best_a = 0.0
    return round(best_a, 2), conf


def text_line_strength(img_l: Image.Image) -> float:
    """Fuerza del perfil de líneas horizontales (para saber si el texto va de lado)."""
    ink = _ink(img_l, 700)
    best = 0.0
    for a in (-4, -2, 0, 2, 4):
        best = max(best, _profile_score(ink, a))
    return best / max(1, ink.width * ink.height)


# ---------------------------------------------------------------------- orientación
_WORD = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+")
# Palabras muy frecuentes: en un texto al revés el OCR saca letras, pero casi nunca estas.
_COMMON = set("""de la que el en y los del se las por un para con no una su al es lo como más mas pero
sus le ya o fue este ha si sí porque esta son entre cuando muy sin sobre también hasta hay donde
desde todo nos durante todos uno les ni contra otros ese eso ante ellos esto antes algunos unos
otro otras otra tanto esa estos mucho nada muchos cual poco ella estar estas algunas algo plazo
dentro caso día días mediante podrá será serán según dicho dicha presente artículo
the of and to in is that for it as with was on be by are this from or at an not have has
which their will can all were been also more one its may other into than these such""".split())


def _ocr_words(img_l: Image.Image, language: str, tessdata: str | None) -> int:
    """Palabras frecuentes del idioma que reconoce el OCR en un recorte: con la página
    derecha salen muchas; al revés o de lado, casi ninguna. -1 si el OCR falla."""
    buf = io.BytesIO()
    img_l.save(buf, "PNG")
    tmp = pymupdf.open()
    try:
        w, h = img_l.size
        page = tmp.new_page(width=w * 72 / 150, height=h * 72 / 150)
        page.insert_image(page.rect, stream=buf.getvalue())
        tp = page.get_textpage_ocr(flags=0, language=language, dpi=150, full=True, tessdata=tessdata)
        text = page.get_text("text", textpage=tp)
    except Exception:
        return -1
    finally:
        tmp.close()
    return sum(1 for w in _WORD.findall(text) if w.lower() in _COMMON)


def _densest_band(img_l: Image.Image, frac=0.28) -> Image.Image:
    """Franja horizontal con más texto (para que el OCR de prueba sea rápido)."""
    w, h = img_l.size
    small = img_l.resize((1, min(h, 400)), Image.Resampling.BOX).tobytes()
    n = len(small)
    win = max(1, int(n * frac))
    ink = [255 - v for v in small]
    best_i, best_s, s = 0, -1, sum(ink[:win])
    for i in range(0, n - win + 1):
        if i:
            s += ink[i + win - 1] - ink[i - 1]
        if s > best_s:
            best_i, best_s = i, s
    y0 = int(best_i / n * h)
    y1 = int((best_i + win) / n * h)
    return img_l.crop((0, y0, w, max(y1, y0 + 20)))


def detect_orientation(img_l: Image.Image, language: str = "spa+eng", tessdata: str | None = None) -> int:
    """Giro (en grados, sentido de las agujas) que hay que aplicar a la página para que
    se lea derecha: 0, 90, 180 o 270. 0 si no se puede saber."""
    k = 150 / 300
    w, h = img_l.size
    small = img_l.resize((max(1, int(w * k)), max(1, int(h * k))), Image.Resampling.BOX) if w > 1600 else img_l
    horiz = text_line_strength(small)
    vert = text_line_strength(small.transpose(Image.Transpose.ROTATE_90))
    sideways = vert > horiz * 1.4
    cands = (90, 270) if sideways else (0, 180)

    def view(turn):
        # PIL rota en sentido contrario a las agujas: girar la página «turn» grados
        # en el sentido de las agujas equivale a rotate(-turn)
        im = small.rotate(-turn, expand=True) if turn else small
        return _densest_band(im)
    first = _ocr_words(view(cands[0]), language, tessdata)
    if first < 0:
        return 0
    if first >= 6 and not sideways:
        return 0                                     # se lee bien: no hace falta probar más
    second = _ocr_words(view(cands[1]), language, tessdata)
    if second >= 3 and second >= 2 * first:
        return cands[1]
    if sideways and first >= 3 and first >= 2 * second:
        return cands[0]
    return 0


# ---------------------------------------------------------------------- mejorar la imagen
def _divide(img: Image.Image, bg: Image.Image) -> Image.Image:
    out = ImageMath.lambda_eval(lambda a: a["convert"](a["min"](a["i"] * 255.0 / (a["b"] + 1.0), 255), "L"),
                                i=img, b=bg)
    return out if out.mode == "L" else out.convert("L")


def clean_background(img: Image.Image) -> Image.Image:
    """Ilumina por igual la página: estima el papel (sin el texto) y divide por él."""
    def one(ch: Image.Image) -> Image.Image:
        w, h = ch.size
        sw, sh = max(8, w // 24), max(8, h // 24)
        bg = ch.resize((sw, sh), Image.Resampling.BOX)
        # quitar el texto (lo oscuro) sin extender demasiado las zonas claras del borde
        bg = bg.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MedianFilter(5))
        bg = bg.filter(ImageFilter.GaussianBlur(1.5)).resize((w, h), Image.Resampling.BILINEAR)
        return _divide(ch, bg)
    if img.mode == "RGB":
        return Image.merge("RGB", [one(c) for c in img.split()])
    return one(img)


def levels(img: Image.Image, white: int = 228, gamma: float = 0.85) -> Image.Image:
    """Papel blanco y texto negro: el gris claro pasa a blanco y se estira el resto."""
    gray = img.convert("L") if img.mode != "L" else img
    hist = gray.histogram()
    total = sum(hist)
    acc, black = 0, 0
    for v in range(256):
        acc += hist[v]
        if acc >= total * 0.004:
            black = v
            break
    black = min(black, 90)
    span = max(20, white - black)
    lut = []
    for v in range(256):
        if v >= white:
            lut.append(255)
        elif v <= black:
            lut.append(0)
        else:
            lut.append(int(round(255 * ((v - black) / span) ** gamma)))
    if img.mode == "RGB":
        return img.point(lut * 3)
    return img.point(lut)


def sharpen(img: Image.Image, level: int, dpi: int) -> Image.Image:
    if level <= 0:
        return img
    radius = max(0.6, 1.1 * dpi / 300)
    percent = {1: 60, 2: 110, 3: 170}.get(level, 110)
    return img.filter(ImageFilter.UnsharpMask(radius=radius, percent=percent, threshold=2))


def otsu(img_l: Image.Image) -> int:
    hist = img_l.histogram()
    total = sum(hist)
    sum_all = sum(i * h for i, h in enumerate(hist))
    wb = sb = 0.0
    best, thr = -1.0, 128
    for t in range(256):
        wb += hist[t]
        if wb == 0:
            continue
        wf = total - wb
        if wf == 0:
            break
        sb += t * hist[t]
        mb, mf = sb / wb, (sum_all - sb) / wf
        var = wb * wf * (mb - mf) ** 2
        if var > best:
            best, thr = var, t
    return thr


def to_bw(img_l: Image.Image, despeckle: bool) -> Image.Image:
    if despeckle:
        img_l = img_l.filter(ImageFilter.MedianFilter(3))
    t = min(200, max(90, otsu(img_l) + 10))
    return img_l.point(lambda v: 255 if v > t else 0).convert("1", dither=Image.Dither.NONE)


def enhance(img: Image.Image, angle: float, opts: Options, dpi: int, mode: str) -> Image.Image:
    """Endereza, limpia, enfoca y convierte la imagen de una página."""
    # primero se limpia (sobre la imagen tal cual) y después se gira: las esquinas que
    # deja el giro (blancas) no estropean la estimación del papel
    if opts.clean:
        img = clean_background(img)
        img = levels(img)
    if angle:
        img = img.rotate(angle, resample=Image.Resampling.BICUBIC, expand=False,
                         fillcolor=(255, 255, 255) if img.mode == "RGB" else 255)
    if mode == GRAY and img.mode != "L":
        img = img.convert("L")
    img = sharpen(img, opts.sharpen, dpi)
    if mode == BW:
        img = to_bw(img if img.mode == "L" else img.convert("L"), opts.despeckle)
    return img


def encode(img: Image.Image, quality: int) -> bytes:
    buf = io.BytesIO()
    if img.mode == "1":
        img.save(buf, "PNG", optimize=True)
    else:
        img.save(buf, "JPEG", quality=quality, optimize=True,
                 subsampling=2 if img.mode == "RGB" else 0)
    return buf.getvalue()


# ====================================================================== páginas y documento
def _replace_page_image(doc: pymupdf.Document, page: pymupdf.Page, data: bytes):
    """Deja en la página solo la imagen nueva (sin texto ni imágenes anteriores);
    las anotaciones, enlaces y campos no se tocan."""
    rot = page.rotation
    if rot:
        page.set_rotation(0)
    try:
        for x in page.get_contents():
            doc.update_stream(x, b" ")
        doc.xref_set_key(page.xref, "Resources", "<<>>")
        page.insert_image(page.rect, stream=data, keep_proportion=False)
    finally:
        if rot:
            page.set_rotation(rot)


def analyze_page(page: pymupdf.Page, opts: Options, tessdata=None, dpi_cap: int | None = None):
    """(imagen sin girar, ángulo, giro de orientación, modo, ppp) o None si no procede."""
    frac, native = page_image_info(page)
    dpi = min(dpi_cap or opts.dpi, native or opts.dpi)
    dpi = max(100, int(dpi))
    if opts.mode == AUTO:
        thumb = _render(page, 50, True)
        mode = COLOR if is_colorful(thumb) else GRAY
    else:
        mode = opts.mode
    img = _render(page, dpi, color=(mode == COLOR))
    gray = img if img.mode == "L" else img.convert("L")
    turned = 0
    if opts.orient:
        # la orientación se mide en la página tal como se ve
        view = gray.rotate(-page.rotation, expand=True) if page.rotation else gray
        turned = detect_orientation(view, opts.language, tessdata)
    angle = 0.0
    if opts.deskew:
        view = gray.rotate(-(page.rotation + turned) % 360, expand=True) if (page.rotation + turned) % 360 else gray
        angle, conf = estimate_skew(view)
        if conf < 0.02:
            angle = 0.0
    return img, angle, turned, mode, dpi


def optimize_page(doc: pymupdf.Document, page_index: int, opts: Options, tessdata=None) -> PageResult:
    page = doc[page_index]
    res = PageResult(page=page_index)
    if opts.only_scanned and not is_scanned(page):
        res.reason = "no es una página escaneada"
        return res
    if not page.get_image_info():
        res.reason = "no tiene imágenes"
        return res
    img, angle, turned, mode, dpi = analyze_page(page, opts, tessdata)
    out = enhance(img, angle, opts, dpi, mode)
    _replace_page_image(doc, page, encode(out, opts.quality))
    if turned:
        page.set_rotation((page.rotation + turned) % 360)
    res.done, res.angle, res.turned, res.mode, res.dpi = True, angle, turned, mode, dpi
    return res


def optimize_document_bytes(data: bytes, pages: list[int], opts: Options, progress=None,
                            cancelled=None, tessdata=None) -> tuple[bytes, Report]:
    """Trabaja sobre una copia (para el hilo en segundo plano). Devuelve (PDF, informe)."""
    doc = pymupdf.open(stream=data, filetype="pdf")
    rep = Report(size_before=len(data))
    try:
        for k, i in enumerate(pages):
            if cancelled and cancelled():
                break
            if progress:
                progress(k, len(pages))
            try:
                rep.pages.append(optimize_page(doc, i, opts, tessdata))
            except Exception as e:  # noqa
                rep.pages.append(PageResult(page=i, reason=f"error: {e}"))
        if progress:
            progress(len(pages), len(pages))
        out = doc.tobytes(garbage=3, deflate=True)
    finally:
        doc.close()
    rep.size_after = len(out)
    return out, rep


def preview(doc: pymupdf.Document, page_index: int, opts: Options, dpi: int = 110,
            tessdata=None) -> tuple[Image.Image, Image.Image, PageResult]:
    """(antes, después, resultado) de una página, a baja resolución, sin tocar el documento.
    Mide la inclinación con la resolución real para que coincida con el resultado final."""
    page = doc[page_index]
    res = PageResult(page=page_index)
    before = _render(page, dpi, True)
    if page.rotation:
        before = before.rotate(-page.rotation, expand=True)
    if opts.only_scanned and not is_scanned(page):
        res.reason = "no es una página escaneada"
        return before, before, res
    img, angle, turned, mode, full_dpi = analyze_page(page, opts, tessdata, dpi_cap=min(opts.dpi, 200))
    small = _render(page, dpi, color=(mode == COLOR))
    out = enhance(small, angle, opts, dpi, mode)
    total = (page.rotation + turned) % 360
    if total:
        out = out.rotate(-total, expand=True)
    res.done, res.angle, res.turned, res.mode, res.dpi = True, angle, turned, mode, min(opts.dpi, full_dpi)
    return before, out.convert("RGB"), res
