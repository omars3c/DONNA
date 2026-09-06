from __future__ import annotations

import collections
import ctypes
import json
import math
import os
import platform
import random
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import psutil

if platform.system() == "Windows":
    _WIN_HIDE: dict = {"creationflags": subprocess.CREATE_NO_WINDOW}
    _OS = "Windows"
elif platform.system() == "Darwin":
    _WIN_HIDE: dict = {}
    _OS = "Darwin"
else:
    _WIN_HIDE: dict = {}
    _OS = "Linux"

from PyQt6.QtCore import (
    QEasingCurve, QMimeData, QObject, QPointF, QRectF, QSize, Qt,
    QTimer, QUrl, pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush, QColor, QConicalGradient, QDragEnterEvent, QDropEvent, QFont,
    QFontDatabase, QFontMetricsF, QKeySequence, QLinearGradient, QPainter,
    QPainterPath, QPen, QPixmap, QRadialGradient, QShortcut,
)
from PyQt6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QPushButton, QScrollArea, QSizePolicy, QSplitter,
    QStackedWidget, QTextEdit, QVBoxLayout, QWidget, QProgressBar,
)
try:
    from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput, QVideoSink, QVideoFrame
    _QT_MULTIMEDIA_OK = True
except ImportError:
    _QT_MULTIMEDIA_OK = False

# ── Base Paths & Config ────────────────────────────────────────────────────────

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent

BASE_DIR   = _base_dir()
CONFIG_DIR = BASE_DIR / "config"
API_FILE   = CONFIG_DIR / "api_keys.json"


def _read_full_config() -> dict:
    try:
        return json.loads(API_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


# ── Theme & Dynamic Color Palette ──────────────────────────────────────────────

DEFAULT_UI_COLOR = "cyan"

COLOR_PRESETS = {
    "cyan":    {"PRI": "#00e5ff", "NAME": "Stark Cyan"},
    "teal":    {"PRI": "#00d2c4", "NAME": "Soft Teal"},
    "emerald": {"PRI": "#4aaa6a", "NAME": "Emerald Mint"},
    "amber":   {"PRI": "#d4a820", "NAME": "Amber Gold (Friday)"},
    "blue":    {"PRI": "#0099ff", "NAME": "Arc Reactor Blue"},
    "purple":  {"PRI": "#c755ff", "NAME": "Amethyst Core"},
    "red":     {"PRI": "#ff3355", "NAME": "Crimson Combat"},
}


class ThemePalette:
    def __init__(self, pri_hex: str = "#00e5ff"):
        self.set_accent(pri_hex)

    def set_accent(self, hex_val: str):
        self.PRI       = hex_val
        self.PRI_DIM   = self._alpha_hex(hex_val, 0.45)
        self.PRI_GHO   = self._alpha_hex(hex_val, 0.08)
        self.BG        = "#05090b"
        self.PANEL     = "#081014"
        self.PANEL2    = "#060b0e"
        self.DARK      = "#040709"
        self.BORDER    = self._alpha_hex(hex_val, 0.18)
        self.BORDER_B  = self._alpha_hex(hex_val, 0.38)
        self.BORDER_DIM= self._alpha_hex(hex_val, 0.08)
        self.GREEN     = "#4aaa6a"
        self.GREEN_DIM = "rgba(74, 170, 106, 0.25)"
        self.GREEN_GHO = "rgba(74, 170, 106, 0.08)"
        self.RED       = "#cc4444"
        self.RED_DIM   = "rgba(204, 68, 68, 0.3)"
        self.RED_GHO   = "rgba(204, 68, 68, 0.1)"
        self.MUTED_C   = "#e05555"
        self.ACC       = hex_val
        self.ACC2      = "#4aaa6a"
        self.ACCENT_TEXT = "#FF2E9F"  # Cyberpunk Neon Magenta for Center AI name & tactical text
        self.WHITE     = "#ffffff"
        self.TEXT      = "#b4e8e4"
        self.TEXT_DIM  = "#3f6b68"
        self.TEXT_MED  = "#6fa8a4"

    @staticmethod
    def _alpha_hex(hex_str: str, alpha: float) -> str:
        h = hex_str.lstrip("#")
        if len(h) == 6:
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            return f"rgba({r}, {g}, {b}, {alpha:.2f})"
        return hex_str

C = ThemePalette("#00e5ff")

def qcol(hex_or_rgba: str, alpha: int | None = None) -> QColor:
    if hex_or_rgba.startswith("rgba"):
        parts = hex_or_rgba.strip("rgba() ").split(",")
        r, g, b = int(parts[0]), int(parts[1]), int(parts[2])
        a = int(float(parts[3]) * 255) if alpha is None else alpha
        return QColor(r, g, b, a)
    c = QColor(hex_or_rgba)
    if alpha is not None:
        c.setAlpha(alpha)
    return c


# ── GPU & System Telemetry ─────────────────────────────────────────────────────

_nvml_lib = None
_nvml_ok  = None

class _Util(ctypes.Structure):
    _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]

def _read_gpu() -> float:
    global _nvml_lib, _nvml_ok
    if _nvml_ok is False: return -1.0
    try:
        if _nvml_lib is None:
            for dll in ("nvml", r"C:\Windows\System32\nvml.dll"):
                try:
                    lib = ctypes.WinDLL(dll)
                    lib.nvmlInit_v2()
                    _nvml_lib = lib
                    break
                except Exception:
                    continue
        if _nvml_lib is None:
            _nvml_ok = False
            return -1.0
        dev = ctypes.c_void_p()
        _nvml_lib.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(dev))
        util = _Util()
        _nvml_lib.nvmlDeviceGetUtilizationRates(dev, ctypes.byref(util))
        _nvml_ok = True
        return float(util.gpu)
    except Exception:
        _nvml_ok = False
        return -1.0


class _SysMetrics:
    def __init__(self):
        self.cpu = 0.0
        self.mem = 0.0
        self.net_up = 0.0
        self.net_down = 0.0
        self.gpu = -1.0
        self.tmp = -1.0
        self._lock = threading.Lock()
        self._last_net = psutil.net_io_counters()
        self._last_t = time.time()
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while True:
            time.sleep(1.5)
            cpu = psutil.cpu_percent()
            mem = psutil.virtual_memory().percent
            now = time.time()
            dt = max(0.1, now - self._last_t)
            curr_net = psutil.net_io_counters()
            up_speed = ((curr_net.bytes_sent - self._last_net.bytes_sent) / dt) / (1024 * 1024) * 8
            dn_speed = ((curr_net.bytes_recv - self._last_net.bytes_recv) / dt) / (1024 * 1024) * 8
            self._last_net = curr_net
            self._last_t = now
            gpu = _read_gpu()
            tmp = -1.0
            try:
                temps = psutil.sensors_temperatures()
                if temps:
                    for entries in temps.values():
                        if entries:
                            tmp = float(entries[0].current)
                            break
            except Exception:
                pass
            with self._lock:
                self.cpu = cpu
                self.mem = mem
                self.net_up = up_speed
                self.net_down = dn_speed
                self.gpu = gpu
                self.tmp = tmp

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "cpu": self.cpu, "mem": self.mem,
                "net_up": self.net_up, "net_down": self.net_down,
                "gpu": self.gpu, "tmp": self.tmp
            }

_metrics = _SysMetrics()


# ── Friday Sphere (Canvas AI Core) ────────────────────────────────────────────

