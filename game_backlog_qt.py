# -*- coding: utf-8 -*-
"""
GameBacklog v4.0 «Qt Deck» — PySide6 UI.

Справжня антиаліація, High-DPI, плавні hover-анімації, кастомні картки,
редактор, статистика, Steam/PC-пікери, налаштування й бокова вкладка `game`.
Логіка даних/сканерів — у backlog_core.py.
"""
from __future__ import annotations

import math
import os
import queue
import re
import sys
import threading
from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import (Qt, QRect, QRectF, QPoint, QPointF, QSize, QTimer, QEvent,
                            Property, QPropertyAnimation)
from PySide6.QtGui import (QPainter, QColor, QPen, QBrush, QFont, QFontMetrics, QFontDatabase,
                           QPainterPath, QCursor, QIcon, QKeySequence, QShortcut, QPalette,
                           QPixmap)
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton,
                               QToolButton, QVBoxLayout, QHBoxLayout, QGridLayout, QScrollArea,
                               QStackedWidget, QSplitter, QLineEdit, QComboBox, QSpinBox,
                               QDoubleSpinBox, QTextEdit, QCheckBox, QDialog, QTabWidget,
                               QFileDialog, QMessageBox, QMenu, QSizeGrip, QListWidget,
                               QListWidgetItem, QColorDialog, QButtonGroup, QInputDialog, QCompleter,
                                QAbstractItemView, QStyledItemDelegate, QStyle, QLayout,
                                 QSizePolicy, QSlider)

import backlog_core as core

try:
    import winreg
except ImportError:  # не Windows
    winreg = None

HOTKEY_ID = 1
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
WM_HOTKEY = 0x0312
AUTOSTART_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTOSTART_NAME = "GameBacklog"


def autostart_command() -> str:
    """Команда для автозапуску: зібраний .exe або pythonw + скрипт."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    script = os.path.abspath(sys.argv[0])
    exe = sys.executable
    if os.path.basename(exe).lower() == "python.exe":
        exe = os.path.join(os.path.dirname(exe), "pythonw.exe")
        if not os.path.isfile(exe):
            exe = sys.executable
    return f'"{exe}" "{script}"'


def set_autostart(enabled: bool) -> None:
    """Додає/прибирає GameBacklog у автозапуску поточного користувача."""
    if winreg is None or os.environ.get("GB_NO_AUTOSTART") == "1":
        return
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY, 0,
                            winreg.KEY_WRITE) as key:
            if enabled:
                winreg.SetValueEx(key, AUTOSTART_NAME, 0, winreg.REG_SZ,
                                  autostart_command())
            else:
                try:
                    winreg.DeleteValue(key, AUTOSTART_NAME)
                except FileNotFoundError:
                    pass
    except OSError:
        pass


def app_icon_path() -> str:
    """Шлях до іконки: у зібраному exe вона лежить у _MEIPASS."""
    base = getattr(sys, "_MEIPASS", None)
    if not base:
        if getattr(sys, "frozen", False):
            base = os.path.dirname(sys.executable)
        else:
            base = os.path.dirname(os.path.abspath(__file__))
    for name in ("icon.ico", "icon.png"):
        path = os.path.join(base, name)
        if os.path.isfile(path):
            return path
    return ""


# --------------------------------------------------------------------------- helpers
def qcolor(value: str) -> QColor:
    return QColor(value)


def mix_color(a: str, b: str, t: float) -> QColor:
    return qcolor(core.mix(a, b, t))


def paint_round(painter: QPainter, rect: QRect | QRectF, radius: int,
                fill: QColor | str, outline: QColor | str | None = None,
                width: float = 1.0) -> None:
    path = QPainterPath()
    path.addRoundedRect(QRectF(rect), float(radius), float(radius))
    painter.fillPath(path, QBrush(QColor(fill)))
    if outline is not None:
        pen = QPen(QColor(outline), width)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.drawPath(path)


def alpha_color(value: str | QColor, alpha: int) -> QColor:
    color = QColor(value)
    color.setAlpha(max(0, min(255, int(alpha))))
    return color


def paint_hud_panel(painter: QPainter, rect: QRect | QRectF, fill: str | QColor,
                    border: str | QColor, glow: str | QColor | None = None,
                    radius: int = 6, brackets: bool = True) -> None:
    """Неонова HUD-панель: м'яке свічення, тонка рамка, кутові засічки."""
    r = QRectF(rect)
    path = QPainterPath()
    path.addRoundedRect(r, float(radius), float(radius))
    if glow is not None:
        painter.save()
        painter.setBrush(Qt.NoBrush)
        for spread, alpha in ((7, 16), (4, 30), (2, 52)):
            glow_path = QPainterPath()
            glow_path.addRoundedRect(r.adjusted(-spread, -spread, spread, spread),
                                     float(radius + spread), float(radius + spread))
            pen = QPen(alpha_color(glow, alpha), float(spread + 1))
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.drawPath(glow_path)
        painter.restore()
    painter.fillPath(path, QBrush(QColor(fill)))
    pen = QPen(QColor(border), 1)
    pen.setCosmetic(True)
    painter.setPen(pen)
    painter.drawPath(path)
    if brackets and glow is not None:
        painter.save()
        pen = QPen(alpha_color(glow, 210), 1.4)
        pen.setCosmetic(True)
        painter.setPen(pen)
        n = 9.0
        for px, py, dx, dy in ((r.left(), r.top(), 1, 1), (r.right(), r.top(), -1, 1),
                               (r.left(), r.bottom(), 1, -1), (r.right(), r.bottom(), -1, -1)):
            painter.drawLine(QPointF(px, py), QPointF(px + dx * n, py))
            painter.drawLine(QPointF(px, py), QPointF(px, py + dy * n))
        painter.restore()


