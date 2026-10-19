# Marvis Pet 冒烟测试报告

- 测试日期：2026-10-19
- 测试环境：Windows 11 (Build 26300)，Python 3.12.10（项目独立 .venv）
- 测试方式：脚本化冒烟测试（进程启动 + Win32 窗口枚举 + 按键注入 + Qt GUI 链路测试）

## 依赖安装（阿里云镜像）

| 包 | 版本 | 结果 |
|---|---|---|
| PySide6 | 6.12.0 | ✅ 成功（含 Essentials/Addons/WebEngine/shiboken6） |
| requests | 2.34.2 | ✅ 成功 |
| keyboard | 0.13.5 | ✅ 成功 |
| pyinstaller | 6.22.3 | ✅ 成功 |

- 虚拟环境：`<项目所在目录>\marvis-pet\.venv`
- 镜像：`https://mirrors.aliyun.com/pypi/simple`（首次全量安装 PySide6 曾超时，拆包续装后成功）

## Ollama 状态

| 项 | 结果 |
|---|---|
| Ollama 服务在线（http://127.0.0.1:11434/api/tags） | ✅ 在线 |
| 目标模型 `qwen2.5:7b` 已安装 | ✅ 存在 |
| 流式推理（/api/chat, stream=True） | ✅ 正常，测试问题回复："桌宠冒烟测试通过。" |

## 源码模式实测（.venv\Scripts\pythonw.exe main.py）

| 用例 | 结果 | 说明 |
|---|---|---|
| 语法检查（py_compile） | ✅ | main.py 编译通过 |
| 程序启动 | ✅ | pythonw 进程正常运行，无崩溃 |
| 宠物窗口出现 | ✅ | Win32 枚举到标题 "MarvisPet" 的可见窗口 |
| 全局快捷键 Ctrl+Alt+J 唤出对话面板 | ✅ | 注入 Ctrl+Alt+J 后枚举到 "Marvis Pet Chat" 窗口 |
| 面板发送消息 → Ollama 流式回复 | ✅ | GUI 链路测试：发送后 QThread 流式接收，assistant 回复写入记录（长度 12 字），宠物状态回复完成回到 idle |
| 开机自启注册表 | ✅ | set_autostart(True) 写入并读取确认，set_autostart(False) 清除确认，未污染注册表 |

## 打包产物实测（dist\MarvisPet.exe）

| 用例 | 结果 | 说明 |
|---|---|---|
| PyInstaller 打包 | ✅ | `pyinstaller --onefile --windowed --name MarvisPet main.py` 退出码 0 |
| exe 启动 | ✅ | 单文件 exe 正常运行 |
| 宠物窗口出现 | ✅ | 枚举到 "MarvisPet" 窗口 |
| Ctrl+Alt+J 唤出对话面板 | ✅ | 枚举到 "Marvis Pet Chat" 窗口 |

## 关键问题与解决记录

1. **全局热键失效（失败点 → 已修复）**
   - 现象：初版用 `pynput.keyboard.GlobalHotKeys('ctrl+alt+j')`，按键注入后回调不触发。
   - 根因：本机 Windows 上 pynput 对 Ctrl/Alt 修饰键的 VK 映射与真实/注入按键（ctrl_l = VK 0xA2）不匹配，HotKey 状态机无法匹配 `Key.ctrl`（VK 0x11）。
   - 修复：改用 `keyboard` 库（boppreh/keyboard 0.13.5）低级钩子实现 `add_hotkey('ctrl+alt+j')`，实测注入触发成功；requirements.txt 同步替换 pynput → keyboard。
2. **按键注入测试注意事项**
   - `keybd_event` 注入时若不携带 scan code（参数为 0），keyboard 库无法识别键位。自动化测试需通过 `MapVirtualKeyW(vk, 0)` 补 scan code；真实键盘硬件自带 scan code，不受影响。
3. **PyInstaller 打包注意**
   - 以管理员权限运行 PyInstaller 会打印 DEPRECATION 警告（6.22 不阻断，7.0 将阻断），建议非管理员终端运行 build.bat。
   - shell 直接调用 `python -m PyInstaller` 在本环境出现输出异常，改用 `Start-Process`/`pyinstaller.exe` 正常（build.bat 内使用 `%PY% -m PyInstaller`，实测等效命令通过）。

## 未自动化断言（人工目测项）

