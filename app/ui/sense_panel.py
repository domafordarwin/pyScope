# app/ui/sense_panel.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from PyQt5 import QtCore, QtGui, QtWidgets

from .style import Color, make_separator, theme_bus

# Sense HAT 2 (없어도 GUI가 뜨도록 안전 처리)
try:
    from sense_hat import SenseHat
    SENSE_OK = True
except Exception:
    SenseHat = None
    SENSE_OK = False


# =====================================================================
# LED grid widget — visual representation of the 8x8 Sense HAT 2 LED matrix.
# Renders cells with radial gradient + soft outer halo for the "on" state,
# giving each lit pixel a real-LED feel.
# =====================================================================
class LedGridWidget(QtWidgets.QWidget):
    pixel_toggled = QtCore.pyqtSignal(int, int, bool)

    def __init__(self, parent=None, cell_size=24, margin=12):
        super().__init__(parent)
        self.N = 8
        self.cell = cell_size
        self.margin = margin
        self.setMinimumSize(
            self.N * self.cell + 2 * self.margin,
            self.N * self.cell + 2 * self.margin,
        )

        self.on = [[False] * self.N for _ in range(self.N)]
        self.display_rgb_on = (180, 200, 220)

        self._dragging = False
        self._drag_mode_on = True
        self._last_cell = None
        self.setMouseTracking(True)

        # repaint substrate / cell colors on theme change
        theme_bus.changed.connect(lambda _: self.update())

    # ---- public API ----
    def set_display_on_color(self, rgb):
        self.display_rgb_on = tuple(int(max(0, min(255, v))) for v in rgb)
        self.update()

    def clear_all(self, emit=False):
        for y in range(self.N):
            for x in range(self.N):
                if self.on[y][x]:
                    self.on[y][x] = False
                    if emit:
                        self.pixel_toggled.emit(x, y, False)
        self.update()

    def set_from_bool64(self, flat64, emit=False):
        if not flat64 or len(flat64) != 64:
            return
        k = 0
        for y in range(self.N):
            for x in range(self.N):
                new_state = bool(flat64[k])
                if self.on[y][x] != new_state:
                    self.on[y][x] = new_state
                    if emit:
                        self.pixel_toggled.emit(x, y, new_state)
                k += 1
        self.update()

    def get_state_flat(self):
        out = []
        for y in range(self.N):
            for x in range(self.N):
                out.append(bool(self.on[y][x]))
        return out

    # ---- input ----
    def _pos_to_cell(self, pos):
        x0 = pos.x() - self.margin
        y0 = pos.y() - self.margin
        if x0 < 0 or y0 < 0:
            return None
        cx = x0 // self.cell
        cy = y0 // self.cell
        if 0 <= cx < self.N and 0 <= cy < self.N:
            return int(cx), int(cy)
        return None

    def mousePressEvent(self, event):
        cell = self._pos_to_cell(event.pos())
        if cell is None:
            return
        x, y = cell

        if event.button() == QtCore.Qt.LeftButton:
            new_state = not self.on[y][x]
            self.on[y][x] = new_state
            self.pixel_toggled.emit(x, y, new_state)
            self._dragging = True
            self._drag_mode_on = True
            self._last_cell = (x, y)
        elif event.button() == QtCore.Qt.RightButton:
            if self.on[y][x]:
                self.on[y][x] = False
                self.pixel_toggled.emit(x, y, False)
            self._dragging = True
            self._drag_mode_on = False
            self._last_cell = (x, y)

        self.update()

    def mouseMoveEvent(self, event):
        if not self._dragging:
            return
        cell = self._pos_to_cell(event.pos())
        if cell is None:
            return
        if cell == self._last_cell:
            return
        x, y = cell

        if self._drag_mode_on:
            if not self.on[y][x]:
                self.on[y][x] = True
                self.pixel_toggled.emit(x, y, True)
        else:
            if self.on[y][x]:
                self.on[y][x] = False
                self.pixel_toggled.emit(x, y, False)

        self._last_cell = (x, y)
        self.update()

    def mouseReleaseEvent(self, event):
        self._dragging = False
        self._last_cell = None

    # ---- paint ----
    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)

        # Fill widget bg to match parent panel (no light fringe around dark plate)
        p.fillRect(self.rect(), QtGui.QColor(Color.BG_ELEV_1))

        # Substrate panel — dark island that holds the LED matrix.
        # Always uses CANVAS_DARK so it visually pairs with the image canvases.
        plate = self.rect().adjusted(4, 4, -4, -4)
        p.setBrush(QtGui.QColor(Color.CANVAS_DARK))
        p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 60), 1))
        p.drawRoundedRect(plate, 12, 12)

        r_on = self.display_rgb_on
        for y in range(self.N):
            for x in range(self.N):
                rx = self.margin + x * self.cell
                ry = self.margin + y * self.cell
                cell_rect = QtCore.QRectF(
                    rx + 2, ry + 2, self.cell - 6, self.cell - 6
                )

                if self.on[y][x]:
                    self._paint_lit_cell(p, cell_rect, r_on)
                else:
                    self._paint_dark_cell(p, cell_rect)

    @staticmethod
    def _paint_lit_cell(p, rect, rgb):
        # Outer glow halo
        glow = QtGui.QColor(rgb[0], rgb[1], rgb[2])
        glow.setAlpha(70)
        halo = rect.adjusted(-4, -4, 4, 4)
        p.setBrush(glow)
        p.setPen(QtCore.Qt.NoPen)
        p.drawRoundedRect(halo, 10, 10)

        # Core LED — radial gradient (bright center, darker edge)
        center = QtGui.QColor(
            min(255, int(rgb[0] * 1.15) + 30),
            min(255, int(rgb[1] * 1.15) + 30),
            min(255, int(rgb[2] * 1.15) + 30),
        )
        edge = QtGui.QColor(
            int(rgb[0] * 0.55),
            int(rgb[1] * 0.55),
            int(rgb[2] * 0.55),
        )
        grad = QtGui.QRadialGradient(rect.center(), rect.width() * 0.7)
        grad.setColorAt(0.0, center)
        grad.setColorAt(0.6, QtGui.QColor(rgb[0], rgb[1], rgb[2]))
        grad.setColorAt(1.0, edge)
        p.setBrush(QtGui.QBrush(grad))
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 90), 1))
        p.drawRoundedRect(rect, 6, 6)

        # Tiny specular highlight
        spec = QtCore.QRectF(
            rect.x() + rect.width() * 0.18,
            rect.y() + rect.height() * 0.16,
            rect.width() * 0.32,
            rect.height() * 0.20,
        )
        p.setBrush(QtGui.QColor(255, 255, 255, 90))
        p.setPen(QtCore.Qt.NoPen)
        p.drawEllipse(spec)

    @staticmethod
    def _paint_dark_cell(p, rect):
        # Dark slate sitting on the slightly darker substrate
        p.setBrush(QtGui.QColor(45, 51, 59))
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 26), 1))
        p.drawRoundedRect(rect, 6, 6)


