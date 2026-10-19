# -*- coding: utf-8 -*-
"""Marvis Pet 冒烟测试（第二轮）
新增功能验证：token 消耗展示 / 任务流程卡片（thinking→streaming→done/failed，30s 消失）/
事件气泡（hey!/done!/oops!）/ Marvis 状态出口预留（有数据展示、无数据降级本地）/ 不回归项。

运行：.venv\\Scripts\\python.exe smoke_test2.py
"""

import ctypes
import json
import os
import re
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
os.chdir(BASE)
TEMP_DIR = os.path.join(BASE, "temp")
os.makedirs(TEMP_DIR, exist_ok=True)

PASSED = []
FAILED = []


def report(name, ok, detail=""):
    tag = "PASS" if ok else "FAIL"
    print(f"[{tag}] {name} {detail}")
    (PASSED if ok else FAILED).append((name, detail))


# ---------------------------------------------------------------------------
# 通用工具（Win32 窗口枚举 / 热键注入）
# ---------------------------------------------------------------------------

user32 = ctypes.windll.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
user32.EnumWindows.argtypes = [WNDENUMPROC, ctypes.c_void_p]
user32.EnumWindows.restype = ctypes.c_bool


def find_window(title_fragment: str):
    out = []

    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                if title_fragment in buf.value:
                    out.append(hwnd)
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


def send_hotkey_ctrl_alt_j():
    vk_ctrl, vk_alt, vk_j = 0xA2, 0xA4, ord("J")
    scan = lambda vk: user32.MapVirtualKeyW(vk, 0)  # noqa: E731
    user32.keybd_event(vk_ctrl, scan(vk_ctrl), 0, 0)
    user32.keybd_event(vk_alt, scan(vk_alt), 0, 0)
    user32.keybd_event(vk_j, scan(vk_j), 0, 0)
    user32.keybd_event(vk_j, scan(vk_j), 2, 0)
    user32.keybd_event(vk_alt, scan(vk_alt), 2, 0)
    user32.keybd_event(vk_ctrl, scan(vk_ctrl), 2, 0)


def wait_for(pred, timeout: float, interval: float = 0.3) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(interval)
    return False


def wait_qt(pred, timeout: float) -> bool:
    """带 Qt 事件循环的等待（保证信号槽被处理）。"""
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    loop = QEventLoop()
    timer = QTimer()
    timer.setInterval(200)
    timer.timeout.connect(loop.quit)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        timer.start()
        loop.exec()
        timer.stop()
    return False


# ---------------------------------------------------------------------------
# A. 金额估算逻辑
# ---------------------------------------------------------------------------

def test_estimate_cost():
    from main import estimate_cost_text

    cfg_free = {"token_price": {"prompt_per_1k": None, "completion_per_1k": None, "currency": "CNY"}}
    s_free = estimate_cost_text(cfg_free, 100, 200)
    ok = "本地免费" in s_free
    report("A1 本地模型标注「本地免费」", ok, f"-> {s_free}")

    cfg_paid = {"token_price": {"prompt_per_1k": 2.0, "completion_per_1k": 8.0, "currency": "CNY"}}
    s_paid = estimate_cost_text(cfg_paid, 1000, 500)
    val = float(s_paid.split("¥")[1]) if "≈¥" in s_paid else -1.0
    ok = "≈¥" in s_paid and abs(val - 6.0) < 1e-6
    report("A2 预留单价估算逻辑", ok, f"-> {s_paid} (期望 ≈¥6.0000)")


# ---------------------------------------------------------------------------
# B. GUI 链路：真实 Ollama 对话 → token / 卡片 / 气泡
# ---------------------------------------------------------------------------