- 粒子光球绘制效果、四态颜色切换（空闲蓝 / 思考紫 / 回复绿 / 出错红）
- 鼠标拖拽移动、拖到屏幕边缘贴边收纳成扁条、鼠标触碰边缘展开
- 托盘图标右键菜单（显示/隐藏、打开对话、开机自启、退出）交互
- 以上功能代码均已实现（QPainter 粒子系统、edge snap/expand、QSystemTrayIcon 菜单），冒烟测试聚焦"可启动、窗口出现、热键唤起、拿到 Ollama 回复"四项硬指标，均通过。

## 结论

**冒烟测试通过。** 程序可正常启动、宠物窗口正常显示、Ctrl+Alt+J 可唤起对话输入条、本地 Ollama（qwen2.5:7b）可返回回复，打包产物同样验证通过。建议实际使用前人工体验托盘/拖拽/贴边收纳等交互细节。

---

## 第二轮冒烟测试（新增功能：token 消耗 / 任务流程卡片 / 事件气泡 / Marvis 状态出口预留）

- 测试日期：2026-10-19
- 测试方式：`smoke_test2.py` 脚本化测试（金额估算逻辑单测 + Qt GUI 链路真实 Ollama 对话 + Marvis 状态出口 file 轮询 + 进程级启动/热键回归）

### 测试结果：PASS 13 / FAIL 0

| 用例 | 结果 | 说明 |
|---|---|---|
| A1 本地模型标注「本地免费」 | ✅ | token_price 未配置单价 → "本地免费" |
| A2 预留单价估算逻辑 | ✅ | 配置单价后输出 `≈¥6.0000`（输入 1000×¥2/1k + 输出 500×¥8/1k） |
| B1 发送触发 hey! 气泡 + thinking 卡片 | ✅ | 发送消息后宠物顶部飘 hey!，任务卡片进入 thinking |
| B2 Ollama 流式回复完成 | ✅ | 真实 qwen2.5:7b 推理完成 |
| B3 token 消耗显示 | ✅ | 本次 输入 44 · 输出 24；标注「本地免费」；会话统计同步 |
| B4 done 卡片 + done! 气泡 + idle | ✅ | 回复完成后卡片变绿色 done，飘 done!，宠物回 idle |
| B5 会话累计 token 累加 | ✅ | 第二轮后会话 输入 125 · 输出 32（首轮 44/24） |
| B6 done 卡片 30s 自动消失 | ✅ | 真实计时 30s 后卡片自动移除 |
| C1 Marvis 状态出口展示任务流程 | ✅ | file 状态源返回 sessions，streaming/done 正确映射成 Marvis 卡片 |
| C2 无数据降级本地流程 | ✅ | 状态文件删除后 Marvis 卡片清空，仅保留本地对话流程 |
| C3 type=none 不启用轮询 | ✅ | 未配置状态源时不启动定时器 |
| D1 源码模式启动 + 宠物窗口出现 | ✅ | 回归通过 |
| D2 Ctrl+Alt+J 唤出对话面板 | ✅ | 热键回归通过（等待热键注册完成后注入） |

### 实现要点

- **token 消耗**：Ollama 流式响应的 done 帧当前版本将 token 计数放在**顶层扁平字段**（`prompt_eval_count` / `eval_count`），非嵌套 `usage` 对象；已做双形态兼容。面板底部实时显示"本次/会话 输入/输出"，本地模型默认标注「本地免费」，`config.json` 配置 `token_price` 单价后自动切换为 `≈¥x.xxxx` 金额估算。
- **任务流程卡片**：悬浮窗顶部卡片堆叠（老上、新下），本地对话状态机 thinking → streaming → done/failed，完成/出错 30s 自动消失；`marvis_state_source` 支持 none/file/http 三种类型轮询 Marvis 状态出口，有数据展示 Marvis 任务流程，无数据/失败自动降级本地流程。
- **事件气泡**：收到新消息 `hey!`、完成 `done!`、出错 `oops!`，带透明度渐隐动画。

### 本轮修复记录

1. TaskCardItem 初始化顺序：`_expire` 定时器创建前调用 `set_state` 会触发 AttributeError，已调整创建顺序。
2. 冒烟脚本 Win32 枚举：Python 3.12 下 `EnumWindows` 回调需通过 `ctypes.WINFUNCTYPE` 声明类型，否则 `ArgumentError`。
3. 热键回归测试需等待进程启动后热键监听注册完成再注入按键（窗口出现 ≈2.5s 后注入稳定通过）。
