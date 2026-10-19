# Marvis Pet — 本地 AI 桌宠（Windows）

一个完全本地推理的 Windows 桌面宠物程序，对标
[dsh-harness-jarvis](https://github.com/CroissanTTs/dsh-harness-jarvis) 的悬浮助手
交互形态：透明置顶的粒子光球宠物常驻桌面，全局快捷键唤出对话输入条，
由本机 **Ollama** 完成推理，不上传任何数据。

![tech](https://img.shields.io/badge/Python-3.12-3776AB) ![gui](https://img.shields.io/badge/GUI-PySide6-41B883) ![llm](https://img.shields.io/badge/LLM-Ollama%20Local-FF6A00) ![license](https://img.shields.io/badge/license-MIT-blue)

## 快速开始（不想装 Python 的看这里）

到 [Releases](../../releases) 下载 `MarvisPet.exe`（单文件，约 48 MB，无需安装），
放到任意目录双击运行即可。首次运行会在同目录生成 `config.json`。

> exe 未做代码签名，Windows SmartScreen 可能提示"未知发布者"，选择"仍要运行"。

前提：本机已安装并运行 [Ollama](https://ollama.com/download)，且已拉取对话模型：

```bash
ollama pull qwen2.5:7b
```

## 功能特性

- 🐾 **透明无边框置顶悬浮宠物**：QPainter 实时绘制的粒子光球，无需图片资源
- 🖱️ **鼠标拖拽 + 贴边收纳**：拖到屏幕左/右边缘自动收成彩色扁条，鼠标触碰边缘自动展开
- ⌨️ **全局快捷键唤起对话**：默认 `Ctrl+Alt+J`，回车发送，对话记录内嵌面板可滚动
- 🤖 **完全本地推理**：对话走本机 Ollama（默认 `http://127.0.0.1:11434`，模型 `qwen2.5:7b`）
- 🎨 **四态动效**：空闲（蓝）/ 思考中（紫）/ 回复中（绿）/ 出错（红），以颜色与粒子形态区分
- 🖥️ **系统托盘**：显示/隐藏窗口、打开对话、开机自启开关、退出
- 📊 **token 消耗显示**：面板底部实时显示"本次 / 会话 输入 · 输出"，本地模型标注「本地免费」；
  配置 `token_price` 单价后自动换算为金额
- 🗂️ **任务流程卡片**：悬浮窗顶部堆叠 thinking → streaming → done / failed 状态卡片，
  完成或出错 30 秒后自动消失
- 💬 **事件气泡**：收到消息飘 `hey!`、完成飘 `done!`、出错飘 `oops!`，带渐隐动画
- 🔌 **状态出口预留**：`marvis_state_source` 支持 `none` / `file` / `http` 三种轮询源，
  有数据时展示外部任务流程，无数据自动降级回本地对话流程

## 目录结构

```
marvis-pet/
├── main.py                  # 主程序（宠物窗口 + 对话面板 + 托盘 + 热键 + 卡片/气泡）
├── config.json              # 配置文件（首次运行自动生成默认值）
├── requirements.txt         # Python 依赖
├── build.bat                # PyInstaller 一键打包脚本
├── MarvisPet.spec           # PyInstaller 规格文件（build.bat 生成后可复用）
├── smoke_test2.py           # 冒烟测试脚本（13 项断言，需本机 Ollama）
├── TEST_REPORT.md           # 冒烟测试报告（源码模式 + exe 模式实测记录）
├── CHANGELOG.md
├── README.md
├── LICENSE                  # MIT
├── tools/leak_check.py      # CI 门禁：绝对路径 / 凭据 / 私人信息泄漏检查
└── .github/workflows/ci.yml
```

## 环境要求

- Windows 10/11
- Python 3.10+（推荐 3.12，开发环境已验证 3.12.10）
- [Ollama](https://ollama.com/download) 已安装并运行，且已拉取对话模型：

```bash
ollama pull qwen2.5:7b
```

## 安装

```bat
:: 1. 进入项目目录
cd /d <项目所在目录>\marvis-pet

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
| `hotkey` | `ctrl+alt+j` | 全局唤起快捷键（keyboard 库键名格式） |
| `auto_start` | `false` | 是否开机自启（也可在托盘菜单切换） |
| `pet_size` | `96` | 宠物窗口直径（像素） |
| `opacity` | `0.95` | 窗口透明度 |
| `token_price.prompt_per_1k` | `null` | 输入侧单价（每千 token），`null` = 本地免费 |
| `token_price.completion_per_1k` | `null` | 输出侧单价（每千 token） |
| `token_price.currency` | `CNY` | 计价货币符号 |
| `marvis_state_source.type` | `none` | 状态源类型：`none` / `file` / `http` |
| `marvis_state_source.file` | `""` | `type=file` 时读取的状态 JSON 路径 |
| `marvis_state_source.url` | `""` | `type=http` 时轮询的状态接口 |
| `marvis_state_source.interval` | `3000` | 轮询间隔（毫秒） |

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

## 冒烟测试

```bat
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python smoke_test2.py
```

需要本机 Ollama 在线且已拉取 `qwen2.5:7b`（测试会发起真实推理）。断言项见
[TEST_REPORT.md](./TEST_REPORT.md)。

## 常见问题

- **提示 Ollama 离线**：确认 Ollama 已启动（`ollama serve`），且 `config.json` 地址正确；可用 `curl http://127.0.0.1:11434/api/tags` 验证。
- **模型不存在**：执行 `ollama pull qwen2.5:7b`（或换成 `config.json` 中指定的模型）。
- **全局快捷键无效**：避免与其他软件冲突，可在 `config.json` 修改 `hotkey` 后重启。
- **打包后找不到模型/地址**：exe 运行时读取的是 exe 同目录的 `config.json`，请复制一份过去。
- **热键在管理员程序前台时失效**：`keyboard` 库走低级键盘钩子，Windows 不允许普通进程监听更高完整性级别的输入；
  以管理员身份运行本程序，或避开在该程序上按热键。

## 技术栈

Python 3.12 · PySide6 (Qt6) · keyboard（全局热键） · requests（Ollama HTTP 流式 API） · PyInstaller

## 贡献

提交前请跑 `python tools/leak_check.py .`（CI 会跑同一份脚本）。
本仓库的 CI 门禁包括：Python 语法编译、依赖清单可解析、绝对路径/凭据/私人信息泄漏检查。

## License

[MIT](./LICENSE)
