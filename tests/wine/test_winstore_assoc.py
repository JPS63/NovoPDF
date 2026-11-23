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

import sys, os, ctypes, hashlib
from ctypes import wintypes as wt
sys.path.insert(0, r"Z:\root\win\NovoPDF\app")
ok = lambda c, m: print(("OK  " if c else "FAIL"), m, flush=True)
from novopdf.core import fileassoc as fa, winstore, certstore, signing
print("exe:", fa.exe_path())
ok(fa.supported(), "supported")
import winreg
try: winreg.DeleteKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.pdf\UserChoice")
except OSError: pass
ok(fa.is_default() is False, "no predeterminado al principio")
fa.register()
cmd = fa._read(winreg.HKEY_CURRENT_USER, r"Software\Classes\NovoPDF.Document\shell\open\command")
ok(cmd == '"%s" "%%1"' % fa.exe_path(), "registro real: " + str(cmd))
k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\.pdf\OpenWithProgids")
ok(winreg.QueryValueEx(k, "NovoPDF.Document")[1] == winreg.REG_NONE, "OpenWithProgids REG_NONE")
with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.pdf\UserChoice") as uc:
    winreg.SetValueEx(uc, "ProgId", 0, winreg.REG_SZ, "NovoPDF.Document")
ok(fa.is_default() is True, "detecta predeterminado")
winreg.SetValueEx(winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\NovoPDF.Document\shell\open\command"), "", 0, winreg.REG_SZ, '"C:\\NoExiste\\NovoPDF.exe" "%1"')
ok(fa.refresh_if_moved() and fa._read(winreg.HKEY_CURRENT_USER, r"Software\Classes\NovoPDF.Document\shell\open\command") == cmd, "carpeta movida -> ruta corregida")
ok(hasattr(ctypes.windll.shell32, "SHOpenWithDialog"), "SHOpenWithDialog disponible")
ok(os.path.isfile(fa._sample_pdf()), "PDF de muestra")
# ventanas de PIN
ok(winstore.bring_prompt_to_front() is False, "sin petición de PIN abierta")
ok(certstore.bring_prompt_to_front(force=True) is False, "certstore.bring_prompt_to_front")
# Importar clave + certificado al almacén MY de Wine con el proveedor RSA y AES
import struct
from cryptography.hazmat.primitives.serialization import pkcs12, Encoding
key, cert, _ = pkcs12.load_key_and_certificates(open("prueba.pfx", "rb").read(), b"1234")
pn = key.private_numbers(); pub = pn.public_numbers; bits = key.key_size
le = lambda n, size: n.to_bytes(size, "little")
blob = (struct.pack("<BBHI", 7, 2, 0, 0xA400) + b"RSA2" + struct.pack("<II", bits, pub.e) +
        le(pub.n, bits // 8) + le(pn.p, bits // 16) + le(pn.q, bits // 16) + le(pn.dmp1, bits // 16) +
        le(pn.dmq1, bits // 16) + le(pn.iqmp, bits // 16) + le(pn.d, bits // 8))
adv = ctypes.WinDLL("advapi32", use_last_error=True)
adv.CryptAcquireContextW.argtypes = [ctypes.POINTER(ctypes.c_size_t), wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, wt.DWORD]
adv.CryptImportKey.argtypes = [ctypes.c_size_t, ctypes.c_char_p, wt.DWORD, ctypes.c_size_t, wt.DWORD, ctypes.POINTER(ctypes.c_size_t)]
PROV = "Microsoft Enhanced RSA and AES Cryptographic Provider"
hp = ctypes.c_size_t(0)
if not adv.CryptAcquireContextW(ctypes.byref(hp), "novopdf_prueba", PROV, 24, 0):
    ok(adv.CryptAcquireContextW(ctypes.byref(hp), "novopdf_prueba", PROV, 24, 8), "contenedor creado")  # CRYPT_NEWKEYSET
hk = ctypes.c_size_t(0)
ok(adv.CryptImportKey(hp.value, blob, len(blob), 0, 0, ctypes.byref(hk)), f"clave importada {ctypes.get_last_error():x}")
c32 = ctypes.WinDLL("crypt32", use_last_error=True)
c32.CertOpenSystemStoreW.restype = ctypes.c_void_p; c32.CertOpenSystemStoreW.argtypes = [ctypes.c_void_p, wt.LPCWSTR]
c32.CertAddEncodedCertificateToStore.argtypes = [ctypes.c_void_p, wt.DWORD, ctypes.c_char_p, wt.DWORD, wt.DWORD, ctypes.POINTER(winstore.PCCERT_CONTEXT)]
c32.CertSetCertificateContextProperty.argtypes = [winstore.PCCERT_CONTEXT, wt.DWORD, wt.DWORD, ctypes.c_void_p]
c32.CertCloseStore.argtypes = [ctypes.c_void_p, wt.DWORD]
class KPI(ctypes.Structure):
    _fields_ = [("pwszContainerName", wt.LPWSTR), ("pwszProvName", wt.LPWSTR), ("dwProvType", wt.DWORD),
                ("dwFlags", wt.DWORD), ("cProvParam", wt.DWORD), ("rgProvParam", ctypes.c_void_p), ("dwKeySpec", wt.DWORD)]
my = c32.CertOpenSystemStoreW(None, "MY")
der = cert.public_bytes(Encoding.DER)
c32.CertCreateCertificateContext.restype = winstore.PCCERT_CONTEXT
c32.CertCreateCertificateContext.argtypes = [wt.DWORD, ctypes.c_char_p, wt.DWORD]
pc = c32.CertCreateCertificateContext(1, der, len(der))
kpi = KPI("novopdf_prueba", PROV, 24, 0, 0, None, 1)
ok(c32.CertSetCertificateContextProperty(pc, 2, 0, ctypes.byref(kpi)), "propiedad de clave")
c32.CertAddCertificateContextToStore.argtypes = [ctypes.c_void_p, winstore.PCCERT_CONTEXT, wt.DWORD, ctypes.c_void_p]
ok(c32.CertAddCertificateContextToStore(my, pc, 3, None), "certificado en MY")
c32.CertCloseStore(my, 0)
certs = signing.windows_certificates()
ok(len(certs) >= 1, f"certificados con clave en MY: {[c.holder for c in certs]}")
ch = [c for c in certs if "PRUEBA" in c.holder.upper() or "JES" in c.holder.upper()][0]
u32 = ctypes.WinDLL("user32"); u32.GetDesktopWindow.restype = ctypes.c_void_p
import pymupdf
for hw, name in ((None, "sin ventana"), (u32.GetDesktopWindow(), "con ventana padre")):
    signer = signing.signer_for(ch, hwnd=hw)
    out = f"firmado_{'h' if hw else 'n'}.pdf"
    signing.sign_pdf(open("texto.pdf", "rb").read(), out, signer, page_index=0, rect=pymupdf.Rect(330, 700, 540, 770))
    r = signing.verify_pdf(open(out, "rb").read())
    ok(r and r[0].intact, f"firma con almacén de Windows ({name}): {r[0].summary if r else r}")
# hilo aparte como en la interfaz
import threading
res = {}
def work():
    try:
        prep = signing.prepare_signature(open("texto.pdf", "rb").read(), signing.signer_for(ch, hwnd=u32.GetDesktopWindow()))
        res["b"] = signing.perform_signature(prep, signing.signer_for(ch, hwnd=u32.GetDesktopWindow())); prep.cleanup()
    except Exception as e: res["e"] = repr(e)
t = threading.Thread(target=work); t.start(); t.join(120)
ok("b" in res and signing.verify_pdf(res["b"])[0].intact, f"firma desde hilo aparte {res.get('e','')}")
