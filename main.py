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

import ctypes
import ctypes.wintypes
import html
import json
import math
import os
import random
import sys
import threading
import time

import requests

from PySide6.QtCore import (
    QAbstractNativeEventFilter,
    QObject,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QSize,
    Qt,
    QThread,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QCursor,
    QFont,
    QIcon,
    QPainter,
    QPen,
    QPixmap,
    QRadialGradient,
    QTextCursor,
    QTransform,
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
    # 窗口置顶：True=悬浮置顶（可见性优先），False=桌面层（不遮挡工作窗口）
    "pet_on_top": True,
    # 宠物形象：sprite=图片形象（真实形象/大肥鱼/小马），orb=粒子光球
    "pet_style": "sprite",
    # 形象：real=老板9张原图真实形象，fish=大肥鱼，pony=marvis 小马
    "pet_character": "pony",
    # fish 形象版本：adult=成年版，baby=幼年版（仅 fish 生效）
    "fish_version": "adult",
    # 图片形象动画刷新率（fps），默认 165（约 6ms/帧）
    "anim_fps": 165,
    # 逐帧动画播放帧率（fps）：帧序列按此速率推进，渲染仍由 anim_fps 驱动
    # 2026-10-21 由 12 提到 24：dsh-pet 素材每动作 48 帧，12fps 一轮 4 秒偏慢，
    # 24fps 一轮 2 秒更接近原始 webm 节奏。
    "anim_frame_fps": 24,
    # 空闲多久（秒）后点播一轮睡眠动作；0 = 不自动睡眠
    "sleep_after": 300,
    # token 单价估算预留：prompt_per_1k / completion_per_1k 配置后启用金额估算，
    # 保持 None 时本地模型标注"本地免费"。
    "token_price": {"prompt_per_1k": None, "completion_per_1k": None, "currency": "CNY"},
    # Marvis 状态出口：type = none | file | http | marvis
    #   - marvis: 直连本机 Marvis 应用 data.db（agent_activities / messages），
    #             桌宠实时展示 Marvis 主应用任务流程（推荐，零额外进程）
    #   - file: 轮询本地状态 JSON（含 sessions 数组）展示 Marvis 任务流程
    #   - http: 轮询 HTTP 端点（同上）
    #   - none: 不启用，降级为本地对话流程卡片
    "marvis_state_source": {"type": "marvis", "url": "", "file": "", "interval": 3000},
    # 拖拽甩抛物理（仿 dsh-pet）：gravity=重力 px/s²、restitution=碰壁恢复系数 0~1、
    # groundFriction=落地水平衰减(/s)、ceilingBounce=顶部是否反弹、throwPower=甩抛力度增益
    "physics": {"gravity": 1400, "restitution": 0.78, "groundFriction": 2.5,
                "ceilingBounce": True, "throwPower": 1.0},
    # 工作状态六档气泡文案（仿 dsh-pet workStatusTexts）：
    # 0 thinking / 1 working / 2 result / 3 waiting / 4 success / 5 error
    "work_status_texts": [
        ["正在认真想下一步呢", "让我整理一下思路~"],
        ["正在处理任务呢", "正在继续干活哦"],
        ["这一步处理好啦", "搞定一步，继续看看"],
        ["需要你确认一下呢", "轮到你来决定啦"],
        ["这一轮搞定啦", "任务完成咯"],
        ["这一步没跑通呢", "刚才的操作遇到点问题"],
    ],
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
            with open(path, "r", encoding="utf-8-sig") as f:
                user = json.load(f)
            if isinstance(user, dict):
                cfg.update({k: v for k, v in user.items() if k in DEFAULT_CONFIG})
        else:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return cfg


def save_config(cfg: dict):
    """把当前配置持久化回 config.json（仅写白名单字段，不破坏未知配置）。"""
    path = config_path()
    merged = dict(cfg)
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8-sig") as f:
                old = json.load(f)
            if isinstance(old, dict):
                merged = dict(old)
                merged.update({k: v for k, v in cfg.items() if k in DEFAULT_CONFIG})
    except Exception:
        pass
    try:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def assets_dir() -> str:
    """图片形象资源目录：源码运行取项目 assets，打包后取 PyInstaller 解包目录 assets。"""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "assets")


def probe_anim_frame_size():
    """探测逐帧素材的单帧像素尺寸（取首个动作的首帧），用于按素材宽高比开窗口。

    dsh-pet 帧为 640x360（16:9 横版）；若窗口仍开正方形，横版素材只占 82x46，
    宠物会明显偏小。返回 (w, h)；探测失败返回 None（回退正方形）。
    """
    anim_dir = os.path.join(assets_dir(), "anim")
    if not os.path.isdir(anim_dir):
        return None
    try:
        subs = [d for d in os.listdir(anim_dir)
                if os.path.isdir(os.path.join(anim_dir, d))]
        subs.sort()
        for name in subs:
            p = os.path.join(anim_dir, name, "frame_000.png")
            if not os.path.exists(p):
                continue
            # 直接读 PNG 头 IHDR（偏移 16..23 = 宽、高），零依赖、不解码整图
            with open(p, "rb") as f:
                head = f.read(24)
            if head[:8] == b"\x89PNG\r\n\x1a\n" and head[12:16] == b"IHDR":
                w = int.from_bytes(head[16:20], "big")
                h = int.from_bytes(head[20:24], "big")
                if w > 0 and h > 0:
                    return w, h
    except Exception:
        pass
    return None


_ANIM_CACHE_SIZE = None


