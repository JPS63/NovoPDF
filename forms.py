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

"""Formularios PDF (AcroForm): leer, rellenar, crear, modificar y aplanar campos.

Todos los rectángulos que entran y salen de este módulo están en coordenadas
*visibles* de la página (las de la pantalla, con el giro de la página aplicado),
igual que en el visor. PyMuPDF guarda los widgets en coordenadas sin girar.

La detección automática de campos (``detect``) está en core/formdetect.py.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

import pymupdf

TEXT, CHECK, RADIO, COMBO, LIST, SIGNATURE, BUTTON = (
    "text", "check", "radio", "combo", "list", "signature", "button")

KIND_NAMES = {TEXT: "Campo de texto", CHECK: "Casilla de verificación", RADIO: "Botón de opción",
              COMBO: "Lista desplegable", LIST: "Cuadro de lista", SIGNATURE: "Campo de firma",
              BUTTON: "Botón"}

_TYPE2KIND = {
    pymupdf.PDF_WIDGET_TYPE_TEXT: TEXT,
    pymupdf.PDF_WIDGET_TYPE_CHECKBOX: CHECK,
    pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON: RADIO,
    pymupdf.PDF_WIDGET_TYPE_COMBOBOX: COMBO,
    pymupdf.PDF_WIDGET_TYPE_LISTBOX: LIST,
    pymupdf.PDF_WIDGET_TYPE_SIGNATURE: SIGNATURE,
    pymupdf.PDF_WIDGET_TYPE_BUTTON: BUTTON,
}
_KIND2TYPE = {v: k for k, v in _TYPE2KIND.items()}

DEFAULT_NAME = {TEXT: "Campo", CHECK: "Casilla", RADIO: "Grupo", COMBO: "Desplegable", LIST: "Lista",
                SIGNATURE: "Firma"}

# Tamaño por defecto (puntos) de un campo creado con un clic
DEFAULT_SIZE = {TEXT: (160, 18), CHECK: (12, 12), RADIO: (12, 12), COMBO: (140, 18),
                LIST: (140, 60), SIGNATURE: (200, 60), BUTTON: (80, 20)}


class FormError(Exception):
    """Operación de formulario no posible (mensaje para el usuario)."""


@dataclass
class Field:
    """Un widget de formulario tal como lo ve la interfaz."""
    page: int
    xref: int
    name: str
    kind: str
    rect: pymupdf.Rect                 # coordenadas visibles
    value: object = ""                 # str (texto, desplegable), bool (casilla/opción), list (lista múltiple)
    on_state: str | None = None        # nombre del estado «activado» (casillas y opciones)
    options: list = field(default_factory=list)   # opciones visibles (desplegable, lista)
    exports: list = field(default_factory=list)   # valores exportados de esas opciones
    label: str = ""                    # descripción (/TU), se muestra como ayuda
    readonly: bool = False
    required: bool = False
    multiline: bool = False
    password: bool = False
    comb: bool = False
    editable: bool = False             # desplegable en el que se puede escribir
    multiselect: bool = False
    max_len: int = 0
    fontsize: float = 0                # 0 = automático
    align: int = 0                     # 0 izq., 1 centro, 2 der.
    signed: bool = False               # firma ya realizada
    group_size: int = 1                # opciones del mismo grupo (botones de opción)

    @property
    def fillable(self) -> bool:
        return not self.readonly and self.kind in (TEXT, CHECK, RADIO, COMBO, LIST)

    @property
    def kind_name(self) -> str:
        return KIND_NAMES.get(self.kind, "Campo")

    @property
    def display_name(self) -> str:
        return self.label or self.name


# ====================================================================== lectura
def _vis(page: pymupdf.Page, r: pymupdf.Rect) -> pymupdf.Rect:
    return pymupdf.Rect(r * page.rotation_matrix).normalize() if page.rotation else pymupdf.Rect(r)


def _unrot(page: pymupdf.Page, r: pymupdf.Rect) -> pymupdf.Rect:
    return pymupdf.Rect(r * page.derotation_matrix).normalize() if page.rotation else pymupdf.Rect(r)


def _choices(w) -> tuple[list, list]:
    shown, exports = [], []
    for c in w.choice_values or []:
        if isinstance(c, (list, tuple)) and len(c) >= 2:
            exports.append(str(c[0]))
            shown.append(str(c[1]))
        else:
            exports.append(str(c))
            shown.append(str(c))
    return shown, exports


def _sig_signed(doc: pymupdf.Document, xref: int) -> bool:
    try:
        v = doc.xref_get_key(xref, "V")
        if v[0] == "null":
            par = doc.xref_get_key(xref, "Parent")
            if par[0] == "xref":
                v = doc.xref_get_key(int(par[1].split()[0]), "V")
        return v[0] not in ("null",)
    except Exception:
        return False


def _field_of(page: pymupdf.Page, w) -> Field:
    kind = _TYPE2KIND.get(w.field_type, BUTTON)
    fl = w.field_flags or 0
    f = Field(page=page.number, xref=w.xref, name=w.field_name or "", kind=kind,
              rect=_vis(page, w.rect), label=w.field_label or "",
              readonly=bool(fl & pymupdf.PDF_FIELD_IS_READ_ONLY),
              required=bool(fl & pymupdf.PDF_FIELD_IS_REQUIRED),
              fontsize=float(w.text_fontsize or 0))
    if kind == TEXT:
        f.value = "" if w.field_value in (None, False) else str(w.field_value)
        f.multiline = bool(fl & pymupdf.PDF_TX_FIELD_IS_MULTILINE)
        f.password = bool(fl & pymupdf.PDF_TX_FIELD_IS_PASSWORD)
        f.comb = bool(fl & pymupdf.PDF_TX_FIELD_IS_COMB)
        f.max_len = int(w.text_maxlen or 0)
        try:
            f.align = int(page.parent.xref_get_key(w.xref, "Q")[1]) if page.parent.xref_get_key(w.xref, "Q")[0] == "int" else 0
        except Exception:
            f.align = 0
    elif kind in (CHECK, RADIO):
        try:
            f.on_state = w.on_state()
        except Exception:
            f.on_state = "Yes"
        if f.on_state is True:
            f.on_state = "Yes"
        try:
            as_ = page.parent.xref_get_key(w.xref, "AS")
            cur = as_[1][1:] if as_[0] == "name" else None
        except Exception:
            cur = None
        if cur is None:
            cur = str(w.field_value) if w.field_value not in (None, False) else "Off"
        f.value = cur not in ("Off", "", "False") and (cur == f.on_state or kind == CHECK)
    elif kind in (COMBO, LIST):
        f.options, f.exports = _choices(w)
        v = w.field_value
        f.editable = bool(fl & pymupdf.PDF_CH_FIELD_IS_EDIT)
        f.multiselect = bool(fl & pymupdf.PDF_CH_FIELD_IS_MULTI_SELECT)
        if isinstance(v, (list, tuple)):
            f.value = [_shown(f, x) for x in v]
        else:
            f.value = _shown(f, "" if v in (None, False) else str(v))
    elif kind == SIGNATURE:
        f.signed = _sig_signed(page.parent, w.xref)
    return f


def _shown(f: Field, export: str) -> str:
    """Texto visible de una opción a partir de su valor exportado."""
    if export in f.exports:
        return f.options[f.exports.index(export)]
    return export


def page_fields(doc: pymupdf.Document, page_index: int) -> list[Field]:
    """Campos de una página en orden de lectura (de arriba abajo, de izquierda a derecha)."""
    page = doc[page_index]
    out = []
    try:
        for w in page.widgets():
            try:
                out.append(_field_of(page, w))
            except Exception:
                continue
    except Exception:
        return []
    # tamaño de los grupos de botones de opción
    groups = {}
    for f in out:
        if f.kind == RADIO:
            groups[f.name] = groups.get(f.name, 0) + 1
    for f in out:
        if f.kind == RADIO:
            f.group_size = groups[f.name]
    return sort_reading(out)


def sort_reading(fields: list[Field]) -> list[Field]:
    """Orden de lectura: por filas (con tolerancia) y, dentro de cada fila, de izquierda a derecha."""
    fs = sorted(fields, key=lambda f: (f.page, f.rect.y0, f.rect.x0))
    out, row, row_y, row_page = [], [], None, None
    for f in fs:
        tol = max(4.0, min(f.rect.height, 14) * 0.6)
        if row and (f.page != row_page or abs(f.rect.y0 - row_y) > tol):
            out.extend(sorted(row, key=lambda g: g.rect.x0))
            row = []
        if not row:
            row_y, row_page = f.rect.y0, f.page
        row.append(f)
    out.extend(sorted(row, key=lambda g: g.rect.x0))
    return out


def all_fields(doc: pymupdf.Document) -> list[Field]:
    out = []
    for i in range(doc.page_count):
        out.extend(page_fields(doc, i))
    return out


def count(doc: pymupdf.Document) -> int:
    n = 0
    for page in doc:
        try:
            n += sum(1 for _ in page.widgets())
        except Exception:
            pass
    return n


def form_kind(doc: pymupdf.Document) -> str:
    """'none' (sin formulario), 'acro' (normal), 'xfa_hybrid' (XFA con campos normales)
    o 'xfa_only' (XFA dinámico sin campos: solo lo rellena Adobe)."""
    try:
        has_xfa = doc.xref_get_key(doc.pdf_catalog(), "AcroForm/XFA")[0] != "null"
    except Exception:
        has_xfa = False
    n = count(doc)
    if has_xfa:
        return "xfa_hybrid" if n else "xfa_only"
    return "acro" if n else "none"


def strip_xfa(doc: pymupdf.Document) -> bool:
    """Quita la parte XFA de un formulario híbrido para que Acrobat muestre los valores
    rellenados aquí (si no, Acrobat seguiría enseñando los datos XFA antiguos)."""
    try:
        cat = doc.pdf_catalog()
        af = doc.xref_get_key(cat, "AcroForm")
        if af[0] == "xref":
            x = int(af[1].split()[0])
            if doc.xref_get_key(x, "XFA")[0] != "null":
                doc.xref_set_key(x, "XFA", "null")
                return True
        elif af[0] == "dict" and "/XFA" in af[1]:
            doc.xref_set_key(cat, "AcroForm/XFA", "null")
            return True
    except Exception:
        pass
    return False


def missing_required(doc: pymupdf.Document) -> list[Field]:
    """Campos obligatorios sin rellenar (un grupo de opciones cuenta una sola vez)."""
    out, seen_radio, seen = [], {}, set()
    fields = all_fields(doc)
    for f in fields:
        if not f.required or f.readonly:
            continue
        if f.kind != RADIO:
            if f.name in seen:          # el mismo dato repetido en varios sitios cuenta una vez
                continue
            seen.add(f.name)
        if f.kind == RADIO:
            seen_radio.setdefault(f.name, []).append(f)
            continue
        empty = (f.kind in (TEXT, COMBO) and not str(f.value).strip()) or \
                (f.kind == LIST and not f.value) or (f.kind == CHECK and not f.value) or \
                (f.kind == SIGNATURE and not f.signed)
        if empty:
            out.append(f)
    for name, group in seen_radio.items():
        if not any(g.value for g in group):
            out.append(group[0])
    return sort_reading(out)


# ====================================================================== rellenar
def _load(doc: pymupdf.Document, page_index: int, xref: int):
    page = doc[page_index]
    w = page.load_widget(xref)
    if w is None:
        raise FormError("No se encuentra el campo en la página.")
    return page, w


def _same_name_widgets(doc: pymupdf.Document, name: str, exclude_xref: int):
    for page in doc:
        for w in page.widgets() or []:
            if w.field_name == name and w.xref != exclude_xref:
                yield page, w


def set_value(doc: pymupdf.Document, page_index: int, xref: int, value) -> bool:
    """Pone el valor de un campo. Para casillas y opciones, value es bool
    (True = marcar este botón). Devuelve True si algo ha cambiado."""
    page, w = _load(doc, page_index, xref)
    f = _field_of(page, w)
    if f.readonly:
        raise FormError("Este campo es de solo lectura.")
    if f.kind == TEXT:
        value = "" if value is None else str(value)
        if f.max_len and len(value) > f.max_len:
            value = value[:f.max_len]
        if not f.multiline:
            value = value.replace("\r\n", " ").replace("\n", " ")
        if value == f.value:
            return False
        if value:
            w.field_value = value
            w.update()
            _sync_siblings(doc, f.name, xref, value, TEXT)
        else:
            _clear_text(doc, xref)
    elif f.kind == CHECK:
        value = bool(value)
        if value == f.value:
            return False
        w.field_value = f.on_state if value else "Off"
        w.update()
        _sync_siblings(doc, f.name, xref, value, CHECK)
    elif f.kind == RADIO:
        value = bool(value)
        if value == f.value:
            return False
        if value:
            w.field_value = f.on_state
            w.update()
            _radio_others_off(doc, f.name, xref, f.on_state)
        else:
            w.field_value = False          # PyMuPDF: «Off» (texto) lo activaría
            w.update()
    elif f.kind == COMBO:
        value = "" if value is None else str(value)
        if value == f.value:
            return False
        export = f.exports[f.options.index(value)] if value in f.options else value
        if export:
            w.field_value = export
            w.update()
            _sync_siblings(doc, f.name, xref, export, COMBO)
        else:
            _clear_text(doc, xref)
    elif f.kind == LIST:
        vals = value if isinstance(value, (list, tuple)) else ([value] if value else [])
        vals = [str(v) for v in vals]
        cur = f.value if isinstance(f.value, list) else ([f.value] if f.value else [])
        if vals == cur:
            return False
        exports = [f.exports[f.options.index(v)] if v in f.options else v for v in vals]
        if exports:
            w.field_value = exports if f.multiselect else exports[0]
            w.update()
        else:
            _clear_text(doc, xref)
        _list_appearance(doc, xref)
    else:
        return False
    strip_xfa(doc)
    return True


def _sync_siblings(doc, name, xref, value, kind):
    """Otros widgets con el mismo nombre (el mismo dato repetido en el documento)."""
    for page, w in list(_same_name_widgets(doc, name, xref)):
        try:
            if kind == CHECK:
                w.field_value = w.on_state() if value else "Off"
            else:
                w.field_value = value
            w.update()
        except Exception:
            continue


def _radio_others_off(doc, name, xref, on_state):
    for page, w in list(_same_name_widgets(doc, name, xref)):
        try:
            if _TYPE2KIND.get(w.field_type) != RADIO:
                continue
            # los botones con el mismo estado «activado» van juntos (opciones al unísono)
            other_on = w.on_state()
            w.field_value = other_on if other_on == on_state else False
            w.update()
        except Exception:
            continue


def _pdf_text(t: str) -> str:
    b = t.encode("cp1252", "replace")
    out = []
    for c in b:
        if c in (0x28, 0x29, 0x5C):
            out.append("\\" + chr(c))
        elif 32 <= c < 127:
            out.append(chr(c))
        else:
            out.append("\\%03o" % c)
    return "(" + "".join(out) + ")"


def _list_appearance(doc: pymupdf.Document, xref: int):
    """MuPDF deja en blanco el aspecto de los cuadros de lista: se dibujan aquí las
    opciones, con las elegidas resaltadas (como hace Acrobat)."""
    try:
        page = None
        for pg in doc:
            if _on_page(doc, pg, xref):
                page = pg
                break
        if page is None:
            return
        w = page.load_widget(xref)
        f = _field_of(page, w)
        t, v = doc.xref_get_key(xref, "AP/N")
        if t != "xref":
            return
        ap = int(v.split()[0])
        t, bb = doc.xref_get_key(ap, "BBox")
        x0, y0, x1, y1 = [float(n) for n in bb.strip("[]").split()]
        wdt, hgt = x1 - x0, y1 - y0
        fs = f.fontsize or 10
        lh = fs * 1.15
        sel = f.value if isinstance(f.value, list) else ([f.value] if f.value else [])
        ops = ["/Tx BMC", "q", f"1 1 {wdt - 2:g} {hgt - 2:g} re W n"]
        y = hgt - 1.5
        for o in f.options:
            if y - lh < -lh:
                break
            if o in sel:
                ops.append(f"0.6 0.75 0.95 rg 1 {y - lh:.2f} {wdt - 2:g} {lh:.2f} re f")
            ops.append(f"BT 0 g /Helv {fs:g} Tf 3 {y - lh + (lh - fs) / 2 + fs * 0.22:.2f} Td {_pdf_text(o)} Tj ET")
            y -= lh
        ops += ["Q", "EMC"]
        doc.update_stream(ap, "\n".join(ops).encode("latin-1"))
        t, fr = doc.xref_get_key(ap, "Resources/Font/Helv")
        if t == "null":
            fx = doc.get_new_xref()
            doc.update_object(fx, "<</Type/Font/Subtype/Type1/BaseFont/Helvetica/Encoding/WinAnsiEncoding>>")
            doc.xref_set_key(ap, "Resources", f"<</Font<</Helv {fx} 0 R>>>>")
    except Exception:
        pass


def reset(doc: pymupdf.Document) -> int:
    """Vacía el formulario. Devuelve los campos que tenían algo."""
    n = 0
    done = set()
    for page in doc:
        for w in list(page.widgets() or []):
            kind = _TYPE2KIND.get(w.field_type)
            if kind not in (TEXT, CHECK, RADIO, COMBO, LIST):
                continue
            if (w.field_flags or 0) & pymupdf.PDF_FIELD_IS_READ_ONLY:
                continue
            fx = _field_xref(doc, w.xref)
            had = w.field_value not in (None, "", "Off", False, [])
            try:
                if kind == CHECK:
                    w.field_value = "Off"
                    w.update()
                elif kind == RADIO:
                    w.field_value = False
                    w.update()
                    if fx != w.xref:
                        doc.xref_set_key(fx, "V", "/Off")
                elif fx not in done:
                    doc.xref_set_key(fx, "V", "()" if kind != LIST else "null")
                    _regen(doc, fx)
                    if kind == LIST:
                        for wx in _widget_xrefs(doc, fx):
                            _list_appearance(doc, wx)
            except Exception:
                continue
            done.add(fx)
            if had:
                n += 1
    if n:
        strip_xfa(doc)
    return n


def values(doc: pymupdf.Document) -> dict:
    """{nombre: valor} de todo el formulario (para exportar datos)."""
    out = {}
    for f in all_fields(doc):
        if f.kind == RADIO:
            if f.value:
                out[f.name] = f.on_state
            else:
                out.setdefault(f.name, "")
        elif f.kind == CHECK:
            out[f.name] = "Sí" if f.value else "No"
        elif f.kind == LIST:
            out[f.name] = "; ".join(f.value) if isinstance(f.value, list) else str(f.value or "")
        elif f.kind in (TEXT, COMBO):
            out.setdefault(f.name, str(f.value or ""))
        elif f.kind == SIGNATURE:
            out[f.name] = "Firmado" if f.signed else ""
    return out


# ====================================================================== aplanar
def flatten(doc: pymupdf.Document, keep_empty_signatures: bool = True) -> int:
    """Convierte los campos en contenido fijo de la página (ya no se pueden cambiar).
    Los campos de firma vacíos se conservan para poder firmar después.
    Las anotaciones (resaltados, notas…) no se tocan."""
    sigs = []
    n = count(doc)
    if not n:
        return 0
    if keep_empty_signatures:
        for page in doc:
            for w in page.widgets() or []:
                if w.field_type == pymupdf.PDF_WIDGET_TYPE_SIGNATURE and not _sig_signed(doc, w.xref):
                    sigs.append((page.number, pymupdf.Rect(w.rect), w.field_name, w.field_label or ""))
    doc.bake(annots=False, widgets=True)
    for pno, r, name, label in sigs:
        w = pymupdf.Widget()
        w.field_type = pymupdf.PDF_WIDGET_TYPE_SIGNATURE
        w.field_name = name
        w.field_label = label
        w.rect = r
        doc[pno].add_widget(w)
    strip_xfa(doc)
    return n - len(sigs)


# ====================================================================== crear y modificar
def _ascii(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def clean_name(label: str, fallback: str = "Campo") -> str:
    """Nombre de campo a partir de una etiqueta («Fecha de nacimiento:» → «Fecha de nacimiento»).
    Sin puntos (en PDF separan niveles) ni caracteres raros."""
    s = re.sub(r"[\s_.…·]+", " ", label or "").strip()
    s = re.sub(r"^[\d\W]+(?=\w)", "", s) if re.match(r"^\(?\d{1,2}[\).-]\s", s) else s
    s = s.strip(" :;,-–—*()[]¿?¡!\"'")
    s = re.sub(r"[^\w áéíóúüñÁÉÍÓÚÜÑçÇ/-]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > 40:
        s = s[:40].rsplit(" ", 1)[0] or s[:40]
    return s or fallback


def export_name(label: str, fallback: str) -> str:
    """Valor exportado de una opción (nombre PDF): solo letras y números ASCII."""
    s = re.sub(r"[^A-Za-z0-9_-]+", "", _ascii(clean_name(label, "")).replace(" ", "_"))
    return s[:30] or fallback


def existing_names(doc: pymupdf.Document) -> set:
    names = set()
    for page in doc:
        for w in page.widgets() or []:
            if w.field_name:
                names.add(w.field_name)
    return names


def unique_name(doc: pymupdf.Document, base: str, taken: set | None = None) -> str:
    taken = existing_names(doc) if taken is None else taken
    base = clean_name(base)
    if base not in taken:
        return base
    n = 2
    while f"{base} {n}" in taken:
        n += 1
    return f"{base} {n}"


def default_rect(kind: str, pt: pymupdf.Point, page_rect: pymupdf.Rect) -> pymupdf.Rect:
    """Rectángulo de tamaño estándar con la esquina superior izquierda en pt (dentro de la página)."""
    w, h = DEFAULT_SIZE.get(kind, (120, 18))
    r = pymupdf.Rect(pt.x, pt.y, pt.x + w, pt.y + h)
    if kind in (CHECK, RADIO):       # el clic marca el centro de la casilla
        r = pymupdf.Rect(pt.x - w / 2, pt.y - h / 2, pt.x + w / 2, pt.y + h / 2)
    return clamp(r, page_rect)


def clamp(r: pymupdf.Rect, page_rect: pymupdf.Rect) -> pymupdf.Rect:
    r = pymupdf.Rect(r)
    dx = max(0, page_rect.x0 - r.x0) - max(0, r.x1 - page_rect.x1)
    dy = max(0, page_rect.y0 - r.y0) - max(0, r.y1 - page_rect.y1)
    return r + (dx, dy, dx, dy)


def add_field(doc: pymupdf.Document, page_index: int, kind: str, rect: pymupdf.Rect, *,
              name: str | None = None, label: str = "", options: list | None = None,
              export: str | None = None, value=None, multiline: bool | None = None,
              required: bool = False, fontsize: float | None = None, editable: bool = False,
              border: bool = True, taken: set | None = None) -> int:
    """Crea un campo y devuelve el xref de su widget. rect en coordenadas visibles.
    Para botones de opción, name es el grupo (las opciones del mismo grupo se excluyen)
    y export el valor de esta opción."""
    page = doc[page_index]
    r = _unrot(page, rect)
    if r.width < 4 or r.height < 4:
        raise FormError("El campo es demasiado pequeño.")
    if kind not in _KIND2TYPE or kind == BUTTON:
        raise FormError("Tipo de campo no admitido.")
    if kind != RADIO or not name:
        name = unique_name(doc, name or label or DEFAULT_NAME.get(kind, "Campo"), taken)
    if taken is not None:
        taken.add(name)
    w = pymupdf.Widget()
    w.field_type = _KIND2TYPE[kind]
    w.field_name = name
    w.field_label = label or ""
    w.rect = r
    # Con borde fino si se dibuja en un sitio vacío; sin borde si va sobre una raya o
    # un recuadro del propio impreso (lo que hace la detección automática).
    w.border_width = 1 if border or kind in (CHECK, RADIO) else 0
    w.border_color = (0.55, 0.6, 0.7) if border or kind in (CHECK, RADIO) else None
    w.fill_color = None
    w.text_font = "Helv"
    if fontsize is None:          # tamaño cómodo según la altura (ni enorme ni diminuto)
        fontsize = max(6, min(11, round(r.height * 0.62))) if kind in (TEXT, COMBO) else 10
    w.text_fontsize = fontsize
    w.text_color = (0, 0, 0)
    flags = 0
    if required:
        flags |= pymupdf.PDF_FIELD_IS_REQUIRED
    if kind == TEXT:
        ml = multiline if multiline is not None else r.height > 34
        if ml:
            flags |= pymupdf.PDF_TX_FIELD_IS_MULTILINE
            w.text_fontsize = min(w.text_fontsize or 10, 10)
        w.field_value = "" if value is None else str(value)
    elif kind == CHECK:
        w.field_value = bool(value)
        w.text_font = "ZaDb"
        w.button_caption = None
    elif kind == RADIO:
        flags |= pymupdf.PDF_BTN_FIELD_IS_RADIO | pymupdf.PDF_BTN_FIELD_IS_NO_TOGGLE_TO_OFF
        w.text_font = "ZaDb"
        w.field_value = False
    elif kind in (COMBO, LIST):
        opts = [str(o) for o in (options or []) if str(o).strip()]
        w.choice_values = opts or [""]
        if kind == COMBO:
            flags |= pymupdf.PDF_CH_FIELD_IS_COMBO
            if editable:
                flags |= pymupdf.PDF_CH_FIELD_IS_EDIT
        w.field_value = str(value) if value else (opts[0] if kind == COMBO and opts and not editable else "")
        if kind == LIST and not value:
            w.field_value = ""
    elif kind == SIGNATURE:
        w.border_color = (0.35, 0.55, 0.45)
    w.field_flags = flags
    annot = page.add_widget(w)
    xref = annot.xref
    # MuPDF guarda /T y /TU en UTF-8 «crudo» (Acrobat mostraría «MatrÃ­cula» y pyHanko no
    # podría firmar): se escriben con la codificación de texto de PDF.
    fx = _field_xref(doc, xref)
    doc.xref_set_key(fx, "T", pymupdf.get_pdf_str(name))
    if label:
        doc.xref_set_key(fx, "TU", pymupdf.get_pdf_str(label))
    elif doc.xref_get_key(fx, "TU")[0] != "null":
        doc.xref_set_key(fx, "TU", "null")
    if kind == CHECK and value:
        set_value(doc, page_index, xref, True)
    if kind == RADIO:
        _fix_radio(doc, page_index, xref, export_name(export or "", "Opcion1"), bool(value))
    if kind == SIGNATURE:
        _blank_appearance(doc, xref)
    if kind == LIST:
        _list_appearance(doc, xref)
    return xref


def _blank_appearance(doc: pymupdf.Document, xref: int):
    """MuPDF dibuja en los campos de firma vacíos una etiqueta roja «SIGN» que saldría al
    imprimir. Se deja en blanco (o solo el borde): los lectores marcan el sitio a su manera."""
    t, v = doc.xref_get_key(xref, "AP/N")
    if t != "xref":
        return
    ap = int(v.split()[0])
    t, bb = doc.xref_get_key(ap, "BBox")
    try:
        x0, y0, x1, y1 = [float(n) for n in bb.strip("[]").split()]
    except Exception:
        doc.update_stream(ap, b"")
        return
    doc.update_stream(ap, f"q 0.55 0.65 0.6 RG 0.75 w {x0 + 0.5:g} {y0 + 0.5:g} {x1 - x0 - 1:g} {y1 - y0 - 1:g} re S Q".encode())


def _fix_radio(doc, page_index, xref, export, on):
    """PyMuPDF crea los botones de opción con los estados «True»/«False»: se cambia
    por el valor exportado de la opción y se coloca en su grupo."""
    page = doc[page_index]
    t, n = doc.xref_get_key(xref, "AP/N")
    if t == "dict":
        names = re.findall(r"/([^\s/<>\[\]()]+)\s+(\d+ 0 R)", n)
        off = [ref for nm, ref in names if nm == "Off"]
        onr = [ref for nm, ref in names if nm != "Off"]
        if onr:
            doc.xref_set_key(xref, "AP/N", f"<</{export} {onr[0]}" + (f"/Off {off[0]}" if off else "") + ">>")
    t, d = doc.xref_get_key(xref, "AP/D")
    if t == "dict":
        names = re.findall(r"/([^\s/<>\[\]()]+)\s+(\d+ 0 R)", d)
        off = [ref for nm, ref in names if nm == "Off"]
        onr = [ref for nm, ref in names if nm != "Off"]
        if onr:
            doc.xref_set_key(xref, "AP/D", f"<</{export} {onr[0]}" + (f"/Off {off[0]}" if off else "") + ">>")
    doc.xref_set_key(xref, "AS", "/Off")
    w = page.load_widget(xref)
    w.field_value = False
    w.update()
    if on:
        set_value(doc, page_index, xref, True)


def radio_groups(doc: pymupdf.Document) -> dict:
    """{grupo: [valores exportados]} de los botones de opción del documento."""
    out = {}
    for f in all_fields(doc):
        if f.kind == RADIO:
            out.setdefault(f.name, []).append(f.on_state)
    return out


def _field_xref(doc: pymupdf.Document, xref: int) -> int:
    """Objeto del campo (el que tiene /T): el propio widget o su /Parent.
    PyMuPDF no cambia las propiedades del campo cuando el widget tiene /Parent
    (así crea él todos los campos), así que se escriben aquí directamente."""
    x = xref
    for _ in range(8):
        if doc.xref_get_key(x, "T")[0] != "null":
            return x
        par = doc.xref_get_key(x, "Parent")
        if par[0] != "xref":
            break
        x = int(par[1].split()[0])
    return xref


def _widget_xrefs(doc: pymupdf.Document, fx: int) -> list[int]:
    kids = doc.xref_get_key(fx, "Kids")
    if kids[0] == "array":
        return [int(v) for v in re.findall(r"(\d+) 0 R", kids[1])]
    return [fx]


def _regen(doc: pymupdf.Document, fx: int):
    """Vuelve a generar el aspecto de todos los widgets del campo."""
    for wx in _widget_xrefs(doc, fx):
        for page in doc:
            w = page.load_widget(wx) if _on_page(doc, page, wx) else None
            if w is not None:
                try:
                    if w.field_type == pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON:
                        w.field_value = w.field_value if w.field_value not in ("Off", "", None) else False
                    w.update()
                except Exception:
                    pass
                break


def _on_page(doc, page, wx) -> bool:
    p = doc.xref_get_key(wx, "P")
    if p[0] == "xref":
        return int(p[1].split()[0]) == page.xref
    return wx in [a[0] for a in page.annot_xrefs()]


def _clear_text(doc: pymupdf.Document, xref: int):
    """PyMuPDF no deja vaciar un campo de texto (ignora el valor «»)."""
    fx = _field_xref(doc, xref)
    doc.xref_set_key(fx, "V", "()")
    _regen(doc, fx)


def update_field(doc: pymupdf.Document, page_index: int, xref: int, *, name: str | None = None,
                 label: str | None = None, required: bool | None = None,
                 readonly: bool | None = None, multiline: bool | None = None,
                 options: list | None = None, fontsize: float | None = None,
                 max_len: int | None = None, editable: bool | None = None,
                 export: str | None = None, align: int | None = None) -> None:
    """Cambia las propiedades de un campo."""
    page, w = _load(doc, page_index, xref)
    kind = _TYPE2KIND.get(w.field_type)
    fx = _field_xref(doc, xref)
    if name is not None:
        name = clean_name(name)
        if name != w.field_name:
            if name in existing_names(doc):
                raise FormError(f"Ya hay otro campo llamado «{name}».")
            doc.xref_set_key(fx, "T", pymupdf.get_pdf_str(name))
    if label is not None:
        doc.xref_set_key(fx, "TU", pymupdf.get_pdf_str(label))
    t, v = doc.xref_get_key(fx, "Ff")
    fl = int(v) if t == "int" else 0
    before = fl

    def setf(bit, on):
        nonlocal fl
        if on is None:
            return
        fl = (fl | bit) if on else (fl & ~bit)
    setf(pymupdf.PDF_FIELD_IS_REQUIRED, required)
    setf(pymupdf.PDF_FIELD_IS_READ_ONLY, readonly)
    if kind == TEXT:
        setf(pymupdf.PDF_TX_FIELD_IS_MULTILINE, multiline)
    if kind == COMBO:
        setf(pymupdf.PDF_CH_FIELD_IS_EDIT, editable)
    if fl != before:
        doc.xref_set_key(fx, "Ff", str(fl))
    if options is not None and kind in (COMBO, LIST):
        opts = [str(o) for o in options if str(o).strip()]
        doc.xref_set_key(fx, "Opt", "[" + " ".join(pymupdf.get_pdf_str(o) for o in opts) + "]")
        cur = w.field_value
        if cur not in opts and not (kind == COMBO and fl & pymupdf.PDF_CH_FIELD_IS_EDIT):
            first = opts[0] if (kind == COMBO and opts) else ""
            doc.xref_set_key(fx, "V", pymupdf.get_pdf_str(first))
    if fontsize is not None and kind in (TEXT, COMBO, LIST):
        for x in {fx, xref}:
            t, da = doc.xref_get_key(x, "DA")
            if t == "string":
                da2 = re.sub(r"(/[A-Za-z0-9_+-]+)\s+[\d.]+\s+Tf", lambda m: f"{m.group(1)} {float(fontsize):g} Tf", da)
                doc.xref_set_key(x, "DA", pymupdf.get_pdf_str(da2))
    if max_len is not None and kind == TEXT:
        doc.xref_set_key(fx, "MaxLen", str(int(max_len)) if max_len else "null")
    if align is not None and kind == TEXT:
        doc.xref_set_key(fx, "Q", str(int(align)))
        if fx != xref and doc.xref_get_key(xref, "Q")[0] != "null":
            doc.xref_set_key(xref, "Q", "null")
    _regen(doc, fx)
    if kind == LIST:
        for wx in _widget_xrefs(doc, fx):
            _list_appearance(doc, wx)
    if export and kind == RADIO:
        ex = export_name(export, "Opcion")
        w = page.load_widget(xref)
        cur = w.on_state()
        if ex != cur:
            was_on = _field_of(page, w).value
            _fix_radio(doc, page_index, xref, ex, was_on)


def move_field(doc: pymupdf.Document, page_index: int, xref: int, rect: pymupdf.Rect) -> None:
    page, w = _load(doc, page_index, xref)
    r = _unrot(page, clamp(rect, page.rect))
    if r.width < 4 or r.height < 4:
        raise FormError("El campo es demasiado pequeño.")
    w.rect = r
    w.update()


def delete_field(doc: pymupdf.Document, page_index: int, xref: int) -> None:
    page, w = _load(doc, page_index, xref)
    page.delete_widget(w)


def duplicate_field(doc: pymupdf.Document, page_index: int, xref: int, dx: float = 0, dy: float = 24) -> int:
    """Copia de un campo (con nombre nuevo) desplazada; devuelve su xref."""
    page, w = _load(doc, page_index, xref)
    f = _field_of(page, w)
    r = clamp(f.rect + (dx, dy, dx, dy), page.rect)
    if f.kind == RADIO:
        n = len([x for x in all_fields(doc) if x.kind == RADIO and x.name == f.name]) + 1
        return add_field(doc, page_index, RADIO, r, name=f.name, label=f.label,
                         export=export_name(f"Opcion{n}", f"Opcion{n}"))
    return add_field(doc, page_index, f.kind, r, name=f.name, label=f.label,
                     options=f.options, multiline=f.multiline, required=f.required,
                     fontsize=f.fontsize or None, editable=f.editable)


# ====================================================================== exportar datos
def _cell(v: str):
    """Números como números (12 / 12,5 / 1.234,56); el resto como texto."""
    t = (v or "").strip()
    if re.fullmatch(r"-?\d{1,15}", t) and not (len(t) > 1 and t.startswith("0")):
        return int(t)
    if re.fullmatch(r"-?\d{1,3}(\.\d{3})*,\d+|-?\d+,\d+", t):
        return float(t.replace(".", "").replace(",", "."))
    return v


def write_xlsx(path: str, rows: list) -> None:
    """rows: [(nombre del archivo, {campo: valor})] → una fila por formulario."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter
    cols = []
    for _, vals in rows:
        for k in vals:
            if k not in cols:
                cols.append(k)
    wb = Workbook()
    ws = wb.active
    ws.title = "Datos"
    ws.append(["Archivo"] + cols)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="2F5BD8")
    for name, vals in rows:
        ws.append([name] + [_cell(str(vals.get(k, ""))) for k in cols])
    for n, k in enumerate(["Archivo"] + cols, start=1):
        width = max([len(str(k))] + [len(str(vals.get(k, "")) if k != "Archivo" else name)
                                     for name, vals in rows]) + 2
        ws.column_dimensions[get_column_letter(n)].width = min(60, max(10, width))
    ws.freeze_panes = "B2"
    tmp = path + ".tmp"
    wb.save(tmp)
    import os
    os.replace(tmp, path)
