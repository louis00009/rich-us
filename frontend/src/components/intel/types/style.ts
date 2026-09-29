/**
 * 情报中心 · 展示样式与筛选选项（单一来源，避免各处硬编码）
 *
 * 从 `types.ts` 抽出（铁律 9 拆分，2026-09-29）。
 *
 * ⚠️ 配色遵循**中国习惯**：看多 = 红，看空 = 绿（跟随平台配色切换，见 lib/format）。
 */
import { downColor, upColor } from '../../../lib/format'
import type { Rec, Tier } from './domain'
import { clampImpact } from './format'

export const REC_LABEL: Record<Rec, string> = {
  strong_buy: '强烈买入',
  buy: '买入',
  hold: '持有',
  reduce: '减持',
  avoid: '回避',
}

/** 中国习惯：看多 = 红，看空 = 绿（跟随平台配色切换） */
export function recBg(rec: Rec | null | undefined): string {
  if (!rec) return '#94a3b8'
  const bull: Rec[] = ['strong_buy', 'buy']
  return bull.includes(rec) ? upColor() : rec === 'hold' ? '#d97706' : downColor()
}

export function sentimentColor(s: string): string {
  return s === 'positive' ? upColor() : s === 'negative' ? downColor() : '#94a3b8'
}

export function sentimentCn(s: string): string {
  return s === 'positive' ? '利好' : s === 'negative' ? '利空' : '中性'
}

export const TIER_STYLE: Record<Tier, { label: string; badge: string; border: string; bg: string; text: string }> = {
  critical: {
    label: '重大',
    badge: 'bg-rose-600 text-white ring-rose-600',
    border: '#e11d48',
    bg: 'bg-rose-50/50',
    text: 'text-rose-700',
  },
  high: {
    label: '重要',
    badge: 'bg-amber-500 text-white ring-amber-500',
    border: '#f59e0b',
    bg: 'bg-amber-50/40',
    text: 'text-amber-700',
  },
  medium: {
    label: '可看',
    badge: 'bg-slate-200 text-slate-700 ring-slate-200',
    border: '#cbd5e1',
    bg: 'bg-white',
    text: 'text-slate-600',
  },
  low: {
    label: '低',
    badge: 'bg-slate-100 text-slate-500 ring-slate-200',
    border: '#e2e8f0',
    bg: 'bg-white',
    text: 'text-slate-400',
  },
}

/** 由影响度推导分档（老后端不返回 tier 时的回落，保持排序语义一致） */
export function tierOf(importance: number | undefined, impact: number): Tier {
  if (importance == null) {
    const i = clampImpact(impact)
    return i >= 5 ? 'critical' : i === 4 ? 'high' : i === 3 ? 'medium' : 'low'
  }
  if (importance >= 79) return 'critical'
  if (importance >= 60) return 'high'
  if (importance >= 40) return 'medium'
  return 'low'
}

export const EVENT_CATEGORIES: { key: string; label: string }[] = [
  { key: '', label: '全部类别' },
  { key: 'model_release', label: '模型发布' },
  { key: 'product_launch', label: '产品发布' },
  { key: 'partnership', label: '合作/联盟' },
  { key: 'earnings', label: '财报/业绩' },
  { key: 'regulatory', label: '监管/政策' },
  { key: 'personnel', label: '人事变动' },
  { key: 'macro', label: '宏观/行业' },
  { key: 'other', label: '其他' },
]

export const STAGE_OPTIONS: { key: string; label: string }[] = [
  { key: '', label: '全部阶段' },
  { key: 'confirmed', label: '已敲定' },
  { key: 'negotiating', label: '在谈' },
  { key: 'rumor', label: '传闻' },
]

/** 内容类型筛选：媒体评论占入库量约 11%，会稀释真正的公司事件 */
export const MEDIA_OPTIONS: { key: string; label: string }[] = [
  { key: '', label: '全部内容' },
  { key: 'exclude', label: '仅公司事件' },
  { key: 'only', label: '仅媒体评论' },
]

export const STAGE_TONE: Record<string, string> = {
  confirmed: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  negotiating: 'bg-sky-50 text-sky-700 ring-sky-200',
  rumor: 'bg-slate-100 text-slate-500 ring-slate-200',
}
