/**
 * 监控总控 · 关键口径 + 近 7 日事件量
 *
 * 从 `MonitorBar.tsx` 抽出（铁律 9，2026-09-30：该文件 443 行，超组件软上限 400）。
 * 纯展示，无业务状态。
 *
 * 六个口径**不论监控开没开都在**（旧实现只在运行中渲染，监控一停整块消失）：
 *   ① 上次运行 ② 本批抓取/建议 ③ 今日新增事件 ④ 近 24h ⑤ 上次抓取 ⑥ 累计
 * 外加近 7 日事件量柱状图 + 「待抓取/参与 Agent/本轮将抓 N 家」汇总行。
 */
import { DailyBars, Metric } from './MonitorMetrics'
import { fmtDuration, fmtSince, fmtUtc, type Overview } from './types'

export default function MonitorStats({
  ov,
  last,
  lastRunText,
  act,
  agents,
  pending,
  planned,
  picked,
  scrapeLimit,
  intervalMin,
}: {
  ov: Overview | null
  last: Overview['last_run'] | null
  lastRunText: string
  act: Overview['activity'] | undefined
  agents: string[]
  pending: number
  /** 本轮「AI 立即抓取」将抓的家数（父级按 指定标的/全部/最多 N 家 算出） */
  planned: number
  picked: boolean
  scrapeLimit: number
  intervalMin: number
}) {
  return (
    <>
      {/* 关键口径：不论监控开没开都在 */}
      <div className="mt-3 grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-6">
        <Metric
          label="上次运行"
          value={lastRunText}
          tone={last?.running ? 'brand' : 'default'}
          title={last ? `开始 ${fmtUtc(last.started_at)}${last.ended_at ? ` · 截止 ${fmtUtc(last.ended_at)}` : ''}` : undefined}
          hint={
            last
              ? `${fmtUtc(last.started_at).slice(5)} · 时长 ${fmtDuration(last.duration_seconds)}`
              : '点击右上角「一键开启监控」'
          }
        />
        <Metric
          label="本批抓取 / 建议"
          value={last ? `${last.events_in_window} / ${last.analyses_in_window}` : '—'}
          tone={last && last.events_in_window > 0 ? 'brand' : 'muted'}
          title="本批次运行窗口内实际入库的事件数 / 建议数（按时间窗口实查，不是批次自报值）"
          hint={last ? `心跳 ${last.tick_count} 次 · ${fmtSince(last.last_tick_at)}` : undefined}
        />
        <Metric
          label="今日新增事件"
          value={act ? act.today_events : '—'}
          tone={act && act.today_events > 0 ? 'brand' : 'muted'}
          title="事件发生日=今天，或今天入库的事件数"
          hint={act ? `涉及 ${act.companies_enabled} 只在观察` : undefined}
        />
        <Metric
          label="近 24 小时"
          value={act ? act.h24_events : '—'}
          title="近 24 小时入库的事件数"
          hint={act ? `其中 4★以上 ${act.h24_high_impact} 条 · 建议 ${act.h24_analyses} 条` : undefined}
        />
        <Metric
          label="上次抓取"
          value={act ? fmtSince(act.last_scrape_at) : '—'}
          title="所有观察标的中最近一次成功抓取的时间"
          hint={act ? `24h 内已覆盖 ${act.scraped_24h} / ${act.companies_enabled} 家` : undefined}
        />
        <Metric
          label="累计"
          value={act ? `${act.events_total} / ${act.analyses_total}` : '—'}
          tone="muted"
          title="历史累计事件数 / 建议数"
          hint={agents.length ? `Agent：${agents.join(' / ')}` : 'Agent：暂无接入'}
        />
      </div>

      {/* 近 7 日事件量 + 上次批次参与方 */}
      <div className="mt-3 flex flex-wrap items-end justify-between gap-4 rounded-lg border border-slate-100 px-3 py-2.5">
        <div>
          <div className="mb-1.5 text-[11px] font-medium text-slate-500">近 7 日事件量</div>
          <DailyBars daily={act?.daily ?? []} />
        </div>
        <div className="min-w-0 flex-1 text-[11px] leading-relaxed text-slate-500">
          <div className="truncate">
            <b className="text-slate-600">待抓取</b> {pending} 家
            <span className="text-slate-400"> / 共 {ov?.stats.companies_enabled ?? '—'} 家启用</span>
            <span className="text-slate-300"> · </span>
            <b className="text-slate-600">参与 Agent</b> {agents.length ? agents.join(' / ') : '暂无接入'}
          </div>
          <div className="mt-0.5 leading-relaxed text-slate-400">
            <b className="text-slate-500">本轮「AI 立即抓取」将抓 {planned} 家</b>
            （{picked ? '指定标的' : scrapeLimit <= 0 ? '全部待抓取' : `最多 ${scrapeLimit} 家`}）。
            监控开启时调度器{picked ? '每轮优先抓指定标的（≤4 家）' : '每轮自动抓 3 家到期轮转'}（周期 {intervalMin} 分钟），全部标的会被逐步覆盖；
            想只跑重点公司就用「指定标的」挑，想一次跑完把「本轮」改成「全部」。
          </div>
          {last?.note && <div className="mt-0.5 truncate text-slate-400">批次备注：{last.note}</div>}
        </div>
      </div>
    </>
  )
}
