# -*- coding: utf-8 -*-
"""
Marvis Pet —— 本地桌宠程序（Windows / Python 3.12 + PySide6）

对标 dsh-harness-jarvis 的核心交互形态，适配本机：
  * 透明无边框置顶悬浮粒子光球宠物，支持鼠标拖拽；
  * 拖到屏幕边缘自动贴边收纳成扁条，鼠标触碰边缘自动展开；
  * 全局快捷键（默认 Ctrl+Alt+J）唤起快速对话输入条，回车发送，对话记录可滚动；
  * 对话后端接本机 Ollama（默认 http://127.0.0.1:11434，模型 qwen2.5:7b），完全本地推理；
  * 空闲 / 思考中 / 回复中 / 出错 四种状态用颜色与粒子形态区分；
  * 系统托盘：显示/隐藏窗口、开机自启开关、退出。

所有可配置项集中在同目录 config.json（首次运行自动生成默认配置）。
"""

from __future__ import annotations

import html
import json
import math
import os
import sys
import time

import requests

from PySide6.QtCore import (
    QObject,
    QPoint,
    QPointF,
    QRect,
    QSize,
    Qt,
    QThread,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QCursor,
    QFont,
    QIcon,
    QPainter,
    QPen,
    QPixmap,
    QRadialGradient,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSystemTrayIcon,
    QFrame,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

APP_NAME = "MarvisPet"
PET_TITLE = "MarvisPet"
CHAT_TITLE = "Marvis Pet Chat"
AUTOSTART_REG_NAME = "MarvisPet"
AUTOSTART_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

DEFAULT_CONFIG = {
    "ollama_base_url": "http://127.0.0.1:11434",
    "model": "qwen2.5:7b",
    "hotkey": "ctrl+alt+j",
    "auto_start": False,
    "pet_size": 96,
    "opacity": 0.95,
    # token 单价估算预留：prompt_per_1k / completion_per_1k 配置后启用金额估算，
    # 保持 None 时本地模型标注"本地免费"。
    "token_price": {"prompt_per_1k": None, "completion_per_1k": None, "currency": "CNY"},
    # Marvis 状态出口（预留）：type = none | file | http
    #   - file: 轮询本地状态 JSON（含 sessions 数组）展示 Marvis 任务流程
    #   - http: 轮询 HTTP 端点（同上）
    #   - none: 不启用，降级为本地对话流程卡片
    "marvis_state_source": {"type": "none", "url": "", "file": "", "interval": 3000},
}

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

def config_path() -> str:
    """配置文件路径：源码运行在项目目录，打包后与 exe 同目录。"""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "config.json")


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    path = config_path()
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                user = json.load(f)
            if isinstance(user, dict):
                cfg.update({k: v for k, v in user.items() if k in DEFAULT_CONFIG})
        else:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return cfg


# ---------------------------------------------------------------------------
# 开机自启（注册表 HKCU\...\Run）
# ---------------------------------------------------------------------------

def _autostart_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    exe = sys.executable
    if exe.lower().endswith("python.exe"):
        exe = exe[:-4] + "w.exe"  # 使用 pythonw 避免弹出控制台
    return f'"{exe}" "{os.path.abspath(__file__)}"'


def set_autostart(enabled: bool) -> bool:
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, AUTOSTART_REG_KEY, 0, winreg.KEY_SET_VALUE
        ) as k:
            if enabled:
                winreg.SetValueEx(k, AUTOSTART_REG_NAME, 0, winreg.REG_SZ, _autostart_command())
            else:
                try:
                    winreg.DeleteValue(k, AUTOSTART_REG_NAME)
                except FileNotFoundError:
                    pass
        return True
    except Exception:
        return False


def is_autostart() -> bool:
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, AUTOSTART_REG_KEY, 0, winreg.KEY_READ
        ) as k:
            winreg.QueryValueEx(k, AUTOSTART_REG_NAME)
            return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Ollama 客户端（本地推理）
# ---------------------------------------------------------------------------

