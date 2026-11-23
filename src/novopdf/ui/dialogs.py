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

"""Cuadros de diálogo."""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QColorDialog, QComboBox,
                               QDialog, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame,
                               QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
                               QRadioButton, QSpinBox, QStackedWidget, QToolButton, QVBoxLayout,
                               QWidget)

from ..core import editing, ocr
from ..core.document import Protection
from . import icons, theme


class Dialog(QDialog):
    """Diálogo base: título grande, explicación y botones abajo."""

    def __init__(self, parent, title: str, subtitle: str = "", icon_name: str | None = None,
                 ok_text: str = "Aceptar", cancel_text: str = "Cancelar", width: int = 460):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(width)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 20, 22, 18)
        outer.setSpacing(12)
        head = QHBoxLayout()
        head.setSpacing(12)
        if icon_name:
            ic = QLabel()
            ic.setPixmap(icons.pixmap(icon_name, 30, theme.ACCENT))
            ic.setAlignment(Qt.AlignTop)
            head.addWidget(ic)
        tl = QVBoxLayout()
        tl.setSpacing(3)
        t = QLabel(title)
        t.setStyleSheet("font-size: 13pt; font-weight: 700;")
        tl.addWidget(t)
        if subtitle:
            s = QLabel(subtitle)
            s.setWordWrap(True)
            s.setObjectName("Muted")
            tl.addWidget(s)
        head.addLayout(tl, 1)
        outer.addLayout(head)
        self.body = QVBoxLayout()
        self.body.setSpacing(10)
        outer.addLayout(self.body)
        self.error = QLabel()
        self.error.setStyleSheet(f"color: {theme.DANGER};")
        self.error.setWordWrap(True)
        self.error.hide()
        outer.addWidget(self.error)
        btns = QHBoxLayout()
        btns.addStretch(1)
        self.cancel_btn = QPushButton(cancel_text)
        self.cancel_btn.clicked.connect(self.reject)
        self.ok_btn = QPushButton(ok_text)
        self.ok_btn.setObjectName("Primary")
        self.ok_btn.setDefault(True)
        self.ok_btn.clicked.connect(self._try_accept)
        if cancel_text:
            btns.addWidget(self.cancel_btn)
        btns.addWidget(self.ok_btn)
        outer.addLayout(btns)

    def show_error(self, text: str):
        self.error.setText(text)
        self.error.setVisible(bool(text))

    def validate(self) -> bool:
        return True

    def _try_accept(self):
        self.show_error("")
        if self.validate():
            self.accept()


def password_field(placeholder="") -> tuple[QWidget, QLineEdit]:
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(4)
    e = QLineEdit()
    e.setEchoMode(QLineEdit.Password)
    e.setPlaceholderText(placeholder)
    b = QToolButton()
    b.setIcon(icons.icon("eye"))
    b.setCheckable(True)
    b.setToolTip("Mostrar u ocultar la contraseña")
    b.setStyleSheet("border:none; padding:4px;")
    b.toggled.connect(lambda on: e.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password))
    h.addWidget(e, 1)
    h.addWidget(b)
    return w, e


# ---------------------------------------------------------------- mensajes
class SigningWaitDialog(Dialog):
    """Espera mientras se firma (en segundo plano). No se puede cerrar hasta que termina,
    salvo con «Dejar de esperar» pasado un tiempo."""
    showPrompt = Signal()
    abandoned = Signal()

    def __init__(self, parent, store: bool, store_name: str):
        if store:
            sub = ("Si tu certificado está protegido o en una tarjeta, el sistema te pedirá el PIN "
                   "o la contraseña en una ventana aparte.")
        else:
            sub = "Un momento, por favor."
        super().__init__(parent, "Firmando el documento…", sub, "sign",
                         ok_text="Mostrar la ventana del PIN", cancel_text="Dejar de esperar", width=520)
        self.setWindowFlag(Qt.WindowCloseButtonHint, False)
        self._can_close = False
        self._finished = False
        bar = QProgressBar()
        bar.setRange(0, 0)
        bar.setTextVisible(False)
        bar.setFixedHeight(8)
        self.body.addWidget(bar)
        self.status = QLabel("Preparando la firma…" if store else "Firmando…")
        self.status.setWordWrap(True)
        self.body.addWidget(self.status)
        self.extra = QLabel("Si usas una tarjeta o el DNIe, comprueba que está bien insertada en el lector. "
                            "Si no aparece ninguna petición de PIN, puedes dejar de esperar e intentarlo de nuevo.")
        self.extra.setWordWrap(True)
        self.extra.setObjectName("Muted")
        self.extra.hide()
        self.body.addWidget(self.extra)
        self.ok_btn.setVisible(store)
        self.ok_btn.setDefault(False)
        self.ok_btn.setObjectName("")
        self.cancel_btn.hide()
        self._store_name = store_name

    def _set_status(self, text: str):
        if self.status.text() != text:
            self.status.setText(text)
            self.adjustSize()

    def set_waiting_pin(self, visible_prompt: bool):
        if visible_prompt:
            self._set_status("Escribe el PIN o la contraseña en la ventana del sistema. "
                             "Si no la ves, pulsa «Mostrar la ventana del PIN».")
        else:
            self._set_status(f"Esperando al {self._store_name}… Si se ha abierto una ventana "
                             "pidiendo el PIN y no la ves, pulsa Alt+Tab o búscala en la barra de tareas.")

    def allow_abandon(self):
        self._can_close = True
        self.cancel_btn.show()
        self.extra.show()
        self.adjustSize()

    def _try_accept(self):
        self.showPrompt.emit()

    def reject(self):
        if self._finished:
            return super().reject()
        if not self._can_close:
            return
        self._finished = True
        self.abandoned.emit()
        super().reject()

    def finish(self):
        self._finished = True
        self.done(1)


def info(parent, title, text):
    QMessageBox.information(parent, title, text)


def warn(parent, title, text):
    QMessageBox.warning(parent, title, text)


def error(parent, title, text):
    QMessageBox.critical(parent, title, text)


def confirm(parent, title, text, yes="Sí", no="No") -> bool:
    box = QMessageBox(QMessageBox.Question, title, text, parent=parent)
    y = box.addButton(yes, QMessageBox.YesRole)
    box.addButton(no, QMessageBox.NoRole)
    box.setDefaultButton(y)
    box.exec()
    return box.clickedButton() is y


def ask_save_changes(parent, name) -> str:
    """Devuelve 'save', 'discard' o 'cancel'."""
    box = QMessageBox(QMessageBox.Question, "Cambios sin guardar",
                      f"«{name}» tiene cambios sin guardar.\n¿Quieres guardarlos?", parent=parent)
    s = box.addButton("Guardar", QMessageBox.AcceptRole)
    d = box.addButton("No guardar", QMessageBox.DestructiveRole)
    box.addButton("Cancelar", QMessageBox.RejectRole)
    box.setDefaultButton(s)
    box.exec()
    c = box.clickedButton()
    return "save" if c is s else "discard" if c is d else "cancel"


# ---------------------------------------------------------------- contraseña al abrir
class PasswordDialog(Dialog):
    def __init__(self, parent, filename: str, wrong: bool = False):
        super().__init__(parent, "Documento protegido",
                         f"«{filename}» está protegido con contraseña. Escríbela para abrirlo.",
                         "lock", ok_text="Abrir")
        w, self.edit = password_field("Contraseña")
        self.body.addWidget(w)
        if wrong:
            self.show_error("La contraseña no es correcta. Inténtalo de nuevo.")
        self.edit.setFocus()

    @property
    def password(self) -> str:
        return self.edit.text()


def ask_password(parent, filename, wrong=False) -> str | None:
    d = PasswordDialog(parent, filename, wrong)
    return d.password if d.exec() == QDialog.Accepted else None


