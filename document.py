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

"""Documento PDF en memoria con historial de deshacer.

Toda la aplicación trabaja sobre una copia del PDF cargada en memoria
(sin cifrado). La protección con contraseña se vuelve a aplicar al guardar.
"""
from __future__ import annotations

import io
import os
import tempfile
from dataclasses import dataclass, field

import pymupdf

MAX_UNDO = 25


class PasswordRequired(Exception):
    """El PDF necesita contraseña para abrirse."""


@dataclass
class Protection:
    """Configuración de contraseñas que se aplicará al guardar."""
    enabled: bool = False
    user_pw: str = ""          # contraseña para abrir
    owner_pw: str = ""         # contraseña de permisos (propietario)
    allow_print: bool = True
    allow_copy: bool = True
    allow_modify: bool = True
    allow_annotate: bool = True

    def permissions(self) -> int:
        p = pymupdf.PDF_PERM_ACCESSIBILITY | pymupdf.PDF_PERM_FORM
        if self.allow_print:
            p |= pymupdf.PDF_PERM_PRINT | pymupdf.PDF_PERM_PRINT_HQ
        if self.allow_copy:
            p |= pymupdf.PDF_PERM_COPY
        if self.allow_modify:
            p |= pymupdf.PDF_PERM_MODIFY | pymupdf.PDF_PERM_ASSEMBLE
        if self.allow_annotate:
            p |= pymupdf.PDF_PERM_ANNOTATE
        return p


