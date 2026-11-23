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

"""Ventana principal de NovoPDF."""
from __future__ import annotations

import logging
import os
import sys
import threading
from dataclasses import dataclass

import pymupdf
from PySide6.QtCore import QEvent, QObject, QPoint, QSettings, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QButtonGroup, QFileDialog, QFrame, QHBoxLayout,
                               QLabel, QLineEdit, QMainWindow, QMessageBox, QProgressDialog,
                               QPushButton, QSpinBox, QStackedWidget, QTabBar, QToolButton,
                               QVBoxLayout, QWidget)

from .. import __version__
from ..core import editing, ocr
from ..core.document import PasswordRequired, PdfDocument
from ..paths import data_dir
from . import dialogs, icons, theme
from .thumbs import ThumbList
from .viewer import (FORM_CREATE, FORM_TOOLS, MARK_TOOLS, T_ADD_IMAGE, T_ADD_TEXT, T_EDIT_TEXT, T_ERASE,
                     T_F_CHECK, T_F_COMBO, T_F_LIST, T_F_RADIO, T_F_SIGN, T_F_TEXT, T_FORM_EDIT,
                     T_HIGHLIGHT, T_IMAGES, T_SELECT, T_SIGN, T_STRIKE, T_UNDERLINE, T_UNMARK, Viewer)
from .welcome import Welcome

PDF_FILTER = "Documentos PDF (*.pdf)"
OPEN_FILTER = "PDF e imágenes (*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp);;Documentos PDF (*.pdf);;Todos los archivos (*)"
IMG_FILTER = "Imágenes (*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.gif)"
INSERT_FILTER = "PDF e imágenes (*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp)"

HINTS = {
    T_SELECT: ("info", "cursor", "Arrastra sobre el texto para seleccionarlo y pulsa Ctrl+C para copiarlo."),
    T_EDIT_TEXT: ("info", "text_edit", "Haz clic en el párrafo que quieras modificar. Se abrirá una ventana para escribir el nuevo texto."),
    T_ADD_TEXT: ("info", "text_add", "Haz clic en el lugar de la página donde quieras escribir."),
    T_IMAGES: ("info", "image", "Haz clic en una imagen para seleccionarla. Arrástrala para moverla; usa la esquina inferior derecha para cambiar su tamaño."),
    T_ADD_IMAGE: ("info", "image_add", "Dibuja un recuadro en la página donde quieras colocar la imagen (o haz clic)."),
    T_ERASE: ("warning", "eraser", "Dibuja un recuadro sobre lo que quieras borrar. Se eliminará todo el contenido de esa zona."),
    T_SIGN: ("success", "sign", "Dibuja un recuadro donde quieras que aparezca tu firma (o haz clic para un tamaño estándar)."),
    T_HIGHLIGHT: ("info", "highlighter", "Arrastra sobre el texto que quieras resaltar. Para quitar una marca, haz clic derecho sobre ella."),
    T_UNDERLINE: ("info", "underline", "Arrastra sobre el texto que quieras subrayar. Para quitar una marca, haz clic derecho sobre ella."),
    T_STRIKE: ("info", "strike", "Arrastra sobre el texto que quieras tachar. Para quitar una marca, haz clic derecho sobre ella."),
    T_UNMARK: ("warning", "unmark", "Haz clic en un resaltado, subrayado o tachado para quitarlo."),
    T_FORM_EDIT: ("info", "f_edit", "Haz clic en un campo para seleccionarlo. Arrástralo para moverlo, usa la esquina para "
                  "cambiar su tamaño, doble clic para sus propiedades y Supr para eliminarlo."),
    T_F_TEXT: ("info", "f_text", "Dibuja el recuadro del campo de texto (o haz clic para un tamaño estándar). "
               "Su nombre se toma del texto que tenga al lado."),
    T_F_CHECK: ("info", "f_check", "Haz clic donde irá cada casilla (o dibuja su recuadro)."),
    T_F_RADIO: ("info", "f_radio", "Haz clic donde irá cada opción. Las opciones del mismo grupo se excluyen entre sí "
                "(al marcar una se desmarcan las demás)."),
    T_F_COMBO: ("info", "f_combo", "Dibuja el recuadro de la lista desplegable; después escribirás sus opciones."),
    T_F_LIST: ("info", "f_list", "Dibuja el recuadro del cuadro de lista; después escribirás sus opciones."),
    T_F_SIGN: ("success", "f_sign", "Dibuja el recuadro donde se firmará. Quien rellene el formulario podrá firmar "
               "haciendo clic en él."),
}
# herramientas de cada pestaña de la cinta (al cambiar de pestaña se vuelve a «Seleccionar»)
TAB_TOOLS = {2: (T_EDIT_TEXT, T_ADD_TEXT, T_IMAGES, T_ADD_IMAGE, T_ERASE, T_HIGHLIGHT, T_UNDERLINE, T_STRIKE, T_UNMARK),
             3: FORM_TOOLS, 4: (T_SIGN,)}
TAB_FORM, TAB_SIGN, TAB_OCR = 3, 4, 5


class OcrWorker(QThread):
    progress = Signal(int, int)
    done = Signal(bytes, int)
    failed = Signal(str)

    def __init__(self, data, pages, lang, dpi, only_needed):
        super().__init__()
        self.args = (data, pages, lang, dpi, only_needed)
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        data, pages, lang, dpi, only = self.args
        try:
            out, words = ocr.ocr_document_bytes(
                data, pages, lang, dpi, progress=lambda k, n, i: self.progress.emit(k, n),
                cancelled=lambda: self._cancel, only_needed=only)
            if self._cancel:
                self.failed.emit("")
            else:
                self.done.emit(out, words)
        except Exception as e:  # noqa
            self.failed.emit(str(e))


class ExportWorker(QThread):
    progress = Signal(int, int)
    done = Signal(list)
    failed = Signal(str)

    def __init__(self, data, opts):
        super().__init__()
        self.data, self.opts = data, opts
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        from ..core import export
        try:
            files = export.export_pages(self.data, progress=lambda k, n: self.progress.emit(k, n),
                                        cancelled=lambda: self._cancel, **self.opts)
            self.done.emit(files)
        except Exception as e:  # noqa
            self.failed.emit(str(e))


class OfficeWorker(QThread):
    """Exporta a Word o Excel en segundo plano (con su propia copia del documento)."""
    progress = Signal(int, int)
    done = Signal(dict)
    failed = Signal(str)

    def __init__(self, data, job):
        super().__init__()
        self.data, self.job = data, job
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        from ..core import office
        doc = None
        try:
            doc = pymupdf.open(stream=self.data, filetype="pdf")
            prog = lambda k, n: (self.progress.emit(k, n), not self._cancel)[1]
            j = self.job
            tmp = j["path"] + ".tmp"
            if j["kind"] == "docx":
                stats = office.to_docx(doc, j["pages"], tmp, office.WordOptions(**j["opts"]), progress=prog)
            else:
                stats = office.to_xlsx(doc, j["pages"], tmp, office.ExcelOptions(**j["opts"]), progress=prog)
            os.replace(tmp, j["path"])
            self.done.emit(stats)
        except office.Cancelled:
            self.failed.emit("")
        except PermissionError:
            self.failed.emit("No se puede escribir el archivo. Si está abierto en Word o Excel, ciérralo y vuelve a intentarlo.")
        except Exception as e:  # noqa
            logging.getLogger("novopdf.exportar").exception("Exportación fallida")
            self.failed.emit(f"No se pudo exportar: {e}")
        finally:
            try:
                if os.path.exists(self.job["path"] + ".tmp"):
                    os.remove(self.job["path"] + ".tmp")
            except OSError:
                pass
            if doc is not None:
                doc.close()


class _SignBridge(QObject):
    """Lleva el resultado de la firma (hilo aparte) al hilo de la interfaz."""
    done = Signal(bytes)
    failed = Signal(str)


def _close(prog):
    """Cierra un QProgressDialog sin emitir «canceled» (que cancelaría el trabajo)."""
    try:
        prog.canceled.disconnect()
    except (RuntimeError, TypeError):
        pass
    prog.close()


class ScanWorker(QThread):
    page = Signal(object)
    done = Signal(int)
    failed = Signal(str, bool)

    def __init__(self, opts):
        super().__init__()
        self.opts = opts
        self.cancelled_flag = False

    def cancel(self):
        self.cancelled_flag = True

    def run(self):
        from ..core import scanner
        scanner.com_init()
        try:
            n = scanner.scan(self.opts, on_page=self.page.emit, cancelled=lambda: self.cancelled_flag)
            self.done.emit(n)
        except scanner.NoPaper as e:
            self.failed.emit(str(e), True)
        except scanner.ScannerError as e:
            self.failed.emit(str(e), False)
        except Exception as e:  # noqa
            self.failed.emit(f"Error inesperado del escáner: {e}", False)
        finally:
            scanner.com_uninit()


class PageBox(QLineEdit):
    """Cuadro para escribir el número de página."""

    def __init__(self):
        super().__init__()
        from PySide6.QtGui import QIntValidator
        self._max = 1
        self._val = QIntValidator(1, 1, self)
        self.setValidator(self._val)
        self.setFixedWidth(56)
        self.setAlignment(Qt.AlignCenter)
        self.setText("1")

    def setMaximum(self, n):
        self._max = max(1, n)
        self._val.setTop(self._max)

    def setValue(self, v):
        self.setText(str(v))

    def value(self) -> int:
        try:
            return max(1, min(int(self.text()), self._max))
        except ValueError:
            return 1


class RibbonButton(QToolButton):
    def __init__(self, text, icon_name, tip="", checkable=False):
        super().__init__()
        self.setObjectName("RibbonButton")
        self.setText(text)
        self.setIcon(icons.icon(icon_name))
        self.setIconSize(QSize(24, 24))
        self.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.setCheckable(checkable)
        self.setToolTip(theme.keys(tip or text.replace("\n", " ")))
        self.setCursor(Qt.PointingHandCursor)
        self.setAutoRaise(True)


@dataclass
class DocTab:
    """Un documento abierto en una pestaña y cómo se estaba viendo."""
    pdf: PdfDocument
    page: int = 0
    zoom: float | None = None
    fit: str | None = "width"
    scanned: bool = False
    sign_warned: bool = False
    src: str | None = None           # archivo del que se abrió (PDF o imagen)
    fp: object = None                # huella del contenido (core.fileid.Fingerprint)
    xfa_warned: bool = False         # ya se avisó de que el formulario XFA se convierte


