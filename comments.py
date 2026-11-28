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

"""Comentarios: notas, cuadros de texto, comentarios sobre texto marcado, respuestas
y estado («resuelto»).

Todo son anotaciones PDF estándar, como las que crea Adobe Acrobat, así que se ven en
cualquier lector (Acrobat/Reader, Edge, Chrome, Firefox, Vista Previa…):
  * nota adhesiva ........ /Text con /Popup, autor (/T), fechas (/CreationDate, /M);
  * cuadro de texto ...... /FreeText (el texto se ve directamente sobre la página);
  * comentario de marca .. /Contents de un resaltado, subrayado o tachado;
  * respuesta ............ /Text con /IRT (en respuesta a) y /RT /R;
  * estado ............... /Text con /IRT, /StateModel /Review y /State /Completed o /None.
Las respuestas y los estados no se dibujan en la página (aspecto vacío): los lectores los
muestran en el hilo del comentario, como Acrobat.

Los rectángulos y puntos que entran y salen de este módulo están en coordenadas
visibles (las del visor); PyMuPDF guarda las anotaciones sin girar.
"""
from __future__ import annotations

import datetime as dt
import getpass
import os
import re
import sys
from dataclasses import dataclass, field

import pymupdf

NOTE, FREETEXT, HIGHLIGHT, UNDERLINE, STRIKEOUT, SQUIGGLY, OTHER = (
    "note", "freetext", "highlight", "underline", "strikeout", "squiggly", "other")

KIND_NAMES = {NOTE: "Nota", FREETEXT: "Cuadro de texto", HIGHLIGHT: "Resaltado", UNDERLINE: "Subrayado",
              STRIKEOUT: "Tachado", SQUIGGLY: "Subrayado ondulado", OTHER: "Anotación"}

_T = pymupdf
_TYPE2KIND = {_T.PDF_ANNOT_TEXT: NOTE, _T.PDF_ANNOT_FREE_TEXT: FREETEXT, _T.PDF_ANNOT_HIGHLIGHT: HIGHLIGHT,
              _T.PDF_ANNOT_UNDERLINE: UNDERLINE, _T.PDF_ANNOT_STRIKE_OUT: STRIKEOUT,
              _T.PDF_ANNOT_SQUIGGLY: SQUIGGLY}
# Anotaciones que los lectores tratan como comentarios (las demás —enlaces, campos,
# ventanas emergentes, marcas de impresora…— no se listan)
_COMMENT_TYPES = set(_TYPE2KIND) | {_T.PDF_ANNOT_INK, _T.PDF_ANNOT_SQUARE, _T.PDF_ANNOT_CIRCLE,
                                    _T.PDF_ANNOT_LINE, _T.PDF_ANNOT_POLYGON, _T.PDF_ANNOT_POLY_LINE,
                                    _T.PDF_ANNOT_STAMP, _T.PDF_ANNOT_CARET, _T.PDF_ANNOT_FILE_ATTACHMENT}
MARKUPS = (HIGHLIGHT, UNDERLINE, STRIKEOUT, SQUIGGLY)

NOTE_COLORS = [("Amarillo", (1.0, 0.82, 0.16)), ("Azul", (0.36, 0.6, 1.0)), ("Verde", (0.35, 0.78, 0.42)),
               ("Rosa", (1.0, 0.5, 0.7)), ("Naranja", (1.0, 0.6, 0.2)), ("Morado", (0.66, 0.5, 0.95))]
FREETEXT_FILLS = [("Sin fondo", None), ("Amarillo claro", (1.0, 0.98, 0.78)), ("Blanco", (1.0, 1.0, 1.0)),
                  ("Azul claro", (0.88, 0.93, 1.0))]
NOTE_SIZE = 16.0                # lado (pt) del icono de la nota (MuPDF lo deja siempre en 16)
_FLAGS_NOTE = _T.PDF_ANNOT_IS_PRINT | _T.PDF_ANNOT_IS_NO_ZOOM | _T.PDF_ANNOT_IS_NO_ROTATE

