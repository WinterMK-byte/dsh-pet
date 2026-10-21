/**
 * 校园中转站 ecust-cic（provider id `ecust-cic`）—— 三窗口用量（按**请求次数**口径）。
 *
 * 接口：`GET https://ai.ecustcic.com/api/user/quota`（Bearer = ECUST_CIC_API_KEY）。
 * 响应：`{ periods: [{ id, period_seconds, quota_requests, used_requests, reset_at }] }`。
 * 窗口按 period_seconds 匹配：3600 = 小时滚动窗、604800 = 周、2592000 = 月。
 *
 * 满额度是**请求次数**而不是 USD（该网关按次数限额，token 只对小时窗有 3000 万上限），
 * 所以 *CapUsd 一律不带出 —— 展示层退化为「已用百分比」相对口径，不假装有金额。
 */
import { fetchWithRetry, num } from '../internal';
import type { BalanceProvider } from '../types';

const SEC_HOUR = 3600;
const SEC_WEEK = 604800;
const SEC_MONTH = 2592000;

interface QuotaPeriod {
  period_seconds?: unknown;
  quota_requests?: unknown;
  used_requests?: unknown;
  reset_at?: unknown;
}

/** 请求次数口径的已用百分比（0-100）；缺窗口或额度非法 → 抛错（不静默当 0） */
function percentUsed(p: QuotaPeriod | undefined, label: string): number {
  if (!p) throw new Error('dsh-pet: ecustcic 响应缺少 ' + label + ' 窗口');
  const cap = num(p.quota_requests, label + '.quota_requests');
  const used = num(p.used_requests, label + '.used_requests');
  if (!(cap > 0)) throw new Error('dsh-pet: ecustcic ' + label + '.quota_requests 非法');
  return Math.min(100, Math.max(0, (used / cap) * 100));
}

/** reset_at → ISO 字符串；缺失/空 → undefined（可选字段） */
function resetAt(p: QuotaPeriod | undefined): string | undefined {
  const v = p?.reset_at;
  return typeof v === 'string' && v.length > 0 ? v : undefined;
}

/** 原始次数（已用 / 上限）：缺失或非法 → undefined（可选装饰，「查看额度」明细行用，不因此整拍失败） */
function rawCount(p: QuotaPeriod | undefined, field: 'used_requests' | 'quota_requests'): number | undefined {
  if (!p) return undefined;
  const v = p[field];
  if (v === undefined || v === null) return undefined;
  const n = Number(v);
  return Number.isFinite(n) ? n : undefined;
}

export const ecustcic: BalanceProvider = {
  ids: ['ecust-cic'],
  credential: { mode: 'ref', ref: 'ECUST_CIC_API_KEY' },
  async fetch({ key, provider }) {
    const res = await fetchWithRetry('https://ai.ecustcic.com/api/user/quota', key);
    if (!res.ok) throw new Error('ecustcic quota HTTP ' + res.status);
    const body: unknown = await res.json();
    const list = (body as { periods?: unknown })?.periods;
    if (!Array.isArray(list) || list.length === 0) throw new Error('dsh-pet: ecustcic 响应缺少 periods');
    const periods = list as QuotaPeriod[];
    const pick = (sec: number): QuotaPeriod | undefined =>
      periods.find((p) => Number(p.period_seconds) === sec);
    const hour = pick(SEC_HOUR);
    const week = pick(SEC_WEEK);
    const month = pick(SEC_MONTH);
    return {
      ok: true,
      provider,
      shape: 'windows',
      data: {
        rolling: percentUsed(hour, '小时'),
        weekly: percentUsed(week, '周'),
        monthly: percentUsed(month, '月'),
        rollingLabel: '每小时',
        rollingResetsAt: resetAt(hour),
        weeklyResetsAt: resetAt(week),
        monthlyResetsAt: resetAt(month),
        // 次数口径原始数字（「查看额度」菜单直显 0/200 这种）——纯展示装饰，不参与档位计算
        rollingUsedCount: rawCount(hour, 'used_requests'),
        rollingCapCount: rawCount(hour, 'quota_requests'),
        weeklyUsedCount: rawCount(week, 'used_requests'),
        weeklyCapCount: rawCount(week, 'quota_requests'),
        monthlyUsedCount: rawCount(month, 'used_requests'),
        monthlyCapCount: rawCount(month, 'quota_requests'),
      },
    };
  },
};
