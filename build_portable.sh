#!/usr/bin/env bash
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

# Construye la carpeta portable de NovoPDF para Windows x64 (desde Linux).
#   - Python 3.12 autónomo (python-build-standalone) en runtime/
#   - Dependencias (wheels win_amd64) en runtime/Lib/site-packages
#   - Código de la aplicación en app/
#   - Datos del OCR en recursos/tessdata
#   - Lanzador NovoPDF.exe (C, compilado con mingw-w64)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/../src"
DL="${DL:-/home/claude/dist_build}"
OUT="${OUT:-$HERE/out/NovoPDF}"

rm -rf "$OUT"
mkdir -p "$OUT"

echo "== runtime de Python"
cp -r "$DL/dl/python" "$OUT/runtime"
R="$OUT/runtime"
find "$R" -name "*.pdb" -delete
rm -rf "$R/include" "$R/libs" "$R/Scripts" "$R/tcl" \
       "$R/Lib/test" "$R/Lib/idlelib" "$R/Lib/tkinter" "$R/Lib/turtledemo" "$R/Lib/ensurepip" \
       "$R/Lib/lib2to3" "$R/Lib/pydoc_data" "$R/DLLs/_tkinter.pyd" "$R/DLLs/tcl86t.dll" "$R/DLLs/tk86t.dll" \
       "$R/Lib/site-packages/pip" "$R/Lib/site-packages/pip-"* "$R/DLLs/_test"*.pyd "$R/DLLs/xxlimited"*.pyd
find "$R/Lib" -name "__pycache__" -type d -prune -exec rm -rf {} +

echo "== dependencias"
SP="$R/Lib/site-packages"
cp -r "$DL/sitepkgs/." "$SP/"
P="$SP/PySide6"
# Conservar solo lo que usa la aplicación (QtCore, QtGui, QtWidgets, QtSvg, QtPrintSupport)
keep_re='^(Qt6Core|Qt6Gui|Qt6Widgets|Qt6Svg|Qt6Network|Qt6PrintSupport)\.dll$|^Qt(Core|Gui|Widgets|Svg|PrintSupport)\.pyd$|^(__init__|_config|_git_pyside_version)\.py$|^(pyside6\.abi3|msvcp140.*|concrt140|vcruntime140.*|vccorlib140|vcomp140)\.dll$|^(plugins|support|translations)$|\.json$'
for f in "$P"/*; do
  b="$(basename "$f")"
  if ! [[ "$b" =~ $keep_re ]]; then rm -rf "$f"; fi
done
find "$P/plugins" -mindepth 1 -maxdepth 1 ! -name platforms ! -name imageformats ! -name iconengines ! -name styles -exec rm -rf {} +
find "$P/plugins/platforms" -type f ! -name qwindows.dll -delete
find "$P/plugins/imageformats" -type f ! -name qjpeg.dll ! -name qico.dll ! -name qsvg.dll ! -name qgif.dll ! -name qtiff.dll ! -name qwebp.dll -delete
find "$P/translations" -type f ! -name "qtbase_es.qm" ! -name "qt_es.qm" -delete
rm -rf "$SP/shiboken6/include" "$SP/shiboken6/lib" "$SP/PySide6/include"
# pywin32: solo lo necesario para COM (escáner WIA)
rm -rf "$SP/pythonwin" "$SP/adodbapi" "$SP/isapi" "$SP/PyWin32.chm" "$SP/win32/Demos" "$SP/win32/test" \
       "$SP/win32com/test" "$SP/win32com/demos" "$SP/win32comext/"*/test "$SP/win32comext/"*/demos
find "$SP" -name "*.pyi" -delete
find "$SP" -name "*.lib" -delete
find "$SP" -name "__pycache__" -type d -prune -exec rm -rf {} +

echo "== aplicación"
mkdir -p "$OUT/app"
cp -r "$SRC/novopdf" "$OUT/app/"
find "$OUT/app" -name "__pycache__" -type d -prune -exec rm -rf {} +
cp "$HERE/novopdf_inicio.pyw" "$OUT/app/"
mkdir -p "$OUT/recursos"
cp -r "$SRC/recursos/tessdata" "$OUT/recursos/"

echo "== lanzador"
x86_64-w64-mingw32-windres "$HERE/launcher/launcher.rc" -O coff -o "$HERE/launcher/launcher.res"
x86_64-w64-mingw32-gcc -O2 -s -municode -mwindows -o "$OUT/NovoPDF.exe" \
    "$HERE/launcher/launcher.c" "$HERE/launcher/launcher.res" -lwinspool -ladvapi32 -lshell32

echo "== documentación"
cp "$HERE/LEEME.txt" "$OUT/LEEME.txt"
cp "$HERE/../LICENSE" "$HERE/../AVISOS_TERCEROS.txt" "$OUT/"
cp -r "$HERE/../licencias" "$OUT/"
du -sh "$OUT"
