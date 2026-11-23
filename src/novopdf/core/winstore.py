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

"""Acceso al almacén de certificados de Windows («Personal») mediante CryptoAPI/CNG.

Permite firmar con certificados instalados en el equipo (FNMT, certificados
de empleado público, DNIe o tarjetas cuyo driver los registre en Windows)
sin exportar la clave privada. Si la clave está protegida, Windows mostrará
su propio cuadro de diálogo para pedir el PIN o la contraseña.
"""
from __future__ import annotations

import ctypes
import hashlib
import logging
import os
import sys
from ctypes import wintypes as wt

AVAILABLE = sys.platform.startswith("win")
ACCEPTS_HWND = True
log = logging.getLogger("novopdf.firma")

CERT_KEY_PROV_INFO_PROP_ID = 2
CERT_NCRYPT_KEY_SPEC = 0xFFFFFFFF
CRYPT_ACQUIRE_COMPARE_KEY_FLAG = 0x4
CRYPT_ACQUIRE_PREFER_NCRYPT_KEY_FLAG = 0x20000
CRYPT_ACQUIRE_WINDOW_HANDLE_FLAG = 0x80
PP_CLIENT_HWND = 1
ASFW_ANY = 0xFFFFFFFF
BCRYPT_PAD_PKCS1 = 0x2
HP_HASHVAL = 0x2
_CALG = {"sha1": 0x8004, "sha256": 0x800C, "sha384": 0x800D, "sha512": 0x800E}
_BCRYPT_ALG = {"sha1": "SHA1", "sha256": "SHA256", "sha384": "SHA384", "sha512": "SHA512"}

_ERRORS = {
    0x8010006E: "Operación cancelada por el usuario.",
    0x80090036: "Operación cancelada por el usuario.",
    0x800704C7: "Operación cancelada por el usuario.",
    0x80090016: "No se encuentra la clave privada del certificado.",
    0x80090010: "Acceso denegado a la clave privada.",
    0x8009000F: "La clave privada no está disponible.",
    0x80090027: "Parámetro incorrecto al acceder a la clave.",
    0x8010000C: "No se encuentra la tarjeta inteligente. Inserte la tarjeta e inténtelo de nuevo.",
    0x80100069: "Se ha retirado la tarjeta inteligente.",
    0x8010006B: "PIN incorrecto.",
    0x8010006C: "La tarjeta está bloqueada (demasiados intentos de PIN).",
}


class WinStoreError(Exception):
    pass


def _err(code: int, what: str) -> WinStoreError:
    code &= 0xFFFFFFFF
    msg = _ERRORS.get(code)
    if msg:
        return WinStoreError(msg)
    return WinStoreError(f"{what} (código 0x{code:08X})")