def draw_cover_image(painter: QPainter, path: str, rect: QRectF, radius: int = 5) -> bool:
    """Малює справжню обкладинку Steam, обрізану по кутах панелі."""
    if not path or not os.path.isfile(path):
        return False
    pix = QPixmap(path)
    if pix.isNull():
        return False
    target = rect.size().toSize()
    scaled = pix.scaled(target, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    clip = QPainterPath()
    clip.addRoundedRect(rect, float(radius), float(radius))
    painter.save()
    painter.setClipPath(clip)
    sx = (scaled.width() - target.width()) / 2.0
    sy = (scaled.height() - target.height()) / 2.0
    painter.drawPixmap(rect, scaled, QRectF(sx, sy, target.width(), target.height()))
    painter.restore()
    return True


def draw_ui_icon(painter: QPainter, name: str, rect: QRect | QRectF,
                 color: str | QColor, weight: float = 2.0) -> None:
    """Векторні іконки замість піксельних емодзі."""
    r = QRectF(rect)
    painter.save()
    pen = QPen(QColor(color), weight)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    cx, cy = r.center().x(), r.center().y()
    s = min(r.width(), r.height())
    if name == "list":
        for dy in (-0.26, 0.0, 0.26):
            painter.drawLine(QPointF(cx - s * 0.3, cy + dy * s), QPointF(cx + s * 0.3, cy + dy * s))
    elif name == "stats":
        painter.drawLine(QPointF(cx - s * 0.34, cy + s * 0.3), QPointF(cx + s * 0.34, cy + s * 0.3))
        for dx, h in ((-0.22, 0.3), (0.0, 0.48), (0.22, 0.38)):
            painter.drawLine(QPointF(cx + dx * s, cy + s * 0.3),
                             QPointF(cx + dx * s, cy + s * (0.3 - h)))
    elif name == "settings":
        for dy in (-0.15, 0.15):
            painter.drawLine(QPointF(cx - s * 0.3, cy + dy * s), QPointF(cx + s * 0.3, cy + dy * s))
            painter.drawEllipse(QPointF(cx - s * 0.12, cy + dy * s), s * 0.075, s * 0.075)
    elif name == "help":
        painter.drawEllipse(QRectF(cx - s * 0.32, cy - s * 0.32, s * 0.64, s * 0.64))
        painter.setFont(QFont("Segoe UI", max(8, int(s * 0.42)), QFont.Bold))
        painter.drawText(QRectF(cx - s * 0.32, cy - s * 0.32, s * 0.64, s * 0.64),
                         Qt.AlignCenter, "?")
    elif name == "plus":
        painter.drawLine(QPointF(cx - s * 0.25, cy), QPointF(cx + s * 0.25, cy))
        painter.drawLine(QPointF(cx, cy - s * 0.25), QPointF(cx, cy + s * 0.25))
    elif name == "edit":
        painter.drawLine(QPointF(cx - s * 0.28, cy + s * 0.28), QPointF(cx - s * 0.06, cy + s * 0.06))
        painter.drawLine(QPointF(cx - s * 0.12, cy - s * 0.02), QPointF(cx + s * 0.02, cy + s * 0.12))
        painter.drawLine(QPointF(cx - s * 0.04, cy - s * 0.1), QPointF(cx + s * 0.1, cy + s * 0.04))
        painter.drawLine(QPointF(cx + s * 0.28, cy - s * 0.28), QPointF(cx + s * 0.02, cy - s * 0.02))
    elif name == "delete":
        painter.drawRect(QRectF(cx - s * 0.22, cy - s * 0.18, s * 0.44, s * 0.4))
        painter.drawLine(QPointF(cx - s * 0.28, cy - s * 0.18), QPointF(cx + s * 0.28, cy - s * 0.18))
        for dx in (-0.1, 0.0, 0.1):
            painter.drawLine(QPointF(cx + dx * s, cy - s * 0.08), QPointF(cx + dx * s, cy + s * 0.15))
    elif name in ("import", "export"):
        direction = -1 if name == "export" else 1
        painter.drawLine(QPointF(cx, cy - s * 0.3 * direction), QPointF(cx, cy + s * 0.16 * direction))
        painter.drawLine(QPointF(cx - s * 0.13, cy + s * 0.04 * direction),
                         QPointF(cx, cy + s * 0.17 * direction))
        painter.drawLine(QPointF(cx + s * 0.13, cy + s * 0.04 * direction),
                         QPointF(cx, cy + s * 0.17 * direction))
        painter.drawLine(QPointF(cx - s * 0.28, cy + s * 0.3),
                         QPointF(cx + s * 0.28, cy + s * 0.3))
    elif name == "language":
        painter.drawEllipse(QRectF(cx - s * 0.3, cy - s * 0.3, s * 0.6, s * 0.6))
        painter.drawEllipse(QRectF(cx - s * 0.12, cy - s * 0.3, s * 0.24, s * 0.6))
        painter.drawLine(QPointF(cx - s * 0.3, cy), QPointF(cx + s * 0.3, cy))
    elif name == "theme":
        painter.drawEllipse(QRectF(cx - s * 0.28, cy - s * 0.28, s * 0.56, s * 0.56))
        painter.setBrush(QColor(color))
        painter.drawPie(QRectF(cx - s * 0.28, cy - s * 0.28, s * 0.56, s * 0.56), 90 * 16, 180 * 16)
    elif name == "compact":
        painter.drawLine(QPointF(cx + s * 0.28, cy - s * 0.28), QPointF(cx + s * 0.28, cy + s * 0.28))
        painter.drawLine(QPointF(cx - s * 0.22, cy), QPointF(cx + s * 0.14, cy))
        painter.drawLine(QPointF(cx - s * 0.06, cy - s * 0.12), QPointF(cx - s * 0.22, cy))
        painter.drawLine(QPointF(cx - s * 0.06, cy + s * 0.12), QPointF(cx - s * 0.22, cy))
    elif name in ("eye", "eye_off"):
        outline = ((cx - s * 0.34, cy), (cx - s * 0.1, cy - s * 0.17),
                   (cx + s * 0.1, cy - s * 0.17), (cx + s * 0.34, cy),
                   (cx + s * 0.1, cy + s * 0.17), (cx - s * 0.1, cy + s * 0.17))
        for i in range(len(outline)):
            painter.drawLine(QPointF(*outline[i]), QPointF(*outline[(i + 1) % len(outline)]))
        if name == "eye":
            painter.setBrush(QColor(color))
            painter.drawEllipse(QPointF(cx, cy), s * 0.075, s * 0.075)
        else:
            painter.drawLine(QPointF(cx - s * 0.3, cy + s * 0.3),
                             QPointF(cx + s * 0.3, cy - s * 0.3))
    elif name == "check":
        painter.drawLine(QPointF(cx - s * 0.24, cy + s * 0.02),
                         QPointF(cx - s * 0.06, cy + s * 0.19))
        painter.drawLine(QPointF(cx - s * 0.06, cy + s * 0.19),
                         QPointF(cx + s * 0.26, cy - s * 0.2))
    elif name == "play":
        pts = ((cx - s * 0.16, cy - s * 0.25), (cx + s * 0.28, cy),
               (cx - s * 0.16, cy + s * 0.25))
        painter.setBrush(QColor(color))
        painter.drawPolygon(QtGui.QPolygonF([QPointF(px, py) for px, py in pts]))
    elif name == "clock":
        painter.drawEllipse(QRectF(cx - s * 0.28, cy - s * 0.28, s * 0.56, s * 0.56))
        painter.drawLine(QPointF(cx, cy - s * 0.16), QPointF(cx, cy + s * 0.02))
        painter.drawLine(QPointF(cx, cy + s * 0.02), QPointF(cx + s * 0.14, cy + s * 0.1))
    elif name == "cross":
        painter.drawLine(QPointF(cx - s * 0.2, cy - s * 0.2),
                         QPointF(cx + s * 0.2, cy + s * 0.2))
        painter.drawLine(QPointF(cx + s * 0.2, cy - s * 0.2),
                         QPointF(cx - s * 0.2, cy + s * 0.2))
    elif name == "star":
        pts = []
        for i in range(10):
            angle = -1.57079632679 + i * 0.6283185307
            radius = s * (0.29 if i % 2 == 0 else 0.13)
            pts.append(QPointF(cx + radius * math.cos(angle),
                               cy + radius * math.sin(angle)))
        painter.setBrush(QColor(color))
        painter.drawPolygon(QtGui.QPolygonF(pts))
    elif name == "dots":
        painter.setBrush(QColor(color))
        for dx in (-0.12, 0.0, 0.12):
            painter.drawEllipse(QPointF(cx + dx * s, cy), s * 0.035, s * 0.035)
    else:
        painter.drawEllipse(QRectF(cx - s * 0.2, cy - s * 0.2, s * 0.4, s * 0.4))
    painter.restore()


ICON_FOR_KEY = {
    "list": "list", "stats": "stats", "settings": "settings", "help": "help",
    "steam": "plus", "pc": "plus", "edit": "edit", "delete": "delete",
    "import": "import", "export": "export", "language": "language",
    "theme": "theme", "compact": "compact",
}
STATUS_ICON = {
    "want": "plus", "playing": "play", "done": "check",
    "postponed": "clock", "dropped": "cross",
}


def draw_theme_mark(painter: QPainter, theme: str, rect: QRect | QRectF,
                    color: str | QColor) -> None:
    """Невелика пасхалка в шапці: Aegis для Доти, штрихкод для Кіберпанка."""
    r = QRectF(rect)
    painter.save()
    painter.setPen(QPen(QColor(color), 1.3))
    painter.setBrush(Qt.NoBrush)
    cx, cy = r.center().x(), r.center().y()
    s = min(r.width(), r.height())
    if theme == "dota2":
        pts = ((cx, cy - s * 0.36), (cx + s * 0.3, cy - s * 0.2),
               (cx + s * 0.23, cy + s * 0.17), (cx, cy + s * 0.38),
               (cx - s * 0.23, cy + s * 0.17), (cx - s * 0.3, cy - s * 0.2))
        path = QtGui.QPolygonF([QPointF(px, py) for px, py in pts])
        painter.drawPolygon(path)
        painter.drawLine(QPointF(cx, cy - s * 0.2), QPointF(cx, cy + s * 0.2))
        painter.drawLine(QPointF(cx - s * 0.12, cy - s * 0.04),
                         QPointF(cx + s * 0.12, cy - s * 0.04))
    elif theme == "cyberpunk":
        for i, width in enumerate((2, 1, 3, 1, 2, 1, 1, 3, 1)):
            x = r.left() + i * (r.width() / 9)
            painter.setPen(QPen(QColor(color), width))
            painter.drawLine(QPointF(x, r.top() + 2), QPointF(x, r.bottom() - 2))
    else:
        painter.setBrush(QColor(color))
        painter.drawEllipse(QRectF(cx - 3.5, cy - 3.5, 7, 7))
    painter.restore()


def clean_label(text: str) -> str:
    """Прибирає піксельний префікс на кшталт «✎ Правка»."""
    text = str(text or "")
    if text and not text[0].isalnum() and " " in text:
        return text.split(" ", 1)[1]
    return text


def elide(text: str, font: QFont, width: int) -> str:
    return QFontMetrics(font).elidedText(str(text or ""), Qt.ElideRight, max(4, int(width)))


def wrap_text_lines(text: str, font: QFont, width: int) -> list[str]:
    """Розбиває рядок по словах так, щоб кожен рядок вліз у ширину картки."""
    fm = QFontMetrics(font)
    words = str(text or "").split()
    if not words:
        return [""]
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = (current + " " + word).strip()
        if current and fm.horizontalAdvance(candidate) > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return [fm.elidedText(line, Qt.ElideRight, max(4, int(width))) for line in lines]


def fit_lines(text: str, font: QFont, width: int, max_lines: int) -> list[str]:
    """Обрізає багаторядковий заголовок до доступної висоти з многоточиєм."""
    lines = wrap_text_lines(text, font, width)
    if len(lines) <= max_lines:
        return lines
    kept = lines[:max_lines]
    fm = QFontMetrics(font)
    kept[-1] = fm.elidedText(" ".join(lines[max_lines - 1:]), Qt.ElideRight,
                             max(4, int(width)))
    return kept


def set_shadow_free(widget: QWidget) -> None:
    widget.setAttribute(Qt.WA_LayoutUsesWidgetRect, True)


class FlowLayout(QLayout):
    """Сітка обкладинок: самі переносяться на новий ряд по ширині."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 10) -> None:
        super().__init__(parent)
        self._items: list[Any] = []
        self._spacing = spacing
        self.setContentsMargins(4, 4, 4, 12)

    def addItem(self, item) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations()

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._layout(rect, False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.getContentsMargins()
        return size + QSize(margins[0] + margins[2], margins[1] + margins[3])

    def _layout(self, rect: QRect, test_only: bool) -> int:
        margins = self.getContentsMargins()
        x, y = rect.x() + margins[0], rect.y() + margins[1]
        line_h = 0
        for item in self._items:
            w, h = item.sizeHint().width(), item.sizeHint().height()
            next_x = x + w + self._spacing
            if next_x > rect.right() - margins[2] and line_h > 0:
                x = rect.x() + margins[0]
                y += line_h + self._spacing
                next_x = x + w + self._spacing
                if not test_only:
                    item.setGeometry(QRect(QPoint(x, y), QSize(w, h)))
                line_h = h
            else:
                if not test_only:
                    item.setGeometry(QRect(QPoint(x, y), QSize(w, h)))
                line_h = max(line_h, h)
            x = next_x
        return y + line_h - rect.y() + margins[3]


class NeonHost(QWidget):
    """Фон списку ігор: сітка й окремий мотив для кожної теми."""

    WIRES = (
        ((0.00, 0.07), (0.13, 0.12), (0.24, 0.08), (0.36, 0.18), (0.45, 0.14)),
        ((1.00, 0.13), (0.87, 0.20), (0.77, 0.15), (0.68, 0.26), (0.61, 0.22)),
        ((0.00, 0.88), (0.12, 0.80), (0.23, 0.86), (0.33, 0.76), (0.42, 0.81)),
        ((1.00, 0.94), (0.89, 0.86), (0.79, 0.92), (0.70, 0.82), (0.62, 0.87)),
        ((0.00, 0.46), (0.08, 0.51), (0.16, 0.45), (0.24, 0.53)),
        ((1.00, 0.55), (0.92, 0.50), (0.84, 0.56), (0.76, 0.48)),
        ((0.29, 1.00), (0.35, 0.93), (0.44, 0.97), (0.52, 0.90)),
        ((0.72, 0.00), (0.78, 0.07), (0.87, 0.03), (0.94, 0.10)),
    )

    def __init__(self, app: App) -> None:
        super().__init__()
        self.app = app
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("background: transparent;")

    def _draw_rune(self, painter: QPainter, center: QPointF,
                   size: float, color: QColor) -> None:
        """Маленький кутовий рунний знак замість дроту."""
        painter.save()
        painter.translate(center)
        painter.setBrush(Qt.NoBrush)
        pen = QPen(color, 1.2)
        pen.setCosmetic(True)
        painter.setPen(pen)
        diamond = QtGui.QPolygonF((
            QPointF(0, -size), QPointF(size * 0.62, 0),
            QPointF(0, size), QPointF(-size * 0.62, 0),
        ))
        painter.drawPolygon(diamond)
        painter.drawLine(QPointF(0, -size * 0.55), QPointF(0, size * 0.55))
        if size > 8:
            painter.drawLine(QPointF(-size * 0.3, 0), QPointF(size * 0.3, 0))
        painter.restore()

    def _draw_dota_motif(self, painter: QPainter, rect: QRectF,
                         pal: dict[str, str]) -> None:
        """Dota 2: річка Radiant/Dire, руни й hota-кути замість дротів."""
        w, h = rect.width(), rect.height()
        painter.save()

        band = QtGui.QPolygonF((
            QPointF(w * 0.10, 0), QPointF(w * 0.24, 0),
            QPointF(w * 0.94, h), QPointF(w * 0.80, h),
        ))
        grad = QtGui.QLinearGradient(QPointF(w * 0.10, 0), QPointF(w * 0.90, h))
        grad.setColorAt(0.0, alpha_color(pal["accent2"], 28))
        grad.setColorAt(0.5, alpha_color(pal["muted"], 12))
        grad.setColorAt(1.0, alpha_color(pal["status_dropped"], 36))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(grad))
        painter.drawPolygon(band)

        edges = (
            (QPointF(w * 0.10, 0), QPointF(w * 0.80, h), pal["accent2"]),
            (QPointF(w * 0.24, 0), QPointF(w * 0.94, h), pal["status_dropped"]),
        )
        for p1, p2, color in edges:
            for width, alpha in ((6, 16), (3, 38), (1, 105)):
                pen = QPen(alpha_color(color, alpha), width)
                pen.setCosmetic(True)
                painter.setPen(pen)
                painter.drawLine(p1, p2)

        for i in range(12):
            t = (i + 0.5) / 12.0
            side = -1 if i % 2 == 0 else 1
            x = w * (0.17 + 0.66 * t) + side * (18 + (i % 3) * 11)
            y = h * t
            color = pal["accent2"] if i % 2 == 0 else pal["status_dropped"]
            self._draw_rune(painter, QPointF(x, y), 7 + (i % 3) * 2,
                            alpha_color(color, 125))
        for px, py, color in ((0.06, 0.08, pal["accent2"]),
                              (0.94, 0.09, pal["status_dropped"]),
                              (0.06, 0.90, pal["status_dropped"]),
                              (0.94, 0.91, pal["accent2"])):
            self._draw_rune(painter, QPointF(w * px, h * py), 12,
                            alpha_color(color, 90))
        painter.restore()

    def _draw_cyberpunk_motif(self, painter: QPainter, rect: QRectF,
                              pal: dict[str, str]) -> None:
        """Cyberpunk 2077: дощові потоки даних і глітч-смуги."""
        w, h = rect.width(), rect.height()
        cols = max(8, int(w / 42))
        painter.save()

        for i in range(cols):
            x = (i + 0.5) * w / cols
            start = ((i * 53) % int(h + 140)) - 110
            color = pal["accent"] if i % 4 == 0 else pal["accent2"]
            pen = QPen(alpha_color(color, 18), 1)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.drawLine(QPointF(x, 0), QPointF(x, h))
            for j in range(6):
                y = start + j * 38
                if -10 <= y <= h:
                    seg = 8 + ((i + j) % 3) * 7
                    alpha = 55 + ((i + j) % 3) * 35
                    pen = QPen(alpha_color(color, alpha), 2)
                    pen.setCosmetic(True)
                    painter.setPen(pen)
                    painter.drawLine(QPointF(x, y), QPointF(x, y + seg))
                    painter.fillRect(QRectF(x - 2, y + seg, 4, 3),
                                     alpha_color(color, 100))

        bars = (
            (0.12, 0.30, pal["accent"]),
            (0.31, 0.14, pal["status_dropped"]),
            (0.56, 0.36, pal["accent2"]),
            (0.78, 0.20, pal["accent"]),
        )
        for i, (ty, tw, color) in enumerate(bars):
            y = ty * h
            x = ((i * 0.29) % 0.62) * w
            painter.fillRect(QRectF(x, y, tw * w, 2), alpha_color(color, 150))
            painter.fillRect(QRectF(x + 7, y + 4, tw * w * 0.6, 1),
                             alpha_color(color, 75))
            painter.fillRect(QRectF(x + tw * w - 12, y - 3, 5, 8),
                             alpha_color(color, 110))
        painter.restore()

    def _draw_wires(self, painter: QPainter, rect: QRectF,
                    pal: dict[str, str]) -> None:
        """Класика/Світла: обірвані неонові дроти з іскрами."""
        colors = [pal["accent"], pal["accent2"], pal["accent"]]
        for index, points in enumerate(self.WIRES):
            color = colors[index % len(colors)]
            poly = QtGui.QPolygonF([QPointF(px * rect.width(), py * rect.height())
                                    for px, py in points])
            for spread, alpha in ((7, 22), (4, 45), (2, 78), (0, 155)):
                pen = QPen(alpha_color(color, alpha), spread + 1)
                pen.setCosmetic(True)
                pen.setCapStyle(Qt.RoundCap)
                pen.setJoinStyle(Qt.RoundJoin)
                painter.setPen(pen)
                painter.drawPolyline(poly)
            tip = poly.at(poly.size() - 1)
            painter.setBrush(QColor(color))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QRectF(tip.x() - 4, tip.y() - 4, 8, 8))
            for dx, dy in ((-9, -5), (8, -8), (6, 9)):
                painter.setPen(QPen(alpha_color(color, 110), 1.2))
                painter.drawLine(tip, QPointF(tip.x() + dx, tip.y() + dy))

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        pal = self.app.pal()
        rect = QRectF(self.rect())
        grad = QtGui.QLinearGradient(QPointF(0, 0),
                                     QPointF(rect.width(), rect.height()))
        grad.setColorAt(0.0, QColor(pal["bg"]))
        grad.setColorAt(1.0, QColor(pal["header_bg"]))
        painter.fillRect(rect, QBrush(grad))

        theme = self.app.theme_key()
        if theme == "dota2":
            # Червоний Dire домінує в кутах; золото Radiant лише теплий відблиск.
            for px, py, color, alpha in (
                (0.0, 0.0, pal["accent"], 52),
                (1.0, 0.0, pal["status_dropped"], 72),
                (0.5, 1.0, pal["accent2"], 22),
            ):
                glow = QtGui.QRadialGradient(
                    QPointF(px * rect.width(), py * rect.height()),
                    max(rect.width(), rect.height()) * 0.6)
                glow.setColorAt(0.0, alpha_color(color, alpha))
                glow.setColorAt(1.0, alpha_color(color, 0))
                painter.fillRect(rect, QBrush(glow))
        elif theme == "cyberpunk":
            painter.setPen(QPen(alpha_color(pal["accent2"], 14), 1))
            scan_y = 0.0
            while scan_y < rect.height():
                painter.drawLine(QPointF(0, scan_y), QPointF(rect.width(), scan_y))
                scan_y += 5

        grid_pen = QPen(alpha_color(pal["accent"], 20), 1)
        grid_pen.setCosmetic(True)
        painter.setPen(grid_pen)
        step = 44
        x = step
        while x < rect.width():
            painter.drawLine(QPointF(x, 0), QPointF(x, rect.height()))
            x += step
        y = step
        while y < rect.height():
            painter.drawLine(QPointF(0, y), QPointF(rect.width(), y))
            y += step

        if theme == "dota2":
            self._draw_dota_motif(painter, rect, pal)
        elif theme == "cyberpunk":
            self._draw_cyberpunk_motif(painter, rect, pal)
        else:
            self._draw_wires(painter, rect, pal)


class App:
    """Контролер: тримає дані/налаштування й керує вікнами."""

    def __init__(self) -> None:
        self.settings: dict[str, Any] = core.read_settings()
        loc = self.settings.get("language", "ru")
        self.locale = loc if loc in ("ru", "en") else "ru"
        self.dark_mode = bool(self.settings.get("dark_mode", True))
        self.games: list[dict[str, Any]] = core.load_data(self.locale)
        self.selected_id: str | None = None
        self.qapp: QApplication | None = None
        self.window: MainWindow | None = None
        self.dock: EdgeDock | None = None
        self._saved_geometry: QRect | None = None
        self._hotkey: HotkeyFilter | None = None

    # ------------------------------------------------------------- текст/палітра/шрифт
    def tr(self, key: str) -> str:
        return core.TEXTS[self.locale].get(key, key)

    def _custom_status(self, key: str) -> dict[str, str] | None:
        for item in core.custom_statuses(self.settings):
            if item["key"] == key:
                return item
        return None

    def statuses(self) -> list[str]:
        keys = list(core.STATUSES)
        for item in core.custom_statuses(self.settings):
            if item["key"] not in keys:
                keys.append(item["key"])
        return keys

    def status_label(self, key: str) -> str:
        custom = self._custom_status(key)
        if custom:
            return custom["label"]
        return core.STATUS_LABELS[self.locale].get(key, key)

    def status_color(self, key: str) -> str:
        custom = self._custom_status(key)
        if custom and custom.get("color"):
            return custom["color"]
        return self.pal().get("status_" + key, self.pal()["muted"])

    def add_status(self, label: str) -> str:
        custom = core.custom_statuses(self.settings)
        key = "custom_" + core.uuid.uuid4().hex[:8]
        item = {"key": key, "label": label.strip(),
                "color": core.CUSTOM_STATUS_COLORS[len(custom) % len(core.CUSTOM_STATUS_COLORS)]}
        self.settings.setdefault("custom_statuses", []).append(item)
        self._statuses_changed()
        return key

    def rename_status(self, key: str, label: str) -> None:
        for item in self.settings.get("custom_statuses", []):
            if isinstance(item, dict) and item.get("key") == key:
                item["label"] = label.strip()
                break
        self._statuses_changed()

    def delete_status(self, key: str) -> None:
        self.settings["custom_statuses"] = [s for s in self.settings.get("custom_statuses", [])
                                            if not (isinstance(s, dict) and s.get("key") == key)]
        for game in self.games:
            if str(game.get("status")) == key:
                game["status"] = "want"
        core.save_data(self.games, self.locale)
        self._statuses_changed()

    def set_status_color(self, key: str, color: str) -> None:
        for item in self.settings.get("custom_statuses", []):
            if isinstance(item, dict) and item.get("key") == key:
                item["color"] = color
                break
        self._statuses_changed()

    def _statuses_changed(self) -> None:
        core.save_settings(self.settings)
        if self.window is not None:
            self.window.editor.rebuild_statuses()
            self.window.refresh_all()

    def theme_key(self) -> str:
        key = str(self.settings.get("theme") or "classic")
        return key if key in core.THEMES else "classic"

    def pal(self) -> dict[str, str]:
        theme = self.theme_key()
        base = dict(core.THEMES[theme]["palette"])
        for key, value in self.settings.get("colors", {}).items():
            if value and key in base:
                base[key] = value
        return base

    def color(self, key: str) -> str:
        return self.pal()[key]

    def font(self, size: int, bold: bool = False) -> QFont:
        family = self.settings.get("fonts", {}).get("family") or "Segoe UI"
        font = QFont(family, size)
        font.setBold(bold)
        return font

    def tech_font(self, size: int, bold: bool = False) -> QFont:
        families = QFontDatabase.families()
        family = "Bahnschrift" if "Bahnschrift" in families else (
            "Consolas" if "Consolas" in families else self.app_font_family())
        font = QFont(family, size)
        font.setBold(bold)
        return font

    def app_font_family(self) -> str:
        return self.settings.get("fonts", {}).get("family") or "Segoe UI"

    def title_size(self) -> int:
        try:
            return int(self.settings.get("fonts", {}).get("title_size", 14))
        except (TypeError, ValueError):
            return 14

    def toolbar_order(self) -> tuple[list[str], set[str]]:
        raw = self.settings.get("toolbar_order")
        hidden = {k for k in self.settings.get("toolbar_hidden", [])
                  if k in core.TOOLBAR_KEYS}
        order = [k for k in raw if k in core.TOOLBAR_KEYS] if isinstance(raw, list) else []
        order += [k for k in core.TOOLBAR_KEYS if k not in order]
        return order, hidden

    # ------------------------------------------------------------- запуск/перебудова
    def start(self) -> int:
        self.qapp = QApplication(sys.argv)
        self.qapp.setApplicationName("GameBacklog")
        self.qapp.setQuitOnLastWindowClosed(False)
        self.qapp.setStyle("Fusion")
        icon_path = app_icon_path()
        if icon_path:
            self.qapp.setWindowIcon(QIcon(icon_path))
        self.apply_palette()
        core.load_custom_fonts(self.settings.get("fonts", {}).get("custom", []))
        set_autostart(bool(self.settings.get("autostart", False)))
        self._install_hotkey()
        self.window = MainWindow(self)
        self.window.show()
        self.dock = EdgeDock(self)
        if self.settings.get("dock_visible", True):
            self.dock.show()
        result = self.qapp.exec()
        self._remove_hotkey()
        return result

    def apply_palette(self) -> None:
        """Фарбуємо системні віджети, щоб у списку/настройках не було білого."""
        if self.qapp is None:
            return
        p = self.pal()
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(p["bg"]))
        palette.setColor(QPalette.WindowText, QColor(p["fg"]))
        palette.setColor(QPalette.Base, QColor(p["field"]))
        palette.setColor(QPalette.AlternateBase, QColor(p["panel"]))
        palette.setColor(QPalette.Text, QColor(p["fg"]))
        palette.setColor(QPalette.ToolTipBase, QColor(p["field"]))
        palette.setColor(QPalette.ToolTipText, QColor(p["fg"]))
        palette.setColor(QPalette.Button, QColor(p["panel"]))
        palette.setColor(QPalette.ButtonText, QColor(p["fg"]))
        palette.setColor(QPalette.Highlight, QColor(p["sel"]))
        palette.setColor(QPalette.HighlightedText, QColor(p["fg"]))
        palette.setColor(QPalette.Disabled, QPalette.WindowText, QColor(p["muted"]))
        palette.setColor(QPalette.Disabled, QPalette.Text, QColor(p["muted"]))
        self.qapp.setPalette(palette)

    def rebuild(self, *, full: bool = True) -> None:
        """Оновлює налаштування. Повне пересоздання — тільки при зміні мови."""
        self.dark_mode = bool(self.settings.get("dark_mode", True))
        loc = self.settings.get("language", "ru")
        self.locale = loc if loc in ("ru", "en") else "ru"
        core.load_custom_fonts(self.settings.get("fonts", {}).get("custom", []))
        self.apply_palette()
        core.save_settings(self.settings)
        if not full:
            if self.window is not None:
                self.window.apply_theme()
            if self.dock is not None:
                self.dock.apply_settings()
                if self.settings.get("dock_visible", True):
                    self.dock.show()
                else:
                    self.dock.hide()
            return
        geom = None
        if self.window is not None:
            geom = self.window.geometry()
            self.window.close()
        if self.dock is not None:
            self.dock.close()
        self.qapp.processEvents()
        self.window = MainWindow(self)
        if geom is not None:
            self.window.setGeometry(geom)
        self.window.show()
        self.dock = EdgeDock(self)
        if self.settings.get("dock_visible", True):
            self.dock.show()

    def toggle_window(self) -> None:
        if self.window is None:
            return
        if self.window.isVisible():
            self._saved_geometry = self.window.geometry()
            self.window.hide()
        else:
            if self._saved_geometry is not None:
                self.window.setGeometry(self._saved_geometry)
            self.window.show()
            self.window.raise_()
            self.window.activateWindow()

    def collapse(self) -> None:
        if self.window and self.window.isVisible():
            self.toggle_window()

    def quit(self) -> None:
        core.save_data(self.games, self.locale)
        core.save_settings(self.settings)
        if self.dock:
            self.dock.close()
        if self.window:
            self.window.close()
        if self.qapp:
            self.qapp.quit()

    # ------------------------------------------------------------- глобальна клавіша
    def _install_hotkey(self) -> None:
        if os.name != "nt":
            return
        try:
            import ctypes
            user = ctypes.windll.user32
            if user.RegisterHotKey(None, HOTKEY_ID, MOD_CONTROL | MOD_ALT, 0x47):
                self._hotkey = HotkeyFilter(self.toggle_window)
                self.qapp.installNativeEventFilter(self._hotkey)
        except Exception:
            pass

    def _remove_hotkey(self) -> None:
        if os.name != "nt":
            return
        try:
            import ctypes
            ctypes.windll.user32.UnregisterHotKey(None, HOTKEY_ID)
        except Exception:
            pass


class HotkeyFilter(QtCore.QAbstractNativeEventFilter):
    def __init__(self, callback) -> None:
        super().__init__()
        self.callback = callback

    def nativeEventFilter(self, event_type, message):
        kind = event_type.decode("utf-8", "ignore") if isinstance(event_type, bytes) else str(event_type)
        if os.name == "nt" and kind == "windows_generic_MSG":
            try:
                import ctypes
                from ctypes import wintypes
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                    self.callback()
                    return True, 0
            except Exception:
                pass
        return False, 0


# --------------------------------------------------------------------------- картки
class GameCard(QFrame):
    WIDTH, HEIGHT = 170, 220
    clicked = QtCore.Signal(str)

    def __init__(self, game: dict[str, Any], app: App, selected: bool) -> None:
        super().__init__()
        self.game, self.app, self.selected = game, app, selected
        self.setFixedSize(QSize(self.WIDTH, self.HEIGHT))
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)
        self._hover = 0.0
        self._anim = QPropertyAnimation(self, b"hoverLevel", self)
        self._anim.setDuration(140)

    def sizeHint(self) -> QSize:
        return QSize(self.WIDTH, self.HEIGHT)

    def get_hover(self) -> float:
        return self._hover

    def set_hover(self, value: float) -> None:
        self._hover = float(value)
        self.update()

    hoverLevel = Property(float, get_hover, set_hover)

    def _animate(self, end: float) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._hover)
        self._anim.setEndValue(end)
        self._anim.start()

    def enterEvent(self, event) -> None:
        self._animate(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._animate(0.0)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit(str(self.game["id"]))
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        pal = self.app.pal()
        status = str(self.game.get("status", "want"))
        sc = self.app.status_color(status)
        title = str(self.game.get("title", ""))
        platform = str(self.game.get("platform") or "PC")
        glow = pal["accent2"] if self.selected else (
            pal["accent"] if self._hover > 0.05 else None)
        base = pal["card_sel"] if self.selected else core.mix(pal["card"], pal["fg"],
                                                               0.02 + 0.05 * self._hover)
        outline = core.mix(pal["card_border"], glow or pal["fg"],
                           0.6 if self.selected else 0.25 * self._hover)
        rect = QRectF(1, 1, self.width() - 2, self.height() - 2)
        paint_hud_panel(painter, rect, base, outline, glow, 7, brackets=bool(glow))

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(sc))
        painter.drawRoundedRect(QRectF(10, 8, self.width() - 20, 3), 1.5, 1.5)

        f_title = self.app.font(self.app.title_size(), True)
        title_w = self.width() - 20
        fm_title = QFontMetrics(f_title)
        line_h = max(8, fm_title.height())
        chip_h = 16
        chip_top = self.height() - 26
        meta_h = 14
        meta_top = chip_top - 6 - meta_h
        title_bottom = meta_top - 3
        cover_top, cover_gap = 16, 7
        min_cover_h, max_cover_h = 84, 120
        max_title_h = title_bottom - (cover_top + min_cover_h + cover_gap)
        max_lines = max(1, min(3, max_title_h // line_h))
        title_lines = fit_lines(title, f_title, title_w, max_lines)
        need_h = len(title_lines) * line_h
        cover_h = max(min_cover_h, min(max_cover_h,
                      title_bottom - need_h - cover_gap - cover_top))
        cover = QRectF(10, cover_top, title_w, cover_h)
        paint_hud_panel(painter, cover, core.mix(pal["card"], sc, 0.12),
                        core.mix(pal["card_border"], sc, 0.35), sc, 5, brackets=False)
        if not draw_cover_image(painter, str(self.game.get("icon") or ""),
                                cover.adjusted(1, 1, -1, -1), 5):
            painter.setPen(QPen(alpha_color(sc, 26), 1))
            for shift in (-60, -20, 20, 60):
                painter.drawLine(QPointF(cover.left() + shift, cover.bottom()),
                                 QPointF(cover.left() + shift + 70, cover.top()))
            painter.setFont(self.app.tech_font(36, True))
            painter.setPen(QColor(pal["fg"]))
            painter.drawText(cover, Qt.AlignCenter, core.initials(title))

        f_plat = self.app.tech_font(9)
        pw = QFontMetrics(f_plat).horizontalAdvance(platform) + 16
        pill = QRectF(cover.center().x() - pw / 2, cover.bottom() - 24, pw, 16)
        paint_hud_panel(painter, pill, core.mix(base, sc, 0.18),
                        core.mix(pal["card_border"], sc, 0.4), None, 3, brackets=False)
        painter.setPen(QColor(alpha_color(pal["fg"], 230)))
        painter.drawText(pill, Qt.AlignCenter, elide(platform, f_plat, pw - 8))

        title_top = cover_top + cover_h + cover_gap
        painter.setFont(f_title)
        painter.setPen(QColor(pal["fg"]))
        painter.drawText(QRectF(10, title_top, title_w, title_bottom - title_top),
                         Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap,
                         "\n".join(title_lines))

        meta = "  ·  ".join(x for x in (
            str(self.game.get("genre") or "—"),
            ("★ " + str(self.game.get("score"))) if self.game.get("score") else "",
            (str(self.game.get("hours")) + " h") if self.game.get("hours") else "",
        ) if x)
        f_meta = self.app.tech_font(9)
        painter.setFont(f_meta)
        painter.setPen(QColor(pal["muted"]))
        painter.drawText(QRectF(10, meta_top, title_w, meta_h), Qt.AlignHCenter,
                         elide(meta, f_meta, title_w))

        label = self.app.status_label(status).upper()
        lw = QFontMetrics(f_meta).horizontalAdvance(label) + 20
        chip = QRectF((self.width() - lw) / 2, chip_top, lw, chip_h)
        paint_hud_panel(painter, chip, core.mix(base, sc, 0.14),
                        core.mix(pal["card_border"], sc, 0.5), sc, 3, brackets=False)
        painter.setBrush(QColor(sc)); painter.setPen(Qt.NoPen)
        painter.drawEllipse(QRectF(chip.left() + 6, chip.top() + 5, 6, 6))
        painter.setPen(QColor(sc))
        painter.drawText(QRectF(chip.left() + 16, chip.top(), lw - 18, 16),
                         Qt.AlignVCenter, label)


class PickerCard(QFrame):
    HEIGHT = 62
    toggled = QtCore.Signal(int, bool)

    def __init__(self, item: dict[str, str], index: int, app: App) -> None:
        super().__init__()
        self.item, self.index, self.app = item, index, app
        self.selected, self._hover = False, 0.0
        self.setFixedHeight(self.HEIGHT)
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)
        self._anim = QPropertyAnimation(self, b"hoverLevel", self)
        self._anim.setDuration(120)

    def get_hover(self) -> float:
        return self._hover

    def set_hover(self, value: float) -> None:
        self._hover = float(value)
        self.update()

    hoverLevel = Property(float, get_hover, set_hover)

    def enterEvent(self, event) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._hover)
        self._anim.setEndValue(1.0)
        self._anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._hover)
        self._anim.setEndValue(0.0)
        self._anim.start()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.selected = not self.selected
            self.update()
            self.toggled.emit(self.index, self.selected)
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        pal = self.app.pal()
        fill = (pal["card_sel"] if self.selected else
                core.mix(pal["field"], pal["fg"], 0.03 + 0.06 * self._hover))
        outline = core.mix(pal["card_border"], pal["accent"],
                           0.65 if self.selected else 0.35 * self._hover)
        paint_hud_panel(painter, QRectF(4, 2, self.width() - 8, self.HEIGHT - 4),
                        fill, outline, pal["accent"] if (self.selected or self._hover > 0.05)
                        else None, 5, brackets=self.selected)
        badge = str(self.item.get("badge") or "?")[:2].upper()
        art = QRectF(10, 11, 36, 40)
        paint_hud_panel(painter, art,
                        core.mix(pal["field"], pal["accent"], 0.12),
                        core.mix(pal["card_border"], pal["accent"], 0.35),
                        pal["accent2"], 4, brackets=False)
        if draw_cover_image(painter, str(self.item.get("icon") or ""),
                            art.adjusted(1, 1, -1, -1), 4):
            tag = QRectF(art.left() + 1, art.bottom() - 11, 18, 10)
            paint_hud_panel(painter, tag, alpha_color(pal["bg"], 210),
                            alpha_color(pal["accent"], 150), None, 2, brackets=False)
            painter.setFont(self.app.tech_font(7, True))
            painter.setPen(QColor(pal["fg"]))
            painter.drawText(tag, Qt.AlignCenter, badge)
        else:
            painter.setFont(self.app.tech_font(13, True))
            painter.setPen(QColor(pal["fg"]))
            painter.drawText(art, Qt.AlignCenter, badge)

        f_title = self.app.font(12, True)
        f_meta = self.app.font(10)
        text_w = self.width() - 112
        painter.setFont(f_title)
        painter.setPen(QColor(pal["fg"]))
        painter.drawText(QRectF(56, 13, text_w, 20), Qt.AlignVCenter,
                         elide(self.item.get("name", ""), f_title, text_w))
        painter.setFont(f_meta)
        painter.setPen(QColor(pal["muted"]))
        painter.drawText(QRectF(56, 34, text_w, 18), Qt.AlignVCenter,
                         elide(self.item.get("meta", ""), f_meta, text_w))

        cx, cy = self.width() - 24, self.HEIGHT / 2
        if self.selected:
            painter.setBrush(QColor(pal["accent"]))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QRectF(cx - 9, cy - 9, 18, 18))
            draw_ui_icon(painter, "check", QRectF(cx - 6, cy - 6, 12, 12),
                         core.text_on(pal["accent"]), 2.2)
        else:
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(pal["border"]), 1))
            painter.drawEllipse(QRectF(cx - 9, cy - 9, 18, 18))


class RailButton(QFrame):
    clicked = QtCore.Signal(str)

    def __init__(self, key: str, label: str, app: App, active: bool = False) -> None:
        super().__init__()
        self.key, self.label, self.app = key, label, app
        self.active, self._hover = active, 0.0
        self.setFixedSize(QSize(84, 66))
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)
        self._anim = QPropertyAnimation(self, b"hoverLevel", self)
        self._anim.setDuration(130)

    def get_hover(self) -> float:
        return self._hover

    def set_hover(self, value: float) -> None:
        self._hover = float(value)
        self.update()

    hoverLevel = Property(float, get_hover, set_hover)

    def set_active(self, value: bool) -> None:
        self.active = value
        self.update()

    def enterEvent(self, event) -> None:
        self._anim.stop(); self._anim.setStartValue(self._hover)
        self._anim.setEndValue(1.0); self._anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._anim.stop(); self._anim.setStartValue(self._hover)
        self._anim.setEndValue(0.0); self._anim.start()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.key)
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        pal = self.app.pal()
        w = self.width()
        fill = (pal["accent"] if self.active else
                core.mix(pal["panel"], pal["fg"], 0.04 + 0.07 * self._hover))
        icon_rect = QRectF(8, 4, w - 16, 32)
        paint_hud_panel(painter, icon_rect, fill,
                        core.mix(pal["card_border"], pal["accent"],
                                 0.7 if self.active else 0.25 * self._hover),
                        pal["accent2"] if (self.active or self._hover > 0.05) else None,
                        6, brackets=False)
        fg = pal["bg"] if self.active else pal["accent"]
        draw_ui_icon(painter, ICON_FOR_KEY.get(self.key, self.key), icon_rect, fg, 2.2)
        label_font = self.app.font(10, self.active)
        painter.setFont(label_font)
        painter.setPen(QColor(pal["fg"] if self.active else pal["muted"]))
        painter.drawText(QRectF(2, 40, w - 4, 20), Qt.AlignCenter,
                         elide(self.label, label_font, w - 4))


class ToolButton(QFrame):
    clicked = QtCore.Signal(str)

    def __init__(self, key: str, text: str, app: App, *, solid: bool = False) -> None:
        super().__init__()
        self.key, self.text, self.app, self.solid = key, text, app, solid
        self._hover = 0.0
        self._font = app.font(10, solid)
        self.icon = ICON_FOR_KEY.get(key)
        icon_w = 18 if self.icon else 0
        gap = 6 if self.icon else 0
        text_w = QFontMetrics(self._font).horizontalAdvance(text)
        self._icon_rect = QRectF(7, 6, 18, 18) if self.icon else QRectF()
        self._text_rect = QRectF(7 + icon_w + gap, 2, max(4, text_w + 2), 26)
        width = max(34, int(self._text_rect.right() + 10))
        self.setFixedSize(QSize(width, 30))
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)
        self._anim = QPropertyAnimation(self, b"hoverLevel", self)
        self._anim.setDuration(120)

    def get_hover(self) -> float:
        return self._hover

    def set_hover(self, value: float) -> None:
        self._hover = float(value)
        self.update()

    hoverLevel = Property(float, get_hover, set_hover)

    def enterEvent(self, event) -> None:
        self._anim.stop(); self._anim.setStartValue(self._hover)
        self._anim.setEndValue(1.0); self._anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._anim.stop(); self._anim.setStartValue(self._hover)
        self._anim.setEndValue(0.0); self._anim.start()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.key)
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        pal = self.app.pal()
        if self.solid:
            fill = core.mix(pal["accent"], pal["fg"], 0.10 * self._hover)
            fg = core.text_on(pal["accent"])
        else:
            fill = core.mix(pal["panel"], pal["fg"], 0.04 + 0.07 * self._hover)
            fg = pal["fg"]
        paint_hud_panel(painter, QRectF(1, 2, self.width() - 2, 26), fill,
                        core.mix(pal["card_border"], pal["accent"], 0.5 if self.solid else 0.2),
                        pal["accent"] if (self.solid or self._hover > 0.05) else None,
                        5, brackets=False)
        if self.icon:
            draw_ui_icon(painter, self.icon, self._icon_rect, fg, 1.8)
        painter.setFont(self._font)
        painter.setPen(QColor(fg))
        painter.drawText(self._text_rect, Qt.AlignVCenter | Qt.AlignLeft, self.text)


class ThemeCard(QFrame):
    chosen = QtCore.Signal(str)

    def __init__(self, key: str, app: App, selected: bool) -> None:
        super().__init__()
        self.key, self.app, self.selected = key, app, selected
        self.setMinimumSize(QSize(240, 150))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)
        self._hover = 0.0
        self._anim = QPropertyAnimation(self, b"hoverLevel", self)
        self._anim.setDuration(120)

    def get_hover(self) -> float:
        return self._hover

    def set_hover(self, value: float) -> None:
        self._hover = float(value)
        self.update()

    hoverLevel = Property(float, get_hover, set_hover)

    def enterEvent(self, event) -> None:
        self._anim.stop(); self._anim.setStartValue(self._hover)
        self._anim.setEndValue(1.0); self._anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._anim.stop(); self._anim.setStartValue(self._hover)
        self._anim.setEndValue(0.0); self._anim.start()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.chosen.emit(self.key)
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        theme = core.THEMES[self.key]
        p = theme["palette"]
        glow = p["accent"] if (self.selected or self._hover > 0.05) else None
        w, h = self.width(), self.height()
        paint_hud_panel(painter, QRectF(1, 1, w - 2, h - 2), p["panel"],
                        core.mix(p["border"], p["accent"],
                                 0.7 if self.selected else 0.25 * self._hover),
                        glow, 8, brackets=self.selected)

        pad = 14 if w < 340 else 18
        title_h = 28 if h < 180 else 34
        painter.setFont(self.app.tech_font(14 if h < 180 else 17, True))
        painter.setPen(QColor(p["fg"]))
        painter.drawText(QRectF(pad, pad, w - pad * 2 - 28, title_h),
                         Qt.AlignVCenter | Qt.AlignLeft,
                         theme["name"][self.app.locale])
        if self.selected:
            draw_ui_icon(painter, "check", QRectF(w - pad - 22, pad + 5, 18, 18),
                         p["accent"], 2.0)

        bar_h = max(34, int(h * 0.32))
        bar_y = h - pad - bar_h
        desc_y = pad + title_h + 4
        desc_h = max(20, bar_y - desc_y - 8)
        painter.setFont(self.app.font(10 if h < 180 else 11))
        painter.setPen(QColor(p["muted"]))
        painter.drawText(QRectF(pad, desc_y, w - pad * 2, desc_h),
                         Qt.AlignTop | Qt.TextWordWrap,
                         theme["desc"][self.app.locale])

        # Велика палітра кольорів замість крихкої смужки — заповнює картку.
        colors = (p["bg"], p["panel"], p["accent"], p["accent2"])
        bar_w = (w - pad * 2 - 8 * (len(colors) - 1)) // len(colors)
        for i, color in enumerate(colors):
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(color))
            painter.drawRoundedRect(QRectF(pad + i * (bar_w + 8), bar_y, bar_w, bar_h), 5, 5)


class ToolbarPreview(QFrame):
    """Живе прев'ю панелі кнопок у вкладці «Кнопки»."""

    def __init__(self, app: App, order: list[str], hidden: list[str]) -> None:
        super().__init__()
        self.app = app
        self.setFixedHeight(42)
        self.set_state(order, hidden)

    def set_state(self, order: list[str], hidden: list[str]) -> None:
        self.order = list(order)
        self.hidden = set(hidden)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        p = self.app.pal()
        rect = QRectF(1, 1, self.width() - 2, self.height() - 2)
        paint_hud_panel(painter, rect, p["field"],
                        core.mix(p["card_border"], p["accent"], 0.45),
                        p["accent"], 5, brackets=True)
        font = self.app.font(9)
        painter.setFont(font)
        x = 10.0
        for key in self.order:
            if key in self.hidden:
                continue
            if key == "language":
                painter.setPen(QPen(alpha_color(p["border"], 200), 1))
                painter.drawLine(QPointF(x, 8), QPointF(x, self.height() - 8))
                x += 9
            label = clean_label(self.app.tr(core.TOOLBAR_LABELS.get(key, key)))
            icon = ICON_FOR_KEY.get(key)
            icon_w = 16 if icon else 0
            gap = 4 if icon else 0
            text_w = QFontMetrics(font).horizontalAdvance(label)
            total = 7 + icon_w + gap + text_w + 9
            if x + total > rect.right() - 4:
                break
            color = p["accent2"] if key in core.TOOLBAR_RIGHT else p["accent"]
            if icon:
                draw_ui_icon(painter, icon, QRectF(x + 5, 12, 16, 16), color, 1.7)
            painter.setPen(QColor(p["fg"]))
            painter.drawText(QRectF(x + 5 + icon_w + gap, 11, text_w + 2, 20),
                             Qt.AlignVCenter | Qt.AlignLeft, label)
            x += total


class ButtonRowDelegate(QStyledItemDelegate):
    """Малює рядок кнопки з векторним оком замість подвійного кліку."""

    toggleRequested = QtCore.Signal(int)

    def __init__(self, app: App, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.app = app

    def paint(self, painter: QPainter, option, index) -> None:
        key = str(index.data(Qt.UserRole) or "")
        hidden = bool(index.data(Qt.UserRole + 1))
        p = self.app.pal()
        rect = QRectF(option.rect)
        painter.save()
        if option.state & QStyle.State_Selected:
            painter.fillRect(rect, QColor(p["sel"]))
            pen = QPen(QColor(p["accent"]), 1)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.drawRect(rect.adjusted(0.5, 0.5, -0.5, -0.5))
        font = self.app.font(10)
        painter.setFont(font)
        painter.setPen(QColor(p["muted"] if hidden else p["fg"]))
        label = clean_label(self.app.tr(core.TOOLBAR_LABELS.get(key, key)))
        painter.drawText(rect.adjusted(10, 0, -32, 0), Qt.AlignVCenter | Qt.AlignLeft,
                         label)
        draw_ui_icon(painter, "eye_off" if hidden else "eye",
                     QRectF(rect.right() - 28, rect.top() + 5, 18, 18),
                     p["muted"] if hidden else p["accent"], 1.6)
        painter.restore()

    def editorEvent(self, event, model, option, index) -> bool:
        if event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            rect = option.rect
            eye = QRect(rect.right() - 32, rect.top() + 2, 26, rect.height() - 4)
            if eye.contains(event.position().toPoint()):
                self.toggleRequested.emit(index.row())
                return True
        return super().editorEvent(event, model, option, index)


class CoverTile(QFrame):
    """Міні-обкладинка в редакторі: без статусної плашки під іконкою."""

    HEIGHT = 88

    def __init__(self, app: App) -> None:
        super().__init__()
        self.app = app
        self.setFixedHeight(self.HEIGHT)
        self.title, self.platform, self.status, self.icon = "", "", "want", ""
        self.bind_data({})

    def bind_data(self, game: dict[str, Any] | str | None = None, platform: str = "",
                  status: str = "want", icon: str = "") -> None:
        if isinstance(game, dict):
            self.title = str(game.get("title") or "")
            self.platform = str(game.get("platform") or "PC")
            self.status = str(game.get("status") or "want")
            self.icon = str(game.get("icon") or "")
        else:
            self.title = str(game or "")
            self.platform = platform
            self.status = status
            self.icon = icon
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        pal = self.app.pal()
        sc = self.app.status_color(self.status)
        paint_hud_panel(painter, QRectF(2, 2, self.width() - 4, self.HEIGHT - 4),
                        pal["card"], core.mix(pal["card_border"], pal["accent"], 0.35),
                        pal["accent"], 6, brackets=True)
        art = QRectF(12, 14, 62, 62)
        paint_hud_panel(painter, art, core.mix(pal["card"], sc, 0.16),
                        core.mix(pal["card_border"], sc, 0.4), sc, 5, brackets=False)
        if not draw_cover_image(painter, self.icon, art.adjusted(1, 1, -1, -1), 5):
            painter.setFont(self.app.tech_font(17, True))
            painter.setPen(QColor(pal["fg"]))
            painter.drawText(art, Qt.AlignCenter, core.initials(self.title or "?"))

        f_title = self.app.font(13, True)
        painter.setFont(f_title)
        painter.setPen(QColor(pal["fg"]))
        painter.drawText(QRectF(86, 16, self.width() - 100, 24), Qt.AlignVCenter,
                         elide(self.title or self.app.tr("editor_hint"),
                               f_title, self.width() - 100))
        f_plat = self.app.font(10)
        painter.setFont(f_plat)
        painter.setPen(QColor(pal["muted"]))
        painter.drawText(QRectF(86, 44, self.width() - 100, 20), Qt.AlignVCenter,
                         elide(self.platform or "PC", f_plat, self.width() - 100))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(sc))
        painter.drawEllipse(QRectF(self.width() - 17, 51, 6, 6))


class StatusChip(QFrame):
    """Вертикальний рядок статусу з векторною іконкою та меню для своїх статусів."""

    chosen = QtCore.Signal(str)
    menuRequested = QtCore.Signal(str, QPoint)

    def __init__(self, key: str, app: App) -> None:
        super().__init__()
        self.key, self.app = key, app
        self.active = False
        self.custom = key not in core.STATUSES
        self.setFixedHeight(34)
        self.setCursor(Qt.PointingHandCursor)

    def set_active(self, value: bool) -> None:
        self.active = value
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.chosen.emit(self.key)
        elif event.button() == Qt.RightButton and self.custom:
            self.menuRequested.emit(self.key, event.globalPosition().toPoint())
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        pal = self.app.pal()
        sc = self.app.status_color(self.key)
        fill = core.mix(sc, pal["panel"], 0.86 if self.active else 0.95)
        outline = core.mix(sc, pal["panel"], 0.25 if self.active else 0.72)
        paint_hud_panel(painter, QRectF(1, 1, self.width() - 2, self.height() - 2),
                        fill, outline, sc if self.active else None, 5, brackets=False)

        icon_rect = QRectF(8, 7, 20, 20)
        paint_hud_panel(painter, icon_rect,
                        core.mix(sc, pal["panel"], 0.25 if self.active else 0.72),
                        sc, None, 4, brackets=False)
        draw_ui_icon(painter, STATUS_ICON.get(self.key, "star"), icon_rect,
                     pal["bg"] if self.active else sc, 1.8)

        f = self.app.font(11, self.active)
        painter.setFont(f)
        painter.setPen(QColor(sc if self.active else pal["fg"]))
        right = 30 if self.custom else 10
        painter.drawText(QRectF(36, 3, max(4, self.width() - 36 - right), 28),
                         Qt.AlignVCenter, elide(self.app.status_label(self.key), f,
                                                self.width() - 36 - right))
        if self.custom:
            draw_ui_icon(painter, "dots", QRectF(self.width() - 26, 11, 14, 12),
                         pal["muted"], 2.2)


class StatCard(QFrame):
    def __init__(self, label: str, value: str, color: str, app: App, tall: bool = False) -> None:
        super().__init__()
        self.label, self.value, self.color, self.app = label, value, color, app
        self.setFixedHeight(96 if tall else 84)
        self.setMinimumWidth(150)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        pal = self.app.pal()
        paint_hud_panel(painter, QRectF(2, 2, self.width() - 4, self.height() - 4),
                        pal["card"], core.mix(pal["card_border"], self.color, 0.3),
                        self.color, 6, brackets=True)
        paint_hud_panel(painter, QRectF(14, 16, 4, self.height() - 32), self.color,
                        self.color, self.color, 2, brackets=False)
        painter.setFont(self.app.tech_font(10, True))
        painter.setPen(QColor(pal["muted"]))
        painter.drawText(QRectF(28, 12, self.width() - 36, 20), Qt.AlignVCenter,
                         elide(self.label.upper(), self.app.tech_font(10, True), self.width() - 36))
        painter.setFont(self.app.tech_font(20, True))
        painter.setPen(QColor(pal["fg"]))
        painter.drawText(QRectF(28, self.height() - 36, self.width() - 36, 28),
                         Qt.AlignVCenter, elide(self.value, self.app.tech_font(20, True),
                                                self.width() - 36))


# --------------------------------------------------------------------------- заголовок
class TitleButton(QFrame):
    """Векторні кнопки вікна замість текстових `─ □ ✕`."""

    clicked = QtCore.Signal()

    def __init__(self, kind: str, app: App) -> None:
        super().__init__()
        self.kind, self.app, self._hover = kind, app, False
        self.setFixedSize(QSize(28, 26))
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)

    def enterEvent(self, event) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        p = self.app.pal()
        color = (p["status_dropped"] if self.kind == "close" else p["accent"]) \
            if self._hover else p["muted"]
        if self._hover:
            paint_round(painter, QRectF(2, 2, self.width() - 4, self.height() - 4),
                        4, core.mix(p["panel"], color, 0.16))
        r = QRectF(10, 9, 8, 8)
        painter.setPen(QPen(QColor(color), 1.5))
        painter.setBrush(Qt.NoBrush)
        if self.kind == "min":
            painter.drawLine(QPointF(r.left(), r.center().y()),
                             QPointF(r.right(), r.center().y()))
        elif self.kind == "max":
            painter.drawRect(r)
        else:
            painter.drawLine(QPointF(r.left(), r.top()), QPointF(r.right(), r.bottom()))
            painter.drawLine(QPointF(r.right(), r.top()), QPointF(r.left(), r.bottom()))


