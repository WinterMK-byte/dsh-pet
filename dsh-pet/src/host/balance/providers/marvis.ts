/**
 * Marvis 本机用量（provider id `marvis`）—— 读本机 Marvis 的 data.db（**只读**）统计 token 用量。
 *
 * 数据源：`llm_token_usage` 表（字段 usage_date / total_tokens）。
 *   - rolling  = 今日 token 总量（`usage_date = date('now','localtime')`）
 *   - monthly  = 本月 token 总量（`usage_date >= 月首`）
 *
 * 与 ecustcic 不同：这里**没有"额度上限/已用百分比"**语义（本地模型 + 云端混合，无法定义额度），
 * 因此：
 *   - data.rolling / data.monthly 直接是 **token 数**（大整数），不是百分比；
 *   - 展示层对 `provider === 'marvis'` 特判为「今日/本月已用 N tokens」文本气泡（见 shared-core.js）；
 *   - `balancePercent` 对 marvis 返回 undefined → 不驱动档位动画（大数会溢出档位）。
 *
 * 凭证：`mode: 'none'`（读本机库，不涉及任何 key / .credentials）。
 * 依赖：Node 内置 `node:sqlite`，需启动参数 `--experimental-sqlite`（见 scripts/start-marvis-pet.mjs）。
 */
import type { BalanceProvider } from '../types';

/** Marvis 数据库路径：默认当前用户的 data.db，可用 MARVIS_DB_PATH 覆盖 */
const DEFAULT_DB =
  'C:\\Users\\makexuan\\AppData\\Roaming\\Tencent\\Marvis\\User\\oAN1i2cvBuoWFQT4P8CE9jptdcfQ\\database\\data.db';

function dbPath(): string {
  const p = process.env.MARVIS_DB_PATH;
  return p && p.length > 0 ? p : DEFAULT_DB;
}

/** 打开只读连接；失败一律 throw（由 index.queryBalance 落 fetch-error，绝不伪造 0） */
async function openReadOnly() {
  let sqlite: any;
  try {
    // @ts-ignore —— node:sqlite 为实验特性，类型定义随 Node 版本变动
    sqlite = await import('node:sqlite');
  } catch (e) {
    throw new Error(
      'marvis: 无法加载 node:sqlite，请以 --experimental-sqlite 启动（用 scripts/start-marvis-pet.mjs）',
    );
  }
  const DatabaseSync = sqlite?.DatabaseSync;
  if (typeof DatabaseSync !== 'function') {
    throw new Error('marvis: node:sqlite 不可用（缺少 DatabaseSync）');
  }
  try {
    return new DatabaseSync(dbPath(), { readOnly: true });
  } catch (e) {
    throw new Error('marvis: 打开 data.db 失败（只读）: ' + (e instanceof Error ? e.message : String(e)));
  }
}

function sumOne(db: any, sql: string): number {
  const row: any = db.prepare(sql).get();
  const v = row?.t ?? row?.['t'];
  const n = Number(v);
  if (!Number.isFinite(n)) throw new Error('marvis: token 查询结果非法');
  return n;
}

export const marvis: BalanceProvider = {
  ids: ['marvis'],
  credential: { mode: 'none' },
  async fetch({ provider }) {
    const db = await openReadOnly();
    try {
      const rolling = sumOne(
        db,
        "SELECT IFNULL(SUM(total_tokens), 0) AS t FROM llm_token_usage WHERE usage_date = date('now', 'localtime')",
      );
      const monthly = sumOne(
        db,
        "SELECT IFNULL(SUM(total_tokens), 0) AS t FROM llm_token_usage WHERE usage_date >= strftime('%Y-%m-01', 'now', 'localtime')",
      );
      return {
        ok: true,
        provider,
        shape: 'windows',
        data: {
          // 注意：这两个是 token 数，不是百分比；展示层按 provider==='marvis' 特判
          monthly,
          rolling,
          monthlyCapUsd: monthly,
          rollingCapUsd: rolling,
        },
      };
    } catch (e) {
      throw e instanceof Error ? e : new Error(String(e));
    } finally {
      try {
        db.close();
      } catch {
        /* noop */
      }
    }
  },
};