RESOLVED = "Completed"           # estado de revisión que Acrobat muestra como «Completado»


class CommentError(Exception):
    """Operación no posible (mensaje para el usuario)."""


@dataclass
class Comment:
    page: int
    xref: int
    kind: str
    rect: pymupdf.Rect                     # coordenadas visibles
    author: str = ""
    text: str = ""
    created: dt.datetime | None = None
    modified: dt.datetime | None = None
    color: tuple | None = None
    subject: str = ""
    quoted: str = ""                       # texto marcado (resaltado, subrayado…)
    replies: list = field(default_factory=list)
    state: str = ""                        # "Completed" = resuelto
    state_author: str = ""
    parent: int = 0                        # xref del comentario al que responde (respuestas)

    @property
    def resolved(self) -> bool:
        return self.state in (RESOLVED, "Accepted")

    @property
    def kind_name(self) -> str:
        return KIND_NAMES.get(self.kind, self.subject or "Anotación")

    @property
    def when(self) -> dt.datetime | None:
        return self.modified or self.created


# ====================================================================== fechas y autor
def pdf_date(when: dt.datetime | None = None) -> str:
    """Fecha en formato PDF con la zona horaria local: D:20261128103000+01'00'."""
    when = (when or dt.datetime.now()).astimezone()
    off = when.utcoffset() or dt.timedelta(0)
    mins = int(off.total_seconds() // 60)
    sign = "+" if mins >= 0 else "-"
    mins = abs(mins)
    return when.strftime("D:%Y%m%d%H%M%S") + f"{sign}{mins // 60:02d}'{mins % 60:02d}'"


def parse_pdf_date(s: str | None) -> dt.datetime | None:
    if not s:
        return None
    m = re.match(r"(?:D:)?(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?([Zz+\-])?(\d{2})?'?(\d{2})?", s.strip())
    if not m:
        return None
    y, mo, d, h, mi, se = (int(m.group(i) or default) for i, default in
                           zip(range(1, 7), (0, 1, 1, 0, 0, 0)))
    tz = None
    if m.group(7) in ("Z", "z"):
        tz = dt.timezone.utc
    elif m.group(7) in ("+", "-"):
        off = dt.timedelta(hours=int(m.group(8) or 0), minutes=int(m.group(9) or 0))
        tz = dt.timezone(off if m.group(7) == "+" else -off)
    try:
        r = dt.datetime(y, mo, d, h, mi, se, tzinfo=tz)
        return r.astimezone() if tz else r
    except ValueError:
        return None


def format_date(when: dt.datetime | None) -> str:
    if when is None:
        return ""
    now = dt.datetime.now(when.tzinfo) if when.tzinfo else dt.datetime.now()
    if when.date() == now.date():
        return f"hoy {when:%H:%M}"
    if when.date() == (now - dt.timedelta(days=1)).date():
        return f"ayer {when:%H:%M}"
    return f"{when:%d/%m/%Y %H:%M}"


def default_author() -> str:
    """Nombre completo del usuario del sistema (o su nombre de inicio de sesión)."""
    try:
        if sys.platform.startswith("win"):
            import ctypes
            size = ctypes.c_ulong(0)
            fn = ctypes.windll.secur32.GetUserNameExW
            fn(3, None, ctypes.byref(size))                 # 3 = NameDisplay
            if size.value:
                buf = ctypes.create_unicode_buffer(size.value)
                if fn(3, buf, ctypes.byref(size)) and buf.value.strip():
                    return buf.value.strip()
        else:
            import pwd
            gecos = pwd.getpwuid(os.getuid()).pw_gecos.split(",")[0].strip()
            if gecos:
                return gecos
    except Exception:
        pass
    try:
        return getpass.getuser()
    except Exception:
        return "Usuario"


# ====================================================================== utilidades
def _vis(page, r) -> pymupdf.Rect:
    return pymupdf.Rect(r * page.rotation_matrix).normalize() if page.rotation else pymupdf.Rect(r)


def _unrot_rect(page, r) -> pymupdf.Rect:
    return pymupdf.Rect(r * page.derotation_matrix).normalize() if page.rotation else pymupdf.Rect(r)


def _unrot_pt(page, p) -> pymupdf.Point:
    return pymupdf.Point(p) * page.derotation_matrix if page.rotation else pymupdf.Point(p)


def _visible_rect(doc, page, a) -> pymupdf.Rect:
    """Rectángulo visible de una anotación. Se lee /Rect directamente: Annot.rect de
    PyMuPDF desplaza las notas /NoRotate en las páginas giradas."""
    if not page.rotation:
        return pymupdf.Rect(a.rect)
    t, v = _key(doc, a.xref, "Rect")
    try:
        nums = [float(n) for n in v.strip("[]").split()]
        ur = (pymupdf.Rect(nums) * page.transformation_matrix).normalize()     # sin girar
    except Exception:
        return _vis(page, a.rect)
    if (a.flags or 0) & pymupdf.PDF_ANNOT_IS_NO_ROTATE:
        tl = ur.tl * page.rotation_matrix          # la esquina queda fija y el icono se ve derecho
        return pymupdf.Rect(tl.x, tl.y, tl.x + ur.width, tl.y + ur.height)
    return _vis(page, ur)


def _annot(page, xref):
    try:
        return page.load_annot(xref)
    except Exception:
        return next((a for a in page.annots() if a.xref == xref), None)


def _key(doc, xref, key) -> tuple[str, str]:
    try:
        return doc.xref_get_key(xref, key)
    except Exception:
        return ("null", "null")


def _name(doc, xref, key) -> str:
    t, v = _key(doc, xref, key)
    return v[1:] if t == "name" else ""


def _text_or_name(doc, xref, key) -> str:
    """/State y /StateModel son textos según la norma (Acrobat), pero hay quien usa nombres."""
    t, v = _key(doc, xref, key)
    if t == "name":
        return v[1:]
    if t == "string":
        return v
    return ""


def _irt(doc, xref) -> int:
    t, v = _key(doc, xref, "IRT")
    return int(v.split()[0]) if t == "xref" else 0


def _set_text_key(doc, xref, key, value: str):
    doc.xref_set_key(xref, key, pymupdf.get_pdf_str(value) if value else "()")


def _stamp(doc, xref, author: str | None = None, created=False):
    now = pdf_date()
    doc.xref_set_key(xref, "M", pymupdf.get_pdf_str(now))
    if created or _key(doc, xref, "CreationDate")[0] == "null":
        doc.xref_set_key(xref, "CreationDate", pymupdf.get_pdf_str(now))
    if author is not None:
        _set_text_key(doc, xref, "T", author)


def _blank_ap(doc, xref, w=20.0, h=20.0):
    """Aspecto vacío (respuestas y estados: no se dibujan en la página)."""
    t, v = _key(doc, xref, "AP/N")
    if t == "xref":
        ap = int(v.split()[0])
        doc.update_stream(ap, b"")
        doc.xref_set_key(ap, "BBox", f"[0 0 {w:g} {h:g}]")


def _freetext_fill(doc, xref):
    """Color de fondo de un cuadro de texto (/C en las FreeText)."""
    t, v = _key(doc, xref, "C")
    if t == "array":
        nums = [float(n) for n in v.strip("[]").split()]
        if len(nums) == 3:
            return tuple(nums)
        if len(nums) == 1:
            return (nums[0],) * 3
    return None


def _popup_rect(page, r: pymupdf.Rect) -> pymupdf.Rect:
    """Sitio de la ventana emergente (para los lectores que la usan): a la derecha."""
    pr = page.mediabox
    w, h = 200, 110
    x0 = min(max(r.x1 + 6, pr.x0), pr.x1 - w)
    y0 = min(max(r.y0, pr.y0), pr.y1 - h)
    return pymupdf.Rect(x0, y0, x0 + w, y0 + h)


def _quoted(page, a) -> str:
    try:
        v = a.vertices or []
        parts = []
        for k in range(0, len(v) - 3, 4):
            r = pymupdf.Quad(v[k:k + 4]).rect
            t = page.get_textbox(r + (0, 1, 0, -1)).strip()
            if t:
                parts.append(t)
        s = " ".join(" ".join(parts).split())
        return s[:300]
    except Exception:
        return ""


# ====================================================================== leer
def _comment_of(page, a, doc) -> Comment:
    info = a.info or {}
    t = a.type[0]
    kind = _TYPE2KIND.get(t, OTHER)
    col = (a.colors or {}).get("stroke") or (a.colors or {}).get("fill")
    rect = _visible_rect(doc, page, a)
    c = Comment(page=page.number, xref=a.xref, kind=kind, rect=rect,
                author=info.get("title", "") or "", text=info.get("content", "") or "",
                created=parse_pdf_date(info.get("creationDate")), modified=parse_pdf_date(info.get("modDate")),
                color=tuple(col) if col else None, subject=info.get("subject", "") or "",
                parent=_irt(doc, a.xref))
    if c.created is None:
        c.created = parse_pdf_date(_key(doc, a.xref, "CreationDate")[1].strip("()"))
    if c.modified is None:
        c.modified = parse_pdf_date(_key(doc, a.xref, "M")[1].strip("()"))
    if kind in MARKUPS:
        c.quoted = _quoted(page, a)
    if kind == OTHER and not c.subject:
        c.subject = a.type[1]
    return c


def _ts(c: Comment) -> float:
    w = c.created or c.modified
    try:
        return w.timestamp() if w else 0.0
    except Exception:
        return 0.0


def page_comments(doc: pymupdf.Document, page_index: int) -> list[Comment]:
    """Hilos de comentarios de una página (comentario con sus respuestas y su estado)."""
    page = doc[page_index]
    tops, replies, states = [], [], []
    try:
        annots = list(page.annots())
    except Exception:
        return []
    for a in annots:
        if a.type[0] not in _COMMENT_TYPES:
            continue
        try:
            c = _comment_of(page, a, doc)
        except Exception:
            continue
        if c.parent:
            model = _text_or_name(doc, a.xref, "StateModel")
            if model or _text_or_name(doc, a.xref, "State"):
                c.state = _text_or_name(doc, a.xref, "State")
                c.subject = model
                states.append(c)
            elif _name(doc, a.xref, "RT") == "Group":
                continue                       # anotación agrupada: forma parte del padre
            else:
                replies.append(c)
        else:
            tops.append(c)
    by = {c.xref: c for c in tops}
    for r in replies:
        by.setdefault(r.xref, r)
    # una respuesta a una respuesta va al hilo del comentario original
    def root(x, seen=()):
        c = by.get(x)
        if c is None or not c.parent or x in seen:
            return x
        return root(c.parent, seen + (x,))
    for r in sorted(replies, key=_ts):
        top = by.get(root(r.parent))
        if top is not None and top is not r:
            top.replies.append(r)
        else:
            r.parent = 0
            tops.append(r)
    for s in sorted(states, key=_ts):
        top = by.get(root(s.parent))
        if top is not None and s.subject in ("Review", ""):
            top.state = s.state
            top.state_author = s.author
    tops.sort(key=lambda c: (round(c.rect.y0 / 4), c.rect.x0))
    return tops


def all_comments(doc: pymupdf.Document) -> list[Comment]:
    out = []
    for i in range(doc.page_count):
        out.extend(page_comments(doc, i))
    return out


def count(doc: pymupdf.Document) -> int:
    """Número de comentarios (hilos) del documento, sin cargar respuestas."""
    n = 0
    for page in doc:
        try:
            for a in page.annots():
                if a.type[0] in _COMMENT_TYPES and not _irt(doc, a.xref):
                    n += 1
        except Exception:
            pass
    return n


def comment_at(doc: pymupdf.Document, page_index: int, pt: pymupdf.Point, grow=2.0) -> Comment | None:
    """Nota o cuadro de texto bajo el punto visible (las marcas de texto se buscan aparte)."""
    for c in reversed(page_comments(doc, page_index)):
        if c.kind in (NOTE, FREETEXT, OTHER) and (c.rect + (-grow, -grow, grow, grow)).contains(pt):
            return c
    return None


def find(doc: pymupdf.Document, xref: int) -> Comment | None:
    """Hilo que contiene la anotación (comentario o respuesta)."""
    for c in all_comments(doc):
        if c.xref == xref or any(r.xref == xref for r in c.replies):
            return c
    return None


# ====================================================================== crear y cambiar
def add_note(doc: pymupdf.Document, page_index: int, pt: pymupdf.Point, text: str, author: str,
             color=None) -> int:
    """Nota adhesiva con la esquina superior izquierda del icono en pt (visible)."""
    page = doc[page_index]
    vr = page.rect
    x = min(max(pt.x, vr.x0), vr.x1 - NOTE_SIZE)
    y = min(max(pt.y, vr.y0), vr.y1 - NOTE_SIZE)
    # Las notas no giran con la página (/NoRotate): su esquina superior izquierda queda
    # fija y el icono se ve derecho; basta con llevar esa esquina a coordenadas sin girar.
    p = _unrot_pt(page, pymupdf.Point(x, y))
    color = tuple(color or NOTE_COLORS[0][1])
    a = page.add_text_annot(p, text or "", icon="Comment")
    a.set_rect(pymupdf.Rect(p.x, p.y, p.x + NOTE_SIZE, p.y + NOTE_SIZE))
    a.set_colors(stroke=color)
    a.set_info(title=author, subject="Nota", content=text or "")
    a.set_flags(_FLAGS_NOTE)
    a.update()
    try:
        a.set_popup(_popup_rect(page, a.rect))
        a.set_open(False)
    except Exception:
        pass
    x = a.xref
    _stamp(doc, x, author, created=True)
    return x


def add_freetext(doc: pymupdf.Document, page_index: int, rect: pymupdf.Rect, text: str, author: str,
                 fontsize: float = 11, color=(0.75, 0.05, 0.05), fill=None, border: bool = True) -> int:
    """Cuadro de texto sobre la página (se ve y se imprime en cualquier lector)."""
    page = doc[page_index]
    r = _unrot_rect(page, rect)
    if r.width < 10 or r.height < 8:
        raise CommentError("El cuadro de texto es demasiado pequeño.")
    color = tuple(color or (0, 0, 0))
    kw = dict(fontsize=fontsize, fontname="helv", text_color=color, fill_color=fill,
              rotate=page.rotation, align=pymupdf.TEXT_ALIGN_LEFT)
    kw["border_width"] = 0.8 if border else 0      # el borde toma el color del texto
    a = page.add_freetext_annot(r, text, **kw)
    a.set_info(title=author, subject="Cuadro de texto", content=text)
    a.update(fontsize=fontsize, text_color=color, fill_color=fill, rotate=page.rotation)
    x = a.xref
    if _key(doc, x, "CL")[0] != "null":     # línea de llamada que MuPDF añade por defecto
        doc.xref_set_key(x, "CL", "null")
    _stamp(doc, x, author, created=True)
    return x


def comment_markup(doc: pymupdf.Document, page_index: int, xref: int, text: str, author: str) -> None:
    """Pone o cambia el comentario de un resaltado, subrayado o tachado."""
    page = doc[page_index]
    a = _annot(page, xref)
    if a is None:
        raise CommentError("No se encuentra la marca.")
    info = a.info or {}
    a.set_info(content=text, title=info.get("title") or author)
    a.update()
    if not a.has_popup:
        try:
            a.set_popup(_popup_rect(page, a.rect))
            a.set_open(False)
        except Exception:
            pass
    _stamp(doc, xref)


def set_text(doc: pymupdf.Document, page_index: int, xref: int, text: str, *, fontsize=None,
             color=None, fill=..., border=None) -> None:
    """Cambia el texto de un comentario (nota, cuadro de texto, marca o respuesta)."""
    page = doc[page_index]
    a = _annot(page, xref)
    if a is None:
        raise CommentError("No se encuentra el comentario.")
    t = a.type[0]
    if t == pymupdf.PDF_ANNOT_FREE_TEXT:
        x0 = a.xref
        da = _key(doc, x0, "DA")[1]
        m = re.search(r"([\d.]+)\s+Tf", da)
        fs = fontsize or (float(m.group(1)) if m else 11)
        mc = re.search(r"([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+rg", da)
        col = tuple(color) if color else ((float(mc.group(1)), float(mc.group(2)), float(mc.group(3))) if mc else (0, 0, 0))
        fl = _freetext_fill(doc, x0) if fill is ... else fill
        bw0 = (a.border or {}).get("width", 0) or 0
        bw = bw0 if border is None else (0.8 if border else 0)
        rect = _vis(page, a.rect) + (bw0 / 2, bw0 / 2, -bw0 / 2, -bw0 / 2)   # sin el grosor del borde
        author = (a.info or {}).get("title") or ""
        created = _key(doc, x0, "CreationDate")
        replies = [r for r in page.annots() if _irt(doc, r.xref) == x0]
        if replies:
            # con respuestas no se puede volver a crear: se cambia el contenido y el aspecto
            a.set_info(content=text)
            a.update(fontsize=fs, text_color=col, fill_color=fl)
            _stamp(doc, x0)
            return
        page.delete_annot(a)
        nx = add_freetext(doc, page_index, rect, text, author, fs, col, fl, bw > 0)
        if created[0] != "null":
            doc.xref_set_key(nx, "CreationDate", created[1])
        return
    a.set_info(content=text)
    a.update()
    if _irt(doc, xref):
        _blank_ap(doc, xref)
    _stamp(doc, xref)


def set_color(doc: pymupdf.Document, page_index: int, xref: int, color) -> None:
    page = doc[page_index]
    a = _annot(page, xref)
    if a is None:
        raise CommentError("No se encuentra el comentario.")
    a.set_colors(stroke=tuple(color))
    a.update()
    _stamp(doc, xref)


def move(doc: pymupdf.Document, page_index: int, xref: int, rect: pymupdf.Rect) -> None:
    """Mueve una nota o un cuadro de texto (rect visible con el tamaño final)."""
    page = doc[page_index]
    a = _annot(page, xref)
    if a is None:
        raise CommentError("No se encuentra el comentario.")
    vr = page.rect
    r = pymupdf.Rect(rect)
    dx = max(0, vr.x0 - r.x0) - max(0, r.x1 - vr.x1)
    dy = max(0, vr.y0 - r.y0) - max(0, r.y1 - vr.y1)
    r += (dx, dy, dx, dy)
    ur = _unrot_rect(page, r)
    if a.type[0] == pymupdf.PDF_ANNOT_TEXT:
        p = _unrot_pt(page, r.tl)
        ur = pymupdf.Rect(p.x, p.y, p.x + NOTE_SIZE, p.y + NOTE_SIZE)
        a.set_rect(ur)
        a.update()
        if a.has_popup:
            try:
                a.set_popup(_popup_rect(page, ur))
            except Exception:
                pass
    else:
        a.set_rect(ur)
        a.update()
    # las respuestas y estados van con el comentario
    for r2 in page.annots():
        if _irt(doc, r2.xref) == xref and r2.type[0] == pymupdf.PDF_ANNOT_TEXT:
            r2.set_rect(pymupdf.Rect(ur.x0, ur.y0, ur.x0 + NOTE_SIZE, ur.y0 + NOTE_SIZE))
            r2.update()
            _blank_ap(doc, r2.xref)
    _stamp(doc, xref)


def add_reply(doc: pymupdf.Document, page_index: int, parent_xref: int, text: str, author: str) -> int:
    """Respuesta a un comentario (como las de Acrobat: /IRT y /RT /R)."""
    if not text.strip():
        raise CommentError("Escribe la respuesta.")
    page = doc[page_index]
    parent = _annot(page, parent_xref)
    if parent is None:
        raise CommentError("No se encuentra el comentario.")
    pr = parent.rect
    a = page.add_text_annot(pr.tl, text, icon="Comment")
    a.set_rect(pymupdf.Rect(pr.x0, pr.y0, pr.x0 + NOTE_SIZE, pr.y0 + NOTE_SIZE))
    a.set_info(title=author, subject="Respuesta", content=text)
    a.set_flags(_FLAGS_NOTE)
    a.update()
    a.set_irt_xref(parent_xref)
    x = a.xref
    doc.xref_set_key(x, "RT", "/R")
    _stamp(doc, x, author, created=True)
    _blank_ap(doc, x)
    return x


def set_resolved(doc: pymupdf.Document, page_index: int, parent_xref: int, resolved: bool, author: str) -> int:
    """Marca el comentario como resuelto («Completado» en Acrobat) o lo vuelve a abrir."""
    page = doc[page_index]
    parent = _annot(page, parent_xref)
    if parent is None:
        raise CommentError("No se encuentra el comentario.")
    pr = parent.rect
    state = RESOLVED if resolved else "None"
    text = f"{'Completado' if resolved else 'Ninguno'} establecido por {author}"
    a = page.add_text_annot(pr.tl, text, icon="Comment")
    a.set_rect(pymupdf.Rect(pr.x0, pr.y0, pr.x0 + NOTE_SIZE, pr.y0 + NOTE_SIZE))
    a.set_info(title=author, content=text)
    a.set_flags(_FLAGS_NOTE | pymupdf.PDF_ANNOT_IS_HIDDEN)
    a.update()
    x = a.xref
    try:
        p = a.popup_xref
        if p:
            doc.xref_set_key(x, "Popup", "null")
    except Exception:
        pass
    doc.xref_set_key(x, "IRT", f"{parent_xref} 0 R")
    doc.xref_set_key(x, "StateModel", pymupdf.get_pdf_str("Review"))
    doc.xref_set_key(x, "State", pymupdf.get_pdf_str(state))
    _stamp(doc, x, author, created=True)
    _blank_ap(doc, x)
    return x


def delete(doc: pymupdf.Document, page_index: int, xref: int) -> None:
    """Elimina un comentario con sus respuestas y estados, o una sola respuesta."""
    page = doc[page_index]
    a = _annot(page, xref)
    if a is None:
        raise CommentError("No se encuentra el comentario.")
    kids = [r.xref for r in page.annots() if _irt(doc, r.xref) == xref]
    for k in kids:
        delete(doc, page_index, k)
    a = _annot(page, xref)
    if a is not None:
        page.delete_annot(a)


# ====================================================================== exportar
def write_xlsx(path: str, doc_name: str, comments: list[Comment]) -> None:
    """Lista de comentarios en Excel (página, tipo, autor, fecha, texto, respuestas, estado)."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    wb = Workbook()
    ws = wb.active
    ws.title = "Comentarios"
    head = ["Página", "Tipo", "Autor", "Fecha", "Texto marcado", "Comentario", "Respuestas", "Estado"]
    ws.append(head)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="2F5BD8")
    for c in comments:
        reps = "\n".join(f"{r.author} ({format_date(r.when)}): {r.text}" for r in c.replies)
        when = c.when.replace(tzinfo=None) if c.when else None
        ws.append([c.page + 1, c.kind_name, c.author, when, c.quoted, c.text, reps,
                   "Resuelto" if c.resolved else ""])
    widths = [8, 16, 22, 17, 40, 60, 60, 10]
    for n, wdt in enumerate(widths):
        ws.column_dimensions[chr(65 + n)].width = wdt
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
        row[3].number_format = "dd/mm/yyyy hh:mm"
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    ws.sheet_properties.tabColor = "2F5BD8"
    wb.properties.title = f"Comentarios de {doc_name}"
    tmp = path + ".tmp"
    wb.save(tmp)
    os.replace(tmp, path)