if AVAILABLE:
    class CERT_CONTEXT(ctypes.Structure):
        _fields_ = [("dwCertEncodingType", wt.DWORD),
                    ("pbCertEncoded", ctypes.POINTER(ctypes.c_ubyte)),
                    ("cbCertEncoded", wt.DWORD),
                    ("pCertInfo", ctypes.c_void_p),
                    ("hCertStore", ctypes.c_void_p)]

    PCCERT_CONTEXT = ctypes.POINTER(CERT_CONTEXT)

    class BCRYPT_PKCS1_PADDING_INFO(ctypes.Structure):
        _fields_ = [("pszAlgId", wt.LPCWSTR)]

    _crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    _ncrypt = ctypes.WinDLL("ncrypt", use_last_error=True)
    _advapi = ctypes.WinDLL("advapi32", use_last_error=True)

    _crypt32.CertOpenSystemStoreW.argtypes = [ctypes.c_void_p, wt.LPCWSTR]
    _crypt32.CertOpenSystemStoreW.restype = ctypes.c_void_p
    _crypt32.CertCloseStore.argtypes = [ctypes.c_void_p, wt.DWORD]
    _crypt32.CertCloseStore.restype = wt.BOOL
    _crypt32.CertEnumCertificatesInStore.argtypes = [ctypes.c_void_p, PCCERT_CONTEXT]
    _crypt32.CertEnumCertificatesInStore.restype = PCCERT_CONTEXT
    _crypt32.CertDuplicateCertificateContext.argtypes = [PCCERT_CONTEXT]
    _crypt32.CertDuplicateCertificateContext.restype = PCCERT_CONTEXT
    _crypt32.CertFreeCertificateContext.argtypes = [PCCERT_CONTEXT]
    _crypt32.CertFreeCertificateContext.restype = wt.BOOL
    _crypt32.CertGetCertificateContextProperty.argtypes = [
        PCCERT_CONTEXT, wt.DWORD, ctypes.c_void_p, ctypes.POINTER(wt.DWORD)]
    _crypt32.CertGetCertificateContextProperty.restype = wt.BOOL
    _crypt32.CryptAcquireCertificatePrivateKey.argtypes = [
        PCCERT_CONTEXT, wt.DWORD, ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t),
        ctypes.POINTER(wt.DWORD), ctypes.POINTER(wt.BOOL)]
    _crypt32.CryptAcquireCertificatePrivateKey.restype = wt.BOOL

    _ncrypt.NCryptSignHash.argtypes = [
        ctypes.c_size_t, ctypes.c_void_p, ctypes.c_char_p, wt.DWORD,
        ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD), wt.DWORD]
    _ncrypt.NCryptSignHash.restype = ctypes.c_long
    _ncrypt.NCryptSetProperty.argtypes = [ctypes.c_size_t, wt.LPCWSTR, ctypes.c_void_p, wt.DWORD, wt.DWORD]
    _ncrypt.NCryptSetProperty.restype = ctypes.c_long
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _user32.GetForegroundWindow.restype = ctypes.c_void_p
    _user32.AllowSetForegroundWindow.argtypes = [wt.DWORD]
    _user32.AllowSetForegroundWindow.restype = wt.BOOL
    WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    _user32.EnumWindows.argtypes = [WNDENUMPROC, wt.LPARAM]
    _user32.EnumWindows.restype = wt.BOOL
    _user32.IsWindowVisible.argtypes = [wt.HWND]
    _user32.IsWindowVisible.restype = wt.BOOL
    _user32.IsIconic.argtypes = [wt.HWND]
    _user32.IsIconic.restype = wt.BOOL
    _user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    _user32.GetClassNameW.restype = ctypes.c_int
    _user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    _user32.GetWindowTextW.restype = ctypes.c_int
    _user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
    _user32.GetWindowThreadProcessId.restype = wt.DWORD
    _user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
    _user32.GetWindowRect.restype = wt.BOOL
    _user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
    _user32.SetForegroundWindow.argtypes = [wt.HWND]
    _user32.SetForegroundWindow.restype = wt.BOOL
    _user32.BringWindowToTop.argtypes = [wt.HWND]
    _user32.BringWindowToTop.restype = wt.BOOL
    _advapi.CryptGetProvParam.argtypes = [ctypes.c_size_t, wt.DWORD, ctypes.c_void_p,
                                          ctypes.POINTER(wt.DWORD), wt.DWORD]
    _advapi.CryptGetProvParam.restype = wt.BOOL
    _advapi.CryptAcquireContextW.argtypes = [ctypes.POINTER(ctypes.c_size_t), wt.LPCWSTR, wt.LPCWSTR,
                                             wt.DWORD, wt.DWORD]
    _advapi.CryptAcquireContextW.restype = wt.BOOL
    _advapi.CryptSetProvParam.argtypes = [ctypes.c_size_t, wt.DWORD, ctypes.c_void_p, wt.DWORD]
    _advapi.CryptSetProvParam.restype = wt.BOOL
    _ncrypt.NCryptFreeObject.argtypes = [ctypes.c_size_t]
    _ncrypt.NCryptFreeObject.restype = ctypes.c_long

    _advapi.CryptCreateHash.argtypes = [ctypes.c_size_t, wt.DWORD, ctypes.c_size_t, wt.DWORD,
                                        ctypes.POINTER(ctypes.c_size_t)]
    _advapi.CryptCreateHash.restype = wt.BOOL
    _advapi.CryptSetHashParam.argtypes = [ctypes.c_size_t, wt.DWORD, ctypes.c_char_p, wt.DWORD]
    _advapi.CryptSetHashParam.restype = wt.BOOL
    _advapi.CryptSignHashW.argtypes = [ctypes.c_size_t, wt.DWORD, wt.LPCWSTR, wt.DWORD,
                                       ctypes.c_void_p, ctypes.POINTER(wt.DWORD)]
    _advapi.CryptSignHashW.restype = wt.BOOL
    _advapi.CryptDestroyHash.argtypes = [ctypes.c_size_t]
    _advapi.CryptReleaseContext.argtypes = [ctypes.c_size_t, wt.DWORD]


