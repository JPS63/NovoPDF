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

"""1.2.2: firma en segundo plano (PIN lento, error de PIN, dejar de esperar) y enlace «predeterminado»."""
import os, sys, shutil, time, hashlib
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["NOVOPDF_HOME"] = "/tmp/claude-0/sw"
os.makedirs("/tmp/claude-0/sw", exist_ok=True); os.makedirs("/tmp/claude-0/shots", exist_ok=True)
sys.path.insert(0, "/home/claude/novopdf/src")
HERE = os.path.dirname(os.path.abspath(__file__))
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
app = QApplication(sys.argv); app.setStyle("Fusion")
from novopdf.ui import theme, dialogs
app.setStyleSheet(theme.build_qss())
from novopdf.ui import mainwindow as mw
from novopdf.core import signing, certstore, fileassoc
import pymupdf
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.hazmat.primitives.asymmetric import padding, utils
from cryptography.hazmat.primitives import hashes
res = []
ok = lambda c, m: (res.append(bool(c)), print(("OK  " if c else "FAIL"), m))
msgs = []
QMessageBox.information = staticmethod(lambda *a, **k: msgs.append(("info", a[2])))
QMessageBox.warning = staticmethod(lambda *a, **k: msgs.append(("warn", a[2])))
QMessageBox.critical = staticmethod(lambda *a, **k: msgs.append(("error", a[2])))
dialogs.confirm = lambda *a, **k: True

key, cert, _ = pkcs12.load_key_and_certificates(open(os.path.join(HERE, "prueba.pfx"), "rb").read(), b"1234")
from asn1crypto import x509 as ax
from cryptography.hazmat.primitives.serialization import Encoding
der = cert.public_bytes(Encoding.DER)
choice = signing.CertChoice(cert=ax.Certificate.load(der), source="windows", der=der)

mode = {"delay": 0, "fail": None}
calls = {"hwnd": None, "thread": None}
import threading
def fake_sign_digest(cert_der, digest, hash_alg, key_algo, hwnd=None):
    calls["hwnd"] = hwnd; calls["thread"] = threading.current_thread().name
    time.sleep(mode["delay"])
    if mode["fail"]:
        raise certstore.StoreError(mode["fail"])
    return key.sign(digest, padding.PKCS1v15(), utils.Prehashed(hashes.SHA256()))
certstore.sign_digest = fake_sign_digest
prompt = {"n": 0}
def fake_bring(force=False):
    prompt["n"] += 1
    return prompt["n"] > 1
certstore.bring_prompt_to_front = fake_bring

out = {"p": ""}
def fake_sign_exec(self):
    self.choice = choice; self.pfx_signer = None
    self.out.setText(out["p"]); self.reason.setCurrentText("Conformidad")
    return True
dialogs.SignDialog.exec = fake_sign_exec

w = mw.MainWindow(); w.resize(1300, 850); w.show()
ok(not w.welcome.default_link.isVisible() or fileassoc.supported(), "enlace oculto donde no se puede usar (Linux)")
shutil.copy(os.path.join(HERE, "texto.pdf"), "/tmp/claude-0/sw/t.pdf")
w.open_file("/tmp/claude-0/sw/t.pdf"); app.processEvents()

# 1) PIN lento: la interfaz debe seguir respondiendo
mode.update(delay=3, fail=None); out["p"] = "/tmp/claude-0/sw/lento.pdf"
beats = []
hb = QTimer(); hb.setInterval(100); hb.timeout.connect(lambda: beats.append(time.monotonic())); hb.start()
shot = {}
def grab_wait():
    for top in app.topLevelWidgets():
        if isinstance(top, dialogs.SigningWaitDialog) and top.isVisible():
            top.grab().save("/tmp/claude-0/shots/firma_espera.png"); shot["status"] = top.status.text()
QTimer.singleShot(2500, grab_wait)
t0 = time.monotonic(); w.sign(0, pymupdf.Rect(330, 700, 540, 770)); dt_ = time.monotonic() - t0
hb.stop()
ok(dt_ >= 3 and len(beats) >= 20, f"interfaz responde durante la espera ({len(beats)} latidos en {dt_:.1f}s)")
ok(calls["thread"] == "NovoPDF-firma", f"firma en hilo aparte ({calls['thread']})")
ok("PIN" in shot.get("status", ""), f"aviso de PIN: {shot.get('status')}")
ok(os.path.isfile(out["p"]) and w.pdf.path == out["p"], "guardado y abierto el firmado")
r = signing.verify_pdf(open(out["p"], "rb").read())
ok(r and r[0].intact, "firma válida")
ok(msgs and msgs[-1][0] == "info", f"mensaje final: {msgs[-1] if msgs else None}")

# 2) PIN incorrecto -> error claro y nada guardado
msgs.clear(); mode.update(delay=0.5, fail="PIN incorrecto."); out["p"] = "/tmp/claude-0/sw/mal.pdf"
w.sign(0, None)
ok(not os.path.exists(out["p"]) and msgs and msgs[-1] == ("error", "PIN incorrecto."), f"PIN incorrecto: {msgs}")

# 3) Dejar de esperar -> no se guarda nada aunque la firma acabe después
msgs.clear(); mode.update(delay=4, fail=None); out["p"] = "/tmp/claude-0/sw/abandono.pdf"
def abandon():
    for top in app.topLevelWidgets():
        if isinstance(top, dialogs.SigningWaitDialog) and top.isVisible():
            top.reject()                       # antes de permitirlo: no debe cerrarse
            still = top.isVisible()
            top.allow_abandon(); top.grab().save("/tmp/claude-0/shots/firma_dejar.png")
            top.reject(); shot["still"] = still
QTimer.singleShot(1000, abandon)
w.sign(0, None)
ok(shot.get("still") is True, "no se puede cerrar la espera antes de tiempo")
QTest.qWait(4500)
ok(not os.path.exists(out["p"]), "tras dejar de esperar no se guarda nada")
ok(msgs and msgs[-1][0] == "warn", f"aviso de interrupción: {msgs[-1] if msgs else None}")

# 4) Enlace «Abrir siempre los PDF con NovoPDF» en la pantalla de inicio
fileassoc.supported = lambda: True; fileassoc.is_default = lambda: False
w.close_document(); app.processEvents(); w._refresh_default_offer(); QTest.qWait(100)
ok(w.welcome.default_link.isVisible(), "enlace visible si NovoPDF no es el predeterminado")
w.grab().save("/tmp/claude-0/shots/inicio_predeterminado.png")
fileassoc.is_default = lambda: True; w._refresh_default_offer()
ok(not w.welcome.default_link.isVisible(), "enlace oculto si ya es el predeterminado")
print("RESULT", "OK" if all(res) else "FAIL", sum(res), "/", len(res))
os._exit(0)