def anim_cache_size():
    """逐帧缓存尺寸：pet_size × 素材宽高比 × 2 倍余量。

    106 动作 × 48 帧、单帧 640x360 全尺寸常驻太贵（9 个常驻动作实测约 457MB），
    加载到窗口 2 倍尺寸即可（约 1/4 内存），画质对 96~171px 的窗口绰绰有余。
    返回 (w, h)；探测失败返回 None（保持原尺寸）。结果只算一次并缓存。
    """
    global _ANIM_CACHE_SIZE
    if _ANIM_CACHE_SIZE is not None:
        return _ANIM_CACHE_SIZE or None
    res = None
    try:
        cfg = load_config()
        size = max(48, int(cfg.get("pet_size", 96)))
        fs = probe_anim_frame_size()
        if fs and fs[1]:
            ar = fs[0] / float(fs[1])
            res = (max(48, int(round(size * ar))) * 2, size * 2)
    except Exception:
        res = None
    _ANIM_CACHE_SIZE = res or False
    return res


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
    """全局热键（默认 Ctrl+Alt+J）。

    使用 Win32 WH_KEYBOARD_LL 低级键盘钩子实现（自研 ctypes，不依赖 keyboard/pynput）：
    - keyboard 库钩子在 PyInstaller 打包环境下注册成功但收不到按键（ctypes 回调失效），弃用；
    - RegisterHotKey 系统热键不受模拟输入触发，冒烟测试无法覆盖，弃用；
    - LL 钩子对真实键盘与模拟输入均生效，打包后同样可靠。
    """

    triggered = Signal()

    def __init__(self):
        super().__init__()
        self._hook = _LowLevelKeyboardHook()
        self._hook.fired.connect(self.triggered)

    def start(self, hotkey: str) -> bool:
        try:
            import ctypes
            _hook_diag("HotkeyManager.start(%r)" % hotkey)

            mods, vk = [], None
            parts = [p.strip() for p in hotkey.lower().replace("+", " ").split() if p.strip()]
            for p in parts:
                if p in ("ctrl", "control"):
                    mods.append(0x11)
                elif p == "alt":
                    mods.append(0x12)
                elif p == "shift":
                    mods.append(0x10)
                elif p in ("win", "windows", "super"):
                    mods.extend([0x5B, 0x5C])
                elif p == "space":
                    vk = 0x20
                elif len(p) == 1:
                    vk = ord(p.upper())
                elif p.startswith("f") and p[1:].isdigit():
                    vk = 0x70 + int(p[1:]) - 1
                else:
                    return False
            if vk is None:
                return False
            _hook_diag("hotkey parsed vk=%s mods=%s" % (vk, mods))
            return self._hook.start(vk, mods)
        except Exception:
            return False

    def stop(self):
        self._hook.stop()


def _hook_diag(msg: str):
    """钩子诊断日志：仅当环境变量 MARVIS_HOOK_DIAG=1 时写入 cwd 下 hook_diag.log。"""
    if os.environ.get("MARVIS_HOOK_DIAG") == "1":
        try:
            with open("hook_diag.log", "a", encoding="utf-8") as _f:
                _f.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), msg))
        except Exception:
            pass


class _LowLevelKeyboardHook(QObject):
    """WH_KEYBOARD_LL 低级键盘钩子：命中指定组合键（修饰键按下 + 目标键）时发 fired 信号。"""

    fired = Signal()
    WH_KEYBOARD_LL = 13
    WM_KEYDOWN = 0x0100
    WM_SYSKEYDOWN = 0x0104

    def __init__(self):
        super().__init__()
        self._vk = None
        self._mods = []
        self._hook = None
        self._thread = None
        self._stop = threading.Event()
        self._cb_ref = None

    def start(self, vk: int, mod_vks) -> bool:
        try:
            import ctypes
            import ctypes.wintypes
            import threading

            class KBDLLHOOKSTRUCT(ctypes.Structure):
                _fields_ = [
                    ("vkCode", ctypes.wintypes.DWORD),
                    ("scanCode", ctypes.wintypes.DWORD),
                    ("flags", ctypes.wintypes.DWORD),
                    ("time", ctypes.wintypes.DWORD),
                    ("dwExtraInfo", ctypes.c_size_t),
                ]

            HOOKPROC = ctypes.WINFUNCTYPE(
                ctypes.c_longlong, ctypes.c_int,
                ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM,
            )

            def _proc(nCode, wParam, lParam):
                try:
                    if nCode >= 0 and wParam in (self.WM_KEYDOWN, self.WM_SYSKEYDOWN):
                        kbd = KBDLLHOOKSTRUCT.from_address(lParam)
                        if kbd.vkCode == self._vk:
                            user32 = ctypes.WinDLL("user32", use_last_error=True)
                            _hook_diag("keydown vk=%s mods=%s" % (kbd.vkCode, self._mods))
                            if all(user32.GetAsyncKeyState(m) & 0x8000 for m in self._mods):
                                _hook_diag("HOTKEY FIRED -> emit")
                                self.fired.emit()
                except Exception:
                    pass
                return ctypes.WinDLL("user32", use_last_error=True).CallNextHookEx(None, nCode, wParam, lParam)

            user32 = ctypes.WinDLL("user32", use_last_error=True)
            self._vk = vk
            self._mods = list(mod_vks)
            self._stop.clear()
            self._cb_ref = HOOKPROC(_proc)
            # WH_KEYBOARD_LL 钩子的 hMod 传 NULL 即可（回调在当前进程），
            # 切勿用 GetModuleHandleW(None) —— 默认 restype 为 c_int 会截断返回值导致 err 126。
            self._hook = user32.SetWindowsHookExW(
                self.WH_KEYBOARD_LL, self._cb_ref, None, 0,
            )
            _hook_diag("SetWindowsHookExW ret=%s err=%s" % (self._hook, ctypes.get_last_error()))
            if not self._hook:
                self._cb_ref = None
                _hook_diag("hook install failed")
                return False

            def _msg_loop():
                import ctypes.wintypes

                msg = ctypes.wintypes.MSG()
                while not self._stop.is_set():
                    r = user32.GetMessageW(ctypes.byref(msg), 0, 0, 0)
                    if r in (0, -1):
                        break
                    user32.TranslateMessage(ctypes.byref(msg))
                    user32.DispatchMessageW(ctypes.byref(msg))

            self._thread = threading.Thread(target=_msg_loop, daemon=True)
            self._thread.start()
            return True
        except Exception:
            return False

    def stop(self):
        try:
            import ctypes

            self._stop.set()
            if self._hook:
                user32 = ctypes.WinDLL("user32", use_last_error=True)
                user32.UnhookWindowsHookEx(self._hook)
                self._hook = None
            if self._thread is not None and self._thread.ident:
                ctypes.WinDLL("user32", use_last_error=True).PostThreadMessageW(
                    self._thread.ident, 0x0012, 0, 0
                )
                self._thread = None
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
            Qt.FramelessWindowHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus
            | (Qt.WindowStaysOnTopHint if self.pet._on_top else Qt.WindowStaysOnBottomHint)
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
        if t in ("file", "http", "marvis"):
            self._timer.start(int(self.source.get("interval") or 3000))

    def stop(self):
        self._timer.stop()

    def _poll(self):
        try:
            t = str(self.source.get("type") or "none")
            if t == "marvis":
                data = self._query_marvis_db()
            elif t == "file":
                path = self.source.get("file") or ""
                if not path or not os.path.exists(path):
                    self.overlay.clear_marvis_sessions()
                    return
                with open(path, "r", encoding="utf-8-sig") as f:
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

    @staticmethod
    def _query_marvis_db() -> dict:
        """直连本机 Marvis 应用 data.db，把 agent_activities / messages 映射为任务卡片。

        状态判定（全为只读查询，绝不写库）：
        - 最近 3 分钟内有子 Agent 活动 → 出卡片（completed+success=done，
          completed+failed=failed，其余=thinking），标题为 agent 名、内容为汇报摘要；
        - 最近 60 秒内有 user 消息且最新消息仍是 user → thinking（等待处理中）；
        - 最近 3 分钟无任何活动 → 返回空 sessions（桌宠回 idle）。
        """
        sessions: list = []
        base = os.path.join(os.environ.get("APPDATA", ""), "Tencent", "Marvis", "User")
        db_path = ""
        if os.path.isdir(base):
            best = None
            for uid in os.listdir(base):
                p = os.path.join(base, uid, "database", "data.db")
                if os.path.exists(p):
                    mtime = os.path.getmtime(p)
                    if best is None or mtime > best[1]:
                        best = (p, mtime)
            db_path = best[0] if best else ""
        if not db_path or not os.path.exists(db_path):
            return {"sessions": []}
        import sqlite3
        from datetime import datetime, timedelta, timezone
        con = sqlite3.connect("file:" + db_path.replace("\\", "/") + "?mode=ro",
                              uri=True, timeout=2)
        try:
            cur = con.cursor()
            # 最近活动（agent_activities.activity_time 为本地时间，可直接与本地 now 比较）
            now = datetime.now()
            cutoff_act = (now - timedelta(seconds=180)).strftime("%Y-%m-%dT%H:%M:%S")
            rows = cur.execute(
                "SELECT id, agent_name, content, status, outcome_status, activity_time"
                " FROM agent_activities WHERE activity_time >= ?"
                " ORDER BY activity_time DESC LIMIT 3", (cutoff_act,)
            ).fetchall()
            for rid, aname, content, status, outcome, atime in rows:
                if status == "completed" and outcome == "success":
                    state = "done"
                elif status == "completed" and outcome == "failed":
                    state = "failed"
                else:
                    state = "thinking"
                detail = (content or "").strip().replace("\n", " ")
                if len(detail) > 42:
                    detail = detail[:42] + "…"
                sessions.append({
                    "id": f"act-{rid}",
                    "title": aname or "Marvis",
                    "state": state,
                    "detail": detail,
                })
            # 最近消息兜底：60s 内有 user 消息且最新消息仍是 user → 等待处理
            cutoff_msg = (datetime.now(timezone.utc) - timedelta(seconds=60)).strftime("%Y-%m-%dT%H:%M:%S")
            last = cur.execute(
                "SELECT role, created_at FROM messages WHERE created_at >= ?"
                " ORDER BY created_at DESC LIMIT 1", (cutoff_msg,)
            ).fetchone()
            if last and last[0] == "user" and not sessions:
                sessions.append({
                    "id": "msg-waiting",
                    "title": "Marvis",
                    "state": "thinking",
                    "detail": "正在处理你的消息",
                })
        finally:
            con.close()
        return {"sessions": sessions}


