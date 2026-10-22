# -*- coding: utf-8 -*-
"""启动画面：在重量级模块导入之前先给用户一个可见窗口。

只依赖 QtCore/QtGui/QtWidgets，导入成本约 0.3s；由 boot.py 在 import main
之前创建，因此 PyQt6.QtWebEngine*、launcher_core 的大量导入都发生在画面
已经绘制之后。窗口刻意做成无边框小卡片（类似大型软件的 splash），不占
任务栏，页面加载完成后由调用方 finish() 关闭。
"""

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

WIDTH = 460
HEIGHT = 172

_BG = "#15171d"
_CARD = "#1b1e26"
_BORDER = "#2b303c"
_TEXT = "#f2f4f8"
_MUTED = "#8b93a7"
_ACCENT = "#3f8cff"


def _icon_pixmap(size: int = 40) -> QPixmap:
    """用代码画一个圆角方块 + 方块字母，避免依赖 ui/icon.svg 在 frozen 下的路径。"""
    pm = QPixmap(size, size)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setBrush(QColor(_ACCENT))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(0, 0, size, size, size * 0.24, size * 0.24)
    p.setPen(QColor("#ffffff"))
    f = QFont("Segoe UI", int(size * 0.42))
    f.setBold(True)
    p.setFont(f)
    p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "D")
    p.end()
    return pm


class StartupSplash(QWidget):
    """无边框启动画面：标题 + 状态文本 + 不定进度条。"""

    def __init__(self):
        super().__init__(None)
        self._finished = False
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(WIDTH, HEIGHT)
        self.setWindowTitle("DevLauncher 正在启动")
        self._build_ui()
        self._center()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        card = QFrame(self)
        card.setObjectName("card")
        card.setStyleSheet(
            "#card { background: %s; border: 1px solid %s; border-radius: 12px; }" % (_CARD, _BORDER)
            + "QLabel { color: %s; }" % _TEXT
        )
        outer.addWidget(card)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(0)

        head = QHBoxLayout()
        head.setSpacing(14)
        logo = QLabel()
        logo.setPixmap(_icon_pixmap(40))
        logo.setFixedSize(40, 40)
        head.addWidget(logo, 0, Qt.AlignmentFlag.AlignTop)

        titles = QVBoxLayout()
        titles.setSpacing(2)
        name = QLabel("DevLauncher")
        f = QFont("Microsoft YaHei UI", 15)
        f.setBold(True)
        name.setFont(f)
        name.setStyleSheet("color: %s;" % _TEXT)
        titles.addWidget(name)
        self._status = QLabel("正在启动…")
        sf = QFont("Microsoft YaHei UI", 9)
        self._status.setFont(sf)
        self._status.setStyleSheet("color: %s;" % _MUTED)
        titles.addWidget(self._status)
        head.addLayout(titles, 1)
        lay.addLayout(head)

        lay.addStretch(1)

        self._bar = QProgressBar(card)
        self._bar.setRange(0, 0)
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(3)
        self._bar.setStyleSheet(
            "QProgressBar { background: %s; border: none; border-radius: 2px; }"
            "QProgressBar::chunk { background: %s; border-radius: 2px; }" % (_BORDER, _ACCENT)
        )
        lay.addWidget(self._bar)

        self._hint = QLabel("正在准备界面，请稍候")
        self._hint.setFont(QFont("Microsoft YaHei UI", 8))
        self._hint.setStyleSheet("color: %s;" % _MUTED)
        lay.addSpacing(8)
        lay.addWidget(self._hint)

    def _center(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        self.move(
            geo.center().x() - self.width() // 2,
            int(geo.center().y() - self.height() / 2) - 40,
        )

    def set_status(self, text: str) -> None:
        """更新状态文本并立即重绘（调用方随后会阻塞在 import 上）。"""
        if self._finished:
            return
        self._status.setText(text)
        QApplication.processEvents()

    def pump(self, ms: int = 0) -> None:
        """把已排队的绘制/布局事件刷出去，保证窗口真的可见。"""
        QApplication.processEvents()
        if ms > 0:
            QTimer.singleShot(ms, lambda: None)
            QApplication.processEvents()

    def finish(self) -> None:
        if self._finished:
            return
        self._finished = True
        self.close()
