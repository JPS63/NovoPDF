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

"""Firma con certificados del Llavero de macOS (Security.framework vía ctypes).

Incluye los certificados con clave privada del llavero del usuario y de
tarjetas inteligentes (DNIe u otras) que macOS expone mediante CryptoTokenKit.
La clave privada no sale del llavero: macOS pide permiso o el PIN si hace falta.
"""
from __future__ import annotations

import ctypes
import hashlib
import sys
from ctypes import POINTER, byref, c_char_p, c_int32, c_long, c_void_p

AVAILABLE = sys.platform == "darwin"


class KeychainError(Exception):
    pass


if AVAILABLE:
    _cf = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    _sec = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/Security.framework/Security")

    def _sym_value(lib, name):            # variable global de tipo puntero (CFStringRef...)
        return c_void_p.in_dll(lib, name).value

    def _sym_addr(lib, name):             # dirección de una estructura global
        return ctypes.addressof(ctypes.c_char.in_dll(lib, name))

    _cf.CFDictionaryCreate.restype = c_void_p
    _cf.CFDictionaryCreate.argtypes = [c_void_p, POINTER(c_void_p), POINTER(c_void_p), c_long, c_void_p, c_void_p]
    _cf.CFArrayGetCount.restype = c_long
    _cf.CFArrayGetCount.argtypes = [c_void_p]
    _cf.CFArrayGetValueAtIndex.restype = c_void_p
    _cf.CFArrayGetValueAtIndex.argtypes = [c_void_p, c_long]
    _cf.CFDataCreate.restype = c_void_p
    _cf.CFDataCreate.argtypes = [c_void_p, c_char_p, c_long]
    _cf.CFDataGetLength.restype = c_long
    _cf.CFDataGetLength.argtypes = [c_void_p]
    _cf.CFDataGetBytePtr.restype = c_void_p
    _cf.CFDataGetBytePtr.argtypes = [c_void_p]
    _cf.CFRelease.argtypes = [c_void_p]
    _cf.CFRetain.argtypes = [c_void_p]
    _cf.CFRetain.restype = c_void_p
    _cf.CFErrorGetCode.restype = c_long
    _cf.CFErrorGetCode.argtypes = [c_void_p]
    _cf.CFErrorCopyDescription.restype = c_void_p
    _cf.CFErrorCopyDescription.argtypes = [c_void_p]
    _cf.CFStringGetCString.restype = ctypes.c_bool
    _cf.CFStringGetCString.argtypes = [c_void_p, c_char_p, c_long, ctypes.c_uint32]
    _cf.CFGetTypeID.restype = c_long
    _cf.CFGetTypeID.argtypes = [c_void_p]
    _cf.CFArrayGetTypeID.restype = c_long

    _sec.SecItemCopyMatching.restype = c_int32
    _sec.SecItemCopyMatching.argtypes = [c_void_p, POINTER(c_void_p)]
    _sec.SecIdentityCopyCertificate.restype = c_int32
    _sec.SecIdentityCopyCertificate.argtypes = [c_void_p, POINTER(c_void_p)]
    _sec.SecIdentityCopyPrivateKey.restype = c_int32
    _sec.SecIdentityCopyPrivateKey.argtypes = [c_void_p, POINTER(c_void_p)]
    _sec.SecCertificateCopyData.restype = c_void_p
    _sec.SecCertificateCopyData.argtypes = [c_void_p]
    _sec.SecKeyCreateSignature.restype = c_void_p
    _sec.SecKeyCreateSignature.argtypes = [c_void_p, c_void_p, c_void_p, POINTER(c_void_p)]
    _sec.SecTrustCopyAnchorCertificates.restype = c_int32
    _sec.SecTrustCopyAnchorCertificates.argtypes = [POINTER(c_void_p)]

    kCFBooleanTrue = _sym_value(_cf, "kCFBooleanTrue")
    _KEYCB = _sym_addr(_cf, "kCFTypeDictionaryKeyCallBacks")
    _VALCB = _sym_addr(_cf, "kCFTypeDictionaryValueCallBacks")
    kSecClass = _sym_value(_sec, "kSecClass")
    kSecClassIdentity = _sym_value(_sec, "kSecClassIdentity")
    kSecReturnRef = _sym_value(_sec, "kSecReturnRef")
    kSecMatchLimit = _sym_value(_sec, "kSecMatchLimit")
    kSecMatchLimitAll = _sym_value(_sec, "kSecMatchLimitAll")
    try:
        kSecAttrAccessGroup = _sym_value(_sec, "kSecAttrAccessGroup")
        kSecAttrAccessGroupToken = _sym_value(_sec, "kSecAttrAccessGroupToken")
    except ValueError:
        kSecAttrAccessGroup = kSecAttrAccessGroupToken = None
    _ALG = {
        ("rsa", "sha256"): "kSecKeyAlgorithmRSASignatureDigestPKCS1v15SHA256",
        ("rsa", "sha384"): "kSecKeyAlgorithmRSASignatureDigestPKCS1v15SHA384",
        ("rsa", "sha512"): "kSecKeyAlgorithmRSASignatureDigestPKCS1v15SHA512",
        ("rsa", "sha1"): "kSecKeyAlgorithmRSASignatureDigestPKCS1v15SHA1",
        ("ec", "sha256"): "kSecKeyAlgorithmECDSASignatureDigestX962SHA256",
        ("ec", "sha384"): "kSecKeyAlgorithmECDSASignatureDigestX962SHA384",
        ("ec", "sha512"): "kSecKeyAlgorithmECDSASignatureDigestX962SHA512",
    }


