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

"""Punto de entrada de NovoPDF."""
from __future__ import annotations

import logging
import os
import sys
import traceback


def _setup_logging():
    from .paths import data_dir
    logging.basicConfig(filename=os.path.join(data_dir(), "novopdf.log"), level=logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s", encoding="utf-8")
    for name in ("pyhanko", "pyhanko_certvalidator", "fontTools"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    # Pasos de la firma y de la asociación de PDF: ayudan a diagnosticar problemas
    try:  # mensajes internos de MuPDF/PyMuPDF al registro (ayudan a diagnosticar)
        import pymupdf
        pymupdf.set_messages(pylogging=True, pylogging_name="novopdf.pymupdf")
        logging.getLogger("novopdf.pymupdf").setLevel(logging.INFO)
    except Exception:
        pass
    for name in ("novopdf.firma", "novopdf.asociacion", "novopdf.impresion", "novopdf.edicion", "novopdf.exportar",
                 "novopdf.instancia", "novopdf.escaner"):
        logging.getLogger(name).setLevel(logging.INFO)


def main():
    _setup_logging()
    # Si NovoPDF ya está abierto, se le pasan los archivos (se abren en pestañas) y se termina.
    files = [os.path.abspath(a) for a in sys.argv[1:] if not a.startswith("-") and os.path.isfile(a)]
    server = None
    if "--nueva-ventana" not in sys.argv:
        from . import instance
        try:
            role, server = instance.claim(files)
        except Exception as e:  # noqa
            logging.getLogger("novopdf.instancia").info("Ventana única no disponible: %s", e)
            role = "alone"
        if role == "forwarded":
            return 0
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    from PySide6.QtCore import QLocale, QTranslator, QLibraryInfo, Qt
    from PySide6.QtGui import QFont, QIcon
    from PySide6.QtWidgets import QApplication, QMessageBox

    if sys.platform.startswith("win"):
        try:  # icono propio en la barra de tareas
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("NovoPDF.App")
        except Exception:
            pass

    from PySide6.QtCore import QEvent, QObject, Signal

    class App(QApplication):
        """En macOS los PDF abiertos desde el Finder llegan como evento, no como argumento."""
        pending: list = []
        window = None

        def event(self, e):
            if e.type() == QEvent.FileOpen:
                path = e.file()
                if self.window is not None:
                    from .ui.mainwindow import MainWindow
                    w = MainWindow.target() or self.window
                    w.open_file(path)
                else:
                    self.pending.append(path)
                return True
            return super().event(e)

    class Relay(QObject):
        """Pasa al hilo de la ventana los archivos que envía otro proceso de NovoPDF."""
        files = Signal(list)

    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = App(sys.argv)
    app.setApplicationName("NovoPDF")
    app.setOrganizationName("NovoPDF")
    app.setStyle("Fusion")
    app.setPalette(app.style().standardPalette())   # siempre tema claro (también en modo oscuro)
    QLocale.setDefault(QLocale(QLocale.Spanish, QLocale.Spain))
    tr = QTranslator(app)
    if tr.load(QLocale(QLocale.Spanish), "qtbase", "_", QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
        app.installTranslator(tr)
    if sys.platform.startswith("win"):
        font = QFont("Segoe UI")
        font.setPointSizeF(10)
    else:
        font = QFont(app.font().family())
        font.setPointSizeF(13 if sys.platform == "darwin" else 10)
    app.setFont(font)
    from .ui import theme, icons
    app.setStyleSheet(theme.build_qss())
    app.setWindowIcon(QIcon(icons.app_icon_pixmap(256)))

    from .ui.mainwindow import MainWindow
    win = MainWindow()

    def excepthook(t, v, tb):
        msg = "".join(traceback.format_exception(t, v, tb))
        logging.error(msg)
        QMessageBox.critical(MainWindow.target(), "Error inesperado",
                             f"Se ha producido un error inesperado:\n\n{v}\n\n"
                             "Los detalles se han guardado en el registro de errores (novopdf.log) "
                             "de la carpeta de datos de NovoPDF.")
    sys.excepthook = excepthook

    win.show()
    app.window = win
    if server is not None:
        relay = Relay()

        def bring(paths):
            w = MainWindow.target()
            if w is None:
                w = MainWindow()
                w.show()
            w.bring_to_front()
            if paths:
                w.open_files(paths)

        relay.files.connect(bring)
        app._relay = relay
        server.on_open = relay.files.emit          # desde el hilo del servidor: va por la cola de Qt
        early, server.pending = server.pending, []
        for paths in early:
            relay.files.emit(paths)
        app.aboutToQuit.connect(server.close)
    if files:
        win.open_files(files)
    elif app.pending:
        win.open_files(list(app.pending))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