class FridaySphereCanvas(QWidget):
    """
    60 FPS Tactical HUD — holographic video background with orbital rings,
    radar ranges, dynamic audio waves, and state reactivity drawn on top.
    """

    def __init__(self, assistant_name: str = "DONNA", parent=None):
        super().__init__(parent)
        self._asst_name = assistant_name.upper()
        self.state      = "STANDBY"
        self.speaking   = False
        self.muted      = False
        self._tick      = 0
        self._ripples   = []
        self._hover_pos = None

        # ── Glitch effect state ─────────────────────────────────────────────
        self._next_glitch = time.time() + random.uniform(3.0, 6.0)
        self._glitch_end  = 0.0

        # ── Load Zeyada Custom Font ─────────────────────────────────────────
        _font_path = Path(__file__).resolve().parent / "assets" / "fonts" / "Zeyada.ttf"
        if _font_path.exists():
            QFontDatabase.addApplicationFont(str(_font_path))

        # ── Hologram Video Sink (frame-based rendering) ─────────────────────
        self._current_frame = None
        self._media_player = None
        if _QT_MULTIMEDIA_OK:
            try:
                self._media_player = QMediaPlayer(self)
                self._audio_output = QAudioOutput(self)
                self._audio_output.setVolume(0.0)   # silent hologram
                self._media_player.setAudioOutput(self._audio_output)

                self._video_sink = QVideoSink(self)
                self._video_sink.videoFrameChanged.connect(self._on_video_frame)
                self._media_player.setVideoSink(self._video_sink)
                self._media_player.setLoops(QMediaPlayer.Loops.Infinite)

                _video_path = Path(__file__).resolve().parent / "assets" / "lilly_hologr.mp4"
                if _video_path.exists():
                    self._media_player.setSource(QUrl.fromLocalFile(str(_video_path)))
                    self._media_player.play()
            except Exception as _ve:
                print(f"[HUD] Video player init failed: {_ve}")
                self._media_player = None

        self.setMouseTracking(True)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._animate)
        self._timer.start(16)

    def _on_video_frame(self, frame: QVideoFrame):
        if frame.isValid():
            self._current_frame = frame.toImage()

    def _animate(self):
        self._tick += 1
        now = time.time()
        self._ripples = [r for r in self._ripples if (now - r[2]) < 1.4]
        self.update()

    def mouseMoveEvent(self, e):
        self._hover_pos = (e.position().x(), e.position().y())
        self.update()

    def leaveEvent(self, e):
        self._hover_pos = None
        self.update()

    def mousePressEvent(self, e):
        self._ripples.append([e.position().x(), e.position().y(), time.time()])
        self.update()
        if hasattr(self, "on_clicked") and callable(self.on_clicked):
            try:
                self.on_clicked()
            except Exception:
                pass

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        W, H = self.width(), self.height()
        cx, cy = W / 2, H / 2
        sz = min(W, H)
        R = sz * 0.35
        t = self._tick * 0.02

        if self.muted:
            glow_col = QColor(220, 70, 70)
            state_text = "⊞  MUTED"
        elif self.speaking:
            glow_col = QColor(0, 229, 255)
            state_text = "●  SPEAKING"
        elif self.state == "LISTENING":
            glow_col = QColor(74, 170, 106)
            state_text = "●  LISTENING"
        elif self.state == "THINKING" or self.state == "PROCESSING":
            glow_col = QColor(0, 210, 200)
            state_text = "◈  THINKING"
        else: # STANDBY
            glow_col = QColor(C.PRI)
            state_text = f"◈  STANDBY  [СКАЖИТЕ '{self._asst_name}']"

        # Scanlines (very light 5% opacity horizontal cyber scanlines)
        scan_offset = int(self._tick * 0.4) % 6
        p.setPen(QPen(QColor(0, 229, 255, 12), 1))
        for y in range(scan_offset, int(H), 6):
            p.drawLine(0, y, int(W), y)

        # Corner Decor
        self._draw_tactical_decor(p, W, H)

        # Ambient Glow (adds state-color aura around the video)
        pulse = math.sin(t * 1.5) * 0.5 + 0.5
        ambient_rad = QRadialGradient(cx, cy, R * 2.2)
        ambient_rad.setColorAt(0.0, qcol(glow_col.name(), int(16 + pulse * 12)))
        ambient_rad.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(ambient_rad))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), R * 2.2, R * 2.2)

        # Radar Range Rings
        for frac, alpha in [(1.55, 18), (1.28, 28), (1.04, 38)]:
            pen = QPen(qcol(glow_col.name(), alpha), 1)
            pen.setDashPattern([2, 6])
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(cx, cy), R * frac, R * frac)

        # ── Tactical HUD Ring (segmented dial + dual-color progress arcs) ──
        self._draw_hud_ring(p, cx, cy, R, t, glow_col)

        # ── Arched Callsign above the sphere (mirrors reference mockup) ──
        # Standard HUD font (Courier New), interface cyan/teal color, curved
        # along the top of the video circle.
        arc_glitch_now = time.time()
        if arc_glitch_now >= self._next_glitch:
            self._glitch_end = arc_glitch_now + random.uniform(0.10, 0.15)
            self._next_glitch = arc_glitch_now + random.uniform(3.5, 7.0)
        arc_is_glitch = arc_glitch_now < self._glitch_end

        arc_font = QFont("Courier New", int(sz * 0.068), QFont.Weight.Bold)
        arc_font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 118)
        arc_radius = R * 1.20
        if arc_is_glitch:
            gx = random.uniform(2.0, 3.5)
            self._draw_arc_text(p, cx - gx, cy, arc_radius, self._asst_name, arc_font,
                                 "#ff2e5a", alpha=140)
            self._draw_arc_text(p, cx + gx, cy, arc_radius, self._asst_name, arc_font,
                                 C.PRI, alpha=140)
        self._draw_arc_text(p, cx, cy, arc_radius, self._asst_name, arc_font, C.PRI, alpha=235)

        # ── Hologram Video (Clipped to perfect circle R, center-cropped) ──
        if self._current_frame and not self._current_frame.isNull():
            p.save()
            clip_path = QPainterPath()
            clip_path.addEllipse(QPointF(cx, cy), R, R)
            p.setClipPath(clip_path)

            iw, ih = self._current_frame.width(), self._current_frame.height()
            if iw > 0 and ih > 0:
                side = min(iw, ih)
                src_x = (iw - side) // 2
                src_y = (ih - side) // 2
                src_rect = QRectF(src_x, src_y, side, side)
                dst_rect = QRectF(cx - R, cy - R, 2 * R, 2 * R)
                p.drawImage(dst_rect, self._current_frame, src_rect)
            p.restore()

        # Chromatic Aberration Border (Subtle 1.5px Red/Cyan shift)
        p.setPen(QPen(QColor(255, 55, 75, int(45 + pulse * 30)), 1.0))
        p.drawEllipse(QPointF(cx - 1.5, cy), R, R)
        p.setPen(QPen(QColor(0, 229, 255, int(45 + pulse * 30)), 1.0))
        p.drawEllipse(QPointF(cx + 1.5, cy), R, R)

        # Glowing border ring around video
        border_pen = QPen(qcol(glow_col.name(), int(130 + pulse * 70)), 1.5)
        p.setPen(border_pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(cx, cy), R, R)

        # Orbit Rings
        speed_mult = 2.5 if (self.state == "THINKING") else 1.0
        rings = [
            {"tilt": 22, "speed": 0.45 * speed_mult, "lw": 1.2, "alpha": 120},
            {"tilt": 68, "speed": -0.30 * speed_mult, "lw": 0.9, "alpha": 90},
            {"tilt": 44, "speed": 0.20 * speed_mult, "lw": 0.7, "alpha": 70},
        ]
        for r in rings:
            ang = t * r["speed"]
            p.save()
            p.translate(cx, cy)
            p.rotate(math.degrees(ang))
            p.scale(1.0, max(0.1, math.sin(math.radians(r["tilt"]))))
            p.setPen(QPen(qcol(glow_col.name(), r["alpha"]), r["lw"]))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(0, 0), R * 0.98, R * 0.98)
            p.restore()

        # Speaking Audio Waves
        if self.speaking or self.state == "SPEAKING":
            for i in range(36):
                ang = (i / 36.0) * math.pi * 2 + t * 0.5
                h = (math.sin(t * 8 + i * 0.8) * 0.5 + 0.5) * (R * 0.14) + 2
                p.setPen(QPen(qcol(C.PRI, 180), 1.5))
                p.drawLine(
                    QPointF(cx + R * math.cos(ang), cy + R * math.sin(ang)),
                    QPointF(cx + (R + h) * math.cos(ang), cy + (R + h) * math.sin(ang))
                )

        # Ripples
        now_ts = time.time()
        for rx, ry, r_start in self._ripples:
            age = (now_ts - r_start) / 1.4
            if age > 1.0: continue
            max_r = R * 1.8
            alpha = int(max(0, (1.0 - age) * 160))
            for ring_idx in range(3):
                cur_r = max_r * max(0, age - ring_idx * 0.15)
                if cur_r > 0:
                    p.setPen(QPen(qcol(glow_col.name(), int(alpha * (1 - ring_idx * 0.25))), 1))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawEllipse(QPointF(rx, ry), cur_r, cur_r)

        # Center AI Labels (Contrast Magenta #FF2E9F + Zeyada Font + Glitch RGB split)
        now_t = time.time()
        is_glitch = False
        if now_t >= self._next_glitch:
            self._glitch_end = now_t + random.uniform(0.10, 0.15)
            self._next_glitch = now_t + random.uniform(3.5, 7.0)
        if now_t < self._glitch_end:
            is_glitch = True

        p.setFont(QFont("Zeyada", int(sz * 0.08), QFont.Weight.Bold))
        # Subtle dark halo behind text for maximum clarity over the holographic video:
        p.setPen(QPen(QColor(0, 0, 0, 220), 1))
        p.drawText(QRectF(cx - 160 + 1, cy - sz * 0.055 + 1, 320, sz * 0.08),
                Qt.AlignmentFlag.AlignCenter, self._asst_name)

        if is_glitch:
            gx = random.uniform(2.5, 4.5)
            gy = random.uniform(-1.0, 1.0)
            # Cyan split left
            p.setPen(QPen(QColor(0, 229, 255, 170), 1))
            p.drawText(QRectF(cx - 160 - gx, cy - sz * 0.055 + gy, 320, sz * 0.08),
                    Qt.AlignmentFlag.AlignCenter, self._asst_name)
            # Red split right
            p.setPen(QPen(QColor(255, 46, 90, 170), 1))
            p.drawText(QRectF(cx - 160 + gx, cy - sz * 0.055 - gy, 320, sz * 0.08),
                    Qt.AlignmentFlag.AlignCenter, self._asst_name)

        # Main Magenta Text
        p.setPen(QPen(QColor(C.ACCENT_TEXT), 1))
        p.drawText(QRectF(cx - 160, cy - sz * 0.055, 320, sz * 0.08),
                Qt.AlignmentFlag.AlignCenter, self._asst_name)

        p.setFont(QFont("Courier New", int(sz * 0.024), QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.ACCENT_TEXT, 220), 1))
        sub_label = "TACTICAL AI" if not self.speaking else "PROCESSING..."
        p.drawText(QRectF(cx - 150, cy + sz * 0.035, 300, sz * 0.04),
                Qt.AlignmentFlag.AlignCenter, sub_label)

        # Status text below sphere
        p.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        p.setPen(QPen(glow_col, 1))
        p.drawText(QRectF(0, H - 28, W, 22), Qt.AlignmentFlag.AlignCenter, state_text)

    def _draw_tactical_decor(self, p: QPainter, W: int, H: int):
        p.setPen(QPen(qcol(C.PRI, 70), 1))
        bl = 16
        for bx, by, dx, dy in [(12, 12, 1, 1), (W - 12, 12, -1, 1),
                            (12, H - 42, 1, -1), (W - 12, H - 42, -1, -1)]:
            p.drawLine(QPointF(float(bx), float(by)), QPointF(float(bx + dx * bl), float(by)))
            p.drawLine(QPointF(float(bx), float(by)), QPointF(float(bx), float(by + dy * bl)))

        p.setFont(QFont("Courier New", 7))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(20, 14, 180, 16), Qt.AlignmentFlag.AlignLeft, "37S NB 4421 8834")
        p.drawText(QRectF(W - 200, 14, 180, 16), Qt.AlignmentFlag.AlignRight, "ALT 3,420 FT · MACH 2.1")
        p.drawText(QRectF(20, H - 46, 220, 16), Qt.AlignmentFlag.AlignLeft, "LAT 40.7128°N · LON 74.0060°W")

        cursor = "_" if (int(time.time() * 2) % 2 == 0) else ""
        p.setPen(QPen(qcol(C.GREEN, 180), 1))
        p.drawText(QRectF(W - 240, H - 46, 220, 16), Qt.AlignmentFlag.AlignRight, f"◈ ALL SYSTEMS NOMINAL {cursor}")

    def _draw_arc_text(self, p: QPainter, cx: float, cy: float, radius: float,
                        text: str, font: QFont, color, alpha: int = 230):
        """
        Draws `text` curved along a circle of given radius, centered on the
        top of the circle (12 o'clock), each glyph rotated tangent to the arc.
        """
        if not text:
            return
        p.save()
        p.setFont(font)
        fm = QFontMetricsF(font)
        char_widths = [fm.horizontalAdvance(ch) for ch in text]
        total_width = sum(char_widths)
        circumference = 2 * math.pi * radius
        if circumference <= 0:
            p.restore()
            return
        total_angle = (total_width / circumference) * 360.0
        base_start_angle = -90.0 - total_angle / 2.0  # center the string at the top

        # Two passes: dark halo first (for legibility over ring ticks), then color
        for pass_color, pass_alpha, offset in ((QColor(0, 0, 0, 200), 200, 1), (QColor(color), alpha, 0)):
            angle = base_start_angle
            for ch, w in zip(text, char_widths):
                char_angle = (w / circumference) * 360.0
                mid_angle = angle + char_angle / 2.0
                rad = math.radians(mid_angle)
                x = cx + (radius + offset) * math.cos(rad)
                y = cy + (radius + offset) * math.sin(rad)
                p.save()
                p.translate(x, y)
                p.rotate(mid_angle + 90.0)
                col = QColor(pass_color)
                col.setAlpha(pass_alpha)
                p.setPen(QPen(col, 1))
                p.drawText(QRectF(-w / 2, -fm.height() * 0.75, w, fm.height()),
                           Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, ch)
                p.restore()
                angle += char_angle
        p.restore()

    def _draw_hud_ring(self, p: QPainter, cx: float, cy: float, R: float, t: float, glow_col: QColor):
        """
        Aviation-style dual dial around the sphere: an outer tick-marked ring
        with pseudo-technical hex/number labels, plus two progress arcs
        (cyan + red) that slowly counter-rotate for a 'live scanning' feel.
        """
        ring_r = R * 1.32

        # Slow independent rotation for the whole dial assembly
        rot = math.degrees(t * 0.04)

        p.save()
        p.translate(cx, cy)
        p.rotate(rot)

        # Tick marks (60 divisions, every 5th tick longer)
        for i in range(60):
            ang = math.radians(i * 6)
            long_tick = (i % 5 == 0)
            tlen = 14 if long_tick else 7
            alpha = 210 if long_tick else 110
            x0, y0 = ring_r * math.cos(ang), ring_r * math.sin(ang)
            x1, y1 = (ring_r + tlen) * math.cos(ang), (ring_r + tlen) * math.sin(ang)
            p.setPen(QPen(qcol(C.PRI, alpha), 1.8 if long_tick else 1.1))
            p.drawLine(QPointF(x0, y0), QPointF(x1, y1))

        # Sparse pseudo-technical hex labels at a few tick positions
        p.setFont(QFont("Courier New", 6))
        for i in range(0, 60, 15):
            ang = math.radians(i * 6)
            lx, ly = (ring_r + 20) * math.cos(ang), (ring_r + 20) * math.sin(ang)
            p.save()
            p.translate(lx, ly)
            p.rotate(-rot)  # keep labels upright regardless of dial rotation
            p.setPen(QPen(qcol(C.TEXT_DIM, 160), 1))
            label = f"{(i * 7 + 40) % 360:03d}"
            p.drawText(QRectF(-16, -6, 32, 12), Qt.AlignmentFlag.AlignCenter, label)
            p.restore()

        p.restore()

        # Dual progress arcs — cyan sweeps one way, red the other, both slow
        arc_r = ring_r
        arc_rect = QRectF(cx - arc_r, cy - arc_r, arc_r * 2, arc_r * 2)

        cyan_start = int((t * 6) % 360)
        cyan_span  = 250
        pen_cyan = QPen(qcol(C.PRI, 200), 2.2)
        pen_cyan.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen_cyan)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(arc_rect, cyan_start * 16, cyan_span * 16)

        red_start = int((-t * 4) % 360)
        red_span  = 80
        pen_red = QPen(qcol("#ff3355", 220), 2.4)
        pen_red.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen_red)
        p.drawArc(arc_rect, red_start * 16, red_span * 16)