# ---------------------------------------------------------------------------
# 图片形象（双形象 sprite 模式）
# ---------------------------------------------------------------------------

# 双形象：状态 -> assets 图片文件名
# 大肥鱼形象版本：adult=成年版（图1-2），baby=幼年版（图3-9），各 4 态表情素材
FISH_VERSIONS = {
    # 素材 = dsh-pet 蓝发小女仆（大肥鱼）形象四态；baby 暂无独立帧，先复用 adult
    "adult": {
        "idle": "fish_idle.png",
        "thinking": "fish_thinking.png",
        "replying": "fish_replying.png",
        "error": "fish_error.png",
    },
    "baby": {
        "idle": "fish_idle.png",
        "thinking": "fish_thinking.png",
        "replying": "fish_replying.png",
        "error": "fish_error.png",
    },
}
CHARACTER_STATES = {
    "fish": FISH_VERSIONS["adult"],  # 动态引用，实际按 fish_version 选择
    "pony": {
        "idle": "pony_idle.png",
        "thinking": "pony_thinking.png",
        "replying": "pony_replying.png",
        "error": "pony_error.png",
    },
    # 真实形象（老板 9 张原图重制）：四态单贴图兜底，逐帧动画走 anim/real_<state>/
    "real": {
        "idle": "real_idle.png",
        "thinking": "real_thinking.png",
        "replying": "real_replying.png",
        "error": "real_error.png",
    },
}
CHARACTER_NAMES = {"fish": "大肥鱼", "pony": "marvis 小马", "real": "真实形象"}
FISH_VERSION_NAMES = {"adult": "成年版", "baby": "幼年版"}

# 逐帧动画：状态 -> 动作序列（assets/anim/<action>/frame_000.png...）。
# 动作名直接对齐 dsh-pet assets/webm 素材名（已全量抽帧为透明 PNG）。
# idle 支持多动作轮播；error 有专属帧（被吓一跳）但保留抖动叠加。
ANIM_ACTIONS = {
    "idle": ["待机呼吸休闲", "东张西望", "原地漂浮踏步", "悠闲哼歌"],  # 发呆漂浮/张望/漂浮踏步/哼歌 轮播
    "thinking": ["深度思考碎碎念", "工作状态-思考冒泡"],
    "replying": ["轻快记录", "工作状态-忙碌点按"],
    "error": ["被吓一跳"],
}

# 余额（钱袋）分档：按**本次会话累计消耗的 prompt token** 映射 dsh-pet 的六个钱袋动作。
# 本地 Ollama 是"本地免费"，没有真余额；这里用"烧掉的 token 越多 → 袋子越瘪"作隐喻。
# 阈值单位 = prompt token 累计；跨档时点播一轮对应动作。
BALANCE_TIERS = [
    (2000,    "余额-钱袋满溢"),
    (8000,    "余额-金袋叮当"),
    (20000,   "余额-钱袋如常"),
    (50000,   "余额-数金皱眉"),
    (100000,  "余额-袋空如洗"),
]

# 空闲睡眠：idle 且长时间无交互 → 点播一轮（播完自动回 idle，下次超时再播）
SLEEP_ACTIONS = ["哈欠连天", "原地小憩沉眠"]