def _iter_store(name: str):
    """Genera (der, tiene_clave_privada) para cada certificado del almacén."""
    if not AVAILABLE:
        return
    store = _crypt32.CertOpenSystemStoreW(None, name)
    if not store:
        return
    try:
        ctx = _crypt32.CertEnumCertificatesInStore(store, None)
        while ctx:
            c = ctx.contents
            der = ctypes.string_at(c.pbCertEncoded, c.cbCertEncoded)
            size = wt.DWORD(0)
            has_key = bool(_crypt32.CertGetCertificateContextProperty(
                ctx, CERT_KEY_PROV_INFO_PROP_ID, None, ctypes.byref(size)))
            yield der, has_key
            ctx = _crypt32.CertEnumCertificatesInStore(store, ctx)  # libera el anterior
    finally:
        _crypt32.CertCloseStore(store, 0)


def personal_certificates() -> list[bytes]:
    """Certificados del almacén «Personal» del usuario que tienen clave privada."""
    return [der for der, has_key in _iter_store("MY") if has_key]


def authority_certificates() -> tuple[list[bytes], list[bytes]]:
    """(raíces de confianza, intermedias) instaladas en Windows."""
    roots = [der for der, _ in _iter_store("ROOT")]
    cas = [der for der, _ in _iter_store("CA")]
    return roots, cas


def sign_digest(cert_der: bytes, digest: bytes, hash_alg: str, key_algo: str,
                hwnd: int | None = None) -> bytes:
    """Firma un resumen (hash) con la clave privada asociada al certificado.
    key_algo: 'rsa' o 'ec'. hwnd: ventana de NovoPDF, para que la petición de PIN
    aparezca encima de ella. Devuelve la firma en el formato que espera CMS."""
    if not AVAILABLE:
        raise WinStoreError("El almacén de certificados solo está disponible en Windows.")
    # Permitir que la ventana del PIN (a veces de otro proceso) pase al primer plano
    try:
        _user32.AllowSetForegroundWindow(ASFW_ANY)
    except Exception:
        pass
    hwnd_v = ctypes.c_void_p(hwnd or _user32.GetForegroundWindow() or None)
    if hwnd_v.value:
        try:   # proveedores CryptoAPI antiguos (CSP): ventana padre de sus diálogos
            _advapi.CryptSetProvParam(0, PP_CLIENT_HWND, ctypes.addressof(hwnd_v), 0)
        except Exception:
            pass
    thumb = hashlib.sha1(cert_der).digest()
    store = _crypt32.CertOpenSystemStoreW(None, "MY")
    if not store:
        raise WinStoreError("No se pudo abrir el almacén de certificados de Windows.")
    found = None
    try:
        ctx = _crypt32.CertEnumCertificatesInStore(store, None)
        while ctx:
            c = ctx.contents
            if hashlib.sha1(ctypes.string_at(c.pbCertEncoded, c.cbCertEncoded)).digest() == thumb:
                found = _crypt32.CertDuplicateCertificateContext(ctx)
                _crypt32.CertFreeCertificateContext(ctx)
                break
            ctx = _crypt32.CertEnumCertificatesInStore(store, ctx)
        if not found:
            raise WinStoreError("El certificado ya no está instalado en este equipo.")

        hkey = ctypes.c_size_t(0)
        keyspec = wt.DWORD(0)
        must_free = wt.BOOL(False)
        flags = CRYPT_ACQUIRE_PREFER_NCRYPT_KEY_FLAG | CRYPT_ACQUIRE_COMPARE_KEY_FLAG
        param = None
        if hwnd_v.value:
            flags |= CRYPT_ACQUIRE_WINDOW_HANDLE_FLAG
            param = ctypes.addressof(hwnd_v)
        log.info("Accediendo a la clave privada del certificado")
        ok = _crypt32.CryptAcquireCertificatePrivateKey(
            found, flags, param, ctypes.byref(hkey), ctypes.byref(keyspec), ctypes.byref(must_free))
        if not ok:
            raise _err(ctypes.get_last_error(), "No se pudo acceder a la clave privada")
        log.info("Clave obtenida (%s); firmando",
                 "CNG" if keyspec.value == CERT_NCRYPT_KEY_SPEC else "CryptoAPI")
        try:
            if keyspec.value == CERT_NCRYPT_KEY_SPEC:
                sig = _sign_ncrypt(hkey.value, digest, hash_alg, key_algo, hwnd_v)
            else:
                sig = _sign_capi(hkey.value, keyspec.value, digest, hash_alg)
        finally:
            if must_free.value:
                if keyspec.value == CERT_NCRYPT_KEY_SPEC:
                    _ncrypt.NCryptFreeObject(hkey.value)
                else:
                    _advapi.CryptReleaseContext(hkey.value, 0)
    finally:
        if found:
            _crypt32.CertFreeCertificateContext(found)
        _crypt32.CertCloseStore(store, 0)
    if key_algo == "ec" and keyspec.value == CERT_NCRYPT_KEY_SPEC:
        # CNG devuelve r||s; CMS necesita DER (SEQUENCE {r, s})
        from asn1crypto.algos import DSASignature
        sig = DSASignature.from_p1363(sig).dump()
    return sig


