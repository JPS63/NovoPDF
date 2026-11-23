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

"""Almacén de certificados del sistema: Windows (CryptoAPI/CNG) o macOS (Llavero)."""
from __future__ import annotations

import sys

if sys.platform == "darwin":
    from . import keychain as _impl
    StoreError = _impl.KeychainError
    NAME = "Llavero de macOS"
else:
    from . import winstore as _impl
    StoreError = _impl.WinStoreError
    NAME = "almacén de certificados de Windows"

AVAILABLE = _impl.AVAILABLE


def personal_certificates() -> list[bytes]:
    return _impl.personal_certificates()


def authority_certificates():
    return _impl.authority_certificates()


def sign_digest(cert_der: bytes, digest: bytes, hash_alg: str, key_algo: str,
                hwnd: int | None = None) -> bytes:
    """hwnd: ventana (Windows) sobre la que el sistema debe mostrar la petición de PIN."""
    if getattr(_impl, "ACCEPTS_HWND", False):
        return _impl.sign_digest(cert_der, digest, hash_alg, key_algo, hwnd=hwnd)
    return _impl.sign_digest(cert_der, digest, hash_alg, key_algo)


def bring_prompt_to_front(force: bool = False) -> bool:
    """Si el sistema está mostrando una petición de PIN/contraseña, la trae al frente.
    Devuelve True si hay una petición abierta."""
    fn = getattr(_impl, "bring_prompt_to_front", None)
    try:
        return bool(fn(force)) if fn else False
    except Exception:
        return False
