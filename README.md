---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: d9895d0aa1b93a25de031252b375f54d_78483087cb8911f18533525400638852
    ReservedCode1: 4GKmf5qPNVljaghzLZdFLJUyl+Z1tSdW+RTM1XfdqpKc7RIoCuF/UFkAg3MwVoL+heLgUNWMiNvr2INcH2X03ELvAYT7NcdlQ5g0G55/sB3meiQXc8txhPmqlP4+V05SgJdgVoxwKrithUSZtmYn7OCMd6A/1AnpBtEZ2P87SFSbQnV8X0bOhsTz7ic=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: d9895d0aa1b93a25de031252b375f54d_78483087cb8911f18533525400638852
    ReservedCode2: 4GKmf5qPNVljaghzLZdFLJUyl+Z1tSdW+RTM1XfdqpKc7RIoCuF/UFkAg3MwVoL+heLgUNWMiNvr2INcH2X03ELvAYT7NcdlQ5g0G55/sB3meiQXc8txhPmqlP4+V05SgJdgVoxwKrithUSZtmYn7OCMd6A/1AnpBtEZ2P87SFSbQnV8X0bOhsTz7ic=
---

# Marvis Pet — 本地 AI 桌宠（Windows）

一个完全本地推理的 Windows 桌面宠物程序，对标
[dsh-harness-jarvis](https://github.com/CroissanTTs/dsh-harness-jarvis) 的悬浮助手
交互形态：透明置顶的粒子光球宠物常驻桌面，全局快捷键唤出对话输入条，
由本机 **Ollama** 完成推理，不上传任何数据。

![tech](https://img.shields.io/badge/Python-3.12-3776AB) ![gui](https://img.shields.io/badge/GUI-PySide6-41B883) ![llm](https://img.shields.io/badge/LLM-Ollama%20Local-FF6A00)

## 功能特性

- 🐾 **透明无边框置顶悬浮宠物**：QPainter 实时绘制的粒子光球，无需图片资源
- 🖱️ **鼠标拖拽 + 贴边收纳**：拖到屏幕左/右边缘自动收成彩色扁条，鼠标触碰边缘自动展开
- ⌨️ **全局快捷键唤起对话**：默认 `Ctrl+Alt+J`，回车发送，对话记录内嵌面板可滚动
- 🤖 **完全本地推理**：对话走本机 Ollama（默认 `http://127.0.0.1:11434`，模型 `qwen2.5:7b`）
- 🎨 **四态动效**：空闲（蓝）/ 思考中（紫）/ 回复中（绿）/ 出错（红），以颜色与粒子形态区分
- 🖥️ **系统托盘**：显示/隐藏窗口、打开对话、开机自启开关、退出

## 目录结构

```
marvis-pet/
├── main.py            # 主程序（宠物窗口 + 对话面板 + 托盘 + 热键）
├── config.json        # 配置文件（首次运行自动生成默认值）
├── requirements.txt   # Python 依赖
├── build.bat          # PyInstaller 一键打包脚本
├── README.md
└── LICENSE
```

## 环境要求

- Windows 10/11
- Python 3.10+（推荐 3.12，本机已验证 3.12.10）
- [Ollama](https://ollama.com/download) 已安装并运行，且已拉取对话模型：

```bash
ollama pull qwen2.5:7b
```

## 安装

```bat
:: 1. 进入项目目录
cd /d C:\Users\makexuan\Desktop\Marvis产出\marvis-pet

:: 2. 创建虚拟环境（可选但推荐）
py -3.12 -m venv .venv

:: 3. 安装依赖（国内可用阿里云镜像）
.venv\Scripts\python -m pip install -i https://mirrors.aliyun.com/pypi/simple -r requirements.txt
```

## 配置

编辑项目根目录的 `config.json`：

| 字段 | 默认值 | 说明 |
|---|---|---|
| `ollama_base_url` | `http://127.0.0.1:11434` | Ollama 服务地址 |
| `model` | `qwen2.5:7b` | 对话模型名（需已 `ollama pull`） |
| `hotkey` | `ctrl+alt+j` | 全局唤起快捷键（pynput 键名格式） |
| `auto_start` | `false` | 是否开机自启（也可在托盘菜单切换） |
| `pet_size` | `96` | 宠物窗口直径（像素） |
| `opacity` | `0.95` | 窗口透明度 |

修改后重启程序生效。

## 运行

```bat
:: 前台运行（便于看日志）
.venv\Scripts\pythonw.exe main.py

:: 或直接双击 main.py / 创建快捷方式指向 pythonw.exe main.py
```

启动后：

- 拖拽光球可移动；拖到屏幕左/右边缘自动收纳成扁条，鼠标移过去即展开
- 双击光球或按 `Ctrl+Alt+J` 唤起对话输入条，输入后回车发送
- 右键托盘图标可显示/隐藏、设置开机自启、退出

## 打包为单文件 exe

```bat
build.bat
```

脚本会自动创建虚拟环境、安装依赖（阿里云镜像）并调用 PyInstaller，
产物位于 `dist\MarvisPet.exe`（单文件、无控制台窗口）。
打包后 `config.json` 需与 exe 放同一目录。

## 常见问题

- **提示 Ollama 离线**：确认 Ollama 已启动（`ollama serve`），且 `config.json` 地址正确；可用 `curl http://127.0.0.1:11434/api/tags` 验证。
- **模型不存在**：执行 `ollama pull qwen2.5:7b`（或换成 `config.json` 中指定的模型）。
- **全局快捷键无效**：避免与其他软件冲突，可在 `config.json` 修改 `hotkey` 后重启。
- **打包后找不到模型/地址**：exe 运行时读取的是 exe 同目录的 `config.json`，请复制一份过去。

## 技术栈

Python 3.12 · PySide6 (Qt6) · keyboard（全局热键） · requests（Ollama HTTP 流式 API） · PyInstaller

## License

[MIT](./LICENSE)
*（内容由AI生成，仅供参考）*