# ---------------------------------------------------------------- proteger
class ProtectDialog(Dialog):
    def __init__(self, parent, prot: Protection):
        super().__init__(parent, "Proteger con contraseña",
                         "La protección se aplica al guardar el documento (cifrado AES de 256 bits).",
                         "lock", ok_text="Aplicar")
        self.result_prot = None
        self.open_chk = QCheckBox("Pedir una contraseña para abrir el documento")
        self.open_chk.setChecked(bool(prot.user_pw) if prot.enabled else True)
        self.body.addWidget(self.open_chk)
        g = QGridLayout()
        g.setContentsMargins(24, 0, 0, 0)
        w1, self.pw1 = password_field("Contraseña")
        w2, self.pw2 = password_field("Repite la contraseña")
        self.pw1.setText(prot.user_pw)
        self.pw2.setText(prot.user_pw)
        g.addWidget(w1, 0, 0)
        g.addWidget(w2, 1, 0)
        self.body.addLayout(g)
        self.open_box = [w1, w2]

        self.perm_chk = QCheckBox("Limitar lo que se puede hacer con el documento")
        restricted = prot.enabled and not (prot.allow_print and prot.allow_copy and prot.allow_modify)
        self.perm_chk.setChecked(restricted)
        self.body.addWidget(self.perm_chk)
        pw = QWidget()
        pl = QVBoxLayout(pw)
        pl.setContentsMargins(24, 0, 0, 0)
        self.c_print = QCheckBox("Permitir imprimir")
        self.c_copy = QCheckBox("Permitir copiar texto e imágenes")
        self.c_mod = QCheckBox("Permitir modificar el documento")
        self.c_ann = QCheckBox("Permitir comentarios y rellenar formularios")
        for c, v in ((self.c_print, prot.allow_print), (self.c_copy, prot.allow_copy),
                     (self.c_mod, prot.allow_modify), (self.c_ann, prot.allow_annotate)):
            c.setChecked(v)
            pl.addWidget(c)
        lbl = QLabel("Contraseña para cambiar estos permisos:")
        lbl.setObjectName("Muted")
        pl.addWidget(lbl)
        w3, self.owner = password_field("Contraseña de permisos")
        self.owner.setText(prot.owner_pw if prot.owner_pw != prot.user_pw else "")
        pl.addWidget(w3)
        self.body.addWidget(pw)
        self.perm_box = pw

        self.remove_btn = QPushButton("Quitar toda la protección")
        self.remove_btn.setObjectName("Link")
        self.remove_btn.clicked.connect(self._remove)
        self.remove_btn.setVisible(prot.enabled)
        self.body.addWidget(self.remove_btn)
        self.open_chk.toggled.connect(self._sync)
        self.perm_chk.toggled.connect(self._sync)
        self._sync()

    def _sync(self):
        for w in self.open_box:
            w.setEnabled(self.open_chk.isChecked())
        self.perm_box.setEnabled(self.perm_chk.isChecked())

    def _remove(self):
        self.result_prot = Protection()
        self.accept()

    def validate(self) -> bool:
        if not self.open_chk.isChecked() and not self.perm_chk.isChecked():
            self.result_prot = Protection()
            return True
        user = ""
        if self.open_chk.isChecked():
            if len(self.pw1.text()) < 4:
                self.show_error("La contraseña debe tener al menos 4 caracteres.")
                return False
            if self.pw1.text() != self.pw2.text():
                self.show_error("Las dos contraseñas no coinciden.")
                return False
            user = self.pw1.text()
        owner = ""
        p = Protection(enabled=True, user_pw=user)
        if self.perm_chk.isChecked():
            owner = self.owner.text()
            if len(owner) < 4:
                self.show_error("Escribe una contraseña de permisos de al menos 4 caracteres.")
                return False
            if owner == user:
                self.show_error("La contraseña de permisos debe ser distinta de la de apertura.")
                return False
            p.allow_print = self.c_print.isChecked()
            p.allow_copy = self.c_copy.isChecked()
            p.allow_modify = self.c_mod.isChecked()
            p.allow_annotate = self.c_ann.isChecked()
        p.owner_pw = owner
        self.result_prot = p
        return True


# ---------------------------------------------------------------- texto
class ColorButton(QPushButton):
    changed = Signal()

    def __init__(self, rgb=(0, 0, 0)):
        super().__init__()
        self.setFixedWidth(46)
        self.set_rgb(rgb)
        self.clicked.connect(self._pick)
        self.setToolTip("Color del texto")

    def set_rgb(self, rgb):
        self.rgb = tuple(rgb)
        c = QColor.fromRgbF(*self.rgb)
        self.setStyleSheet(f"QPushButton {{ background: {c.name()}; border: 2px solid white; "
                           f"border-radius: 7px; outline: 1px solid #d0d5df; min-height: 22px; }}")

    def _pick(self):
        c = QColorDialog.getColor(QColor.fromRgbF(*self.rgb), self, "Color del texto")
        if c.isValid():
            self.set_rgb((c.redF(), c.greenF(), c.blueF()))
            self.changed.emit()


class TextDialog(Dialog):
    """Escribir o modificar texto.

    resolver(text, bold, italic) -> FontChoice  : elección automática (editar párrafo)
    families: familias instaladas para elegir a mano.
    """

    AUTO = "__auto__"

    def __init__(self, parent, title, subtitle, text="", fontsize=12.0, color=(0, 0, 0),
                 family=None, bold=False, italic=False, show_align=False, resolver=None,
                 families=(), original_name="", scanned=False):
        super().__init__(parent, title, subtitle, "text_edit", ok_text="Aplicar", width=640)
        from ..core import fonts as _fonts
        self._fonts = _fonts
        self.resolver = resolver
        self.edit = QPlainTextEdit(text)
        self.edit.setMinimumHeight(140)
        self.body.addWidget(self.edit)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.family = QComboBox()
        self.family.setMinimumWidth(210)
        self.family.setToolTip("Tipo de letra")
        if resolver is not None:
            orig = f" ({original_name})" if original_name else ""
            self.family.addItem(f"La misma que el original{orig}", self.AUTO)
            self.family.insertSeparator(1)
        fams = list(families) or ["Helvetica", "Times", "Courier"]
        for f in fams:
            self.family.addItem(f, f)
        if resolver is None:
            idx = self.family.findData(family) if family else -1
            self.family.setCurrentIndex(max(0, idx))
        self.size = QDoubleSpinBox()
        self.size.setRange(4, 96)
        self.size.setDecimals(1)
        self.size.setSingleStep(0.5)
        self.size.setValue(fontsize)
        self.size.setSuffix(" pt")
        self.size.setMinimumWidth(90)
        self.bold = QToolButton()
        self.bold.setText("N")
        self.bold.setCheckable(True)
        self.bold.setChecked(bold)
        self.bold.setToolTip("Negrita")
        self.bold.setStyleSheet("QToolButton{font-weight:800; padding:5px 10px; border:1px solid #e1e5ee; border-radius:6px;} QToolButton:checked{background:#e8eefc; color:#2f5bd8;}")
        self.italic = QToolButton()
        self.italic.setText("K")
        self.italic.setCheckable(True)
        self.italic.setChecked(italic)
        self.italic.setToolTip("Cursiva")
        self.italic.setStyleSheet("QToolButton{font-style:italic; padding:5px 11px; border:1px solid #e1e5ee; border-radius:6px;} QToolButton:checked{background:#e8eefc; color:#2f5bd8;}")
        self.color = ColorButton(color)
        self._orig_size, self._orig_color = fontsize, tuple(color)
        frow = QHBoxLayout()
        frow.setSpacing(8)
        flab = QLabel("Fuente:")
        frow.addWidget(flab)
        frow.addWidget(self.family, 1)
        self.body.addLayout(frow)
        self.font_note = QLabel()
        self.font_note.setObjectName("Muted")
        self.font_note.setWordWrap(True)
        self.font_note.setContentsMargins(52, 0, 0, 4)
        self.body.addWidget(self.font_note)
        row.addWidget(QLabel("Tamaño:"))
        row.addWidget(self.size)
        row.addWidget(self.bold)
        row.addWidget(self.italic)
        row.addWidget(self.color)
        self.align = QComboBox()
        if show_align:
            self.align.addItem("Alineación original", -1)
        for k, lab in enumerate(("Izquierda", "Centro", "Derecha", "Justificado")):
            self.align.addItem(lab, k)
        if show_align:
            row.addWidget(self.align)
        row.addStretch(1)
        self.body.addLayout(row)
        self._choice = None
        self._orig_style = (bold, italic) if resolver is not None else None
        from PySide6.QtCore import QTimer
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._update_choice)
        self.edit.textChanged.connect(self._timer.start)
        self.family.currentIndexChanged.connect(lambda _: self._update_choice())
        self.bold.toggled.connect(lambda _: self._update_choice())
        self.italic.toggled.connect(lambda _: self._update_choice())
        self.size.valueChanged.connect(lambda _: self._update_choice())
        self.color.changed.connect(self._update_choice)
        self.align.currentIndexChanged.connect(lambda _: self._update_choice())
        self.scanned = scanned
        if scanned:
            for wdg in (self.family, self.size, self.bold, self.italic, self.color, self.align, flab):
                wdg.setEnabled(False)
                wdg.setToolTip("En un documento escaneado se imita la letra de la imagen")
        self._update_choice()
        self.edit.setFocus()
        cur = self.edit.textCursor()
        cur.movePosition(cur.MoveOperation.End)
        self.edit.setTextCursor(cur)

    def _compute_choice(self):
        text = self.edit.toPlainText()
        b, i = self.bold.isChecked(), self.italic.isChecked()
        data = self.family.currentData()
        if data == self.AUTO and self.resolver is not None:
            return self.resolver(text, b, i)
        ch = self._fonts.choice_for_family(data or "Helvetica", b, i)
        if ch is None:
            ch = self._fonts.FontChoice(label="Helvetica (estándar PDF)", kind="standard",
                                        family="Helvetica", base14=self._fonts.BASE14[("sans", b, i)])
        if not ch.covers(text):
            # la fuente elegida no tiene algún carácter: usar una estándar del mismo estilo
            ch = self._fonts.FontChoice(label=f"Helvetica (estándar PDF; «{ch.family}» no tiene todos los caracteres)",
                                        kind="standard", family="Helvetica",
                                        base14=self._fonts.BASE14[("sans", b, i)])
        return ch

    def _update_choice(self):
        if getattr(self, "scanned", False):
            self.font_note.setText("Documento escaneado: las palabras que cambies se taparán y se escribirán "
                                   "de nuevo imitando la letra, el tamaño y el color de la imagen. "
                                   "El texto que ves aquí es el reconocido (OCR) y puede tener errores.")
            try:
                self._choice = self._compute_choice()
            except Exception:
                self._choice = None
            return
        try:
            self._choice = self._compute_choice()
            icons_ok = {"embedded": "✔", "system": "✔", "similar": "≈", "standard": "≈"}
            if self.keeps_original_style():
                self.font_note.setText("Cada palabra conserva su fuente, tamaño y estilo; solo se cambian las "
                                       f"palabras que edites. Palabras nuevas: {icons_ok.get(self._choice.kind, '')} "
                                       f"{self._choice.label}")
            else:
                self.font_note.setText(f"Se usará: {icons_ok.get(self._choice.kind, '')} {self._choice.label}"
                                       + (" · Se volverá a escribir todo el párrafo con este formato."
                                          if self._orig_style is not None else ""))
        except Exception as e:  # noqa
            self._choice = None
            self.font_note.setText("")

    def keeps_original_style(self) -> bool:
        """Edición de un párrafo sin tocar el formato: se conserva el de cada palabra."""
        if self._orig_style is None:
            return False
        if getattr(self, "scanned", False):
            return True
        return (self.family.currentData() == self.AUTO
                and (self.bold.isChecked(), self.italic.isChecked()) == self._orig_style
                and abs(self.size.value() - self._orig_size) < 0.01 and self.color.rgb == self._orig_color
                and self.align.currentData() == -1)

    def validate(self):
        self._timer.stop()
        self._update_choice()
        return True

    def values(self) -> dict:
        return dict(text=self.edit.toPlainText(), fontsize=self.size.value(), color=self.color.rgb,
                    family=self.family.currentData(), bold=self.bold.isChecked(),
                    italic=self.italic.isChecked(), align=self.align.currentData(),
                    keep_style=self.keeps_original_style(),
                    choice=self._choice or self._compute_choice())


