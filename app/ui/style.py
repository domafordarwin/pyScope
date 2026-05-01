# app/ui/style.py
# -*- coding: utf-8 -*-
"""
RAIM Scope - Design System with three switchable themes.

Themes:
  * "light"  — bright instrument console (default)
  * "blue"   — original deep navy with neon cyan accent
  * "black"  — pure industrial dark (JEOL/SEM style)

Use apply_theme(app, name) to activate a theme. Subscribe to
theme_bus.changed(str) to refresh inline styles when the theme changes.
"""

from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtGui import QColor, QFont, QPalette


# =====================================================================
# Theme palettes
# =====================================================================
class _LightTheme:
    """Bright Leica/Zeiss-inspired instrument console."""
    BG_DEEP    = "#bfc4cb"
    BG_BASE    = "#cad0d6"
    BG_ELEV_1  = "#f0f3f6"
    BG_ELEV_2  = "#f8fafc"
    BG_ELEV_3  = "#ffffff"
    INPUT_BG   = "#dde1e6"
    TITLE_STRIP = "#dce1e6"
    CANVAS_DARK = "#1a1d22"
    CANVAS_TEXT = "#828892"

    BORDER_SUBTLE  = "rgba(0,0,0,0.12)"
    BORDER_DEFAULT = "rgba(0,0,0,0.22)"
    BORDER_STRONG  = "rgba(0,0,0,0.35)"
    BORDER_DEPTH   = "rgba(0,0,0,0.32)"

    TEXT_PRIMARY   = "#15191f"
    TEXT_SECONDARY = "#3e4651"
    TEXT_MUTED     = "#626973"
    TEXT_DIM       = "#8a919a"

    ACCENT       = "#1f6aa6"
    ACCENT_HOVER = "#2a7bbb"
    ACCENT_PRESS = "#155485"
    ACCENT_GLOW  = "rgba(31,106,166,0.20)"
    ACCENT_DEEP  = "rgba(31,106,166,0.08)"

    AMBER  = "#a06a1f"
    GREEN  = "#3f7843"
    RED    = "#9c3e3e"
    PURPLE = "#5d4f99"

    HIGHLIGHT_TEXT   = "#ffffff"
    PRIMARY_BTN_TEXT = "#ffffff"
    PILL_BG          = "rgba(0,0,0,0.04)"


class _BlueTheme:
    """Original deep navy with neon cyan accent."""
    BG_DEEP    = "#0a0c10"
    BG_BASE    = "#0f131a"
    BG_ELEV_1  = "#131820"
    BG_ELEV_2  = "#1a2029"
    BG_ELEV_3  = "#232b37"
    INPUT_BG   = "#0a0c10"
    TITLE_STRIP = "#1a2029"
    CANVAS_DARK = "#0a0c10"
    CANVAS_TEXT = "#828892"

    BORDER_SUBTLE  = "rgba(255,255,255,0.08)"
    BORDER_DEFAULT = "rgba(255,255,255,0.14)"
    BORDER_STRONG  = "rgba(255,255,255,0.24)"
    BORDER_DEPTH   = "rgba(0,0,0,0.40)"

    TEXT_PRIMARY   = "#e6edf5"
    TEXT_SECONDARY = "#a8b3bf"
    TEXT_MUTED     = "#6b7785"
    TEXT_DIM       = "#4a5260"

    ACCENT       = "#5ec8ff"
    ACCENT_HOVER = "#7ad4ff"
    ACCENT_PRESS = "#3fbcff"
    ACCENT_GLOW  = "rgba(94,200,255,0.18)"
    ACCENT_DEEP  = "rgba(94,200,255,0.06)"

    AMBER  = "#ffb547"
    GREEN  = "#4ade80"
    RED    = "#ef4444"
    PURPLE = "#a78bfa"

    HIGHLIGHT_TEXT   = "#0a0c10"
    PRIMARY_BTN_TEXT = "#0a0c10"
    PILL_BG          = "rgba(255,255,255,0.04)"


