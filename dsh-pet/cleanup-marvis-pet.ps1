# 启动前清理残留的 marvis-pet 进程（standalone + electron-helper），
# 避免旧进程抢端口或让新窗口不出现。匹配 standalone.js / electron-helper 命令行特征，
# 不要求路径含 marvis-pet（工作目录启动时命令行只有 lib\standalone.js 也照样清掉）。
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -match 'standalone\.js|electron-helper' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