class OllamaClient:
    def __init__(self, base_url: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.model = model
        # 最近一次流式响应的 usage 字段（prompt_eval_count / eval_count）
        self.last_usage: dict = {}

    def ping(self, timeout: float = 3.0) -> bool:
        try:
            r = requests.get(f"{self.base_url}/api/tags", timeout=timeout)
            return r.status_code == 200
        except Exception:
            return False

    def chat_stream(self, messages):
        """流式对话，逐段产出回复文本；结束时把 usage 记录到 self.last_usage。"""
        self.last_usage = {}
        url = f"{self.base_url}/api/chat"
        payload = {"model": self.model, "messages": messages, "stream": True}
        with requests.post(url, json=payload, stream=True, timeout=300) as r:
            r.raise_for_status()
            for line in r.iter_lines(decode_unicode=True):
                if not line:
                    continue
                data = json.loads(line)
                if data.get("done"):
                    # 兼容两种 Ollama 返回形态：
                    #  1) 嵌套 usage 对象；2) 顶层扁平字段（当前版本流式返回）
                    usage = data.get("usage") or {}
                    if not usage:
                        usage = {
                            k: data[k]
                            for k in ("prompt_eval_count", "eval_count",
                                     "prompt_eval_cached_count", "total_duration", "eval_duration")
                            if k in data
                        }
                    self.last_usage = usage
                    return
                delta = (data.get("message") or {}).get("content") or ""
                if delta:
                    yield delta


class ChatWorker(QThread):
    """后台对话线程，避免阻塞 UI。"""

    token = Signal(str)
    finished_ok = Signal(str, dict)  # (完整回复, usage)
    failed = Signal(str)

    def __init__(self, client: OllamaClient, messages: list):
        super().__init__()
        self._client = client
        self._messages = messages

    def run(self):
        try:
            parts = []
            for t in self._client.chat_stream(self._messages):
                parts.append(t)
                self.token.emit(t)
            self.finished_ok.emit("".join(parts), self._client.last_usage)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(f"Ollama 请求失败：{e}")


# ---------------------------------------------------------------------------
# 全局快捷键（keyboard 库低级钩子，独立线程回调）
# ---------------------------------------------------------------------------

class HotkeyManager(QObject):
    triggered = Signal()

    def __init__(self):
        super().__init__()
        self._handler = None

    def start(self, hotkey: str) -> bool:
        try:
            import keyboard

            self._handler = keyboard.add_hotkey(hotkey, self._emit, suppress=False)
            return True
        except Exception:
            return False

    def _emit(self):
        # 钩子线程回调；Signal 默认 AutoConnection，跨线程自动排队到主线程
        self.triggered.emit()

    def stop(self):
        try:
            import keyboard

            if self._handler is not None:
                keyboard.remove_hotkey(self._handler)
                self._handler = None
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 任务流程卡片（借鉴 mavis-pet：老卡上 / 新卡下 / 完成 30s 消失）
# ---------------------------------------------------------------------------

TASK_STATES = {
    # 状态: (显示文字, 颜色)
    "thinking": ("思考中", "#b082ff"),
    "streaming": ("生成中", "#5aa8ff"),
    "waiting": ("等待中", "#ffb84d"),
    "done": ("已完成", "#3ecf6e"),
    "failed": ("出错", "#ff5c5c"),
}

# Marvis 状态出口 session.state -> 卡片状态映射
MARVIS_STATE_MAP = {
    "thinking": "thinking",
    "streaming": "streaming",
    "streaming_text": "streaming",
    "waiting": "waiting",
    "waiting_perm": "waiting",
    "done": "done",
    "failed": "failed",
    "error": "failed",
}

DONE_EXPIRE_MS = 30000  # 完成 / 出错的卡片 30s 后自动消失


class TaskCardItem(QFrame):
    """单张任务状态卡片。"""

    removed = Signal(str)

    def __init__(self, task_id: str, title: str, state: str, source: str):
        super().__init__()
        self.task_id = task_id
        self.source = source
        self.state = state
        self.setObjectName("taskCard")
        self.setStyleSheet(
            "QFrame#taskCard{background:rgba(26,29,38,235);"
            "border:1px solid #3a3f4a;border-radius:8px;}"
        )
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(8)
        self._dot = QLabel("●")
        self._dot.setStyleSheet("border:none;")
        self._dot.setFixedWidth(14)
        title_label = QLabel(title)
        title_label.setStyleSheet("color:#e8e8e8;font-size:12px;border:none;")
        title_label.setToolTip(title)
        self._state_label = QLabel()
        self._state_label.setStyleSheet("border:none;")
        lay.addWidget(self._dot)
        lay.addWidget(title_label, 1)
        lay.addWidget(self._state_label)
        self._expire = QTimer(self)
        self._expire.setSingleShot(True)
        self._expire.timeout.connect(lambda: self.removed.emit(self.task_id))
        self.set_state(state)

    def set_state(self, state: str):
        text, color = TASK_STATES.get(state, TASK_STATES["thinking"])
        self.state = state
        self._dot.setStyleSheet(f"color:{color};font-size:12px;border:none;")
        self._state_label.setText(text)
        self._state_label.setStyleSheet(f"color:{color};font-size:11px;border:none;")
        if state in ("done", "failed"):
            self._expire.start(DONE_EXPIRE_MS)
        else:
            self._expire.stop()


class TaskOverlay(QWidget):
    """任务流程卡片悬浮层：悬浮在宠物窗口上方，多任务堆叠（老上、新下），
    完成 / 出错 30s 自动消失。支持本地对话流程与 Marvis 状态出口两路卡片。"""

    def __init__(self, pet: PetWindow):
        super().__init__(None)
        self.pet = pet
        self._local_cards: dict[str, TaskCardItem] = {}
        self._marvis_cards: dict[str, TaskCardItem] = {}
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedWidth(300)
        self.setFixedHeight(0)
        self._vbox = QVBoxLayout(self)
        self._vbox.setContentsMargins(4, 4, 4, 4)
        self._vbox.setSpacing(6)
        self._vbox.addStretch(1)

    # ----- 布局与定位 -----
    def _resize_to_fit(self):
        self.setFixedHeight(max(0, int(self.sizeHint().height())))
        self.reposition()

    def reposition(self):
        g = self.pet.frameGeometry()
        screen = QApplication.primaryScreen().availableGeometry()
        x = g.center().x() - self.width() // 2
        y = g.top() - self.height() - 10
        if x < screen.left():
            x = screen.left()
        if x + self.width() > screen.right():
            x = screen.right() - self.width()
        if y < screen.top():
            y = g.bottom() + 10  # 上方放不下则放到宠物下方
        self.move(x, y)

    # ----- 本地对话流程卡片 -----
    def add_local_task(self, task_id: str, title: str, state: str = "thinking"):
        if task_id in self._local_cards:
            self._local_cards[task_id].set_state(state)
            self._resize_to_fit()
            return
        card = TaskCardItem(task_id, title, state, "local")
        card.removed.connect(self._on_card_expired)
        self._local_cards[task_id] = card
        self._vbox.insertWidget(self._vbox.count() - 1, card)
        self._resize_to_fit()

    def update_local_task(self, task_id: str, state: str):
        card = self._local_cards.get(task_id)
        if card is not None:
            card.set_state(state)
            self._resize_to_fit()

    def remove_local_task(self, task_id: str):
        card = self._local_cards.pop(task_id, None)
        if card is not None:
            self._vbox.removeWidget(card)
            card.deleteLater()
            self._resize_to_fit()

    # ----- Marvis 状态出口任务卡片（有数据展示 / 无数据降级本地）-----
    def set_marvis_sessions(self, sessions: list):
        for tid in list(self._marvis_cards):
            self.remove_marvis_task(tid)
        for item in sessions or []:
            tid = str(item.get("id") or item.get("title") or f"m-{id(item)}")
            state = MARVIS_STATE_MAP.get(str(item.get("state") or ""), "thinking")
            title = str(item.get("title") or item.get("detail") or "Marvis 任务")
            detail = item.get("detail")
            if detail and str(detail) != title:
                title = f"{title} · {detail}"
            card = TaskCardItem(tid, title, state, "marvis")
            card.removed.connect(self._on_card_expired)
            self._marvis_cards[tid] = card
            self._vbox.insertWidget(self._vbox.count() - 1, card)
        self._resize_to_fit()

    def remove_marvis_task(self, task_id: str):
        card = self._marvis_cards.pop(task_id, None)
        if card is not None:
            self._vbox.removeWidget(card)
            card.deleteLater()
            self._resize_to_fit()

    def clear_marvis_sessions(self):
        for tid in list(self._marvis_cards):
            self.remove_marvis_task(tid)

    def _on_card_expired(self, task_id: str):
        self.remove_local_task(task_id)
        self.remove_marvis_task(task_id)


# ---------------------------------------------------------------------------
# Marvis 状态出口轮询（预留）：有数据展示 Marvis 任务流程，无数据降级本地对话
# ---------------------------------------------------------------------------

class MarvisStatePoller(QObject):
    """按配置轮询本地状态文件或 HTTP 端点，把 Marvis 任务流程映射成任务卡片。
    数据源未配置 / 无数据 / 读取失败时清空 Marvis 卡片，仅保留本地对话流程。"""

    def __init__(self, overlay: TaskOverlay, cfg: dict):
        super().__init__()
        self.overlay = overlay
        self.source = dict(cfg.get("marvis_state_source") or {"type": "none"})
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)

    def start(self):
        t = str(self.source.get("type") or "none")
        if t in ("file", "http"):
            self._timer.start(int(self.source.get("interval") or 3000))

    def stop(self):
        self._timer.stop()

    def _poll(self):
        try:
            t = str(self.source.get("type") or "none")
            if t == "file":
                path = self.source.get("file") or ""
                if not path or not os.path.exists(path):
                    self.overlay.clear_marvis_sessions()
                    return
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            elif t == "http":
                url = self.source.get("url") or ""
                if not url:
                    self.overlay.clear_marvis_sessions()
                    return
                data = requests.get(url, timeout=3).json()
            else:
                self.overlay.clear_marvis_sessions()
                return
            self.overlay.set_marvis_sessions(data.get("sessions") or [])
        except Exception:
            # 状态出口无数据 / 读取失败 → 降级：仅保留本地对话流程卡片
            self.overlay.clear_marvis_sessions()