class _BlackTheme:
    """Pure industrial dark — JEOL/SEM instrument feel."""
    BG_DEEP    = "#161616"
    BG_BASE    = "#1c1c1c"
    BG_ELEV_1  = "#262626"
    BG_ELEV_2  = "#303030"
    BG_ELEV_3  = "#3a3a3a"
    INPUT_BG   = "#0e0e0e"
    TITLE_STRIP = "#1f1f1f"
    CANVAS_DARK = "#0a0a0a"
    CANVAS_TEXT = "#828892"

    BORDER_SUBTLE  = "rgba(255,255,255,0.07)"
    BORDER_DEFAULT = "rgba(255,255,255,0.18)"
    BORDER_STRONG  = "rgba(255,255,255,0.32)"
    BORDER_DEPTH   = "rgba(0,0,0,0.50)"

    TEXT_PRIMARY   = "#ececec"
    TEXT_SECONDARY = "#b4b4b4"
    TEXT_MUTED     = "#7e7e7e"
    TEXT_DIM       = "#555555"

    ACCENT       = "#5fa8d3"
    ACCENT_HOVER = "#79b8de"
    ACCENT_PRESS = "#4889b0"
    ACCENT_GLOW  = "rgba(95,168,211,0.20)"
    ACCENT_DEEP  = "rgba(95,168,211,0.08)"

    AMBER  = "#d4a25c"
    GREEN  = "#6ac46a"
    RED    = "#d27676"
    PURPLE = "#a78bd9"

    HIGHLIGHT_TEXT   = "#0a0a0a"
    PRIMARY_BTN_TEXT = "#0a0a0a"
    PILL_BG          = "rgba(255,255,255,0.04)"


THEMES = {
    "light": _LightTheme,
    "blue":  _BlueTheme,
    "black": _BlackTheme,
}

# (label, swatch sample color) — used by the header theme switcher
THEME_LABELS = (
    ("light", "라이트 회색", "#cad0d6"),
    ("blue",  "딥 블루",     "#0f131a"),
    ("black", "블랙",         "#1c1c1c"),
)


# =====================================================================
# Live theme reference — Color.* attributes mutate when theme changes.
# =====================================================================
class Color:
    """Active theme tokens. Values switch when apply_theme runs."""
    pass


def _activate(theme_cls):
    for k, v in vars(theme_cls).items():
        if not k.startswith("_"):
            setattr(Color, k, v)


# Bootstrap before any other module reads Color.*
_activate(_LightTheme)


# =====================================================================
# Theme change bus — widgets with inline styles subscribe here
# =====================================================================
class _ThemeBus(QtCore.QObject):
    changed = QtCore.pyqtSignal(str)


theme_bus = _ThemeBus()
_current_theme_name = "light"


def current_theme():
    return _current_theme_name


# =====================================================================
# Font selection (Korean + Latin friendly)
# =====================================================================
def _pick_font_family():
    db = QtGui.QFontDatabase()
    installed = {f.lower() for f in db.families()}
    priority = (
        "Pretendard Variable", "Pretendard",
        "Noto Sans KR", "Spoqa Han Sans Neo",
        "Malgun Gothic", "맑은 고딕",
        "Apple SD Gothic Neo",
        "Segoe UI Variable", "Segoe UI",
        "Inter", "Sans Serif",
    )
    for fam in priority:
        if fam.lower() in installed:
            return fam
    return "Sans Serif"


_UI_FONT_FAMILY = "Sans Serif"


