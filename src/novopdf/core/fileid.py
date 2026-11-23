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

"""¿Es el mismo archivo? Para no abrir dos veces el mismo PDF.

Un mismo archivo puede llegar con rutas distintas: mayúsculas/minúsculas, nombres cortos
(PROGRA~1), unidad de red (Z:\\...) o ruta UNC (\\\\servidor\\...), accesos directos o
enlaces. Se comparan la ruta real normalizada y, si el sistema lo da, el identificador del
archivo (volumen + índice del archivo). Además se guarda una huella del contenido para
detectar el mismo documento abierto desde otra copia (p. ej. un adjunto guardado dos veces).
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

MAX_HASH = 400 * 1024 * 1024        # no se calcula la huella de archivos mayores


def norm(path: str) -> str:
    try:
        p = os.path.realpath(path)
    except (OSError, ValueError):
        p = os.path.abspath(path)
    if p.startswith("\\\\?\\UNC\\"):
        p = "\\\\" + p[8:]
    elif p.startswith("\\\\?\\"):
        p = p[4:]
    return os.path.normcase(os.path.normpath(p))


def stat_id(path: str):
    try:
        st = os.stat(path)
    except OSError:
        return None
    if not st.st_ino:
        return None
    return (st.st_dev, st.st_ino)


def same_file(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    if norm(a) == norm(b):
        return True
    ia, ib = stat_id(a), stat_id(b)
    return ia is not None and ia == ib


@dataclass
class Fingerprint:
    size: int
    digest: str | None

    def matches(self, other: "Fingerprint | None") -> bool:
        return (other is not None and self.digest is not None and self.size == other.size
                and self.digest == other.digest)


def fingerprint(path: str | None) -> Fingerprint | None:
    """Tamaño y SHA-256 del archivo (None si no se puede leer)."""
    if not path:
        return None
    try:
        size = os.path.getsize(path)
        if size > MAX_HASH:
            return Fingerprint(size, None)
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return Fingerprint(size, h.hexdigest())
    except OSError:
        return None
