# dsh-pet desktop helper —— 前台全屏独占探测（Windows 常驻进程）
#
# 每 800ms 检查一次前台窗口是否完整覆盖其所在显示器（全屏游戏 / 全屏视频 / 放映模式），
# stdout 输出一行 "1"（独占）/ "0"（非独占），由 main.js 逐行解析。
# 探测进程异常退出时 main.js 判定为「探测不可用」，桌宠保持现状（宁可不治理也不误藏）。
#
# 判定口径：
#   - GetForegroundWindow 拿前台窗口；GetWindowRect 拿其矩形；
#   - MonitorFromWindow + GetMonitorInfo 拿该窗口所在显示器的完整区域 rcMonitor；
#   - 前台窗口覆盖 rcMonitor（容差 2px）即视为全屏独占。
#   普通最大化窗口只覆盖 rcWork（不含任务栏），不会误判；桌面/资源管理器窗口同样不满足。

$ErrorActionPreference = 'Stop'

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class ForegroundProbe {
    [DllImport("user32.dll")]
    public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")]
    public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);
    [DllImport("user32.dll")]
    public static extern IntPtr MonitorFromWindow(IntPtr hwnd, uint dwFlags);
    [DllImport("user32.dll")]
    public static extern bool GetMonitorInfo(IntPtr hMonitor, ref MONITORINFO lpmi);
    [StructLayout(LayoutKind.Sequential)]
    public struct RECT { public int Left; public int Top; public int Right; public int Bottom; }
    [StructLayout(LayoutKind.Sequential)]
    public struct MONITORINFO { public int cbSize; public RECT rcMonitor; public RECT rcWork; public uint dwFlags; }
}
"@

$MONITOR_DEFAULTTONEAREST = 2
$TOLERANCE = 2

while ($true) {
    $exclusive = $false
    $hwnd = [ForegroundProbe]::GetForegroundWindow()
    if ($hwnd -ne [IntPtr]::Zero) {
        $rect = New-Object ForegroundProbe+RECT
        if ([ForegroundProbe]::GetWindowRect($hwnd, [ref]$rect)) {
            $w = $rect.Right - $rect.Left
            $h = $rect.Bottom - $rect.Top
            $mon = [ForegroundProbe]::MonitorFromWindow($hwnd, $MONITOR_DEFAULTTONEAREST)
            $mi = New-Object ForegroundProbe+MONITORINFO
            $mi.cbSize = [System.Runtime.InteropServices.Marshal]::SizeOf($mi)
            if ([ForegroundProbe]::GetMonitorInfo($mon, [ref]$mi)) {
                $mw = $mi.rcMonitor.Right - $mi.rcMonitor.Left
                $mh = $mi.rcMonitor.Bottom - $mi.rcMonitor.Top
                if (($w -ge ($mw - $TOLERANCE)) -and ($h -ge ($mh - $TOLERANCE))) {
                    $exclusive = $true
                }
            }
        }
    }
    if ($exclusive) { Write-Output '1' } else { Write-Output '0' }
    Start-Sleep -Milliseconds 800
}