# =====================================================================
# Apply / switch theme
# =====================================================================
def apply_theme(app: QtWidgets.QApplication, theme_name: str = "light"):
    """Activate a theme and notify subscribers."""
    global _UI_FONT_FAMILY, _current_theme_name

    theme_cls = THEMES.get(theme_name, _LightTheme)
    _activate(theme_cls)
    _current_theme_name = theme_name

    # Resolve font family once (first call), reuse afterwards.
    if _UI_FONT_FAMILY == "Sans Serif":
        _UI_FONT_FAMILY = _pick_font_family()

    base = QFont(_UI_FONT_FAMILY)
    base.setPointSize(10)
    base.setStyleStrategy(QFont.PreferAntialias)
    app.setFont(base)

    # Palette
    pal = QPalette()
    pal.setColor(QPalette.Window,          QColor(Color.BG_DEEP))
    pal.setColor(QPalette.WindowText,      QColor(Color.TEXT_PRIMARY))
    pal.setColor(QPalette.Base,            QColor(Color.BG_ELEV_1))
    pal.setColor(QPalette.AlternateBase,   QColor(Color.BG_ELEV_2))
    pal.setColor(QPalette.ToolTipBase,     QColor(Color.BG_ELEV_3))
    pal.setColor(QPalette.ToolTipText,     QColor(Color.TEXT_PRIMARY))
    pal.setColor(QPalette.Text,            QColor(Color.TEXT_PRIMARY))
    pal.setColor(QPalette.Button,          QColor(Color.BG_ELEV_2))
    pal.setColor(QPalette.ButtonText,      QColor(Color.TEXT_PRIMARY))
    pal.setColor(QPalette.Highlight,       QColor(Color.ACCENT))
    pal.setColor(QPalette.HighlightedText, QColor(Color.HIGHLIGHT_TEXT))
    pal.setColor(QPalette.PlaceholderText, QColor(Color.TEXT_MUTED))
    app.setPalette(pal)

    app.setStyleSheet(app_qss())

    theme_bus.changed.emit(theme_name)


# =====================================================================
# Font helpers — Korean-friendly defaults
# =====================================================================
def make_font(size_pt=10, weight=QFont.Normal, letter_spacing=0.0, family=None):
    f = QFont(family if family else _UI_FONT_FAMILY)
    f.setPointSize(size_pt)
    f.setWeight(weight)
    if letter_spacing:
        f.setLetterSpacing(QFont.AbsoluteSpacing, letter_spacing)
    return f


def section_title_font():
    return make_font(size_pt=9, weight=QFont.Bold, letter_spacing=0.6)


def brand_font():
    # English brand "RAIM SCOPE" — slightly tracked for branded feel.
    return make_font(size_pt=13, weight=QFont.Bold, letter_spacing=1.8)


def value_font():
    # Pills like 대기 / 실시간 / 촬영 중 — Korean, no spacing.
    return make_font(size_pt=11, weight=QFont.DemiBold, letter_spacing=0.0)


def korean_font(size_pt=10, weight=QFont.Normal):
    return make_font(size_pt=size_pt, weight=weight, letter_spacing=0.0)


# =====================================================================
# Reusable widget builders
# =====================================================================
def make_separator(orientation="h", strong=False):
    line = QtWidgets.QFrame()
    if orientation == "h":
        line.setFrameShape(QtWidgets.QFrame.HLine)
        line.setFixedHeight(1)
    else:
        line.setFrameShape(QtWidgets.QFrame.VLine)
        line.setFixedWidth(1)
    line.setProperty("role", "column-divider" if strong else "separator")
    return line


