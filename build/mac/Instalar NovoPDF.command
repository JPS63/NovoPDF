#!/bin/bash
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

# Instala NovoPDF en la carpeta Aplicaciones y quita la marca de «descargado de Internet».
DIR="$(cd "$(dirname "$0")" && pwd)"
if [ ! -d "$DIR/NovoPDF.app" ]; then
  echo "No se encuentra NovoPDF.app junto a este archivo. Descomprime primero el ZIP completo."
  read -n 1 -s -r -p "Pulsa una tecla para cerrar…"; exit 1
fi
if [ -w /Applications ]; then DEST="/Applications"; else DEST="$HOME/Applications"; mkdir -p "$DEST"; fi
echo "Instalando NovoPDF en $DEST …"
rm -rf "$DEST/NovoPDF.app"
ditto "$DIR/NovoPDF.app" "$DEST/NovoPDF.app" || { echo "No se pudo copiar."; exit 1; }
xattr -dr com.apple.quarantine "$DEST/NovoPDF.app" 2>/dev/null
echo "Listo. Abriendo NovoPDF…"
open "$DEST/NovoPDF.app"