# =====================================================================
# LED pattern presets
# =====================================================================
def _pat_all_on():    return [True] * 64
def _pat_clear():     return [False] * 64

def _pat_annulus(inner_r=3.0, outer_r=5.5):
    """
    환형(annular) 암시야 패턴.
    중심 (3.5, 3.5)에서 거리 inner_r ~ outer_r (셀 단위) 사이의 LED만 점등.

    선택 가이드 (Sense HAT 2 pitch 6.5mm, 시료 거리 100mm 기준):
      inner_r=1.5  →  대부분 LED 점등 (저 NA 4× 대물용, NA<0.13)
      inner_r=2.5  →  중간 NA 10× 대물용 (NA≈0.22)
      inner_r=3.0  →  외곽 링 (기본값, 옛 _pat_ring과 유사)
      inner_r=3.5  →  코너 4개 + 인접 (고 NA 20× 대물용)
      inner_r=4.5  →  코너 4개만 (극고 NA, 8x8로 한계)

    inner_r > outer_r 면 모두 꺼짐.
    """
    out = [False] * 64
    cx = cy = 3.5
    for y in range(8):
        for x in range(8):
            r = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
            if inner_r <= r <= outer_r:
                out[y * 8 + x] = True
    return out


def _pat_ring():
    """레거시 별칭 — 외곽 링 패턴 (annulus 3.0~5.5와 시각적으로 유사)."""
    return _pat_annulus(3.0, 5.5)