# ---------------------------------------------------------------- exportar a imagen
class ExportDialog(Dialog):
    def __init__(self, parent, page_count, current, selected, folder, base, settings):
        super().__init__(parent, "Exportar como imagen",
                         "Guarda las páginas del documento como archivos de imagen.", "export_img",
                         ok_text="Exportar", width=600)
        from ..core import export
        self.export = export
        self.settings = settings
        self._pc, self._cur, self._sel = page_count, current, selected
        f = QFormLayout()
        f.setLabelAlignment(Qt.AlignRight)
        f.setVerticalSpacing(9)
        self.fmt = QComboBox()
        for ext, name, desc in export.FORMATS:
            self.fmt.addItem(f"{name}  (.{ext})", ext)
        self.fmt.setCurrentIndex(max(0, self.fmt.findData(settings.value("export/fmt", "png"))))
        f.addRow("Formato:", self.fmt)
        self.fmt_desc = QLabel()
        self.fmt_desc.setObjectName("Muted")
        self.fmt_desc.setWordWrap(True)
        f.addRow("", self.fmt_desc)

        pw = QWidget()
        pl = QVBoxLayout(pw)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(4)
        self.r_all = QRadioButton(f"Todas ({page_count})")
        self.r_cur = QRadioButton(f"Página actual ({current + 1})")
        self.r_sel = QRadioButton(f"Seleccionadas en el panel ({len(selected)})")
        self.r_sel.setEnabled(len(selected) > 1)
        rr = QHBoxLayout()
        self.r_rng = QRadioButton("Intervalo:")
        self.rng = QLineEdit()
        self.rng.setPlaceholderText("p. ej. 1-3, 5, 8")
        self.rng.textEdited.connect(lambda _: self.r_rng.setChecked(True))
        rr.addWidget(self.r_rng)
        rr.addWidget(self.rng, 1)
        (self.r_sel if len(selected) > 1 else self.r_all).setChecked(True)
        for r in (self.r_all, self.r_cur, self.r_sel):
            pl.addWidget(r)
        pl.addLayout(rr)
        f.addRow("Páginas:", pw)

        self.dpi = QComboBox()
        for v, lab in ((72, "72 ppp - pantalla"), (150, "150 ppp - uso normal"),
                       (300, "300 ppp - impresión (recomendado)"), (600, "600 ppp - máxima calidad")):
            self.dpi.addItem(lab, v)
        self.dpi.setCurrentIndex(max(0, self.dpi.findData(int(settings.value("export/dpi", 300)))))
        self.dpi_label = QLabel("Resolución:")
        f.addRow(self.dpi_label, self.dpi)
        self.mode = QComboBox()
        for k, lab in export.COLOR_MODES:
            self.mode.addItem(lab, k)
        self.mode.setCurrentIndex(max(0, self.mode.findData(settings.value("export/mode", "color"))))
        self.mode_label = QLabel("Color:")
        f.addRow(self.mode_label, self.mode)
        self.quality = QSpinBox()
        self.quality.setRange(30, 100)
        self.quality.setValue(int(settings.value("export/quality", 90)))
        self.quality.setSuffix(" %")
        self.quality_label = QLabel("Calidad:")
        f.addRow(self.quality_label, self.quality)
        self.multi = QCheckBox("Todas las páginas en un único archivo TIFF")
        self.multi.setChecked(settings.value("export/multi", "true") in (True, "true"))
        f.addRow("", self.multi)

        drow = QHBoxLayout()
        self.folder = QLineEdit(folder)
        b = QPushButton(icons.icon("folder"), " Cambiar…")
        b.clicked.connect(self._browse)
        drow.addWidget(self.folder, 1)
        drow.addWidget(b)
        f.addRow("Carpeta:", drow)
        self.base = QLineEdit(base)
        f.addRow("Nombre:", self.base)
        self.preview = QLabel()
        self.preview.setObjectName("Muted")
        self.preview.setWordWrap(True)
        f.addRow("", self.preview)
        self.body.addLayout(f)

        for w in (self.fmt, self.dpi, self.mode):
            w.currentIndexChanged.connect(lambda _: self._sync())
        for w in (self.r_all, self.r_cur, self.r_sel, self.r_rng, self.multi):
            w.toggled.connect(lambda _: self._sync())
        self.rng.textChanged.connect(lambda _: self._sync())
        self.base.textChanged.connect(lambda _: self._sync())
        self._sync()

    def _browse(self):
        p = QFileDialog.getExistingDirectory(self, "Carpeta de destino", self.folder.text())
        if p:
            self.folder.setText(p)

    def pages(self):
        if self.r_cur.isChecked():
            return [self._cur]
        if self.r_sel.isChecked():
            return list(self._sel)
        if self.r_rng.isChecked():
            return self.export.parse_range(self.rng.text(), self._pc)
        return list(range(self._pc))

    def _sync(self):
        fmt = self.fmt.currentData()
        desc = next(d for e, _, d in self.export.FORMATS if e == fmt)
        self.fmt_desc.setText(desc)
        raster = fmt != "svg"
        for w in (self.dpi, self.dpi_label, self.mode, self.mode_label):
            w.setVisible(raster)
        q = fmt in ("jpg", "webp")
        self.quality.setVisible(q)
        self.quality_label.setVisible(q)
        self.multi.setVisible(fmt == "tif")
        try:
            pages = self.pages()
            files = self.export.planned_files(self.folder.text(), self.base.text() or "pagina", fmt, pages,
                                              self._pc, self.multi.isChecked())
            names = os.path.basename(files[0]) + (f" … {os.path.basename(files[-1])}" if len(files) > 1 else "")
            txt = f"Se crearán {len(files)} archivo(s): {names}"
            if raster:
                dpi = self.dpi.currentData()
                txt += f"\nUna página A4 a {dpi} ppp mide unos {round(8.27 * dpi)} × {round(11.69 * dpi)} píxeles."
            self.preview.setText(txt)
        except ValueError as e:
            self.preview.setText(str(e))

    def validate(self):
        try:
            pages = self.pages()
        except ValueError as e:
            self.show_error(str(e))
            return False
        if not self.base.text().strip():
            self.show_error("Escribe un nombre para los archivos.")
            return False
        if not self.folder.text().strip():
            self.show_error("Elige una carpeta de destino.")
            return False
        fmt = self.fmt.currentData()
        files = self.export.planned_files(self.folder.text(), self.base.text().strip(), fmt, pages,
                                          self._pc, self.multi.isChecked())
        existing = [f for f in files if os.path.exists(f)]
        if existing and not confirm(self, "Archivos existentes",
                                    f"Ya existen {len(existing)} archivo(s) con ese nombre en la carpeta.\n"
                                    "¿Quieres reemplazarlos?", "Reemplazar", "Cancelar"):
            return False
        s = self.settings
        s.setValue("export/fmt", fmt)
        s.setValue("export/dpi", self.dpi.currentData())
        s.setValue("export/mode", self.mode.currentData())
        s.setValue("export/quality", self.quality.value())
        s.setValue("export/multi", self.multi.isChecked())
        self.result = dict(pages=pages, folder=self.folder.text().strip(), base=self.base.text().strip(),
                           fmt=fmt, dpi=self.dpi.currentData(), mode=self.mode.currentData(),
                           quality=self.quality.value(), multipage_tiff=self.multi.isChecked())
        return True


