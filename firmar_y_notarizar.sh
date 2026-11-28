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

# Firma NovoPDF.app con un certificado «Developer ID Application» y lo notariza en Apple,
# para que se abra sin avisos en cualquier Mac. Ejecutar en un Mac con Xcode Command Line Tools.
#
# Uso: ./firmar_y_notarizar.sh NovoPDF.app "Developer ID Application: Organización (TEAMID)" perfil-notarytool
#   (perfil creado antes con: xcrun notarytool store-credentials perfil-notarytool --apple-id ... --team-id ...)
set -euo pipefail
APP="$1"; ID="$2"; PROFILE="$3"
ENT="$(mktemp)"
cat > "$ENT" <<'PL'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>com.apple.security.cs.allow-unsigned-executable-memory</key><true/>
  <key>com.apple.security.cs.disable-library-validation</key><true/>
</dict></plist>
PL
xattr -cr "$APP"
# 1) Bibliotecas y binarios internos (de dentro hacia fuera)
find "$APP/Contents" -type f \( -name "*.so" -o -name "*.dylib" \) -print0 |
  xargs -0 -n1 codesign --force --timestamp --options runtime --entitlements "$ENT" --sign "$ID"
find "$APP/Contents" -path "*.framework/*" -type f -perm +111 ! -name "*.*" -print0 |
  xargs -0 -n1 codesign --force --timestamp --options runtime --entitlements "$ENT" --sign "$ID"
codesign --force --timestamp --options runtime --entitlements "$ENT" --sign "$ID" "$APP/Contents/MacOS/python3"
# 2) El paquete completo
codesign --force --timestamp --options runtime --entitlements "$ENT" --sign "$ID" "$APP"
codesign --verify --deep --strict --verbose=2 "$APP"
# 3) Notarización
ditto -c -k --keepParent "$APP" /tmp/NovoPDF_notarizar.zip
xcrun notarytool submit /tmp/NovoPDF_notarizar.zip --keychain-profile "$PROFILE" --wait
xcrun stapler staple "$APP"
echo "NovoPDF firmado y notarizado."