@dataclass
class PdfDocument:
    doc: pymupdf.Document
    path: str | None = None
    protection: Protection = field(default_factory=Protection)
    modified: bool = False
    restricted: bool = False   # el autor limitó la edición (contraseña de propietario)
    source_bytes: bytes | None = None      # fichero original tal como se abrió
    fonts_added: bool = False               # se han incrustado fuentes al editar texto
    title: str | None = None                # nombre propuesto para un documento nuevo
    source_password: str | None = None
    print_allowed: bool = True              # el autor permite imprimir (o se conoce la contraseña de permisos)
    copy_allowed: bool = True               # el autor permite copiar el contenido (exportar a Word/Excel)
    form_allowed: bool = True               # el autor permite rellenar formularios (aunque limite la edición)
    _undo: list = field(default_factory=list)
    _redo: list = field(default_factory=list)

    # ------------------------------------------------------------------ apertura
    @classmethod
    def open(cls, path: str, password: str | None = None) -> "PdfDocument":
        with open(path, "rb") as fh:
            data = fh.read()
        return cls.from_bytes(data, path=path, password=password)

    @classmethod
    def from_bytes(cls, data: bytes, path: str | None = None,
                   password: str | None = None, filetype: str = "pdf") -> "PdfDocument":
        src = pymupdf.open(stream=data, filetype=filetype)
        prot = Protection()
        restricted = False
        print_allowed = True
        copy_allowed = True
        form_allowed = True
        if src.needs_pass:
            if not password:
                src.close()
                raise PasswordRequired()
            rc = src.authenticate(password)
            if not rc:
                src.close()
                raise PasswordRequired("wrong")
            # 2 = usuario, 4 = propietario, 6 = ambas iguales
            prot.enabled = True
            prot.user_pw = password
            if rc & 4:
                prot.owner_pw = password
            perms = src.permissions
            prot.allow_print = bool(perms & pymupdf.PDF_PERM_PRINT)
            prot.allow_copy = bool(perms & pymupdf.PDF_PERM_COPY)
            prot.allow_modify = bool(perms & pymupdf.PDF_PERM_MODIFY)
            prot.allow_annotate = bool(perms & pymupdf.PDF_PERM_ANNOTATE)
            restricted = not (rc & 4) and not prot.allow_modify
            print_allowed = bool(rc & 4) or prot.allow_print
            copy_allowed = bool(rc & 4) or prot.allow_copy
            form_allowed = bool(rc & 4) or bool(perms & (pymupdf.PDF_PERM_FORM | pymupdf.PDF_PERM_ANNOTATE))
        elif (src.metadata or {}).get("encryption"):
            # Solo tiene contraseña de propietario (restricciones del autor).
            perms = src.permissions
            restricted = not (perms & pymupdf.PDF_PERM_MODIFY)
            print_allowed = bool(perms & pymupdf.PDF_PERM_PRINT)
            copy_allowed = bool(perms & pymupdf.PDF_PERM_COPY)
            form_allowed = bool(perms & (pymupdf.PDF_PERM_FORM | pymupdf.PDF_PERM_ANNOTATE))
            if password and src.authenticate(password) & 4:
                restricted = False
                print_allowed = True
                copy_allowed = True
                form_allowed = True
        if src.is_pdf:
            plain = src.tobytes(encryption=pymupdf.PDF_ENCRYPT_NONE, garbage=1)
            src.close()
            doc = pymupdf.open(stream=plain, filetype="pdf")
        else:  # imágenes, etc. -> convertir a PDF
            pdfbytes = src.convert_to_pdf()
            src.close()
            doc = pymupdf.open(stream=pdfbytes, filetype="pdf")
            path = None
        return cls(doc=doc, path=path, protection=prot, restricted=restricted,
                   source_bytes=data if filetype == "pdf" else None, source_password=password,
                   print_allowed=print_allowed, copy_allowed=copy_allowed, form_allowed=form_allowed)

    @classmethod
    def new_blank(cls, pages: int = 1, width: float = 595, height: float = 842) -> "PdfDocument":
        doc = pymupdf.open()
        for _ in range(max(1, pages)):
            doc.new_page(width=width, height=height)
        d = cls(doc=doc)
        d.modified = True
        return d

    @classmethod
    def from_images(cls, paths: list[str]) -> "PdfDocument":
        doc = pymupdf.open()
        _append_images(doc, paths, len(doc))
        d = cls(doc=doc)
        d.modified = True
        return d

    @classmethod
    def merge(cls, items: list[tuple[str, str | None]]) -> "PdfDocument":
        """items: [(ruta, contraseña o None)]"""
        doc = pymupdf.open()
        for p, pw in items:
            if p.lower().endswith(".pdf"):
                src = pymupdf.open(p)
                if src.needs_pass and not src.authenticate(pw or ""):
                    raise PasswordRequired(os.path.basename(p))
                doc.insert_pdf(src)
                src.close()
            else:
                _append_images(doc, [p], len(doc))
        d = cls(doc=doc)
        d.modified = True
        return d

    # ------------------------------------------------------------------ info
    @property
    def page_count(self) -> int:
        return self.doc.page_count

    @property
    def name(self) -> str:
        if self.path:
            return os.path.basename(self.path)
        return self.title or "Documento nuevo.pdf"

    def has_signatures(self) -> bool:
        """True si el documento contiene firmas digitales realizadas."""
        try:
            for xref in range(1, self.doc.xref_length()):
                t = self.doc.xref_get_key(xref, "Type")
                if t[1] in ("/Sig", "/DocTimeStamp") and self.doc.xref_get_key(xref, "ByteRange")[0] != "null":
                    return True
        except Exception:
            pass
        return False

    def looks_scanned(self) -> bool:
        """True si las páginas tienen imágenes pero casi nada de texto."""
        n = min(self.page_count, 5)
        if n == 0:
            return False
        scanned = 0
        for i in range(n):
            page = self.doc[i]
            if len(page.get_text("text").strip()) < 20 and page.get_images():
                scanned += 1
        return scanned >= max(1, (n + 1) // 2)

    # ------------------------------------------------------------------ historial
    def checkpoint(self):
        """Guarda el estado actual antes de un cambio (para Deshacer)."""
        self._undo.append(self.doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_NONE))
        if len(self._undo) > MAX_UNDO:
            self._undo.pop(0)
        self._redo.clear()
        self._modified_before = self.modified
        self.modified = True

    def drop_checkpoint(self):
        """Descarta el último punto de Deshacer cuando al final no se ha cambiado nada."""
        if self._undo:
            self._undo.pop()
            self.modified = getattr(self, "_modified_before", self.modified)

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self.doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_NONE))
        self._replace(self._undo.pop())
        self.modified = True
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self.doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_NONE))
        self._replace(self._redo.pop())
        self.modified = True
        return True

    def replace_with_bytes(self, data: bytes, checkpoint: bool = True):
        if checkpoint:
            self.checkpoint()
        self._replace(data)

    def _replace(self, data: bytes):
        old = self.doc
        self.doc = pymupdf.open(stream=data, filetype="pdf")
        old.close()

    def _compact(self, **kw) -> bytes:
        """Bytes limpios (garbage=3) SIN tocar el documento abierto: MuPDF renumera los
        objetos del documento en memoria al limpiar, y la interfaz guarda números de objeto
        (campos de formulario, imágenes) que dejarían de valer."""
        raw = self.doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_NONE)
        tmp = pymupdf.open(stream=raw, filetype="pdf")
        try:
            return tmp.tobytes(garbage=3, encryption=pymupdf.PDF_ENCRYPT_NONE, **kw)
        finally:
            tmp.close()

    def plain_bytes(self) -> bytes:
        return self._compact(deflate=True)

    # ------------------------------------------------------------------ guardar
    def output_bytes(self) -> bytes:
        plain = self._compact(deflate=True, deflate_images=True, deflate_fonts=True)
        if self.fonts_added:
            # Las fuentes añadidas al editar se guardan solo con los caracteres usados
            try:
                tmp = pymupdf.open(stream=plain, filetype="pdf")
                tmp.subset_fonts(fallback=False)
                plain = tmp.tobytes(garbage=3, deflate=True, deflate_fonts=True,
                                    encryption=pymupdf.PDF_ENCRYPT_NONE)
                tmp.close()
            except Exception:
                pass
        p = self.protection
        if p.enabled and (p.user_pw or p.owner_pw):
            return encrypt_bytes(plain, p)
        return plain

    def bytes_for_signing(self) -> tuple[bytes, str | None]:
        """Bytes sobre los que firmar y contraseña para pyHanko.
        Si el documento ya estaba firmado y no se ha modificado, se firma el
        fichero original (firma incremental) para no invalidar las firmas previas."""
        p = self.protection
        pw = (p.owner_pw or p.user_pw) if p.enabled else None
        if not self.modified and self.source_bytes is not None and self.has_signatures():
            return self.source_bytes, self.source_password
        return self.output_bytes(), pw

    def save(self, path: str | None = None):
        path = path or self.path
        if not path:
            raise ValueError("Falta la ruta de destino")
        if not self.modified and self.source_bytes is not None:
            data = self.source_bytes          # sin cambios: copia exacta (conserva firmas)
        else:
            data = self.output_bytes()
        write_atomic(path, data)
        self.path = path
        self.modified = False
        self.source_bytes = data
        p = self.protection
        self.source_password = (p.owner_pw or p.user_pw) if p.enabled else None

    # ------------------------------------------------------------------ páginas
    def delete_pages(self, indices: list[int]):
        if len(indices) >= self.page_count:
            raise ValueError("No se pueden eliminar todas las páginas del documento.")
        self.checkpoint()
        self.doc.delete_pages(sorted(set(indices)))

    def extract_pages(self, indices: list[int], dest: str):
        out = pymupdf.open()
        for i in sorted(set(indices)):
            out.insert_pdf(self.doc, from_page=i, to_page=i)
        out.save(dest, garbage=3, deflate=True)
        out.close()

    def rotate_pages(self, indices: list[int], angle: int):
        self.checkpoint()
        for i in indices:
            page = self.doc[i]
            page.set_rotation((page.rotation + angle) % 360)

    def insert_blank(self, at: int, count: int = 1):
        self.checkpoint()
        ref = self.doc[min(max(at - 1, 0), self.page_count - 1)] if self.page_count else None
        w, h = (ref.rect.width, ref.rect.height) if ref else (595, 842)
        for k in range(count):
            self.doc.new_page(pno=at + k, width=w, height=h)

    def insert_file(self, at: int, path: str, password: str | None = None) -> int:
        """Inserta un PDF o imágenes en la posición indicada. Devuelve nº de páginas añadidas."""
        before = self.page_count
        if path.lower().endswith(".pdf"):
            src = pymupdf.open(path)
            if src.needs_pass and not src.authenticate(password or ""):
                src.close()
                raise PasswordRequired(os.path.basename(path))
            self.checkpoint()
            self.doc.insert_pdf(src, start_at=at)
            src.close()
        else:
            self.checkpoint()
            _append_images(self.doc, [path], at)
        return self.page_count - before

    def duplicate_pages(self, indices: list[int]):
        self.checkpoint()
        for offset, i in enumerate(sorted(indices)):
            src = i + offset
            # fullcopy_page(pno, to): «to» es la página delante de la que se inserta; -1 = al final
            to = src + 1 if src + 1 < self.doc.page_count else -1
            self.doc.fullcopy_page(src, to)

    def move_pages(self, indices: list[int], to: int):
        """Mueve las páginas seleccionadas para que queden antes de la posición `to`."""
        indices = sorted(set(indices))
        order = list(range(self.page_count))
        moving = [order[i] for i in indices]
        rest = [p for p in order if p not in moving]
        to_adj = to - sum(1 for i in indices if i < to)
        new_order = rest[:to_adj] + moving + rest[to_adj:]
        if new_order == order:
            return False
        self.checkpoint()
        self.doc.select(new_order)
        return True