def _sign_ncrypt(hkey: int, digest: bytes, hash_alg: str, key_algo: str, hwnd=None) -> bytes:
    # Que el cuadro de PIN de Windows aparezca delante de NovoPDF
    try:
        if hwnd is None or not hwnd.value:
            hwnd = ctypes.c_void_p(_user32.GetForegroundWindow())
        if hwnd.value:
            _ncrypt.NCryptSetProperty(hkey, "HWND Handle", ctypes.byref(hwnd), ctypes.sizeof(hwnd), 0)
    except Exception:
        pass
    if key_algo == "rsa":
        pad = BCRYPT_PKCS1_PADDING_INFO(_BCRYPT_ALG[hash_alg])
        ppad = ctypes.cast(ctypes.pointer(pad), ctypes.c_void_p)
        flags = BCRYPT_PAD_PKCS1
    else:
        pad = None
        ppad = None
        flags = 0
    size = wt.DWORD(0)
    st = _ncrypt.NCryptSignHash(hkey, ppad, digest, len(digest), None, 0, ctypes.byref(size), flags)
    if st != 0:
        raise _err(st, "No se pudo firmar con el certificado")
    buf = (ctypes.c_ubyte * size.value)()
    st = _ncrypt.NCryptSignHash(hkey, ppad, digest, len(digest), ctypes.cast(buf, ctypes.c_void_p),
                                size, ctypes.byref(size), flags)
    if st != 0:
        raise _err(st, "No se pudo firmar con el certificado")
    del pad
    return bytes(buf[: size.value])


NTE_BAD_ALGID = 0x80090008
PP_NAME, PP_CONTAINER, PP_KEYSET_TYPE = 4, 6, 27
PROV_RSA_AES = 24
MS_ENH_RSA_AES_PROV = "Microsoft Enhanced RSA and AES Cryptographic Provider"


def _prov_str(hprov: int, param: int) -> str:
    size = wt.DWORD(0)
    if not _advapi.CryptGetProvParam(hprov, param, None, ctypes.byref(size), 0) or not size.value:
        return ""
    buf = ctypes.create_string_buffer(size.value)
    if not _advapi.CryptGetProvParam(hprov, param, buf, ctypes.byref(size), 0):
        return ""
    return buf.value.decode("mbcs" if sys.platform.startswith("win") else "latin-1", "replace")


def _sign_capi(hprov: int, keyspec: int, digest: bytes, hash_alg: str) -> bytes:
    try:
        return _sign_capi_with(hprov, keyspec, digest, hash_alg)
    except _NoSha2:
        pass
    # Claves de los proveedores software antiguos de Microsoft (Base/Strong/Enhanced):
    # el mismo contenedor se abre con el proveedor «RSA and AES», que sí admite SHA-256.
    name, container = _prov_str(hprov, PP_NAME), _prov_str(hprov, PP_CONTAINER)
    log.info("El proveedor «%s» no admite %s; se reintenta con %s", name, hash_alg, MS_ENH_RSA_AES_PROV)
    if not container or not name.startswith("Microsoft") or "Smart Card" in name:
        raise WinStoreError(f"El proveedor del certificado ({name or 'desconocido'}) no admite SHA-256.")
    flags = 0
    kst = wt.DWORD(0)
    size = wt.DWORD(4)
    if _advapi.CryptGetProvParam(hprov, PP_KEYSET_TYPE, ctypes.byref(kst), ctypes.byref(size), 0):
        flags |= kst.value & 0x20          # CRYPT_MACHINE_KEYSET
    h2 = ctypes.c_size_t(0)
    if not _advapi.CryptAcquireContextW(ctypes.byref(h2), container, MS_ENH_RSA_AES_PROV, PROV_RSA_AES, flags):
        raise _err(ctypes.get_last_error(), "El proveedor del certificado no admite SHA-256")
    try:
        try:
            return _sign_capi_with(h2.value, keyspec, digest, hash_alg)
        except _NoSha2:
            raise WinStoreError("El proveedor del certificado no admite SHA-256.") from None
    finally:
        _advapi.CryptReleaseContext(h2.value, 0)


