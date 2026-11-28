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

"""Firma digital PAdES de documentos PDF (pyHanko).

Fuentes de certificado:
  * Almacén del sistema: «Personal» de Windows o Llavero de macOS (sin exportar la clave privada).
  * Fichero .pfx / .p12 con su contraseña.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import io
import os
import logging
import tempfile
import time
from dataclasses import dataclass

import pymupdf
from asn1crypto import x509
from asn1crypto.algos import SignedDigestAlgorithm
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign import fields, signers
from pyhanko.sign.signers.pdf_cms import Signer
from pyhanko.pdf_utils.layout import AxisAlignment, InnerScaling, SimpleBoxLayoutRule
from pyhanko.stamp import StaticStampStyle
from pyhanko_certvalidator import ValidationContext
from pyhanko_certvalidator.registry import SimpleCertificateStore

from . import certstore
from . import certstore as winstore  # compatibilidad (atributo AVAILABLE)


log = logging.getLogger("novopdf.firma")


class SigningError(Exception):
    pass


# ---------------------------------------------------------------- certificados
@dataclass
class CertChoice:
    cert: x509.Certificate
    source: str                      # "windows" | "pfx"
    der: bytes = b""
    pfx_path: str = ""

    @property
    def holder(self) -> str:
        return holder_name(self.cert)

    @property
    def issuer(self) -> str:
        n = self.cert.issuer.native
        return n.get("common_name") or n.get("organization_name") or "?"

    @property
    def valid_to(self) -> dt.datetime:
        return self.cert.not_valid_after

    @property
    def expired(self) -> bool:
        now = dt.datetime.now(dt.timezone.utc)
        return not (self.cert.not_valid_before <= now <= self.cert.not_valid_after)


def holder_name(cert: x509.Certificate) -> str:
    n = cert.subject.native
    given, sur = n.get("given_name"), n.get("surname")
    if given and sur:
        name = f"{given} {sur}"
    else:
        name = n.get("common_name") or cert.subject.human_friendly
    return str(name)


def holder_details(cert: x509.Certificate) -> str:
    """Datos adicionales (p. ej. NIF y organización) para mostrar al usuario."""
    n = cert.subject.native
    extra = []
    if n.get("serial_number"):
        extra.append(str(n["serial_number"]))
    if n.get("organization_name"):
        org = n["organization_name"]
        extra.append(org if isinstance(org, str) else ", ".join(org))
    return " · ".join(extra)


def _usable_for_signing(cert: x509.Certificate) -> bool:
    try:
        ku = cert.key_usage_value
        if ku is None:
            return True
        usages = set(ku.native)
        return bool(usages & {"digital_signature", "non_repudiation"})
    except Exception:
        return True


def windows_certificates() -> list[CertChoice]:
    out = []
    if not winstore.AVAILABLE:
        return out
    for der in certstore.personal_certificates():
        try:
            c = x509.Certificate.load(der)
            if _usable_for_signing(c):
                out.append(CertChoice(cert=c, source="windows", der=der))
        except Exception:
            continue
    out.sort(key=lambda c: (c.expired, c.holder.lower()))
    return out


def load_pfx(path: str, password: str) -> tuple[CertChoice, Signer]:
    try:
        signer = signers.SimpleSigner.load_pkcs12(path, passphrase=password.encode("utf-8") if password else None)
    except Exception as e:
        raise SigningError("No se pudo abrir el certificado. Compruebe la contraseña.") from e
    if signer is None:
        raise SigningError("No se pudo abrir el certificado. Compruebe la contraseña.")
    return CertChoice(cert=signer.signing_cert, source="pfx", pfx_path=path), signer


# ---------------------------------------------------------------- cadena / confianza
_cached_authorities = None


def _authorities():
    global _cached_authorities
    if _cached_authorities is None:
        roots, cas = [], []
        try:
            r, c = certstore.authority_certificates()
            for der in r:
                try:
                    roots.append(x509.Certificate.load(der))
                except Exception:
                    pass
            for der in c:
                try:
                    cas.append(x509.Certificate.load(der))
                except Exception:
                    pass
        except Exception:
            pass
        _cached_authorities = (roots, cas)
    return _cached_authorities


def _build_chain(cert: x509.Certificate) -> list[x509.Certificate]:
    roots, cas = _authorities()
    pool = cas + roots
    chain = []
    cur = cert
    for _ in range(8):
        if cur.self_signed != "no":
            break
        issuer = next((c for c in pool if c.subject == cur.issuer and c not in chain), None)
        if issuer is None:
            break
        chain.append(issuer)
        cur = issuer
    return chain


class WindowsStoreSigner(Signer):
    """Firmante que delega la operación criptográfica en el sistema (Windows o macOS)."""

    def __init__(self, choice: CertChoice, hwnd: int | None = None):
        cert = choice.cert
        self._der = choice.der
        self.hwnd = hwnd        # ventana sobre la que debe aparecer la petición de PIN
        self._algo = "ec" if cert.public_key.algorithm == "ec" else "rsa"
        mech = SignedDigestAlgorithm({"algorithm": "sha256_ecdsa" if self._algo == "ec" else "sha256_rsa"})
        super().__init__(signing_cert=cert, signature_mechanism=mech,
                         cert_registry=SimpleCertificateStore.from_certs(_build_chain(cert)))

    async def async_sign_raw(self, data: bytes, digest_algorithm: str, dry_run=False) -> bytes:
        bits = self.signing_cert.public_key.bit_size
        if dry_run:
            if self._algo == "ec":
                return bytes(2 * ((bits + 7) // 8) + 9)
            return bytes((bits + 7) // 8)
        digest = hashlib.new(digest_algorithm, data).digest()
        try:
            log.info("Solicitando la firma al %s (%s, %d bits)", certstore.NAME, self._algo, bits)
            t0 = time.monotonic()
            sig = certstore.sign_digest(self._der, digest, digest_algorithm, self._algo, hwnd=self.hwnd)
            log.info("Firma criptográfica obtenida en %.1f s", time.monotonic() - t0)
            return sig
        except certstore.StoreError as e:
            log.warning("El almacén de certificados devolvió un error: %s", e)
            raise SigningError(str(e)) from e


def signer_for(choice: CertChoice, pfx_signer: Signer | None = None, hwnd: int | None = None) -> Signer:
    if choice.source == "windows":
        return WindowsStoreSigner(choice, hwnd)
    if pfx_signer is None:
        raise SigningError("Falta el certificado.")
    # completar la cadena con las autoridades conocidas
    try:
        extra = _build_chain(choice.cert)
        if extra and pfx_signer.cert_registry is not None:
            for c in extra:
                pfx_signer.cert_registry.register(c)
    except Exception:
        pass
    return pfx_signer


# ---------------------------------------------------------------- sello visible
ACCENT = (0.16, 0.36, 0.86)


def _stamp_pdf(width: float, height: float, name: str, details: str, when: dt.datetime,
               reason: str, location: str) -> str:
    doc = pymupdf.open()
    page = doc.new_page(width=width, height=height)
    r = page.rect
    # Fondo y bordes
    page.draw_rect(r, color=None, fill=(0.96, 0.97, 1.0))
    page.draw_rect(pymupdf.Rect(0, 0, max(3, width * 0.02), height), color=None, fill=ACCENT)
    page.draw_rect(r, color=ACCENT, width=0.8)
    pad = max(4, min(width, height) * 0.07)
    x0 = max(3, width * 0.02) + pad
    lines = [("hebo", "Firmado digitalmente por", 0.7, ACCENT),
             ("hebo", name, 1.0, (0.08, 0.1, 0.16))]
    if details:
        lines.append(("helv", details, 0.75, (0.3, 0.32, 0.38)))
    lines.append(("helv", "Fecha: " + when.strftime("%d/%m/%Y %H:%M:%S"), 0.8, (0.2, 0.22, 0.28)))
    if reason:
        lines.append(("helv", "Motivo: " + reason, 0.8, (0.2, 0.22, 0.28)))
    if location:
        lines.append(("helv", "Lugar: " + location, 0.8, (0.2, 0.22, 0.28)))
    avail_w = width - x0 - pad
    avail_h = height - 2 * pad
    # Tamaño base que hace caber todas las líneas
    base = 12.0
    while base > 3:
        total_h = sum(base * f * 1.25 for _, _, f, _ in lines)
        too_wide = any(pymupdf.get_text_length(t, fontname=fn, fontsize=base * f) > avail_w
                       for fn, t, f, _ in lines)
        if total_h <= avail_h and not too_wide:
            break
        base -= 0.25
    total_h = sum(base * f * 1.25 for _, _, f, _ in lines)
    y = pad + (avail_h - total_h) / 2
    for fn, t, f, color in lines:
        fs = base * f
        y += fs * 1.05
        page.insert_text((x0, y), t, fontname=fn, fontsize=fs, color=color)
        y += fs * 0.2
    fd, path = tempfile.mkstemp(suffix=".pdf", prefix="novopdf_sello_")
    os.close(fd)
    doc.save(path)
    doc.close()
    return path


def _to_pdf_box(page: pymupdf.Page, rect: pymupdf.Rect) -> tuple[int, int, int, int]:
    """Convierte un rectángulo visible de PyMuPDF a coordenadas PDF (origen abajo-izq.)."""
    r = rect * page.derotation_matrix            # a página sin rotar (coordenadas MuPDF)
    r = r * ~page.transformation_matrix           # a espacio PDF
    r.normalize()
    return (round(r.x0), round(r.y0), round(r.x1), round(r.y1))


# ---------------------------------------------------------------- firmar
@dataclass
class PreparedSignature:
    """Firma preparada en el hilo principal (todo lo que usa PyMuPDF).
    La parte criptográfica (perform_signature) puede ir en un hilo aparte."""
    pdf_bytes: bytes
    field_name: str
    spec: object
    style: object
    reason: str
    location: str
    password: str | None
    stamp_path: str | None = None

    def cleanup(self):
        if self.stamp_path and os.path.exists(self.stamp_path):
            try:
                os.remove(self.stamp_path)
            except OSError:
                pass
        self.stamp_path = None


def prepare_signature(pdf_bytes: bytes, signer: Signer, *, page_index: int = 0,
                      rect: pymupdf.Rect | None = None, reason: str = "", location: str = "",
                      password: str | None = None, field_name: str | None = None) -> PreparedSignature:
    """Elige el nombre del campo y genera el sello visible (usa PyMuPDF: hilo principal).
    field_name: campo de firma vacío que ya existe en el formulario (se firma en él)."""
    tmp_doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        if tmp_doc.needs_pass:
            tmp_doc.authenticate(password or "")
        existing = set()
        for p in tmp_doc:
            for w in p.widgets() or []:
                if w.field_name:
                    existing.add(w.field_name)
        use_existing = bool(field_name) and field_name in existing
        if not use_existing:
            n = 1
            while f"Firma{n}" in existing:
                n += 1
            field_name = f"Firma{n}"
        stamp_path = None
        if rect is not None and not rect.is_empty:
            page = tmp_doc[page_index]
            box = _to_pdf_box(page, rect)
            rot = page.rotation
            design = _stamp_pdf(rect.width, rect.height, holder_name(signer.signing_cert),
                                holder_details(signer.signing_cert), dt.datetime.now(),
                                reason, location)
            # El sello se dibuja en el espacio sin rotar de la página: se gira su
            # contenido para que se vea derecho en pantalla.
            a = pymupdf.open(design)
            b = pymupdf.open()
            if rot in (90, 270):
                bp = b.new_page(width=rect.height, height=rect.width)
            else:
                bp = b.new_page(width=rect.width, height=rect.height)
            bp.show_pdf_page(bp.rect, a, 0, rotate=rot)
            fd, stamp_path = tempfile.mkstemp(suffix=".pdf", prefix="novopdf_sello_")
            os.close(fd)
            b.save(stamp_path)
            a.close()
            b.close()
            os.remove(design)
            spec = None if use_existing else fields.SigFieldSpec(field_name, on_page=page_index, box=box)
            style = StaticStampStyle.from_pdf_file(
                stamp_path, border_width=0,
                background_layout=SimpleBoxLayoutRule(
                    x_align=AxisAlignment.ALIGN_MID, y_align=AxisAlignment.ALIGN_MID,
                    inner_content_scaling=InnerScaling.STRETCH_FILL))
        else:
            spec = None if use_existing else fields.SigFieldSpec(field_name, on_page=page_index, box=None)
            style = None
    finally:
        tmp_doc.close()
    return PreparedSignature(pdf_bytes=pdf_bytes, field_name=field_name, spec=spec, style=style,
                             reason=reason, location=location, password=password,
                             stamp_path=stamp_path)


def perform_signature(prep: PreparedSignature, signer: Signer) -> bytes:
    """Firma (pyHanko + certificado). No usa PyMuPDF: se puede ejecutar en otro hilo.
    Devuelve los bytes del PDF firmado."""
    writer = IncrementalPdfFileWriter(io.BytesIO(prep.pdf_bytes), strict=False)
    if writer.prev.encrypted:
        writer.encrypt(prep.password or "")
    meta = signers.PdfSignatureMetadata(field_name=prep.field_name, md_algorithm="sha256",
                                        reason=prep.reason or None, location=prep.location or None,
                                        name=holder_name(signer.signing_cert))
    pdf_signer = signers.PdfSigner(meta, signer, stamp_style=prep.style, new_field_spec=prep.spec)
    out = io.BytesIO()
    try:
        pdf_signer.sign_pdf(writer, output=out)
    except SigningError:
        raise
    except Exception as e:
        cause = e
        while cause.__cause__ is not None and not isinstance(cause, SigningError):
            cause = cause.__cause__
        if isinstance(cause, SigningError):
            raise cause
        raise SigningError(f"No se pudo firmar el documento: {e}") from e
    return out.getvalue()


def sign_pdf(pdf_bytes: bytes, out_path: str, signer: Signer, *, page_index: int = 0,
             rect: pymupdf.Rect | None = None, reason: str = "", location: str = "",
             password: str | None = None, field_name: str | None = None) -> None:
    """Firma el PDF (bytes) y lo guarda en out_path (todo en el hilo actual).
    rect: zona visible en coordenadas de pantalla (None = firma invisible)."""
    prep = prepare_signature(pdf_bytes, signer, page_index=page_index, rect=rect, reason=reason,
                             location=location, password=password, field_name=field_name)
    try:
        data = perform_signature(prep, signer)
        from .document import write_atomic
        write_atomic(out_path, data)
    finally:
        prep.cleanup()


# ---------------------------------------------------------------- verificar
@dataclass
class SignatureReport:
    field: str
    signer: str
    details: str
    issuer: str
    when: str
    intact: bool
    covers_all: bool
    trusted: bool
    reason: str
    summary: str


def verify_pdf(data: bytes, password: str | None = None) -> list[SignatureReport]:
    from pyhanko.sign.validation import validate_pdf_signature
    reader = PdfFileReader(io.BytesIO(data), strict=False)
    if reader.encrypted:
        reader.decrypt(password or "")
    roots, cas = _authorities()
    vc = ValidationContext(trust_roots=roots or None, other_certs=cas, allow_fetching=False,
                           revocation_mode="soft-fail")
    out = []
    for sig in reader.embedded_signatures:
        try:
            st = validate_pdf_signature(sig, vc)
            cert = st.signing_cert
            intact = bool(st.intact and st.valid)
            cov = getattr(st, "coverage", None)
            covers_all = cov is not None and cov.name == "ENTIRE_FILE"
            modified_after = getattr(st, "modification_level", None)
            trusted = bool(st.trusted)
            when = st.signer_reported_dt
            when_s = when.astimezone().strftime("%d/%m/%Y %H:%M:%S") if when else "—"
            if not intact:
                summary = "La firma NO es válida: el documento se alteró después de firmarse."
            elif not covers_all:
                summary = ("Firma correcta. El documento tiene cambios posteriores "
                           "(otras firmas o anotaciones añadidas después).")
            else:
                summary = "Firma correcta: el documento no se ha modificado desde que se firmó."
            if intact and not trusted:
                summary += (" El certificado no se ha podido verificar contra las autoridades "
                            "de confianza instaladas en este equipo.")
            reason = ""
            try:
                reason = str(sig.sig_object.get("/Reason", "") or "")
            except Exception:
                pass
            out.append(SignatureReport(
                field=sig.field_name, signer=holder_name(cert), details=holder_details(cert),
                issuer=(cert.issuer.native.get("common_name") or ""), when=when_s,
                intact=intact, covers_all=covers_all, trusted=trusted, reason=reason,
                summary=summary))
            _ = modified_after
        except Exception as e:
            out.append(SignatureReport(field=getattr(sig, "field_name", "?"), signer="?", details="",
                                       issuer="", when="—", intact=False, covers_all=False,
                                       trusted=False, reason="",
                                       summary=f"No se pudo verificar la firma: {e}"))
    return out