class OfficeExportDialog(Dialog):
    """Exportar a Word o a Excel."""

    def __init__(self, parent, kind, page_count, current, selected, default_path, settings):
        is_word = kind == "docx"
        super().__init__(parent, "Exportar a Word" if is_word else "Exportar a Excel",
                         ("Crea un documento de Word que se puede editar: párrafos, fuentes, negritas, viñetas, "
                          "tablas, imágenes y resaltados." if is_word else
                          "Pasa las tablas del PDF a una hoja de cálculo. Los importes, porcentajes y fechas "
                          "se convierten en números y fechas de verdad."),
                         "word_doc" if is_word else "sheet_doc", ok_text="Exportar", width=600)
        self.kind = kind
        self.settings = settings
        self._pc, self._cur, self._sel = page_count, current, list(selected)
        f = QFormLayout()
        f.setLabelAlignment(Qt.AlignRight)
        f.setVerticalSpacing(9)
        pw = QWidget()
        pl = QVBoxLayout(pw)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(4)
        self.r_all = QRadioButton(f"Todas ({page_count})")
        self.r_cur = QRadioButton(f"Página actual ({current + 1})")
        self.r_sel = QRadioButton(f"Seleccionadas en el panel ({len(selected)})")
        self.r_sel.setEnabled(len(selected) > 1)
        rr = QHBoxLayout()
        self.r_rng = QRadioButton("Intervalo:")
        self.rng = QLineEdit()
        self.rng.setPlaceholderText("p. ej. 1-3, 5, 8")
        self.rng.textEdited.connect(lambda _: self.r_rng.setChecked(True))
        rr.addWidget(self.r_rng)
        rr.addWidget(self.rng, 1)
        (self.r_sel if len(selected) > 1 else self.r_all).setChecked(True)
        for r in (self.r_all, self.r_cur, self.r_sel):
            pl.addWidget(r)
        pl.addLayout(rr)
        f.addRow("Páginas:", pw)
        if is_word:
            self.o_breaks = QCheckBox("Un salto de página por cada página del PDF")
            self.o_breaks.setChecked(settings.value("office/breaks", "true") in (True, "true"))
            self.o_images = QCheckBox("Incluir las imágenes")
            self.o_images.setChecked(settings.value("office/images", "true") in (True, "true"))
            self.o_hf = QCheckBox("Encabezado y pie de página de Word con lo que se repite en todas las páginas")
            self.o_hf.setChecked(settings.value("office/hf", "true") in (True, "true"))
            ow = QWidget()
            ol = QVBoxLayout(ow)
            ol.setContentsMargins(0, 0, 0, 0)
            ol.setSpacing(4)
            for c in (self.o_breaks, self.o_images, self.o_hf):
                ol.addWidget(c)
            f.addRow("Opciones:", ow)
        else:
            self.mode = QComboBox()
            for k, lab in (("tables", "Una hoja por cada tabla"), ("one_sheet", "Todas las tablas en una sola hoja"),
                           ("text", "Todo el texto, en columnas (una hoja por página)")):
                self.mode.addItem(lab, k)
            self.mode.setCurrentIndex(max(0, self.mode.findData(settings.value("office/mode", "tables"))))
            f.addRow("Contenido:", self.mode)
            self.o_convert = QCheckBox("Convertir importes, porcentajes y fechas en números y fechas")
            self.o_convert.setChecked(settings.value("office/convert", "true") in (True, "true"))
            f.addRow("", self.o_convert)
            note = QLabel("Si el PDF no tiene tablas con líneas, el texto se reparte en columnas según su posición.")
            note.setObjectName("Muted")
            note.setWordWrap(True)
            f.addRow("", note)
        orow = QHBoxLayout()
        self.out = QLineEdit(default_path)
        b = QPushButton(icons.icon("folder"), " Cambiar…")
        b.clicked.connect(self._browse)
        orow.addWidget(self.out, 1)
        orow.addWidget(b)
        f.addRow("Guardar como:", orow)
        self.body.addLayout(f)
        self.result = None

    def _browse(self):
        flt = "Documento de Word (*.docx)" if self.kind == "docx" else "Libro de Excel (*.xlsx)"
        p, _ = QFileDialog.getSaveFileName(self, "Guardar como", self.out.text(), flt)
        if p:
            if not p.lower().endswith("." + self.kind):
                p += "." + self.kind
            self.out.setText(p)

    def pages(self):
        if self.r_cur.isChecked():
            return [self._cur]
        if self.r_sel.isChecked():
            return sorted(self._sel)
        if self.r_rng.isChecked():
            from ..core.export import parse_range
            return parse_range(self.rng.text(), self._pc)
        return list(range(self._pc))

    def validate(self):
        try:
            pages = self.pages()
        except ValueError as e:
            self.show_error(str(e))
            return False
        path = self.out.text().strip()
        if not path:
            self.show_error("Indica dónde guardar el archivo.")
            return False
        if not path.lower().endswith("." + self.kind):
            path += "." + self.kind
            self.out.setText(path)
        folder = os.path.dirname(path) or "."
        if not os.path.isdir(folder):
            self.show_error("La carpeta de destino no existe.")
            return False
        if os.path.exists(path) and not confirm(self, "El archivo ya existe",
                                                f"Ya existe «{os.path.basename(path)}».\n¿Quieres reemplazarlo?",
                                                "Reemplazar", "Cancelar"):
            return False
        s = self.settings
        if self.kind == "docx":
            s.setValue("office/breaks", self.o_breaks.isChecked())
            s.setValue("office/images", self.o_images.isChecked())
            s.setValue("office/hf", self.o_hf.isChecked())
            opts = dict(page_breaks=self.o_breaks.isChecked(), images=self.o_images.isChecked(),
                        header_footer=self.o_hf.isChecked())
        else:
            s.setValue("office/mode", self.mode.currentData())
            s.setValue("office/convert", self.o_convert.isChecked())
            opts = dict(mode=self.mode.currentData(), convert=self.o_convert.isChecked())
        self.result = dict(kind=self.kind, pages=pages, path=path, opts=opts)
        return True


