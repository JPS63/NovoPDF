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

from cryptography import x509
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
import datetime as dt
now=dt.datetime.now(dt.timezone.utc)
cak=rsa.generate_private_key(public_exponent=65537,key_size=2048)
caname=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,"AC Pruebas NovoPDF")])
ca=(x509.CertificateBuilder().subject_name(caname).issuer_name(caname).public_key(cak.public_key()).serial_number(1)
 .not_valid_before(now-dt.timedelta(days=1)).not_valid_after(now+dt.timedelta(days=3650))
 .add_extension(x509.BasicConstraints(ca=True,path_length=None),True).sign(cak,hashes.SHA256()))
k=rsa.generate_private_key(public_exponent=65537,key_size=2048)
sub=x509.Name([x509.NameAttribute(NameOID.COUNTRY_NAME,"ES"),x509.NameAttribute(NameOID.SERIAL_NUMBER,"IDCES-12345678Z"),
 x509.NameAttribute(NameOID.GIVEN_NAME,"JESÚS"),x509.NameAttribute(NameOID.SURNAME,"MUÑOZ PRUEBA"),
 x509.NameAttribute(NameOID.COMMON_NAME,"MUÑOZ PRUEBA JESÚS - 12345678Z")])
c=(x509.CertificateBuilder().subject_name(sub).issuer_name(caname).public_key(k.public_key()).serial_number(2)
 .not_valid_before(now-dt.timedelta(days=1)).not_valid_after(now+dt.timedelta(days=700))
 .add_extension(x509.KeyUsage(True,True,False,False,False,False,False,False,False),True).sign(cak,hashes.SHA256()))
open("prueba.pfx","wb").write(pkcs12.serialize_key_and_certificates(b"prueba",k,c,[ca],serialization.BestAvailableEncryption(b"1234")))
open("ca.der","wb").write(ca.public_bytes(serialization.Encoding.DER))