def _data_bytes(cfdata) -> bytes:
    n = _cf.CFDataGetLength(cfdata)
    return ctypes.string_at(_cf.CFDataGetBytePtr(cfdata), n)


def _cfstr(s) -> str:
    buf = ctypes.create_string_buffer(2048)
    if s and _cf.CFStringGetCString(s, buf, 2048, 0x08000100):
        return buf.value.decode("utf-8", "replace")
    return ""


def _identities() -> list[int]:
    """Referencias SecIdentity (hay que liberarlas con CFRelease)."""
    queries = [[(kSecClass, kSecClassIdentity), (kSecReturnRef, kCFBooleanTrue),
                (kSecMatchLimit, kSecMatchLimitAll)]]
    if kSecAttrAccessGroupToken:
        queries.append(queries[0] + [(kSecAttrAccessGroup, kSecAttrAccessGroupToken)])
    out = []
    for q in queries:
        keys = (c_void_p * len(q))(*[k for k, _ in q])
        vals = (c_void_p * len(q))(*[v for _, v in q])
        d = _cf.CFDictionaryCreate(None, keys, vals, len(q), _KEYCB, _VALCB)
        res = c_void_p()
        st = _sec.SecItemCopyMatching(d, byref(res))
        _cf.CFRelease(d)
        if st != 0 or not res.value:
            continue
        if _cf.CFGetTypeID(res.value) == _cf.CFArrayGetTypeID():
            for i in range(_cf.CFArrayGetCount(res.value)):
                out.append(_cf.CFRetain(_cf.CFArrayGetValueAtIndex(res.value, i)))
            _cf.CFRelease(res.value)
        else:
            out.append(res.value)
    return out


def _identity_der(ident) -> bytes | None:
    cert = c_void_p()
    if _sec.SecIdentityCopyCertificate(ident, byref(cert)) != 0 or not cert.value:
        return None
    data = _sec.SecCertificateCopyData(cert.value)
    _cf.CFRelease(cert.value)
    if not data:
        return None
    b = _data_bytes(data)
    _cf.CFRelease(data)
    return b


def personal_certificates() -> list[bytes]:
    if not AVAILABLE:
        return []
    seen, out = set(), []
    for ident in _identities():
        try:
            der = _identity_der(ident)
            if der and der not in seen:
                seen.add(der)
                out.append(der)
        finally:
            _cf.CFRelease(ident)
    return out


def authority_certificates() -> tuple[list[bytes], list[bytes]]:
    """(raíces de confianza del sistema, intermedias)."""
    if not AVAILABLE:
        return [], []
    roots = []
    arr = c_void_p()
    if _sec.SecTrustCopyAnchorCertificates(byref(arr)) == 0 and arr.value:
        for i in range(_cf.CFArrayGetCount(arr.value)):
            data = _sec.SecCertificateCopyData(_cf.CFArrayGetValueAtIndex(arr.value, i))
            if data:
                roots.append(_data_bytes(data))
                _cf.CFRelease(data)
        _cf.CFRelease(arr.value)
    return roots, []


def sign_digest(cert_der: bytes, digest: bytes, hash_alg: str, key_algo: str) -> bytes:
    """Firma un resumen con la clave del llavero asociada al certificado (salida DER/PKCS#1)."""
    if not AVAILABLE:
        raise KeychainError("El Llavero solo está disponible en macOS.")
    alg_name = _ALG.get((key_algo, hash_alg))
    if not alg_name:
        raise KeychainError(f"Algoritmo no admitido: {key_algo}/{hash_alg}")
    alg = _sym_value(_sec, alg_name)
    target = hashlib.sha1(cert_der).digest()
    idents = _identities()
    try:
        ident = next((i for i in idents if (lambda d: d and hashlib.sha1(d).digest() == target)(_identity_der(i))), None)
        if ident is None:
            raise KeychainError("El certificado ya no está en el Llavero.")
        key = c_void_p()
        if _sec.SecIdentityCopyPrivateKey(ident, byref(key)) != 0 or not key.value:
            raise KeychainError("No se pudo acceder a la clave privada del certificado.")
        data = _cf.CFDataCreate(None, digest, len(digest))
        err = c_void_p()
        sig = _sec.SecKeyCreateSignature(key.value, alg, data, byref(err))
        _cf.CFRelease(data)
        _cf.CFRelease(key.value)
        if not sig:
            code, desc = 0, ""
            if err.value:
                code = _cf.CFErrorGetCode(err.value)
                d = _cf.CFErrorCopyDescription(err.value)
                desc = _cfstr(d)
                if d:
                    _cf.CFRelease(d)
                _cf.CFRelease(err.value)
            if code in (-128, -25293):
                raise KeychainError("Operación cancelada por el usuario.")
            raise KeychainError(f"No se pudo firmar con el certificado del Llavero ({code}). {desc}".strip())
        out = _data_bytes(sig)
        _cf.CFRelease(sig)
        return out
    finally:
        for i in idents:
            _cf.CFRelease(i)