class MainWindow(QMainWindow):
    windows: list = []               # ventanas abiertas (se pueden sacar pestañas a otras)
    _closed: list = []               # ventanas cerradas pendientes de borrar
    last_active = None               # la última que tuvo el foco: ahí van los archivos nuevos

    @classmethod
    def target(cls):
        """Ventana donde abrir lo que llega de fuera (Explorador, Finder)."""
        if cls.last_active is not None and cls.last_active in cls.windows:
            return cls.last_active
        return cls.windows[-1] if cls.windows else None

    @classmethod
    def find_open(cls, path: str, exclude=None):
        """(ventana, índice) de la pestaña que ya tiene abierto ese archivo, en cualquier ventana."""
        from ..core import fileid
        for w in list(cls.windows):
            for k, d in enumerate(w.docs):
                if d is exclude:
                    continue
                if fileid.same_file(d.src or d.pdf.path, path) or fileid.same_file(d.pdf.path, path):
                    return w, k
        return None, -1

    @classmethod
    def find_same_content(cls, fp):
        """(ventana, índice) de un documento abierto, sin cambios, idéntico byte a byte."""
        if fp is None or fp.digest is None:
            return None, -1
        for w in list(cls.windows):
            for k, d in enumerate(w.docs):
                if d.fp is not None and not d.pdf.modified and fp.matches(d.fp):
                    return w, k
        return None, -1

    def __init__(self):
        super().__init__()
        MainWindow.windows.append(self)
        MainWindow.last_active = self
        self.settings = QSettings(os.path.join(data_dir(), "novopdf.ini"), QSettings.IniFormat)
        self.pdf: PdfDocument | None = None
        self.docs: list[DocTab] = []        # pestañas de documentos, en orden
        self._cur = -1
        self.sign_warned = False
        self.search_results = []
        self.search_pos = -1
        self._scanned = False
        self.setWindowTitle("NovoPDF")
        self.setWindowIcon(QIcon(icons.app_icon_pixmap(256)))
        self.resize(1280, 860)
        self.setAcceptDrops(True)
        self._sign_job = None
        self._build()
        self._load_mark_colors()
        try:
            from ..core import fileassoc
            fileassoc.refresh_if_moved()
        except Exception:
            pass
        self._update_state()
        self._refresh_default_offer()
        geo = self.settings.value("window/geometry")
        if geo is not None:
            try:
                self.restoreGeometry(geo)
            except Exception:
                pass

    # ================================================================== interfaz
    def _build(self):
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setCentralWidget(central)

        # --- cabecera con pestañas
        header = QWidget()
        header.setObjectName("Header")
        header.setAttribute(Qt.WA_StyledBackground, True)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(14, 8, 14, 8)
        hl.setSpacing(6)
        logo = QLabel()
        pm = icons.app_icon_pixmap(56)
        pm.setDevicePixelRatio(2)
        logo.setPixmap(pm)
        hl.addWidget(logo)
        title = QLabel("NovoPDF")
        title.setObjectName("AppTitle")
        hl.addWidget(title)
        hl.addSpacing(22)
        self.tab_group = QButtonGroup(self)
        self.tab_group.setExclusive(True)
        self.tabs = []
        for k, (label, ic) in enumerate([("Inicio", "home"), ("Páginas", "pages"), ("Editar", "text_edit"),
                                          ("Formulario", "form"), ("Firmar", "sign"), ("Reconocer texto", "scan")]):
            b = QPushButton(icons.icon(ic, color=theme.MUTED, active=theme.ACCENT), " " + label)
            b.setObjectName("TabButton")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setIconSize(QSize(18, 18))
            self.tab_group.addButton(b, k)
            hl.addWidget(b)
            self.tabs.append(b)
        self.tab_group.idClicked.connect(self._tab_changed)
        hl.addStretch(1)
        self.doc_label = QLabel("")
        self.doc_label.setObjectName("DocTitle")
        hl.addWidget(self.doc_label)
        help_btn = QToolButton()
        help_btn.setIcon(icons.icon("help"))
        help_btn.setIconSize(QSize(22, 22))
        help_btn.setToolTip("Ayuda rápida y Acerca de NovoPDF")
        help_btn.setAutoRaise(True)
        help_btn.clicked.connect(self.show_help)
        hl.addWidget(help_btn)
        root.addWidget(header)

        # --- cinta de botones
        self.ribbon = QStackedWidget()
        self.ribbon.setObjectName("Ribbon")
        self.ribbon.setAttribute(Qt.WA_StyledBackground, True)
        self.ribbon.setFixedHeight(82)
        root.addWidget(self.ribbon)
        self._build_ribbons()

        # --- barra de ayuda contextual
        self.hint = QWidget()
        self.hint.setObjectName("HintBar")
        self.hint.setAttribute(Qt.WA_StyledBackground, True)
        hb = QHBoxLayout(self.hint)
        hb.setContentsMargins(16, 7, 10, 7)
        self.hint_icon = QLabel()
        hb.addWidget(self.hint_icon)
        self.hint_text = QLabel()
        self.hint_text.setObjectName("HintText")
        self.hint_text.setWordWrap(True)
        hb.addWidget(self.hint_text, 1)
        self.hint_buttons = QHBoxLayout()
        self.hint_buttons.setSpacing(6)
        hb.addLayout(self.hint_buttons)
        root.addWidget(self.hint)

        # --- pestañas de los documentos abiertos
        self.doc_bar = QWidget()
        self.doc_bar.setObjectName("DocTabs")
        self.doc_bar.setAttribute(Qt.WA_StyledBackground, True)
        dl = QHBoxLayout(self.doc_bar)
        dl.setContentsMargins(10, 6, 10, 0)
        dl.setSpacing(4)
        from .doctabs import DocTabBar
        self.doc_tabs = DocTabBar(self)
        self.doc_tabs.setObjectName("DocTabBar")
        self.doc_tabs.detachRequested.connect(self._detach_dropped)
        self.doc_tabs.menuRequested.connect(self._tab_menu)
        self.doc_tabs.setTabsClosable(True)
        self.doc_tabs.setMovable(True)
        self.doc_tabs.setExpanding(False)
        self.doc_tabs.setDrawBase(False)
        self.doc_tabs.setElideMode(Qt.ElideMiddle)
        self.doc_tabs.setUsesScrollButtons(True)
        self.doc_tabs.currentChanged.connect(self._switch_tab)
        self.doc_tabs.tabCloseRequested.connect(lambda k: self._close_tab(k))
        self.doc_tabs.tabMoved.connect(self._tab_moved)
        dl.addWidget(self.doc_tabs, 0, Qt.AlignBottom)
        new_tab = QToolButton()
        new_tab.setObjectName("NewTab")
        new_tab.setIcon(icons.icon("open"))
        new_tab.setIconSize(QSize(18, 18))
        new_tab.setToolTip(theme.keys("Abrir otro documento en una pestaña nueva (Ctrl+O)"))
        new_tab.setCursor(Qt.PointingHandCursor)
        new_tab.clicked.connect(lambda: self.open_file())
        dl.addWidget(new_tab, 0, Qt.AlignVCenter)
        dl.addStretch(1)
        self.doc_bar.setVisible(False)
        root.addWidget(self.doc_bar)

        # --- cuerpo
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)
        self.welcome = Welcome()
        self.welcome.actionRequested.connect(self._welcome_action)
        self.welcome.openRecent.connect(self.open_file)
        self.stack.addWidget(self.welcome)
        work = QWidget()
        wl = QHBoxLayout(work)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.setSpacing(0)
        self.thumbs = ThumbList()
        self.thumbs.pageClicked.connect(lambda i: self.viewer.go_to(i))
        self.thumbs.reordered.connect(self._reorder)
        self.thumbs.menuAction.connect(self._thumb_menu)
        self.thumbs.itemSelectionChanged.connect(self._update_state)
        wl.addWidget(self.thumbs)
        self.viewer = Viewer()
        self.viewer.pageChanged.connect(self._page_changed)
        self.viewer.zoomChanged.connect(lambda z: self.zoom_label.setText(f"{round(z * 100)} %"))
        self.viewer.action.connect(self._viewer_action)
        self.viewer.imageSelected.connect(lambda on: self._refresh_hint())
        self.viewer.fieldSelected.connect(lambda f: self._refresh_hint())
        self.viewer.show_fields = self.settings.value("form/highlight", True, type=bool)
        self._form_state = ("none", 0, [])     # (tipo, nº de campos, obligatorios sin rellenar)
        wl.addWidget(self.viewer, 1)
        self.stack.addWidget(work)

        # --- barra de estado
        sb = self.statusBar()
        sb.setSizeGripEnabled(False)
        self.page_spin = PageBox()
        self.page_spin.editingFinished.connect(lambda: self.viewer.go_to(self.page_spin.value() - 1))
        self.page_total = QLabel("")
        pw = QWidget()
        pl = QHBoxLayout(pw)
        pl.setContentsMargins(6, 0, 0, 0)
        pl.setSpacing(4)
        pl.addWidget(QLabel("Página"))
        pl.addWidget(self.page_spin)
        pl.addWidget(self.page_total)
        sb.addWidget(pw)
        self.lock_label = QLabel("")
        sb.addWidget(self.lock_label)
        self.msg_label = QLabel("")
        self.msg_label.setStyleSheet(f"color: {theme.ACCENT}; font-weight: 600;")
        sb.addWidget(self.msg_label, 1)
        self._msg_timer = QTimer(self)
        self._msg_timer.setSingleShot(True)
        self._msg_timer.timeout.connect(lambda: self.msg_label.setText(""))
        zw = QWidget()
        zl = QHBoxLayout(zw)
        zl.setContentsMargins(0, 0, 6, 0)
        zl.setSpacing(2)
        for ic, tip, fn in (("zoom_out", "Alejar (Ctrl -)", lambda: self.viewer.zoom_out()),):
            b = QToolButton(); b.setObjectName("StatusButton"); b.setIcon(icons.icon(ic)); b.setToolTip(theme.keys(tip)); b.clicked.connect(fn); zl.addWidget(b)
        self.zoom_label = QLabel("100 %")
        self.zoom_label.setFixedWidth(52)
        self.zoom_label.setAlignment(Qt.AlignCenter)
        zl.addWidget(self.zoom_label)
        for ic, tip, fn in (("zoom_in", "Acercar (Ctrl +)", lambda: self.viewer.zoom_in()),
                            ("fit", "Ajustar al ancho (Ctrl 0)", lambda: self.viewer.fit_width()),
                            ("blank", "Página completa", lambda: self.viewer.fit_page())):
            b = QToolButton(); b.setObjectName("StatusButton"); b.setIcon(icons.icon(ic)); b.setToolTip(theme.keys(tip)); b.clicked.connect(fn); zl.addWidget(b)
        sb.addPermanentWidget(zw)
        self.status_widgets = [pw, zw]

        # --- atajos
        for seq, fn in ((QKeySequence.Open, self.open_file), (QKeySequence.Save, self.save),
                        (QKeySequence("Ctrl+Shift+S"), self.save_as), (QKeySequence.Undo, self.undo),
                        (QKeySequence("Ctrl+Y"), self.redo), (QKeySequence("Ctrl+Shift+Z"), self.redo),
                        (QKeySequence.Find, self._focus_search), (QKeySequence(Qt.Key_F3), self.search_next),
                        (QKeySequence("Ctrl+W"), self.close_document),
                        (QKeySequence("Ctrl+Tab"), lambda: self._cycle_tab(1)),
                        (QKeySequence("Ctrl+Shift+Tab"), lambda: self._cycle_tab(-1)),
                        (QKeySequence("Ctrl+PgDown"), lambda: self._cycle_tab(1)),
                        (QKeySequence("Ctrl+PgUp"), lambda: self._cycle_tab(-1)),
                        (QKeySequence.Print, lambda: self.print_document()),
                        (QKeySequence("Ctrl++"), lambda: self.viewer.zoom_in()),
                        (QKeySequence("Ctrl+="), lambda: self.viewer.zoom_in()),
                        (QKeySequence("Ctrl+-"), lambda: self.viewer.zoom_out()),
                        (QKeySequence("Ctrl+0"), lambda: self.viewer.fit_width())):
            QShortcut(seq, self, fn)
        self.tabs[0].setChecked(True)
        self._tab_changed(0)

    def notify(self, text, ms=5000):
        self.msg_label.setText(theme.keys(text))
        self._msg_timer.start(ms)

    def _group(self, lay: QHBoxLayout, buttons, sep=True):
        for b in buttons:
            lay.addWidget(b)
        if sep:
            f = QFrame()
            f.setObjectName("RibbonSep")
            f.setFixedWidth(1)
            lay.addWidget(f)

    def _ribbon_page(self):
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(12, 6, 12, 6)
        lay.setSpacing(2)
        self.ribbon.addWidget(w)
        return lay

    def _build_ribbons(self):
        from PySide6.QtWidgets import QMenu
        B = RibbonButton
        # Inicio
        lay = self._ribbon_page()
        self.b_open = B("Abrir", "open", "Abrir un PDF (Ctrl+O)")
        self.b_open.clicked.connect(lambda: self.open_file())
        self.b_new = B("Nuevo", "file_plus", "Crear un PDF nuevo")
        self.b_new.clicked.connect(self._new_menu)
        self.b_save = B("Guardar", "save", "Guardar (Ctrl+S)")
        self.b_save.clicked.connect(self.save)
        self.b_saveas = B("Guardar\ncomo", "save_as", "Guardar con otro nombre (Ctrl+Mayús+S)")
        self.b_saveas.clicked.connect(self.save_as)
        self.b_print = B("Imprimir", "printer", "Imprimir el documento (Ctrl+P)")
        self.b_print.clicked.connect(lambda: self.print_document())
        self.b_export = B("Exportar", "export", "Exportar a Word, a Excel o como imágenes")
        self.b_export.setPopupMode(QToolButton.InstantPopup)
        em = QMenu(self.b_export)
        em.addAction(icons.icon("word_doc"), "Documento de Word (.docx)…", lambda: self.export_office("docx"))
        em.addAction(icons.icon("sheet_doc"), "Hoja de cálculo de Excel (.xlsx)…", lambda: self.export_office("xlsx"))
        em.addSeparator()
        em.addAction(icons.icon("export_img"), "Imágenes (PNG, JPEG, TIFF, SVG…)…", self.export_images)
        self.b_export.setMenu(em)
        self.b_scan = B("Escanear", "scanner", "Escanear papel y crear un PDF en un solo paso")
        self.b_scan.clicked.connect(lambda: self.scan_document(False))
        self._group(lay, [self.b_open, self.b_new, self.b_scan, self.b_save, self.b_saveas, self.b_print, self.b_export])
        self.b_protect = B("Contraseña", "lock", "Proteger el documento con contraseña")
        self.b_protect.clicked.connect(self.protect)
        self._group(lay, [self.b_protect])
        self.b_undo = B("Deshacer", "undo", "Deshacer (Ctrl+Z)")
        self.b_undo.clicked.connect(self.undo)
        self.b_redo = B("Rehacer", "redo", "Rehacer (Ctrl+Y)")
        self.b_redo.clicked.connect(self.redo)
        self._group(lay, [self.b_undo, self.b_redo])
        sw = QWidget()
        sl = QVBoxLayout(sw)
        sl.setContentsMargins(8, 4, 8, 4)
        sl.setSpacing(4)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar en el documento…")
        self.search.setClearButtonEnabled(True)
        self.search.addAction(icons.icon("search"), QLineEdit.LeadingPosition)
        self.search.setFixedWidth(260)
        self.search.returnPressed.connect(self.search_next)
        self.search.textChanged.connect(lambda _: self._clear_search())
        sl.addWidget(self.search)
        self.search_info = QLabel("")
        self.search_info.setObjectName("GroupLabel")
        sl.addWidget(self.search_info)
        lay.addWidget(sw)
        lay.addStretch(1)
        self.b_close = B("Cerrar", "close", "Cerrar el documento (Ctrl+W)")
        self.b_close.clicked.connect(self.close_document)
        lay.addWidget(self.b_close)

        # Páginas
        lay = self._ribbon_page()
        self.b_blank = B("Página en\nblanco", "blank", "Insertar una página en blanco después de la actual")
        self.b_blank.clicked.connect(lambda: self.insert_blank())
        self.b_insert = B("Insertar\narchivo", "file_in", "Insertar páginas de otro PDF o imágenes")
        self.b_insert.clicked.connect(lambda: self.insert_file())
        self.b_scan_add = B("Escanear\npáginas", "scanner", "Escanear páginas y añadirlas después de la página actual")
        self.b_scan_add.clicked.connect(lambda: self.scan_document(True))
        self._group(lay, [self.b_blank, self.b_insert, self.b_scan_add])
        self.b_extract = B("Extraer", "file_out", "Guardar las páginas seleccionadas como un PDF nuevo")
        self.b_extract.clicked.connect(self.extract_pages)
        self.b_dup = B("Duplicar", "copy", "Duplicar las páginas seleccionadas")
        self.b_dup.clicked.connect(self.duplicate_pages)
        self.b_delete = B("Eliminar", "trash", "Eliminar las páginas seleccionadas")
        self.b_delete.clicked.connect(self.delete_pages)
        self._group(lay, [self.b_extract, self.b_dup, self.b_delete])
        self.b_rotl = B("Girar\nizquierda", "rot_left")
        self.b_rotl.clicked.connect(lambda: self.rotate_pages(-90))
        self.b_rotr = B("Girar\nderecha", "rot_right")
        self.b_rotr.clicked.connect(lambda: self.rotate_pages(90))
        self._group(lay, [self.b_rotl, self.b_rotr])
        self.b_up = B("Mover\narriba", "up", "Mover las páginas seleccionadas una posición antes")
        self.b_up.clicked.connect(lambda: self.move_pages(-1))
        self.b_down = B("Mover\nabajo", "down", "Mover las páginas seleccionadas una posición después")
        self.b_down.clicked.connect(lambda: self.move_pages(1))
        self._group(lay, [self.b_up, self.b_down], sep=False)
        lay.addStretch(1)

        # Editar (herramientas)
        lay = self._ribbon_page()
        self.tool_group = QButtonGroup(self)
        self.tool_group.setExclusive(True)
        self.tool_buttons = {}

        def tool(text, ic, t, tip):
            b = B(text, ic, tip, checkable=True)
            self.tool_group.addButton(b)
            self.tool_buttons[t] = b
            b.clicked.connect(lambda: self.set_tool(t))
            return b
        self._group(lay, [tool("Seleccionar", "cursor", T_SELECT, "Seleccionar y copiar texto")])
        self._group(lay, [tool("Editar\ntexto", "text_edit", T_EDIT_TEXT, "Modificar un párrafo existente"),
                          tool("Añadir\ntexto", "text_add", T_ADD_TEXT, "Escribir texto nuevo en la página")])
        self._group(lay, [tool("Imágenes", "image", T_IMAGES, "Mover, cambiar tamaño, reemplazar o eliminar imágenes"),
                          tool("Añadir\nimagen", "image_add", T_ADD_IMAGE, "Colocar una imagen en la página")])
        self._group(lay, [tool("Borrar\nzona", "eraser", T_ERASE, "Eliminar todo lo que hay en una zona")])
        self.b_color = QToolButton()
        self.b_color.setObjectName("RibbonButton")
        self.b_color.setText("Color")
        self.b_color.setIconSize(QSize(24, 24))
        self.b_color.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.b_color.setPopupMode(QToolButton.InstantPopup)
        self.b_color.setAutoRaise(True)
        self.b_color.setCursor(Qt.PointingHandCursor)
        self.b_color.setToolTip("Color de la marca")
        self._group(lay, [tool("Resaltar", "highlighter", T_HIGHLIGHT, "Resaltar texto (como un rotulador)"),
                          tool("Subrayar", "underline", T_UNDERLINE, "Subrayar texto"),
                          tool("Tachar", "strike", T_STRIKE, "Tachar texto"),
                          self.b_color,
                          tool("Quitar\nmarca", "unmark", T_UNMARK, "Quitar un resaltado, subrayado o tachado")], sep=False)
        lay.addStretch(1)

        # Formulario
        lay = self._ribbon_page()
        self.b_fields_on = B("Resaltar\ncampos", "fields_on", "Colorear los campos que se pueden rellenar", checkable=True)
        self.b_fields_on.setChecked(self.settings.value("form/highlight", True, type=bool))
        self.b_fields_on.toggled.connect(self.toggle_field_highlight)
        self.b_form_reset = B("Vaciar\nformulario", "form_reset", "Borrar lo escrito en todos los campos")
        self.b_form_reset.clicked.connect(self.form_reset)
        self.b_form_data = B("Exportar\ndatos", "sheet_doc", "Guardar los datos del formulario en una hoja de Excel")
        self.b_form_data.setPopupMode(QToolButton.InstantPopup)
        dm = QMenu(self.b_form_data)
        dm.addAction(icons.icon("sheet_doc"), "Datos de este formulario (Excel)…", lambda: self.export_form_data(False))
        dm.addAction(icons.icon("merge"), "Datos de varios formularios rellenados (Excel)…", lambda: self.export_form_data(True))
        self.b_form_data.setMenu(dm)
        self._group(lay, [self.b_fields_on, self.b_form_reset, self.b_form_data])
        self.b_detect = B("Detectar\ncampos", "wand", "Crear automáticamente los campos de un impreso sin formulario "
                          "(rayas, recuadros, tablas y casillas)")
        self.b_detect.clicked.connect(lambda: self.form_detect())
        self._group(lay, [self.b_detect,
                          tool("Editar\ncampos", "f_edit", T_FORM_EDIT, "Seleccionar, mover, cambiar el tamaño, "
                               "cambiar las propiedades o eliminar campos")])
        self._group(lay, [tool("Texto", "f_text", T_F_TEXT, "Añadir un campo de texto"),
                          tool("Casilla", "f_check", T_F_CHECK, "Añadir una casilla de verificación"),
                          tool("Opción", "f_radio", T_F_RADIO, "Añadir un botón de opción (elegir una entre varias)"),
                          tool("Desplegable", "f_combo", T_F_COMBO, "Añadir una lista desplegable"),
                          tool("Lista", "f_list", T_F_LIST, "Añadir un cuadro de lista"),
                          tool("Firma", "f_sign", T_F_SIGN, "Añadir un campo para firmar digitalmente")])
        self.b_flatten = B("Aplanar", "flatten", "Convertir los campos en texto fijo de la página (ya no se podrán cambiar)")
        self.b_flatten.clicked.connect(self.form_flatten)
        self._group(lay, [self.b_flatten], sep=False)
        lay.addStretch(1)

        # Firmar
        lay = self._ribbon_page()
        self.b_sign = tool("Firmar", "sign", T_SIGN, "Firmar digitalmente con un sello visible")
        self.b_sign_inv = B("Firma\ninvisible", "pen", "Firmar digitalmente sin sello visible")
        self.b_sign_inv.clicked.connect(lambda: self.sign(None, None))
        self._group(lay, [self.b_sign, self.b_sign_inv])
        self.b_verify = B("Ver\nfirmas", "shield", "Comprobar las firmas del documento")
        self.b_verify.clicked.connect(self.verify)
        self._group(lay, [self.b_verify], sep=False)
        lay.addStretch(1)

        # OCR
        lay = self._ribbon_page()
        self.b_ocr = B("Reconocer\ntexto", "scan", "Reconocer el texto de páginas escaneadas (OCR)")
        self.b_ocr.clicked.connect(self.run_ocr)
        self._group(lay, [self.b_ocr], sep=False)
        expl = QLabel("Convierte documentos escaneados (solo imágenes) en PDF con texto que se puede buscar, "
                      "seleccionar y copiar.\nFunciona sin conexión a Internet. Idiomas: español e inglés.")
        expl.setObjectName("Muted")
        lay.addSpacing(10)
        lay.addWidget(expl)
        lay.addStretch(1)

        self.doc_buttons = [self.b_color, self.b_scan_add, self.b_save, self.b_saveas, self.b_print, self.b_export, self.b_protect, self.b_close, self.b_blank,
                            self.b_insert, self.b_extract, self.b_dup, self.b_delete, self.b_rotl,
                            self.b_rotr, self.b_up, self.b_down, self.b_sign, self.b_sign_inv,
                            self.b_verify, self.b_ocr, self.search, self.b_fields_on, self.b_form_reset,
                            self.b_form_data, self.b_detect, self.b_flatten] + list(self.tool_buttons.values())

    # ================================================================== estado
    def _tab_changed(self, k):
        self.ribbon.setCurrentIndex(k)
        if self.viewer.tool != T_SELECT and self.viewer.tool not in TAB_TOOLS.get(k, ()):
            self.set_tool(T_SELECT)
        self._refresh_hint()

    def set_tool(self, t):
        if t != T_SELECT and not self.pdf:
            return
        if t in (T_EDIT_TEXT, T_ADD_TEXT, T_IMAGES, T_ADD_IMAGE, T_ERASE) + FORM_TOOLS and not self._can_edit(ask=True):
            t = T_SELECT
        # Con texto ya seleccionado, Resaltar/Subrayar/Tachar se aplican directamente a él
        if t in MARK_TOOLS and self.viewer.tool == T_SELECT:
            i, words = self.viewer.selected_words()
            if words:
                self._viewer_action("mark", i, (t, words))
        self.viewer.set_tool(t)
        b = self.tool_buttons.get(t)
        if b:
            b.setChecked(True)
        self._update_color_button()
        self._refresh_hint()

    # ================================================================== marcas de texto
    def _load_mark_colors(self):
        from ..core import markup
        for t in MARK_TOOLS:
            v = self.settings.value(f"mark/{t}", None)
            try:
                col = tuple(float(x) for x in (v if isinstance(v, (list, tuple)) else str(v).split(",")))
                assert len(col) == 3
            except Exception:
                col = markup.default_color(t)
            self.viewer.mark_colors[t] = col
        self._update_color_button()

    def _update_color_button(self):
        from PySide6.QtWidgets import QMenu
        from ..core import markup
        t = self.viewer.tool if self.viewer.tool in MARK_TOOLS else T_HIGHLIGHT
        cur = self.viewer.mark_colors.get(t, markup.default_color(t))
        self.b_color.setIcon(self.viewer._swatch_icon(cur))
        m = QMenu(self.b_color)
        names = {T_HIGHLIGHT: "resaltar", T_UNDERLINE: "subrayar", T_STRIKE: "tachar"}
        m.addSection(f"Color para {names[t]}")
        for name, col in markup.colors_for(t):
            a = m.addAction(self.viewer._swatch_icon(col), name)
            a.setCheckable(True)
            a.setChecked(all(abs(x - y) < 0.01 for x, y in zip(col, cur)))
            a.triggered.connect(lambda _=False, t=t, col=col: self._set_mark_color(t, col))
        self.b_color.setMenu(m)

    def _set_mark_color(self, t, col):
        self.viewer.mark_colors[t] = tuple(col)
        self.settings.setValue(f"mark/{t}", ",".join(f"{x:.3f}" for x in col))
        self._update_color_button()
        if self.viewer.tool != t and self.pdf:
            self.set_tool(t)

    def _set_hint(self, kind, icon_name, text, buttons=()):
        while self.hint_buttons.count():
            it = self.hint_buttons.takeAt(0)
            if it.widget():
                it.widget().hide()          # si no, se ve encima del nuevo hasta que se borra
                it.widget().deleteLater()
        if not text:
            self.hint.hide()
            return
        self.hint.setProperty("kind", kind)
        self.hint.style().unpolish(self.hint)
        self.hint.style().polish(self.hint)
        col = {"info": theme.ACCENT, "success": theme.SUCCESS, "warning": theme.WARNING}.get(kind, theme.ACCENT)
        self.hint_icon.setPixmap(icons.pixmap(icon_name, 20, col))
        self.hint_text.setText(theme.keys(text))
        for label, fn, primary in buttons:
            b = QPushButton(label)
            b.setObjectName("Primary" if primary else "Small")
            if primary:
                b.setStyleSheet("padding: 4px 12px;")
            b.clicked.connect(fn)
            self.hint_buttons.addWidget(b)
        self.hint.show()

    def _refresh_hint(self):
        if not self.pdf:
            self._set_hint("", "", "")
            return
        t = self.viewer.tool
        if t != T_SELECT:
            kind, ic, text = HINTS[t]
            btns = []
            if t == T_IMAGES and self.viewer.sel_image:
                i, item, _ = self.viewer.sel_image
                btns = [("Reemplazar…", lambda: self._viewer_action("image_replace", i, item), False),
                        ("Eliminar", lambda: self._viewer_action("image_delete", i, item), False)]
                text = "Imagen seleccionada. Arrástrala para moverla o usa la esquina para cambiar su tamaño (Mayús: sin mantener proporción)."
            if t in FORM_TOOLS and self.viewer.sel_field:
                i, f, _ = self.viewer.sel_field
                x = f.xref
                what = f"opción «{f.on_state}» del grupo «{f.name}»" if f.kind == "radio" else f"«{f.name}»"
                text = (f"{f.kind_name} {what} seleccionado. Arrástralo para moverlo, usa la esquina para cambiar "
                        "su tamaño o pulsa Supr para eliminarlo.")
                btns = [("Propiedades…", lambda: self._viewer_action("form_props", i, x), False),
                        ("Duplicar", lambda: self._viewer_action("form_dup", i, x), False),
                        ("Eliminar", lambda: self._viewer_action("form_delete", i, x), False)]
            if t in FORM_CREATE:
                btns.append(("Editar campos", lambda: self.set_tool(T_FORM_EDIT), False))
            btns.append(("Terminar", lambda: self.set_tool(T_SELECT), False))
            self._set_hint(kind, ic, text, btns)
            return
        tab = self.tab_group.checkedId()
        if self.pdf.restricted:
            self._set_hint("warning", "lock", "El autor ha limitado la edición de este documento. Para modificarlo necesitas la contraseña de permisos.",
                           [("Introducir contraseña…", self._unlock_restrictions, False)])
        elif self.pdf.has_signatures() and not self.pdf.modified:
            self._set_hint("success", "shield", "Este documento está firmado digitalmente. Si lo modificas, las firmas dejarán de ser válidas.",
                           [("Ver firmas", self.verify, False)])
        elif self._form_state[0] == "xfa_only":
            self._set_hint("warning", "form", "Este formulario es de tipo XFA dinámico (Adobe LiveCycle): NovoPDF no puede "
                           "mostrar ni rellenar sus campos. Ábrelo con Adobe Acrobat Reader.")
        elif self._scanned and tab != TAB_OCR and not self._form_state[1]:
            self._set_hint("info", "scan", "Este documento parece escaneado: su texto no se puede buscar ni copiar.",
                           [("Reconocer texto (OCR)", self.run_ocr, True)])
        elif self._form_state[1] and tab in (0, 1, TAB_FORM):
            missing = self._form_state[2]
            text = ("Este documento es un formulario: haz clic en un campo para rellenarlo; Tab pasa al siguiente.")
            btns = [("Rellenar", self._fill_first, True)]
            if missing:
                text += (f" Falta{'n' if len(missing) > 1 else ''} {len(missing)} campo{'s' if len(missing) > 1 else ''} "
                         f"obligatorio{'s' if len(missing) > 1 else ''} (marcado{'s' if len(missing) > 1 else ''} en rojo).")
                btns = [("Ir al siguiente obligatorio", self._goto_missing, True)]
            if not self.viewer.form_fill:
                text = "El autor ha limitado los cambios: para rellenar este formulario necesitas la contraseña de permisos."
                btns = [("Introducir contraseña…", self._unlock_restrictions, False)]
            self._set_hint("info", "form", text, btns)
        elif tab == TAB_FORM:
            self._set_hint("info", "form", "Este documento no tiene campos para rellenar. Pulsa «Detectar campos» para "
                           "crearlos automáticamente, o elige un tipo de campo y dibújalo en la página.",
                           [("Detectar campos", lambda: self.form_detect(), True)])
        elif tab == 1:
            self._set_hint("info", "pages", "Selecciona páginas en el panel de la izquierda (Ctrl o Mayús para varias). Arrástralas para cambiar el orden.")
        elif tab == 2:
            self._set_hint("info", "text_edit", "Elige una herramienta: editar un párrafo, añadir texto o imágenes, borrar una zona, o resaltar, subrayar y tachar texto.")
        elif tab == TAB_SIGN:
            self._set_hint("success", "sign", "Pulsa «Firmar» y dibuja un recuadro en la página donde quieras el sello de firma.")
        else:
            self._set_hint("", "", "")

    def _update_state(self):
        has = self.pdf is not None
        self.stack.setCurrentIndex(1 if has else 0)
        for b in self.doc_buttons:
            b.setEnabled(has)
        for w in self.status_widgets:
            w.setVisible(has)
        if not has:
            self.b_undo.setEnabled(False)
            self.b_redo.setEnabled(False)
            self.welcome.set_recent(self._recent())
            self.doc_label.setText("")
            self.setWindowTitle("NovoPDF")
            self.lock_label.setText("")
            self._refresh_hint()
            return
        sel = self.thumbs.selected_pages()
        self.b_undo.setEnabled(self.pdf.can_undo())
        self.b_redo.setEnabled(self.pdf.can_redo())
        mark = " •" if self.pdf.modified else ""
        self.doc_label.setText(self.pdf.name + mark)
        if 0 <= self._cur < self.doc_tabs.count():
            self.doc_tabs.setTabText(self._cur, self.pdf.name + mark)
            self.doc_tabs.setTabToolTip(self._cur, self.pdf.path or self.pdf.name)
        self.setWindowTitle(f"{self.pdf.name}{mark} — NovoPDF")
        n = self.pdf.page_count
        self.page_spin.setMaximum(max(1, n))
        self.page_total.setText(f"de {n}")
        lock = []
        if self.pdf.protection.enabled:
            lock.append("🔒 Protegido con contraseña")
        if self.pdf.has_signatures():
            lock.append("✔ Firmado")
        self.lock_label.setText("   ".join(lock))
        self.b_delete.setEnabled(n > 1)
        for b in (self.b_up, self.b_down):
            b.setEnabled(n > 1)

    def _recent(self):
        v = self.settings.value("recent", [])
        if isinstance(v, str):
            v = [v]
        return list(v or [])

    def _add_recent(self, path):
        r = [p for p in self._recent() if os.path.normcase(p) != os.path.normcase(path)]
        r.insert(0, path)
        self.settings.setValue("recent", r[:12])

    # ================================================================== documento
    def _confirm_close(self) -> bool:
        if not self.pdf or not self.pdf.modified:
            return True
        r = dialogs.ask_save_changes(self, self.pdf.name)
        if r == "cancel":
            return False
        if r == "save":
            return self.save()
        return True

    # ------------------------------------------------------------------ pestañas
    def _save_view(self):
        """Guarda cómo se está viendo el documento actual (página, zoom) en su pestaña."""
        if 0 <= self._cur < len(self.docs) and self.docs[self._cur].pdf is self.pdf and self.pdf:
            d = self.docs[self._cur]
            d.page = self.viewer.current_page()
            d.zoom = self.viewer.zoom
            d.fit = self.viewer.fit_mode
            d.scanned = self._scanned
            d.sign_warned = self.sign_warned

    def _show_tab(self, k: int):
        """Muestra el documento de la pestaña k (o la pantalla de inicio si no hay ninguno)."""
        d = self.docs[k] if 0 <= k < len(self.docs) else None
        self._cur = k if d else -1
        pdf = d.pdf if d else None
        self.pdf = pdf
        self.sign_warned = d.sign_warned if d else False
        self._clear_search()
        self._scanned = d.scanned if d else False
        self.viewer.form_fill = bool(pdf) and (not pdf.restricted or pdf.form_allowed)
        self.viewer.set_document(pdf)
        self.thumbs.set_document(pdf)
        self.viewer.set_tool(T_SELECT)
        self.tool_buttons[T_SELECT].setChecked(True)
        self._update_form_state()
        self.page_spin.setValue((d.page + 1) if d else 1)
        self.viewer._last_page = -1
        self.doc_tabs.blockSignals(True)
        if d:
            self.doc_tabs.setCurrentIndex(k)
        self.doc_tabs.blockSignals(False)
        self.doc_bar.setVisible(bool(self.docs))
        if d and (d.page or d.fit != "width"):
            QTimer.singleShot(0, lambda: self._restore_view(d))
        self._update_state()
        self._refresh_hint()

    def _restore_view(self, d: DocTab):
        if self.pdf is not d.pdf:
            return
        if d.fit == "page":
            self.viewer.fit_page()
        elif d.fit != "width" and d.zoom:
            self.viewer.set_zoom(d.zoom)
        page = d.page

        def go():
            if self.pdf is d.pdf and self.viewer.current_page() != page:
                self.viewer.go_to(page)

        # en una ventana recién creada las páginas se recolocan varias veces al mostrarse
        # (ajuste al ancho): se vuelve a la página durante el primer medio segundo
        for ms in (0, 60, 150, 300, 500):
            QTimer.singleShot(ms, go)

    def _switch_tab(self, k: int):
        if k == self._cur or not (0 <= k < len(self.docs)):
            return
        self._commit_form()
        self._save_view()
        self._show_tab(k)

    def _cycle_tab(self, step: int):
        if len(self.docs) > 1:
            self._switch_tab((self._cur + step) % len(self.docs))

    def _tab_moved(self, frm: int, to: int):
        self.docs.insert(to, self.docs.pop(frm))
        self._cur = self.doc_tabs.currentIndex()

    def _tab_index_of_button(self, b) -> int:
        for k in range(self.doc_tabs.count()):
            if self.doc_tabs.tabButton(k, QTabBar.RightSide) is b:
                return k
        return -1

    def _tab_of(self, path: str) -> int:
        """Pestaña de esta ventana que ya tiene abierto ese archivo (o -1)."""
        from ..core import fileid
        for k, d in enumerate(self.docs):
            if fileid.same_file(d.src or d.pdf.path, path) or fileid.same_file(d.pdf.path, path):
                return k
        return -1

    def bring_to_front(self):
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()
        MainWindow.last_active = self

    def show_doc(self, k: int):
        """Muestra la pestaña k de esta ventana y pone la ventana delante."""
        self.bring_to_front()
        self._switch_tab(k)

    def _busy_path(self, path: str) -> bool:
        """Avisa si ese archivo está abierto en otra pestaña (no se puede sobrescribir)."""
        cur = self.docs[self._cur] if 0 <= self._cur < len(self.docs) else None
        w, k = MainWindow.find_open(path, exclude=cur)
        if w is None:
            return False
        dialogs.error(self, "Archivo abierto",
                      f"«{os.path.basename(path)}» está abierto en otra pestaña"
                      f"{'' if w is self else ' de otra ventana'} de NovoPDF.\n\n"
                      "Ciérralo antes o elige otro nombre.")
        return True

    # ------------------------------------------------------------------ ventanas
    def changeEvent(self, e):
        if e.type() == QEvent.ActivationChange and self.isActiveWindow():
            MainWindow.last_active = self
        super().changeEvent(e)

    def _new_window(self, at: QPoint | None = None) -> "MainWindow":
        w = MainWindow()
        w.resize(self.size())
        if at is not None:
            w.move(max(0, at.x() - 260), max(0, at.y() - 40))
        else:
            w.move(self.pos() + QPoint(40, 40))
        w.show()
        return w

    def _take_doc(self, d: DocTab) -> DocTab | None:
        """Quita la pestaña de esta ventana sin cerrar el documento (para llevarla a otra)."""
        if d not in self.docs:
            return None
        k = self.docs.index(d)
        if k == self._cur:
            self._save_view()
        was_current = k == self._cur
        self.docs.pop(k)
        self.doc_tabs.blockSignals(True)
        self.doc_tabs.removeTab(k)
        self.doc_tabs.blockSignals(False)
        if was_current:
            self._cur = -1
            self._show_tab(min(k, len(self.docs) - 1))
        else:
            if k < self._cur:
                self._cur -= 1
            self.doc_bar.setVisible(bool(self.docs))
        return d

    def _adopt(self, d: DocTab, index: int | None = None):
        """Recibe una pestaña de otra ventana (con su página y zoom)."""
        self._save_view()
        k = len(self.docs) if index is None else max(0, min(index, len(self.docs)))
        self.docs.insert(k, d)
        self._insert_tab_widget(k, d.pdf.name)
        if self._cur >= k:
            self._cur += 1
        self._show_tab(k)

    def move_doc_to(self, d: DocTab, other: "MainWindow", index: int | None = None):
        if other is self or d not in self.docs:
            return
        self._take_doc(d)
        other._adopt(d, index)
        other.bring_to_front()
        if not self.docs and len(MainWindow.windows) > 1:
            self.close()                 # ventana vacía: se cierra

    def detach_doc(self, d: DocTab, at: QPoint | None = None):
        """Lleva el documento a una ventana nueva (si no es el único de esta ventana)."""
        if d not in self.docs or len(self.docs) < 2:
            return None
        self._take_doc(d)
        w = self._new_window(at)
        w._adopt(d)
        w.bring_to_front()
        return w

    def _detach_dropped(self, d: DocTab, at: QPoint):
        self.detach_doc(d, at)

    def gather_windows(self):
        """Trae aquí las pestañas de todas las demás ventanas."""
        for w in [x for x in MainWindow.windows if x is not self]:
            for d in list(w.docs):
                w.move_doc_to(d, self)

    def _tab_menu(self, k: int, pos: QPoint):
        m = self._build_tab_menu(k)
        if m is not None:
            m.exec(pos)

    def _build_tab_menu(self, k: int):
        from PySide6.QtWidgets import QMenu
        if not (0 <= k < len(self.docs)):
            return None
        d = self.docs[k]
        m = QMenu(self)
        a = m.addAction(icons.icon("export"), "Abrir en una ventana nueva", lambda: self.detach_doc(d))
        a.setEnabled(len(self.docs) > 1)
        others = [w for w in MainWindow.windows if w is not self]
        if others:
            sub = m.addMenu("Mover a otra ventana")
            for w in others:
                names = ", ".join(x.pdf.name for x in w.docs[:3]) + ("…" if len(w.docs) > 3 else "")
                sub.addAction(names or "Ventana vacía", lambda w=w: self.move_doc_to(d, w))
            m.addAction("Traer aquí las pestañas de las otras ventanas", self.gather_windows)
        m.addSeparator()
        if d.pdf.path:
            m.addAction(icons.icon("folder"), "Mostrar en la carpeta", lambda: self._reveal(d.pdf.path))
        m.addAction(icons.icon("close"), "Cerrar", lambda: self._close_tab(self.docs.index(d)) if d in self.docs else None)
        c = m.addAction("Cerrar las demás pestañas", lambda: self._close_others(d))
        c.setEnabled(len(self.docs) > 1)
        return m

    def _close_others(self, keep: DocTab):
        for d in [x for x in self.docs if x is not keep]:
            if d in self.docs and not self._close_tab(self.docs.index(d)):
                break

    def _reveal(self, path: str):
        import subprocess
        try:
            if sys.platform.startswith("win"):
                subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", path])
            else:
                from PySide6.QtCore import QUrl
                from PySide6.QtGui import QDesktopServices
                QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))
        except Exception as e:  # noqa
            dialogs.error(self, "Mostrar en la carpeta", str(e))

    def _close_tab(self, k: int, ask: bool = True) -> bool:
        """Cierra la pestaña k (preguntando si hay cambios sin guardar)."""
        if not (0 <= k < len(self.docs)):
            return True
        if k == self._cur:
            self._commit_form()
        if ask and self.docs[k].pdf.modified:
            if k != self._cur:
                self._switch_tab(k)        # que se vea cuál es antes de preguntar
            if not self._confirm_close():
                return False
        was_current = k == self._cur
        d = self.docs.pop(k)
        try:
            d.pdf.doc.close()
        except Exception:
            pass
        self.doc_tabs.blockSignals(True)
        self.doc_tabs.removeTab(k)
        self.doc_tabs.blockSignals(False)
        if was_current:
            self._cur = -1
            self._show_tab(min(k, len(self.docs) - 1))
        else:
            if k < self._cur:
                self._cur -= 1
            self.doc_bar.setVisible(bool(self.docs))
        return True

    def _set_document(self, pdf: PdfDocument | None, src: str | None = None, fp=None):
        """Muestra un documento nuevo en su propia pestaña (None: cierra la actual)."""
        if pdf is None:
            self._close_tab(self._cur, ask=False)
            return
        self._save_view()
        self.docs.append(DocTab(pdf, scanned=pdf.looks_scanned(), src=src or pdf.path, fp=fp))
        k = len(self.docs) - 1
        self._insert_tab_widget(k, pdf.name)
        if self.tab_group.checkedId() in (2, TAB_SIGN):
            self.tabs[0].setChecked(True)
            self._tab_changed(0)
        self._show_tab(k)

    def _insert_tab_widget(self, k: int, name: str):
        self.doc_tabs.blockSignals(True)
        self.doc_tabs.insertTab(k, icons.icon("file"), name)
        close = QToolButton()
        close.setObjectName("TabClose")
        close.setIcon(icons.icon("close"))
        close.setIconSize(QSize(12, 12))
        close.setAutoRaise(True)
        close.setCursor(Qt.PointingHandCursor)
        close.setToolTip(theme.keys("Cerrar este documento (Ctrl+W)"))
        close.clicked.connect(lambda _=False, b=close: self._close_tab(self._tab_index_of_button(b)))
        self.doc_tabs.setTabButton(k, QTabBar.RightSide, close)
        self.doc_tabs.blockSignals(False)

    def _replace_document(self, pdf: PdfDocument):
        """Sustituye el documento de la pestaña actual (p. ej. por su versión firmada)."""
        if not (0 <= self._cur < len(self.docs)):
            self._set_document(pdf)
            return
        old = self.docs[self._cur].pdf
        try:
            old.doc.close()
        except Exception:
            pass
        from ..core import fileid
        self.docs[self._cur] = DocTab(pdf, scanned=pdf.looks_scanned(), src=pdf.path,
                                      fp=fileid.fingerprint(pdf.path))
        self.doc_tabs.setTabText(self._cur, pdf.name)
        self._show_tab(self._cur)

    def open_files(self, paths: list[str]):
        """Abre varios archivos, cada uno en su pestaña (los ya abiertos solo se muestran)."""
        for p in paths:
            self.open_file(p)

    def open_file(self, path: str | None = None):
        if not path:
            start = self.settings.value("last_dir", os.path.expanduser("~"))
            paths, _ = QFileDialog.getOpenFileNames(self, "Abrir documentos", start, OPEN_FILTER)
            if not paths:
                return
            if len(paths) > 1:
                self.open_files(paths)
                return
            path = paths[0]
        from ..core import fileid
        path = os.path.abspath(path)
        w, k = MainWindow.find_open(path)
        if w is not None:
            w.show_doc(k)
            w.notify(f"«{w.docs[k].pdf.name}» ya estaba abierto.", 4000)
            return
        fp = fileid.fingerprint(path)
        w, k = MainWindow.find_same_content(fp)
        if w is not None:
            other = w.docs[k]
            where = os.path.dirname(other.src or other.pdf.path or "") or "—"
            if dialogs.confirm(self, "Documento ya abierto",
                               f"«{os.path.basename(path)}» es idéntico a «{other.pdf.name}», que ya está "
                               f"abierto (carpeta: {where}).\n\n¿Quieres ir al documento que ya está abierto?",
                               "Ir al que está abierto", "Abrir también este"):
                w.show_doc(k)
                return
        self.settings.setValue("last_dir", os.path.dirname(path))
        pw, wrong = None, False
        while True:
            try:
                QApplication.setOverrideCursor(Qt.WaitCursor)
                is_pdf = path.lower().endswith(".pdf")
                if is_pdf:
                    pdf = PdfDocument.open(path, pw)
                else:
                    pdf = PdfDocument.from_images([path])
                    pdf.title = os.path.splitext(os.path.basename(path))[0] + ".pdf"
                break
            except PasswordRequired:
                QApplication.restoreOverrideCursor()
                pw = dialogs.ask_password(self, os.path.basename(path), wrong)
                if pw is None:
                    return
                wrong = True
            except Exception as e:
                QApplication.restoreOverrideCursor()
                dialogs.error(self, "No se pudo abrir", f"No se pudo abrir el archivo:\n{path}\n\n{e}")
                return
            finally:
                QApplication.restoreOverrideCursor()
        if pdf.path:
            self._add_recent(pdf.path)
        self._set_document(pdf, src=path, fp=fp)

    def _welcome_action(self, a):
        {"open": self.open_file, "new": self.new_blank, "images": self.new_from_images,
         "merge": self.merge_pdfs, "scan": lambda: self.scan_document(False),
         "default": self.make_default_app}[a]()

    def _new_menu(self):
        from PySide6.QtWidgets import QMenu
        m = QMenu(self)
        m.addAction(icons.icon("file_plus"), "PDF en blanco…", self.new_blank)
        m.addAction(icons.icon("images"), "PDF desde imágenes…", self.new_from_images)
        m.addAction(icons.icon("merge"), "Combinar varios PDF…", self.merge_pdfs)
        m.addAction(icons.icon("scanner"), "Escanear desde el escáner…", lambda: self.scan_document(False))
        m.exec(self.b_new.mapToGlobal(self.b_new.rect().bottomLeft()))

    def new_blank(self):
        d = dialogs.NewBlankDialog(self)
        if d.exec():
            n, w, h = d.values()
            self._set_document(PdfDocument.new_blank(n, w, h))

    def new_from_images(self):
        start = self.settings.value("last_dir", os.path.expanduser("~"))
        files, _ = QFileDialog.getOpenFileNames(self, "Elegir imágenes", start, IMG_FILTER)
        if not files:
            return
        d = dialogs.FileListDialog(self, "PDF desde imágenes", "Cada imagen será una página, en este orden.",
                                   "images", IMG_FILTER, "Crear PDF", files)
        if d.exec():
            try:
                QApplication.setOverrideCursor(Qt.WaitCursor)
                self._set_document(PdfDocument.from_images(d.files()))
            except Exception as e:
                dialogs.error(self, "Error", f"No se pudo crear el PDF:\n{e}")
            finally:
                QApplication.restoreOverrideCursor()

    def merge_pdfs(self):
        d = dialogs.FileListDialog(self, "Combinar varios PDF", "Los archivos se unirán en este orden en un único documento.",
                                   "merge", INSERT_FILTER, "Combinar")
        if not d.exec():
            return
        items = []
        for p in d.files():
            pw = None
            if p.lower().endswith(".pdf"):
                x = pymupdf.open(p)
                wrong = False
                while x.needs_pass and not x.authenticate(pw or ""):
                    pw = dialogs.ask_password(self, os.path.basename(p), wrong)
                    if pw is None:
                        return
                    wrong = True
                x.close()
            items.append((p, pw))
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            self._set_document(PdfDocument.merge(items))
        except Exception as e:
            dialogs.error(self, "Error", f"No se pudieron combinar los documentos:\n{e}")
        finally:
            QApplication.restoreOverrideCursor()

    def close_document(self):
        if self.pdf:
            self._close_tab(self._cur)

    def save(self) -> bool:
        if not self.pdf:
            return False
        self._commit_form()
        if not self.pdf.path:
            return self.save_as()
        return self._save_to(self.pdf.path)

    def save_as(self) -> bool:
        if not self.pdf:
            return False
        self._commit_form()
        start = self.pdf.path or os.path.join(self.settings.value("last_dir", os.path.expanduser("~")), self.pdf.name)
        path, _ = QFileDialog.getSaveFileName(self, "Guardar como", start, PDF_FILTER)
        if not path:
            return False
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        if self._busy_path(path):
            return False
        return self._save_to(path)

    def _save_to(self, path) -> bool:
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            self.pdf.save(path)
        except PermissionError:
            QApplication.restoreOverrideCursor()
            dialogs.error(self, "No se pudo guardar",
                          "No se puede escribir el archivo. Puede que esté abierto en otro programa o que no tengas permiso en esa carpeta.\n\nPrueba con «Guardar como».")
            return False
        except Exception as e:
            QApplication.restoreOverrideCursor()
            dialogs.error(self, "No se pudo guardar", str(e))
            return False
        QApplication.restoreOverrideCursor()
        if 0 <= self._cur < len(self.docs):
            from ..core import fileid
            d = self.docs[self._cur]
            d.src = path
            d.fp = fileid.fingerprint(path)
        self._add_recent(path)
        self.settings.setValue("last_dir", os.path.dirname(path))
        self._update_state()
        missing = self._form_state[2]
        if missing:
            self.notify(f"Documento guardado. Ojo: falta{'n' if len(missing) > 1 else ''} {len(missing)} campo"
                        f"{'s' if len(missing) > 1 else ''} obligatorio{'s' if len(missing) > 1 else ''} por rellenar.", 7000)
        else:
            self.notify("Documento guardado.", 4000)
        return True

    def protect(self):
        if not self.pdf:
            return
        self._commit_form()
        d = dialogs.ProtectDialog(self, self.pdf.protection)
        if d.exec() and d.result_prot is not None:
            self.pdf.protection = d.result_prot
            self.pdf.modified = True
            self._update_state()
            msg = ("La protección se ha quitado." if not d.result_prot.enabled else
                   "La protección se aplicará al guardar.")
            self.notify(msg + " Recuerda guardar el documento.", 6000)
            if dialogs.confirm(self, "Guardar ahora", msg + "\n¿Quieres guardar el documento ahora?", "Guardar", "Más tarde"):
                self.save()

    def _unlock_restrictions(self):
        pw = dialogs.ask_password(self, self.pdf.name)
        while pw is not None:
            try:
                data = self.pdf.source_bytes
                x = pymupdf.open(stream=data, filetype="pdf")
                ok = x.authenticate(pw) & 4
                x.close()
            except Exception:
                ok = False
            if ok:
                self.pdf.restricted = False
                self.pdf.print_allowed = True
                self.pdf.copy_allowed = True
                self.pdf.form_allowed = True
                self.viewer.form_fill = True
                self.pdf.protection.owner_pw = pw
                self._refresh_hint()
                self.notify("Edición desbloqueada.", 4000)
                return
            pw = dialogs.ask_password(self, self.pdf.name, wrong=True)

    def _can_edit(self, ask=False) -> bool:
        if not self.pdf:
            return False
        if self.pdf.restricted:
            if ask:
                dialogs.warn(self, "Edición limitada", "El autor ha limitado la edición de este documento. "
                                   "Introduce la contraseña de permisos para poder modificarlo.")
                self._unlock_restrictions()
            return not self.pdf.restricted
        if self.pdf.has_signatures() and not self.sign_warned:
            if not dialogs.confirm(self, "Documento firmado",
                                   "Este documento está firmado digitalmente.\nSi lo modificas, las firmas "
                                   "existentes dejarán de ser válidas.\n\n¿Quieres continuar?",
                                   "Modificar de todos modos", "Cancelar"):
                return False
            self.sign_warned = True
        return True

    def after_change(self, pages=None, structure=False, keep_selection=False):
        self._scanned = self._scanned and self.pdf.looks_scanned()
        self.viewer.refresh(pages, structure=structure)
        self._update_form_state()
        if structure:
            self.thumbs.rebuild()
        else:
            self.thumbs.refresh_pages(pages if pages is not None else range(self.pdf.page_count))
        self._clear_search()
        self._update_state()
        self._refresh_hint()

    def undo(self):
        ed = self.viewer.editor
        if ed.active:
            dirty = ed.dirty()
            ed.close(commit=False)
            if dirty:                    # deshacer lo que se estaba escribiendo
                return
        if self.pdf and self.pdf.undo():
            self.after_change(structure=True)

    def redo(self):
        self.viewer.editor.close(commit=False)
        if self.pdf and self.pdf.redo():
            self.after_change(structure=True)

    # ================================================================== páginas
    def _selected(self):
        sel = self.thumbs.selected_pages()
        return sel or [self.viewer.current_page()]

    def _page_changed(self, i):
        self.page_spin.blockSignals(True)
        self.page_spin.setValue(i + 1)
        self.page_spin.blockSignals(False)
        self.thumbs.select_page(i)

    def insert_blank(self, at=None):
        if not self._can_edit(True):
            return
        at = self.viewer.current_page() + 1 if at is None else at
        self.pdf.insert_blank(at)
        self.after_change(structure=True)
        QTimer.singleShot(50, lambda: self.viewer.go_to(at))

    def insert_file(self, at=None, path=None):
        if not self._can_edit(True):
            return
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Insertar páginas", self.settings.value("last_dir", ""), INSERT_FILTER)
            if not path:
                return
        if at is None:
            d = dialogs.InsertPositionDialog(self, os.path.basename(path), self.viewer.current_page(), self.pdf.page_count)
            if not d.exec():
                return
            at = d.position()
        pw, wrong = None, False
        while True:
            try:
                n = self.pdf.insert_file(at, path, pw)
                break
            except PasswordRequired:
                pw = dialogs.ask_password(self, os.path.basename(path), wrong)
                if pw is None:
                    return
                wrong = True
            except Exception as e:
                dialogs.error(self, "Error", f"No se pudo insertar el archivo:\n{e}")
                return
        self.after_change(structure=True)
        self.notify(f"Se han insertado {n} página(s).", 4000)
        QTimer.singleShot(50, lambda: self.viewer.go_to(at))

    def extract_pages(self):
        sel = self._selected()
        base = os.path.splitext(self.pdf.name)[0]
        rng = f"{sel[0] + 1}" if len(sel) == 1 else f"{sel[0] + 1}-{sel[-1] + 1}"
        start = os.path.join(os.path.dirname(self.pdf.path) if self.pdf.path else self.settings.value("last_dir", ""),
                             f"{base}_pag_{rng}.pdf")
        path, _ = QFileDialog.getSaveFileName(self, f"Guardar {len(sel)} página(s) extraída(s)", start, PDF_FILTER)
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        if self._busy_path(path):
            return
        try:
            self.pdf.extract_pages(sel, path)
        except Exception as e:
            dialogs.error(self, "Error", str(e))
            return
        self.notify(f"Se han guardado {len(sel)} página(s) en {os.path.basename(path)}.", 6000)
        if dialogs.confirm(self, "Páginas extraídas",
                           f"Se ha creado «{os.path.basename(path)}» con {len(sel)} página(s).\n\n"
                           "¿Quieres eliminarlas también de este documento?", "Eliminarlas", "No, mantenerlas"):
            self.delete_pages(sel, ask=False)

    def delete_pages(self, sel=None, ask=True):
        if not self._can_edit(True):
            return
        sel = sel or self._selected()
        if len(sel) >= self.pdf.page_count:
            dialogs.warn(self, "Eliminar páginas", "No se pueden eliminar todas las páginas del documento.")
            return
        if ask and len(sel) > 1 and not dialogs.confirm(self, "Eliminar páginas", f"¿Eliminar {len(sel)} páginas?", "Eliminar", "Cancelar"):
            return
        self.pdf.delete_pages(sel)
        self.thumbs.clearSelection()
        self.after_change(structure=True)
        self.notify(f"Se han eliminado {len(sel)} página(s). Puedes deshacerlo con Ctrl+Z.", 5000)

    def duplicate_pages(self):
        if not self._can_edit(True):
            return
        self.pdf.duplicate_pages(self._selected())
        self.after_change(structure=True)

    def rotate_pages(self, angle, sel=None):
        if not self._can_edit(True):
            return
        sel = sel or self._selected()
        self.pdf.rotate_pages(sel, angle)
        self.after_change(pages=sel, structure=True)

    def move_pages(self, d):
        if not self._can_edit(True):
            return
        sel = self._selected()
        if d < 0:
            if sel[0] == 0:
                return
            to = sel[0] - 1
        else:
            if sel[-1] >= self.pdf.page_count - 1:
                return
            to = sel[-1] + 2
        if self.pdf.move_pages(sel, to):
            self.after_change(structure=True)
            new_first = sel[0] + d
            self.thumbs.clearSelection()
            for k in range(len(sel)):
                it = self.thumbs.item(new_first + k)
                if it:
                    it.setSelected(True)
            self.viewer.go_to(new_first)

    def _reorder(self, order):
        if not self._can_edit(True):
            self.thumbs.rebuild()
            return
        self.pdf.checkpoint()
        self.pdf.doc.select(order)
        self.after_change(structure=True)

    def _thumb_menu(self, a):
        sel = self._selected()
        if a == "rot_right":
            self.rotate_pages(90, sel)
        elif a == "rot_left":
            self.rotate_pages(-90, sel)
        elif a == "extract":
            self.extract_pages()
        elif a == "duplicate":
            self.duplicate_pages()
        elif a == "blank":
            self.insert_blank(sel[-1] + 1)
        elif a == "insert":
            self.insert_file(sel[-1] + 1)
        elif a == "delete":
            self.delete_pages(sel)
        elif a == "print":
            self.print_document(sel)

    # ================================================================== edición
    def _viewer_action(self, kind, i, data):
        if not self.pdf:
            return
        if kind == "sign":
            self.sign(i, data)
            return
        if kind == "form_value":
            self._form_set(i, *data)
            return
        if kind == "form_sign":
            f = data
            if f.signed:
                self.verify()
            else:
                self.sign(i, f.rect, field_name=f.name)
            return
        if kind == "form_locked":
            dialogs.warn(self, "Formulario protegido", "El autor de este documento no permite rellenar el formulario "
                         "sin la contraseña de permisos.")
            self._unlock_restrictions()
            return
        if kind.startswith("form_"):
            self._form_action(kind, i, data)
            return
        if kind == "rotate_page":
            self.rotate_pages(data, [i])
            return
        if kind == "delete_page":
            self.delete_pages([i])
            return
        if kind in ("mark", "unmark", "mark_color", "unmark_words"):
            self._mark_action(kind, i, data)
            return
        if not self._can_edit(True):
            return
        page = self.pdf.doc[i]
        try:
            if kind == "edit_block":
                b = data
                from ..core import fonts
                QApplication.setOverrideCursor(Qt.WaitCursor)
                try:
                    fams = fonts.common_families()       # la 1.ª vez explora las fuentes del equipo
                    cache = {}

                    def resolver(text, bold, italic, b=b, page=page):
                        k = (bold, italic)
                        if k not in cache:
                            same = bold == b.bold and italic == b.italic
                            cache[k] = fonts.candidates(page, b.font_name, b.family, bold, italic,
                                                        use_embedded=same)
                        return fonts.best_for_text(cache[k], text)
                    orig = fonts.pdf_font_family(b.font_name)[1] if b.font_name else ""
                finally:
                    QApplication.restoreOverrideCursor()
                if not self._edit_paragraph(i, b, fams, resolver, orig):
                    return
            elif kind == "add_text":
                from ..core import fonts
                QApplication.setOverrideCursor(Qt.WaitCursor)
                try:
                    fams = fonts.common_families()
                finally:
                    QApplication.restoreOverrideCursor()
                last = self.settings.value("text/last", {}) or {}
                default_family = last.get("family") if last.get("family") in fams else (fams[0] if fams else "Helvetica")
                d = dialogs.TextDialog(self, "Añadir texto", "Escribe el texto que quieres añadir en la página.",
                                       "", float(last.get("fontsize", 12)), tuple(last.get("color", (0, 0, 0))),
                                       default_family, last.get("bold", "false") in (True, "true"),
                                       last.get("italic", "false") in (True, "true"), families=fams)
                if not d.exec():
                    return
                v = d.values()
                if not v["text"].strip():
                    return
                self.settings.setValue("text/last", {k: v[k] for k in ("fontsize", "color", "family", "bold", "italic")})
                self.pdf.checkpoint()
                editing.add_text(self.pdf.doc[i], data, v["text"], v["fontsize"], v["color"], v["choice"])
                self.pdf.fonts_added = True
            elif kind == "image_move":
                item, rect = data
                self.pdf.checkpoint()
                editing.move_image(page, item, rect)
            elif kind == "image_delete":
                self.pdf.checkpoint()
                editing.delete_image(page, data)
            elif kind == "image_replace":
                path, _ = QFileDialog.getOpenFileName(self, "Elegir la nueva imagen", self.settings.value("last_img_dir", ""), IMG_FILTER)
                if not path:
                    return
                self.settings.setValue("last_img_dir", os.path.dirname(path))
                self.pdf.checkpoint()
                editing.replace_image(page, data, path)
            elif kind == "add_image":
                path, _ = QFileDialog.getOpenFileName(self, "Elegir imagen", self.settings.value("last_img_dir", ""), IMG_FILTER)
                if not path:
                    return
                self.settings.setValue("last_img_dir", os.path.dirname(path))
                self.pdf.checkpoint()
                editing.add_image(page, data, path)
            elif kind == "erase":
                self.pdf.checkpoint()
                editing.erase_area(page, data)
            else:
                return
        except Exception as e:
            if self.pdf.can_undo():
                self.pdf.undo()
                self.pdf._redo.clear()
            from ..core import textedit
            if isinstance(e, textedit.EditError):
                logging.getLogger("novopdf.edicion").warning("Edición deshecha: %s", e)
                dialogs.error(self, "No se pudo cambiar el texto",
                              "No se ha podido cambiar este texto sin alterar el resto de la página, "
                              "así que se ha dejado como estaba.\n\nPrueba a cambiar menos palabras de una vez "
                              "o usa «Borrar zona» y «Añadir texto».")
            else:
                dialogs.error(self, "No se pudo realizar el cambio", str(e))
        self.after_change(pages=[i])

    def _mark_action(self, kind, i, data):
        """Resaltar, subrayar o tachar (anotaciones: no cambian el texto del documento)."""
        from ..core import markup
        if self.pdf.restricted and not self.pdf.protection.allow_annotate:
            if not self._can_edit(True):
                return
        if self.pdf.has_signatures() and not self.sign_warned and not self._can_edit(True):
            return
        page = self.pdf.doc[i]
        try:
            if kind == "mark":
                tool, words = data
                rects = markup.line_rects(words)
                if not rects:
                    return
                self.pdf.checkpoint()
                markup.add_mark(page, tool, rects, self.viewer.mark_colors.get(tool))
                n = len(words)
                verb = {T_HIGHLIGHT: "Resaltada", T_UNDERLINE: "Subrayada", T_STRIKE: "Tachada"}[tool]
                self.notify(f"{verb}{'s' if n > 1 else ''} {n} palabra{'s' if n > 1 else ''}. "
                            "Clic derecho sobre la marca para quitarla o cambiar el color.", 5000)
            elif kind == "unmark":
                self.pdf.checkpoint()
                if not markup.remove_mark(page, data):
                    self.pdf.drop_checkpoint()
                    return
                self.notify("Marca quitada.", 3000)
            elif kind == "unmark_words":
                rects = markup.line_rects(data)
                self.pdf.checkpoint()
                n = markup.remove_marks_in(page, rects)
                if not n:
                    self.pdf.drop_checkpoint()
                    self.notify("El texto seleccionado no tiene marcas.", 3000)
                    return
                self.notify(f"Se han quitado {n} marca{'s' if n > 1 else ''}.", 3000)
            elif kind == "mark_color":
                xref, col = data
                self.pdf.checkpoint()
                markup.recolor(page, xref, col)
        except Exception as e:
            if self.pdf.can_undo():
                self.pdf.undo()
                self.pdf._redo.clear()
            dialogs.error(self, "No se pudo marcar el texto", str(e))
        self.after_change(pages=[i])

    def _edit_paragraph(self, i, b, fams, resolver, orig) -> bool:
        """Editar un párrafo. Si no se cambia el formato, solo se tocan las palabras editadas
        (core.textedit); si se cambia, se vuelve a escribir el párrafo con el formato elegido."""
        from ..core import scanedit, textedit
        text = b.text
        scanned = scanedit.is_scanned_block(b, self.pdf.doc[i])
        while True:
            d = dialogs.TextDialog(self, "Editar texto", "Cambia lo que necesites: el resto del párrafo y de la "
                                   "página se mantiene igual.", text, b.fontsize, b.color,
                                   None, b.bold, b.italic, show_align=True, resolver=resolver,
                                   families=fams, original_name=orig, scanned=scanned)
            if not d.exec():
                return False
            v = d.values()
            text = v["text"]
            page = self.pdf.doc[i]
            if v["keep_style"]:
                if text.rstrip() == b.text:
                    return False
                outcome = self._apply_text_edit(page, b, text, v["choice"])
                if outcome == "edit":
                    continue
                return outcome == "done"
            # formato cambiado: se reescribe el párrafo
            self.pdf.checkpoint()
            align = v["align"]
            if align is None or align < 0:
                align = 3 if self._looks_justified(b) else 0
            editing.replace_block(page, b, text, v["fontsize"], v["color"], v["choice"], align)
            self.pdf.fonts_added = True
            return True

    def _apply_text_edit(self, page, b, text, choice) -> str:
        """Cambia solo las palabras editadas. Devuelve done | edit | cancel."""
        from ..core import textedit
        shrink = None
        while True:
            self.pdf.checkpoint()
            try:
                res = textedit.edit_paragraph(page, b, text, allow_shrink=shrink)
            except textedit.NoSpace as ns:
                self.pdf.drop_checkpoint()          # todavía no se ha cambiado nada
                c = self._ask_no_space(ns)
                if c == "shrink" and ns.shrink:
                    shrink = ns.shrink
                    continue
                return c
            except textedit.Unsupported as e:
                from ..core import scanedit
                if scanedit.is_scanned_block(b, page):
                    self.pdf.drop_checkpoint()
                    dialogs.warn(self, "Editar texto", str(e))
                    return "edit"
                logging.getLogger("novopdf.edicion").info("Edición clásica (%s)", e)
                align = 3 if self._looks_justified(b) else 0
                editing.replace_block(page, b, text, b.fontsize, b.color, choice, align)
                res = None
            break
        self.pdf.fonts_added = True
        if res is not None:
            msgs = {"reflow": "Texto cambiado; se han recolocado las palabras del párrafo.",
                    "condensed": "Texto cambiado; el párrafo se ha estrechado ligeramente para que quepa.",
                    "extra": "Texto cambiado; el párrafo ocupa una línea más.",
                    "shrunk": "Texto cambiado con la letra del párrafo algo más pequeña.",
                    "scan": "Texto cambiado sobre el escaneado: se ha tapado lo antiguo y escrito lo nuevo "
                            "imitando la letra."}
            note = msgs.get(res.mode, "Texto cambiado.")
            approx = [n for n in res.notes if n.startswith("Fuente aproximada")]
            if approx:
                note += " " + approx[0]
            self.notify(note, 7000)
        return "done"

    def _ask_no_space(self, ns) -> str:
        box = QMessageBox(QMessageBox.Question, "El texto no cabe",
                          "El texto nuevo ocupa más que el párrafo original y debajo hay otro contenido "
                          "que quedaría tapado.", parent=self)
        b_shrink = None
        if ns.shrink:
            box.setInformativeText(f"Puedes reducir la letra de este párrafo al {round(ns.shrink * 100)} % "
                                   "para que quepa en el mismo espacio, o seguir editando para acortar el texto.")
            b_shrink = box.addButton(f"Reducir la letra al {round(ns.shrink * 100)} %", QMessageBox.AcceptRole)
        else:
            box.setInformativeText("Acorta un poco el texto para que quepa en el espacio del párrafo.")
        b_edit = box.addButton("Seguir editando", QMessageBox.ActionRole)
        box.addButton("Cancelar", QMessageBox.RejectRole)
        box.exec()
        c = box.clickedButton()
        if b_shrink is not None and c is b_shrink:
            return "shrink"
        if c is b_edit:
            return "edit"
        return "cancel"

    @staticmethod
    def _looks_justified(b) -> bool:
        rs = [r.x1 for r in b.line_rects[:-1]] if len(b.line_rects) > 2 else []
        return bool(rs) and max(rs) - min(rs) < 2.5

    # ================================================================== búsqueda
    def _focus_search(self):
        if self.pdf:
            self.tabs[0].setChecked(True)
            self._tab_changed(0)
            self.search.setFocus()
            self.search.selectAll()

    def _clear_search(self):
        self.search_results = []
        self.search_pos = -1
        self.viewer.search_hits = {}
        self.viewer.current_hit = None
        if hasattr(self, "search_info"):
            self.search_info.setText("")
        for w in self.viewer.pages:
            w.update()

    def search_next(self):
        if not self.pdf:
            return
        q = self.search.text().strip()
        if not q:
            return
        if not self.search_results:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            hits = {}
            for i in range(self.pdf.page_count):
                r = self.pdf.doc[i].search_for(q)
                if r:
                    hits[i] = r
                    self.search_results += [(i, x) for x in r]
            QApplication.restoreOverrideCursor()
            self.viewer.search_hits = hits
            if not self.search_results:
                self.search_info.setText("Sin resultados" + (" · ¿Documento escaneado? Prueba «Reconocer texto»" if self._scanned else ""))
                return
            start = self.viewer.current_page()
            self.search_pos = next((k - 1 for k, (i, _) in enumerate(self.search_results) if i >= start), -1)
        self.search_pos = (self.search_pos + 1) % len(self.search_results)
        i, r = self.search_results[self.search_pos]
        self.viewer.current_hit = (i, r)
        self.search_info.setText(f"Resultado {self.search_pos + 1} de {len(self.search_results)} · Intro: siguiente")
        self.viewer.go_to(i, r)
        for w in self.viewer.pages:
            w.update()

    # ================================================================== exportar imágenes
    def export_images(self):
        self._commit_form()
        if not self.pdf:
            return
        base = os.path.splitext(self.pdf.name)[0]
        folder = os.path.dirname(self.pdf.path) if self.pdf.path else self.settings.value("last_dir", os.path.expanduser("~"))
        d = dialogs.ExportDialog(self, self.pdf.page_count, self.viewer.current_page(),
                                 self.thumbs.selected_pages(), folder, base, self.settings)
        if not d.exec():
            return
        opts = d.result
        n = len(opts["pages"])
        prog = QProgressDialog("Preparando…", "Cancelar", 0, n, self)
        prog.setWindowTitle("Exportando imágenes")
        prog.setWindowModality(Qt.WindowModal)
        prog.setMinimumDuration(300)
        prog.setMinimumWidth(380)
        try:
            from PIL import Image
            Image.init()   # cargar los formatos antes de pasar al hilo de trabajo
        except Exception:
            pass
        worker = ExportWorker(self.pdf.plain_bytes(), opts)
        self._export_worker = worker

        def on_progress(k, total):
            prog.setMaximum(total)
            prog.setValue(k)
            prog.setLabelText(f"Exportando página {min(k + 1, total)} de {total}…")

        def on_done(files):
            _close(prog)
            if not files:
                return
            box = QMessageBox(QMessageBox.Information, "Exportación terminada",
                              f"Se han creado {len(files)} archivo(s) en:\n{opts['folder']}", parent=self)
            open_btn = box.addButton("Abrir la carpeta", QMessageBox.AcceptRole)
            box.addButton("Cerrar", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is open_btn:
                from PySide6.QtCore import QUrl
                from PySide6.QtGui import QDesktopServices
                QDesktopServices.openUrl(QUrl.fromLocalFile(opts["folder"]))

        def on_fail(msg):
            _close(prog)
            dialogs.error(self, "No se pudo exportar", msg)

        worker.progress.connect(on_progress)
        worker.done.connect(on_done)
        worker.failed.connect(on_fail)
        prog.canceled.connect(worker.cancel)
        worker.start()

    # ================================================================== imprimir
    def print_document(self, pages: list[int] | None = None):
        self._commit_form()
        """Imprime el documento tal como se ve (con los cambios aún sin guardar)."""
        if not self.pdf:
            return
        if not self.pdf.print_allowed:
            if not dialogs.confirm(self, "Impresión no permitida",
                                   "El autor de este documento no permite imprimirlo.\n\n"
                                   "Si conoces la contraseña de permisos, puedes introducirla para imprimir.",
                                   "Introducir contraseña…", "Cancelar"):
                return
            self._unlock_restrictions()
            if not self.pdf.print_allowed:
                return
        try:
            from ..core import printing
            from .printdialog import PrintDialog
        except ImportError as e:
            logging.getLogger("novopdf.impresion").exception("Impresión no disponible")
            dialogs.error(self, "Imprimir", "La impresión no está disponible en esta instalación de NovoPDF "
                                            f"(falta un componente: {e}).\n\nInstala la versión completa más reciente.")
            return
        sel = self.thumbs.selected_pages()
        d = PrintDialog(self, self.pdf.doc, self.pdf.name, self.viewer.current_page(), sel, self.settings)
        if pages:
            if len(pages) > 1 and d.r_sel.isEnabled():
                d.r_sel.setChecked(True)
            else:
                d.rng.setText(", ".join(str(p + 1) for p in sorted(pages)))
                d.r_rng.setChecked(True)
        if not d.exec() or not d.result:
            return
        opts = d.result
        printer = d.printer
        name = printer.printerName() or os.path.basename(printer.outputFileName() or "")
        prog = QProgressDialog("Preparando la impresión…", "Cancelar", 0, max(1, len(opts["pages"])), self)
        prog.setWindowTitle("Imprimiendo")
        prog.setWindowModality(Qt.WindowModal)
        prog.setMinimumDuration(0)
        prog.setMinimumWidth(400)
        prog.setValue(0)

        def progress(k, total):
            prog.setMaximum(total)
            prog.setValue(k)
            if k < total:
                prog.setLabelText(f"Enviando la página {k + 1} de {total} a «{name}»…")
            QApplication.processEvents()
            return not prog.wasCanceled()

        try:
            if opts.get("compat"):
                from ..core import printing_win
                n = printing_win.print_pages(self.pdf.doc, opts["printer"], opts["pages"], fit=opts["fit"],
                                             auto_rotate=opts["auto_rotate"], gray=opts["gray"],
                                             copies=opts["copies"], collate=opts["collate"],
                                             duplex=opts["duplex"], paper_id=opts["paper_id"],
                                             doc_name=self.pdf.name, progress=progress)
            else:
                n = printing.print_pages(self.pdf.doc, printer, opts["pages"], fit=opts["fit"],
                                         auto_rotate=opts["auto_rotate"], gray=opts["gray"],
                                         copies=opts["copies"], collate=opts["collate"], progress=progress)
        except printing.PrintCancelled:
            _close(prog)
            self.notify("Impresión cancelada.", 4000)
            return
        except printing.PrintError as e:
            _close(prog)
            dialogs.error(self, "No se pudo imprimir", str(e))
            return
        _close(prog)
        copies = "" if opts["copies"] <= 1 else f" ({opts['copies']} copias)"
        self.notify(f"Enviado a «{name}»: {len(opts['pages'])} página{'s' if len(opts['pages']) != 1 else ''}{copies}.", 6000)

    # ================================================================== Word y Excel
    def export_office(self, kind, _after_ocr=False):
        self._commit_form()
        if not self.pdf:
            return
        if not self.pdf.copy_allowed:
            if not dialogs.confirm(self, "Copia no permitida",
                                   "El autor de este documento no permite copiar su contenido.\n\n"
                                   "Si conoces la contraseña de permisos, puedes introducirla para exportarlo.",
                                   "Introducir contraseña…", "Cancelar"):
                return
            self._unlock_restrictions()
            if not self.pdf.copy_allowed:
                return
        if self._scanned and not _after_ocr and ocr.tessdata_dir():
            box = QMessageBox(QMessageBox.Question, "Documento escaneado",
                              "Este documento parece escaneado: sus páginas son imágenes y no tienen texto.",
                              parent=self)
            box.setInformativeText("Para que el texto se pueda editar en " + ("Word" if kind == "docx" else "Excel")
                                   + ", primero hay que reconocerlo (OCR). ¿Quieres hacerlo ahora?")
            b_ocr = box.addButton("Reconocer el texto y exportar", QMessageBox.AcceptRole)
            b_go = box.addButton("Exportar sin reconocer", QMessageBox.ActionRole)
            box.addButton("Cancelar", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is b_ocr:
                self._start_ocr(list(range(self.pdf.page_count)),
                                on_finished=lambda words: self.export_office(kind, True))
                return
            if box.clickedButton() is not b_go:
                return
        base = os.path.splitext(self.pdf.name)[0]
        folder = os.path.dirname(self.pdf.path) if self.pdf.path else self.settings.value("last_dir", os.path.expanduser("~"))
        default = os.path.join(self.settings.value("office/last_dir", folder) or folder, f"{base}.{kind}")
        d = dialogs.OfficeExportDialog(self, kind, self.pdf.page_count, self.viewer.current_page(),
                                       self.thumbs.selected_pages(), default, self.settings)
        if not d.exec() or not d.result:
            return
        job = d.result
        self.settings.setValue("office/last_dir", os.path.dirname(job["path"]))
        n = len(job["pages"])
        what = "Word" if kind == "docx" else "Excel"
        prog = QProgressDialog(f"Preparando la exportación a {what}…", "Cancelar", 0, max(1, n), self)
        prog.setWindowTitle(f"Exportando a {what}")
        prog.setWindowModality(Qt.WindowModal)
        prog.setMinimumDuration(200)
        prog.setMinimumWidth(400)
        worker = OfficeWorker(self.pdf.plain_bytes(), job)
        self._office_worker = worker

        def on_progress(k, total):
            prog.setMaximum(total)
            prog.setValue(k)
            prog.setLabelText(f"Exportando a {what}… ({min(100, round(100 * k / max(1, total)))} %)")

        def on_done(stats):
            _close(prog)
            self._export_finished(job, stats)

        def on_fail(msg):
            _close(prog)
            if msg:
                dialogs.error(self, "No se pudo exportar", msg)
            else:
                self.notify("Exportación cancelada.", 3000)

        worker.progress.connect(on_progress)
        worker.done.connect(on_done)
        worker.failed.connect(on_fail)
        prog.canceled.connect(worker.cancel)
        worker.start()

    def _export_finished(self, job, stats):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        path = job["path"]
        if job["kind"] == "docx":
            parts = [f"{stats.get('pages', 0)} página(s)"]
            if stats.get("tables"):
                parts.append(f"{stats['tables']} tabla(s)")
            if stats.get("images"):
                parts.append(f"{stats['images']} imagen(es)")
            text = "Se ha creado el documento de Word (" + ", ".join(parts) + "):\n" + path
            if stats.get("scanned"):
                text += (f"\n\n{stats['scanned']} página(s) no tenían texto (escaneadas) y se han incluido como imagen.")
        else:
            if stats.get("fallback"):
                text = ("No se han encontrado tablas con líneas en el PDF, así que se ha pasado todo el texto "
                        f"a columnas ({stats.get('sheets', 0)} hoja(s)):\n{path}")
            elif stats.get("mode") == "text":
                text = f"Se ha creado el libro de Excel ({stats.get('sheets', 0)} hoja(s)):\n{path}"
            else:
                text = f"Se ha creado el libro de Excel con {stats.get('tables', 0)} tabla(s):\n{path}"
        box = QMessageBox(QMessageBox.Information, "Exportación terminada", text, parent=self)
        b_open = box.addButton("Abrir el archivo", QMessageBox.AcceptRole)
        b_dir = box.addButton("Abrir la carpeta", QMessageBox.ActionRole)
        box.addButton("Cerrar", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is b_open:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        elif box.clickedButton() is b_dir:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))

    # ================================================================== OCR
    def run_ocr(self):
        if not self.pdf or not self._can_edit(True):
            return
        if not ocr.tessdata_dir():
            dialogs.error(self, "OCR no disponible", "No se encuentran los datos de idioma del OCR (carpeta «recursos/tessdata»).")
            return
        d = dialogs.OcrDialog(self, self.pdf.page_count, self.viewer.current_page(), self.thumbs.selected_pages())
        if not d.exec():
            return
        self._start_ocr(d.pages(), d.lang.currentData(), d.quality.currentData(), d.skip.isChecked())

    def _start_ocr(self, pages, lang="spa", dpi=300, only_needed=True, on_finished=None):
        """Lanza el OCR en segundo plano. on_finished(words) sustituye al mensaje final."""
        prog = QProgressDialog("Preparando…", "Cancelar", 0, len(pages), self)
        prog.setWindowTitle("Reconociendo texto")
        prog.setWindowModality(Qt.WindowModal)
        prog.setMinimumDuration(0)
        prog.setMinimumWidth(380)
        prog.setValue(0)
        worker = OcrWorker(self.pdf.plain_bytes(), pages, lang, dpi, only_needed)
        self._ocr_worker = worker

        def on_progress(k, n):
            prog.setMaximum(n)
            prog.setValue(k)
            prog.setLabelText(f"Reconociendo texto: página {min(k + 1, n)} de {n}…")

        def on_done(data, words):
            _close(prog)
            self.pdf.replace_with_bytes(data)
            self._scanned = False
            self.after_change(structure=True)
            if on_finished:
                on_finished(words)
            elif words:
                dialogs.info(self, "Texto reconocido", f"Se han reconocido {words} palabras.\n\nAhora puedes buscar, seleccionar y copiar el texto. "
                             "Guarda el documento para conservar el resultado.")
            else:
                dialogs.info(self, "Reconocer texto", "No se ha encontrado texto nuevo que reconocer "
                             "(las páginas ya tenían texto o no contienen texto legible).")

        def on_fail(msg):
            _close(prog)
            if msg:
                dialogs.error(self, "Error en el OCR", msg)
            elif on_finished:
                on_finished(None)

        worker.progress.connect(on_progress)
        worker.done.connect(on_done)
        worker.failed.connect(on_fail)
        prog.canceled.connect(worker.cancel)
        worker.start()

    # ================================================================== escanear
    def scan_document(self, adding=False):
        from ..core import scanner
        if not scanner.available():
            dialogs.warn(self, "Escanear", "El escaneo directo solo está disponible en Windows y macOS.")
            return
        if adding and not self.pdf:
            adding = False
        if adding and not self._can_edit(True):
            return
        if scanner.USE_FOLDER_SCAN:
            # macOS: Captura de Imagen + carpeta vigilada
            d = dialogs.FolderScanDialog(self, self.settings, adding)
            if not d.exec():
                return
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                images = scanner.files_to_images(d.files)
            except Exception as e:
                QApplication.restoreOverrideCursor()
                dialogs.error(self, "Escanear", f"No se pudieron leer las páginas escaneadas:\n{e}")
                return
            QApplication.restoreOverrideCursor()
            self._scan = dict(images=images, adding=adding, ocr=d.ocr.isChecked(), blank=d.blank.isChecked(),
                              mode=d.mode.currentData(), opts=None)
            self._finish_scan()
            return
        scanner.com_init()
        d = dialogs.ScanDialog(self, self.settings, adding)
        if not d.exec():
            return
        self._scan = dict(images=[], adding=adding, ocr=d.ocr.isChecked(), blank=d.blank.isChecked(),
                          mode=d.mode.currentData(), opts=getattr(d, "options", None))
        if d.use_wizard:
            self._scan_with_wizard()
        else:
            self._scan_round()

    def _scan_with_wizard(self):
        from ..core import scanner
        while True:
            try:
                imgs = scanner.acquire_with_windows_dialog()
            except scanner.ScannerError as e:
                dialogs.error(self, "Escanear", str(e))
                break
            if not imgs:
                break
            self._scan["images"] += imgs
            n = len(self._scan["images"])
            if not dialogs.confirm(self, "Escanear", f"Página {n} escaneada.\n¿Quieres escanear otra página?",
                                   "Escanear otra página", "Terminar"):
                break
        self._finish_scan()

    def _scan_round(self):
        from ..core import scanner
        st = self._scan
        opts = st["opts"]
        first = len(st["images"]) + 1
        prog = QProgressDialog(f"Escaneando la página {first}…", "Cancelar", 0, 0, self)
        prog.setWindowTitle("Escaneando")
        prog.setWindowModality(Qt.WindowModal)
        prog.setMinimumDuration(0)
        prog.setMinimumWidth(380)
        worker = ScanWorker(opts)
        self._scan_worker = worker

        def on_page(img):
            st["images"].append(img)
            prog.setLabelText(f"Página {len(st['images'])} escaneada. "
                              + ("Escaneando la siguiente…" if opts.source != "flatbed" else "Procesando…"))

        def on_done(n):
            _close(prog)
            if worker.cancelled_flag:
                self._finish_scan(cancelled=True)
                return
            total = len(st["images"])
            if opts.source == "flatbed":
                box = QMessageBox(QMessageBox.Question, "Escanear",
                                  f"Página {total} escaneada.\n\nSi hay más páginas, coloca la siguiente en el "
                                  "cristal y pulsa «Escanear otra página».", parent=self)
            else:
                box = QMessageBox(QMessageBox.Question, "Escanear",
                                  f"Se han escaneado {total} página(s).\n\nSi tienes más hojas, colócalas en el "
                                  "alimentador y pulsa «Escanear más hojas».", parent=self)
            more = box.addButton("Escanear otra página" if opts.source == "flatbed" else "Escanear más hojas",
                                 QMessageBox.ActionRole)
            done = box.addButton("Terminar", QMessageBox.AcceptRole)
            box.setDefaultButton(done)
            box.exec()
            if box.clickedButton() is more:
                self._scan_round()
            else:
                self._finish_scan()

        def on_fail(msg, no_paper):
            _close(prog)
            n = len(st["images"])
            if no_paper and n == 0:
                msg = "No hay papel en el alimentador. Coloca las hojas y vuelve a intentarlo."
            if n:
                if dialogs.confirm(self, "Escanear", f"{msg}\n\nYa hay {n} página(s) escaneada(s). "
                                   "¿Quieres crear el PDF con ellas?", "Sí, crear el PDF", "No, descartarlas"):
                    self._finish_scan()
            else:
                dialogs.error(self, "No se pudo escanear", msg + "\n\nSi el problema continúa, prueba con "
                              "«Usar el asistente de escaneo de Windows» en la ventana de escaneo.")

        worker.page.connect(on_page)
        worker.done.connect(on_done)
        worker.failed.connect(on_fail)
        prog.canceled.connect(worker.cancel)
        worker.start()

    def _finish_scan(self, cancelled=False):
        from ..core import scanner
        st = self._scan
        if not st["images"]:
            return
        if cancelled and not dialogs.confirm(
                self, "Escaneo cancelado", f"Se han escaneado {len(st['images'])} página(s) antes de cancelar.\n"
                "¿Quieres crear el PDF con ellas?", "Sí, crear el PDF", "No, descartarlas"):
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            data, removed = scanner.images_to_pdf(st["images"], st["mode"], st["blank"])
        except Exception as e:
            QApplication.restoreOverrideCursor()
            dialogs.error(self, "Escanear", f"No se pudo crear el PDF:\n{e}")
            return
        QApplication.restoreOverrideCursor()
        if not data:
            dialogs.info(self, "Escanear", "Todas las páginas escaneadas estaban en blanco.")
            return
        src = pymupdf.open(stream=data, filetype="pdf")
        n = src.page_count
        if st["adding"] and self.pdf:
            at = self.viewer.current_page() + 1
            self.pdf.checkpoint()
            self.pdf.doc.insert_pdf(src, start_at=at)
            src.close()
            self.after_change(structure=True)
            QTimer.singleShot(50, lambda: self.viewer.go_to(at))
            new_pages = list(range(at, at + n))
        else:
            src.close()
            import datetime as _dt
            doc = PdfDocument.from_bytes(data)
            doc.modified = True
            doc.title = _dt.datetime.now().strftime("Escaneo %Y-%m-%d %H.%M.pdf")
            self._set_document(doc)
            new_pages = list(range(n))
        extra = f" Se han quitado {removed} página(s) en blanco." if removed else ""

        def summary(words):
            msg = f"Se han escaneado {n} página(s).{extra}"
            if words:
                msg += f"\nTexto reconocido: {words} palabras."
            msg += "\n\nRecuerda guardar el documento."
            dialogs.info(self, "Escaneo terminado", msg)

        if st["ocr"] and ocr.tessdata_dir():
            self._scanned = False
            self._start_ocr(new_pages, "spa", 300, True, on_finished=summary)
        else:
            summary(None)

    # ================================================================== formularios
    def _commit_form(self):
        """Pasa al PDF lo que se esté escribiendo en un campo."""
        try:
            self.viewer.editor.close(commit=True)
        except Exception:
            logging.getLogger("novopdf.formulario").exception("No se pudo guardar el campo")

    def _update_form_state(self):
        from ..core import forms
        if not self.pdf:
            self._form_state = ("none", 0, [])
            return
        try:
            doc = self.pdf.doc
            if not doc.is_form_pdf:      # rápido (catálogo): sin formulario no se recorren las páginas
                xfa = doc.xref_get_key(doc.pdf_catalog(), "AcroForm/XFA")[0] != "null"
                kind, n, missing = ("xfa_only" if xfa else "none"), 0, []
            else:
                kind = forms.form_kind(doc)
                n = forms.count(doc)
                missing = forms.missing_required(doc) if n else []
        except Exception:
            kind, n, missing = "none", 0, []
        self._form_state = (kind, n, missing)
        d = self.docs[self._cur] if 0 <= self._cur < len(self.docs) else None
        if kind == "xfa_hybrid" and d is not None and not d.xfa_warned:
            d.xfa_warned = True
            self.notify("Formulario XFA de Adobe: al rellenarlo con NovoPDF se guarda como formulario "
                        "normal (compatible con todos los lectores).", 8000)

    def _fill_first(self):
        f = self.viewer.first_field()
        if f is not None:
            self.viewer.open_field(f)

    def _goto_missing(self):
        missing = self._form_state[2]
        if not missing:
            return
        cur = self.viewer.editor
        start = (cur.page, cur.xref) if cur.active else None
        pick = missing[0]
        if start:
            keys = [(m.page, m.xref) for m in missing]
            if start in keys:
                pick = missing[(keys.index(start) + 1) % len(missing)]
        f = self.viewer.field_by_xref(pick.page, pick.xref) or pick
        if f.kind == "signature":
            self.viewer.go_to(f.page, f.rect)
            self.notify(f"Falta firmar en «{f.display_name}»: haz clic en el campo de firma.", 6000)
            return
        self.viewer.open_field(f)

    def _can_fill(self) -> bool:
        """Rellenar un formulario: lo permite el autor (aunque limite la edición) y, si el
        documento está firmado, se avisa de que las firmas dejarán de ser válidas."""
        if not self.pdf:
            return False
        if self.pdf.restricted and not self.pdf.form_allowed:
            dialogs.warn(self, "Formulario protegido", "El autor de este documento no permite rellenar el formulario "
                         "sin la contraseña de permisos.")
            self._unlock_restrictions()
            if self.pdf.restricted and not self.pdf.form_allowed:
                return False
        if self.pdf.has_signatures() and not self.sign_warned:
            if not dialogs.confirm(self, "Documento firmado",
                                   "Este documento está firmado digitalmente.\nSi rellenas o cambias el formulario, "
                                   "las firmas existentes dejarán de ser válidas.\n\n¿Quieres continuar?",
                                   "Continuar de todos modos", "Cancelar"):
                return False
            self.sign_warned = True
        return True

    def _form_set(self, i, xref, value):
        from ..core import forms
        if not self._can_fill():
            self.viewer.refresh([i])
            return
        f = self.viewer.field_by_xref(i, xref)
        self.pdf.checkpoint()
        try:
            changed = forms.set_value(self.pdf.doc, i, xref, value)
        except forms.FormError as e:
            self.pdf.drop_checkpoint()
            self.notify(str(e), 4000)
            return
        except Exception as e:  # noqa
            logging.getLogger("novopdf.formulario").exception("No se pudo rellenar el campo")
            self.pdf.drop_checkpoint()
            dialogs.error(self, "No se pudo rellenar el campo", str(e))
            return
        if not changed:
            self.pdf.drop_checkpoint()
            return
        pages = {i}
        if f is not None:
            try:
                pages |= {g.page for g in forms.all_fields(self.pdf.doc) if g.name == f.name}
            except Exception:
                pages = None
        self.after_change(pages=sorted(pages) if pages else None)

    def _form_action(self, kind, i, data):
        """Crear, mover, duplicar, eliminar o cambiar las propiedades de un campo."""
        from ..core import formdetect, forms
        if not self._can_edit(True):
            return
        doc = self.pdf.doc
        select = None
        try:
            if kind == "form_add":
                fkind, r, small = data
                pr = self.viewer.page_rect(i)
                rect = forms.default_rect(fkind, r, pr) if small else forms.clamp(r, pr)
                label = formdetect.suggest_label(doc[i], rect, fkind)
                opts = {}
                if fkind in (forms.COMBO, forms.LIST, forms.RADIO):
                    groups = forms.radio_groups(doc)
                    tmp = forms.Field(page=i, xref=0, name="", kind=fkind, rect=rect)
                    if fkind == forms.RADIO:
                        last = getattr(self, "_last_radio_group", None)
                        tmp.name = last if last in groups else forms.unique_name(doc, "Grupo")
                        n = len(groups.get(tmp.name, [])) + 1
                        tmp.on_state = forms.export_name(label, f"Opcion{n}") if label else f"Opcion{n}"
                    else:
                        tmp.name = forms.unique_name(doc, label or ("Lista" if fkind == forms.LIST else "Desplegable"))
                    tmp.label = formdetect._tooltip(label) if fkind != forms.RADIO else ""
                    d = dialogs.FieldDialog(self, tmp, creating=True, groups=groups.keys(),
                                            taken=forms.existing_names(doc))
                    if not d.exec():
                        return
                    v = d.values()
                    opts = dict(name=v["name"], label=v["label"], required=v["required"])
                    if fkind == forms.RADIO:
                        opts["export"] = forms.export_name(v["export"], "Opcion")
                        self._last_radio_group = v["name"]
                    else:
                        opts["options"] = v.get("options")
                        opts["editable"] = v.get("editable", False)
                else:
                    opts = dict(name=label or None, label=formdetect._tooltip(label))
                self.pdf.checkpoint()
                xref = forms.add_field(doc, i, fkind, rect, **opts)
                select = xref
                created = [x for x in forms.page_fields(doc, i) if x.xref == xref]
                name = created[0].name if created else ""
                self.notify(f"{forms.KIND_NAMES[fkind]} «{name}» creado. Haz doble clic sobre él con "
                            "«Editar campos» para cambiar su nombre u otras propiedades.", 6000)
            elif kind == "form_move":
                xref, rect = data
                self.pdf.checkpoint()
                forms.move_field(doc, i, xref, rect)
                select = xref
            elif kind == "form_delete":
                f = self.viewer.field_by_xref(i, data)
                self.pdf.checkpoint()
                forms.delete_field(doc, i, data)
                if f is not None:
                    self.notify(f"Campo «{f.name}» eliminado (Ctrl+Z para recuperarlo).", 4000)
            elif kind == "form_dup":
                self.pdf.checkpoint()
                select = forms.duplicate_field(doc, i, data)
            elif kind == "form_props":
                f = self.viewer.field_by_xref(i, data)
                if f is None:
                    return
                d = dialogs.FieldDialog(self, f, groups=forms.radio_groups(doc).keys(),
                                        taken=forms.existing_names(doc))
                if not d.exec():
                    return
                v = d.values()           # en un grupo de opciones, el nombre es el del grupo (cambia en todas)
                self.pdf.checkpoint()
                forms.update_field(doc, i, data, **v)
                select = data
            else:
                return
        except forms.FormError as e:
            self.pdf.drop_checkpoint()
            dialogs.error(self, "Formulario", str(e))
            return
        except Exception as e:  # noqa
            logging.getLogger("novopdf.formulario").exception("Cambio de formulario fallido")
            if self.pdf.can_undo():
                self.pdf.undo()
                self.pdf._redo.clear()
            dialogs.error(self, "No se pudo cambiar el formulario", str(e))
            self.after_change(structure=True)
            return
        self.after_change(pages=None if kind == "form_props" else [i])
        if select is not None and self.viewer.tool in FORM_TOOLS:
            self.viewer.select_field(i, select)

    def form_detect(self, after_ocr=False):
        from ..core import formdetect
        if not self.pdf or not self._can_edit(True):
            return
        self._commit_form()
        if self.pdf.looks_scanned() and not after_ocr and ocr.tessdata_dir():
            box = QMessageBox(QMessageBox.Question, "Detectar campos",
                              "Las páginas parecen escaneadas y sin texto reconocido.\n\nSi antes se reconoce el "
                              "texto (OCR), cada campo tomará el nombre de su etiqueta («Nombre», «DNI»…); si no, "
                              "se llamarán «Campo», «Campo 2»…", parent=self)
            first = box.addButton("Reconocer el texto primero", QMessageBox.AcceptRole)
            box.addButton("Detectar ahora", QMessageBox.ActionRole)
            cancel = box.addButton("Cancelar", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is cancel:
                return
            if box.clickedButton() is first:
                self._start_ocr(list(range(self.pdf.page_count)),
                                on_finished=lambda words: self.form_detect(after_ocr=True))
                return
        n_pages = self.pdf.page_count
        prog = None
        if n_pages > 8:
            prog = QProgressDialog("Buscando campos…", "Cancelar", 0, n_pages, self)
            prog.setWindowTitle("Detectar campos")
            prog.setWindowModality(Qt.WindowModal)
            prog.setMinimumDuration(300)
        cancelled = []

        def progress(k, n):
            if prog is not None:
                prog.setValue(k)
                QApplication.processEvents()
                if prog.wasCanceled():
                    cancelled.append(True)
                    raise KeyboardInterrupt
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            found = formdetect.detect(self.pdf.doc, progress=progress)
        except KeyboardInterrupt:
            found = {}
        finally:
            QApplication.restoreOverrideCursor()
            if prog is not None:
                _close(prog)
        if cancelled:
            return
        if not found:
            dialogs.info(self, "Detectar campos", "No se han encontrado sitios para rellenar (rayas, recuadros vacíos, "
                         "celdas de tablas o casillas).\n\nPuedes añadir los campos a mano: elige un tipo de campo "
                         "y dibújalo en la página.")
            return
        counts = {}
        for props in found.values():
            for p in props:
                counts[p.kind] = counts.get(p.kind, 0) + 1
        cur = self.viewer.current_page()
        d = dialogs.DetectFieldsDialog(self, counts, len(found), len(found) > 1 and cur in found)
        if not d.exec():
            return
        if d.only_page.isChecked():
            found = {cur: found[cur]}
        self.pdf.checkpoint()
        try:
            n = formdetect.apply(self.pdf.doc, found)
        except Exception as e:  # noqa
            logging.getLogger("novopdf.formulario").exception("Detección fallida")
            self.pdf.undo()
            self.pdf._redo.clear()
            dialogs.error(self, "Detectar campos", f"No se pudieron crear los campos:\n{e}")
            self.after_change(structure=True)
            return
        if not n:
            self.pdf.drop_checkpoint()
            return
        self.after_change(pages=sorted(found))
        self.tabs[TAB_FORM].setChecked(True)
        self._tab_changed(TAB_FORM)
        self.set_tool(T_FORM_EDIT)
        first = min(found)
        if first != self.viewer.current_page():
            self.viewer.go_to(first)
        self.notify(f"Se han creado {n} campo{'s' if n != 1 else ''}. Revísalos y pulsa «Terminar» para rellenar.", 8000)

    def form_reset(self):
        from ..core import forms
        if not self.pdf:
            return
        self._commit_form()
        if not self._form_state[1]:
            self.notify("Este documento no tiene campos.", 3000)
            return
        if not dialogs.confirm(self, "Vaciar formulario", "¿Borrar lo escrito en todos los campos del formulario?\n\n"
                               "Se puede deshacer con Ctrl+Z.", "Vaciar", "Cancelar"):
            return
        if not self._can_fill():
            return
        self.pdf.checkpoint()
        n = forms.reset(self.pdf.doc)
        if not n:
            self.pdf.drop_checkpoint()
            self.notify("El formulario ya estaba vacío.", 3000)
            return
        self.after_change()
        self.notify(f"Formulario vaciado ({n} campo{'s' if n != 1 else ''}).", 4000)

    def form_flatten(self):
        from ..core import forms
        if not self.pdf or not self._can_edit(True):
            return
        self._commit_form()
        if not self._form_state[1]:
            self.notify("Este documento no tiene campos.", 3000)
            return
        if not dialogs.confirm(self, "Aplanar formulario",
                               "Lo escrito en los campos pasará a ser texto fijo de la página: se verá y se imprimirá "
                               "igual en cualquier programa, pero ya no se podrá cambiar.\n\nLos campos de firma vacíos "
                               "se conservan para poder firmar después.\n\nConsejo: si quieres conservar también el "
                               "formulario rellenable, usa después «Guardar como» con otro nombre.",
                               "Aplanar", "Cancelar"):
            return
        self.pdf.checkpoint()
        try:
            n = forms.flatten(self.pdf.doc)
        except Exception as e:  # noqa
            logging.getLogger("novopdf.formulario").exception("Aplanar fallido")
            self.pdf.undo()
            self.pdf._redo.clear()
            dialogs.error(self, "Aplanar formulario", str(e))
            self.after_change(structure=True)
            return
        self.set_tool(T_SELECT)
        self.after_change()
        self.notify(f"Formulario aplanado ({n} campo{'s' if n != 1 else ''}). Recuerda guardar.", 5000)

    def toggle_field_highlight(self, on: bool):
        self.viewer.show_fields = bool(on)
        self.settings.setValue("form/highlight", bool(on))
        for w in self.viewer.pages:
            w.update()

    def export_form_data(self, many: bool):
        from ..core import forms
        self._commit_form()
        start = self.settings.value("last_dir", os.path.expanduser("~"))
        rows = []
        if many:
            paths, _ = QFileDialog.getOpenFileNames(self, "Elegir los formularios rellenados", start, PDF_FILTER)
            if not paths:
                return
            skipped = []
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                for p in paths:
                    try:
                        x = pymupdf.open(p)
                        if x.needs_pass:
                            skipped.append(os.path.basename(p))
                            x.close()
                            continue
                        rows.append((os.path.basename(p), forms.values(x)))
                        x.close()
                    except Exception:
                        skipped.append(os.path.basename(p))
            finally:
                QApplication.restoreOverrideCursor()
            base = "datos_formularios.xlsx"
            folder = os.path.dirname(paths[0])
        else:
            if not self.pdf or not self._form_state[1]:
                self.notify("Este documento no tiene campos.", 3000)
                return
            rows.append((self.pdf.name, forms.values(self.pdf.doc)))
            skipped = []
            base = os.path.splitext(self.pdf.name)[0] + "_datos.xlsx"
            folder = os.path.dirname(self.pdf.path) if self.pdf.path else start
        if not any(r[1] for r in rows):
            dialogs.info(self, "Exportar datos", "Los documentos elegidos no tienen campos de formulario.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Guardar los datos", os.path.join(folder, base),
                                              "Hoja de cálculo de Excel (*.xlsx)")
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        try:
            forms.write_xlsx(path, rows)
        except PermissionError:
            dialogs.error(self, "Exportar datos", "No se puede escribir el archivo. Si está abierto en Excel, "
                          "ciérralo y vuelve a intentarlo.")
            return
        except Exception as e:  # noqa
            dialogs.error(self, "Exportar datos", f"No se pudieron guardar los datos:\n{e}")
            return
        msg = f"Datos de {len(rows)} formulario{'s' if len(rows) != 1 else ''} guardados en:\n{path}"
        if skipped:
            msg += "\n\nNo se han podido leer (protegidos o dañados): " + ", ".join(skipped)
        dialogs.info(self, "Exportar datos", msg)

    # ================================================================== firma
    def sign(self, page_index, rect, field_name=None):
        if not self.pdf:
            return
        self._commit_form()
        if self.pdf.restricted:
            self._can_edit(True)
            if self.pdf.restricted:
                return
        visible = rect is not None
        if page_index is None:
            page_index = self.viewer.current_page()
        base = os.path.splitext(self.pdf.name)[0]
        folder = os.path.dirname(self.pdf.path) if self.pdf.path else self.settings.value("last_dir", os.path.expanduser("~"))
        default_out = os.path.join(folder, f"{base}_firmado.pdf")
        d = dialogs.SignDialog(self, default_out, visible, page_index + 1, self.settings)
        if not d.exec():
            self.set_tool(T_SELECT)
            return
        from ..core import certstore, signing
        log = logging.getLogger("novopdf.firma")
        out = d.out.text().strip()
        if not out.lower().endswith(".pdf"):
            out += ".pdf"
        if self._busy_path(out):
            return
        store = d.choice.source == "windows"
        log.info("Firma iniciada (%s, %s): %s", "almacén" if store else "archivo .pfx",
                 "visible" if visible else "invisible", d.choice.holder)
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            data, pw = self.pdf.bytes_for_signing()
            signer = signing.signer_for(d.choice, d.pfx_signer)
            prep = signing.prepare_signature(data, signer, page_index=page_index, rect=rect,
                                             reason=d.reason.currentText().strip(),
                                             location=d.location.text().strip(), password=pw,
                                             field_name=field_name)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            log.warning("No se pudo preparar la firma: %s", e)
            dialogs.error(self, "No se pudo firmar", str(e))
            return
        QApplication.restoreOverrideCursor()

        # La operación criptográfica (y la petición de PIN) va en un hilo aparte para
        # que la ventana siga respondiendo y la petición del sistema se pueda mostrar.
        wait = dialogs.SigningWaitDialog(self, store, certstore.NAME)
        if store and isinstance(signer, signing.WindowsStoreSigner) and sys.platform.startswith("win"):
            signer.hwnd = int(wait.winId())
        bridge = _SignBridge()
        state = {"result": None, "error": None, "abandoned": False}

        def work():
            try:
                res = signing.perform_signature(prep, signer)
                bridge.done.emit(res)
            except Exception as e:  # noqa
                bridge.failed.emit(str(e) or e.__class__.__name__)
            finally:
                prep.cleanup()

        def on_done(res):
            if state["abandoned"]:
                log.warning("La firma terminó después de dejar de esperar; no se guarda.")
                return
            state["result"] = res
            wait.finish()

        def on_fail(msg):
            if state["abandoned"]:
                return
            state["error"] = msg
            wait.finish()

        ticks = [0]

        def tick():
            ticks[0] += 1
            if store:
                wait.set_waiting_pin(certstore.bring_prompt_to_front())
            if ticks[0] == 25:
                wait.allow_abandon()
                log.warning("La firma lleva %d s esperando", ticks[0])

        def on_abandon():
            state["abandoned"] = True
            log.warning("El usuario ha dejado de esperar la firma")

        bridge.done.connect(on_done)
        bridge.failed.connect(on_fail)
        wait.showPrompt.connect(lambda: wait.set_waiting_pin(certstore.bring_prompt_to_front(force=True)))
        wait.abandoned.connect(on_abandon)
        timer = QTimer(self)
        timer.setInterval(1000)
        timer.timeout.connect(tick)
        self._sign_job = (bridge, timer)          # mantener referencias
        threading.Thread(target=work, daemon=True, name="NovoPDF-firma").start()
        timer.start()
        wait.exec()
        timer.stop()
        self._sign_job = None

        if state["abandoned"]:
            dialogs.warn(self, "Firma interrumpida",
                         "Se ha dejado de esperar y no se ha guardado nada.\n\n"
                         "Si sigue abierta una ventana pidiendo el PIN, ciérrala. Si usas una tarjeta o el "
                         "DNIe, sácala y vuelve a insertarla antes de intentarlo de nuevo.")
            self.set_tool(T_SELECT)
            return
        if state["error"] is not None:
            log.warning("Firma fallida: %s", state["error"])
            dialogs.error(self, "No se pudo firmar", state["error"])
            return
        try:
            from ..core.document import write_atomic
            write_atomic(out, state["result"])
        except OSError as e:
            log.warning("No se pudo guardar el documento firmado: %s", e)
            dialogs.error(self, "No se pudo guardar",
                          f"El documento se ha firmado pero no se ha podido guardar en:\n{out}\n\n{e}\n\n"
                          "Comprueba que no esté abierto en otro programa y que puedes escribir en esa carpeta.")
            return
        log.info("Documento firmado y guardado")
        self.set_tool(T_SELECT)
        # abrir el documento firmado
        prot = self.pdf.protection
        try:
            new = PdfDocument.open(out, (prot.owner_pw or prot.user_pw) if prot.enabled else None)
        except Exception:
            new = None
        if new:
            new.modified = False
            self._add_recent(out)
            keep = page_index
            self._replace_document(new)
            QTimer.singleShot(80, lambda: self.viewer.go_to(keep))
        dialogs.info(self, "Documento firmado", f"El documento se ha firmado y guardado como:\n{out}")

    # ================================================================== programa predeterminado
    def _refresh_default_offer(self):
        from ..core import fileassoc
        show = False
        try:
            if fileassoc.supported():
                st = fileassoc.is_default()
                if fileassoc.IS_MAC:
                    show = st is False or (st is None and not self.settings.value("assoc/mac_done", False, type=bool))
                else:
                    show = st is False
        except Exception:
            show = False
        self.welcome.set_default_offer(show)

    def make_default_app(self):
        from ..core import fileassoc
        if fileassoc.IS_MAC:
            dialogs.info(self, "Abrir los PDF con NovoPDF",
                         "Para que los PDF se abran siempre con NovoPDF:\n\n" + fileassoc.MAC_STEPS)
            self.settings.setValue("assoc/mac_done", True)
            self._refresh_default_offer()
            return
        if not fileassoc.supported():
            dialogs.info(self, "Abrir los PDF con NovoPDF",
                         "Esta opción solo está disponible en la versión portable para Windows.")
            return
        if fileassoc.is_default():
            dialogs.info(self, "Abrir los PDF con NovoPDF", "NovoPDF ya es el programa con el que se abren los PDF.")
            self._refresh_default_offer()
            return
        try:
            fileassoc.register()
        except Exception as e:
            logging.getLogger("novopdf.asociacion").warning("Registro fallido: %s", e)
            dialogs.error(self, "Abrir los PDF con NovoPDF", f"No se pudo registrar NovoPDF:\n{e}")
            return
        if not dialogs.confirm(self, "Abrir los PDF con NovoPDF",
                               "Ahora se abrirá una ventana de Windows.\n\n"
                               "Elige «NovoPDF» en la lista y pulsa «Siempre» "
                               "(o marca «Usar siempre esta aplicación» y pulsa «Aceptar»).",
                               "Continuar", "Cancelar"):
            return
        sample = self.pdf.path if self.pdf and self.pdf.path and self.pdf.path.lower().endswith(".pdf") else None
        ok = False
        try:
            ok = fileassoc.show_system_chooser(int(self.winId()), sample)
        except Exception as e:
            logging.getLogger("novopdf.asociacion").warning("Ventana «Abrir con» fallida: %s", e)
        if fileassoc.is_default():
            dialogs.info(self, "Abrir los PDF con NovoPDF",
                         "Listo. A partir de ahora, al hacer doble clic en un PDF se abrirá con NovoPDF.\n\n"
                         "Si mueves la carpeta de NovoPDF a otro sitio, NovoPDF actualizará la asociación "
                         "la próxima vez que lo abras.")
        else:
            box = QMessageBox(QMessageBox.Information, "Abrir los PDF con NovoPDF",
                              ("No se ha cambiado el programa predeterminado.\n\n" if ok else "") +
                              "También puedes hacerlo desde Configuración de Windows > Aplicaciones > "
                              "Aplicaciones predeterminadas: busca «.pdf» y elige NovoPDF.", parent=self)
            settings_btn = box.addButton("Abrir Configuración", QMessageBox.AcceptRole)
            box.addButton("Cerrar", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is settings_btn:
                fileassoc.open_default_apps_settings()
        self._refresh_default_offer()

    def verify(self):
        if not self.pdf:
            return
        from ..core import signing
        if self.pdf.modified or self.pdf.source_bytes is None:
            if not self.pdf.has_signatures():
                dialogs.info(self, "Firmas", "Este documento no contiene firmas digitales.")
                return
            dialogs.warn(self, "Firmas", "El documento tiene cambios sin guardar. Se comprobarán las firmas del archivo original.")
        data = self.pdf.source_bytes
        if not data:
            dialogs.info(self, "Firmas", "Este documento no contiene firmas digitales.")
            return
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            reps = signing.verify_pdf(data, self.pdf.source_password)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            dialogs.error(self, "Firmas", f"No se pudieron comprobar las firmas:\n{e}")
            return
        QApplication.restoreOverrideCursor()
        if not reps:
            dialogs.info(self, "Firmas", "Este documento no contiene firmas digitales.")
            return
        dialogs.SignaturesDialog(self, reps).exec()

    # ================================================================== otros
    def show_help(self):
        d = dialogs.Dialog(self, "Ayuda rápida", f"NovoPDF {__version__}", "help", ok_text="Entendido",
                           cancel_text="", width=560)
        txt = QLabel(
            "<p><b>Inicio</b>: abrir, crear, guardar, imprimir, exportar (a Word, a Excel o como imágenes "
            "PNG, JPEG, TIFF, BMP, GIF, WebP o SVG), proteger con contraseña y buscar texto.</p>"
            "<p><b>Exportar a Word</b> crea un documento editable con sus fuentes, negritas, viñetas, tablas, "
            "imágenes y resaltados. <b>Exportar a Excel</b> pasa las tablas a celdas, con los importes, "
            "porcentajes y fechas como números y fechas.</p>"
            "<p><b>Imprimir</b> (Ctrl+P): elige impresora, páginas (todas, la actual, las seleccionadas, "
            "un intervalo, solo pares o impares), copias, doble cara y color; la vista previa muestra "
            "cómo quedará cada hoja. También puedes imprimir páginas sueltas con el botón derecho "
            "sobre las miniaturas.</p>"
            "<p><b>Pestañas</b>: cada documento se abre en su pestaña (un mismo archivo solo se abre una "
            "vez). Arrastra una pestaña fuera de la barra para llevar el documento a una ventana nueva, "
            "o suéltala sobre otra ventana de NovoPDF para pasarlo a ella; con el botón derecho sobre "
            "la pestaña tienes más opciones.</p>"
            "<p><b>Páginas</b>: selecciona miniaturas a la izquierda (Ctrl/Mayús para varias) para "
            "extraer, eliminar, duplicar, girar o mover. Arrástralas para reordenar.</p>"
            "<p><b>Editar</b>: elige una herramienta y sigue las indicaciones de la barra de ayuda. "
            "Al editar un párrafo solo cambian las palabras que modifiques: cada una conserva su fuente, "
            "tamaño, negrita o cursiva, y el resto del párrafo y de la página no se mueve.</p>"
            "<p><b>Resaltar, subrayar y tachar</b> (en Editar): arrastra sobre el texto, o selecciónalo y "
            "pulsa el botón. Con clic derecho sobre una marca puedes quitarla o cambiar su color.</p>"
            "<p><b>Formularios</b>: haz clic en un campo para rellenarlo; Tab pasa al siguiente y Mayús+Tab al "
            "anterior. Las casillas y opciones se marcan con un clic o con la barra espaciadora. Los campos "
            "obligatorios sin rellenar se ven en rojo. En la pestaña <b>Formulario</b> puedes vaciarlo, exportar "
            "los datos a Excel (también de muchos formularios a la vez), <b>detectar campos</b> automáticamente "
            "en un impreso sin formulario (rayas, recuadros, tablas y casillas), añadir campos de texto, casillas, "
            "opciones, desplegables, listas y firmas, cambiarlos con <b>Editar campos</b> y <b>aplanar</b> el "
            "formulario para que quede fijo.</p>"
            "<p><b>Firmar</b>: dibuja un recuadro en la página y elige tu certificado (instalado en el sistema "
            "o archivo .pfx/.p12). En un formulario, haz clic en su campo de firma.</p>"
            "<p><b>Escanear</b>: crea un PDF directamente desde el escáner (cristal o alimentador, "
            "a una o doble cara), quita las páginas en blanco y reconoce el texto. En «Páginas» puedes "
            "añadir páginas escaneadas al documento abierto.</p>"
            "<p><b>Reconocer texto</b>: hace que los documentos escaneados se puedan buscar y copiar.</p>"
            "<p>Todo se puede deshacer con <b>Ctrl+Z</b>. Los cambios no se guardan en el archivo hasta "
            "que pulsas <b>Guardar</b>.</p>"
            "<p style='color:#6b7385'>Atajos: Ctrl+O abrir · Ctrl+S guardar · Ctrl+P imprimir · Ctrl+F buscar · "
            "Ctrl+Tab cambiar de pestaña · Ctrl+W cerrar la pestaña · "
            "Ctrl+rueda zoom · Supr eliminar imagen o campo seleccionado · Tab siguiente campo.</p>")
        txt.setText(theme.keys(txt.text()))
        txt.setWordWrap(True)
        d.body.addWidget(txt)
        from ..core import fileassoc
        if fileassoc.supported():
            b = QPushButton(icons.icon("check", color=theme.ACCENT), " Abrir siempre los PDF con NovoPDF")
            b.setObjectName("Link")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda: (d.accept(), QTimer.singleShot(0, self.make_default_app)))
            d.body.addWidget(b)
        ab = QPushButton(icons.icon("info", color=theme.ACCENT), " Acerca de NovoPDF (licencia y código fuente)")
        ab.setObjectName("Link")
        ab.setCursor(Qt.PointingHandCursor)
        ab.clicked.connect(lambda: (d.accept(), QTimer.singleShot(0, self.show_about)))
        d.body.addWidget(ab)
        d.exec()

    def show_about(self):
        dialogs.AboutDialog(self).exec()

    def dragEnterEvent(self, e):
        from .doctabs import MIME, DragState
        if e.mimeData().hasFormat(MIME) and DragState.window is not None and DragState.window is not self:
            e.acceptProposedAction()
        elif e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        from .doctabs import MIME, receive_tab
        if e.mimeData().hasFormat(MIME):
            if receive_tab(self):
                e.acceptProposedAction()
            return
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        paths = [p for p in paths if os.path.splitext(p)[1].lower() in (".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp")]
        if not paths:
            return
        if self.pdf:
            many = len(paths) > 1
            box = QMessageBox(QMessageBox.Question, "Archivo arrastrado",
                              f"¿Qué quieres hacer con {len(paths)} archivos?" if many else
                              f"¿Qué quieres hacer con «{os.path.basename(paths[0])}»?", parent=self)
            o = box.addButton("Abrirlos en pestañas nuevas" if many else "Abrirlo en una pestaña nueva",
                              QMessageBox.AcceptRole)
            ins = box.addButton("Añadirlos al final de este documento" if many else
                                "Añadirlo al final de este documento", QMessageBox.ActionRole)
            box.addButton("Cancelar", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is ins:
                for p in paths:
                    self.insert_file(self.pdf.page_count, p)
                return
            if box.clickedButton() is not o:
                return
        self.open_files(paths)

    def closeEvent(self, e):
        self._commit_form()
        # cada documento con cambios sin guardar: se muestra y se pregunta
        for k in range(len(self.docs)):
            if self.docs[k].pdf.modified:
                self._switch_tab(k)
                if not self._confirm_close():
                    e.ignore()
                    return
        for d in self.docs:
            try:
                d.pdf.doc.close()
            except Exception:
                pass
        if self in MainWindow.windows:
            MainWindow.windows.remove(self)
        if MainWindow.last_active is self:
            MainWindow.last_active = MainWindow.windows[-1] if MainWindow.windows else None
        self.docs = []
        self.pdf = None
        self.settings.setValue("window/geometry", self.saveGeometry())
        e.accept()
        if MainWindow.windows:
            # quedan otras ventanas: liberar esta (se mantiene la referencia hasta borrarla)
            MainWindow._closed.append(self)
            self.deleteLater()
