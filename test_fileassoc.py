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

"""Asociación de PDF (Windows) con un winreg simulado."""
import os, sys, types, tempfile
sys.path.insert(0, "/home/claude/novopdf/src")
root = tempfile.mkdtemp(); os.environ["NOVOPDF_HOME"] = root
open(os.path.join(root, "NovoPDF.exe"), "wb").close()
REG = {}
w = types.ModuleType("winreg")
w.HKEY_CURRENT_USER = "HKCU"; w.KEY_WRITE = 1; w.REG_SZ = 1; w.REG_NONE = 0
class K:
    def __init__(s, p): s.p = p.lower()
    def __enter__(s): return s
    def __exit__(s, *a): pass
def OpenKey(r, p):
    if p.lower() not in REG: raise OSError(p)
    return K(p)
def CreateKeyEx(r, p, *a): REG.setdefault(p.lower(), {}); return K(p)
def QueryValueEx(k, n):
    if n not in REG[k.p]: raise OSError(n)
    return (REG[k.p][n], 1)
def SetValueEx(k, n, _, t, v): REG[k.p][n] = v
w.OpenKey, w.CreateKeyEx, w.QueryValueEx, w.SetValueEx = OpenKey, CreateKeyEx, QueryValueEx, SetValueEx
sys.modules["winreg"] = w
from novopdf.core import fileassoc as fa
fa.IS_WINDOWS = True; fa.IS_MAC = False; fa._notify = lambda: None
ok = lambda c, m: print(("OK  " if c else "FAIL"), m)
exe = os.path.join(root, "NovoPDF.exe")
ok(fa.supported() and fa.exe_path() == exe, "ejecutable portable detectado")
ok(fa.is_default() is False, "sin elección: no es predeterminado")
fa.register()
cmd = REG[r"software\classes\novopdf.document\shell\open\command"][""]
ok(cmd == f'"{exe}" "%1"', f"comando: {cmd}")
ok("NovoPDF.Document" in REG[r"software\classes\.pdf\openwithprogids"], "en «Abrir con» de .pdf")
ok(REG[r"software\registeredapplications"]["NovoPDF"] == r"Software\NovoPDF\Capabilities", "en Aplicaciones predeterminadas")
ok(REG[r"software\classes\applications\novopdf.exe\supportedtypes"].get(".pdf") == "", "SupportedTypes .pdf")
uc = r"software\microsoft\windows\currentversion\explorer\fileexts\.pdf\userchoice"
REG[uc] = {"ProgId": "MSEdgePDF"}; ok(fa.is_default() is False, "Edge predeterminado -> False")
REG[uc] = {"ProgId": "NovoPDF.Document"}; ok(fa.is_default() is True, "ProgId propio -> True")
REG[uc] = {"ProgId": "Applications\\NovoPDF.exe"}; ok(fa.is_default() is True, "Applications\\NovoPDF.exe -> True")
# carpeta movida: la ruta registrada ya no existe
REG[r"software\classes\novopdf.document\shell\open\command"][""] = '"C:\\Antes\\NovoPDF\\NovoPDF.exe" "%1"'
ok(fa.refresh_if_moved() is True and REG[r"software\classes\novopdf.document\shell\open\command"][""] == f'"{exe}" "%1"', "ruta actualizada al mover la carpeta")
# otra copia existente: no se toca
other = os.path.join(tempfile.mkdtemp(), "NovoPDF.exe"); open(other, "wb").close()
REG[r"software\classes\novopdf.document\shell\open\command"][""] = f'"{other}" "%1"'
ok(fa.refresh_if_moved() is False, "no pisa otra copia instalada que sí existe")
p = fa._sample_pdf(); import pymupdf; ok(pymupdf.open(p).page_count == 1, "PDF de muestra válido")
