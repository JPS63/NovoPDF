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

"""Pantalla de inicio."""
from __future__ import annotations

import os

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QPushButton, QToolButton, QVBoxLayout, QWidget)

from . import icons, theme


class Welcome(QWidget):
    actionRequested = Signal(str)
    openRecent = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Welcome")
        self.setAttribute(Qt.WA_StyledBackground, True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(40, 30, 40, 30)
        outer.addStretch(1)
        center = QHBoxLayout()
        center.addStretch(1)
        col = QVBoxLayout()
        col.setSpacing(18)

        head = QHBoxLayout()
        logo = QLabel()
        pm = icons.app_icon_pixmap(128)
        pm.setDevicePixelRatio(2)
        logo.setPixmap(pm)
        head.addWidget(logo)
        tl = QVBoxLayout()
        tl.setSpacing(2)
        t = QLabel("NovoPDF")
        t.setObjectName("WelcomeTitle")
        s = QLabel("¿Qué quieres hacer?")
        s.setObjectName("WelcomeSub")
        tl.addStretch(1)
        tl.addWidget(t)
        tl.addWidget(s)
        tl.addStretch(1)
        head.addLayout(tl)
        head.addStretch(1)
        col.addLayout(head)

        grid = QGridLayout()
        grid.setSpacing(14)
        actions = [("open", "open", "Abrir un PDF"),
                   ("new", "file_plus", "PDF en blanco"),
                   ("images", "images", "PDF desde\nimágenes"),
                   ("scan", "scanner", "Escanear\nun documento"),
                   ("merge", "merge", "Combinar\nvarios PDF")]
        for k, (key, ic, label) in enumerate(actions):
            b = QToolButton()
            b.setObjectName("BigAction")
            b.setText(label)
            b.setIcon(icons.icon(ic, color=theme.ACCENT if key == "open" else "#2b3245"))
            b.setIconSize(QSize(34, 34))
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, a=key: self.actionRequested.emit(a))
            grid.addWidget(b, 0, k)
        col.addLayout(grid)

        card = QFrame()
        card.setObjectName("Card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(18, 14, 18, 14)
        rt = QLabel("Abiertos recientemente")
        rt.setObjectName("SectionTitle")
        cl.addWidget(rt)
        self.recent = QListWidget()
        self.recent.setObjectName("Recent")
        self.recent.setMinimumHeight(170)
        self.recent.setCursor(Qt.PointingHandCursor)
        self.recent.itemActivated.connect(lambda it: self.openRecent.emit(it.data(Qt.UserRole)))
        self.recent.itemClicked.connect(lambda it: self.openRecent.emit(it.data(Qt.UserRole)))
        cl.addWidget(self.recent)
        self.empty = QLabel("Aún no has abierto ningún documento.")
        self.empty.setObjectName("Muted")
        cl.addWidget(self.empty)
        col.addWidget(card)

        tip = QLabel("Consejo: también puedes arrastrar un PDF o una imagen a esta ventana.")
        tip.setObjectName("Muted")
        tip.setAlignment(Qt.AlignCenter)
        col.addWidget(tip)

        self.default_link = QPushButton(icons.icon("check", color=theme.ACCENT),
                                        " Abrir siempre los PDF con NovoPDF")
        self.default_link.setObjectName("Link")
        self.default_link.setCursor(Qt.PointingHandCursor)
        self.default_link.setToolTip("Hacer que al hacer doble clic en un PDF se abra con NovoPDF")
        self.default_link.clicked.connect(lambda: self.actionRequested.emit("default"))
        self.default_link.hide()
        dl = QHBoxLayout()
        dl.addStretch(1)
        dl.addWidget(self.default_link)
        dl.addStretch(1)
        col.addLayout(dl)

        center.addLayout(col)
        center.addStretch(1)
        outer.addLayout(center)
        outer.addStretch(2)

    def set_recent(self, paths):
        self.recent.clear()
        shown = 0
        for p in paths:
            if not os.path.isfile(p):
                continue
            it = QListWidgetItem(icons.icon("file"), f"{os.path.basename(p)}   —   {os.path.dirname(p)}")
            it.setData(Qt.UserRole, p)
            it.setToolTip(p)
            self.recent.addItem(it)
            shown += 1
            if shown >= 8:
                break
        self.empty.setVisible(shown == 0)
        self.recent.setVisible(shown > 0)

    def set_default_offer(self, visible: bool):
        self.default_link.setVisible(visible)
