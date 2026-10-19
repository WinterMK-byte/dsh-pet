# 变更记录

本文件按 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 组织，版本号遵循
[语义化版本](https://semver.org/lang/zh-CN/)。

## [0.1.0] - 2026-10-19

首个公开版本。

### 新增

- 透明无边框置顶悬浮宠物：QPainter 实时绘制的粒子光球，无图片资源依赖
- 鼠标拖拽移动；拖到屏幕左/右边缘自动收纳成扁条，鼠标触碰边缘自动展开
- 全局快捷键（默认 `Ctrl+Alt+J`）唤起对话输入条，回车发送，记录面板可滚动
- 接入本机 Ollama 流式对话（`/api/chat`，`stream=true`），完全本地推理、零上传
- 四态动效：空闲（蓝）/ 思考中（紫）/ 回复中（绿）/ 出错（红）
- 系统托盘：显示/隐藏、打开对话、开机自启开关（`HKCU\...\Run`，默认关）、退出
- 全部配置集中在 `config.json`
- token 消耗显示：本次 / 会话 输入输出统计，本地模型标注「本地免费」，配置单价后换算金额
- 任务流程卡片：thinking → streaming → done / failed，完成或出错 30 秒自动消失
- 事件气泡：`hey!` / `done!` / `oops!`，带透明度渐隐动画
- Marvis 状态出口预留：`marvis_state_source` 支持 `none` / `file` / `http`，无数据自动降级本地流程
- PyInstaller 单文件打包脚本 `build.bat`，产物约 48 MB，无控制台窗口
- 冒烟测试脚本 `smoke_test2.py`（13 项断言）与测试报告 `TEST_REPORT.md`
- CI 门禁：语法编译、依赖清单可解析、泄漏检查（`tools/leak_check.py`）

### 已知限制

- 仅支持 Windows（依赖 Win32 窗口特性与 `keyboard` 低级钩子）
- exe 未做代码签名，SmartScreen 会提示未知发布者
- 「任务状态联动」尚未接入 Marvis 侧实时事件流，当前仅支持文件 / HTTP 轮询的自定义状态源