def _pat_half_left():
    out = [False] * 64
    for y in range(8):
        for x in range(4):
            out[y * 8 + x] = True
    return out

def _pat_half_right():
    out = [False] * 64
    for y in range(8):
        for x in range(4, 8):
            out[y * 8 + x] = True
    return out

def _pat_half_top():
    out = [False] * 64
    for y in range(4):
        for x in range(8):
            out[y * 8 + x] = True
    return out

def _pat_half_bottom():
    out = [False] * 64
    for y in range(4, 8):
        for x in range(8):
            out[y * 8 + x] = True
    return out


# =====================================================================
# SensePanel — illumination control (Sense HAT 2)
# =====================================================================
class SensePanel(QtWidgets.QGroupBox):
    brightness_changed = QtCore.pyqtSignal(int)
    color_changed = QtCore.pyqtSignal(tuple)
    off_clicked = QtCore.pyqtSignal()
    preset_clicked = QtCore.pyqtSignal(str)

    # Internal pattern key -> Korean display label
    # Note: DF label is computed dynamically in _refresh_mode_label() to include
    # the inner-radius value from the slider.
    _PATTERN_DISPLAY = {
        "OFF":         "끔",
        "BF":          "BF · 명시야",
        "DF":          "DF · 암시야",
        "DPC_LEFT":    "DPC ◀ 좌",
        "DPC_RIGHT":   "DPC ▶ 우",
        "DPC_TOP":     "DPC ▲ 상",
        "DPC_BOTTOM":  "DPC ▼ 하",
        "CUSTOM":      "사용자 정의",
    }

    # DF annulus geometry constants
    # Default tuned for NA 0.25 (10× achromat) at 60-80mm LED distance.
    # Higher NA / shorter distance → larger r;  lower NA / longer distance → smaller r.
    # Slide while watching the live view: contrast jumps when crossing the NA boundary.
    _DF_OUTER_RADIUS = 5.5      # fixed outer (corners distance ≈ 4.95)
    _DF_INNER_MIN_X10 = 10      # slider min × 10  → r = 1.0
    _DF_INNER_MAX_X10 = 45      # slider max × 10  → r = 4.5
    _DF_INNER_DEF_X10 = 25      # default              r = 2.5 (NA 0.25 @ ~70mm)

    def __init__(self, parent=None):
        super().__init__("조명  ·  SENSE HAT 2", parent)

        # SenseHat() construction can hang on Pi if I2C device is unresponsive
        # (e.g. HAT not seated, ribbon dislodged, conflicting kernel module).
        # We wrap it so a hardware failure degrades to UI-only mode instead of
        # freezing the whole GUI thread.
        self.sense = None
        if SENSE_OK:
            try:
                self.sense = SenseHat()
            except Exception as e:
                import sys
                print("[SensePanel] SenseHat() 초기화 실패: %r" % e, file=sys.stderr)
                self.sense = None

        self._pattern_name = "CUSTOM"

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(12, 14, 12, 12)
        root.setSpacing(10)

        # ---- Brightness ----
        cap_b = QtWidgets.QLabel("밝기")
        cap_b.setProperty("role", "caption")
        root.addWidget(cap_b)

        b_row = QtWidgets.QHBoxLayout()
        b_row.setSpacing(8)
        self.b_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.b_slider.setRange(0, 255)
        self.b_slider.setValue(255)
        self.b_value = QtWidgets.QLabel("255")
        self.b_value.setProperty("role", "value")
        self.b_value.setFixedWidth(36)
        self.b_value.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        # 드래그 중엔 라벨만 갱신 (I2C 호출 폭주 방지),
        # 놓을 때 또는 키보드/방향키 변경 시에만 실제 LED 적용
        self.b_slider.valueChanged.connect(self._on_brightness_value_changed)
        self.b_slider.sliderReleased.connect(self._on_brightness_released)
        b_row.addWidget(self.b_slider, 1)
        b_row.addWidget(self.b_value)
        root.addLayout(b_row)

        # ---- RGB ----
        cap_c = QtWidgets.QLabel("RGB 색상")
        cap_c.setProperty("role", "caption")
        root.addWidget(cap_c)

        c_row = QtWidgets.QHBoxLayout()
        c_row.setSpacing(6)
        self.r = QtWidgets.QSpinBox(); self.r.setRange(0, 255); self.r.setValue(180)
        self.g = QtWidgets.QSpinBox(); self.g.setRange(0, 255); self.g.setValue(180)
        self.b = QtWidgets.QSpinBox(); self.b.setRange(0, 255); self.b.setValue(180)
        for w in (self.r, self.g, self.b):
            w.valueChanged.connect(self._on_color)
            w.setMinimumWidth(56)
        c_row.addWidget(self.r)
        c_row.addWidget(self.g)
        c_row.addWidget(self.b)
        c_row.addStretch(1)
        root.addLayout(c_row)

        root.addSpacing(2)
        root.addWidget(make_separator("h"))
        root.addSpacing(2)

        # ---- Presets ----
        cap_p = QtWidgets.QLabel("모드 프리셋")
        cap_p.setProperty("role", "caption")
        root.addWidget(cap_p)

        pgrid = QtWidgets.QGridLayout()
        pgrid.setHorizontalSpacing(6)
        pgrid.setVerticalSpacing(6)

        self.btn_bf    = QtWidgets.QPushButton("BF · 명시야")
        self.btn_df    = QtWidgets.QPushButton("DF · 암시야")
        self.btn_df.setToolTip(
            "암시야 — 아래 슬라이더로 내경 반지름을 조정하세요\n"
            "(저배율 대물엔 작게, 고배율 대물엔 크게)"
        )
        self.btn_clear = QtWidgets.QPushButton("끔")
        self.btn_clear.setProperty("role", "danger")

        self.btn_dpc_l = QtWidgets.QPushButton("DPC ◀")
        self.btn_dpc_r = QtWidgets.QPushButton("DPC ▶")
        self.btn_dpc_t = QtWidgets.QPushButton("DPC ▲")
        self.btn_dpc_b = QtWidgets.QPushButton("DPC ▼")

        pgrid.addWidget(self.btn_bf,    0, 0)
        pgrid.addWidget(self.btn_df,    0, 1)
        pgrid.addWidget(self.btn_clear, 0, 2)
        pgrid.addWidget(self.btn_dpc_l, 1, 0)
        pgrid.addWidget(self.btn_dpc_r, 1, 1)
        pgrid.addWidget(self.btn_dpc_t, 2, 0)
        pgrid.addWidget(self.btn_dpc_b, 2, 1)
        root.addLayout(pgrid)

        # ---- DF inner radius (암시야 환형 안쪽 반지름) ----
        cap_df = QtWidgets.QLabel("DF 내경 반지름 (대물 NA ↑ 일수록 ↑)")
        cap_df.setProperty("role", "caption")
        root.addWidget(cap_df)

        df_row = QtWidgets.QHBoxLayout()
        df_row.setSpacing(8)
        self.df_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.df_slider.setRange(self._DF_INNER_MIN_X10, self._DF_INNER_MAX_X10)
        self.df_slider.setValue(self._DF_INNER_DEF_X10)
        self.df_slider.setSingleStep(1)
        self.df_slider.setPageStep(5)
        self.df_slider.setTickPosition(QtWidgets.QSlider.TicksBelow)
        self.df_slider.setTickInterval(5)
        self.df_slider.setToolTip(
            "DF 내경 반지름 (셀 단위, 1.0 ~ 4.5)\n"
            "1.5 ≈ 4× 대물,  2.5 ≈ 10× 대물,  3.0 ≈ 외곽 링,  3.5 ≈ 20× 대물"
        )
        self.df_value = QtWidgets.QLabel("3.0")
        self.df_value.setProperty("role", "value")
        self.df_value.setFixedWidth(40)
        self.df_value.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        # 같은 throttle 패턴: 드래그 중엔 라벨만, 놓을 때 LED 적용
        self.df_slider.valueChanged.connect(self._on_df_value_changed)
        self.df_slider.sliderReleased.connect(self._on_df_released)
        df_row.addWidget(self.df_slider, 1)
        df_row.addWidget(self.df_value)
        root.addLayout(df_row)

        root.addSpacing(4)

        # ---- LED grid (centered) ----
        grid_wrap = QtWidgets.QHBoxLayout()
        grid_wrap.addStretch(1)
        self.led_grid = LedGridWidget(cell_size=26, margin=14)
        grid_wrap.addWidget(self.led_grid)
        grid_wrap.addStretch(1)
        root.addLayout(grid_wrap)

        # ---- Mode + apply ----
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(8)
        cap_mode = QtWidgets.QLabel("모드")
        cap_mode.setProperty("role", "caption")
        self.lbl_mode = QtWidgets.QLabel(self._PATTERN_DISPLAY["CUSTOM"])
        self.lbl_mode.setProperty("role", "value")
        row.addWidget(cap_mode)
        row.addWidget(self.lbl_mode)
        row.addStretch(1)
        self.btn_apply = QtWidgets.QPushButton("LED에 적용")
        self.btn_apply.setProperty("role", "primary")
        row.addWidget(self.btn_apply)
        root.addLayout(row)

        # Sense HAT availability hint
        self._hint = None
        if not SENSE_OK:
            self._hint = QtWidgets.QLabel(
                "⚠  Sense HAT 2 미감지 — UI 그리드만 표시 (하드웨어 쓰기 비활성)"
            )
            self._hint.setProperty("role", "caption")
            self._hint.setWordWrap(True)
            self._refresh_hint_color()
            root.addWidget(self._hint)
        theme_bus.changed.connect(lambda _: self._refresh_hint_color())

        # ---- signals ----
        self.btn_clear.clicked.connect(lambda: self.apply_preset("OFF"))
        self.btn_bf.clicked.connect(lambda: self.apply_preset("BF"))
        self.btn_df.clicked.connect(lambda: self.apply_preset("DF"))
        self.btn_dpc_l.clicked.connect(lambda: self.apply_preset("DPC_LEFT"))
        self.btn_dpc_r.clicked.connect(lambda: self.apply_preset("DPC_RIGHT"))
        self.btn_dpc_t.clicked.connect(lambda: self.apply_preset("DPC_TOP"))
        self.btn_dpc_b.clicked.connect(lambda: self.apply_preset("DPC_BOTTOM"))

        self.btn_apply.clicked.connect(self.push_full_led_state)
        self.led_grid.pixel_toggled.connect(self._on_pixel_toggled)

        # initial
        self._apply_display_color()
        self.apply_preset("OFF")

    # ---- public getters for meta ----
    def get_color(self):
        return (self.r.value(), self.g.value(), self.b.value())

    def get_brightness(self):
        return self.b_slider.value()

    def effective_rgb(self):
        base = self.get_color()
        br = self.get_brightness()
        scale = br / 255.0
        return tuple(int(max(0, min(255, round(c * scale)))) for c in base)

    def current_pattern_name(self):
        return self._pattern_name

    def get_grid_state_flat(self):
        return self.led_grid.get_state_flat()

    # ---- UI events ----
    def _on_brightness_value_changed(self, v):
        # 드래그 중: 라벨/UI 색상만 갱신 (I2C 호출 안 함)
        self.b_value.setText(str(v))
        self._apply_display_color()
        if not self.b_slider.isSliderDown():
            # 드래그가 아닌 키보드/방향키/스텝 클릭 → 즉시 적용
            self.push_full_led_state()
            self.brightness_changed.emit(v)

    def _on_brightness_released(self):
        # 드래그 끝 → 최종 값으로 LED 적용
        self.push_full_led_state()
        self.brightness_changed.emit(self.b_slider.value())

    def _on_color(self):
        self._apply_display_color()
        self.push_full_led_state()
        self.color_changed.emit(self.get_color())

    def _apply_display_color(self):
        self.led_grid.set_display_on_color(self.effective_rgb())

    def _refresh_hint_color(self):
        if self._hint is not None:
            self._hint.setStyleSheet("color: %s;" % Color.AMBER)

    # ---- DF inner radius helpers ----
    def _df_inner_radius(self):
        return self.df_slider.value() / 10.0

    def _on_df_value_changed(self, v):
        # 드래그 중: 라벨만 갱신 (I2C 호출 폭주 방지)
        r = v / 10.0
        self.df_value.setText("%.1f" % r)
        if not self.df_slider.isSliderDown():
            # 드래그가 아닌 변경 (키보드 등) → 즉시 적용
            self._apply_df_pattern(r)

    def _on_df_released(self):
        # 드래그 끝 → 최종 반지름으로 LED 적용
        self._apply_df_pattern(self._df_inner_radius())

    def _apply_df_pattern(self, r):
        if self._pattern_name == "DF":
            flat = _pat_annulus(r, self._DF_OUTER_RADIUS)
            self.led_grid.set_from_bool64(flat, emit=False)
            self.push_full_led_state()
            self._refresh_mode_label()

    def _on_df_inner_changed(self, v):
        # 레거시 별칭 (외부에서 호출되는 경우 호환성 유지)
        self._on_df_value_changed(v)

    def _refresh_mode_label(self):
        name = self._pattern_name
        if name == "DF":
            self.lbl_mode.setText("DF · 암시야 (r=%.1f)" % self._df_inner_radius())
        else:
            self.lbl_mode.setText(self._PATTERN_DISPLAY.get(name, name))

    def _on_pixel_toggled(self, x, y, onoff):
        self._pattern_name = "CUSTOM"
        self._refresh_mode_label()
        if self.sense is None:
            return
        eff = self.effective_rgb()
        if onoff:
            self.sense.set_pixel(x, y, eff[0], eff[1], eff[2])
        else:
            self.sense.set_pixel(x, y, 0, 0, 0)

    # ---- presets ----
    def apply_preset(self, name: str):
        name = name.upper().strip()
        self._pattern_name = name

        if name == "OFF":
            flat = _pat_clear()
        elif name == "BF":
            flat = _pat_all_on()
        elif name == "DF":
            # 슬라이더의 현재 내경 반지름 사용 → NA 별 적응
            flat = _pat_annulus(self._df_inner_radius(), self._DF_OUTER_RADIUS)
        elif name == "DPC_LEFT":
            flat = _pat_half_left()
        elif name == "DPC_RIGHT":
            flat = _pat_half_right()
        elif name == "DPC_TOP":
            flat = _pat_half_top()
        elif name == "DPC_BOTTOM":
            flat = _pat_half_bottom()
        else:
            flat = None

        if flat is not None:
            self.led_grid.set_from_bool64(flat, emit=False)
            self.push_full_led_state()

        self._refresh_mode_label()
        self.preset_clicked.emit(self._pattern_name)

    # ---- Sense HAT apply ----
    def push_full_led_state(self):
        if self.sense is None:
            return
        eff = self.effective_rgb()
        state = self.led_grid.get_state_flat()
        pixels = [(eff if on else (0, 0, 0)) for on in state]
        self.sense.set_pixels(pixels)

    def clear(self):
        if self.sense is not None:
            self.sense.clear()
        self.led_grid.clear_all(emit=False)
        self._pattern_name = "OFF"
        self._refresh_mode_label()