def encrypt_bytes(plain: bytes, p: Protection) -> bytes:
    """Cifra con AES-256 (lo hace pyHanko para que el resultado admita después
    firmas incrementales)."""
    from pyhanko.pdf_utils.crypt.permissions import StandardPermissions as SP
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.pdf_utils.writer import copy_into_new_writer
    perms = SP.ALLOW_ASSISTIVE_TECHNOLOGY | SP.ALLOW_FORM_FILLING
    if p.allow_print:
        perms |= SP.ALLOW_PRINTING | SP.ALLOW_HIGH_QUALITY_PRINTING
    if p.allow_copy:
        perms |= SP.ALLOW_CONTENT_EXTRACTION
    if p.allow_modify:
        perms |= SP.ALLOW_MODIFICATION_GENERIC | SP.ALLOW_REASSEMBLY
    if p.allow_annotate:
        perms |= SP.ALLOW_ANNOTS_FORM_FILLING
    w = copy_into_new_writer(PdfFileReader(io.BytesIO(plain), strict=False))
    owner = (p.owner_pw or p.user_pw).encode("utf-8")
    user = p.user_pw.encode("utf-8") if p.user_pw else b""
    w.encrypt(owner, user, perms=perms)
    out = io.BytesIO()
    w.write(out)
    return out.getvalue()


def _append_images(doc: pymupdf.Document, paths: list[str], at: int):
    pos = at
    for p in paths:
        pix = pymupdf.Pixmap(p)
        w, h = pix.width, pix.height
        pix = None
        # Página A4 (vertical u horizontal según la imagen), con margen
        a4w, a4h = (842, 595) if w > h else (595, 842)
        page = doc.new_page(pno=pos, width=a4w, height=a4h)
        margin = 18
        target = pymupdf.Rect(margin, margin, a4w - margin, a4h - margin)
        page.insert_image(target, filename=p, keep_proportion=True)
        pos += 1


def write_atomic(path: str, data: bytes):
    folder = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(prefix=".novopdf_", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
