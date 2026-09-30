/**
 * 入库台账（从 MonitorBar.tsx 抽出——主文件超组件软上限 400）。
 *
 * 每一条「数据进了库」的记录：内置 AI 抓取 / 外部 Agent 提交事件与建议。
 * 失败与空抓也如实记录（记 0 条），绝不静默 —— 「记录好那些数据入库了」。
 * 展开状态自持（默认收起，与主组件的其它弹窗互不干扰）。
 *
 * 09-30 加：底部「失败 X 家 · 一键重试」按钮 —— 父级监听 IngestItem.ok==false
 * 数量；点击调 POST /intel/scrape/retry（jobs 后台重跑，复用 raw_news 缓存直接打标）。
 */
import { useState } from 'react'
import { RefreshCw, ScrollText } from 'lucide-react'
import { Button } from '../ui'
import { fmtUtc, type IngestItem } from './types'

/** 台账动作标签：一行看懂「这条记录是哪条入库路径」 */
const ACTION_LABEL: Record<string, string> = {
  scrape: '抓取',
  ai_scrape: '批量',
  submit_events: '事件',
  submit_analysis: '建议',
}

export default function IngestLog({
  ingest,
  onRetryFailures,
  retrying,
}: {
  ingest: IngestItem[]
  /** 「一键重试失败家」回调（父级触发 POST /intel/scrape/retry） */
  onRetryFailures?: () => void
  /** 重试任务进行中（用于禁用按钮） */
  retrying?: boolean
}) {
  const [open, setOpen] = useState(false)
  /* 09-30：失败家数 = 失败且动作是「抓取」的台账条数；按 symbol 去重展示唯一值。 */
  const failedSymbols = Array.from(
    new Set(
      ingest
        .filter((it) => !it.ok && it.action === 'scrape')
        .map((it) => (it.detail || '').match(/^([A-Z][A-Z0-9.]{0,15})/)?.[1] || '')
        .filter(Boolean),
    ),
  )
  const failedCount = failedSymbols.length
  return (
    <div className="mt-3 rounded-lg border border-slate-100 px-3 py-2.5">
      <button
        className="flex w-full items-center gap-2 text-[11px] font-medium text-slate-500"
        onClick={() => setOpen((v) => !v)}
      >
        <ScrollText className="h-3.5 w-3.5" />
        入库台账（最近 {ingest.length} 条）
        {failedCount > 0 && (
          <span className="ml-1 inline-flex items-center gap-1 rounded-full bg-rose-50 px-2 py-0.5 text-[10px] font-medium text-rose-700 ring-1 ring-inset ring-rose-200">
            失败 {failedCount} 家
          </span>
        )}
        <span className="ml-auto text-slate-300">{open ? '收起 ▲' : '展开 ▼'}</span>
      </button>
      {failedCount > 0 && onRetryFailures && (
        <div className="mt-1.5 flex items-center gap-2">
          <Button
            size="sm"
            variant="danger"
            icon={<RefreshCw className={`h-3.5 w-3.5 ${retrying ? 'animate-spin' : ''}`} />}
            loading={retrying}
            onClick={onRetryFailures}
            title="复用 raw_news 缓存（≤30 分钟）直接打标，跳过新闻抓取；按 fallback 链逐档试模型"
          >
            一键重试 {failedCount} 家
          </Button>
          <span className="text-[11px] text-slate-400">
            失败：{failedSymbols.slice(0, 8).join('、')}
            {failedSymbols.length > 8 && ` 等 ${failedSymbols.length} 家`}
          </span>
        </div>
      )}
      {open && (
        <ul className="mt-2 max-h-44 space-y-1 overflow-y-auto pr-1 text-[11px]">
          {ingest.length === 0 && (
            <li className="text-slate-400">
              暂无入库记录 —— 点「AI 立即抓取」或开启监控后，这里逐条记录每家进了多少数据
            </li>
          )}
          {ingest.map((it, i) => (
            <li key={i} className="flex items-center gap-2 leading-relaxed">
              <span className="num shrink-0 text-slate-400" title={fmtUtc(it.ts)}>
                {fmtUtc(it.ts)}
              </span>
              <span className={`shrink-0 font-medium ${it.ok ? 'text-emerald-600' : 'text-rose-600'}`}>
                {ACTION_LABEL[it.action] ?? it.action}
              </span>
              <span className="min-w-0 flex-1 truncate text-slate-500" title={it.detail}>
                {it.detail}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