class PetSprite:
    """图片形象渲染器：加载 4 态表情 QPixmap 与逐帧动画序列，
    按动画相位计算 上下浮动 / 左右摇摆 / 呼吸缩放 / 状态特效
    （思考晃、回复跳、出错抖），叠加在帧动画之上作为微动。"""

    def __init__(self, character: str, fish_version: str = "adult",
                 frame_fps: float = 12.0):
        self.character = character if character in CHARACTER_STATES else "fish"
        self.fish_version = fish_version if fish_version in FISH_VERSIONS else "adult"
        self.frame_fps = max(1.0, float(frame_fps))
        self._pixmaps: dict[str, QPixmap] = {}
        self._frames: dict[str, list[QPixmap]] = {}
        self._override = None  # 点播单动作（仿 dsh-pet 右键点播）：动作名或 None
        self._override_t0 = 0.0
        self._pooled_actions = set()  # 常驻挂载动作名（ANIM_ACTIONS），点播动作播完即卸载
        self._load()

    def _fit(self, pix: QPixmap) -> QPixmap:
        """把原帧缩到缓存尺寸（窗口 2 倍）以控内存：9 常驻动作 457MB → 约 130MB。"""
        if pix.isNull():
            return pix
        sz = anim_cache_size()
        if not sz:
            return pix
        cw, ch = sz
        if pix.width() <= cw and pix.height() <= ch:
            return pix
        return pix.scaled(cw, ch, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    def _load_frames(self):
        """从 assets/anim/<action>/frame_000.png... 加载逐帧序列。

        fish 形象使用全局 ANIM_ACTIONS 动作池；
        real 形象按状态加载 assets/anim/real_<state>/frame_000.png...。
        """
        self._frames = {}
        self._pooled_actions = set()
        anim_dir = os.path.join(assets_dir(), "anim")
        if not os.path.isdir(anim_dir):
            return
        if self.character == "real":
            for state in ("idle", "thinking", "replying", "error"):
                seq = []
                for i in range(100):
                    p = os.path.join(anim_dir, f"real_{state}", f"frame_{i:03d}.png")
                    if not os.path.exists(p):
                        break
                    pix = QPixmap(p)
                    if not pix.isNull():
                        seq.append(pix)
                if seq:
                    self._frames[f"real_{state}"] = seq
        elif self.character == "fish":
            for actions in ANIM_ACTIONS.values():
                for action in actions:
                    if action in self._frames:
                        continue
                    seq = []
                    for i in range(100):
                        p = os.path.join(anim_dir, action, f"frame_{i:03d}.png")
                        if not os.path.exists(p):
                            break
                        pix = QPixmap(p)
                        if not pix.isNull():
                            seq.append(self._fit(pix))
                    if seq:
                        self._frames[action] = seq
                        self._pooled_actions.add(action)
        if os.environ.get("MARVIS_PET_DIAG"):
            with open(f"pet_diag_{os.getpid()}.log", "a", encoding="utf-8") as _df:
                _df.write(f"[diag] frames: " +
                          ", ".join(f"{k}={len(v)}" for k, v in self._frames.items()) + "\n")

    def _pick_frame(self, state: str, t: float) -> QPixmap | None:
        """按累计时间 t 与 frame_fps 取当前动作帧；idle 多动作轮播。

        点播（override）：有素材则播放一轮后自动清除回退 idle；无素材静默回退。
        """
        if self._override is not None:
            pool = self._frames.get(self._override, [])
            if pool:
                remaining = (t - self._override_t0) * self.frame_fps
                if remaining >= len(pool):
                    self._finish_override()
                else:
                    return pool[int(remaining)]
            else:
                self._finish_override()
        if self.character == "real":
            actions = [f"real_{state}"] if state in ("idle", "thinking", "replying", "error") else []
        else:
            actions = ANIM_ACTIONS.get(state)
        if not actions:
            return None
        pool: list[QPixmap] = []
        for a in actions:
            pool.extend(self._frames.get(a, []))
        if not pool:
            return None
        idx = int(t * self.frame_fps) % len(pool)
        return pool[idx]

    def play_once(self, action: str, t0: float):
        """点播单动作：有逐帧素材则播放一轮（用调用方时间基准 t0 对齐）。
        未常驻挂载的动作（如右键点播的任意 dsh-pet 动作）即时从磁盘加载，
        播放一轮后自动卸载释放内存。"""
        pool = self._frames.get(action)
        if not pool:
            pool = self._load_action_frames(action)
        if pool:
            self._override = action
            self._override_t0 = t0
        else:
            self._override = None

    def _load_action_frames(self, action: str) -> list[QPixmap]:
        """按动作名从磁盘加载逐帧序列（assets/anim/<action>/frame_000.png...）。"""
        anim_dir = os.path.join(assets_dir(), "anim")
        if not os.path.isdir(anim_dir):
            return []
        seq = []
        for i in range(100):
            p = os.path.join(anim_dir, action, f"frame_{i:03d}.png")
            if not os.path.exists(p):
                break
            pix = QPixmap(p)
            if not pix.isNull():
                seq.append(self._fit(pix))
        if seq:
            self._frames[action] = seq
        return seq

    def _finish_override(self):
        """点播结束：清除 override；非常驻动作从缓存卸载，避免 106 个动作全量常驻。"""
        a = self._override
        self._override = None
        if a and a not in self._pooled_actions:
            self._frames.pop(a, None)

    def _load(self):
        states = CHARACTER_STATES[self.character]
        if self.character == "fish":
            states = FISH_VERSIONS[self.fish_version]
        if os.environ.get("MARVIS_PET_DIAG"):
            with open(f"pet_diag_{os.getpid()}.log", "a", encoding="utf-8") as _df:
                _df.write(f"[diag] assets_dir={assets_dir()} character={self.character} version={self.fish_version}\n")
                for state, fname in states.items():
                    p = os.path.join(assets_dir(), fname)
                    pix = QPixmap(p)
                    _df.write(f"[diag] load {state}: {p} null={pix.isNull()}\n")
        for state, fname in states.items():
            pix = QPixmap(os.path.join(assets_dir(), fname))
            if not pix.isNull():
                self._pixmaps[state] = pix
        self._load_frames()
        if os.environ.get("MARVIS_PET_DIAG"):
            with open(f"pet_diag_{os.getpid()}.log", "a", encoding="utf-8") as _df:
                _df.write(f"[diag] loaded states: {sorted(self._pixmaps.keys())}\n")

    def set_fish_version(self, version: str):
        """fish 形象切换幼年/成年版，重新加载素材（仅 fish 生效）。"""
        if self.character != "fish" or version not in FISH_VERSIONS:
            return
        self.fish_version = version
        self._pixmaps.clear()
        self._load()

    def has_image(self, state: str) -> bool:
        return state in self._pixmaps

    def pixmap(self, state: str) -> QPixmap | None:
        # 表情缺失时回退到 idle，保证任何状态都能渲染
        return self._pixmaps.get(state) or self._pixmaps.get("idle")

    def paint(self, painter: QPainter, w: int, h: int, state: str,
              t: float, snapped: bool, error_dt: float = 0.0):
        """在 (w,h) 画布内绘制当前形象。t=累计动画秒数；snapped=贴边收纳。"""
        # 逐帧动画优先：有帧序列时用帧图，否则回退四态单贴图
        frame_pix = self._pick_frame(state, t)
        pix = frame_pix if frame_pix is not None else self.pixmap(state)
        if pix is None:
            return
        pix_w, pix_h = pix.width(), pix.height()
        if pix_w <= 0 or pix_h <= 0:
            return
        if snapped:
            # 贴边收纳：绘制缩小图标，跟随状态色
            side = min(w, h)
            target = QPixmap(pix).scaled(
                max(6, side * 2 // 3), max(6, side * 2 // 3),
                Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            painter.setOpacity(0.85)
            painter.drawPixmap(
                int((w - target.width()) / 2), int((h - target.height()) / 2), target
            )
            return

        # ---- 程序化动画参数（time-based，dt 驱动，与帧率解耦）----
        # 上下浮动（0.5Hz 正弦，幅度随状态变化）
        float_amp = 3.0
        # 左右摇摆（0.3Hz 正弦，绕中心小角度旋转）
        swing_amp = 4.0
        # 呼吸缩放
        breath_amp = 0.03
        if state == "thinking":
            float_amp = 4.5
            swing_amp = 8.0
            breath_amp = 0.05
        elif state == "replying":
            float_amp = 5.5
            swing_amp = 3.0
            breath_amp = 0.07
        elif state == "error":
            float_amp = 3.0
            swing_amp = 5.0
            breath_amp = 0.04

        fy = math.sin(t * math.tau * 0.5) * float_amp
        rot = math.sin(t * math.tau * 0.3) * swing_amp
        scale = 1.0 + breath_amp * math.sin(t * math.tau * 0.8)
        # 出错抖动：叠加高频偏移
        jx = 0.0
        jy = 0.0
        if state == "error":
            jx = math.sin(t * math.tau * 8.0) * 1.8
            jy = math.cos(t * math.tau * 9.0) * 1.8

        # 目标绘制尺寸：贴合窗口，留出动画余量
        draw_w = int(min(w, h) * 0.86 * scale)
        draw_h = int(draw_w * pix_h / pix_w)
        scaled = QPixmap(pix).scaled(
            draw_w, draw_h, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )

        painter.save()
        painter.translate(w / 2 + jx, h / 2 + fy + jy)
        painter.rotate(rot)
        painter.setOpacity(1.0)
        painter.drawPixmap(
            int(-scaled.width() / 2), int(-scaled.height() / 2), scaled
        )
        painter.restore()


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
        # 图片形象模式（双形象 / 粒子光球）
        self.style = str(cfg.get("pet_style", "sprite"))
        self.character = str(cfg.get("pet_character", "fish"))
        self.fish_version = str(cfg.get("fish_version", "adult"))
        self.sprite = PetSprite(self.character, self.fish_version,
                                float(cfg.get("anim_frame_fps", 12)))
        # time-based 动画：_anim_t 累计秒数，_last_tick 上一帧时间戳
        self._anim_t = 0.0
        self._last_tick = time.monotonic()
        # 事件气泡（done! / oops / hey!）
        self._bubble = None  # {"text":..., "color":QColor, "start":float, "duration":float}
        self._bubble_timer = QTimer(self)
        self._bubble_timer.timeout.connect(self._bubble_tick)
        self._bubble_timer.start(40)
        # 甩抛物理（仿 dsh-pet）：松手时按拖拽速度抛掷，重力下落 + 碰壁反弹 + 落地摩擦
        self._phys_vx = 0.0
        self._phys_vy = 0.0
        self._phys_last_t = 0.0
        self._phys_active = False
        self._phys_timer = QTimer(self)
        self._phys_timer.timeout.connect(self._physics_tick)
        self._phys_timer.start(20)
        # 拖拽测速（用于甩抛初速）
        self._drag_last_ts = 0.0
        self._drag_last_global = QPoint()
        self._drag_vel = QPointF(0.0, 0.0)

        self.setWindowTitle(PET_TITLE)
        # 位置策略：默认桌面层（WindowStaysOnBottomHint，不遮挡工作窗口）；
        # 托盘/配置可切换为置顶悬浮（WindowStaysOnTopHint）。
        self._on_top = bool(self.cfg.get("pet_on_top", False))
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus
            | (Qt.WindowStaysOnTopHint if self._on_top else Qt.WindowStaysOnBottomHint)
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_DeleteOnClose, False)

        size = max(48, int(cfg.get("pet_size", 96)))
        self._pet_size = size
        # 按逐帧素材真实宽高比开窗口（dsh-pet 帧为 640x360 横版）：
        # 高度保持 pet_size，宽度按宽高比放大，避免横版素材被挤成小图。
        self._pet_w, self._pet_h = size, size
        _fs = probe_anim_frame_size()
        if _fs and _fs[0] > 0 and _fs[1] > 0:
            ar = _fs[0] / float(_fs[1])
            if 1.05 < ar < 4.0:
                self._pet_w = max(48, int(round(size * ar)))
        self.setFixedSize(self._pet_w, self._pet_h)
        try:
            self.setWindowOpacity(float(cfg.get("opacity", 0.95)))
        except Exception:
            pass

        self._build_particles()

        # 初始位置：屏幕右下角附近
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.right() - self._pet_w - 80, screen.bottom() - self._pet_h - 80)

        # 动画刷新：图片形象按 anim_fps（默认 165fps ≈ 6ms/帧）高精度定时驱动；
        # 动画参数为 time-based，即使定时器实际触发频率有抖动，运动速率也保持恒定。
        try:
            fps = max(30, int(cfg.get("anim_fps", 165)))
        except (TypeError, ValueError):
            fps = 165
        self._anim_timer = QTimer(self)
        self._anim_timer.setTimerType(Qt.PreciseTimer)
        self._anim_timer.timeout.connect(self._tick)
        self._anim_timer.start(max(1, int(1000 / fps)))

        # 边缘触碰检测（收纳时自动展开）
        self._edge_timer = QTimer(self)
        self._edge_timer.timeout.connect(self._check_edge_hover)
        self._edge_timer.start(200)

        # 空闲睡眠：idle 且无交互超过 sleep_after 秒 → 点播一轮睡眠动作（仿 dsh-pet）
        self._last_activity = time.time()
        self._sleep_idx = 0
        self._sleep_timer = QTimer(self)
        self._sleep_timer.timeout.connect(self._check_sleep)
        self._sleep_timer.start(10000)

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
        if state != "idle":
            self._last_activity = time.time()  # 非空闲 = 有活动，推迟睡眠
        self.update()

    # ----- 空闲睡眠 -----
    def mark_activity(self):
        """任何交互（点击/拖拽/对话/任务）都调用：重置空闲计时，唤醒。"""
        self._last_activity = time.time()

    def _check_sleep(self):
        if self.state != "idle" or self._snapped or self._override_active():
            return
        try:
            after = float(self.cfg.get("sleep_after", 300))
        except (TypeError, ValueError):
            after = 300.0
        if after <= 0:
            return
        if time.time() - self._last_activity >= after:
            action = SLEEP_ACTIONS[self._sleep_idx % len(SLEEP_ACTIONS)]
            self._sleep_idx += 1
            self._last_activity = time.time()
            self.sprite.play_once(action, self._anim_t)
            self.update()

    def _override_active(self) -> bool:
        return getattr(self.sprite, "_override", None) is not None

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
        now = time.monotonic()
        dt = min(0.1, max(0.0, now - self._last_tick))
        self._last_tick = now
        self._anim_t += dt
        # 粒子光球动画按原 30ms/帧 节奏缩放，避免因帧率提升而加速
        ratio = dt / 0.03
        self._angle += 0.05 * ratio
        self._pulse += 0.12 * ratio
        self.update()

    # ----- 形象 / 风格切换 -----
    def set_character(self, character: str):
        """切换形象（real / fish / pony），即时生效。"""
        if character not in CHARACTER_STATES:
            return
        self.character = character
        self.sprite = PetSprite(character, self.fish_version,
                                self.sprite.frame_fps)
        self.update()

    def set_fish_version(self, version: str):
        """切换大肥鱼幼年/成年版（仅 fish 形象生效），即时生效。"""
        if version not in FISH_VERSIONS:
            return
        if self.character != "fish":
            return
        self.fish_version = version
        self.sprite.set_fish_version(version)
        self.update()

    def set_style(self, style: str):
        """切换渲染风格（sprite 图片形象 / orb 粒子光球），即时生效。"""
        if style not in ("sprite", "orb"):
            return
        self.style = style
        self.update()

    def set_on_top(self, on_top: bool):
        """切换置顶/桌面层（默认桌面层，不遮挡工作窗口），即时生效。

        on_top=False：窗口置于普通窗口之下（桌面层），不遮挡用户工作窗口；
        on_top=True：置顶悬浮（旧版行为），供需要盯着桌宠时切换。
        """
        self._on_top = bool(on_top)
        flags = (
            Qt.FramelessWindowHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus
            | (Qt.WindowStaysOnTopHint if self._on_top else Qt.WindowStaysOnBottomHint)
        )
        self.setWindowFlags(flags)  # 可见窗口会自动 hide，随后 show 应用新层级
        self.show()
        if self._on_top:
            self.raise_()
        if getattr(self, "overlay", None) is not None:
            self.overlay.setWindowFlags(flags)
            self.overlay.show()
        # Qt 的 WindowStaysOnTopHint 在 Tool 窗口上可能只更新内部 flag 而不映射到
        # Windows WS_EX_TOPMOST，这里用 Win32 SetWindowPos 强制应用真实 Z 层级。
        self._force_win32_topmost(int(self.winId()), self._on_top)
        if getattr(self, "overlay", None) is not None and self.overlay.isVisible():
            self._force_win32_topmost(int(self.overlay.winId()), self._on_top)
        self.update()

    @staticmethod
    def _force_win32_topmost(hwnd: int, on_top: bool) -> int:
        """用 SetWindowPos 强制置顶/取消置顶，返回 Win32 调用结果。"""
        user32 = ctypes.windll.user32
        if not user32.SetWindowPos.argtypes:
            user32.SetWindowPos.argtypes = [
                ctypes.wintypes.HWND, ctypes.wintypes.HWND,
                ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint,
            ]
            user32.SetWindowPos.restype = ctypes.c_int
        HWND_TOPMOST = ctypes.c_void_p(-1)
        HWND_NOTOPMOST = ctypes.c_void_p(-2)
        SWP_NOSIZE = 0x0001
        SWP_NOMOVE = 0x0002
        SWP_NOACTIVATE = 0x0010
        target = HWND_TOPMOST if on_top else HWND_NOTOPMOST
        return user32.SetWindowPos(
            ctypes.wintypes.HWND(hwnd), target, 0, 0, 0, 0,
            SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE,
        )

    # ----- 绘制 -----
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if self._snapped:
            self._paint_bar(painter)
            if self.style == "sprite":
                self._paint_sprite(painter)
        elif self.style == "sprite":
            self._paint_sprite(painter)
        else:
            self._paint_orb(painter)
        self._paint_bubble(painter)

    def _paint_sprite(self, painter: QPainter):
        self.sprite.paint(
            painter, self.width(), self.height(),
            self.state, self._anim_t, self._snapped,
        )
        if os.environ.get("MARVIS_PET_DIAG"):
            with open(f"pet_diag_{os.getpid()}.log", "a", encoding="utf-8") as _df:
                _df.write(f"[diag] paint state={self.state} t={self._anim_t:.3f} snapped={self._snapped} "
                          f"has_idle={self.sprite.has_image('idle')} size={self.width()}x{self.height()}\n")

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

    # ----- 鼠标拖拽 + 甩抛物理 -----
    # 甩抛初速估算：移植 dsh-pet src/shared/physics.ts 同款算法
    # （轨迹窗口采样 → 端点均值+峰值加权 → 加速增益 → 软钳速 3600 封顶 → 死区 500）
    _TRAIL_KEEP_MS = 200.0
    _RELEASE_WINDOW_MS = 150.0
    _RELEASE_STALE_MS = 150.0
    _MIN_SPAN_MS = 20.0
    _SEG_MIN_DT_MS = 8.0
    _DEAD_ZONE_SPEED = 500.0
    _MAX_THROW_SPEED = 3600.0
    _PEAK_WEIGHT = 0.5
    _ACCEL_REF = 8000.0
    _ACCEL_GAIN_MAX = 0.6
    # 拖拽弹簧（dsh-pet springStep 同款）：刚度 200、阻尼 30，过阻尼不 overshoot
    _SPRING_K = 200.0
    _SPRING_C = 30.0
    # 落地停竖速度阈值（px/s）：|vy| 小于它直接停竖直，不再反弹
    _REST_VY = 40.0
    # 静止水平速度阈值（px/s）：贴地且 |vx| 小于它认为已静止
    _REST_VX = 15.0

    @staticmethod
    def _soft_clamp_speed(speed: float) -> float:
        if speed <= 0:
            return 0.0
        return PetWindow._MAX_THROW_SPEED * (1 - math.exp(-speed / PetWindow._MAX_THROW_SPEED))

    @classmethod
    def _estimate_release_velocity(cls, trail, now: float, power: float = 1.0):
        """由拖拽轨迹估算松手初速 (vx, vy)，px/s；温柔放下返回 None。"""
        if not trail:
            return None
        last = trail[-1]
        if now - last[0] > cls._RELEASE_STALE_MS:
            return None
        win = [s for s in trail if now - s[0] <= cls._RELEASE_WINDOW_MS]
        if len(win) < 2:
            return None
        t0, x0, y0 = win[0]
        t1, x1, y1 = win[-1]
        span_ms = t1 - t0
        if span_ms < cls._MIN_SPAN_MS:
            return None
        base_vx = (x1 - x0) / span_ms * 1000.0
        base_vy = (y1 - y0) / span_ms * 1000.0
        base_speed = math.hypot(base_vx, base_vy)
        if base_speed < 1e-6:
            return None
        # 分段速度（过密采样向前合并，dt 下限 SEG_MIN_DT_MS）
        seg = []
        px, py, pt = x0, y0, t0
        for s in win[1:]:
            dt = s[0] - pt
            if dt >= cls._SEG_MIN_DT_MS:
                seg.append(((math.hypot(s[1] - px, s[2] - py) / dt) * 1000.0, s[0]))
                px, py, pt = s[1], s[2], s[0]
        peak = max((v for v, _ in seg), default=base_speed)
        # 末段加速度（仍在加速的甩动放大初速，最多 60%）
        accel = 0.0
        if len(seg) >= 2:
            accel = (seg[-1][0] - seg[0][0]) / max((seg[-1][1] - seg[0][1]) / 1000.0, cls._MIN_SPAN_MS / 1000.0)
        sp_before = ((1 - cls._PEAK_WEIGHT) * base_speed + cls._PEAK_WEIGHT * peak) * (
            1 + min(max(accel, 0.0) / cls._ACCEL_REF, 1.0) * cls._ACCEL_GAIN_MAX)
        speed = cls._soft_clamp_speed(sp_before) * power
        if speed < cls._DEAD_ZONE_SPEED:
            return None
        return (base_vx / base_speed * speed, base_vy / base_speed * speed)

    def mousePressEvent(self, e):
        self.mark_activity()  # 交互唤醒：重置空闲睡眠计时
        if e.button() == Qt.LeftButton:
            self._stop_physics()
            self._dragging = True
            self._drag_offset = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            # 轨迹时间戳统一用毫秒（与 dsh-pet 采样窗口常量同单位，避免秒/毫秒混用放大初速）
            self._drag_last_ts = time.monotonic() * 1000.0
            gp = e.globalPosition().toPoint()
            self._drag_trail = [(self._drag_last_ts, gp.x(), gp.y())]
            self._drag_last_global = e.globalPosition().toPoint()
            # 拖拽弹簧初速（dsh-pet springStep）：按下时从 0 开始积累
            self._spring_vx = 0.0
            self._spring_vy = 0.0

    def mouseMoveEvent(self, e):
        if self._dragging:
            now = time.monotonic() * 1000.0
            gp = e.globalPosition().toPoint()
            # 追加轨迹采样点（保留最近 200ms，供甩抛初速估算；采样用鼠标绝对坐标，同 dsh-pet）
            self._drag_trail.append((now, gp.x(), gp.y()))
            cutoff = now - PetWindow._TRAIL_KEEP_MS
            self._drag_trail = [s for s in self._drag_trail if s[0] >= cutoff]
            # 弹簧跟手（dsh-pet springStep 同款）：宠物不直接贴鼠，过阻尼弹簧追目标
            # v += ((target - x) * K - v * C) * power * dt;  x += v * dt
            phys = self.cfg.get("physics", {})
            power = float(phys.get("throwPower", 1.0))
            dt = max(1e-4, (now - self._drag_last_ts) / 1000.0)
            target = gp - self._drag_offset
            pos = self.frameGeometry().topLeft()
            self._spring_vx += ((target.x() - pos.x()) * PetWindow._SPRING_K
                                - self._spring_vx * PetWindow._SPRING_C) * power * dt
            self._spring_vy += ((target.y() - pos.y()) * PetWindow._SPRING_K
                                - self._spring_vy * PetWindow._SPRING_C) * power * dt
            nx = pos.x() + self._spring_vx * dt
            ny = pos.y() + self._spring_vy * dt
            self.move(int(nx), int(ny))
            self._drag_last_ts = now
            self._drag_last_global = gp

    def mouseReleaseEvent(self, e):
        if self._dragging:
            self._dragging = False
            phys = self.cfg.get("physics", {})
            power = float(phys.get("throwPower", 1.0))
            # 初速估算用毫秒时间戳（与轨迹采样同单位）；物理循环仍用秒
            now = time.monotonic() * 1000.0
            v = PetWindow._estimate_release_velocity(self._drag_trail, now, power)
            if v is not None:
                # 达到甩抛阈值：抛掷（dsh-pet 同款初速估算 + 软钳速封顶）
                self._phys_vx, self._phys_vy = v
                # 物理循环时间戳用秒（与 _physics_tick 同单位，避免首帧 dt 异常）
                self._phys_last_t = time.monotonic()
                self._phys_active = True
            else:
                self._maybe_snap()

    # ----- 甩抛物理循环（重力 / 碰壁反弹 / 落地摩擦）-----
    def _physics_tick(self):
        if not self._phys_active:
            return
        phys = self.cfg.get("physics", {})
        g = float(phys.get("gravity", 1400))
        rest = float(phys.get("restitution", 0.78))
        friction = float(phys.get("groundFriction", 2.5))
        ceiling = bool(phys.get("ceilingBounce", True))
        now = time.monotonic()
        dt = min(0.05, max(0.001, now - self._phys_last_t))
        self._phys_last_t = now
        self._phys_vy += g * dt
        geom = self.frameGeometry()
        nx = geom.x() + self._phys_vx * dt
        ny = geom.y() + self._phys_vy * dt
        screen = QApplication.primaryScreen().availableGeometry()
        w, h = self.width(), self.height()
        if nx <= screen.left():
            nx = screen.left()
            self._phys_vx = abs(self._phys_vx) * rest
        elif nx + w >= screen.right():
            nx = screen.right() - w
            self._phys_vx = -abs(self._phys_vx) * rest
        if ny <= screen.top():
            ny = screen.top()
            self._phys_vy = abs(self._phys_vy) * rest if ceiling else 0.0
        elif ny + h >= screen.bottom():
            ny = screen.bottom() - h
            # dsh-pet 落地停竖：|vy| < REST_VY(40) 直接停竖直，否则弹性反弹
            if abs(self._phys_vy) < PetWindow._REST_VY:
                self._phys_vy = 0.0
            else:
                self._phys_vy = -abs(self._phys_vy) * rest
            self._phys_vx *= max(0.0, 1.0 - friction * dt)
        speed = (self._phys_vx ** 2 + self._phys_vy ** 2) ** 0.5
        # dsh-pet 静止判定：贴地且 |vy|<1、|vx|<REST_VX(15)；或碰边后整体低速直接停
        grounded = ny + h >= screen.bottom() - 1
        if (grounded and abs(self._phys_vy) < 1.0 and abs(self._phys_vx) < PetWindow._REST_VX) or \
           (speed < PetWindow._REST_VY and abs(self._phys_vy) < 1.0):
            self._stop_physics()
            self._maybe_snap()
            return
        self.move(int(nx), int(ny))

    def _stop_physics(self):
        self._phys_active = False

    # ----- 右键菜单（仿 dsh-pet：点播动作 / 工作状态 / 切换形象 / 置顶 / 退出）-----
    def contextMenuEvent(self, e):
        menu = QMenu(self)
        anim_menu = menu.addMenu("点播动作")
        anim_dir = os.path.join(assets_dir(), "anim")
        anim_actions = []
        if os.path.isdir(anim_dir):
            anim_actions = sorted(d for d in os.listdir(anim_dir)
                                  if os.path.isdir(os.path.join(anim_dir, d)))
        for action in anim_actions:
            anim_menu.addAction(action, lambda a=action: self._play_action(a))
        ws_menu = menu.addMenu("工作状态")
        for idx, lab in enumerate(("思考中", "工作中", "一步完成", "等你确认", "完成", "出错")):
            ws_menu.addAction(lab, lambda i=idx: self._set_work_status(i))
        menu.addSeparator()
        char_menu = menu.addMenu("切换形象")
        for key, name in CHARACTER_NAMES.items():
            char_menu.addAction(name, lambda k=key: self.set_character(k))
        menu.addAction("取消置顶" if self._on_top else "置顶显示",
                       lambda: self.set_on_top(not self._on_top))
        menu.addSeparator()
        menu.addAction("退出", QApplication.instance().quit)
        menu.exec(e.globalPos())

    def _play_action(self, action: str):
        """点播单动作：有逐帧素材播放一轮后回 idle；无素材仅回 idle。"""
        if action in ANIM_ACTIONS.get("idle", []):
            self.state = "idle"
        self.sprite.play_once(action, self._anim_t)
        self.update()

    def _set_work_status(self, idx: int):
        """工作状态六档气泡（仿 dsh-pet workStatusTexts），并切对应 4 态贴图。"""
        texts = self.cfg.get("work_status_texts", [])
        pool = texts[idx] if 0 <= idx < len(texts) else []
        state_map = {0: "thinking", 1: "thinking", 2: "replying", 3: "idle", 4: "idle", 5: "error"}
        self.state = state_map.get(idx, "idle")
        if pool:
            self.add_bubble(random.choice(pool))
        self.update()

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
        # setFixedSize 会阻止 setGeometry 改变尺寸，压扁前必须先解除固定尺寸
        self.setFixedSize(bar_w, geom.height())
        if side == "left":
            self.setGeometry(QRect(screen.left(), geom.top(), bar_w, geom.height()))
        else:
            self.setGeometry(QRect(screen.right() - bar_w, geom.top(), bar_w, geom.height()))
        self.update()

    def _expand(self):
        if self._snapped:
            self._snapped = False
            if not self._restore_rect.isNull():
                self.setFixedSize(getattr(self, "_pet_w", self._pet_size),
                                  getattr(self, "_pet_h", self._pet_size))
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
        before = self._session_usage["prompt"]
        self._session_usage["prompt"] += p
        self._session_usage["eval"] += e
        self._update_token_label(p, e)
        self._check_balance_tier(before, self._session_usage["prompt"])

    def _check_balance_tier(self, before: int, after: int):
        """累计 prompt token 跨过余额分档阈值 → 点播对应钱袋动作一轮（仿 dsh-pet）。"""
        pet = getattr(self, "pet", None)
        if pet is None:
            return

        def tier_of(v: int) -> int:
            t = len(BALANCE_TIERS)
            for i, (th, _a) in enumerate(BALANCE_TIERS):
                if v < th:
                    return i
            return t

        b0, b1 = tier_of(before), tier_of(after)
        if b1 == b0:
            return
        if b1 >= len(BALANCE_TIERS):
            action = "余额-分文不剩"
        else:
            action = BALANCE_TIERS[b1][1]
        pet.mark_activity()
        pet.sprite.play_once(action, pet._anim_t)
        pet.update()

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

        # 形象切换（真实形象 / 大肥鱼 / 小马），即时生效并写回 config.json
        char_menu = QMenu("形象切换", menu)
        char_group = QActionGroup(char_menu)
        char_group.setExclusive(True)
        for key in CHARACTER_NAMES:
            act = QAction(CHARACTER_NAMES[key], char_menu)
            act.setCheckable(True)
            act.setChecked(self.pet.character == key)
            act.triggered.connect(lambda checked, k=key: self._set_character(k))
            char_group.addAction(act)
            char_menu.addAction(act)
        menu.addMenu(char_menu)

        # 大肥鱼版本切换（成年 / 幼年，仅 fish 形象生效），即时生效并写回 config.json
        fish_version_menu = QMenu("大肥鱼版本", menu)
        fv_group = QActionGroup(fish_version_menu)
        fv_group.setExclusive(True)
        for key in ("adult", "baby"):
            act = QAction(FISH_VERSION_NAMES[key], fish_version_menu)
            act.setCheckable(True)
            act.setChecked(self.pet.fish_version == key)
            act.triggered.connect(lambda checked, k=key: self._set_fish_version(k))
            fv_group.addAction(act)
            fish_version_menu.addAction(act)
        menu.addMenu(fish_version_menu)

        # 渲染风格切换（图片形象 / 粒子光球），即时生效并写回 config.json
        style_menu = QMenu("渲染风格", menu)
        style_group = QActionGroup(style_menu)
        style_group.setExclusive(True)
        for key, label in (("sprite", "图片形象"), ("orb", "粒子光球")):
            act = QAction(label, style_menu)
            act.setCheckable(True)
            act.setChecked(self.pet.style == key)
            act.triggered.connect(lambda checked, k=key: self._set_style(k))
            style_group.addAction(act)
            style_menu.addAction(act)
        menu.addMenu(style_menu)

        menu.addSeparator()

        # 位置策略：默认桌面层（不遮挡工作窗口），可切换置顶悬浮，即时生效并写回 config.json
        act_ontop = QAction("置顶显示（默认桌面层不遮挡）", menu)
        act_ontop.setCheckable(True)
        act_ontop.setChecked(bool(self.pet.cfg.get("pet_on_top", False)))
        act_ontop.toggled.connect(self._set_on_top)
        menu.addAction(act_ontop)

        menu.addSeparator()

        act_quit = QAction("退出", menu)
        act_quit.triggered.connect(self._quit)
        menu.addAction(act_quit)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_activated)
        self.tray.show()
        return True

    def _set_character(self, key: str):
        self.pet.set_character(key)
        cfg = dict(self.pet.cfg)
        cfg["pet_character"] = key
        self.pet.cfg = cfg
        save_config(cfg)

    def _set_fish_version(self, key: str):
        self.pet.set_fish_version(key)
        cfg = dict(self.pet.cfg)
        cfg["fish_version"] = key
        self.pet.cfg = cfg
        save_config(cfg)

    def _set_style(self, key: str):
        self.pet.set_style(key)
        cfg = dict(self.pet.cfg)
        cfg["pet_style"] = key
        self.pet.cfg = cfg
        save_config(cfg)

    def _set_on_top(self, checked: bool):
        self.pet.set_on_top(bool(checked))
        cfg = dict(self.pet.cfg)
        cfg["pet_on_top"] = bool(checked)
        self.pet.cfg = cfg
        save_config(cfg)

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
    _hook_diag("main: hotkey.start ret=%s" % ok)

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
