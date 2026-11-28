# NovoPDF - aplicación sencilla para trabajar con documentos PDF
# Copyright (C) 2026 Jesús Punzón Suero
# SPDX-License-Identifier: AGPL-3.0-or-later

"""1.7.0: despertar impresoras de red (partes que no dependen de Windows)."""
import os, socket, sys, threading, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from novopdf.core import printwake as pw

res = []
ok = lambda c, m: (res.append(bool(c)), print(("OK  " if c else "FAIL"), m))

ok(pw.host_from_text("IP_192.168.1.37") == "192.168.1.37", "puerto TCP/IP estándar")
ok(pw.host_from_text("192.168.0.20_1") == "192.168.0.20", "puerto con sufijo")
ok(pw.host_from_text("http://192.168.1.50:80/WSD/DEVICE") == "192.168.1.50", "URL de WSD")
ok(pw.host_from_text("ipp://EPSON1A2B3C.local:631/ipp/print") == "EPSON1A2B3C.local", "URL IPP con nombre")
ok(pw.host_from_text("EP1A2B3C:EPSON ET-2810 Series") == "", "puerto EpsonNet sin IP")
ok(pw.host_from_text("127.0.0.1") == "", "no se toma localhost")
for port, drv, kind in (("WSD-6f1a2b3c-0000-4c11", "", "wsd"), ("USB001", "", "usb"), ("IP_10.0.0.5", "", "tcp"),
                        ("PORTPROMPT:", "Microsoft Print To PDF", "virtual"), ("EP1A2B3C:EPSON ET-2810", "", "epson"),
                        ("\\\\servidor\\Epson", "", "shared"), ("\\\\.\\pipe\\NovoPDF-impresora", "Microsoft Print To PDF", "virtual")):
    ok(pw.port_kind(port, drv) == kind, f"tipo de puerto {port} → {kind}")

st = pw.PrinterState(name="EPSON", status=0x80 | 0x400000, attributes=pw.ATTR_WORK_OFFLINE,
                     jobs=[(5, "informe.pdf", pw.JOB_STATUS_ERROR, "jps"), (6, "otro.pdf", 0, "jps")])
ok("sin conexión" in st.status_text() and "reposo" in st.status_text() and "usar sin conexión" in st.status_text(),
   f"estado legible ({st.status_text()})")
ok([j[0] for j in st.bad_jobs] == [5], "trabajos atascados")

# impresora «dormida» que tarda en contestar
srv = socket.socket()
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.2", 0))
port = srv.getsockname()[1]
ok(pw.reachable("127.0.0.2", (port,), 0.3) == 0, "dormida: no contesta")


def despierta():
    time.sleep(2.5)
    srv.listen(5)
threading.Thread(target=despierta, daemon=True).start()
t0 = time.monotonic()
prog = []
woke = pw.wake("127.0.0.2", timeout=15, progress=lambda e, t: prog.append(e), ports=(port,))
ok(woke and 2 < time.monotonic() - t0 < 8 and prog, f"se insiste hasta que contesta ({time.monotonic() - t0:.1f} s)")
ok(not pw.wake("127.0.0.3", timeout=2, ports=(port + 1,)), "si no contesta, se rinde al acabar el tiempo")
srv.close()
print(f"\n{sum(res)}/{len(res)}")
sys.exit(0 if all(res) else 1)