def make_status_dot(color_hex, diameter=8):
    dot = QtWidgets.QLabel()
    dot.setFixedSize(diameter, diameter)
    dot.setStyleSheet(
        "background:%s; border-radius:%dpx;" % (color_hex, diameter // 2)
    )
    return dot


def add_card_shadow(widget, blur=22, y_offset=3, alpha=55):
    shadow = QtWidgets.QGraphicsDropShadowEffect(widget)
    shadow.setBlurRadius(blur)
    shadow.setOffset(0, y_offset)
    shadow.setColor(QColor(0, 0, 0, alpha))
    widget.setGraphicsEffect(shadow)
    return shadow


def hex_to_rgb_str(h):
    """#rrggbb -> 'r,g,b' (used to compose rgba in QSS)."""
    h = h.lstrip("#")
    return "%d,%d,%d" % (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


# =====================================================================
# Application stylesheet
# =====================================================================
def app_qss() -> str:
    C = Color
    green_rgb = hex_to_rgb_str(C.GREEN)
    red_rgb   = hex_to_rgb_str(C.RED)

    return """
    /* ============== Top-level surfaces ============== */
    QMainWindow,
    QDialog {
        background: %(bg_deep)s;
    }
    QDockWidget > QWidget,
    QStackedWidget,
    QMainWindow > QWidget#centralWidget {
        background: %(bg_deep)s;
    }

    /* ============== Labels ============== */
    QLabel {
        background: transparent;
        color: %(text_secondary)s;
    }
    QLabel[role="muted"]   { color: %(text_muted)s; font-size: 11px; }
    QLabel[role="value"]   { color: %(accent)s; font-weight: 600; }
    QLabel[role="caption"] {
        color: %(text_muted)s;
        font-size: 11px;
        font-weight: 600;
        padding-bottom: 2px;
    }
    QLabel[role="title"] {
        color: %(text_primary)s;
        font-weight: 800;
        font-size: 12px;
        padding: 5px 11px 6px 11px;
        background: %(title_strip)s;
        border: 1px solid %(border_default)s;
        border-left: 3px solid %(accent)s;
        border-radius: 4px;
    }

    /* ============== Group boxes (panel cards with title strip) ============== */
    QGroupBox {
        background: %(bg_elev_1)s;
        border: 1px solid %(border_default)s;
        border-radius: 8px;
        margin-top: 30px;
        padding: 12px 12px 10px 12px;
        color: %(text_primary)s;
        font-size: 11px;
        font-weight: 700;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        subcontrol-position: top left;
        left: -1px;
        top: 0px;
        padding: 6px 14px 6px 14px;
        color: %(text_primary)s;
        background: %(title_strip)s;
        border: 1px solid %(border_default)s;
        border-bottom: none;
        border-left: 3px solid %(accent)s;
        border-top-left-radius: 8px;
        border-top-right-radius: 8px;
    }
    QGroupBox QGroupBox {
        background: %(bg_elev_2)s;
        border: 1px solid %(border_subtle)s;
        margin-top: 22px;
    }
    QGroupBox QGroupBox::title {
        background: %(bg_elev_1)s;
    }

    /* ============== Buttons (default — pseudo-3D) ============== */
    QPushButton {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 %(bg_elev_3)s, stop:1 %(bg_elev_2)s);
        border: 1px solid %(border_default)s;
        border-bottom: 1px solid %(border_depth)s;
        border-radius: 6px;
        padding: 7px 14px;
        color: %(text_primary)s;
        font-size: 11px;
        font-weight: 600;
        min-height: 22px;
    }
    QPushButton:hover {
        background: %(bg_elev_3)s;
        border-color: %(border_strong)s;
    }
    QPushButton:pressed {
        background: %(bg_elev_1)s;
        border-top: 1px solid %(border_depth)s;
        border-bottom: 1px solid %(border_default)s;
        padding-top: 8px;
        padding-bottom: 6px;
    }
    QPushButton:disabled {
        color: %(text_dim)s;
        background: %(bg_elev_1)s;
        border-color: %(border_subtle)s;
    }
    QPushButton:checked {
        background: %(accent_glow)s;
        border-color: %(accent)s;
        color: %(accent_press)s;
        font-weight: 700;
    }

    /* ============== Buttons (primary) ============== */
    QPushButton[role="primary"] {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 %(accent_hover)s, stop:1 %(accent_press)s);
        border: 1px solid %(accent_press)s;
        color: %(primary_btn_text)s;
        font-weight: 700;
    }
    QPushButton[role="primary"]:hover {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 %(accent_hover)s, stop:1 %(accent)s);
    }
    QPushButton[role="primary"]:pressed {
        background: %(accent_press)s;
    }
    QPushButton[role="primary"]:disabled {
        background: %(bg_elev_1)s;
        color: %(text_dim)s;
        border-color: %(border_subtle)s;
    }

    /* ============== Buttons (success / danger) ============== */
    QPushButton[role="success"] {
        background: rgba(%(green_rgb)s,0.18);
        border: 1px solid rgba(%(green_rgb)s,0.55);
        color: %(green)s;
        font-weight: 700;
    }
    QPushButton[role="success"]:hover {
        background: rgba(%(green_rgb)s,0.28);
        border-color: %(green)s;
    }
    QPushButton[role="danger"] {
        background: rgba(%(red_rgb)s,0.18);
        border: 1px solid rgba(%(red_rgb)s,0.55);
        color: %(red)s;
        font-weight: 700;
    }
    QPushButton[role="danger"]:hover {
        background: rgba(%(red_rgb)s,0.28);
        border-color: %(red)s;
    }
    QPushButton[role="danger"]:disabled {
        background: %(bg_elev_1)s;
        color: %(text_dim)s;
        border-color: %(border_subtle)s;
    }

    /* ============== Buttons (ghost) ============== */
    QPushButton[role="ghost"] {
        background: transparent;
        border: 1px solid %(border_subtle)s;
        border-bottom: 1px solid %(border_default)s;
        color: %(text_secondary)s;
    }
    QPushButton[role="ghost"]:hover {
        background: %(bg_elev_2)s;
        color: %(text_primary)s;
    }

    /* ============== Inputs (recessed) ============== */
    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
        background: %(input_bg)s;
        border: 1px solid %(border_default)s;
        border-top: 1px solid %(border_depth)s;
        border-radius: 6px;
        padding: 6px 10px;
        color: %(text_primary)s;
        selection-background-color: %(accent_glow)s;
        selection-color: %(text_primary)s;
        min-height: 18px;
    }
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
        border: 1px solid %(accent)s;
        background: %(bg_elev_1)s;
    }
    QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {
        border-color: %(border_strong)s;
    }
    QSpinBox::up-button, QSpinBox::down-button,
    QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
        background: transparent;
        border: none;
        width: 14px;
    }

    /* ============== Slider ============== */
    QSlider { min-height: 22px; }
    QSlider::groove:horizontal {
        border: none;
        height: 4px;
        background: %(input_bg)s;
        border-radius: 2px;
    }
    QSlider::sub-page:horizontal {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 %(accent_press)s, stop:1 %(accent)s);
        border-radius: 2px;
    }
    QSlider::add-page:horizontal {
        background: %(input_bg)s;
        border-radius: 2px;
    }
    QSlider::handle:horizontal {
        background: %(text_primary)s;
        border: 2px solid %(accent)s;
        width: 14px;
        height: 14px;
        margin: -7px 0;
        border-radius: 8px;
    }
    QSlider::handle:horizontal:hover {
        background: %(accent)s;
        border-color: %(text_primary)s;
    }

    /* ============== Tabs ============== */
    QTabWidget::pane {
        border: 1px solid %(border_default)s;
        border-radius: 8px;
        background: %(bg_elev_1)s;
        top: -1px;
    }
    QTabBar { background: transparent; }
    QTabBar::tab {
        background: %(title_strip)s;
        color: %(text_muted)s;
        padding: 8px 22px;
        border: 1px solid %(border_default)s;
        border-bottom: none;
        border-top-left-radius: 6px;
        border-top-right-radius: 6px;
        margin-right: 3px;
        font-weight: 700;
        font-size: 11px;
    }
    QTabBar::tab:hover {
        background: %(bg_elev_2)s;
        color: %(text_secondary)s;
    }
    QTabBar::tab:selected {
        background: %(bg_elev_1)s;
        color: %(accent_press)s;
        border-top: 3px solid %(accent)s;
        border-bottom: 1px solid %(bg_elev_1)s;
        padding-top: 6px;
    }

    /* ============== Dock ============== */
    QDockWidget { color: %(text_primary)s; }
    QDockWidget::title {
        text-align: left;
        background: %(title_strip)s;
        padding: 10px 16px;
        border: 1px solid %(border_default)s;
        border-bottom: none;
        border-top-left-radius: 8px;
        border-top-right-radius: 8px;
        border-left: 3px solid %(accent)s;
        font-weight: 800;
        color: %(text_primary)s;
    }

    /* ============== Status bar ============== */
    QStatusBar {
        background: %(title_strip)s;
        color: %(text_secondary)s;
        border-top: 1px solid %(border_default)s;
        padding: 6px 14px;
        font-size: 11px;
        font-weight: 500;
    }
    QStatusBar::item { border: none; }

    /* ============== List widget ============== */
    QListWidget {
        background: %(input_bg)s;
        border: 1px solid %(border_default)s;
        border-radius: 8px;
        padding: 4px;
        outline: none;
    }
    QListWidget::item {
        color: %(text_secondary)s;
        border-radius: 5px;
        padding: 2px;
        margin: 2px;
    }
    QListWidget::item:hover { background: %(bg_elev_2)s; }
    QListWidget::item:selected {
        background: %(accent_glow)s;
        color: %(accent_press)s;
        border: 1px solid %(accent)s;
    }

    /* ============== Frame separators ============== */
    QFrame[role="separator"]      { background: %(border_subtle)s; border: none; }
    QFrame[role="column-divider"] { background: %(border_default)s; border: none; }

    /* ============== Custom semantic surfaces ============== */
    QWidget[role="header"] {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 %(bg_elev_1)s, stop:1 %(title_strip)s);
        border-bottom: 2px solid %(accent)s;
    }
    QFrame[role="toolbar"] {
        background: %(title_strip)s;
        border-bottom: 1px solid %(border_default)s;
    }
    QWidget[role="surface"] {
        background: %(bg_elev_1)s;
        border: 1px solid %(border_default)s;
        border-radius: 8px;
    }
    QLabel[role="canvas"] {
        background: %(canvas_dark)s;
        border: 1px solid %(border_default)s;
        border-radius: 8px;
        color: %(canvas_text)s;
    }

    /* ============== Splitter ============== */
    QSplitter::handle { background: %(border_subtle)s; }
    QSplitter::handle:hover { background: %(accent_glow)s; }

    /* ============== Scroll ============== */
    QScrollArea, QScrollArea > QWidget > QWidget {
        background: transparent;
        border: none;
    }
    QAbstractScrollArea { background: transparent; }
    QScrollBar:vertical {
        background: transparent; width: 10px; margin: 2px;
    }
    QScrollBar::handle:vertical {
        background: %(border_default)s; border-radius: 4px; min-height: 30px;
    }
    QScrollBar::handle:vertical:hover { background: %(border_strong)s; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0; background: transparent;
    }
    QScrollBar:horizontal {
        background: transparent; height: 10px; margin: 2px;
    }
    QScrollBar::handle:horizontal {
        background: %(border_default)s; border-radius: 4px; min-width: 30px;
    }
    QScrollBar::handle:horizontal:hover { background: %(border_strong)s; }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
        width: 0; background: transparent;
    }

    /* ============== ToolTip ============== */
    QToolTip {
        background: %(bg_elev_3)s;
        color: %(text_primary)s;
        border: 1px solid %(border_strong)s;
        padding: 6px 10px;
        border-radius: 6px;
        font-size: 11px;
    }
    """ % {
        "bg_deep":           C.BG_DEEP,
        "bg_base":           C.BG_BASE,
        "bg_elev_1":         C.BG_ELEV_1,
        "bg_elev_2":         C.BG_ELEV_2,
        "bg_elev_3":         C.BG_ELEV_3,
        "input_bg":          C.INPUT_BG,
        "title_strip":       C.TITLE_STRIP,
        "canvas_dark":       C.CANVAS_DARK,
        "canvas_text":       C.CANVAS_TEXT,
        "border_subtle":     C.BORDER_SUBTLE,
        "border_default":    C.BORDER_DEFAULT,
        "border_strong":     C.BORDER_STRONG,
        "border_depth":      C.BORDER_DEPTH,
        "text_primary":      C.TEXT_PRIMARY,
        "text_secondary":    C.TEXT_SECONDARY,
        "text_muted":        C.TEXT_MUTED,
        "text_dim":          C.TEXT_DIM,
        "accent":            C.ACCENT,
        "accent_hover":      C.ACCENT_HOVER,
        "accent_press":      C.ACCENT_PRESS,
        "accent_glow":       C.ACCENT_GLOW,
        "primary_btn_text":  C.PRIMARY_BTN_TEXT,
        "green":             C.GREEN,
        "red":               C.RED,
        "green_rgb":         green_rgb,
        "red_rgb":           red_rgb,
    }