class TitleBar(QFrame):
    def __init__(self, window: "MainWindow") -> None:
        super().__init__()
        self.window_ref = window
        self.app = window.app
        self.setFixedHeight(38)
        self.setCursor(Qt.ArrowCursor)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(42, 0, 8, 0)
        layout.setSpacing(8)
        self.title_label = QLabel(self.app.tr("app_name"))
        self.title_label.setFont(self.app.tech_font(12, True))
        self.title_label.setStyleSheet("background: transparent;")
        layout.addWidget(self.title_label)
        layout.addStretch(1)
        for kind, handler in (("min", self._minimize), ("max", self._maximize),
                              ("close", self._close)):
            btn = TitleButton(kind, self.app)
            btn.clicked.connect(handler)
            layout.addWidget(btn)
        self._drag_pos: QPoint | None = None

    def _minimize(self) -> None:
        self.window_ref.showMinimized()

    def _maximize(self) -> None:
        if self.window_ref.isMaximized():
            self.window_ref.showNormal()
        else:
            self.window_ref.showMaximized()

    def _close(self) -> None:
        self.window_ref.app.collapse()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.window_ref.underMouse():
            self._drag_pos = event.globalPosition().toPoint() - self.window_ref.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_pos is not None and event.buttons() & Qt.LeftButton:
            self.window_ref.move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        self._maximize()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        pal = self.app.pal()
        paint_round(painter, QRectF(0, 0, self.width(), self.height()), 0, pal["header_bg"])
        gradient = QtGui.QLinearGradient(QPointF(0, 0), QPointF(self.width(), 0))
        gradient.setColorAt(0.0, alpha_color(pal["accent"], 230))
        gradient.setColorAt(0.45, alpha_color(pal["accent2"], 160))
        gradient.setColorAt(1.0, alpha_color(pal["accent2"], 0))
        painter.setPen(Qt.NoPen)
        painter.fillRect(QRectF(0, self.height() - 2, self.width(), 2), QBrush(gradient))
        draw_theme_mark(painter, self.app.theme_key(),
                        QRectF(13, 10, 18, 18), pal["accent"])