# ---------------------------------------------------------------------------
# 粒子光球宠物窗口
# ---------------------------------------------------------------------------

STATE_COLORS = {
    # 状态: (主色, 深色)
    "idle": (QColor(80, 160, 255), QColor(30, 70, 160)),      # 蓝：平静漂浮
    "thinking": (QColor(190, 130, 255), QColor(110, 60, 200)),  # 紫：快速环绕
    "replying": (QColor(90, 230, 140), QColor(30, 150, 80)),   # 绿：脉冲扩散
    "error": (QColor(255, 100, 100), QColor(190, 30, 30)),     # 红：抖动闪烁
}


class _Particle:
    __slots__ = ("radius", "angle", "speed", "size", "phase")

    def __init__(self, radius, angle, speed, size, phase=0.0):
        self.radius = radius
        self.angle = angle
        self.speed = speed
        self.size = size
        self.phase = phase


class PetWindow(QWidget):
    def __init__(self, cfg: dict):
        super().__init__(None)
        self.cfg = cfg
        self.state = "idle"
        self._dragging = False
        self._drag_offset = QPoint()
        self._snapped = False
        self._restore_rect = QRect()
        self._angle = 0.0
        self._pulse = 0.0
        # 事件气泡（done! / oops / hey!）
        self._bubble = None  # {"text":..., "color":QColor, "start":float, "duration":float}
        self._bubble_timer = QTimer(self)
        self._bubble_timer.timeout.connect(self._bubble_tick)
        self._bubble_timer.start(40)

        self.setWindowTitle(PET_TITLE)
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_DeleteOnClose, False)

        size = max(48, int(cfg.get("pet_size", 96)))
        self.setFixedSize(size, size)
        try:
            self.setWindowOpacity(float(cfg.get("opacity", 0.95)))
        except Exception:
            pass

        self._build_particles()

        # 初始位置：屏幕右下角附近
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.right() - size - 80, screen.bottom() - size - 80)

        # 动画刷新
        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._tick)
        self._anim_timer.start(30)

        # 边缘触碰检测（收纳时自动展开）
        self._edge_timer = QTimer(self)
        self._edge_timer.timeout.connect(self._check_edge_hover)
        self._edge_timer.start(200)

        # 任务流程卡片悬浮层（位于宠物上方）+ 对话面板
        self.overlay = TaskOverlay(self)
        self.overlay.show()
        self.chat_panel = ChatPanel(cfg, self)

    # ----- 粒子构建 -----
    def _build_particles(self):
        size = self.width() // 2
        self._particles = [
            _Particle(radius=size * 0.55 + i * size * 0.09, angle=i * math.pi * 2 / 14,
                      speed=0.02 + (i % 5) * 0.006, size=3 + (i % 4), phase=i * 0.7)
            for i in range(14)
        ]

    # ----- 状态 -----
    def set_state(self, state: str):
        if state not in STATE_COLORS:
            state = "idle"
        self.state = state
        self.update()

    # ----- 事件气泡（done! / oops / hey!）-----
    def add_bubble(self, text: str, color: str = "#ffd75a", duration: float = 1.8):
        self._bubble = {
            "text": text,
            "color": QColor(color),
            "start": time.monotonic(),
            "duration": duration,
        }
        self.update()

    def _bubble_tick(self):
        if self._bubble is None:
            return
        elapsed = time.monotonic() - self._bubble["start"]
        if elapsed >= self._bubble["duration"]:
            self._bubble = None
        self.update()

    def _paint_bubble(self, painter: QPainter):
        if self._bubble is None:
            return
        b = self._bubble
        elapsed = time.monotonic() - b["start"]
        ratio = elapsed / b["duration"]
        alpha = 255
        if ratio > 0.7:
            alpha = int(255 * (1.0 - (ratio - 0.7) / 0.3))
        if alpha <= 0:
            self._bubble = None
            return
        w, h = self.width(), self.height()
        text = b["text"]
        fm = painter.fontMetrics()
        bw = min(w - 8, fm.horizontalAdvance(text) + 26)
        bh = fm.height() + 12
        rect = QRect(int((w - bw) / 2), 6, int(bw), int(bh))
        col = QColor(b["color"])
        col.setAlpha(alpha)
        painter.setPen(Qt.NoPen)
        painter.setBrush(col)
        painter.drawRoundedRect(rect, 8, 8)
        # 气泡尾巴指向宠物中心
        tip_x = w / 2
        painter.drawPolygon(
            [QPointF(tip_x - 6, rect.bottom()), QPointF(tip_x + 6, rect.bottom()),
             QPointF(tip_x, rect.bottom() + 7)]
        )
        painter.setPen(QPen(QColor(255, 255, 255, alpha), 1))
        painter.drawText(rect.adjusted(4, 0, -4, 0), Qt.AlignCenter, text)

    # ----- 窗口移动时卡片悬浮层跟随 -----
    def moveEvent(self, event):
        super().moveEvent(event)
        if hasattr(self, "overlay"):
            self.overlay.reposition()

    # ----- 动画 tick -----
    def _tick(self):
        self._angle += 0.05
        self._pulse += 0.12
        self.update()

    # ----- 绘制 -----
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if self._snapped:
            self._paint_bar(painter)
        else:
            self._paint_orb(painter)
        self._paint_bubble(painter)

    def _paint_bar(self, painter):
        """贴边收纳后的细扁条。"""
        w, h = self.width(), self.height()
        main_c, _ = STATE_COLORS.get(self.state, STATE_COLORS["idle"])
        grad = QRadialGradient(QPointF(w / 2, h / 2), max(w, h) / 2)
        grad.setColorAt(0.0, QColor(main_c.red(), main_c.green(), main_c.blue(), 230))
        grad.setColorAt(1.0, QColor(main_c.red(), main_c.green(), main_c.blue(), 80))
        painter.setBrush(grad)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(QRectF(0, h * 0.1, w, h * 0.8), w / 2, w / 2)

    def _paint_orb(self, painter):
        cx = self.width() / 2
        cy = self.height() / 2
        main_c, dark_c = STATE_COLORS.get(self.state, STATE_COLORS["idle"])
        r = self.width() * 0.32

        # 中心光球
        glow = QRadialGradient(QPointF(cx - r * 0.25, cy - r * 0.25), r * 2.1)
        glow.setColorAt(0.0, QColor(main_c.red(), main_c.green(), main_c.blue(), 255))
        glow.setColorAt(0.45, QColor(main_c.red(), main_c.green(), main_c.blue(), 170))
        glow.setColorAt(1.0, QColor(dark_c.red(), dark_c.green(), dark_c.blue(), 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(QPointF(cx, cy), r * 1.8, r * 1.8)

        # 状态相关脉冲外圈
        if self.state in ("replying", "error"):
            pulse_r = r * (1.15 + 0.35 * (0.5 + 0.5 * math.sin(self._pulse)))
            pen = QPen(QColor(main_c.red(), main_c.green(), main_c.blue(), 150), 2)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(QPointF(cx, cy), pulse_r, pulse_r)

        # 粒子轨道
        speed_factor = 1.0
        if self.state == "thinking":
            speed_factor = 2.4
        elif self.state == "error":
            speed_factor = 1.6
        for p in self._particles:
            ang = p.angle + self._angle * p.speed * speed_factor
            px = cx + math.cos(ang) * p.radius
            py = cy + math.sin(ang) * p.radius
            alpha = 120 + 80 * (0.5 + 0.5 * math.sin(self._pulse + p.phase))
            c = QColor(main_c.red(), main_c.green(), main_c.blue(), int(alpha))
            painter.setPen(Qt.NoPen)
            painter.setBrush(c)
            painter.drawEllipse(QPointF(px, py), p.size, p.size)

        # 出错时轻微抖动偏移
        if self.state == "error":
            off = 1.0 + 1.5 * math.sin(self._pulse * 3.0)
            painter.setPen(QPen(QColor(255, 200, 200, 120), 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(QPointF(cx, cy), r * 1.0 + off, r * 1.0 + off)

    # ----- 鼠标拖拽 -----
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._dragging = True
            self._drag_offset = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._dragging:
            self.move(e.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, e):
        if self._dragging:
            self._dragging = False
            self._maybe_snap()

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.chat_panel.toggle_visible(self.frameGeometry())

    # ----- 贴边收纳 -----
    def _maybe_snap(self):
        if self._snapped:
            return
        screen = QApplication.primaryScreen().availableGeometry()
        geom = self.frameGeometry()
        near = 20
        if geom.left() <= screen.left() + near:
            self._snap("left", geom)
        elif geom.right() >= screen.right() - near:
            self._snap("right", geom)
        else:
            self._expand()

    def _snap(self, side: str, geom: QRect):
        self._snapped = True
        self._restore_rect = geom
        bar_w = max(6, min(10, self.width() // 8))
        screen = QApplication.primaryScreen().availableGeometry()
        if side == "left":
            self.setGeometry(QRect(screen.left(), geom.top(), bar_w, geom.height()))
        else:
            self.setGeometry(QRect(screen.right() - bar_w, geom.top(), bar_w, geom.height()))
        self.update()

    def _expand(self):
        if self._snapped:
            self._snapped = False
            if not self._restore_rect.isNull():
                self.setGeometry(self._restore_rect)
            self.update()

    def _check_edge_hover(self):
        if not self._snapped:
            return
        screen = QApplication.primaryScreen().availableGeometry()
        pos = QCursor.pos()
        bar = self.frameGeometry()
        left_zone = pos.x() <= screen.left() + 40
        right_zone = pos.x() >= screen.right() - 40
        in_y = bar.top() - 12 <= pos.y() <= bar.bottom() + 12
        if (left_zone or right_zone) and in_y:
            self._expand()


# ---------------------------------------------------------------------------
# 快速对话面板
# ---------------------------------------------------------------------------

def estimate_cost_text(cfg: dict, prompt_tokens: int, completion_tokens: int) -> str:
    """预留的按模型单价估算金额逻辑。

    仅当 config.json 的 token_price.prompt_per_1k / completion_per_1k 配置了数值时
    才估算（标注 ≈）；未配置时本地模型一律标注"本地免费"。
    """
    price = cfg.get("token_price") or {}
    pp = price.get("prompt_per_1k")
    cp = price.get("completion_per_1k")
    if pp is None and cp is None:
        return "本地免费"
    try:
        pp = float(pp or 0.0)
        cp = float(cp or 0.0)
    except (TypeError, ValueError):
        return "本地免费"
    total = prompt_tokens / 1000.0 * pp + completion_tokens / 1000.0 * cp
    cur = str(price.get("currency") or "CNY")
    symbol = "¥" if cur == "CNY" else "$" if cur == "USD" else f"{cur} "
    return f"≈{symbol}{total:.4f}"


class ChatPanel(QWidget):
    def __init__(self, cfg: dict, pet: PetWindow):
        super().__init__(None)
        self.cfg = cfg
        self.pet = pet
        self._worker = None
        self.messages = [
            {
                "role": "system",
                "content": (
                    "你是 Marvis Pet，一个运行在用户桌面的本地 AI 桌宠助手。"
                    "回答保持简洁、友好、准确。"
                ),
            }
        ]
        self._ai_buffer = ""
        # token 消耗统计（输入 prompt / 输出 eval）
        self._session_usage = {"prompt": 0, "eval": 0}
        self._task_seq = 0
        self._current_task_id = None

        self.setWindowTitle(CHAT_TITLE)
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(440, 560)

        self._build_ui()
        self._load_client()

    def _load_client(self):
        self.client = OllamaClient(
            self.cfg.get("ollama_base_url", DEFAULT_CONFIG["ollama_base_url"]),
            self.cfg.get("model", DEFAULT_CONFIG["model"]),
        )

    def _build_ui(self):
        root = QWidget(self)
        root.setStyleSheet(
            "QWidget#chatRoot{background:rgba(24,26,32,235);border-radius:14px;}"
            "QTextBrowser#log{background:transparent;border:none;color:#ddd;font-size:13px;}"
            "QLineEdit#input{background:#1e2128;border:1px solid #3a3f4a;border-radius:8px;"
            "color:#eee;padding:8px 10px;font-size:14px;}"
            "QLineEdit#input:focus{border:1px solid #5090ff;}"
            "QPushButton#send{background:#2b6fd6;color:white;border:none;border-radius:8px;"
            "padding:6px 16px;font-size:13px;}"
            "QPushButton#send:hover{background:#3a80ea;}"
        )
        root.setObjectName("chatRoot")
        root.setGeometry(0, 0, 440, 560)

        outer = QVBoxLayout(root)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("Marvis Pet · 本地对话")
        title.setStyleSheet("color:#9ab8ff;font-size:14px;font-weight:bold;border:none;")
        self.status_label = QLabel("空闲")
        self.status_label.setStyleSheet("color:#6fb8ff;font-size:12px;border:none;")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.status_label)
        outer.addLayout(header)

        self.log = QTextBrowser()
        self.log.setObjectName("log")
        self.log.setOpenExternalLinks(False)
        outer.addWidget(self.log, 1)

        input_row = QHBoxLayout()
        self.input_edit = QLineEdit()
        self.input_edit.setObjectName("input")
        self.input_edit.setPlaceholderText("输入问题，回车发送…")
        self.input_edit.returnPressed.connect(self._send)
        send_btn = QPushButton("发送")
        send_btn.setObjectName("send")
        send_btn.clicked.connect(self._send)
        input_row.addWidget(self.input_edit, 1)
        input_row.addWidget(send_btn)
        outer.addLayout(input_row)

        # token 消耗状态栏
        self.token_label = QLabel("本次 输入 0 · 输出 0　|　会话 输入 0 · 输出 0　|　本地免费")
        self.token_label.setStyleSheet("color:#8a93a6;font-size:11px;border:none;")
        outer.addWidget(self.token_label)

        self._append("系统", "Ollama 连接正常，随时可以提问。", "#7fa8ff")

    # ----- 显示/隐藏 -----
    def toggle_visible(self, pet_geom: QRect):
        if self.isVisible():
            self.hide()
            return
        screen = QApplication.primaryScreen().availableGeometry()
        x = pet_geom.right() + 10
        y = pet_geom.top()
        if x + self.width() > screen.right():
            x = pet_geom.left() - self.width() - 10
        if y + self.height() > screen.bottom():
            y = screen.bottom() - self.height()
        if y < screen.top():
            y = screen.top()
        self.move(max(screen.left(), x), max(screen.top(), y))
        self.show()
        self.raise_()
        self.input_edit.setFocus()

    # ----- 对话记录 -----
    def _append(self, who: str, text: str, color: str):
        self.log.append(
            f'<div style="margin:5px 0;">'
            f'<b style="color:{color};">{html.escape(who)}</b><br>'
            f'<span style="color:#e8e8e8;">{html.escape(text)}</span></div>'
        )
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def _append_stream(self, text: str):
        """流式追加到当前 AI 回复块（同一段内不换行）。"""
        cursor = self.log.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(text)
        self.log.setTextCursor(cursor)
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    # ----- 发送 -----
    def _send(self):
        text = self.input_edit.text().strip()
        if not text:
            return
        if self._worker is not None and self._worker.isRunning():
            self.status_label.setText("正在回复，请稍候…")
            return
        self.input_edit.clear()
        self.messages.append({"role": "user", "content": text})
        self._append("你", text, "#9ab8ff")
        self._append("Marvis", "", "#7fe0a0")  # 占位，后续流式填充

        self._ai_buffer = ""
        self.pet.set_state("thinking")
        self.status_label.setText("思考中…")

        # 任务流程卡片：发送 → thinking；首 token → streaming；完成 → done（30s 消失）
        self._task_seq += 1
        self._current_task_id = f"local-{self._task_seq}"
        title = text if len(text) <= 18 else text[:18] + "…"
        self.pet.overlay.add_local_task(self._current_task_id, title, "thinking")
        # 事件气泡：收到新消息 → hey!
        self.pet.add_bubble("hey!", "#ffb84d")

        self._worker = ChatWorker(self.client, self.messages)
        self._worker.token.connect(self._on_token)
        self._worker.finished_ok.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_token(self, delta: str):
        if not self._ai_buffer:
            self.pet.set_state("replying")
            self.status_label.setText("回复中…")
            if self._current_task_id:
                self.pet.overlay.update_local_task(self._current_task_id, "streaming")
        self._ai_buffer += delta
        self._append_stream(delta)

    def _on_finished(self, answer: str, usage: dict):
        self.messages.append({"role": "assistant", "content": answer})
        self._update_usage(usage)
        self._ai_buffer = ""
        self.pet.set_state("idle")
        self.status_label.setText("空闲")
        if self._current_task_id:
            self.pet.overlay.update_local_task(self._current_task_id, "done")
            self._current_task_id = None
        # 事件气泡：任务完成 → done!
        self.pet.add_bubble("done!", "#3ecf6e")

    def _on_failed(self, err: str):
        self._append("系统", err, "#ff7a7a")
        self._ai_buffer = ""
        self.pet.set_state("error")
        self.status_label.setText("出错")
        if self._current_task_id:
            self.pet.overlay.update_local_task(self._current_task_id, "failed")
            self._current_task_id = None
        # 事件气泡：任务出错 → oops!
        self.pet.add_bubble("oops!", "#ff5c5c")
        QTimer.singleShot(3000, lambda: (self.pet.set_state("idle"), self.status_label.setText("空闲")))

    # ----- token 消耗统计 -----
    def _update_usage(self, usage: dict):
        p = int(usage.get("prompt_eval_count") or 0)
        e = int(usage.get("eval_count") or 0)
        self._session_usage["prompt"] += p
        self._session_usage["eval"] += e
        self._update_token_label(p, e)

    def _update_token_label(self, p: int, e: int):
        sp = self._session_usage["prompt"]
        se = self._session_usage["eval"]
        cost = estimate_cost_text(self.cfg, sp, se)
        self.token_label.setText(
            f"本次 输入 {p} · 输出 {e}　|　会话 输入 {sp} · 输出 {se}　|　{cost}"
        )

    def closeEvent(self, event):
        event.ignore()
        self.hide()


# ---------------------------------------------------------------------------
# 系统托盘
# ---------------------------------------------------------------------------

class TrayManager(QObject):
    def __init__(self, app: QApplication, pet: PetWindow):
        super().__init__()
        self.app = app
        self.pet = pet
        self.tray = None

    def _make_icon(self) -> QIcon:
        pix = QPixmap(64, 64)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        grad = QRadialGradient(QPointF(28, 28), 30)
        grad.setColorAt(0.0, QColor(120, 180, 255))
        grad.setColorAt(1.0, QColor(30, 70, 160))
        p.setPen(Qt.NoPen)
        p.setBrush(grad)
        p.drawEllipse(QPointF(32, 32), 24, 24)
        p.end()
        return QIcon(pix)

    def build(self) -> bool:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return False
        self.tray = QSystemTrayIcon(self._make_icon(), self)
        self.tray.setToolTip("Marvis Pet 桌宠")

        menu = QMenu()

        act_toggle = QAction("显示 / 隐藏宠物", menu)
        act_toggle.triggered.connect(self._toggle_pet)
        menu.addAction(act_toggle)

        act_chat = QAction("打开对话输入条", menu)
        act_chat.triggered.connect(self._open_chat)
        menu.addAction(act_chat)

        menu.addSeparator()

        act_autostart = QAction("开机自启", menu)
        act_autostart.setCheckable(True)
        act_autostart.setChecked(is_autostart())
        act_autostart.toggled.connect(set_autostart)
        menu.addAction(act_autostart)

        menu.addSeparator()

        act_quit = QAction("退出", menu)
        act_quit.triggered.connect(self._quit)
        menu.addAction(act_quit)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_activated)
        self.tray.show()
        return True

    def _toggle_pet(self):
        self.pet.setVisible(not self.pet.isVisible())

    def _open_chat(self):
        if self.pet.isVisible():
            self.pet.chat_panel.toggle_visible(self.pet.frameGeometry())

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self._toggle_pet()

    def _quit(self):
        self.app.quit()


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def main():
    cfg = load_config()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)  # 托盘常驻，不因窗口关闭退出

    pet = PetWindow(cfg)
    pet.show()

    # Marvis 状态出口轮询（预留）：未配置时静默降级为本地对话流程
    marvis_poller = MarvisStatePoller(pet.overlay, cfg)
    marvis_poller.start()

    tray = TrayManager(app, pet)
    tray.build()

    hotkey = HotkeyManager()
    hotkey.triggered.connect(
        lambda: pet.chat_panel.toggle_visible(pet.frameGeometry())
    )
    ok = hotkey.start(str(cfg.get("hotkey", "ctrl+alt+j")))

    if cfg.get("auto_start", False) and not is_autostart():
        set_autostart(True)

    # Ollama 在线状态提示（不阻塞启动）
    def _check_ollama():
        ok_ping = pet.chat_panel.client.ping()
        if ok_ping:
            pet.chat_panel.status_label.setText("空闲 · Ollama 在线")
        else:
            pet.chat_panel.status_label.setText("Ollama 离线")
            pet.chat_panel._append("系统", "未检测到 Ollama（127.0.0.1:11434），请先启动 Ollama 服务。", "#ff7a7a")

    QTimer.singleShot(600, _check_ollama)

    code = app.exec()
    hotkey.stop()
    sys.exit(code)


if __name__ == "__main__":
    main()