# ---------------------------------------------------------------- OCR
class ScanDialog(Dialog):
    """Opciones de escaneo."""

    def __init__(self, parent, settings, adding: bool):
        super().__init__(parent, "Escanear documento",
                         ("Las páginas escaneadas se añadirán al documento abierto."
                          if adding else "Se creará un PDF nuevo con las páginas escaneadas."),
                         "scanner", ok_text="Escanear", width=560)
        from ..core import scanner
        self.scanner = scanner
        self.settings = settings
        self.use_wizard = False
        f = QFormLayout()
        f.setLabelAlignment(Qt.AlignRight)
        f.setVerticalSpacing(9)
        drow = QHBoxLayout()
        self.device = QComboBox()
        self.device.setMinimumWidth(300)
        rb = QToolButton()
        rb.setIcon(icons.icon("redo"))
        rb.setToolTip("Buscar escáneres de nuevo")
        rb.setStyleSheet("border:none; padding:4px;")
        rb.clicked.connect(self._load_devices)
        drow.addWidget(self.device, 1)
        drow.addWidget(rb)
        f.addRow("Escáner:", drow)
        sw = QWidget()
        sl = QVBoxLayout(sw)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(4)
        self.r_flat = QRadioButton("Cristal (una página cada vez)")
        self.r_feed = QRadioButton("Alimentador de hojas (todas seguidas)")
        self.r_dup = QRadioButton("Alimentador a doble cara")
        for r in (self.r_flat, self.r_feed, self.r_dup):
            sl.addWidget(r)
        f.addRow("Origen:", sw)
        self.mode = QComboBox()
        for k, lab in (("gray", "Escala de grises (recomendado para documentos)"), ("color", "Color"),
                       ("bw", "Blanco y negro (archivos más pequeños)")):
            self.mode.addItem(lab, k)
        self.mode.setCurrentIndex(max(0, self.mode.findData(settings.value("scan/mode", "gray"))))
        f.addRow("Color:", self.mode)
        self.dpi = QComboBox()
        for v, lab in ((150, "150 ppp - archivo pequeño"), (200, "200 ppp - normal"),
                       (300, "300 ppp - recomendado para reconocer texto"), (600, "600 ppp - máxima calidad")):
            self.dpi.addItem(lab, v)
        self.dpi.setCurrentIndex(max(0, self.dpi.findData(int(settings.value("scan/dpi", 300)))))
        f.addRow("Resolución:", self.dpi)
        self.body.addLayout(f)
        self.ocr = QCheckBox("Reconocer el texto al terminar (para poder buscar y copiar)")
        self.ocr.setChecked(settings.value("scan/ocr", "true") in (True, "true"))
        self.blank = QCheckBox("Quitar las páginas en blanco")
        self.blank.setChecked(settings.value("scan/blank", "true") in (True, "true"))
        self.body.addWidget(self.ocr)
        self.body.addWidget(self.blank)
        self.twain_ui = QCheckBox("Mostrar la ventana del escáner (para elegir sus opciones antes de escanear)")
        self.twain_ui.setToolTip("Escáneres TWAIN: abre la ventana del controlador del fabricante. Algunos "
                                 "escáneres solo funcionan con ella.")
        self.twain_ui.setChecked(settings.value("scan/twain_ui", "true") in (True, "true"))
        self.body.addWidget(self.twain_ui)
        self.note = QLabel()
        self.note.setObjectName("Muted")
        self.note.setWordWrap(True)
        self.body.addWidget(self.note)
        wiz = QPushButton("¿El escáner no aparece o da error? Usar el asistente de escaneo de Windows")
        wiz.setObjectName("Link")
        wiz.clicked.connect(self._wizard)
        self.body.addWidget(wiz)
        self.device.currentIndexChanged.connect(lambda _: self._sync_caps())
        self.devices = []
        self._load_devices()

    def _load_devices(self):
        from PySide6.QtWidgets import QApplication
        self.device.clear()
        self.note.setText("")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.devices = self.scanner.list_devices()
        except self.scanner.ScannerError as e:
            self.devices = []
            self.note.setText(str(e))
        finally:
            QApplication.restoreOverrideCursor()
        last = self.settings.value("scan/device", "")
        for dev in self.devices:
            self.device.addItem(icons.icon("scanner"), dev.name, dev.id)
        if self.devices:
            self.device.setCurrentIndex(max(0, self.device.findData(last)))
        elif not self.note.text():
            self.note.setText("No se ha encontrado ningún escáner (ni WIA ni TWAIN). Comprueba que está "
                              "encendido y conectado, que su controlador está instalado, y pulsa el botón "
                              "de buscar de nuevo.")
        self.ok_btn.setEnabled(bool(self.devices))
        self._sync_caps()

    def _sync_caps(self):
        dev = next((d for d in self.devices if d.id == self.device.currentData()), None)
        self.twain_ui.setVisible(bool(dev and getattr(dev, "kind", "wia") == "twain"))
        self.r_flat.setEnabled(dev is None or dev.flatbed or not (dev.feeder or dev.duplex))
        self.r_feed.setEnabled(bool(dev and dev.feeder))
        self.r_dup.setEnabled(bool(dev and dev.duplex))
        last = self.settings.value("scan/source", "flatbed")
        want = {"flatbed": self.r_flat, "feeder": self.r_feed, "duplex": self.r_dup}.get(last, self.r_flat)
        if not want.isEnabled():
            want = self.r_flat if self.r_flat.isEnabled() else self.r_feed
        want.setChecked(True)

    def _wizard(self):
        self.use_wizard = True
        self.accept()

    def validate(self):
        if not self.devices:
            self.show_error("No hay ningún escáner disponible.")
            return False
        src = "duplex" if self.r_dup.isChecked() else "feeder" if self.r_feed.isChecked() else "flatbed"
        s = self.settings
        s.setValue("scan/device", self.device.currentData())
        s.setValue("scan/source", src)
        s.setValue("scan/mode", self.mode.currentData())
        s.setValue("scan/dpi", self.dpi.currentData())
        s.setValue("scan/ocr", self.ocr.isChecked())
        s.setValue("scan/blank", self.blank.isChecked())
        s.setValue("scan/twain_ui", self.twain_ui.isChecked())
        self.options = self.scanner.ScanSettings(self.device.currentData(), src, self.mode.currentData(),
                                                 self.dpi.currentData(), self.twain_ui.isChecked())
        return True