# --------------------------------------------------------------------------- головне вікно
class MainWindow(QMainWindow):
    def __init__(self, app: App) -> None:
        super().__init__()
        self.app = app
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowTitle(self.app.tr("app_name"))
        icon_path = app_icon_path()
        if icon_path:
            self.setWindowIcon(QIcon(icon_path))
        self.resize(1180, 730)
        self.setMinimumSize(920, 620)
        self.cards: list[GameCard] = []
        self.chips: dict[str, StatusChip] = {}
        self.toolbar_buttons: dict[str, ToolButton] = {}
        self.rail_buttons: dict[str, RailButton] = {}
        self.vars: dict[str, QWidget] = {}
        self.active_tab = "list"
        self.search_text = ""
        self.filter_status_key = "all"
        self.filter_platform_value = "all"
        self.active_only_bool = False
        self.sort_key = "custom"
        self._updating = False
        self._icon_backfill_tasks: queue.Queue = queue.Queue()
        self._icon_backfill_q: queue.Queue = queue.Queue()
        self._icon_backfill_pending = 0
        self._icon_backfill_queued: set[str] = set()
        self._icon_backfill_active = False

        self._central = QWidget()
        self.setCentralWidget(self._central)
        outer = QVBoxLayout(self._central)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(0)
        self._shell = QFrame()
        self._shell.setObjectName("shell")
        outer.addWidget(self._shell)
        shell_layout = QVBoxLayout(self._shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)
        shell_layout.addWidget(TitleBar(self))

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        shell_layout.addLayout(body, 1)
        body.addWidget(self._build_rail())
        self.stack = QStackedWidget()
        body.addWidget(self.stack, 1)
        self.list_view = self._build_list_view()
        self.stats_view = self._build_stats_view()
        self.settings_view = SettingsDialog(self.app, embedded=True,
                                            on_close=self.show_list)
        self.help_view = HelpDialog(self.app, embedded=True,
                                    on_close=self.show_list)
        self.stack.addWidget(self.list_view)
        self.stack.addWidget(self.stats_view)
        self.stack.addWidget(self.settings_view)
        self.stack.addWidget(self.help_view)
        shell_layout.addWidget(self._build_statusbar())
        grip = QSizeGrip(self._shell)
        grip.setFixedSize(16, 16)
        shell_layout.addWidget(grip, 0, Qt.AlignRight)

        self._apply_sheet()
        self.refresh_all()
        # Редактор вимкнено при запуску — відкривається тільки кліком по картці.
        self.editor.clear()
        self.hide_editor()
        self._start_icon_backfill()

    # ------------------------------------------------------------- іконки й перевірка Steam
    def _start_icon_backfill(self, games: list[dict[str, Any]] | None = None) -> None:
        """Підтягує обкладинки й перевірені жанри Steam-ігор."""
        if os.environ.get("GB_NO_ICON_BACKFILL") == "1":
            return
        if self.app.window is not None and self.app.window is not self:
            return

        added = False
        for game in (self.app.games if games is None else games):
            game_id = str(game["id"])
            if game_id in self._icon_backfill_queued:
                continue
            icon = str(game.get("icon") or "")
            has_icon = bool(icon and os.path.isfile(icon) and os.path.getsize(icon) > 0)
            if has_icon and core.is_steam_verified(game):
                continue
            appid = str(game.get("appid") or "").strip()
            if not appid.isdigit():
                appid = core.appid_from_link(game.get("link", ""))
            if not appid:
                continue
            self._icon_backfill_queued.add(game_id)
            self._icon_backfill_tasks.put((game_id, appid, not has_icon))
            self._icon_backfill_pending += 1
            added = True
        if not added:
            return
        if not self._icon_backfill_active:
            self._icon_backfill_active = True
            threading.Thread(target=self._icon_backfill_worker,
                             args=(self._icon_backfill_tasks, self._icon_backfill_q),
                             daemon=True).start()
            QTimer.singleShot(120, self._poll_icon_backfill)

    @staticmethod
    def _icon_backfill_worker(tasks: queue.Queue, results: queue.Queue) -> None:
        while True:
            item = tasks.get()
            if item is None:
                break
            game_id, appid, need_icon = item
            data = core.steam_appdata(appid)
            header = str(data.get("header_image") or "")
            path = core.cache_steam_icon(appid, header) if (need_icon or header) else ""
            genres = [str(g.get("description") or "") for g in data.get("genres", [])
                      if g.get("description")]
            results.put((game_id, appid, path, genres, bool(data)))

    def _poll_icon_backfill(self) -> None:
        if self.app.window is not None and self.app.window is not self:
            return
        while True:
            try:
                game_id, appid, path, genres, ok = self._icon_backfill_q.get_nowait()
            except queue.Empty:
                break
            self._icon_backfill_pending -= 1
            self._icon_backfill_queued.discard(game_id)
            game = next((g for g in self.app.games
                         if str(g["id"]) == str(game_id)), None)
            if game is None:
                continue
            changed = False
            if ok:
                core.mark_steam_verified(game, genres, appid)
                changed = True
            if path and os.path.isfile(path) and os.path.getsize(path) > 0:
                game["icon"] = path
                game["appid"] = appid
                changed = True
            if not changed:
                continue
            core.save_data(self.app.games, self.app.locale)
            for card in self.cards:
                if str(card.game["id"]) == str(game_id):
                    card.game["icon"] = str(game.get("icon") or "")
                    card.game["appid"] = appid
                    card.update()
            if self.app.selected_id == str(game_id):
                self.editor.cover.bind_data(game)
                self.editor.update_verify_label(game)
            if self.active_tab == "stats":
                self.build_stats()
        if self._icon_backfill_pending > 0:
            QTimer.singleShot(120, self._poll_icon_backfill)
        else:
            self._icon_backfill_active = False
            self._icon_backfill_tasks.put(None)

    # ------------------------------------------------------------- палітра stylesheet
    def _apply_sheet(self) -> None:
        p = self.app.pal()
        self.setStyleSheet(f"""
            QWidget {{ background: {p['bg']}; color: {p['fg']}; }}
            QDialog, QScrollArea, QTabWidget, QStackedWidget {{ background: {p['bg']}; }}
            QFrame#shell {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 {p['header_bg']}, stop:0.55 {p['bg']}, stop:1 {p['panel']});
                border: 1px solid {p['card_border']}; border-radius: 12px; }}
            QLabel {{ background: transparent; color: {p['fg']}; }}
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit {{
                background: {p['field']}; color: {p['fg']};
                border: 1px solid {p['border']}; border-radius: 4px;
                padding: 5px 8px; selection-background-color: {p['sel']};
            }}
            QComboBox::drop-down {{ border: none; }}
            QComboBox QAbstractItemView {{ background: {p['panel']}; color: {p['fg']};
                border: 1px solid {p['border']}; selection-background-color: {p['sel']}; }}
            QCheckBox {{ color: {p['muted']}; spacing: 6px; }}
            QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}
            QScrollBar::handle:vertical {{ background: {p['border']}; border-radius: 4px; min-height: 30px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QScrollBar:horizontal {{ background: transparent; height: 8px; }}
            QScrollBar::handle:horizontal {{ background: {p['border']}; border-radius: 4px; min-width: 30px; }}
            QMenu {{ background: {p['panel']}; color: {p['fg']};
                border: 1px solid {p['border']}; border-radius: 8px; padding: 4px; }}
            QMenu::item {{ padding: 6px 20px; border-radius: 4px; }}
            QMenu::item:selected {{ background: {p['sel']}; }}
            QTabWidget::pane {{ border: 1px solid {p['border']}; border-radius: 8px;
                background: {p['panel']}; top: -1px; }}
            QTabBar::tab {{ background: {p['bg']}; color: {p['muted']}; padding: 8px 16px;
                border: 1px solid {p['border']}; border-radius: 4px; margin-right: 4px; }}
            QTabBar::tab:selected {{ background: {p['sel']}; color: {p['fg']}; }}
        """)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setBrush(Qt.NoBrush)
        super().paintEvent(event)

    # ------------------------------------------------------------- рейл / тулбар
    def _build_rail(self) -> QWidget:
        rail = QFrame()
        rail.setFixedWidth(92)
        p = self.app.pal()
        rail.setStyleSheet(f"background: qlineargradient(x1:0, y1:0, x2:0, y2:1, "
                           f"stop:0 {p['header_bg']}, stop:1 {p['bg']}); "
                           "border-radius: 0 0 0 12px;")
        layout = QVBoxLayout(rail)
        layout.setContentsMargins(4, 8, 4, 8)
        layout.setSpacing(4)
        entries = [("list", self.app.tr("tab_list")),
                   ("stats", self.app.tr("tab_stats")),
                   ("settings", self.app.tr("settings")),
                   ("help", self.app.tr("help"))]
        for key, label in entries:
            button = RailButton(key, clean_label(label), self.app, active=(key == "list"))
            button.clicked.connect(self._on_rail)
            self.rail_buttons[key] = button
            layout.addWidget(button)
        layout.addStretch(1)
        return rail

    def _on_rail(self, key: str) -> None:
        if key == "list":
            self.show_list()
        elif key == "stats":
            self.show_stats()
        elif key == "settings":
            self.show_settings()
        elif key == "help":
            self.show_help()

    def _build_toolbar(self) -> QWidget:
        self.toolbar_buttons.clear()
        bar = QWidget()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        order, hidden = self.app.toolbar_order()
        left, right = [], []
        for key in order:
            if key in hidden:
                continue
            label = clean_label(self.app.tr(core.TOOLBAR_LABELS.get(key, key)))
            btn = ToolButton(key, label, self.app,
                             solid=(key in ("steam", "pc")))
            btn.clicked.connect(self._on_tool)
            self.toolbar_buttons[key] = btn
            (right if key in core.TOOLBAR_RIGHT else left).append(btn)
        for btn in left:
            layout.addWidget(btn)
        layout.addStretch(1)
        for btn in right:
            layout.addWidget(btn)
        return bar

    def rebuild_toolbar(self) -> None:
        layout = self.list_view.layout()
        old = getattr(self, "toolbar_widget", None)
        index = layout.indexOf(old) if old is not None else -1
        if old is not None:
            layout.removeWidget(old)
            old.deleteLater()
        self.toolbar_widget = self._build_toolbar()
        layout.insertWidget(index if index >= 0 else 2, self.toolbar_widget)

    def apply_theme(self) -> None:
        """Оновлює вигляд без закриття/пересоздання вікна — без миготіння."""
        self._apply_sheet()
        self.rebuild_toolbar()
        self.library_label.setFont(self.app.tech_font(11, True))
        self.library_label.setStyleSheet(f"color: {self.app.pal()['muted']};")
        self.library_label.setText(
            self.app.tr("library_eyebrow").format(len(self.app.games)))
        for card in self.cards:
            card.update()
        self.editor.update()
        for chip in self.chips.values():
            chip.update()
        self._update_statusbar(len(self.cards))

    def _on_tool(self, key: str) -> None:
        actions = {"steam": self.steam_add, "pc": self.pc_add,
                   "delete": self.delete_game, "import": self.import_games,
                   "export": self.export_games, "compact": self.app.collapse}
        action = actions.get(key)
        if action:
            action()

    # ------------------------------------------------------------- список
    def _build_list_view(self) -> QWidget:
        view = QWidget()
        layout = QVBoxLayout(view)
        layout.setContentsMargins(14, 10, 14, 8)
        layout.setSpacing(8)
        p = self.app.pal()
        self.library_label = QLabel(self.app.tr("library_eyebrow").format(len(self.app.games)))
        self.library_label.setFont(self.app.tech_font(11, True))
        self.library_label.setStyleSheet(f"color: {p['muted']};")
        layout.addWidget(self.library_label)
        hint = QLabel(self.app.tr("hint"))
        hint.setFont(self.app.font(10))
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {p['muted']};")
        layout.addWidget(hint)
        self.toolbar_widget = self._build_toolbar()
        layout.addWidget(self.toolbar_widget)

        filters = QHBoxLayout()
        filters.setSpacing(8)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(self.app.tr("search"))
        self.search_edit.textChanged.connect(self._on_search)
        filters.addWidget(self.search_edit, 2)
        self.status_combo = QComboBox()
        self.status_combo.currentIndexChanged.connect(self._on_filter)
        filters.addWidget(self.status_combo, 1)
        self.platform_combo = QComboBox()
        self.platform_combo.currentIndexChanged.connect(self._on_filter)
        filters.addWidget(self.platform_combo, 1)
        self.active_check = QCheckBox(self.app.tr("active_only"))
        self.active_check.stateChanged.connect(self._on_filter)
        filters.addWidget(self.active_check)
        self.sort_combo = QComboBox()
        self.sort_combo.currentIndexChanged.connect(self._on_sort)
        filters.addWidget(self.sort_combo, 1)
        layout.addLayout(filters)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(True)
        self.splitter = splitter
        self.cards_area = QScrollArea()
        self.cards_area.setWidgetResizable(True)
        self.cards_area.setFrameShape(QFrame.NoFrame)
        self.cards_host = NeonHost(self.app)
        self.cards_layout = FlowLayout(self.cards_host, spacing=10)
        self.cards_area.setWidget(self.cards_host)
        splitter.addWidget(self.cards_area)
        self.editor = EditorPanel(self.app, self)
        splitter.addWidget(self.editor)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([640, 380])
        layout.addWidget(splitter, 1)
        self._update_filter_values()
        return view

    def _update_filter_values(self) -> None:
        self.status_combo.blockSignals(True)
        self.platform_combo.blockSignals(True)
        self.sort_combo.blockSignals(True)
        self.status_combo.clear()
        self.status_combo.addItem(self.app.tr("all"), "all")
        for key in self.app.statuses():
            self.status_combo.addItem(self.app.status_label(key), key)
        platforms = sorted({str(g.get("platform", "")) for g in self.app.games if g.get("platform")},
                           key=str.lower)
        self.platform_combo.clear()
        self.platform_combo.addItem(self.app.tr("all"), "all")
        for platform in platforms:
            self.platform_combo.addItem(platform, platform)
        self.sort_combo.clear()
        for key in core.SORT_KEYS:
            self.sort_combo.addItem(core.SORT_TEXT[self.app.locale][key], key)
        current = self.app.tr("all")
        self.status_combo.setCurrentText(current)
        self.platform_combo.setCurrentText(current)
        self.sort_combo.setCurrentText(core.SORT_TEXT[self.app.locale][self.sort_key])
        self.status_combo.blockSignals(False)
        self.platform_combo.blockSignals(False)
        self.sort_combo.blockSignals(False)

    def _on_search(self, text: str) -> None:
        self.search_text = text.strip().lower()
        self.refresh_cards()

    def _on_filter(self, *_args) -> None:
        self.filter_status_key = self.status_combo.currentData() or "all"
        self.filter_platform_value = self.platform_combo.currentData() or "all"
        self.active_only_bool = self.active_check.isChecked()
        self.refresh_cards()

    def _on_sort(self, *_args) -> None:
        self.sort_key = self.sort_combo.currentData() or "custom"
        self.refresh_cards()

    def _visible_games(self) -> list[dict[str, Any]]:
        games = list(self.app.games)
        if self.search_text:
            games = [g for g in games if self.search_text in str(g.get("title", "")).lower()
                     or self.search_text in str(g.get("genre", "")).lower()]
        if self.filter_status_key != "all":
            games = [g for g in games if g.get("status") == self.filter_status_key]
        if self.filter_platform_value != "all":
            games = [g for g in games if g.get("platform") == self.filter_platform_value]
        if self.active_only_bool:
            games = [g for g in games if g.get("status") not in core.DONE_STATUSES]
        key = self.sort_key
        if key == "title_asc":
            games.sort(key=lambda g: str(g.get("title", "")).lower())
        elif key == "title_desc":
            games.sort(key=lambda g: str(g.get("title", "")).lower(), reverse=True)
        elif key == "date_desc":
            games.sort(key=lambda g: str(g.get("added", "")), reverse=True)
        elif key == "score_desc":
            games.sort(key=lambda g: core.as_float(g.get("score")), reverse=True)
        elif key == "hours_desc":
            games.sort(key=lambda g: core.as_float(g.get("hours")), reverse=True)
        elif key == "status":
            order = {name: index for index, name in enumerate(self.app.statuses())}
            games.sort(key=lambda g: order.get(str(g.get("status", "want")), len(order)))
        else:
            games.sort(key=lambda g: int(g.get("order", 0)))
        return games

    def refresh_cards(self) -> None:
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.cards = []
        visible = self._visible_games()
        for game in visible:
            card = GameCard(game, self.app, game["id"] == self.app.selected_id)
            card.clicked.connect(self.select_game)
            self.cards_layout.addWidget(card)
            self.cards.append(card)
        if not visible:
            empty = QLabel(self.app.tr("empty_list"))
            empty.setFont(self.app.font(11))
            empty.setWordWrap(True)
            empty.setFixedWidth(320)
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet(f"color: {self.app.pal()['muted']}; padding: 26px 18px;")
            self.cards_layout.addWidget(empty)
        self.library_label.setText(self.app.tr("library_eyebrow").format(len(self.app.games)))
        self._update_statusbar(len(visible))

    def _build_statusbar(self) -> QLabel:
        self.statusbar = QLabel()
        self.statusbar.setFont(self.app.tech_font(10))
        self.statusbar.setStyleSheet(f"color: {self.app.pal()['muted']}; padding: 6px 12px;")
        return self.statusbar

    def _update_statusbar(self, shown: int) -> None:
        counts = {s: 0 for s in self.app.statuses()}
        for game in self.app.games:
            counts[game.get("status", "want")] = counts.get(game.get("status", "want"), 0) + 1
        self.statusbar.setText(self.app.tr("statusbar").format(
            total=len(self.app.games), want=counts["want"], playing=counts["playing"],
            done=counts["done"], shown=shown))

    # ------------------------------------------------------------- редактор
    def show_editor(self) -> None:
        if not self.editor.isVisible():
            self.editor.show()
            total = max(760, self.width() - 92)
            self.splitter.setSizes([int(total * 0.62), int(total * 0.38)])

    def hide_editor(self) -> None:
        self.editor.hide()
        total = max(760, self.width() - 92)
        self.splitter.setSizes([total, 0])

    def select_game(self, game_id: str) -> None:
        game = next((g for g in self.app.games if str(g["id"]) == str(game_id)), None)
        if not game:
            return
        self.app.selected_id = str(game["id"])
        self.show_editor()
        self._updating = True
        self.editor.bind(game)
        self._updating = False
        for card in self.cards:
            card.selected = str(card.game["id"]) == self.app.selected_id
            card.update()
        for key, chip in self.chips.items():
            chip.set_active(key == str(game.get("status")))

    def focus_editor(self) -> None:
        if not self.app.selected_id:
            QMessageBox.information(self, "GameBacklog", self.app.tr("msg_select"))
            return
        self.show_editor()
        self.editor.title_edit.setFocus()
        self.editor.title_edit.selectAll()

    def save_game(self) -> None:
        game = next((g for g in self.app.games if str(g["id"]) == self.app.selected_id), None)
        if not game:
            QMessageBox.information(self, "GameBacklog", self.app.tr("msg_select"))
            return
        values = self.editor.collect()
        if not values["title"]:
            return
        old_appid = str(game.get("appid") or "")
        game.update(values)
        if str(values.get("appid") or "") != old_appid:
            game["steam_verified"] = False
            game["verified_genres"] = []
            game["verified_at"] = ""
        core.save_data(self.app.games, self.app.locale)
        self.refresh_all()
        self.editor.bind(game)
        self._start_icon_backfill([game])

    def mark_done(self) -> None:
        game = next((g for g in self.app.games if str(g["id"]) == self.app.selected_id), None)
        if not game:
            QMessageBox.information(self, "GameBacklog", self.app.tr("msg_select"))
            return
        game["status"] = "done"
        core.save_data(self.app.games, self.app.locale)
        self.refresh_all()
        self.editor.bind(game)

    def delete_game(self) -> None:
        game = next((g for g in self.app.games if str(g["id"]) == self.app.selected_id), None)
        if not game:
            QMessageBox.information(self, "GameBacklog", self.app.tr("msg_select"))
            return
        confirm = ConfirmDialog(
            self.app, self.app.tr("delete_title"),
            self.app.tr("delete_confirm").format(game.get("title", "")),
            self.app.tr("delete_action"), self)
        if confirm.exec() != QDialog.Accepted:
            return
        self.app.games = [g for g in self.app.games if str(g["id"]) != self.app.selected_id]
        self.app.selected_id = None
        core.save_data(self.app.games, self.app.locale)
        self.refresh_all()
        self.editor.clear()

    # ------------------------------------------------------------- статистика
    def _build_stats_view(self) -> QWidget:
        view = QWidget()
        layout = QVBoxLayout(view)
        layout.setContentsMargins(18, 14, 18, 14)
        title = QLabel(self.app.tr("stats_header"))
        title.setFont(self.app.font(16, True))
        layout.addWidget(title)
        self.stats_host = QScrollArea()
        self.stats_host.setWidgetResizable(True)
        self.stats_host.setFrameShape(QFrame.NoFrame)
        self.stats_inner = QWidget()
        self.stats_grid = QGridLayout(self.stats_inner)
        self.stats_grid.setAlignment(Qt.AlignTop)
        self.stats_host.setWidget(self.stats_inner)
        layout.addWidget(self.stats_host, 1)
        return view

    def build_stats(self) -> None:
        while self.stats_grid.count():
            item = self.stats_grid.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        games = self.app.games
        counts = {s: 0 for s in self.app.statuses()}
        verified = 0
        for game in games:
            status = game.get("status", "want")
            counts[status] = counts.get(status, 0) + 1
            if core.is_steam_verified(game):
                verified += 1
        unverified = len(games) - verified
        done = counts["done"] + counts["dropped"]
        pct = round(100 * done / len(games)) if games else 0
        pal = self.app.pal()
        cards = [
            ("card_total", str(len(games)), pal["muted"]),
            ("card_verified", str(verified), pal["status_done"]),
            ("card_done", str(done), pal["status_done"]),
            ("card_pct", f"{pct}%", pal["status_done"]),
            ("card_playing", str(counts["playing"]), pal["status_playing"]),
            ("card_postponed", str(counts["postponed"]), pal["status_postponed"]),
            ("card_dropped", str(counts["dropped"]), pal["status_dropped"]),
            ("card_unverified", str(unverified), pal["status_postponed"]),
        ]
        for index, (label, value, color) in enumerate(cards):
            self.stats_grid.addWidget(StatCard(self.app.tr(label), value, color, self.app),
                                      index // 4, index % 4)

        platforms: dict[str, int] = {}
        genres: dict[str, int] = {}
        for game in games:
            if game.get("platform"):
                platforms[str(game["platform"])] = platforms.get(str(game["platform"]), 0) + 1
            if core.is_steam_verified(game):
                for genre in core.steam_verified_genres(game):
                    genres[genre] = genres.get(genre, 0) + 1
        row = 2
        sections = ((self.app.tr("platforms"), platforms, ""),
                    (self.app.tr("genres_steam"), genres, self.app.tr("genres_hint")))
        for heading, data, hint in sections:
            label = QLabel(heading)
            label.setFont(self.app.font(10, True))
            label.setStyleSheet(f"color: {pal['muted']};")
            self.stats_grid.addWidget(label, row, 0, 1, 4)
            row += 1
            if hint:
                note = QLabel(hint)
                note.setFont(self.app.font(9))
                note.setStyleSheet(f"color: {pal['muted']};")
                self.stats_grid.addWidget(note, row, 0, 1, 4)
                row += 1
            if not data:
                empty = QLabel(self.app.tr("no_data"))
                empty.setStyleSheet(f"color: {pal['muted']};")
                self.stats_grid.addWidget(empty, row, 0, 1, 4)
                row += 1
                continue
            top = sorted(data.items(), key=lambda x: -x[1])[:8]
            bar_rows = max(1, (len(top) + 3) // 4)
            for index, (name, count) in enumerate(top):
                bar = StatCard(name, str(count), pal["accent"], self.app)
                self.stats_grid.addWidget(bar, row + index // 4, index % 4)
            row += bar_rows
        note = QLabel(self.app.tr("manual_note"))
        note.setFont(self.app.font(9))
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {pal['muted']};")
        self.stats_grid.addWidget(note, row, 0, 1, 4)

    def _set_active_rail(self, key: str) -> None:
        for name, button in self.rail_buttons.items():
            button.set_active(name == key)

    def show_list(self) -> None:
        self.active_tab = "list"
        self.stack.setCurrentWidget(self.list_view)
        self._set_active_rail("list")

    def show_stats(self) -> None:
        self.active_tab = "stats"
        self.stack.setCurrentWidget(self.stats_view)
        self._set_active_rail("stats")
        self.build_stats()

    def show_settings(self) -> None:
        self.active_tab = "settings"
        self.stack.setCurrentWidget(self.settings_view)
        self._set_active_rail("settings")

    def show_help(self) -> None:
        self.active_tab = "help"
        self.stack.setCurrentWidget(self.help_view)
        self._set_active_rail("help")

    def refresh_all(self) -> None:
        self._update_filter_values()
        self.refresh_cards()
        if self.active_tab == "stats":
            self.build_stats()

    # ------------------------------------------------------------- дії
    def steam_add(self) -> None:
        dlg = SteamDialog(self.app, self)
        dlg.exec()

    def pc_add(self) -> None:
        dlg = PcGamesDialog(self.app, self)
        dlg.exec()

    def import_games(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, self.app.tr("import_title"), "",
                                              "JSON / CSV (*.json *.csv)")
        if not path:
            return
        try:
            raw = core.read_export(path)
        except Exception as exc:
            QMessageBox.warning(self, "GameBacklog", self.app.tr("import_error").format(exc))
            return
        items = [core.normalize_game(item) for item in raw if isinstance(item, dict)]
        if not items:
            return
        replace = QMessageBox.question(self, self.app.tr("import_title"),
                                       self.app.tr("import_prompt").format(len(items)),
                                       QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes
        if replace:
            self.app.games = items
        else:
            titles = {str(g.get("title", "")).strip().lower() for g in self.app.games}
            order = max([g["order"] for g in self.app.games], default=-1) + 1
            for item in items:
                if str(item.get("title", "")).strip().lower() in titles:
                    continue
                item["order"] = order
                order += 1
                self.app.games.append(item)
                titles.add(str(item.get("title", "")).strip().lower())
        core.save_data(self.app.games, self.app.locale)
        self.refresh_all()
        self._start_icon_backfill()
        QMessageBox.information(self, "GameBacklog",
                                self.app.tr("import_done").format(len(self.app.games)))

    def export_games(self) -> None:
        if not self.app.games:
            QMessageBox.information(self, "GameBacklog", self.app.tr("empty_export"))
            return
        path, _ = QFileDialog.getSaveFileName(self, self.app.tr("export_title"),
                                              "games.json", "JSON (*.json);;CSV (*.csv)")
        if not path:
            return
        try:
            core.write_export(path, self.app.games)
        except Exception as exc:
            QMessageBox.warning(self, "GameBacklog", self.app.tr("export_error").format(exc))
            return
        QMessageBox.information(self, "GameBacklog", self.app.tr("export_done").format(path))

    def open_settings(self) -> None:
        self.show_settings()

    def open_help(self) -> None:
        self.show_help()


class HudSection(QFrame):
    """М'який блок-секція редактора замість табличних рядків."""

    def __init__(self, app: App, title: str) -> None:
        super().__init__()
        self.app, self.title = app, title
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 14)
        outer.setSpacing(9)
        label = QLabel(title.upper())
        label.setFont(app.tech_font(10, True))
        label.setStyleSheet(f"color: {app.pal()['accent2']}; background: transparent;")
        outer.addWidget(label)
        self.body = QVBoxLayout()
        self.body.setSpacing(8)
        outer.addLayout(self.body)

    def addWidget(self, widget: QWidget, stretch: int = 0) -> None:
        self.body.addWidget(widget, stretch)

    def addLayout(self, layout: QLayout) -> None:
        self.body.addLayout(layout)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        p = self.app.pal()
        paint_hud_panel(painter, QRectF(1, 1, self.width() - 2, self.height() - 2),
                        core.mix(p["panel"], p["card"], 0.45),
                        core.mix(p["card_border"], p["accent"], 0.18),
                        None, 10, brackets=True)


class HudField(QFrame):
    """Поле без жорсткої рамки: підсвічується м'якою панеллю тільки у фокусі."""

    def __init__(self, widget: QWidget, app: App, *, min_height: int = 38) -> None:
        super().__init__()
        self.app, self.inner = app, widget
        self.setMinimumHeight(min_height)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 2, 12, 2)
        lay.addWidget(widget)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        p = self.app.pal()
        focus = QtWidgets.QApplication.focusWidget()
        active = focus is not None and self.isAncestorOf(focus)
        border = core.mix(p["card_border"], p["panel"], 0.5)
        if active:
            border = core.mix(border, p["accent"], 0.6)
        paint_hud_panel(painter, QRectF(1, 1, self.width() - 2, self.height() - 2),
                        core.mix(p["field"], p["panel"], 0.18), border,
                        p["accent"] if active else None, 9, brackets=False)


class EditorPanel(QScrollArea):
    """Права панель редагування гри: статуси, запуск, оригінальна іконка."""

    def __init__(self, app: App, window: MainWindow) -> None:
        super().__init__()
        self.app, self.window = app, window
        self._active_status = "want"
        self._icon_q: queue.Queue = queue.Queue()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        host = QWidget()
        self.setWidget(host)
        layout = QVBoxLayout(host)
        layout.setContentsMargins(12, 10, 8, 10)
        layout.setSpacing(10)

        header_row = QHBoxLayout()
        header = QLabel(app.tr("editor_header"))
        header.setFont(app.font(14, True))
        close_btn = TitleButton("close", app)
        close_btn.clicked.connect(self.window.hide_editor)
        header_row.addWidget(header, 1)
        header_row.addWidget(close_btn, 0, Qt.AlignRight)
        layout.addLayout(header_row)

        self.cover = CoverTile(app)
        layout.addWidget(self.cover)

        # Поля редагування існують тільки коли обрано карточку гри.
        self.body = QWidget()
        body_layout = QVBoxLayout(self.body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(10)
        layout.addWidget(self.body, 1)

        main = HudSection(app, app.tr("section_main"))
        body_layout.addWidget(main)
        self.title_edit = self._field(main, app.tr("f_title"))
        self.platform_combo = self._field(main, app.tr("f_platform"), core.PLATFORM_PRESETS)
        self.genre_combo = self._field(main, app.tr("f_genre"), core.GENRE_PRESETS)
        self.verify_label = QLabel("")
        self.verify_label.setFont(app.font(9))
        self.verify_label.setStyleSheet(
            f"color: {app.pal()['muted']}; background: transparent;")
        main.addWidget(self.verify_label)

        status = HudSection(app, app.tr("section_status"))
        body_layout.addWidget(status)
        self.chips_layout = QVBoxLayout()
        self.chips_layout.setSpacing(5)
        status.addLayout(self.chips_layout)
        add_status = QPushButton(app.tr("add_status"))
        add_status.clicked.connect(self._add_status)
        status.addWidget(add_status)

        launch = HudSection(app, app.tr("section_launch"))
        body_layout.addWidget(launch)
        self.link_edit = self._field(launch, app.tr("f_link"))
        browse = QPushButton(app.tr("browse"))
        browse.setObjectName("inline")
        browse.clicked.connect(self._browse_exe)
        self.exe_edit = self._field(launch, app.tr("f_exe"), trailing=browse)
        launch_actions = QVBoxLayout()
        launch_actions.setSpacing(7)
        launch_btn = QPushButton(app.tr("launch"))
        launch_btn.setObjectName("launch")
        launch_btn.clicked.connect(self._launch)
        self.icon_btn = QPushButton(app.tr("icon_update"))
        self.icon_btn.clicked.connect(self._refresh_icon)
        launch_actions.addWidget(launch_btn)
        launch_actions.addWidget(self.icon_btn)
        launch.addLayout(launch_actions)

        meta = HudSection(app, app.tr("section_meta"))
        body_layout.addWidget(meta)
        self.score_edit = self._field(meta, app.tr("f_score"))
        self.hours_edit = self._field(meta, app.tr("f_hours"))
        self.price_edit = self._field(meta, app.tr("f_price"))

        dates = HudSection(app, app.tr("section_dates"))
        body_layout.addWidget(dates)
        self.added_edit = self._field(dates, app.tr("f_added"))
        self.completed_edit = self._field(dates, app.tr("f_completed"))

        notes_section = HudSection(app, app.tr("section_notes"))
        body_layout.addWidget(notes_section)
        self.tags_edit = self._field(notes_section, app.tr("f_tags"))
        self.notes_edit = self._field(notes_section, app.tr("f_notes"), multiline=True)

        save = QPushButton(app.tr("save_changes"))
        save.setObjectName("accent")
        save.clicked.connect(self.window.save_game)
        done = QPushButton(app.tr("mark_done"))
        done.clicked.connect(self.window.mark_done)
        body_layout.addWidget(save)
        body_layout.addWidget(done)

        self.rebuild_statuses()
        self._apply_buttons()
        self.set_active(False)

    def _field(self, section: HudSection, placeholder: str,
               presets: list[str] | None = None, *, trailing: QWidget | None = None,
               multiline: bool = False) -> QLineEdit | QTextEdit:
        if multiline:
            widget: QLineEdit | QTextEdit = QTextEdit()
            widget.setPlaceholderText(placeholder)
            widget.setFixedHeight(74)
        else:
            widget = QLineEdit()
            widget.setPlaceholderText(placeholder)
            if presets:
                widget.setCompleter(QCompleter(presets, self))
        if trailing is None:
            inner: QWidget = widget
        else:
            inner = QWidget()
            row = QHBoxLayout(inner)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(6)
            row.addWidget(widget, 1)
            row.addWidget(trailing, 0)
        section.addWidget(HudField(inner, self.app, min_height=96 if multiline else 40))
        return widget

    def _apply_buttons(self) -> None:
        p = self.app.pal()
        self.setStyleSheet(f"""
            QLineEdit, QTextEdit {{ background: transparent; color: {p['fg']};
                border: none; outline: none; padding: 6px 0;
                selection-background-color: {p['sel']}; }}
            QTextEdit {{ padding: 6px 0; }}
            QListView {{ background: {p['panel']}; color: {p['fg']};
                border: 1px solid {p['border']}; selection-background-color: {p['sel']}; }}
            QPushButton {{ background: {core.mix(p['panel'], p['card'], 0.25)};
                color: {p['fg']}; border: none; border-radius: 9px;
                padding: 10px 12px; outline: none; }}
            QPushButton:hover {{ background: {core.mix(p['panel'], p['accent'], 0.14)}; }}
            QPushButton#accent {{ background: {p['accent']};
                color: {core.text_on(p['accent'])}; }}
            QPushButton#launch {{ background: {p['accent2']};
                color: {core.text_on(p['accent2'])}; }}
            QPushButton#inline {{ background: transparent; color: {p['accent']};
                border-radius: 6px; padding: 4px 6px; }}
            QPushButton#inline:hover {{ background: {p['sel']}; }}
        """)

    def _line(self, placeholder: str, layout: QVBoxLayout) -> QLineEdit:
        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        layout.addWidget(self._labeled(placeholder, edit))
        return edit

    def _labeled(self, label: str, widget: QWidget) -> QWidget:
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        lbl = QLabel(label)
        lbl.setFont(self.app.font(9))
        lbl.setStyleSheet(f"color: {self.app.pal()['muted']};")
        lay.addWidget(lbl)
        lay.addWidget(widget)
        return host

    # ------------------------------------------------------------- статуси
    def rebuild_statuses(self) -> None:
        current = self._active_status if self._active_status in self.app.statuses() else "want"
        while self.chips_layout.count():
            item = self.chips_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.window.chips.clear()
        for key in self.app.statuses():
            chip = StatusChip(key, self.app)
            chip.set_active(key == current)
            chip.chosen.connect(self._choose_status)
            chip.menuRequested.connect(self._status_menu)
            self.window.chips[key] = chip
            self.chips_layout.addWidget(chip)
        self.chips_layout.addStretch(1)
        self._active_status = current

    def _set_active_status(self, key: str) -> None:
        if key not in self.app.statuses():
            key = "want"
        self._active_status = key
        for name, chip in self.window.chips.items():
            chip.set_active(name == key)

    def _label_taken(self, label: str, ignore_key: str | None = None) -> bool:
        wanted = label.strip().casefold()
        for key in self.app.statuses():
            if key == ignore_key:
                continue
            if self.app.status_label(key).strip().casefold() == wanted:
                return True
        return False

    def _current_game(self) -> dict[str, Any] | None:
        if self.body.isHidden():
            return None
        return next((g for g in self.app.games
                     if str(g["id"]) == str(self.app.selected_id)), None)

    def _choose_status(self, key: str) -> None:
        self._set_active_status(key)
        game = self._current_game()
        if not game:
            return
        game["status"] = key
        core.save_data(self.app.games, self.app.locale)
        self.cover.bind_data(game)
        self.window.refresh_all()

    def _add_status(self) -> None:
        label, ok = QInputDialog.getText(self, "GameBacklog", self.app.tr("status_name"))
        if not ok or not label.strip():
            return
        if self._label_taken(label):
            QMessageBox.information(self, "GameBacklog", self.app.tr("status_exists"))
            return
        key = self.app.add_status(label)
        game = self._current_game()
        if game:
            game["status"] = key
            core.save_data(self.app.games, self.app.locale)
            self.cover.bind_data(game)
            self.window.refresh_all()
        self._set_active_status(key)

    def _status_menu(self, key: str, pos: QPoint) -> None:
        if key not in core.STATUSES:
            return
        menu = QMenu(self)
        menu.addAction(self.app.tr("status_rename"), lambda: self._rename_status(key))
        menu.addAction(self.app.tr("status_color"), lambda: self._color_status(key))
        menu.addSeparator()
        menu.addAction(self.app.tr("status_delete"), lambda: self._delete_status(key))
        menu.exec(pos)

    def _rename_status(self, key: str) -> None:
        current = self.app.status_label(key)
        label, ok = QInputDialog.getText(self, "GameBacklog", self.app.tr("status_rename"),
                                         text=current)
        if not ok or not label.strip():
            return
        if self._label_taken(label, key):
            QMessageBox.information(self, "GameBacklog", self.app.tr("status_exists"))
            return
        self.app.rename_status(key)
        game = self._current_game()
        if game:
            self.cover.bind_data(game)

    def _color_status(self, key: str) -> None:
        color = QColorDialog.getColor(QColor(self.app.status_color(key)), self,
                                      self.app.tr("status_color"))
        if not color.isValid():
            return
        self.app.set_status_color(key, color.name())
        game = self._current_game()
        if game:
            self.cover.bind_data(game)

    def _delete_status(self, key: str) -> None:
        label = self.app.status_label(key)
        reply = QMessageBox.question(
            self, "GameBacklog",
            self.app.tr("status_delete_confirm").format(label),
            QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        self.app.delete_status(key)
        game = self._current_game()
        if game:
            self._set_active_status(str(game.get("status") or "want"))
            self.cover.bind_data(game)
        else:
            self.clear()

    # ------------------------------------------------------------- запуск/іконка
    def _commit_fields(self) -> dict[str, Any] | None:
        game = self._current_game()
        if not game:
            return None
        game.update(self.collect())
        core.save_data(self.app.games, self.app.locale)
        return game

    def _browse_exe(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, self.app.tr("f_exe"), "",
                                              "Executable (*.exe);;All files (*.*)")
        if not path:
            return
        self.exe_edit.setText(path)
        self._commit_fields()

    def _launch(self) -> None:
        game = self._commit_fields()
        if not game:
            QMessageBox.information(self, "GameBacklog", self.app.tr("msg_select"))
            return
        ok, desc = core.launch_game(game)
        if ok:
            QMessageBox.information(self, "GameBacklog",
                                    self.app.tr("launch_ok").format(desc))
        else:
            QMessageBox.warning(self, "GameBacklog",
                                self.app.tr("launch_fail").format(desc))

    def _refresh_icon(self) -> None:
        game = self._current_game()
        if not game:
            QMessageBox.information(self, "GameBacklog", self.app.tr("msg_select"))
            return
        appid = core.appid_from_link(self.link_edit.text().strip()) \
            or str(game.get("appid") or "")
        if not appid:
            QMessageBox.warning(self, "GameBacklog",
                                self.app.tr("icon_fail").format("Steam AppID not found"))
            return
        game.update(self.collect())
        game["appid"] = appid
        core.save_data(self.app.games, self.app.locale)
        self.icon_btn.setEnabled(False)
        self._icon_q = queue.Queue()
        q = self._icon_q
        threading.Thread(target=self._worker_icon, args=(appid, q), daemon=True).start()
        self._poll_icon()

    def _worker_icon(self, appid: str, q: queue.Queue) -> None:
        q.put(core.cache_steam_icon(appid))

    def _poll_icon(self) -> None:
        try:
            path = self._icon_q.get_nowait()
        except queue.Empty:
            QTimer.singleShot(80, self._poll_icon)
            return
        self.icon_btn.setEnabled(True)
        if not path:
            QMessageBox.warning(self, "GameBacklog",
                                self.app.tr("icon_fail").format("header_image"))
            return
        game = self._current_game()
        if not game:
            return
        game["icon"] = path
        core.save_data(self.app.games, self.app.locale)
        self.cover.bind_data(game)
        self.window.refresh_all()
        QMessageBox.information(self, "GameBacklog", self.app.tr("icon_done"))

    # ------------------------------------------------------------- дані
    def bind(self, game: dict[str, Any]) -> None:
        self.title_edit.setText(str(game.get("title") or ""))
        self.platform_combo.setText(str(game.get("platform") or "PC"))
        self.genre_combo.setText(str(game.get("genre") or ""))
        self.score_edit.setText(str(game.get("score") or ""))
        self.hours_edit.setText(str(game.get("hours") or ""))
        self.price_edit.setText(str(game.get("price") or ""))
        self.link_edit.setText(str(game.get("link") or ""))
        self.exe_edit.setText(str(game.get("exe") or ""))
        self.tags_edit.setText(str(game.get("tags") or ""))
        self.added_edit.setText(str(game.get("added") or ""))
        self.completed_edit.setText(str(game.get("completed") or ""))
        self.notes_edit.setPlainText(str(game.get("notes") or ""))
        self.cover.bind_data(game)
        self.update_verify_label(game)
        status = str(game.get("status") or "want")
        self._set_active_status(status)
        self.set_active(True)

    def set_active(self, active: bool) -> None:
        """Без обраної картки поля редагування взагалі не показуємо."""
        self.body.setVisible(active)
        if not active:
            self.cover.bind_data({})

    def update_verify_label(self, game: dict[str, Any]) -> None:
        appid = str(game.get("appid") or core.appid_from_link(game.get("link", "")))
        if core.is_steam_verified(game):
            text = self.app.tr("verified_yes")
            color = self.app.pal()["status_done"]
        elif appid.isdigit():
            text = self.app.tr("verified_wait")
            color = self.app.pal()["muted"]
        else:
            text = self.app.tr("verified_no")
            color = self.app.pal()["muted"]
        self.verify_label.setText(text)
        self.verify_label.setStyleSheet(f"color: {color}; background: transparent;")

    def clear(self) -> None:
        self.bind(core.make_game())
        self.set_active(False)

    def collect(self) -> dict[str, Any]:
        link = self.link_edit.text().strip()
        return {"title": self.title_edit.text().strip(),
                "platform": self.platform_combo.text().strip() or "PC",
                "genre": self.genre_combo.text().strip(),
                "status": self._active_status if self._active_status in self.app.statuses()
                          else "want",
                "score": self.score_edit.text().strip(),
                "hours": self.hours_edit.text().strip(),
                "price": self.price_edit.text().strip(),
                "link": link,
                "appid": core.appid_from_link(link),
                "exe": self.exe_edit.text().strip(),
                "tags": self.tags_edit.text().strip(),
                "added": self.added_edit.text().strip(),
                "completed": self.completed_edit.text().strip(),
                "notes": self.notes_edit.toPlainText()}


# --------------------------------------------------------------------------- пікери
class PickerList(QScrollArea):
    def __init__(self, app: App) -> None:
        super().__init__()
        self.app = app
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.host = QWidget()
        self.layout_ = QVBoxLayout(self.host)
        self.layout_.setContentsMargins(4, 4, 4, 4)
        self.layout_.setSpacing(4)
        self.layout_.addStretch(1)
        self.setWidget(self.host)
        self.cards: list[PickerCard] = []
        self.selected: set[int] = set()

    def set_items(self, items: list[dict[str, str]], empty_text: str = "") -> None:
        while self.layout_.count() > 1:
            item = self.layout_.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.cards, self.selected = [], set()
        for index, item in enumerate(items):
            card = PickerCard(item, index, self.app)
            card.toggled.connect(self._toggle)
            self.layout_.insertWidget(self.layout_.count() - 1, card)
            self.cards.append(card)
        if not items and empty_text:
            label = QLabel(empty_text)
            label.setWordWrap(True)
            label.setStyleSheet(f"color: {self.app.pal()['muted']}; padding: 24px;")
            self.layout_.insertWidget(self.layout_.count() - 1, label)
        self.on_change(len(self.selected))

    def _toggle(self, index: int, selected: bool) -> None:
        if selected:
            self.selected.add(index)
        else:
            self.selected.discard(index)
        self.on_change(len(self.selected))

    def on_change(self, count: int) -> None:
        pass

    def selected_items(self) -> list[dict[str, str]]:
        return [self.cards[i].item for i in sorted(self.selected) if i < len(self.cards)]


class PickerDialog(QDialog):
    def __init__(self, app: App, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.app = app
        self.setWindowTitle("GameBacklog")
        self.resize(640, 560)
        self.setStyleSheet(f"background: {app.pal()['bg']}; color: {app.pal()['fg']};")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        header = QLabel(self.title_text())
        header.setFont(app.font(15, True))
        layout.addWidget(header)
        hint = QLabel(app.tr(self.hint_key()))
        hint.setFont(app.font(10))
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {app.pal()['muted']};")
        layout.addWidget(hint)
        layout.addLayout(self._build_top())
        self.picker = PickerList(app)
        self.picker.on_change = self._update_selected
        layout.addWidget(self.picker, 1)
        bottom = QHBoxLayout()
        self.selected_label = QLabel(app.tr("picker_selected").format(0))
        self.selected_label.setFont(app.font(10))
        bottom.addWidget(self.selected_label)
        bottom.addStretch(1)
        add = QPushButton(app.tr("picker_add"))
        add.setObjectName("accent")
        add.clicked.connect(self.add_selected)
        bottom.addWidget(add)
        close = QPushButton(app.tr("steam_close"))
        close.clicked.connect(self.reject)
        bottom.addWidget(close)
        layout.addLayout(bottom)
        self.status_label = QLabel("")
        self.status_label.setFont(app.font(9))
        self.status_label.setStyleSheet(f"color: {app.pal()['muted']};")
        layout.addWidget(self.status_label)
        self._apply_buttons()

    def title_text(self) -> str:
        return ""

    def hint_key(self) -> str:
        return "hint"

    def _build_top(self) -> QHBoxLayout:
        return QHBoxLayout()

    def _apply_buttons(self) -> None:
        p = self.app.pal()
        self.setStyleSheet(f"""
            QDialog {{ background: {p['bg']}; color: {p['fg']}; }}
            QPushButton {{ background: {p['panel']}; color: {p['fg']};
                border: 1px solid {p['border']}; border-radius: 4px; padding: 7px 12px; }}
            QPushButton#accent {{ background: {p['accent']}; color: {core.text_on(p['accent'])};
                border-color: {p['accent']}; }}
            QLabel {{ background: transparent; color: {p['fg']}; }}
        """)

    def _update_selected(self, count: int) -> None:
        self.selected_label.setText(self.app.tr("picker_selected").format(count))

    def add_selected(self) -> None:
        pass


class SteamDialog(PickerDialog):
    def __init__(self, app: App, parent: QWidget | None = None) -> None:
        self.q: queue.Queue = queue.Queue()
        super().__init__(app, parent)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._poll)
        self.timer.start(120)
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self._do_search)

    def title_text(self) -> str:
        return self.app.tr("steam_title")

    def hint_key(self) -> str:
        return "steam_hint"

    def _build_top(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.addWidget(QLabel(self.app.tr("steam_search")))
        self.search_edit = QLineEdit()
        self.search_edit.textChanged.connect(lambda *_: self.search_timer.start(350))
        layout.addWidget(self.search_edit, 1)
        return layout

    def _do_search(self) -> None:
        term = self.search_edit.text().strip()
        if len(term) < 2:
            self.picker.set_items([])
            self.status_label.setText("")
            return
        self.status_label.setText(self.app.tr("steam_wait"))
        threading.Thread(target=self._worker_search, args=(term,), daemon=True).start()

    def _worker_search(self, term: str) -> None:
        try:
            found = core.steam_search(term, self.app.tr("steam_free"))
        except Exception as exc:
            self.q.put(("error", str(exc)))
            return
        items = []
        if found:
            for name, appid, price in found:
                items.append({"name": name, "appid": str(appid), "price": price,
                              "icon": core.cache_steam_icon(appid)})
            self.q.put(("results", items))
            return
        try:
            top = core.steam_top_charts(10, self.app.tr("steam_free"))
        except Exception as exc:
            self.q.put(("error", str(exc)))
            return
        for item in top:
            item["icon"] = core.cache_steam_icon(item["appid"], item.get("icon_url", ""))
        self.q.put(("top", top))

    def add_selected(self) -> None:
        selected = self.picker.selected_items()
        if not selected:
            QMessageBox.information(self, "GameBacklog", self.app.tr("steam_select"))
            return
        self.status_label.setText(self.app.tr("steam_details"))
        apps = [(str(item["name"]), int(item["appid"])) for item in selected]
        threading.Thread(target=self._worker_add, args=(apps,), daemon=True).start()

    def _worker_add(self, apps) -> None:
        enriched = []
        for name, appid in apps:
            genres, icon = core.steam_game_info(appid)
            enriched.append((name, appid, genres, icon))
        self.q.put(("added", enriched))

    def _finish_add(self, apps) -> None:
        links = {str(g.get("link", "")) for g in self.app.games}
        titles = {str(g.get("title", "")).strip().lower() for g in self.app.games}
        order = max([g["order"] for g in self.app.games], default=-1) + 1
        added = skipped = 0
        for name, appid, genres, icon in apps:
            link = f"https://store.steampowered.com/app/{appid}/"
            if link in links or name.strip().lower() in titles:
                skipped += 1
                continue
            game = core.make_game(name)
            game.update(platform="Steam", link=link, genre=", ".join(genres[:2]),
                        order=order, appid=str(appid), icon=icon)
            if genres or icon:
                core.mark_steam_verified(game, genres, appid)
            order += 1
            self.app.games.append(game)
            links.add(link)
            titles.add(name.strip().lower())
            added += 1
        core.save_data(self.app.games, self.app.locale)
        parent = self.parent()
        if isinstance(parent, MainWindow):
            parent.refresh_all()
            parent._start_icon_backfill()
        self.accept()

    def _poll(self) -> None:
        while True:
            try:
                kind, payload = self.q.get_nowait()
            except queue.Empty:
                break
            if kind in ("results", "top"):
                cards = [{"name": item["name"], "badge": "↑" if kind == "top" else "S",
                          "meta": f"Steam  ·  {item['price']}  ·  #{item['appid']}",
                          "appid": str(item["appid"]),
                          "icon": str(item.get("icon") or "")} for item in payload]
                self.picker.set_items(cards, self.app.tr("steam_nothing"))
                if kind == "top":
                    self.status_label.setText(
                        self.app.tr("steam_top") if payload
                        else self.app.tr("steam_nothing"))
                else:
                    self.status_label.setText(
                        self.app.tr("steam_ready").format(len(payload)) if payload
                        else self.app.tr("steam_nothing"))
            elif kind == "error":
                self.status_label.setText(self.app.tr("steam_error").format(str(payload)[:160]))
            elif kind == "added":
                self._finish_add(payload)


class PcGamesDialog(PickerDialog):
    def __init__(self, app: App, parent: QWidget | None = None) -> None:
        super().__init__(app, parent)
        self.items: list[dict[str, str]] = []
        QTimer.singleShot(0, self.scan)

    def title_text(self) -> str:
        return self.app.tr("pc_title")

    def hint_key(self) -> str:
        return "pc_hint"

    def _build_top(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        scan = QPushButton(self.app.tr("pc_scan"))
        scan.clicked.connect(self.scan)
        browse = QPushButton(self.app.tr("pc_browse"))
        browse.clicked.connect(self.browse_folder)
        layout.addWidget(scan)
        layout.addWidget(browse)
        layout.addStretch(1)
        return layout

    def scan(self) -> None:
        self.status_label.setText(self.app.tr("pc_scanning"))
        self._set_items(core.scan_installed())

    def browse_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, self.app.tr("pc_browse"))
        if not folder:
            return
        items = []
        for entry in os.listdir(folder):
            path = os.path.join(folder, entry)
            if os.path.isdir(path) and not entry.startswith("."):
                items.append({"name": entry, "appid": "", "source": "Папка", "path": path})
        self._set_items(items)

    def _set_items(self, items: list[dict[str, str]]) -> None:
        self.items = items
        cards = []
        for item in items:
            icon = ""
            appid = str(item.get("appid") or "").strip()
            if appid.isdigit():
                cached = os.path.join(core.ICONS_DIR, f"{appid}.jpg")
                if os.path.isfile(cached) and os.path.getsize(cached) > 0:
                    icon = cached
            cards.append({"name": item["name"],
                          "badge": str(item.get("source") or "PC")[:2],
                          "meta": f"{item.get('source', 'PC')}  ·  {item.get('path', '')}",
                          "icon": icon, **item})
        self.picker.set_items(cards, self.app.tr("pc_empty"))
        self.status_label.setText(self.app.tr("pc_found").format(len(items))
                                  if items else self.app.tr("pc_empty"))

    def add_selected(self) -> None:
        selected = self.picker.selected_items()
        if not selected:
            QMessageBox.information(self, "GameBacklog", self.app.tr("pc_select"))
            return
        titles = {str(g.get("title", "")).strip().lower() for g in self.app.games}
        links = {str(g.get("link", "")) for g in self.app.games}
        order = max([g["order"] for g in self.app.games], default=-1) + 1
        added = skipped = 0
        for item in selected:
            name = str(item["name"]).strip()
            if name.lower() in titles:
                skipped += 1
                continue
            game = core.make_game(name)
            source = str(item.get("source") or "PC")
            game["platform"] = source if source in ("Steam", "Epic", "GOG", "Xbox") else "PC"
            if item.get("appid"):
                game["appid"] = str(item["appid"])
                game["link"] = f"https://store.steampowered.com/app/{item['appid']}/"
            if item.get("path"):
                game["notes"] = f"{self.app.tr('pc_path')}: {item['path']}"
                game["exe"] = core.find_game_exe(str(item["path"]))
            if game["link"] and game["link"] in links:
                skipped += 1
                continue
            game["order"] = order
            order += 1
            self.app.games.append(game)
            titles.add(name.lower())
            links.add(game["link"])
            added += 1
        core.save_data(self.app.games, self.app.locale)
        parent = self.parent()
        if isinstance(parent, MainWindow):
            parent.refresh_all()
            parent._start_icon_backfill()
        self.accept()


# --------------------------------------------------------------------------- HUD-підтвердження
class HudDialogFrame(QFrame):
    def __init__(self, app: App) -> None:
        super().__init__()
        self.app = app
        self.setAttribute(Qt.WA_StyledBackground, True)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        pal = self.app.pal()
        paint_hud_panel(painter, QRectF(1, 1, self.width() - 2, self.height() - 2),
                        pal["panel"], core.mix(pal["card_border"], pal["accent"], 0.45),
                        pal["accent"], 9, brackets=True)


def center_hud_dialog(dialog: QWidget, app: App) -> None:
    """Центрує безрамковий HUD-діалог відносно вікна або екрана."""
    parent = dialog.parentWidget() or app.window
    if parent is not None and parent.isVisible():
        center = parent.mapToGlobal(QPoint(parent.width() // 2, parent.height() // 2))
    else:
        screen = QApplication.primaryScreen()
        center = screen.availableGeometry().center() if screen else QPoint(400, 300)
    dialog.move(center - QPoint(dialog.width() // 2, dialog.height() // 2))


class ConfirmDialog(QDialog):
    def __init__(self, app: App, title: str, message: str,
                 accept_label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.app = app
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setModal(True)
        self.setFixedSize(420, 200)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        self.frame = HudDialogFrame(app)
        outer.addWidget(self.frame)

        pal = app.pal()
        danger = pal.get("status_dropped", pal["accent"])
        layout = QVBoxLayout(self.frame)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(8)

        title_label = QLabel(title)
        title_label.setFont(app.tech_font(15, True))
        title_label.setStyleSheet(f"color: {pal['accent']}; background: transparent;")
        layout.addWidget(title_label)

        message_label = QLabel(message)
        message_label.setFont(app.font(11))
        message_label.setWordWrap(True)
        message_label.setStyleSheet(f"color: {pal['fg']}; background: transparent;")
        layout.addWidget(message_label)

        warn = QLabel(app.tr("delete_warn"))
        warn.setFont(app.font(10))
        warn.setStyleSheet(f"color: {pal['muted']}; background: transparent;")
        layout.addWidget(warn)
        layout.addStretch(1)

        row = QHBoxLayout()
        row.setSpacing(8)
        cancel = QPushButton(app.tr("cancel"))
        cancel.setStyleSheet(
            f"QPushButton {{ background: {pal['field']}; color: {pal['fg']}; "
            f"border: 1px solid {pal['border']}; border-radius: 6px; padding: 8px 16px; }}")
        cancel.clicked.connect(self.reject)
        accept = QPushButton(accept_label)
        accept.setStyleSheet(
            f"QPushButton {{ background: {danger}; color: {core.text_on(danger)}; "
            f"border: 1px solid {danger}; border-radius: 6px; padding: 8px 16px; "
            "font-weight: 600; }")
        accept.clicked.connect(self.accept)
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(accept)
        layout.addLayout(row)

        center_hud_dialog(self, app)


class HelpDialog(QDialog):
    def __init__(self, app: App, parent: QWidget | None = None, *,
                 embedded: bool = False, on_close=None) -> None:
        super().__init__(parent)
        self.app = app
        self.embedded = embedded
        self.on_close = on_close or (lambda: None)
        self.setWindowTitle(clean_label(app.tr("help")))
        if embedded:
            self.setWindowFlags(Qt.Widget)
            margins = (18, 14, 18, 14)
        else:
            self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
            self.setAttribute(Qt.WA_TranslucentBackground, True)
            self.setModal(True)
            self.resize(560, 460)
            margins = (12, 12, 12, 12)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(*margins)
        self.frame = HudDialogFrame(app)
        outer.addWidget(self.frame)
        layout = QVBoxLayout(self.frame)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        pal = app.pal()
        head = QHBoxLayout()
        title = QLabel(clean_label(app.tr("help")))
        title.setFont(app.tech_font(15, True))
        title.setStyleSheet(f"color: {pal['accent']}; background: transparent;")
        close_icon = TitleButton("close", app)
        close_icon.clicked.connect(self.reject)
        head.addWidget(title, 1)
        head.addWidget(close_icon, 0, Qt.AlignRight)
        layout.addLayout(head)

        text = QTextEdit()
        text.setReadOnly(True)
        text.setFont(app.font(11))
        text.setText(app.tr("help_text"))
        text.setStyleSheet(
            f"QTextEdit {{ background: {pal['field']}; color: {pal['fg']}; "
            f"border: 1px solid {pal['border']}; border-radius: 6px; "
            f"padding: 10px; selection-background-color: {pal['sel']}; }}")
        layout.addWidget(text, 1)

        close = QPushButton(app.tr("steam_close"))
        close.setObjectName("accent")
        close.setStyleSheet(
            f"QPushButton#accent {{ background: {pal['accent']}; "
            f"color: {core.text_on(pal['accent'])}; border: none; "
            "border-radius: 6px; padding: 8px 18px; font-weight: 600; }")
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close)
        layout.addLayout(row)
        if not embedded:
            center_hud_dialog(self, app)

    def done(self, result: int) -> None:
        if self.embedded:
            self.on_close()
            return
        super().done(result)


# --------------------------------------------------------------------------- налаштування
class SettingsDialog(QDialog):
    def __init__(self, app: App, parent: QWidget | None = None, *,
                 embedded: bool = False, on_close=None) -> None:
        super().__init__(parent)
        self.app = app
        self.embedded = embedded
        self.on_close = on_close or (lambda: None)
        self.setWindowTitle(app.tr("set_title"))
        if embedded:
            self.setWindowFlags(Qt.Widget)
            margins = (18, 14, 18, 14)
        else:
            self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
            self.setAttribute(Qt.WA_TranslucentBackground, True)
            self.setModal(True)
            self.resize(620, 560)
            margins = (12, 12, 12, 12)
        self.data = {
            "colors": dict(app.settings.get("colors", {})),
            "fonts": dict(app.settings.get("fonts", {})),
            "dark_mode": app.dark_mode,
            "theme": app.theme_key(),
            "language": app.locale,
            "dock_visible": bool(app.settings.get("dock_visible", True)),
            "dock_edge": app.settings.get("dock_edge", "right"),
            "dock_pos": int(app.settings.get("dock_pos", 33)),
            "dock_mirror": bool(app.settings.get("dock_mirror", True)),
            "dock_text_mirror": bool(app.settings.get("dock_text_mirror", False)),
            "autostart": bool(app.settings.get("autostart", False)),
            "toolbar_order": list(app.toolbar_order()[0]),
            "toolbar_hidden": list(app.toolbar_order()[1]),
        }
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(260)
        self._timer.timeout.connect(self._apply)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(*margins)
        self.frame = HudDialogFrame(app)
        outer.addWidget(self.frame)
        layout = QVBoxLayout(self.frame)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        pal = app.pal()
        head = QHBoxLayout()
        title = QLabel(app.tr("set_title"))
        title.setFont(app.tech_font(15, True))
        title.setStyleSheet(f"color: {pal['accent']}; background: transparent;")
        close = TitleButton("close", app)
        close.clicked.connect(self.reject)
        head.addWidget(title, 1)
        head.addWidget(close, 0, Qt.AlignRight)
        layout.addLayout(head)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self.tabs.addTab(self._theme_tab(), app.tr("set_theme_tab"))
        self.tabs.addTab(self._colors_tab(), app.tr("set_colors"))
        self.tabs.addTab(self._fonts_tab(), app.tr("set_fonts"))
        self.tabs.addTab(self._buttons_tab(), app.tr("set_buttons"))
        self.tabs.addTab(self._general_tab(), app.tr("set_general"))
        hint = QLabel(app.tr("set_live_hint"))
        hint.setFont(app.font(9))
        hint.setStyleSheet(f"color: {pal['muted']};")
        layout.addWidget(hint)
        buttons = QHBoxLayout()
        ok = QPushButton(app.tr("ok"))
        ok.clicked.connect(self._ok)
        buttons.addStretch(1)
        buttons.addWidget(ok)
        layout.addLayout(buttons)
        self._apply_sheet()
        if not embedded:
            center_hud_dialog(self, app)

    def _apply_sheet(self) -> None:
        p = self.app.pal()
        self.setStyleSheet(f"""
            QDialog {{ background: transparent; }}
            QWidget {{ background: transparent; color: {p['fg']}; }}
            QLabel {{ background: transparent; color: {p['fg']}; }}
            QPushButton {{ background: {p['panel']}; color: {p['fg']};
                border: 1px solid {p['border']}; border-radius: 5px; padding: 6px 12px; }}
            QPushButton:hover {{ background: {p['sel']}; border-color: {p['accent']}; }}
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit {{
                background: {p['field']}; color: {p['fg']};
                border: 1px solid {p['border']}; border-radius: 5px;
                padding: 5px 8px; selection-background-color: {p['sel']}; }}
            QComboBox::drop-down {{ border: none; }}
            QComboBox QAbstractItemView {{ background: {p['field']}; color: {p['fg']};
                border: 1px solid {p['border']}; selection-background-color: {p['sel']}; }}
            QCheckBox {{ color: {p['fg']}; spacing: 6px; }}
            QListWidget {{ background: {p['field']}; color: {p['fg']};
                border: 1px solid {p['border']}; border-radius: 5px; }}
            QListWidget::item:selected {{ background: {p['sel']}; color: {p['fg']}; }}
            QTabWidget::pane {{ border: 1px solid {p['border']}; border-radius: 8px;
                background: {p['panel']}; top: -1px; }}
            QTabBar::tab {{ background: {p['panel']}; color: {p['muted']};
                padding: 8px 14px; border: 1px solid {p['border']};
                border-bottom: none; border-radius: 5px 5px 0 0; }}
            QTabBar::tab:selected {{ background: {p['sel']}; color: {p['fg']};
                border-color: {p['accent']}; }}
            QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}
            QScrollBar::handle:vertical {{ background: {p['border']}; border-radius: 4px; min-height: 30px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        """)

    def _theme_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        hint = QLabel(self.app.tr("set_theme_hint"))
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {self.app.pal()['muted']};")
        layout.addWidget(hint)
        grid = QGridLayout()
        grid.setSpacing(12)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(0, 1)
        grid.setRowStretch(1, 1)
        self.theme_cards = {}
        for index, key in enumerate(core.THEME_KEYS):
            card = ThemeCard(key, self.app, key == self.data["theme"])
            card.chosen.connect(self._choose_theme)
            self.theme_cards[key] = card
            grid.addWidget(card, index // 2, index % 2)
        layout.addLayout(grid, 1)
        return widget

    def _choose_theme(self, key: str) -> None:
        self.data["theme"] = key
        self.data["dark_mode"] = key != "light"
        if hasattr(self, "theme_combo"):
            self.theme_combo.blockSignals(True)
            self.theme_combo.setCurrentIndex(0 if key != "light" else 1)
            self.theme_combo.blockSignals(False)
        for card_key, card in self.theme_cards.items():
            card.selected = card_key == key
            card.update()
        self._apply_sheet()
        self._changed()

    def _colors_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        base = core.THEMES[self.data.get("theme", "classic")]["palette"]
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        grid = QGridLayout(host)
        self.color_buttons = {}
        row = col = 0
        for key, label in core.COLOR_LABELS[self.app.locale].items():
            btn = QPushButton(label)
            color = self.data["colors"].get(key) or base[key]
            btn.setStyleSheet(f"background: {color}; color: {core.text_on(color)}; "
                              "border-radius: 4px; padding: 8px;")
            btn.clicked.connect(lambda *_a, k=key, b=btn: self._pick_color(k, b))
            self.color_buttons[key] = btn
            grid.addWidget(btn, row, col)
            col += 1
            if col > 1:
                col, row = 0, row + 1
        scroll.setWidget(host)
        layout.addWidget(scroll)
        reset = QPushButton(self.app.tr("set_reset_colors"))
        reset.clicked.connect(self._reset_colors)
        layout.addWidget(reset, 0, Qt.AlignRight)
        return widget

    def _pick_color(self, key: str, button: QPushButton) -> None:
        color = QColorDialog.getColor(QColor(self.data["colors"].get(key, "#ffffff")), self)
        if color.isValid():
            value = color.name()
            self.data["colors"][key] = value
            button.setStyleSheet(f"background: {value}; color: {core.text_on(value)}; "
                                 "border-radius: 4px; padding: 8px;")
            self._changed()

    def _reset_colors(self) -> None:
        self.data["colors"].clear()
        base = core.THEMES[self.data.get("theme", "classic")]["palette"]
        for key, button in self.color_buttons.items():
            color = base[key]
            button.setStyleSheet(f"background: {color}; color: {core.text_on(color)}; "
                                 "border-radius: 4px; padding: 8px;")
        self._changed()

    def _fonts_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        fonts = self.data["fonts"]
        families = sorted(set(QFontDatabase.families()) | set(fonts.get("custom_names", [])))
        row = QHBoxLayout()
        row.addWidget(QLabel(self.app.tr("set_family")))
        self.family_combo = QComboBox()
        self.family_combo.setEditable(True)
        self.family_combo.addItems(families)
        self.family_combo.setCurrentText(fonts.get("family") or "Segoe UI")
        row.addWidget(self.family_combo, 1)
        layout.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel(self.app.tr("set_size")))
        self.size_spin = QSpinBox()
        self.size_spin.setRange(7, 24)
        self.size_spin.setValue(int(fonts.get("size", 11)))
        row.addWidget(self.size_spin)
        row.addWidget(QLabel(self.app.tr("set_title_size")))
        self.title_spin = QSpinBox()
        self.title_spin.setRange(8, 32)
        self.title_spin.setValue(int(fonts.get("title_size", 14)))
        row.addWidget(self.title_spin)
        layout.addLayout(row)

        add = QPushButton(self.app.tr("set_add_font"))
        add.clicked.connect(self._add_font)
        layout.addWidget(add)
        custom = fonts.get("custom", [])
        label = QLabel(self.app.tr("set_custom_fonts") + " " + ", ".join(
            os.path.basename(path) for path in custom) if custom
            else self.app.tr("set_custom_fonts") + " —")
        label.setWordWrap(True)
        layout.addWidget(label)
        hint = QLabel(self.app.tr("set_font_hint"))
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {self.app.pal()['muted']};")
        layout.addWidget(hint)
        self.preview = QLabel(self.app.tr("set_preview"))
        self.preview.setFont(QFont(self.family_combo.currentText(), self.size_spin.value()))
        layout.addWidget(self.preview)
        self.family_combo.currentTextChanged.connect(self._update_preview)
        self.size_spin.valueChanged.connect(self._update_preview)
        self.title_spin.valueChanged.connect(self._update_preview)
        self.family_combo.currentTextChanged.connect(self._changed)
        self.size_spin.valueChanged.connect(self._changed)
        self.title_spin.valueChanged.connect(self._changed)
        layout.addStretch(1)
        return widget

    def _update_preview(self, *_args) -> None:
        self.preview.setFont(QFont(self.family_combo.currentText(), self.size_spin.value()))

    def _add_font(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, self.app.tr("set_add_font"), "",
                                              "Fonts (*.ttf *.otf)")
        if not path:
            return
        fonts = self.data["fonts"]
        custom = list(fonts.get("custom", []))
        if path not in custom:
            custom.append(path)
        fonts["custom"] = custom
        core.load_custom_fonts([path])
        QMessageBox.information(self, "GameBacklog", self.app.tr("font_added").format(path))
        self._changed()

    def _buttons_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        hint = QLabel(self.app.tr("set_button_hint"))
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {self.app.pal()['muted']};")
        layout.addWidget(hint)

        self.button_preview = ToolbarPreview(
            self.app, self.data["toolbar_order"], self.data["toolbar_hidden"])
        layout.addWidget(self.button_preview)

        self.button_list = QListWidget()
        self.button_list.setDragEnabled(True)
        self.button_list.setAcceptDrops(True)
        self.button_list.setDropIndicatorShown(True)
        self.button_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.button_list.setDefaultDropAction(Qt.MoveAction)
        self.button_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self._row_delegate = ButtonRowDelegate(self.app, self.button_list)
        self._row_delegate.toggleRequested.connect(self._toggle_button_at)
        self.button_list.setItemDelegate(self._row_delegate)
        self.button_list.model().rowsMoved.connect(lambda *_a: self._sync_button_order())
        self._refresh_button_list()
        layout.addWidget(self.button_list, 1)

        row = QHBoxLayout()
        up = QPushButton(self.app.tr("set_up"))
        up.clicked.connect(lambda: self._move_button(-1))
        down = QPushButton(self.app.tr("set_down"))
        down.clicked.connect(lambda: self._move_button(1))
        toggle = QPushButton(self.app.tr("set_toggle"))
        toggle.clicked.connect(self._toggle_button)
        row.addWidget(up); row.addWidget(down); row.addWidget(toggle)
        layout.addLayout(row)

        presets = QHBoxLayout()
        for key, text_key in (("min", "set_preset_min"),
                              ("normal", "set_preset_normal"),
                              ("all", "set_preset_all"),
                              ("reset", "set_reset_buttons")):
            btn = QPushButton(self.app.tr(text_key))
            btn.clicked.connect(lambda *_a, k=key: self._apply_preset(k))
            presets.addWidget(btn)
        layout.addLayout(presets)
        return widget

    def _refresh_button_list(self) -> None:
        self.button_list.clear()
        for key in self.data["toolbar_order"]:
            item = QListWidgetItem(clean_label(
                self.app.tr(core.TOOLBAR_LABELS.get(key, key))))
            item.setData(Qt.UserRole, key)
            item.setData(Qt.UserRole + 1, key in self.data["toolbar_hidden"])
            item.setSizeHint(QSize(10, 30))
            self.button_list.addItem(item)
        self.button_preview.set_state(self.data["toolbar_order"],
                                      self.data["toolbar_hidden"])

    def _sync_button_order(self) -> None:
        self.data["toolbar_order"] = [
            str(self.button_list.item(i).data(Qt.UserRole))
            for i in range(self.button_list.count())
        ]
        self.button_preview.set_state(self.data["toolbar_order"],
                                      self.data["toolbar_hidden"])
        self._changed()

    def _move_button(self, delta: int) -> None:
        row = self.button_list.currentRow()
        target = row + delta
        if row < 0 or target < 0 or target >= self.button_list.count():
            return
        items = self.data["toolbar_order"]
        items[row], items[target] = items[target], items[row]
        self._refresh_button_list()
        self.button_list.setCurrentRow(target)
        self._changed()

    def _toggle_button_at(self, row: int) -> None:
        if row < 0 or row >= len(self.data["toolbar_order"]):
            return
        key = self.data["toolbar_order"][row]
        hidden = self.data["toolbar_hidden"]
        if key in hidden:
            hidden.remove(key)
        else:
            hidden.append(key)
        self._refresh_button_list()
        self.button_list.setCurrentRow(row)
        self._changed()

    def _toggle_button(self, *_args) -> None:
        self._toggle_button_at(self.button_list.currentRow())

    def _apply_preset(self, preset: str) -> None:
        if preset == "min":
            visible = ["steam", "pc"]
        elif preset == "normal":
            visible = ["steam", "pc", "edit", "delete", "import", "export"]
        else:
            visible = list(core.TOOLBAR_KEYS)
        self.data["toolbar_order"] = [
            k for k in core.TOOLBAR_KEYS if k in visible
        ] + [k for k in core.TOOLBAR_KEYS if k not in visible]
        self.data["toolbar_hidden"] = [k for k in core.TOOLBAR_KEYS if k not in visible]
        self._refresh_button_list()
        self._changed()

    def _general_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.theme_combo = QComboBox()
        self.theme_combo.addItem(self.app.tr("set_dark"), True)
        self.theme_combo.addItem(self.app.tr("set_light"), False)
        self.theme_combo.setCurrentIndex(0 if self.data["dark_mode"] else 1)
        layout.addLayout(self._row(self.app.tr("set_theme"), self.theme_combo))
        self.lang_combo = QComboBox()
        self.lang_combo.addItem("RU", "ru")
        self.lang_combo.addItem("EN", "en")
        self.lang_combo.setCurrentText(self.app.locale.upper())
        layout.addLayout(self._row(self.app.tr("set_lang"), self.lang_combo))
        self.dock_check = QCheckBox(self.app.tr("set_dock_arrow"))
        self.dock_check.setChecked(self.data["dock_visible"])
        layout.addWidget(self.dock_check)

        self.dock_edge = QComboBox()
        for edge in ("left", "right", "top", "bottom"):
            self.dock_edge.addItem(self.app.tr("dock_" + edge), edge)
        self.dock_edge.setCurrentIndex(
            max(0, self.dock_edge.findData(self.data["dock_edge"])))
        layout.addLayout(self._row(self.app.tr("set_dock_edge"), self.dock_edge))

        self.dock_pos = QSlider(Qt.Horizontal)
        self.dock_pos.setRange(0, 100)
        self.dock_pos.setValue(self.data["dock_pos"])
        layout.addLayout(self._row(self.app.tr("set_dock_position"), self.dock_pos))

        self.dock_mirror = QCheckBox(self.app.tr("set_dock_mirror"))
        self.dock_mirror.setChecked(self.data["dock_mirror"])
        layout.addWidget(self.dock_mirror)

        self.dock_text_mirror = QCheckBox(self.app.tr("set_dock_mirror_text"))
        self.dock_text_mirror.setChecked(self.data["dock_text_mirror"])
        layout.addWidget(self.dock_text_mirror)

        self.autostart_check = QCheckBox(self.app.tr("set_autostart"))
        self.autostart_check.setChecked(self.data["autostart"])
        layout.addWidget(self.autostart_check)

        self.theme_combo.currentIndexChanged.connect(self._changed)
        self.lang_combo.currentIndexChanged.connect(self._changed)
        self.dock_check.stateChanged.connect(self._changed)
        self.dock_edge.currentIndexChanged.connect(self._changed)
        self.dock_pos.valueChanged.connect(self._changed)
        self.dock_mirror.stateChanged.connect(self._changed)
        self.dock_text_mirror.stateChanged.connect(self._changed)
        self.autostart_check.stateChanged.connect(self._changed)
        layout.addStretch(1)
        return widget

    @staticmethod
    def _row(label: str, widget: QWidget) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.addWidget(QLabel(label))
        layout.addWidget(widget, 1)
        return layout

    def _changed(self) -> None:
        """Будь-яка зміна застосовується сама — без кнопки «Застосувати»."""
        self._timer.start()

    def _apply(self) -> None:
        self.data["fonts"]["family"] = self.family_combo.currentText()
        self.data["fonts"]["size"] = self.size_spin.value()
        self.data["fonts"]["title_size"] = self.title_spin.value()
        if not bool(self.theme_combo.currentData()):
            self.data["theme"] = "light"
        elif self.data.get("theme") == "light":
            self.data["theme"] = "classic"
        self.data["dark_mode"] = self.data["theme"] != "light"
        old_locale = self.app.locale
        self.data["language"] = self.lang_combo.currentData() or self.app.locale
        self.data["dock_visible"] = self.dock_check.isChecked()
        self.data["dock_edge"] = self.dock_edge.currentData() or "right"
        self.data["dock_pos"] = self.dock_pos.value()
        self.data["dock_mirror"] = self.dock_mirror.isChecked()
        self.data["dock_text_mirror"] = self.dock_text_mirror.isChecked()
        self.data["autostart"] = self.autostart_check.isChecked()
        self.app.settings.update(self.data)
        set_autostart(self.data["autostart"])
        core.load_custom_fonts(self.data["fonts"].get("custom", []))
        full = self.data["language"] != old_locale
        self.app.rebuild(full=full)
        if full:
            return
        self._apply_sheet()
        for card_key, card in self.theme_cards.items():
            card.selected = card_key == self.data["theme"]
            card.update()
        self.setWindowTitle(self.app.tr("set_title"))

    def done(self, result: int) -> None:
        full = False
        if self._timer.isActive():
            self._timer.stop()
            full = (self.lang_combo.currentData() or self.app.locale) != self.app.locale
            self._apply()
        if self.embedded:
            if not full:
                self.on_close()
            return
        super().done(result)

    def _ok(self) -> None:
        self._timer.stop()
        full = (self.lang_combo.currentData() or self.app.locale) != self.app.locale
        self._apply()
        if full:
            return
        self.accept()


# --------------------------------------------------------------------------- док
class EdgeDock(QWidget):
    WIDTH, HEIGHT = 30, 104

    def __init__(self, app: App) -> None:
        super().__init__()
        self.app = app
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedSize(self.WIDTH, self.HEIGHT)
        self.setCursor(Qt.PointingHandCursor)
        self._hover = 0.0
        self._anim = QPropertyAnimation(self, b"hoverLevel", self)
        self._anim.setDuration(160)
        self.apply_settings()
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)

    def get_hover(self) -> float:
        return self._hover

    def set_hover(self, value: float) -> None:
        self._hover = float(value)
        self.update()

    hoverLevel = Property(float, get_hover, set_hover)

    def _horizontal(self) -> bool:
        return self.app.settings.get("dock_edge", "right") in ("top", "bottom")

    def apply_settings(self) -> None:
        """Край, положення вздовж нього й дзеркало іконки — з налаштувань."""
        horizontal = self._horizontal()
        w, h = (self.HEIGHT, self.WIDTH) if horizontal else (self.WIDTH, self.HEIGHT)
        if self.size() != QSize(w, h):
            self.setFixedSize(w, h)
        screen = QApplication.primaryScreen().availableGeometry()
        edge = self.app.settings.get("dock_edge", "right")
        pos = max(0, min(100, int(self.app.settings.get("dock_pos", 33))))
        if horizontal:
            x = screen.left() + round((screen.width() - w) * pos / 100)
            y = screen.top() if edge == "top" else screen.bottom() - h + 1
        else:
            x = screen.left() if edge == "left" else screen.right() - w + 1
            y = screen.top() + round((screen.height() - h) * pos / 100)
        self.move(x, y)
        self.update()

    def _animate(self, end: float) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._hover)
        self._anim.setEndValue(end)
        self._anim.start()

    def enterEvent(self, event) -> None:
        self._animate(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._animate(0.0)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.app.toggle_window()
        super().mousePressEvent(event)

    def _menu(self, pos: QPoint) -> None:
        menu = QMenu(self)
        menu.addAction(self.app.tr("dock_restore"), self.app.toggle_window)
        menu.addSeparator()
        if self.app.settings.get("dock_visible", True):
            menu.addAction(self.app.tr("dock_hide"), self._hide)
        else:
            menu.addAction(self.app.tr("dock_show"), self._show)
        menu.addAction(self.app.tr("settings"), self.app.window.open_settings)
        menu.addSeparator()
        menu.addAction(self.app.tr("dock_exit"), self.app.quit)
        menu.exec(self.mapToGlobal(pos))

    def _hide(self) -> None:
        self.app.settings["dock_visible"] = False
        core.save_settings(self.app.settings)
        self.hide()

    def _show(self) -> None:
        self.app.settings["dock_visible"] = True
        core.save_settings(self.app.settings)
        self.show()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        pal = self.app.pal()
        hover = min(1.0, max(0.0, self._hover))
        accent, accent2 = pal["accent"], pal["accent2"]
        w, h = self.width(), self.height()
        horizontal = self._horizontal()

        # Дзеркалимо декоративний шар (іконку), напис лишаємо читаємим.
        painter.save()
        if self.app.settings.get("dock_mirror", True):
            if horizontal:
                painter.translate(0, h)
                painter.scale(1, -1)
            else:
                painter.translate(w, 0)
                painter.scale(-1, 1)

        fill = core.mix(pal["dock"], accent, 0.18 + 0.22 * hover)
        border = core.mix(pal["dock_fg"], accent, 0.45 + 0.35 * hover)
        paint_hud_panel(painter, QRectF(1, 1, w - 2, h - 2),
                        fill, border, accent, 7, brackets=True)

        if horizontal:
            lines = ((5.0, accent), (h - 5.0, accent2))
        else:
            lines = ((5.0, accent), (w - 5.0, accent2))
        for offset, color in lines:
            pen = QPen(alpha_color(color, int(70 + 110 * hover)), 1)
            pen.setCosmetic(True)
            painter.setPen(pen)
            if horizontal:
                painter.drawLine(QPointF(14, offset), QPointF(w - 14, offset))
            else:
                painter.drawLine(QPointF(offset, 14), QPointF(offset, h - 14))

        playing = any(str(g.get("status")) == "playing" for g in self.app.games)
        dot = self.app.status_color("playing") if playing else accent2
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(alpha_color(dot, 45)))
        if horizontal:
            painter.drawEllipse(QRectF(10, h / 2 - 6, 12, 12))
            painter.setBrush(QColor(dot))
            painter.drawEllipse(QRectF(13, h / 2 - 3, 6, 6))
        else:
            painter.drawEllipse(QRectF(w / 2 - 6, 10, 12, 12))
            painter.setBrush(QColor(dot))
            painter.drawEllipse(QRectF(w / 2 - 3, 13, 6, 6))
        painter.restore()

        painter.save()
        painter.translate(w / 2, h / 2 + 4)
        if not horizontal:
            painter.rotate(90)
        if self.app.settings.get("dock_text_mirror", False):
            painter.scale(-1, 1)
        font = self.app.tech_font(12, True)
        painter.setFont(font)
        fm = QFontMetrics(font)
        text = "GAME"
        tw = fm.horizontalAdvance(text)
        painter.setPen(QColor(alpha_color(accent, int(120 + 100 * hover))))
        painter.drawText(QRectF(-tw / 2 + 1, -10, tw, 20), Qt.AlignCenter, text)
        painter.setPen(QColor(pal["dock_fg"]))
        painter.drawText(QRectF(-tw / 2, -9, tw, 18), Qt.AlignCenter, text)
        painter.restore()


def main() -> int:
    return App().start()


if __name__ == "__main__":
    raise SystemExit(main())