def test_gui_flow():
    from PySide6.QtWidgets import QApplication
    from main import PetWindow, load_config

    app = QApplication.instance() or QApplication(sys.argv)
    cfg = load_config()
    pet = PetWindow(cfg)
    pet.hide()
    pet.overlay.hide()
    panel = pet.chat_panel

    # B1: 发送消息 → hey! 气泡 + thinking 卡片
    panel.input_edit.setText("用一句话介绍你自己")
    panel._send()
    bubble_hey = pet._bubble is not None and pet._bubble["text"] == "hey!"
    task_id = panel._current_task_id
    card_thinking = task_id is not None and task_id in pet.overlay._local_cards and pet.overlay._local_cards[task_id].state == "thinking"
    report("B1 发送触发 hey! 气泡 + thinking 卡片", bubble_hey and card_thinking,
           f"气泡={'有' if bubble_hey else '无'} 卡片={'有' if card_thinking else '无'}")

    # B2: 等待回复完成（真实 Ollama qwen2.5:7b）
    def worker_done():
        return panel._worker is None or not panel._worker.isRunning()

    ok_wait = wait_qt(worker_done, 180)
    report("B2 Ollama 流式回复完成", ok_wait, "超时则视为 FAIL")

    # B3: token 数字（本次输入/输出 > 0，标注本地免费）
    text = panel.token_label.text()
    m = re.search(r"本次 输入 (\d+) · 输出 (\d+)", text)
    p = e = 0
    if m:
        p, e = int(m.group(1)), int(m.group(2))
    ok = ok_wait and m is not None and p > 0 and e > 0 and "本地免费" in text
    ok = ok and panel._session_usage["prompt"] == p and panel._session_usage["eval"] == e
    report("B3 token 消耗显示（本次输入/输出/本地免费）", ok, f"-> {text}")

    # B4: 卡片 done + done! 气泡 + 宠物回 idle
    card_done = task_id in pet.overlay._local_cards and pet.overlay._local_cards[task_id].state == "done"
    bubble_done = pet._bubble is None or pet._bubble["text"] == "done!"
    ok = card_done and bubble_done and pet.state == "idle"
    report("B4 done 卡片 + done! 气泡 + idle", ok,
           f"卡片={card_done} 气泡={'done!' if bubble_done else pet._bubble and pet._bubble['text']} 状态={pet.state}")

    # B5: 第二次对话 → 会话累计增加
    panel.input_edit.setText("再说一句，谢谢")
    panel._send()
    ok_wait2 = wait_qt(worker_done, 180)
    text2 = panel.token_label.text()
    m2 = re.search(r"会话 输入 (\d+) · 输出 (\d+)", text2)
    sp = se = 0
    if m2:
        sp, se = int(m2.group(1)), int(m2.group(2))
    ok = ok_wait2 and m2 is not None and (sp > p or se > e)
    report("B5 会话累计 token 累加", ok, f"-> 会话 输入 {sp} / 输出 {se} (首轮 {p}/{e})")

    # B6: 完成卡片 30s 自动消失（真实计时）
    fake_id = "fake-expire-test"
    pet.overlay.add_local_task(fake_id, "30s消失测试", "thinking")
    pet.overlay.update_local_task(fake_id, "done")
    deadline = time.time() + 34
    disappeared = False
    while time.time() < deadline:
        if fake_id not in pet.overlay._local_cards:
            disappeared = True
            break
        app.processEvents()
        time.sleep(0.5)
    report("B6 done 卡片 30s 自动消失", disappeared)

    pet.close()
    return p, e, sp, se


# ---------------------------------------------------------------------------
# C. Marvis 状态出口（file 型）预留：有数据展示 / 无数据降级
# ---------------------------------------------------------------------------

def test_marvis_poller():
    from PySide6.QtWidgets import QApplication
    from main import MarvisStatePoller, PetWindow, load_config

    app = QApplication.instance() or QApplication(sys.argv)
    state_file = os.path.join(TEMP_DIR, "marvis_pet_state_test.json")
    cfg = load_config()
    cfg["marvis_state_source"] = {"type": "file", "file": state_file, "interval": 3000}
    pet = PetWindow(cfg)
    pet.hide()
    pet.overlay.hide()
    poller = MarvisStatePoller(pet.overlay, cfg)

    # C1: 有数据 → 展示 Marvis 任务流程卡片（streaming / done 映射）
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump({"sessions": [
            {"id": "s1", "title": "数据分析", "state": "streaming_text"},
            {"id": "s2", "title": "代码评审", "state": "done"},
        ]}, f, ensure_ascii=False)
    poller._poll()
    cards = pet.overlay._marvis_cards
    ok = "s1" in cards and cards["s1"].state == "streaming" and "s2" in cards and cards["s2"].state == "done"
    report("C1 Marvis 状态出口展示任务流程", ok, f"-> 卡片 {sorted(cards.keys())} 状态 {[c.state for c in cards.values()]}")

    # C2: 无数据 → 清空 Marvis 卡片（降级为本地对话流程）
    os.remove(state_file)
    poller._poll()
    ok = not pet.overlay._marvis_cards
    report("C2 无数据降级本地流程", ok, f"-> Marvis 卡片剩余 {len(pet.overlay._marvis_cards)}")

    # C3: 未配置（none）→ 不启动轮询
    cfg["marvis_state_source"] = {"type": "none", "url": "", "file": "", "interval": 3000}
    poller2 = MarvisStatePoller(pet.overlay, cfg)
    poller2.start()
    ok = not poller2._timer.isActive()
    report("C3 type=none 不启用轮询", ok)

    pet.close()


# ---------------------------------------------------------------------------
# D. 进程级启动 + 热键（不回归）
# ---------------------------------------------------------------------------

def test_process_smoke():
    exe = os.path.join(BASE, ".venv", "Scripts", "pythonw.exe")
    proc = subprocess.Popen([exe, os.path.join(BASE, "main.py")])
    try:
        ok = wait_for(lambda: len(find_window("MarvisPet")) > 0, 30)
        report("D1 源码模式启动 + 宠物窗口出现", ok)
        # 等待热键监听注册完成（启动流程中 hotkey 注册在窗口创建之后）
        time.sleep(2.5)
        send_hotkey_ctrl_alt_j()
        ok = wait_for(lambda: len(find_window("Marvis Pet Chat")) > 0, 20)
        report("D2 Ctrl+Alt+J 唤出对话面板（不回归）", ok)
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:
            proc.kill()


# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("Marvis Pet 冒烟测试（第二轮：token / 卡片 / 气泡 / Marvis 出口）")
    print("=" * 60)
    test_estimate_cost()
    test_gui_flow()
    test_marvis_poller()
    test_process_smoke()
    print("=" * 60)
    print(f"结果：PASS {len(PASSED)} / FAIL {len(FAILED)}")
    for name, detail in FAILED:
        print(f"  FAIL -> {name} {detail}")
    print("=" * 60)
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()
