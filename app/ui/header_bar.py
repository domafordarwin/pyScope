# app/ui/header_bar.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HeaderBar — branded title strip with live status indicator and theme switcher.
"""

from PyQt5 import QtCore, QtGui, QtWidgets
from .style import (
    Color, brand_font, value_font, make_font,
    apply_theme, theme_bus, current_theme, THEME_LABELS,
)


# =====================================================================
# Pulsing status dot
# =====================================================================
class _PulseDot(QtWidgets.QWidget):
    def __init__(self, parent=None, diameter=10):
        super().__init__(parent)
        self.setFixedSize(diameter + 12, diameter + 12)
        self._d = diameter
        self._color = QtGui.QColor(Color.TEXT_MUTED)
        self._pulse = 0.0
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)
        self._active = False
        theme_bus.changed.connect(lambda _: self.update())

    def set_active(self, active: bool, color_hex: str = None):
        self._active = active
        if active:
            self._color = QtGui.QColor(color_hex or Color.GREEN)
            self._pulse = 0.0
            self._timer.start()
        else:
            self._color = QtGui.QColor(Color.TEXT_MUTED)
            self._timer.stop()
            self._pulse = 0.0
        self.update()

    def _tick(self):
        self._pulse = (self._pulse + 0.05) % 2.0
        self.update()

    def paintEvent(self, ev):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        cx, cy = self.width() / 2.0, self.height() / 2.0

        if self._active:
            t = abs(1.0 - self._pulse)
            halo = QtGui.QColor(self._color)
            halo.setAlphaF(0.10 + 0.15 * t)
            p.setBrush(halo)
            p.setPen(QtCore.Qt.NoPen)
            radius = self._d / 2.0 + 4 + 3 * t
            p.drawEllipse(QtCore.QPointF(cx, cy), radius, radius)

        p.setBrush(self._color)
        p.setPen(QtCore.Qt.NoPen)
        p.drawEllipse(QtCore.QPointF(cx, cy), self._d / 2.0, self._d / 2.0)


# =====================================================================
# Theme switcher — 3 colored swatches in the header
# =====================================================================
class ThemeSwitcher(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # caption
        cap = QtWidgets.QLabel("테마")
        cap.setFont(make_font(size_pt=8, weight=QtGui.QFont.Bold, letter_spacing=0.6))
        cap.setStyleSheet("color:%s; background:transparent;" % Color.TEXT_MUTED)
        self._cap = cap
        layout.addWidget(cap)

        self._buttons = {}
        for name, label, sample in THEME_LABELS:
            btn = QtWidgets.QPushButton()
            btn.setFixedSize(22, 22)
            btn.setCursor(QtCore.Qt.PointingHandCursor)
            btn.setCheckable(True)
            btn.setToolTip(label)
            btn.clicked.connect(lambda _checked, n=name: self._switch(n))
            self._buttons[name] = (btn, sample)
            layout.addWidget(btn)

        self._refresh_styles()
        self._update_check_states(current_theme())
        theme_bus.changed.connect(self._update_check_states)
        theme_bus.changed.connect(lambda _: self._refresh_styles())

    def _switch(self, name):
        app = QtWidgets.QApplication.instance()
        if app is not None and name != current_theme():
            apply_theme(app, name)

    def _update_check_states(self, current):
        for n, (btn, _) in self._buttons.items():
            btn.blockSignals(True)
            btn.setChecked(n == current)
            btn.blockSignals(False)

    def _refresh_styles(self):
        # caption color follows theme
        self._cap.setStyleSheet("color:%s; background:transparent;" % Color.TEXT_MUTED)
        for n, (btn, sample) in self._buttons.items():
            btn.setStyleSheet(
                "QPushButton {"
                "  background: %s;"
                "  border: 2px solid %s;"
                "  border-radius: 11px;"
                "}"
                "QPushButton:hover { border: 2px solid %s; }"
                "QPushButton:checked { border: 2px solid %s; }"
                % (sample, Color.BORDER_DEFAULT, Color.BORDER_STRONG, Color.ACCENT)
            )


# =====================================================================
# HeaderBar
# =====================================================================
class HeaderBar(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("role", "header")
        self.setFixedHeight(64)
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(20, 10, 20, 10)
        layout.setSpacing(14)

        # ---- Status indicator dot ----
        self.dot = _PulseDot(diameter=10)

        # ---- Brand block ----
        brand_box = QtWidgets.QVBoxLayout()
        brand_box.setSpacing(0)
        brand_box.setContentsMargins(0, 0, 0, 0)

        self.lbl_brand = QtWidgets.QLabel("RAIM SCOPE")
        self.lbl_brand.setFont(brand_font())

        self.lbl_sub = QtWidgets.QLabel("BF · DF · DPC · 합성RGB  ·  Sense HAT 2 조명")
        self.lbl_sub.setFont(make_font(size_pt=8, letter_spacing=0.0))

        brand_box.addWidget(self.lbl_brand)
        brand_box.addWidget(self.lbl_sub)

        # ---- Theme switcher ----
        self.theme_switcher = ThemeSwitcher()

        # ---- Right side: state pill ----
        right = QtWidgets.QHBoxLayout()
        right.setSpacing(8)

        self.lbl_state_caption = QtWidgets.QLabel("상태")
        self.lbl_state_caption.setFont(make_font(size_pt=8, weight=QtGui.QFont.Bold, letter_spacing=0.6))

        self.lbl_state = QtWidgets.QLabel("대기")
        self.lbl_state.setFont(value_font())

        right.addWidget(self.lbl_state_caption)
        right.addWidget(self.lbl_state)

        # ---- Assemble ----
        layout.addWidget(self.dot)
        layout.addLayout(brand_box)
        layout.addStretch(1)
        layout.addWidget(self.theme_switcher)
        layout.addSpacing(20)
        layout.addLayout(right)

        # ---- Theme refresh ----
        self._refresh_inline_styles("init")
        theme_bus.changed.connect(self._refresh_inline_styles)
        # Reset state pill to "대기" on theme change
        self._current_state = "ready"

    # ---- inline color refresh on theme change ----
    def _refresh_inline_styles(self, _name):
        self.lbl_brand.setStyleSheet(
            "color:%s; background:transparent;" % Color.TEXT_PRIMARY
        )
        self.lbl_sub.setStyleSheet(
            "color:%s; background:transparent;" % Color.TEXT_MUTED
        )
        self.lbl_state_caption.setStyleSheet(
            "color:%s; background:transparent;" % Color.TEXT_MUTED
        )
        # restore current state pill colors
        if hasattr(self, "_current_state"):
            self._apply_state_pill(self._current_state)

    @staticmethod
    def _pill_style(text_color):
        return (
            "background: %s;"
            "border: 1px solid %s;"
            "border-radius: 10px;"
            "padding: 4px 14px;"
            "color: %s;"
        ) % (Color.PILL_BG, Color.BORDER_DEFAULT, text_color)

    def _apply_state_pill(self, state):
        if state == "live":
            self.lbl_state.setText("실시간")
            self.lbl_state.setStyleSheet(self._pill_style(Color.GREEN))
        elif state == "capturing":
            self.lbl_state.setText("촬영 중")
            self.lbl_state.setStyleSheet(self._pill_style(Color.AMBER))
        else:
            self.lbl_state.setText("대기")
            self.lbl_state.setStyleSheet(self._pill_style(Color.TEXT_SECONDARY))

    # ---- public API ----
    def set_camera_active(self, active: bool):
        self._current_state = "live" if active else "ready"
        self.dot.set_active(active, Color.GREEN)
        self._apply_state_pill(self._current_state)

    def set_capturing(self):
        self._current_state = "capturing"
        self.dot.set_active(True, Color.AMBER)
        self._apply_state_pill(self._current_state)