# ── Cyberpunk Chamfer Panel & Scanlines ────────────────────────────────────────

class CyberChamferPanel(QWidget):
    """
    Tactical Cyberpunk panel with diagonal cut / chamfered corner
    and glowing tech border.
    """
    def __init__(self, cut_corner="tl", cut_size=10, bg_col=None, border_col=None, parent=None):
        super().__init__(parent)
        self.cut_corner = cut_corner
        self.cut_size = cut_size
        self.bg_col = bg_col or C.PANEL
        self.border_col = border_col or C.BORDER
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = float(self.width()), float(self.height())
        c = float(self.cut_size)

        path = QPainterPath()
        if self.cut_corner == "tl":
            path.moveTo(c, 0)
            path.lineTo(W, 0)
            path.lineTo(W, H)
            path.lineTo(0, H)
            path.lineTo(0, c)
            path.closeSubpath()
        elif self.cut_corner == "tr":
            path.moveTo(0, 0)
            path.lineTo(W - c, 0)
            path.lineTo(W, c)
            path.lineTo(W, H)
            path.lineTo(0, H)
            path.closeSubpath()
        elif self.cut_corner == "bl":
            path.moveTo(0, 0)
            path.lineTo(W, 0)
            path.lineTo(W, H)
            path.lineTo(c, H)
            path.lineTo(0, H - c)
            path.closeSubpath()
        elif self.cut_corner == "br":
            path.moveTo(0, 0)
            path.lineTo(W, 0)
            path.lineTo(W, H - c)
            path.lineTo(W - c, H)
            path.lineTo(0, H)
            path.closeSubpath()
        else:
            path.addRect(0, 0, W, H)

        p.fillPath(path, QBrush(qcol(self.bg_col)))
        p.setPen(QPen(qcol(self.border_col), 1))
        p.drawPath(path)


class _GlobalScanlineOverlay(QWidget):
    """
    Lightweight fullscreen scanline overlay widget (5% opacity, scrolling).
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._offset = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._step)
        self._timer.start(50)

    def _step(self):
        self._offset = (self._offset + 1) % 5
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        W, H = self.width(), self.height()
        p.setPen(QPen(QColor(0, 229, 255, 11), 1))
        for y in range(self._offset, H, 5):
            p.drawLine(0, y, W, y)


# ── Metric Bar Widget ─────────────────────────────────────────────────────────

class MetricBar(QWidget):
    def __init__(self, key: str, unit: str, warn: float = 85.0, parent=None):
        super().__init__(parent)
        self.key = key
        self.unit = unit
        self.warn = warn
        self.val = 0.0

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(2)

        self._k_lbl = QLabel(key)
        self._k_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._k_lbl.setFont(QFont("Courier New", 7))
        self._k_lbl.setStyleSheet(f"color: {C.TEXT_DIM};")
        lay.addWidget(self._k_lbl)

        self._v_lbl = QLabel("0")
        self._v_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._v_lbl.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        self._v_lbl.setStyleSheet(f"color: {C.PRI};")
        lay.addWidget(self._v_lbl)

        self._u_lbl = QLabel(unit)
        self._u_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._u_lbl.setFont(QFont("Courier New", 6))
        self._u_lbl.setStyleSheet(f"color: {C.TEXT_DIM};")
        lay.addWidget(self._u_lbl)

        self.setStyleSheet(f"border-bottom: 1px solid {C.BORDER_DIM};")

    def update_val(self, val: float, display_str: str | None = None):
        self.val = val
        txt = display_str if display_str else f"{val:.0f}"
        self._v_lbl.setText(txt)
        col = C.RED if val > self.warn else C.PRI
        self._v_lbl.setStyleSheet(f"color: {col};")


class TacticalSpectrogram(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(54)
        self._tick = 0
        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._step)
        self._tmr.start(40)

    def _step(self):
        self._tick += 1
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        num_bars = 24
        bw = (W - (num_bars * 3)) / num_bars
        t = self._tick * 0.1
        for i in range(num_bars):
            val = math.sin(t * 1.5 + i * 0.5) * 0.5 + 0.5
            h = max(3.0, val * (H - 12))
            x = i * (bw + 3)
            y = H - h - 4
            col = qcol(C.RED if val > 0.8 else (C.PRI if val > 0.4 else C.GREEN), int(90 + val * 140))
            p.fillRect(QRectF(x, y, bw, h), col)


# ── Floating Modals: Setup, Remote Access QR, Customize ───────────────────────

class RemoteKeyOverlay(QWidget):
    closed = pyqtSignal()
    _OW, _OH = 390, 460

    def __init__(self, url: str, key: str, auto_login_url: str = "",
                manual_url: str = "", expiry_secs: int = 600, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            RemoteKeyOverlay {{
                background: rgba(6, 8, 9, 0.96);
                border: 1px solid {C.BORDER_B};
                border-radius: 8px;
            }}
        """)
        self._expiry = time.time() + expiry_secs
        self._on_new_key = None
        self._auto_url = auto_login_url
        self._manual_url = manual_url or url

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(6)

        hdr = QLabel("◈  TACTICAL REMOTE ACCESS")
        hdr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hdr.setFont(QFont("Orbitron", 10, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        lay.addWidget(hdr)

        self._qr_label = QLabel()
        self._qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._qr_label.setFixedSize(160, 160)
        self._qr_label.setStyleSheet("background: white; border-radius: 6px; padding: 4px;")
        qr_row = QHBoxLayout(); qr_row.addStretch(); qr_row.addWidget(self._qr_label); qr_row.addStretch()
        lay.addLayout(qr_row)

        self._update_qr(auto_login_url or url)

        hint = QLabel("Scan QR code with phone camera to connect instantly")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setFont(QFont("Courier New", 7))
        hint.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        lay.addWidget(hint)

        self._key_lbl = QLabel(key)
        self._key_lbl.setFont(QFont("Courier New", 22, QFont.Weight.Bold))
        self._key_lbl.setStyleSheet(f"""
            color: {C.PRI};
            background: #0c1014;
            border: 1px solid {C.BORDER_B};
            border-radius: 6px;
            padding: 4px;
            letter-spacing: 8px;
        """)
        self._key_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._key_lbl)

        self._timer_lbl = QLabel()
        self._timer_lbl.setFont(QFont("Courier New", 7))
        self._timer_lbl.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        self._timer_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._timer_lbl)

        btn_row = QHBoxLayout()
        close_btn = QPushButton("DISMISS")
        close_btn.setFixedHeight(28)
        close_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: {C.PANEL}; color: {C.TEXT};
                border: 1px solid {C.BORDER}; border-radius: 3px;
            }}
            QPushButton:hover {{ color: {C.PRI}; border: 1px solid {C.BORDER_B}; }}
        """)
        close_btn.clicked.connect(self._do_close)
        btn_row.addWidget(close_btn)
        lay.addLayout(btn_row)

        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._tick)
        self._tmr.start(1000)
        self._tick()

    def set_new_key_callback(self, fn):
        self._on_new_key = fn

    def _update_qr(self, url: str):
        if not url: return
        try:
            import qrcode
            from io import BytesIO
            qr = qrcode.QRCode(box_size=4, border=1)
            qr.add_data(url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            buf = BytesIO()
            img.save(buf, format="PNG")
            px = QPixmap()
            px.loadFromData(buf.getvalue())
            self._qr_label.setPixmap(px.scaled(150, 150, Qt.AspectRatioMode.KeepAspectRatio))
        except Exception:
            self._qr_label.setText(url[:20])

    def _tick(self):
        rem = max(0, int(self._expiry - time.time()))
        m, s = divmod(rem, 60)
        self._timer_lbl.setText(f"Token expires in  {m:02d}:{s:02d}")
        if rem == 0: self._do_close()

    def _do_close(self):
        self._tmr.stop()
        self.hide()
        self.closed.emit()


class SetupOverlay(QWidget):
    done = pyqtSignal(str, str)
    _OW, _OH = 440, 360

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            SetupOverlay {{
                background: rgba(6, 8, 9, 0.98);
                border: 1px solid {C.BORDER_B};
                border-radius: 8px;
            }}
        """)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(10)

        t = QLabel("◈ DONNA TACTICAL OS INITIALIZATION")
        t.setFont(QFont("Orbitron", 10, QFont.Weight.Bold))
        t.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        lay.addWidget(t)

        lbl = QLabel("Enter your Google Gemini API Key:")
        lbl.setFont(QFont("Courier New", 8))
        lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        lay.addWidget(lbl)

        self._key_in = QLineEdit()
        self._key_in.setPlaceholderText("AIzaSy...")
        self._key_in.setFont(QFont("Courier New", 9))
        self._key_in.setStyleSheet(f"""
            QLineEdit {{
                background: #000a10; color: {C.PRI};
                border: 1px solid {C.BORDER_B}; border-radius: 4px; padding: 6px;
            }}
        """)
        lay.addWidget(self._key_in)

        save_btn = QPushButton("INITIALIZE SYSTEM")
        save_btn.setFixedHeight(34)
        save_btn.setFont(QFont("Orbitron", 8, QFont.Weight.Bold))
        save_btn.setStyleSheet(f"""
            QPushButton {{
                background: {C.PRI_DIM}; color: {C.PRI};
                border: 1px solid {C.BORDER_B}; border-radius: 4px;
            }}
            QPushButton:hover {{ background: {C.BORDER_B}; }}
        """)
        save_btn.clicked.connect(self._save)
        lay.addWidget(save_btn)

    def _save(self):
        k = self._key_in.text().strip()
        if k:
            self.done.emit(k, "windows")
            self.hide()