class FolderScanDialog(Dialog):
    """macOS: escaneo con «Captura de Imagen». NovoPDF recoge las páginas de una carpeta."""

    def __init__(self, parent, settings, adding: bool):
        super().__init__(parent, "Escanear documento",
                         ("Las páginas escaneadas se añadirán al documento abierto."
                          if adding else "Se creará un PDF nuevo con las páginas escaneadas."),
                         "scanner", ok_text="Crear PDF", width=620)
        import time
        from PySide6.QtCore import QSize, QTimer
        from ..core import scanner
        self.scanner = scanner
        self.settings = settings
        self.folder = settings.value("scan/mac_folder", "") or scanner.mac_scan_folder()
        if not os.path.isdir(self.folder):
            self.folder = scanner.mac_scan_folder()
        self.since = time.time()
        self.known: set = set()
        self.files: list = []
        steps = QLabel(
            "<ol style='margin-left:-20px'>"
            "<li>Pulsa <b>Abrir Captura de Imagen</b> y elige tu escáner en la lista de la izquierda.</li>"
            "<li>En <b>«Escanear a»</b> elige la carpeta <b>«%s»</b> (solo la primera vez) y, en "
            "<b>Formato</b>, JPEG, PNG, TIFF o PDF.</li>"
            "<li>Pulsa <b>Escanear</b>. Las páginas aparecerán aquí; cuando termines, pulsa <b>Crear PDF</b>.</li>"
            "</ol>" % os.path.basename(self.folder))
        steps.setWordWrap(True)
        steps.setTextFormat(Qt.RichText)
        self.body.addWidget(steps)
        row = QHBoxLayout()
        ob = QPushButton(icons.icon("scanner"), " Abrir Captura de Imagen")
        ob.setObjectName("Primary")
        ob.clicked.connect(lambda: scanner.open_image_capture(self.folder))
        fb = QPushButton(icons.icon("folder"), " Mostrar la carpeta")
        fb.clicked.connect(self._show_folder)
        cb = QPushButton("Usar otra carpeta…")
        cb.setObjectName("Link")
        cb.clicked.connect(self._choose_folder)
        row.addWidget(ob)
        row.addWidget(fb)
        row.addStretch(1)
        row.addWidget(cb)
        self.body.addLayout(row)
        self.count = QLabel()
        self.count.setObjectName("SectionTitle")
        self.body.addWidget(self.count)
        self.list = QListWidget()
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setIconSize(QSize(72, 100))
        self.list.setMinimumHeight(150)
        self.list.setMovement(QListWidget.Static)
        self.list.setResizeMode(QListWidget.Adjust)
        self.body.addWidget(self.list)
        f = QFormLayout()
        self.mode = QComboBox()
        for k, lab in (("gray", "Escala de grises (recomendado para documentos)"), ("color", "Color"),
                       ("bw", "Blanco y negro (archivos más pequeños)")):
            self.mode.addItem(lab, k)
        self.mode.setCurrentIndex(max(0, self.mode.findData(settings.value("scan/mode", "gray"))))
        f.addRow("Color del PDF:", self.mode)
        self.body.addLayout(f)
        self.ocr = QCheckBox("Reconocer el texto al terminar (para poder buscar y copiar)")
        self.ocr.setChecked(settings.value("scan/ocr", "true") in (True, "true"))
        self.blank = QCheckBox("Quitar las páginas en blanco")
        self.blank.setChecked(settings.value("scan/blank", "true") in (True, "true"))
        self.body.addWidget(self.ocr)
        self.body.addWidget(self.blank)
        self.use_wizard = False
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.poll)
        self.timer.start()
        self._update()

    def _show_folder(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.folder))

    def _choose_folder(self):
        p = QFileDialog.getExistingDirectory(self, "Carpeta donde guarda los escaneos Captura de Imagen", self.folder)
        if p:
            self.folder = p
            self.settings.setValue("scan/mac_folder", p)
            self.poll()

    def poll(self):
        from PySide6.QtGui import QImage, QPixmap
        new = self.scanner.new_files(self.folder, self.since, self.known)
        for p in new:
            self.known.add(p)
            self.files.append(p)
            pm = QPixmap()
            if not p.lower().endswith(".pdf"):
                img = QImage(p)
                if not img.isNull():
                    pm = QPixmap.fromImage(img.scaled(144, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            it = QListWidgetItem(QIcon(pm) if not pm.isNull() else icons.icon("file"), str(len(self.files)))
            it.setToolTip(p)
            self.list.addItem(it)
        if new:
            self.list.scrollToBottom()
        self._update()

    def _update(self):
        n = len(self.files)
        self.count.setText("Esperando páginas…" if n == 0 else f"{n} archivo(s) recibido(s)")
        self.ok_btn.setEnabled(n > 0)

    def validate(self):
        self.poll()
        if not self.files:
            self.show_error("Todavía no ha llegado ninguna página escaneada.")
            return False
        self.timer.stop()
        s = self.settings
        s.setValue("scan/mode", self.mode.currentData())
        s.setValue("scan/ocr", self.ocr.isChecked())
        s.setValue("scan/blank", self.blank.isChecked())
        return True

    def reject(self):
        self.timer.stop()
        super().reject()


class OcrDialog(Dialog):
    def __init__(self, parent, page_count, current, selected):
        super().__init__(parent, "Reconocer texto (OCR)",
                         "Convierte las páginas escaneadas en texto que se puede buscar, seleccionar y "
                         "copiar. El aspecto del documento no cambia.", "scan", ok_text="Reconocer texto")
        f = QFormLayout()
        f.setLabelAlignment(Qt.AlignRight)
        self.lang = QComboBox()
        for code, label in ocr.LANGUAGES:
            self.lang.addItem(label, code)
        f.addRow("Idioma del documento:", self.lang)
        self.quality = QComboBox()
        self.quality.addItem("Normal (recomendado)", 300)
        self.quality.addItem("Alta (más lento; letra pequeña)", 400)
        f.addRow("Calidad:", self.quality)
        self.body.addLayout(f)
        self.r_all = QRadioButton(f"Todo el documento ({page_count} páginas)")
        self.r_cur = QRadioButton(f"Solo la página actual ({current + 1})")
        self.r_sel = QRadioButton(f"Páginas seleccionadas en el panel ({len(selected)})")
        self.r_all.setChecked(True)
        self.r_sel.setEnabled(len(selected) > 1)
        for r in (self.r_all, self.r_cur, self.r_sel):
            self.body.addWidget(r)
        self.skip = QCheckBox("Saltar las páginas que ya tienen texto")
        self.skip.setChecked(True)
        self.body.addWidget(self.skip)
        self._pc, self._cur, self._sel = page_count, current, selected

    def pages(self) -> list[int]:
        if self.r_cur.isChecked():
            return [self._cur]
        if self.r_sel.isChecked():
            return list(self._sel)
        return list(range(self._pc))


# ---------------------------------------------------------------- nuevo documento
SIZES = [("A4 vertical", 595, 842), ("A4 horizontal", 842, 595), ("A3 vertical", 842, 1191),
         ("Carta (EE. UU.)", 612, 792)]


class NewBlankDialog(Dialog):
    def __init__(self, parent):
        super().__init__(parent, "Nuevo PDF en blanco", "Crea un documento con páginas vacías.",
                         "file_plus", ok_text="Crear")
        f = QFormLayout()
        self.size = QComboBox()
        for name, w, h in SIZES:
            self.size.addItem(name, (w, h))
        self.count = QSpinBox()
        self.count.setRange(1, 500)
        self.count.setValue(1)
        f.addRow("Tamaño de página:", self.size)
        f.addRow("Número de páginas:", self.count)
        self.body.addLayout(f)

    def values(self):
        w, h = self.size.currentData()
        return self.count.value(), w, h


class FileListDialog(Dialog):
    """Lista ordenable de archivos (para combinar PDF o crear desde imágenes)."""

    def __init__(self, parent, title, subtitle, icon_name, filter_, ok_text, initial=None):
        super().__init__(parent, title, subtitle, icon_name, ok_text=ok_text, width=560)
        self.filter = filter_
        self.list = QListWidget()
        self.list.setDragDropMode(QAbstractItemView.InternalMove)
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.setMinimumHeight(220)
        self.body.addWidget(self.list)
        row = QHBoxLayout()
        add = QPushButton(icons.icon("file_plus"), " Añadir archivos…")
        add.clicked.connect(self._add)
        up = QPushButton(icons.icon("up"), "")
        up.setToolTip("Subir")
        up.clicked.connect(lambda: self._move(-1))
        down = QPushButton(icons.icon("down"), "")
        down.setToolTip("Bajar")
        down.clicked.connect(lambda: self._move(1))
        rem = QPushButton(icons.icon("trash"), " Quitar")
        rem.clicked.connect(self._remove)
        row.addWidget(add)
        row.addStretch(1)
        row.addWidget(up)
        row.addWidget(down)
        row.addWidget(rem)
        self.body.addLayout(row)
        tip = QLabel("Consejo: arrastra los archivos de la lista para cambiar el orden.")
        tip.setObjectName("Muted")
        self.body.addWidget(tip)
        for p in initial or []:
            self._append(p)

    def _append(self, p):
        it = QListWidgetItem(icons.icon("file"), os.path.basename(p))
        it.setData(Qt.UserRole, p)
        it.setToolTip(p)
        self.list.addItem(it)

    def _add(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Añadir archivos", "", self.filter)
        for p in files:
            self._append(p)

    def _move(self, d):
        r = self.list.currentRow()
        if r < 0:
            return
        n = r + d
        if 0 <= n < self.list.count():
            it = self.list.takeItem(r)
            self.list.insertItem(n, it)
            self.list.setCurrentRow(n)

    def _remove(self):
        for it in self.list.selectedItems():
            self.list.takeItem(self.list.row(it))

    def files(self):
        return [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())]

    def validate(self):
        if not self.files():
            self.show_error("Añade al menos un archivo.")
            return False
        return True


class InsertPositionDialog(Dialog):
    def __init__(self, parent, filename, current, count):
        super().__init__(parent, "Insertar páginas", f"¿Dónde quieres insertar «{filename}»?",
                         "file_in", ok_text="Insertar")
        self.opts = [("Después de la página actual", current + 1),
                     ("Antes de la página actual", current),
                     ("Al principio del documento", 0),
                     ("Al final del documento", count)]
        self.group = QButtonGroup(self)
        for k, (lab, _) in enumerate(self.opts):
            r = QRadioButton(f"{lab}" + (f" ({current + 1})" if k < 2 else ""))
            self.group.addButton(r, k)
            self.body.addWidget(r)
            if k == 0:
                r.setChecked(True)

    def position(self) -> int:
        return self.opts[self.group.checkedId()][1]


# ---------------------------------------------------------------- firmas: verificación
class SignaturesDialog(Dialog):
    def __init__(self, parent, reports):
        super().__init__(parent, "Firmas del documento",
                         f"El documento contiene {len(reports)} firma(s) digital(es).", "shield",
                         ok_text="Cerrar", cancel_text="", width=600)
        for r in reports:
            card = QFrame()
            card.setObjectName("Card")
            g = QHBoxLayout(card)
            g.setContentsMargins(14, 12, 14, 12)
            ic = QLabel()
            if not r.intact:
                name, col = "error", theme.DANGER
            elif r.trusted and r.covers_all:
                name, col = "shield", theme.SUCCESS
            elif r.trusted:
                name, col = "shield", theme.SUCCESS
            else:
                name, col = "warning", theme.WARNING
            ic.setPixmap(icons.pixmap(name, 28, col))
            ic.setAlignment(Qt.AlignTop)
            g.addWidget(ic)
            v = QVBoxLayout()
            t = QLabel(f"<b>{r.signer}</b>" + (f" &nbsp;<span style='color:{theme.MUTED}'>{r.details}</span>" if r.details else ""))
            v.addWidget(t)
            meta = QLabel(f"Fecha: {r.when}" + (f" · Motivo: {r.reason}" if r.reason else "")
                          + (f" · Emisor: {r.issuer}" if r.issuer else ""))
            meta.setObjectName("Muted")
            meta.setWordWrap(True)
            v.addWidget(meta)
            s = QLabel(r.summary)
            s.setWordWrap(True)
            v.addWidget(s)
            g.addLayout(v, 1)
            self.body.addWidget(card)


# ---------------------------------------------------------------- firma: creación
REASONS = ["", "Soy el autor del documento", "Conformidad", "Aprobación", "Visto bueno",
           "He revisado este documento"]


class SignDialog(Dialog):
    def __init__(self, parent, default_out: str, visible: bool, page_no: int, settings):
        super().__init__(parent, "Firmar el documento",
                         ("Se añadirá un sello visible en la página %d." % page_no) if visible else
                         "Se añadirá una firma invisible (no aparece en la página).",
                         "sign", ok_text="Firmar y guardar", width=600)
        from ..core import signing
        self.signing = signing
        self.settings = settings
        self.choice = None
        self.pfx_signer = None

        src_row = QHBoxLayout()
        self.r_win = QRadioButton("Certificado del Llavero de este Mac" if sys.platform == "darwin" else "Certificado instalado en este equipo")
        self.r_pfx = QRadioButton("Archivo de certificado (.pfx / .p12)")
        src_row.addWidget(self.r_win)
        src_row.addWidget(self.r_pfx)
        src_row.addStretch(1)
        self.body.addLayout(src_row)
        self.stack = QStackedWidget()
        # --- almacén de Windows
        wpage = QWidget()
        wl = QVBoxLayout(wpage)
        wl.setContentsMargins(0, 0, 0, 0)
        self.cert_list = QListWidget()
        self.cert_list.setMinimumHeight(150)
        wl.addWidget(self.cert_list)
        self.win_note = QLabel()
        self.win_note.setObjectName("Muted")
        self.win_note.setWordWrap(True)
        wl.addWidget(self.win_note)
        self.stack.addWidget(wpage)
        # --- archivo
        fpage = QWidget()
        fl = QFormLayout(fpage)
        fl.setContentsMargins(0, 4, 0, 0)
        frow = QHBoxLayout()
        self.pfx_path = QLineEdit(settings.value("sign/pfx", ""))
        self.pfx_path.setPlaceholderText("Selecciona el archivo del certificado")
        b = QPushButton("Examinar…")
        b.clicked.connect(self._browse_pfx)
        frow.addWidget(self.pfx_path, 1)
        frow.addWidget(b)
        fl.addRow("Archivo:", frow)
        pw, self.pfx_pw = password_field("Contraseña del certificado")
        fl.addRow("Contraseña:", pw)
        self.stack.addWidget(fpage)
        self.body.addWidget(self.stack)

        f = QFormLayout()
        self.reason = QComboBox()
        self.reason.setEditable(True)
        self.reason.addItems(REASONS)
        self.reason.setCurrentText(settings.value("sign/reason", ""))
        self.reason.lineEdit().setPlaceholderText("Opcional")
        self.location = QLineEdit(settings.value("sign/location", ""))
        self.location.setPlaceholderText("Opcional, p. ej. Badajoz")
        f.addRow("Motivo:", self.reason)
        f.addRow("Lugar:", self.location)
        orow = QHBoxLayout()
        self.out = QLineEdit(default_out)
        ob = QPushButton("Cambiar…")
        ob.clicked.connect(self._browse_out)
        orow.addWidget(self.out, 1)
        orow.addWidget(ob)
        f.addRow("Guardar como:", orow)
        self.body.addLayout(f)
        note = QLabel("La firma es lo último que se debe hacer: si después se modifica el documento, "
                      "la firma dejará de ser válida.")
        note.setObjectName("Muted")
        note.setWordWrap(True)
        self.body.addWidget(note)

        self.r_win.toggled.connect(lambda on: self._show_page(0 if on else 1))
        self._load_windows()
        if signing.winstore.AVAILABLE and self.cert_list.count() and settings.value("sign/source", "windows") == "windows":
            self.r_win.setChecked(True)
        else:
            self.r_pfx.setChecked(True)
        self._show_page(0 if self.r_win.isChecked() else 1)
        if not signing.winstore.AVAILABLE:
            self.r_win.setEnabled(False)

    def _show_page(self, k):
        from PySide6.QtWidgets import QSizePolicy
        self.stack.setCurrentIndex(k)
        for i in range(self.stack.count()):
            pol = QSizePolicy.Preferred if i == k else QSizePolicy.Ignored
            self.stack.widget(i).setSizePolicy(pol, pol)
        self.stack.adjustSize()
        self.adjustSize()

    def _load_windows(self):
        self.certs = self.signing.windows_certificates()
        if not self.signing.winstore.AVAILABLE:
            self.win_note.setText("El almacén de certificados del sistema solo está disponible en Windows y macOS.")
            return
        last = self.settings.value("sign/thumb", "")
        import hashlib
        for c in self.certs:
            extra = self.signing.holder_details(c.cert)
            txt = f"{c.holder}\n{('%s · ' % extra) if extra else ''}Emitido por {c.issuer} · Válido hasta {c.valid_to:%d/%m/%Y}"
            if c.expired:
                txt += "  (CADUCADO)"
            it = QListWidgetItem(icons.icon("sign" if not c.expired else "warning"), txt)
            it.setData(Qt.UserRole, c)
            if c.expired:
                it.setForeground(QColor(theme.MUTED))
            self.cert_list.addItem(it)
            if hashlib.sha1(c.der).hexdigest() == last:
                self.cert_list.setCurrentItem(it)
        if self.cert_list.count() and self.cert_list.currentRow() < 0:
            self.cert_list.setCurrentRow(0)
        if not self.certs:
            self.win_note.setText("No hay certificados personales instalados en este equipo. "
                                  "Puedes usar un archivo .pfx/.p12 o instalar tu certificado en el sistema"
                                  + (" (Llavero)." if sys.platform == "darwin" else "."))
        else:
            self.win_note.setText("Si el certificado está protegido o en una tarjeta, el sistema te pedirá "
                                  "el PIN o la contraseña al firmar.")

    def _browse_pfx(self):
        p, _ = QFileDialog.getOpenFileName(self, "Certificado", os.path.dirname(self.pfx_path.text()),
                                           "Certificados (*.pfx *.p12);;Todos los archivos (*)")
        if p:
            self.pfx_path.setText(p)

    def _browse_out(self):
        p, _ = QFileDialog.getSaveFileName(self, "Guardar documento firmado", self.out.text(), "PDF (*.pdf)")
        if p:
            if not p.lower().endswith(".pdf"):
                p += ".pdf"
            self.out.setText(p)

    def validate(self) -> bool:
        import hashlib
        if self.r_win.isChecked():
            it = self.cert_list.currentItem()
            if not it:
                self.show_error("Selecciona un certificado.")
                return False
            c = it.data(Qt.UserRole)
            if c.expired:
                self.show_error("El certificado seleccionado está caducado o todavía no es válido.")
                return False
            self.choice = c
            self.settings.setValue("sign/source", "windows")
            self.settings.setValue("sign/thumb", hashlib.sha1(c.der).hexdigest())
        else:
            path = self.pfx_path.text().strip()
            if not path or not os.path.isfile(path):
                self.show_error("Selecciona el archivo del certificado.")
                return False
            try:
                self.choice, self.pfx_signer = self.signing.load_pfx(path, self.pfx_pw.text())
            except self.signing.SigningError as e:
                self.show_error(str(e))
                return False
            if self.choice.expired:
                self.show_error("El certificado está caducado o todavía no es válido.")
                return False
            self.settings.setValue("sign/source", "pfx")
            self.settings.setValue("sign/pfx", path)
        out = self.out.text().strip()
        if not out:
            self.show_error("Indica dónde guardar el documento firmado.")
            return False
        if not out.lower().endswith(".pdf"):
            self.out.setText(out + ".pdf")
        self.settings.setValue("sign/reason", self.reason.currentText())
        self.settings.setValue("sign/location", self.location.text())
        return True


class FieldDialog(Dialog):
    """Propiedades de un campo de formulario (también al crear desplegables, listas y opciones)."""

    def __init__(self, parent, field, creating=False, groups=None, taken=None):
        from ..core import forms
        self.forms = forms
        self.f = field
        self.taken = set(taken or ()) - {field.name}
        k = field.kind
        title = ("Nuevo: " if creating else "") + field.kind_name.lower().capitalize()
        sub = {forms.COMBO: "Escribe las opciones de la lista, una por línea.",
               forms.LIST: "Escribe las opciones de la lista, una por línea.",
               forms.RADIO: "Los botones de opción del mismo grupo se excluyen entre sí: al marcar uno "
                            "se desmarcan los demás.",
               forms.SIGNATURE: "Al hacer clic en este campo se podrá firmar digitalmente en él."}.get(
            k, "El nombre identifica el dato (por ejemplo, al exportar los datos a Excel).")
        icon = {forms.TEXT: "f_text", forms.CHECK: "f_check", forms.RADIO: "f_radio", forms.COMBO: "f_combo",
                forms.LIST: "f_list", forms.SIGNATURE: "f_sign"}.get(k, "form")
        super().__init__(parent, title, sub, icon, ok_text="Crear" if creating else "Aceptar", width=460)
        f = QFormLayout()
        f.setLabelAlignment(Qt.AlignRight)
        if k == forms.RADIO:
            self.name = QComboBox()
            self.name.setEditable(True)
            self.name.addItems(sorted(groups or []))
            self.name.setEditText(field.name)
            f.addRow("Grupo:", self.name)
            self.export = QLineEdit(field.on_state or "")
            self.export.setPlaceholderText("p. ej. Si, No, Mañana, Tarde")
            f.addRow("Valor de esta opción:", self.export)
        else:
            self.name = QLineEdit(field.name)
            f.addRow("Nombre:", self.name)
        self.label = QLineEdit(field.label)
        self.label.setPlaceholderText("Texto de ayuda al pasar el ratón (opcional)")
        f.addRow("Descripción:", self.label)
        self.options = None
        self.editable = None
        self.multiline = self.fontsize = self.maxlen = self.align = None
        if k in (forms.COMBO, forms.LIST):
            self.options = QPlainTextEdit("\n".join(field.options))
            self.options.setPlaceholderText("Badajoz\nCáceres")
            self.options.setFixedHeight(110)
            f.addRow("Opciones:", self.options)
            if k == forms.COMBO:
                self.editable = QCheckBox("Permitir escribir un valor que no está en la lista")
                self.editable.setChecked(field.editable)
                f.addRow("", self.editable)
        if k == forms.TEXT:
            self.multiline = QCheckBox("Varias líneas (párrafos)")
            self.multiline.setChecked(field.multiline)
            f.addRow("", self.multiline)
            self.fontsize = QComboBox()
            self.fontsize.addItem("Automático", 0)
            for n in (7, 8, 9, 10, 11, 12, 14, 16):
                self.fontsize.addItem(f"{n} pt", n)
            idx = self.fontsize.findData(int(field.fontsize)) if field.fontsize else 0
            if idx < 0:
                self.fontsize.addItem(f"{field.fontsize:g} pt", field.fontsize)
                idx = self.fontsize.count() - 1
            self.fontsize.setCurrentIndex(idx)
            self.align = QComboBox()
            self.align.addItems(["Izquierda", "Centro", "Derecha"])
            self.align.setCurrentIndex(field.align if field.align in (0, 1, 2) else 0)
            row = QHBoxLayout()
            row.addWidget(self.fontsize)
            row.addSpacing(10)
            row.addWidget(QLabel("Alineación:"))
            row.addWidget(self.align)
            row.addStretch(1)
            f.addRow("Tamaño de letra:", row)
            self.maxlen = QSpinBox()
            self.maxlen.setRange(0, 9999)
            self.maxlen.setSpecialValueText("Sin límite")
            self.maxlen.setValue(field.max_len)
            f.addRow("Máximo de caracteres:", self.maxlen)
        self.required = QCheckBox("Obligatorio")
        self.required.setChecked(field.required)
        self.readonly = QCheckBox("Solo lectura")
        self.readonly.setChecked(field.readonly)
        row = QHBoxLayout()
        row.addWidget(self.required)
        row.addSpacing(16)
        if k != forms.SIGNATURE:
            row.addWidget(self.readonly)
        row.addStretch(1)
        f.addRow("", row)
        self.body.addLayout(f)

    def _name(self) -> str:
        return (self.name.currentText() if isinstance(self.name, QComboBox) else self.name.text()).strip()

    def _opts(self):
        return [o.strip() for o in self.options.toPlainText().splitlines() if o.strip()] if self.options else None

    def validate(self) -> bool:
        forms = self.forms
        name = forms.clean_name(self._name(), "")
        if not name:
            self.show_error("Escribe un nombre para el campo.")
            return False
        if self.f.kind != forms.RADIO and name in self.taken:
            self.show_error(f"Ya hay otro campo llamado «{name}».")
            return False
        if self.options is not None and not self._opts():
            self.show_error("Escribe al menos una opción.")
            return False
        if self.f.kind == forms.RADIO and not self.export.text().strip():
            self.show_error("Escribe el valor de esta opción (lo que se guarda al marcarla).")
            return False
        return True

    def values(self) -> dict:
        forms = self.forms
        v = {"name": forms.clean_name(self._name()), "label": self.label.text().strip(),
             "required": self.required.isChecked()}
        if self.f.kind != forms.SIGNATURE:
            v["readonly"] = self.readonly.isChecked()
        if self.options is not None:
            v["options"] = self._opts()
        if self.editable is not None:
            v["editable"] = self.editable.isChecked()
        if self.multiline is not None:
            v["multiline"] = self.multiline.isChecked()
            v["fontsize"] = float(self.fontsize.currentData() or 0)
            v["max_len"] = self.maxlen.value()
            v["align"] = self.align.currentIndex()
        if self.f.kind == forms.RADIO:
            v["export"] = self.export.text().strip()
        return v


class DetectFieldsDialog(Dialog):
    """Resumen de los campos encontrados antes de crearlos."""

    def __init__(self, parent, counts: dict, pages: int, current_only_possible: bool):
        n = sum(counts.values())
        super().__init__(parent, "Detectar campos",
                         f"Se han encontrado {n} posible{'s' if n != 1 else ''} campo{'s' if n != 1 else ''} "
                         f"en {pages} página{'s' if pages != 1 else ''}.", "wand", ok_text="Crear los campos")
        names = [("text", "de texto"), ("check", "casillas"), ("signature", "de firma")]
        parts = [f"<b>{counts[k]}</b> {label}" for k, label in names if counts.get(k)]
        lab = QLabel(" · ".join(parts))
        self.body.addWidget(lab)
        tip = QLabel("Después podrás revisarlos: arrástralos para moverlos, cambia su tamaño desde la esquina, "
                     "pulsa Supr para borrar los que sobren o haz doble clic para cambiar su nombre. "
                     "Si algo no te convence, Ctrl+Z los quita todos.")
        tip.setWordWrap(True)
        tip.setObjectName("Muted")
        self.body.addWidget(tip)
        self.only_page = QCheckBox("Solo en la página actual")
        self.only_page.setVisible(current_only_possible)
        self.body.addWidget(self.only_page)


class AboutDialog(Dialog):
    """«Acerca de NovoPDF»: versión, copyright, licencia AGPL y enlace al código fuente."""

    def __init__(self, parent=None):
        from .. import COPYRIGHT, URL_CODIGO_FUENTE, __version__
        super().__init__(parent, "Acerca de NovoPDF", f"Versión {__version__}", "info",
                         ok_text="Cerrar", cancel_text="", width=520)
        txt = QLabel(
            f"<p><b>{COPYRIGHT}</b></p>"
            "<p>NovoPDF es software libre: puede redistribuirlo y/o modificarlo bajo los términos de "
            "la Licencia Pública General Affero de GNU (GNU AGPL), versión 3 o (a su elección) "
            "cualquier versión posterior, publicada por la Free Software Foundation.</p>"
            "<p>Se distribuye con la esperanza de que sea útil, pero <b>SIN NINGUNA GARANTÍA</b>; "
            "ni siquiera la garantía implícita de comerciabilidad o idoneidad para un propósito "
            "particular. Consulte la licencia para más detalles.</p>"
            f"<p><b>Código fuente:</b> <a href=\"{URL_CODIGO_FUENTE}\">{URL_CODIGO_FUENTE}</a></p>"
            "<p style='color:#6b7385'>Utiliza PyMuPDF/MuPDF (AGPL-3.0, Artifex), Qt/PySide6 (LGPL-3.0), "
            "Tesseract (Apache-2.0), Python (PSF) y otros componentes de terceros, cada uno con su "
            "propia licencia.</p>")
        txt.setWordWrap(True)
        txt.setTextFormat(Qt.RichText)
        txt.setOpenExternalLinks(True)
        txt.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.body.addWidget(txt)
        for label, fname, fallback in (
                ("Ver la licencia (GNU AGPL v3)", "LICENSE", "https://www.gnu.org/licenses/agpl-3.0.html"),
                ("Ver los avisos de terceros", "AVISOS_TERCEROS.txt", URL_CODIGO_FUENTE)):
            b = QPushButton(icons.icon("file", color=theme.ACCENT), " " + label)
            b.setObjectName("Link")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, f=fname, u=fallback: self._open(f, u))
            self.body.addWidget(b)

    @staticmethod
    def _open(fname: str, fallback: str):
        """Abre el archivo que acompaña al programa; si no está, la página web equivalente."""
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        from ..paths import app_dir
        path = os.path.join(app_dir(), fname)
        if os.path.isfile(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        else:
            QDesktopServices.openUrl(QUrl(fallback))
