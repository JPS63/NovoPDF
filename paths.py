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

"""Rutas de la aplicación (modo portable: todo junto al ejecutable)."""
import os
import sys


def app_dir() -> str:
    """Carpeta raíz de la aplicación portable."""
    env = os.environ.get("NOVOPDF_HOME")
    if env:
        return env
    here = os.path.dirname(os.path.abspath(__file__))       # .../app/novopdf
    return os.path.dirname(os.path.dirname(here))            # raíz portable


def resource_dir() -> str:
    return os.path.join(app_dir(), "recursos")


IS_MAC = sys.platform == "darwin"


def data_dir() -> str:
    """Configuración del usuario. Windows: junto al programa si se puede escribir
    allí (uso portable en USB); si no, en %APPDATA%. macOS: ~/Library/Application Support."""
    if IS_MAC:
        d = os.path.join(os.path.expanduser("~/Library/Application Support"), "NovoPDF")
        os.makedirs(d, exist_ok=True)
        return d
    d = os.path.join(app_dir(), "datos")
    try:
        os.makedirs(d, exist_ok=True)
        test = os.path.join(d, ".w")
        with open(test, "w") as fh:
            fh.write("1")
        os.remove(test)
        return d
    except OSError:
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        d = os.path.join(base, "NovoPDF")
        os.makedirs(d, exist_ok=True)
        return d


IS_WINDOWS = sys.platform.startswith("win")