class CustomizeOverlay(QWidget):
    """Full customization modal: Assistant Name, User Name, Accent Color."""
    saved = pyqtSignal(str, str, str)
    _OW, _OH = 460, 480

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            CustomizeOverlay {{
                background: rgba(6, 8, 9, 0.98);
                border: 1px solid {C.BORDER_B};
                border-radius: 8px;
            }}
        """)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(10)

        t = QLabel("◈  TACTICAL OS CONFIGURATION")
        t.setFont(QFont("Orbitron", 10, QFont.Weight.Bold))
        t.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        lay.addWidget(t)

        cfg = _read_full_config()

        # Assistant Name
        l1 = QLabel("Assistant Name (AI Core):")
        l1.setFont(QFont("Courier New", 7))
        l1.setStyleSheet(f"color: {C.TEXT_DIM};")
        lay.addWidget(l1)

        self._asst_in = QLineEdit(cfg.get("assistant_name") or "Донна")
        self._asst_in.setFont(QFont("Courier New", 9))
        self._asst_in.setStyleSheet(f"background:#0c1014; color:{C.PRI}; border:1px solid {C.BORDER}; padding:4px;")
        lay.addWidget(self._asst_in)

        # User Name / Title
        l2 = QLabel("Operator Address Name (User):")
        l2.setFont(QFont("Courier New", 7))
        l2.setStyleSheet(f"color: {C.TEXT_DIM};")
        lay.addWidget(l2)

        self._user_in = QLineEdit(cfg.get("user_name") or "Сэр")
        self._user_in.setFont(QFont("Courier New", 9))
        self._user_in.setStyleSheet(f"background:#0c1014; color:{C.GREEN}; border:1px solid {C.BORDER}; padding:4px;")
        lay.addWidget(self._user_in)

        # Color Theme Presets
        l3 = QLabel("UI Accent Theme:")
        l3.setFont(QFont("Courier New", 7))
        l3.setStyleSheet(f"color: {C.TEXT_DIM};")
        lay.addWidget(l3)

        preset_row = QHBoxLayout()
        preset_row.setSpacing(6)
        self._selected_color = cfg.get("ui_color") or "#00e5ff"

        for k, v in COLOR_PRESETS.items():
            btn = QPushButton()
            btn.setFixedSize(26, 26)
            btn.setToolTip(v["NAME"])
            btn.setStyleSheet(f"background: {v['PRI']}; border: 1px solid {C.WHITE}; border-radius: 4px;")
            btn.clicked.connect(lambda _, col=v["PRI"]: self._pick_color(col))
            preset_row.addWidget(btn)
        lay.addLayout(preset_row)

        btn_row = QHBoxLayout()
        save_btn = QPushButton("APPLY CONFIGURATION")
        save_btn.setFixedHeight(32)
        save_btn.setFont(QFont("Orbitron", 8, QFont.Weight.Bold))
        save_btn.setStyleSheet(f"background: {C.PRI_DIM}; color: {C.PRI}; border: 1px solid {C.BORDER_B}; border-radius: 4px;")
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)

        close_btn = QPushButton("DISMISS")
        close_btn.setFixedHeight(32)
        close_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        close_btn.setStyleSheet(f"background: {C.PANEL}; color: {C.TEXT}; border: 1px solid {C.BORDER}; border-radius: 4px;")
        close_btn.clicked.connect(self.hide)
        btn_row.addWidget(close_btn)
        lay.addLayout(btn_row)

    def _pick_color(self, hex_val: str):
        self._selected_color = hex_val

    def _save(self):
        a_name = self._asst_in.text().strip() or "Донна"
        u_name = self._user_in.text().strip() or "Сэр"
        self.saved.emit(a_name, u_name, self._selected_color)
        self.hide()


# ── Mini HUD Panels (Tactical Map / Tactical Analytics / Status Analytics) ─────

class MiniHudPanel(QWidget):
    """
    Small circular tactical dial, used in a row of three beneath the main
    sphere. Three interchangeable modes, all driven by real data already
    tracked elsewhere in the app:

      "radar" — mirrors the aircraft position text already shown under the
                main sphere (LAT 40.7128°N · LON 74.0060°W) as a blinking
                marker on a radar grid.
      "video" — mirrors the main hologram's current video frame at a
                smaller scale (shares the already-decoded frame, no extra
                video decoder instantiated).
      "gauge" — a live circular gauge driven by value_getter(), used here
                for real-time CPU load from the existing _metrics singleton.
    """
    def __init__(self, mode: str, title: str, video_source=None, value_getter=None, parent=None):
        super().__init__(parent)
        self.mode = mode
        self.title = title
        self.video_source = video_source
        self.value_getter = value_getter
        self._value = 0.0
        self._tick = 0
        self.setFixedSize(104, 104)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._animate)
        self._timer.start(50)  # 20fps — plenty for a small decorative dial

    def _animate(self):
        self._tick += 1
        if self.value_getter:
            try:
                self._value = float(self.value_getter())
            except Exception:
                pass
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        cx, cy = W / 2, H / 2 + 8
        R = min(W, H) * 0.32
        t = self._tick * 0.05

        # Outer dual-color ring shared across all three modes for visual unity
        ring_r = R * 1.22
        arc_rect = QRectF(cx - ring_r, cy - ring_r, ring_r * 2, ring_r * 2)
        p.setPen(QPen(qcol(C.PRI, 150), 2.0))
        p.drawArc(arc_rect, int((t * 22) % 360) * 16, 250 * 16)
        p.setPen(QPen(qcol("#ff3355", 210), 2.0))
        p.drawArc(arc_rect, int((-t * 15) % 360) * 16, 55 * 16)

        # Inner disc
        p.setBrush(QBrush(QColor(3, 6, 7, 235)))
        p.setPen(QPen(qcol(C.PRI, 90), 1))
        p.drawEllipse(QPointF(cx, cy), R, R)

        if self.mode == "video" and self.video_source is not None:
            frame = getattr(self.video_source, "_current_frame", None)
            if frame is not None and not frame.isNull():
                p.save()
                clip = QPainterPath()
                clip.addEllipse(QPointF(cx, cy), R, R)
                p.setClipPath(clip)
                iw, ih = frame.width(), frame.height()
                if iw > 0 and ih > 0:
                    side = min(iw, ih)
                    sx, sy = (iw - side) // 2, (ih - side) // 2
                    p.drawImage(QRectF(cx - R, cy - R, R * 2, R * 2), frame,
                                QRectF(sx, sy, side, side))
                p.restore()

        elif self.mode == "gauge":
            span = max(0.0, min(100.0, self._value)) / 100.0 * 270
            gauge_rect = QRectF(cx - R * 0.86, cy - R * 0.86, R * 1.72, R * 1.72)
            p.setPen(QPen(qcol(C.TEXT_DIM, 70), 4))
            p.drawArc(gauge_rect, -225 * 16, 270 * 16)
            p.setPen(QPen(qcol(C.PRI, 220), 4))
            p.drawArc(gauge_rect, -225 * 16, int(span * 16))
            p.setFont(QFont("Courier New", int(R * 0.34), QFont.Weight.Bold))
            p.setPen(QPen(QColor(C.ACCENT_TEXT), 1))
            p.drawText(QRectF(cx - R, cy - R * 0.2, R * 2, R * 0.4),
                       Qt.AlignmentFlag.AlignCenter, f"{self._value:.0f}%")

        elif self.mode == "radar":
            for frac in (0.4, 0.7, 1.0):
                p.setPen(QPen(qcol(C.PRI, 35), 0.8))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(QPointF(cx, cy), R * frac, R * frac)
            p.setPen(QPen(qcol(C.PRI, 30), 0.8))
            p.drawLine(QPointF(cx - R, cy), QPointF(cx + R, cy))
            p.drawLine(QPointF(cx, cy - R), QPointF(cx, cy + R))

            # Marker position mirrors the real LAT/LON readout shown under
            # the main sphere — fixed heading derived from those coordinates
            ang = math.radians(52)
            mr = R * 0.55
            mx, my = cx + mr * math.cos(ang), cy + mr * math.sin(ang)
            pulse = math.sin(t * 3) * 0.5 + 0.5
            p.setBrush(QBrush(qcol("#ff3355", int(180 + pulse * 60))))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(mx, my), 3.0, 3.0)
            p.setPen(QPen(qcol("#ff3355", 70), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(mx, my), 6 + pulse * 4, 6 + pulse * 4)

        p.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.TEXT_MED, 220), 1))
        p.drawText(QRectF(0, 0, W, 12), Qt.AlignmentFlag.AlignCenter, self.title)


# ── Main Tactical Window ───────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    _log_sig        = pyqtSignal(str)
    _state_sig      = pyqtSignal(str)
    _content_sig    = pyqtSignal(str, str)
    _reconfig_sig   = pyqtSignal()
    _camera_sig     = pyqtSignal(bytes)
    _cam_stream_sig = pyqtSignal(bool)
    _cam_frame_sig  = pyqtSignal(bytes)
    _clipboard_sig  = pyqtSignal(str)

    def __init__(self, face_path: str = ""):
        super().__init__()
        _cfg = _read_full_config()
        self._assistant_name = (_cfg.get("assistant_name") or "Донна").strip()
        self._user_name = (_cfg.get("user_name") or "Сэр").strip()

        _ui_color = _cfg.get("ui_color")
        if _ui_color:
            C.set_accent(_ui_color)

        self.setWindowTitle(f"{self._assistant_name.upper()} — TACTICAL OS v5.1.0")
        self.resize(1180, 740)
        self.setMinimumSize(960, 600)
        self.setAcceptDrops(True)

        screen = QApplication.primaryScreen().availableGeometry()
        self.move((screen.width() - 1180) // 2, (screen.height() - 740) // 2)

        self.on_text_command   = None
        self.on_remote_clicked = None
        self.on_interrupt      = None
        self._muted            = False
        self._current_file     = None
        self._remote_overlay   = None
        self._customize_overlay= None
        self._overlay          = None
        self._ready            = self._check_config()

        central = QWidget()
        central.setStyleSheet(f"background: {C.BG};")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        root.addWidget(self._build_header())

        # Main Body
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        body.addWidget(self._build_left_sidebar(), stretch=0)
        body.addWidget(self._build_center_area(), stretch=5)
        body.addWidget(self._build_right_sidebar(), stretch=0)
        root.addLayout(body, stretch=1)

        # Footer
        root.addWidget(self._build_footer())

        # Global Scanline Cyberpunk Overlay
        self._scanlines = _GlobalScanlineOverlay(self)
        self._scanlines.setGeometry(self.rect())
        self._scanlines.raise_()

        # Quick Access Settings Drawer
        self._quick_drawer = self._build_quick_drawer()

        # Signals
        self._log_sig.connect(self._append_log)
        self._state_sig.connect(self._apply_state)
        self._content_sig.connect(self._show_content)
        self._reconfig_sig.connect(self._show_setup)

        # Timers
        self._clock_tmr = QTimer(self)
        self._clock_tmr.timeout.connect(self._tick_clock)
        self._clock_tmr.start(1000)
        self._tick_clock()

        self._metrics_tmr = QTimer(self)
        self._metrics_tmr.timeout.connect(self._update_metrics)
        self._metrics_tmr.start(1500)

        # Clipboard Monitor
        QApplication.clipboard().dataChanged.connect(self._on_clipboard_changed)

        if not self._ready:
            QTimer.singleShot(300, self._show_setup)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, "_scanlines") and self._scanlines:
            self._scanlines.setGeometry(self.rect())
            self._scanlines.raise_()

    # ── Header ────────────────────────────────────────────────────────────────

    def _build_header(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(46)
        w.setStyleSheet(f"""
            background: linear-gradient(90deg, #07090c, #0a0d10, #07090c);
            border-bottom: 1px solid {C.BORDER};
        """)
        lay = QHBoxLayout(w)
        lay.setContentsMargins(14, 0, 14, 0)
        lay.setSpacing(12)

        # Drawer button
        self._drawer_btn = QPushButton("⚙")
        self._drawer_btn.setFixedSize(26, 26)
        self._drawer_btn.setFont(QFont("Courier New", 12))
        self._drawer_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._drawer_btn.setToolTip("Tactical Settings & Controls")
        self._drawer_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_DIM};
                border: 1px solid {C.BORDER}; border-radius: 4px;
            }}
            QPushButton:hover {{ color: {C.PRI}; border-color: {C.BORDER_B}; }}
        """)
        self._drawer_btn.clicked.connect(self._toggle_drawer)
        lay.addWidget(self._drawer_btn)

        # Title
        t = QLabel(self._assistant_name.upper())
        t.setFont(QFont("Orbitron", 11, QFont.Weight.Bold))
        t.setStyleSheet(f"color: {C.PRI}; background: transparent; letter-spacing: 2px;")
        lay.addWidget(t)

        sub = QLabel("TACTICAL AI v5.1.0")
        sub.setFont(QFont("Courier New", 7))
        sub.setStyleSheet(f"color: {C.TEXT_DIM}; border-left: 1px solid {C.BORDER}; padding-left: 10px;")
        lay.addWidget(sub)

        badge = QLabel("TOP SECRET // SCI")
        badge.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        badge.setStyleSheet(f"background: {C.RED_GHO}; color: {C.RED}; border: 1px solid {C.RED_DIM}; border-radius: 2px; padding: 1px 6px;")
        lay.addWidget(badge)

        lay.addStretch()

        # Status Dots
        for name in ["NEURAL", "SATLINK", "ENCRYPT", "FIREWALL"]:
            dot_box = QHBoxLayout(); dot_box.setSpacing(4)
            d = QLabel("●"); d.setFont(QFont("Courier New", 7)); d.setStyleSheet(f"color: {C.GREEN};")
            lbl = QLabel(name); lbl.setFont(QFont("Courier New", 7)); lbl.setStyleSheet(f"color: {C.TEXT_DIM};")
            dot_box.addWidget(d); dot_box.addWidget(lbl)
            lay.addLayout(dot_box)

        lay.addSpacing(16)

        self._clock_lbl = QLabel("00:00:00")
        self._clock_lbl.setFont(QFont("Orbitron", 11, QFont.Weight.Bold))
        self._clock_lbl.setStyleSheet(f"color: {C.PRI};")
        lay.addWidget(self._clock_lbl)

        self._date_lbl = QLabel("")
        self._date_lbl.setFont(QFont("Courier New", 7))
        self._date_lbl.setStyleSheet(f"color: {C.TEXT_DIM};")
        lay.addWidget(self._date_lbl)

        return w

    def _tick_clock(self):
        now = datetime.now()
        self._clock_lbl.setText(now.strftime("%H:%M:%S"))
        self._date_lbl.setText(now.strftime("%a %d %b %Y").upper())

    # ── Quick Access Drawer ───────────────────────────────────────────────────

    def _build_quick_drawer(self) -> QWidget:
        w = QWidget(self.centralWidget())
        w.setFixedWidth(260)
        w.setStyleSheet(f"""
            background: rgba(6, 8, 9, 0.98);
            border: 1px solid {C.BORDER_B};
            border-radius: 6px;
        """)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        t = QLabel("◈  TACTICAL CONTROLS")
        t.setFont(QFont("Orbitron", 8, QFont.Weight.Bold))
        t.setStyleSheet(f"color: {C.PRI};")
        lay.addWidget(t)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine); sep.setStyleSheet(f"color: {C.BORDER};")
        lay.addWidget(sep)

        # Autostart on boot button
        self._autostart_btn = QPushButton()
        self._autostart_btn.setFixedHeight(28)
        self._autostart_btn.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        self._autostart_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_autostart_btn(self._check_autostart())
        self._autostart_btn.clicked.connect(self._toggle_autostart)
        lay.addWidget(self._autostart_btn)

        # Morning briefing toggle
        self._brief_btn = QPushButton()
        self._brief_btn.setFixedHeight(28)
        self._brief_btn.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        self._brief_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        from memory.config_manager import get_brief_enabled
        self._update_brief_btn(get_brief_enabled())
        self._brief_btn.clicked.connect(self._toggle_brief)
        lay.addWidget(self._brief_btn)

        # Desktop Shortcut
        sc_btn = QPushButton("📌 CREATE DESKTOP SHORTCUT")
        sc_btn.setFixedHeight(28)
        sc_btn.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        sc_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        sc_btn.setStyleSheet(f"background: {C.PANEL}; color: {C.TEXT}; border: 1px solid {C.BORDER}; border-radius: 3px;")
        sc_btn.clicked.connect(self._create_desktop_shortcut)
        lay.addWidget(sc_btn)

        # Customization button
        cust_btn = QPushButton("🎨 APPEARANCE & THEMES")
        cust_btn.setFixedHeight(28)
        cust_btn.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        cust_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cust_btn.setStyleSheet(f"background: {C.PANEL}; color: {C.PRI}; border: 1px solid {C.BORDER_B}; border-radius: 3px;")
        cust_btn.clicked.connect(self._open_customize)
        lay.addWidget(cust_btn)

        # Setup / Keys
        setup_btn = QPushButton("🔑 API KEYS / CONFIG")
        setup_btn.setFixedHeight(28)
        setup_btn.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        setup_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        setup_btn.setStyleSheet(f"background: {C.PANEL}; color: {C.TEXT}; border: 1px solid {C.BORDER}; border-radius: 3px;")
        setup_btn.clicked.connect(self._show_setup)
        lay.addWidget(setup_btn)

        # Fullscreen Toggle
        fs_btn = QPushButton("⛶ FULLSCREEN TOGGLE [F11]")
        fs_btn.setFixedHeight(28)
        fs_btn.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        fs_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        fs_btn.setStyleSheet(f"background: {C.PANEL}; color: {C.TEXT_DIM}; border: 1px solid {C.BORDER}; border-radius: 3px;")
        fs_btn.clicked.connect(self._toggle_fullscreen)
        lay.addWidget(fs_btn)

        w.adjustSize()
        w.hide()
        return w

    def _toggle_drawer(self):
        if self._quick_drawer.isVisible():
            self._quick_drawer.hide()
        else:
            self._quick_drawer.setGeometry(12, 46, 260, self._quick_drawer.sizeHint().height())
            self._quick_drawer.show()
            self._quick_drawer.raise_()

    # ── Autostart & Shortcuts ─────────────────────────────────────────────────

    def _check_autostart(self) -> bool:
        try:
            if _OS == "Windows":
                import winreg
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_READ)
                try:
                    winreg.QueryValueEx(key, "FRYDAY_AI")
                    return True
                except FileNotFoundError:
                    return False
                finally:
                    winreg.CloseKey(key)
        except Exception:
            pass
        return False

    def _toggle_autostart(self):
        cur = self._check_autostart()
        try:
            if _OS == "Windows":
                import winreg
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_ALL_ACCESS)
                try:
                    if cur:
                        try: winreg.DeleteValue(key, "FRYDAY_AI")
                        except FileNotFoundError: pass
                        self._append_log("SYS: Auto-start on Windows boot disabled.")
                        self._update_autostart_btn(False)
                    else:
                        pythonw = Path(sys.executable).parent / "pythonw.exe"
                        exe = str(pythonw if pythonw.exists() else sys.executable)
                        script = str(BASE_DIR / "main.py")
                        winreg.SetValueEx(key, "FRYDAY_AI", 0, winreg.REG_SZ, f'"{exe}" "{script}"')
                        self._append_log("SYS: Auto-start on Windows boot enabled.")
                        self._update_autostart_btn(True)
                finally:
                    winreg.CloseKey(key)
        except Exception as e:
            self._append_log(f"ERR: Auto-start failed: {e}")

    def _update_autostart_btn(self, enabled: bool):
        if enabled:
            self._autostart_btn.setText("⚡ AUTO-START ON BOOT: ON")
            self._autostart_btn.setStyleSheet(f"background:{C.GREEN_GHO}; color:{C.GREEN}; border:1px solid {C.GREEN}; border-radius:3px;")
        else:
            self._autostart_btn.setText("⚡ AUTO-START ON BOOT: OFF")
            self._autostart_btn.setStyleSheet(f"background:{C.PANEL}; color:{C.TEXT_DIM}; border:1px solid {C.BORDER}; border-radius:3px;")

    def _toggle_brief(self):
        from memory.config_manager import get_brief_enabled, set_brief_enabled
        new_val = not get_brief_enabled()
        set_brief_enabled(new_val)
        self._update_brief_btn(new_val)
        self._append_log(f"SYS: Morning briefing {'enabled' if new_val else 'disabled'}.")

    def _update_brief_btn(self, enabled: bool):
        if enabled:
            self._brief_btn.setText("🌅 MORNING BRIEFING: ON")
            self._brief_btn.setStyleSheet(f"background:{C.GREEN_GHO}; color:{C.GREEN}; border:1px solid {C.GREEN}; border-radius:3px;")
        else:
            self._brief_btn.setText("🌅 MORNING BRIEFING: OFF")
            self._brief_btn.setStyleSheet(f"background:{C.PANEL}; color:{C.TEXT_DIM}; border:1px solid {C.BORDER}; border-radius:3px;")

    def _create_desktop_shortcut(self):
        try:
            if _OS == "Windows":
                from win32com.client import Dispatch
                desktop = Path(os.environ["USERPROFILE"]) / "Desktop"
                lnk = str(desktop / "DONNA.lnk")
                pythonw = Path(sys.executable).parent / "pythonw.exe"
                target = str(pythonw if pythonw.exists() else sys.executable)
                script = str(BASE_DIR / "main.py")

                sh = Dispatch("WScript.Shell")
                sc = sh.CreateShortCut(lnk)
                sc.TargetPath = target
                sc.Arguments = f'"{script}"'
                sc.WorkingDirectory = str(BASE_DIR)
                sc.Description = "Donna Tactical AI Assistant"
                sc.save()
                self._append_log("SYS: Desktop shortcut created successfully.")
        except Exception as e:
            self._append_log(f"ERR: Shortcut creation failed: {e}")

    def _toggle_fullscreen(self):
        if self.isFullScreen(): self.showNormal()
        else: self.showFullScreen()

    # ── Left Sidebar (SYS Metrics) ────────────────────────────────────────────

    def _build_left_sidebar(self) -> QWidget:
        w = CyberChamferPanel(cut_corner="tl", cut_size=10, bg_col=C.PANEL2, border_col=C.BORDER)
        w.setFixedWidth(78)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 8, 4, 8)
        lay.setSpacing(2)

        hdr = QLabel("SYS")
        hdr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hdr.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color: {C.TEXT_DIM};")
        lay.addWidget(hdr)

        self._m_cpu = MetricBar("CPU", "%", 85)
        self._m_ram = MetricBar("RAM", "%", 85)
        self._m_up  = MetricBar("NET ↑", "Mb/s", 500)
        self._m_dn  = MetricBar("NET ↓", "Mb/s", 500)
        self._m_gpu = MetricBar("GPU", "%", 90)
        self._m_tmp = MetricBar("TMP", "°C", 80)

        for m in (self._m_cpu, self._m_ram, self._m_up, self._m_dn, self._m_gpu, self._m_tmp):
            lay.addWidget(m)

        lay.addStretch()

        core_box = QWidget()
        core_box.setStyleSheet(f"border-top: 1px solid {C.BORDER}; padding-top: 4px;")
        cb_lay = QVBoxLayout(core_box)
        cb_lay.setContentsMargins(0, 0, 0, 0)
        cb_lay.setSpacing(1)
        cl1 = QLabel("AI CORE")
        cl1.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl1.setFont(QFont("Courier New", 6))
        cl1.setStyleSheet(f"color: {C.TEXT_DIM};")
        cl2 = QLabel("● ACTIVE_")
        cl2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl2.setFont(QFont("Courier New", 6, QFont.Weight.Bold))
        cl2.setStyleSheet(f"color: {C.GREEN};")
        self._ai_core_lbl = cl2
        cb_lay.addWidget(cl1); cb_lay.addWidget(cl2)
        lay.addWidget(core_box)
        return w

    def _update_metrics(self):
        s = _metrics.snapshot()
        self._m_cpu.update_val(s["cpu"])
        self._m_ram.update_val(s["mem"])
        self._m_up.update_val(s["net_up"], f"{s['net_up']:.1f}")
        self._m_dn.update_val(s["net_down"], f"{s['net_down']:.1f}")
        if s["gpu"] >= 0: self._m_gpu.update_val(s["gpu"])
        if s["tmp"] >= 0: self._m_tmp.update_val(s["tmp"], f"{s['tmp']:.0f}")

        cursor = "_" if (int(time.time() * 2) % 2 == 0) else ""
        if hasattr(self, "_ai_core_lbl"):
            self._ai_core_lbl.setText(f"● ACTIVE {cursor}")

    # ── Center Area (Sphere & Bottom Tabs) ────────────────────────────────────

    def _build_center_area(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.hud = FridaySphereCanvas(assistant_name=self._assistant_name)
        self.hud.on_clicked = self._on_sphere_clicked
        lay.addWidget(self.hud, stretch=4)
        lay.addWidget(self._build_mini_panels_row(), stretch=0)
        lay.addWidget(self._build_bottom_tabs_panel(), stretch=2)
        return w

    def _build_mini_panels_row(self) -> QWidget:
        row = QWidget()
        row.setFixedHeight(116)
        h = QHBoxLayout(row)
        h.setContentsMargins(20, 4, 20, 4)
        h.setSpacing(36)
        h.addStretch()
        h.addWidget(MiniHudPanel(mode="radar", title="TACTICAL MAP"))
        h.addWidget(MiniHudPanel(mode="gauge", title="TACTICAL ANALYTICS",
                                  value_getter=lambda: _metrics.snapshot()["mem"]))
        h.addWidget(MiniHudPanel(mode="gauge", title="STATUS ANALYTICS",
                                  value_getter=lambda: _metrics.snapshot()["cpu"]))
        h.addStretch()
        return row

    def _on_sphere_clicked(self):
        if hasattr(self, "on_wake_clicked") and callable(self.on_wake_clicked):
            self.on_wake_clicked()

    def _build_bottom_tabs_panel(self) -> QWidget:
        w = CyberChamferPanel(cut_corner="tl", cut_size=10, bg_col=C.PANEL, border_col=C.BORDER)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(6)

        tab_row = QHBoxLayout()
        tab_row.setSpacing(12)

        self._tab_cmd_btn = QPushButton("COMMAND")
        self._tab_cnt_btn = QPushButton("ITINERARY / SEARCH")
        self._tab_anl_btn = QPushButton("ANALYTICS")

        for b, idx in [(self._tab_cmd_btn, 0), (self._tab_cnt_btn, 1), (self._tab_anl_btn, 2)]:
            b.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _, i=idx: self._switch_bottom_tab(i))
            tab_row.addWidget(b)

        tab_row.addStretch()

        self._mute_btn = QPushButton("🎙  MIC ACTIVE")
        self._mute_btn.setFixedHeight(24)
        self._mute_btn.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        self._mute_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._style_mute_btn()
        self._mute_btn.clicked.connect(self._toggle_mute)
        tab_row.addWidget(self._mute_btn)

        lay.addLayout(tab_row)

        self._bottom_stack = QStackedWidget()

        # Tab 0: Command Input
        cmd_w = QWidget()
        cw_lay = QHBoxLayout(cmd_w)
        cw_lay.setContentsMargins(0, 4, 0, 4)
        cw_lay.setSpacing(8)

        prm = QLabel(">")
        prm.setFont(QFont("Orbitron", 10, QFont.Weight.Bold))
        prm.setStyleSheet(f"color: {C.ACCENT_TEXT};")
        cw_lay.addWidget(prm)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Enter tactical command or query…")
        self._input.setFont(QFont("Courier New", 9))
        self._input.setStyleSheet(f"""
            QLineEdit {{
                background: {C.PRI_GHO}; color: {C.PRI};
                border: 1px solid {C.BORDER}; border-radius: 3px; padding: 6px 10px;
            }}
            QLineEdit:focus {{ border: 1px solid {C.ACCENT_TEXT}; }}
        """)
        self._input.returnPressed.connect(self._send_cmd)
        cw_lay.addWidget(self._input, stretch=1)

        tx_btn = QPushButton("TRANSMIT")
        tx_btn.setFixedHeight(30)
        tx_btn.setFont(QFont("Orbitron", 8, QFont.Weight.Bold))
        tx_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        tx_btn.setStyleSheet(f"""
            QPushButton {{
                background: {C.PRI_DIM}; color: {C.PRI};
                border: 1px solid {C.ACCENT_TEXT}; border-radius: 3px; padding: 0 14px;
            }}
            QPushButton:hover {{ background: {C.ACCENT_TEXT}; color: #05090b; border: 1px solid {C.ACCENT_TEXT}; }}
        """)
        tx_btn.clicked.connect(self._send_cmd)
        cw_lay.addWidget(tx_btn)

        self._bottom_stack.addWidget(cmd_w)

        # Tab 1: Itinerary / Search Content Display
        cnt_w = QWidget()
        cnt_lay = QVBoxLayout(cnt_w)
        cnt_lay.setContentsMargins(0, 0, 0, 0)
        cnt_lay.setSpacing(4)
        self._content_title = QLabel("SYSTEM FEED")
        self._content_title.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        self._content_title.setStyleSheet(f"color: {C.PRI};")
        cnt_lay.addWidget(self._content_title)
        self._content_text = QTextEdit()
        self._content_text.setReadOnly(True)
        self._content_text.setFont(QFont("Courier New", 8))
        self._content_text.setStyleSheet(f"""
            QTextEdit {{
                background: #080b0e; color: {C.TEXT};
                border: 1px solid {C.BORDER}; border-radius: 3px; padding: 4px;
            }}
        """)
        cnt_lay.addWidget(self._content_text)
        self._bottom_stack.addWidget(cnt_w)

        # Tab 2: Analytics
        anl_w = QWidget()
        anl_lay = QHBoxLayout(anl_w)
        anl_lay.setContentsMargins(0, 0, 0, 0)
        self._spectro = TacticalSpectrogram()
        anl_lay.addWidget(self._spectro, stretch=1)
        th_box = QVBoxLayout()
        th_box.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        t1 = QLabel("THREAT INDEX")
        t1.setFont(QFont("Courier New", 7)); t1.setStyleSheet(f"color: {C.TEXT_DIM};")
        t2 = QLabel("NOMINAL")
        t2.setFont(QFont("Orbitron", 10, QFont.Weight.Bold)); t2.setStyleSheet(f"color: {C.GREEN};")
        th_box.addWidget(t1); th_box.addWidget(t2)
        anl_lay.addLayout(th_box)
        self._bottom_stack.addWidget(anl_w)

        lay.addWidget(self._bottom_stack)
        self._switch_bottom_tab(0)
        return w

    def _switch_bottom_tab(self, idx: int):
        self._bottom_stack.setCurrentIndex(idx)
        for i, b in enumerate([self._tab_cmd_btn, self._tab_cnt_btn, self._tab_anl_btn]):
            if i == idx:
                b.setStyleSheet(f"background: transparent; color: {C.ACCENT_TEXT}; border-bottom: 2px solid {C.ACCENT_TEXT}; padding: 4px 8px;")
            else:
                b.setStyleSheet(f"background: transparent; color: {C.TEXT_DIM}; border-bottom: 2px solid transparent; padding: 4px 8px;")

    def _send_cmd(self):
        txt = self._input.text().strip()
        if not txt: return
        self._input.clear()
        self._append_log(f"You: {txt}")
        if self.on_text_command:
            threading.Thread(target=self.on_text_command, args=(txt,), daemon=True).start()

    # ── Right Sidebar (Dialogue & Operator) ───────────────────────────────────

    def _build_right_sidebar(self) -> QWidget:
        w = CyberChamferPanel(cut_corner="tr", cut_size=10, bg_col=C.PANEL2, border_col=C.BORDER)
        w.setFixedWidth(310)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        tab_row = QHBoxLayout()
        tab_row.setSpacing(0)
        self._r_dlg_btn = QPushButton("DIALOGUE")
        self._r_opr_btn = QPushButton("OPERATOR")

        for b, idx in [(self._r_dlg_btn, 0), (self._r_opr_btn, 1)]:
            b.setFixedHeight(32)
            b.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _, i=idx: self._switch_right_tab(i))
            tab_row.addWidget(b)

        lay.addLayout(tab_row)

        self._right_stack = QStackedWidget()

        # Tab 0: Dialogue
        dlg_w = QWidget()
        dw_lay = QVBoxLayout(dlg_w)
        dw_lay.setContentsMargins(8, 8, 8, 8)
        dw_lay.setSpacing(6)

        self._alert_lbl = QLabel("◈ Perimeter sensor grid: nominal")
        self._alert_lbl.setFont(QFont("Courier New", 7))
        self._alert_lbl.setStyleSheet(f"color: {C.TEXT_DIM}; border-bottom: 1px solid {C.BORDER_DIM}; padding-bottom: 4px;")
        dw_lay.addWidget(self._alert_lbl)

        self._chat_display = QTextEdit()
        self._chat_display.setReadOnly(True)
        self._chat_display.setFont(QFont("Courier New", 8))
        self._chat_display.setStyleSheet(f"""
            QTextEdit {{
                background: #060809; color: {C.TEXT};
                border: 1px solid {C.BORDER_DIM}; border-radius: 4px; padding: 6px;
            }}
        """)
        dw_lay.addWidget(self._chat_display, stretch=1)

        # Voice Interrupt Button
        act_row = QHBoxLayout()
        intr_btn = QPushButton("⏹ INTERRUPT SPEECH")
        intr_btn.setFixedHeight(26)
        intr_btn.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        intr_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        intr_btn.setStyleSheet(f"""
            QPushButton {{
                background: {C.PANEL}; color: {C.RED};
                border: 1px solid {C.RED_DIM}; border-radius: 3px;
            }}
            QPushButton:hover {{ background: {C.RED_GHO}; }}
        """)
        intr_btn.clicked.connect(self._do_interrupt)
        act_row.addWidget(intr_btn)
        dw_lay.addLayout(act_row)

        self._right_stack.addWidget(dlg_w)

        # Tab 1: Operator
        opr_w = QWidget()
        ow_lay = QVBoxLayout(opr_w)
        ow_lay.setContentsMargins(12, 12, 12, 12)
        ow_lay.setSpacing(8)

        op_hdr = QHBoxLayout()
        av = QLabel("👤")
        av.setFont(QFont("Segoe UI Emoji", 20))
        op_hdr.addWidget(av)
        op_info = QVBoxLayout()
        oname = QLabel(self._user_name.upper())
        oname.setFont(QFont("Orbitron", 10, QFont.Weight.Bold))
        oname.setStyleSheet(f"color: {C.PRI};")
        orole = QLabel("TACTICAL OPERATOR · ONLINE")
        orole.setFont(QFont("Courier New", 7))
        orole.setStyleSheet(f"color: {C.GREEN};")
        op_info.addWidget(oname); op_info.addWidget(orole)
        op_hdr.addLayout(op_info)
        ow_lay.addLayout(op_hdr)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine); sep.setStyleSheet(f"color: {C.BORDER};")
        ow_lay.addWidget(sep)

        details = [
            ("ROLE", "TACTICAL AI CONTROLLER"),
            ("UNIT", "STARK INDUSTRIES / J.I.C."),
            ("CLEARANCE", "TOP SECRET // SCI"),
            ("STATUS", "ONLINE (ENCRYPTED)"),
        ]
        for k, v in details:
            row = QHBoxLayout()
            k_l = QLabel(k); k_l.setFont(QFont("Courier New", 7)); k_l.setStyleSheet(f"color: {C.TEXT_DIM};")
            v_l = QLabel(v); v_l.setFont(QFont("Courier New", 7, QFont.Weight.Bold)); v_l.setStyleSheet(f"color: {C.PRI};")
            row.addWidget(k_l); row.addStretch(); row.addWidget(v_l)
            ow_lay.addLayout(row)

        ow_lay.addSpacing(8)

        remote_btn = QPushButton("📱 REMOTE ACCESS (PHONE QR)")
        remote_btn.setFixedHeight(28)
        remote_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        remote_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        remote_btn.setStyleSheet(f"background: {C.PANEL}; color: {C.PRI}; border: 1px solid {C.BORDER_B}; border-radius: 3px;")
        remote_btn.clicked.connect(self._open_remote)
        ow_lay.addWidget(remote_btn)

        settings_btn = QPushButton("⚙ CONFIGURATION & THEMES")
        settings_btn.setFixedHeight(28)
        settings_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        settings_btn.setStyleSheet(f"background: {C.PANEL}; color: {C.TEXT}; border: 1px solid {C.BORDER}; border-radius: 3px;")
        settings_btn.clicked.connect(self._open_customize)
        ow_lay.addWidget(settings_btn)

        ow_lay.addStretch()
        self._right_stack.addWidget(opr_w)

        lay.addWidget(self._right_stack)
        self._switch_right_tab(0)
        return w

    def _switch_right_tab(self, idx: int):
        self._right_stack.setCurrentIndex(idx)
        if idx == 0:
            self._r_dlg_btn.setStyleSheet(f"background: {C.PANEL2}; color: {C.PRI}; border-bottom: 2px solid {C.PRI};")
            self._r_opr_btn.setStyleSheet(f"background: transparent; color: {C.TEXT_DIM}; border-bottom: 1px solid {C.BORDER};")
        else:
            self._r_opr_btn.setStyleSheet(f"background: {C.PANEL2}; color: {C.PRI}; border-bottom: 2px solid {C.PRI};")
            self._r_dlg_btn.setStyleSheet(f"background: transparent; color: {C.TEXT_DIM}; border-bottom: 1px solid {C.BORDER};")

    def _do_interrupt(self):
        if self.on_interrupt:
            self.on_interrupt()

    # ── Bottom Status Bar Footer ──────────────────────────────────────────────

    def _build_footer(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(24)
        w.setStyleSheet(f"background: #040608; border-top: 1px solid {C.BORDER};")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(14, 0, 14, 0)
        lay.setSpacing(16)

        for txt in ["STARK LINK: ACTIVE", "AES-512: ENGAGED", "PERIMETER: CLEAR"]:
            l = QLabel(txt)
            l.setFont(QFont("Courier New", 7))
            l.setStyleSheet(f"color: {C.TEXT_DIM};")
            lay.addWidget(l)

        lay.addStretch()

        stat = QLabel("DONNA TACTICAL — ALL SYSTEMS NOMINAL")
        stat.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        stat.setStyleSheet(f"color: {C.GREEN};")
        lay.addWidget(stat)

        return w

    # ── File Drag & Drop ──────────────────────────────────────────────────────

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        if urls:
            file_path = urls[0].toLocalFile()
            if os.path.exists(file_path):
                self._current_file = file_path
                fname = Path(file_path).name
                self._append_log(f"SYS: Attached file: {fname} ({file_path})")
                self._show_content(f"FILE ATTACHED: {fname}", f"Path: {file_path}\nReady for tactical analysis.")

    # ── Clipboard Intelligence ────────────────────────────────────────────────

    def _on_clipboard_changed(self):
        try:
            txt = QApplication.clipboard().text().strip()
            if len(txt) > 8 and not txt.startswith("SYS:"):
                # Preview in dialogue alert ticker
                self._alert_lbl.setText(f"◈ Clipboard: {txt[:36]}...")
        except Exception:
            pass

    # ── Event Handlers & State Updates ────────────────────────────────────────

    def _append_log(self, text: str):
        ts = datetime.now().strftime("%H:%M:%S")
        if text.startswith("You:") or text.startswith("User:"):
            msg = text.split(":", 1)[1].strip()
            self._chat_display.append(f"<span style='color:{C.GREEN}; font-weight:bold;'>[{ts}] {self._user_name}:</span> <span style='color:#c8e8d8;'>{msg}</span><br>")
        elif text.startswith("FRYDAY:") or text.startswith("JARVIS:") or text.startswith(f"{self._assistant_name}:"):
            msg = text.split(":", 1)[1].strip()
            self._chat_display.append(f"<span style='color:{C.PRI}; font-weight:bold;'>[{ts}] {self._assistant_name}:</span> <span style='color:{C.TEXT};'>{msg}</span><br>")
        else:
            self._chat_display.append(f"<span style='color:{C.TEXT_DIM};'>[{ts}] {text}</span><br>")
            self._alert_lbl.setText(f"◈ {text[:48]}")

    def _apply_state(self, state: str):
        self.hud.state = state
        self.hud.speaking = (state == "SPEAKING")
        self.hud.update()

    def _show_content(self, title: str, text: str):
        self._content_title.setText(f"◈  {title.upper()}")
        self._content_text.setPlainText(text)
        self._switch_bottom_tab(1)

    def _toggle_mute(self):
        self._muted = not self._muted
        self.hud.muted = self._muted
        self._style_mute_btn()
        if self._muted:
            self._apply_state("MUTED")
            self._append_log("SYS: Microphone muted.")
        else:
            self._apply_state("STANDBY")
            self._append_log("SYS: Microphone active (Standby).")

    def _style_mute_btn(self):
        if self._muted:
            self._mute_btn.setText("🔇  MUTED")
            self._mute_btn.setStyleSheet(f"""
                QPushButton {{
                    background: {C.RED_GHO}; color: {C.RED};
                    border: 1px solid {C.RED_DIM}; border-radius: 3px; padding: 2px 8px;
                }}
            """)
        else:
            self._mute_btn.setText("🎙  MIC ACTIVE")
            self._mute_btn.setStyleSheet(f"""
                QPushButton {{
                    background: {C.GREEN_GHO}; color: {C.GREEN};
                    border: 1px solid {C.GREEN_DIM}; border-radius: 3px; padding: 2px 8px;
                }}
                QPushButton:hover {{ background: rgba(74, 170, 106, 0.18); }}
            """)

    def _check_config(self) -> bool:
        if not API_FILE.exists(): return False
        try:
            d = json.loads(API_FILE.read_text(encoding="utf-8"))
            return bool(d.get("gemini_api_key"))
        except Exception:
            return False

    def _show_setup(self):
        ov = SetupOverlay(self.centralWidget())
        cw = self.centralWidget()
        ow, oh = SetupOverlay._OW, SetupOverlay._OH
        ov.setGeometry((cw.width() - ow) // 2, (cw.height() - oh) // 2, ow, oh)
        ov.done.connect(self._on_setup_done)
        ov.show()
        self._overlay = ov

    def _on_setup_done(self, key: str, os_name: str):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        data = _read_full_config()
        data["gemini_api_key"] = key
        data["os_system"] = os_name
        data.setdefault("assistant_name", "Донна")
        data.setdefault("user_name", "Сэр")
        data.setdefault("gemini_voice", "Kore")
        API_FILE.write_text(json.dumps(data, indent=4, ensure_ascii=False), encoding="utf-8")
        self._ready = True
        self._append_log("SYS: Configuration updated successfully.")

    def _open_customize(self):
        cw = self.centralWidget()
        ov = CustomizeOverlay(parent=cw)
        ow, oh = CustomizeOverlay._OW, CustomizeOverlay._OH
        ov.setGeometry((cw.width() - ow) // 2, (cw.height() - oh) // 2, ow, oh)
        ov.saved.connect(self._on_customize_saved)
        ov.show()
        self._customize_overlay = ov

    def _on_customize_saved(self, asst_name: str, user_name: str, color_hex: str):
        self._assistant_name = asst_name
        self._user_name = user_name
        C.set_accent(color_hex)
        self.hud._asst_name = asst_name.upper()
        self.setWindowTitle(f"{self._assistant_name.upper()} — TACTICAL OS v5.1.0")

        # Save to api_keys.json
        data = _read_full_config()
        data["assistant_name"] = asst_name
        data["user_name"] = user_name
        data["ui_color"] = color_hex
        API_FILE.write_text(json.dumps(data, indent=4, ensure_ascii=False), encoding="utf-8")
        self._append_log(f"SYS: Theme and Identity applied: {asst_name} / {user_name}.")
        self.update()

    def _open_remote(self):
        if not self.on_remote_clicked:
            self._append_log("SYS: Dashboard not running.")
            return
        res = self.on_remote_clicked()
        if not res: return
        url, key, auto, manual = res[0], res[1], (res[2] if len(res) >= 3 else ""), (res[3] if len(res) >= 4 else res[0])
        cw = self.centralWidget()
        ow, oh = RemoteKeyOverlay._OW, RemoteKeyOverlay._OH
        ov = RemoteKeyOverlay(url, key, auto_login_url=auto, manual_url=manual, expiry_secs=600, parent=cw)
        ov.set_new_key_callback(self.on_remote_clicked)
        ov.setGeometry((cw.width() - ow) // 2, (cw.height() - oh) // 2, ow, oh)
        ov.closed.connect(lambda: setattr(self, "_remote_overlay", None))
        ov.show()
        self._remote_overlay = ov

    def notify_phone_connected(self):
        if self._remote_overlay and self._remote_overlay.isVisible():
            self._remote_overlay._key_lbl.setText("CONNECTED")
            self._remote_overlay._key_lbl.setStyleSheet(f"color: {C.GREEN}; background: {C.GREEN_GHO}; border: 1px solid {C.GREEN};")

    def resizeEvent(self, e):
        super().resizeEvent(e)
        cw = self.centralWidget()
        if self._remote_overlay and self._remote_overlay.isVisible():
            ow, oh = RemoteKeyOverlay._OW, RemoteKeyOverlay._OH
            self._remote_overlay.setGeometry((cw.width() - ow) // 2, (cw.height() - oh) // 2, ow, oh)
        if self._overlay and self._overlay.isVisible():
            ow, oh = SetupOverlay._OW, SetupOverlay._OH
            self._overlay.setGeometry((cw.width() - ow) // 2, (cw.height() - oh) // 2, ow, oh)
        if self._customize_overlay and self._customize_overlay.isVisible():
            ow, oh = CustomizeOverlay._OW, CustomizeOverlay._OH
            self._customize_overlay.setGeometry((cw.width() - ow) // 2, (cw.height() - oh) // 2, ow, oh)

    def closeEvent(self, event):
        """Cleanly terminate all sidecar services, MCP processes, and background threads."""
        try:
            from core.mcp_engine import mcp_engine
            for server in list(mcp_engine._servers.values()):
                if server.process:
                    try:
                        server.process.terminate()
                    except Exception:
                        pass
        except Exception:
            pass
        event.accept()
        # Hard exit to ensure zero lingering background processes or daemons
        os._exit(0)


# ── JarvisUI Interface Class Wrapper (Contract with main.py) ──────────────────

class JarvisUI:
    """High-level thread-safe interface for main.py."""

    def __init__(self, face_path: str = ""):
        self._app = QApplication.instance() or QApplication(sys.argv)
        self._win = MainWindow(face_path=face_path)
        self._win.show()

    @property
    def muted(self) -> bool:
        return self._win._muted

    @property
    def current_file(self) -> str | None:
        return self._win._current_file

    @property
    def on_text_command(self):
        return self._win.on_text_command

    @on_text_command.setter
    def on_text_command(self, cb):
        self._win.on_text_command = cb

    @property
    def on_remote_clicked(self):
        return self._win.on_remote_clicked

    @on_remote_clicked.setter
    def on_remote_clicked(self, cb):
        self._win.on_remote_clicked = cb

    @property
    def on_interrupt(self):
        return self._win.on_interrupt

    @on_interrupt.setter
    def on_interrupt(self, cb):
        self._win.on_interrupt = cb

    def set_state(self, state: str):
        self._win._state_sig.emit(state)

    def write_log(self, text: str):
        self._win._log_sig.emit(text)

    def show_content(self, title: str, text: str):
        self._win._content_sig.emit(title[:48], text[:4000])

    def wait_for_api_key(self):
        while not self._win._ready:
            time.sleep(0.1)

    def prompt_reconfig(self):
        self._win._ready = False
        self._win._reconfig_sig.emit()

    def show_camera_frame(self, img_bytes: bytes):
        pass

    def start_camera_stream(self):
        pass

    def stop_camera_stream(self):
        pass

    def notify_phone_connected(self):
        self._win.notify_phone_connected()

    @property
    def assistant_name(self) -> str:
        return self._win._assistant_name

    def start_speaking(self):
        self.set_state("SPEAKING")

    def stop_speaking(self):
        if not self.muted:
            self.set_state("STANDBY")

    def run(self):
        return self._app.exec()

    def exec(self):
        return self._app.exec()

    def mainloop(self):
        return self._app.exec()

    @property
    def root(self):
        return self


if __name__ == "__main__":
    app = QApplication(sys.argv)
    ui = MainWindow()
    ui.show()
    sys.exit(app.exec())