class _NoSha2(Exception):
    pass


def _sign_capi_with(hprov: int, keyspec: int, digest: bytes, hash_alg: str) -> bytes:
    hhash = ctypes.c_size_t(0)
    if not _advapi.CryptCreateHash(hprov, _CALG[hash_alg], 0, 0, ctypes.byref(hhash)):
        code = ctypes.get_last_error() & 0xFFFFFFFF
        if code == NTE_BAD_ALGID:
            raise _NoSha2()
        raise _err(code, "El proveedor del certificado no admite SHA-256")
    try:
        if not _advapi.CryptSetHashParam(hhash.value, HP_HASHVAL, digest, 0):
            raise _err(ctypes.get_last_error(), "Error al preparar la firma")
        size = wt.DWORD(0)
        if not _advapi.CryptSignHashW(hhash.value, keyspec, None, 0, None, ctypes.byref(size)):
            raise _err(ctypes.get_last_error(), "No se pudo firmar con el certificado")
        buf = (ctypes.c_ubyte * size.value)()
        if not _advapi.CryptSignHashW(hhash.value, keyspec, None, 0,
                                      ctypes.cast(buf, ctypes.c_void_p), ctypes.byref(size)):
            raise _err(ctypes.get_last_error(), "No se pudo firmar con el certificado")
        return bytes(buf[: size.value])[::-1]   # CryptoAPI devuelve little-endian
    finally:
        _advapi.CryptDestroyHash(hhash.value)


# ------------------------------------------------------------------ ventana del PIN
_PROMPT_CLASSES = ("Credential Dialog Xaml Host",)
_IGNORED_CLASSES = ("IME", "MSCTFIME UI", "tooltips_class32", "SysShadow", "ForegroundStaging",
                    "CicMarshalWndClass", "OleMainThreadWndClass", "WorkerW")
_raised: set[int] = set()


def _prompt_windows() -> list[int]:
    """Ventanas visibles que parecen una petición de PIN/contraseña: la de Seguridad de
    Windows (CredUI) o cualquier diálogo no-Qt de este proceso (CSP del certificado)."""
    found = []
    pid = os.getpid()

    def cb(h, _):
        try:
            if not _user32.IsWindowVisible(h):
                return True
            buf = ctypes.create_unicode_buffer(256)
            _user32.GetClassNameW(h, buf, 256)
            cls = buf.value
            if cls in _PROMPT_CLASSES:
                found.append(h)
                return True
            owner = wt.DWORD(0)
            _user32.GetWindowThreadProcessId(h, ctypes.byref(owner))
            if owner.value != pid or cls.startswith("Qt") or cls in _IGNORED_CLASSES:
                return True
            r = wt.RECT()
            _user32.GetWindowRect(h, ctypes.byref(r))
            if r.right - r.left < 120 or r.bottom - r.top < 60:
                return True
            found.append(h)
        except Exception:
            pass
        return True

    _user32.EnumWindows(WNDENUMPROC(cb), 0)
    return found


def bring_prompt_to_front(force: bool = False) -> bool:
    """Trae al frente la petición de PIN si existe. Sin force, cada ventana solo se
    adelanta una vez (para no quitar el foco si el usuario cambia de ventana)."""
    if not AVAILABLE:
        return False
    try:
        wins = _prompt_windows()
    except Exception:
        return False
    fg = _user32.GetForegroundWindow()
    for h in wins:
        if h == fg or (h in _raised and not force):
            continue
        _raised.add(h)
        try:
            if _user32.IsIconic(h):
                _user32.ShowWindow(h, 9)       # SW_RESTORE
            _user32.BringWindowToTop(h)
            _user32.SetForegroundWindow(h)
            log.info("Petición de PIN traída al frente")
        except Exception:
            pass
    return bool(wins)
