#!/bin/sh
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

# Compila el ayudante TWAIN (32 y 64 bits) y lo deja en src/novopdf/bin
set -e
cd "$(dirname "$0")"
i686-w64-mingw32-gcc   -O2 -s -mwindows -Wall -o novopdf_twain32.exe novopdf_twain.c -luser32 -lkernel32
x86_64-w64-mingw32-gcc -O2 -s -mwindows -Wall -o novopdf_twain64.exe novopdf_twain.c -luser32 -lkernel32
mkdir -p ../../src/novopdf/bin
cp novopdf_twain32.exe novopdf_twain64.exe ../../src/novopdf/bin/
# escáner de prueba para Wine (tests/ui_twain.py)
i686-w64-mingw32-gcc -shared -O2 -o test/NovoFake.ds test/fake_ds.c -Wl,--kill-at
