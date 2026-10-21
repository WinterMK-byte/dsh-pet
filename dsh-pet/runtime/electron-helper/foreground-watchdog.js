/**
 * dsh-pet desktop helper —— 前台独占遮挡看门狗（纯判定部分）。
 *
 * 【问题】桌宠窗口始终置顶（screen-saver 带），打全屏游戏 / 看全屏视频时它压在游戏画面上，
 * 既挡前台资源，又可能触发 DWM 视频合成黑屏（见 main.js 头部 issue #60 的完整遮挡条件）。
 *
 * 【方案】Windows 上由常驻探测进程（foreground-probe.ps1）持续上报「前台窗口是否全屏独占」：
 * 前台窗口矩形完整覆盖其所在显示器（rcMonitor，容差 2px）即视为全屏独占
 * （全屏游戏、全屏视频、放映模式等），输出 1/0 行协议。本文件只做**防抖状态判定**：
 * 连续独占足够久才隐藏（避免进入全屏瞬间的抖动来回闪），恢复非独占立即恢复显示。
 *
 * 【安全默认】探测进程不可用（非 Windows / PowerShell 缺失 / 探测崩溃）时上层不隐藏——
 * 治理功能宁可不生效，也不能把桌宠莫名藏起来（遮挡治理是体验优化，不是保命逻辑）。
 *
 * 本文件只放纯判定：不 require('electron')，可被 node:test 直接加载单测（同 topmost-watchdog.js）。
 */

'use strict';

/** 前台独占探测/判定节拍（ms）：多久做一次判定。探测脚本输出间隔与此同量级 */
const FOREGROUND_WATCHDOG_TICK_MS = 1000;

/** 连续全屏独占多久才隐藏（ms）：防抖窗口，避免进入/退出全屏瞬间抖动导致桌宠闪烁 */
const FOREGROUND_HIDE_DELAY_MS = 1200;

/**
 * 这一拍要不要隐藏桌宠窗口。
 *
 * 只有「探测可用、前台持续全屏独占达到防抖时长」才返回 true；窗口已销毁、当前非独占、
 * 独占状态尚未开始计时（探测刚启动还没抓到首拍）一律 false。
 *
 * @param {{nowMs:number,exclusiveSinceMs:(number|null),exclusive:boolean,destroyed:boolean}} state
 * @returns {boolean}
 */
function shouldHideForForeground(state) {
  const { nowMs, exclusiveSinceMs, exclusive, destroyed } = state || {};
  if (destroyed || !exclusive) return false;
  if (typeof exclusiveSinceMs !== 'number' || !Number.isFinite(exclusiveSinceMs)) return false;
  const elapsed = nowMs - exclusiveSinceMs;
  // 时间正常流逝且已超过防抖时长 → 隐藏；时钟回拨 / 时间戳异常一律按未到点处理（宁可不藏）
  return elapsed >= FOREGROUND_HIDE_DELAY_MS;
}

module.exports = { FOREGROUND_WATCHDOG_TICK_MS, FOREGROUND_HIDE_DELAY_MS, shouldHideForForeground };
