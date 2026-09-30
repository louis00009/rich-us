/**
 * 监控总控
 *
 * 旧实现只在「监控运行中」时渲染右侧指标，监控一停整块消失；而且用的是
 * `run.events_found / analyses_done` —— 这两个字段只在写入带 run_id 时累加，
 * 实测运行中的批次长期显示「事件 0 / 建议 0」，数字既缺又假。
 *
 * 现在固定展示六个关键口径（不论监控开没开）：
 *   ① 上次运行（起止时刻 + 时长 + 状态）  ② 本批窗口内实际抓取/建议条数
 *   ③ 今日新增事件                        ④ 近 24h 事件（含高影响条数）
 *   ⑤ 上次抓取时间与覆盖标的数            ⑥ 累计事件/建议
 * 外加近 7 日事件量柱状图 —— 一眼看出情报流是活的还是断了。
 *
 * 抓取家数（2026-09-29 补）：
 * 「AI 立即抓取」曾把家数**写死 4**，而库里待抓取有 20+ 家 —— 用户看到「0/4 家」
 * 会以为剩下的人被漏掉了。实际是**刻意的分批**（单家 = 1 次多源新闻聚合 + 最多 2 次
 * LLM 调用，推理型模型每次先烧上千 token 思维链，一次跑完会占满配额并撞网关限流）。
 * 现在：家数可下拉选择（最多 4/8/12 家 或 全部待抓取），并在进度条下方与底部汇总行
 * **显式说明「本轮只抓 N 家 / 待抓取共 M 家」以及调度器每轮自动轮转 3 家** ——
 * 分批这件事本身没问题，问题是没告诉用户。
 *
 * 指定标的（2026-09-29 再补，用户原话「我可能有重点要跑的，或者我可能就选一家跑」）：
 * 家数选择只能从待抓取清单里**按顺序取前 N 家**，无法表达「今天重点跑这几家」。
 * 现在多了「指定标的」：勾选即精确批次（后端不再按 limit 截断），点选顺序 = 抓取顺序，
 * 选择结果持久化到 localStorage（每天要跑，不该每天重挑）。**有选择时「本轮」家数不生效**
 * —— 该 Select 会被禁用并说明原因，避免「勾了 7 家却只跑 4 家」这种看起来像 bug 的行为。
 */
import { useState } from 'react'
import { Satellite } from 'lucide-react'
import IngestLog from './IngestLog'
import LiveStatusView from './LiveStatus'
import { ModelChain } from './ModelChain'
import { Badge, Button, Card, Select, Switch } from '../ui'
import ScrapePicker from './ScrapePicker'
import MonitorStats from './MonitorStats'
import MonitorToolbar from './MonitorToolbar'
import { type IngestItem, type LiveStatus, type Overview } from './types'

const INTERVALS = [5, 10, 15, 30, 60, 120]

export default function MonitorBar({
  ov,
  live,
  ingest,
  monitorOn,
  running,
  intervalMin,
  setIntervalMin,
  aiScrape,
  setAiScrape,
  autoAnalyze,
  setAutoAnalyze,
  scrapeLimit,
  setScrapeLimit,
  scrapeSymbols,
  setScrapeSymbols,
  busy,
  model,
  setModel,
  modelOptions,
  defaultModel,
  scrapeJob,
  onCancelScrape,
  onStart,
  onStop,
  onAiScrape,
  onChainChange,
  onRetryFailures,
}: {
  ov: Overview | null
  /** 实时运行状态（/intel/live，父级 3s 轮询）；null = 老后端 */
  live: LiveStatus | null
  /** 入库台账（/intel/scrape-log，父级 15s 轮询） */
  ingest: IngestItem[]
  monitorOn: boolean
  running: Overview['scheduler']['current_run']
  intervalMin: number
  setIntervalMin: (v: number) => void
  aiScrape: boolean
  setAiScrape: (v: boolean) => void
  autoAnalyze: boolean
  setAutoAnalyze: (v: boolean) => void
  /** 本轮抓取家数：0 = 全部待抓取（**仅在未指定标的时生效**） */
  scrapeLimit: number
  setScrapeLimit: (v: number) => void
  /** 指定标的（有序 = 抓取顺序）；非空时它就是精确批次，scrapeLimit 不生效 */
  scrapeSymbols: string[]
  setScrapeSymbols: (v: string[]) => void
  busy: string
  model: string
  setModel: (v: string) => void
  modelOptions: string[]
  defaultModel: string
  scrapeJob: { id: string; progress: number; total: number; note: string } | null
  onCancelScrape: () => void
  onStart: () => void
  onStop: () => void
  onAiScrape: () => void
  /** 模型链改动后回调（父级重拉 overview 让链显示同步）；09-30 加 */
  onChainChange?: () => void
  /** 「一键重试失败家」回调（父级触发 POST /intel/scrape/retry）；09-30 加 */
  onRetryFailures?: () => void
}) {
  // hooks 必须在任何 early return 之前（React #300 白屏）
  const [pickerOpen, setPickerOpen] = useState(false)
  const act = ov?.activity
  // 到期待抓取的家数（与外部 Agent 的 poll 同一口径）——「AI 立即抓取」家数的分母
  const pending = ov?.stats.tasks_pending ?? 0
  // 后端给出的待抓取**清单**（判定含 interval*1.2，前端不得自行推算）
  const pendingSymbols = ov?.stats.pending_symbols ?? []
  /** 非空 = 「指定标的」模式：勾选即精确批次，scrapeLimit 不生效 */
  const picked = scrapeSymbols.length > 0
  const planned = picked ? scrapeSymbols.length : scrapeLimit <= 0 ? pending : Math.min(scrapeLimit, pending || scrapeLimit)
  // 优先用「最近一次批次」：监控停止后 running 为 null，但 last_run 仍在
  const last = ov?.last_run ?? null
  // last_run.agents_seen 后端已解析成数组；老后端可能是 JSON 字符串 → 双兼容
  const agents: string[] = Array.isArray(last?.agents_seen)
    ? (last!.agents_seen as unknown as string[])
    : (() => {
        try {
          return JSON.parse(String(last?.agents_seen || '[]')) as string[]
        } catch {
          return []
        }
      })()

  const lastRunText = last
    ? last.running
      ? `Run #${last.id} 运行中`
      : `Run #${last.id} 已${last.status === 'finished' ? '归档' : '收尾'}`
    : '从未运行'

  return (
    <Card
      className="shrink-0"
      title="监控总控"
      subtitle="开启后内置 AI 自动抓取情报（外部 Agent 可选增强）；截止时自动归档事件节点与建议报告"
      actions={
        <MonitorToolbar
          ov={ov}
          pending={pending}
          picked={picked}
          scrapeSymbols={scrapeSymbols}
          scrapeLimit={scrapeLimit}
          setScrapeLimit={setScrapeLimit}
          scrapeJob={scrapeJob}
          busy={busy}
          monitorOn={monitorOn}
          pickerOpen={pickerOpen}
          setPickerOpen={setPickerOpen}
          onAiScrape={onAiScrape}
          onStart={onStart}
          onStop={onStop}
        />
      }
    >
      {/* 指定标的：勾选即精确批次。默认收起（大多数轮次用「自动」就够），有选择时常驻展开，
          否则用户会看不到自己之前挑了哪几家、也就无从修改。 */}
      {(pickerOpen || picked) && (
        <ScrapePicker
          companies={ov?.companies ?? []}
          pendingSymbols={pendingSymbols}
          value={scrapeSymbols}
          onChange={(list) => {
            setScrapeSymbols(list)
            // 清空后**保持面板展开**：用户点「清空」多半是想换一批，而不是让面板凭空消失
            // （刷新后靠 picked 自动展开的那种情况，清空会让 picked 变 false 而收起 —— 体验不一致）。
            if (!list.length) setPickerOpen(true)
          }}
          disabled={!!scrapeJob}
        />
      )}

      {/* 立即抓取的实时进度条（后台任务）：跑多久、跑到第几家、当前步骤一目了然，可取消 */}
      {scrapeJob && (
        <div className="mb-3 rounded-lg border border-brand-200 bg-brand-50/60 px-3 py-2">
          <div className="flex items-center gap-2 text-xs">
            <Satellite className="h-3.5 w-3.5 shrink-0 animate-pulse text-brand-600" />
            <b className="shrink-0 text-brand-800">AI 抓取进行中</b>
            <span className="num shrink-0 font-semibold text-brand-700">
              {scrapeJob.progress}/{scrapeJob.total || '—'} 家
            </span>
            <span className="min-w-0 flex-1 truncate text-slate-500">{scrapeJob.note}</span>
            <Button size="sm" variant="ghost" onClick={onCancelScrape}>
              取消
            </Button>
          </div>
          <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-slate-200">
            <div
              className="h-full rounded-full bg-brand-500 transition-all duration-500"
              style={{ width: `${scrapeJob.total ? Math.max(4, Math.round((scrapeJob.progress / scrapeJob.total) * 100)) : 4}%` }}
            />
          </div>
          {/* 分批是刻意的，不是「漏抓」—— 必须在这里说明，否则用户会以为剩下 24 家被丢了 */}
          {picked ? (
            <div className="mt-1 text-[10px] leading-relaxed text-brand-700/80">
              本轮按「指定标的」执行 {scrapeSymbols.length} 家：{scrapeSymbols.join(' → ')}
              <span className="text-brand-700/70">（勾选即精确批次，「本轮」家数不生效）</span>
            </div>
          ) : (
            scrapeLimit > 0 &&
            pending > scrapeLimit && (
              <div className="mt-1 text-[10px] leading-relaxed text-brand-700/80">
                本轮只抓 {scrapeLimit} 家，待抓取共 {pending} 家 —— 刻意分批（单家含 2 次 LLM 调用，一次跑完会占满配额且易撞网关限流）。
                再点一次「AI 立即抓取」继续下一批，或把「本轮」改成「全部」一次跑完；也可用「指定标的」直接挑重点公司。
              </div>
            )
          )}
        </div>
      )}

      {/* 09-30：监控实时进度 —— 仅在「没有手动抓取在跑」时显示，避免两条进度条叠加。手动进行中
         时只显示上方的「AI 抓取进行中」条（jobs 互斥锁已在后端确认不会并发）。 */}
      {!scrapeJob && (
        <LiveStatusView monitorOn={monitorOn} live={live} ov={ov} defaultModel={defaultModel} />
      )}

      {/* 状态 + 开关 */}
      <div className="flex flex-wrap items-center gap-x-5 gap-y-3">
        <div className="flex flex-wrap items-center gap-2">
          {monitorOn ? (
            <Badge tone="green" dot>
              监控运行中{running ? ` · Run #${running.id}` : ''}
            </Badge>
          ) : (
            <Badge tone="slate">监控已停止</Badge>
          )}
          {ov && !ov.settings.monitor_enabled && ov.scheduler.current_run && (
            <Badge tone="amber">存在未关闭批次</Badge>
          )}
          {ov && (
            <Badge tone={ov.llm.configured ? 'green' : 'slate'} dot={ov.llm.configured}>
              {ov.llm.configured ? 'AI 已连接' : 'AI 未配置'}
            </Badge>
          )}
          {/* 09-30：熔断器状态 —— 连续 N 家失败后跳过整批，避免日志雪崩 */}
          {ov?.breaker && (
            <span
              title={
                ov.breaker.open
                  ? `连续 ${ov.breaker.consec_failures} 家失败，剩余 ${Math.ceil(ov.breaker.cooldown_remaining_s / 60)} 分钟冷却；所有抓取已跳过`
                  : ov.breaker.consec_failures > 0
                    ? `已累计 ${ov.breaker.consec_failures} 次失败 / 阈值 ${ov.breaker.threshold}`
                    : '网关健康'
              }
            >
              <Badge
                tone={ov.breaker.open ? 'red' : ov.breaker.consec_failures > 0 ? 'amber' : 'green'}
                dot
              >
                {ov.breaker.open
                  ? `熔断中 ${Math.ceil(ov.breaker.cooldown_remaining_s / 60)}分`
                  : ov.breaker.consec_failures > 0
                    ? `失败 ${ov.breaker.consec_failures}/${ov.breaker.threshold}`
                    : '网关健康'}
              </Badge>
            </span>
          )}
        </div>

        <label className="flex items-center gap-2 text-xs text-slate-500">
          抓取周期
          <Select value={intervalMin} onChange={(e) => setIntervalMin(Number(e.target.value))} disabled={monitorOn} className="!w-24">
            {INTERVALS.map((m) => (
              <option key={m} value={m}>
                {m} 分钟
              </option>
            ))}
          </Select>
        </label>

        {/* 抓取模型：空 = 设置页默认；选项 = 别名 + 网关全模型（/ai/status）。仅作用于「AI 立即抓取」 */}
        <label className="flex items-center gap-2 text-xs text-slate-500" title="「AI 立即抓取」使用的模型；监控调度固定用设置页默认模型">
          模型
          <Select value={model} onChange={(e) => setModel(e.target.value)} className="!w-52 max-w-[220px]">
            <option value="">{defaultModel ? `默认（${defaultModel}）` : '默认模型'}</option>
            {modelOptions.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </Select>
        </label>
      </div>

      {/* 模型 fallback 链（09-30 加）：每家抓取按顺序逐档试，第一个可用即用 ——
          不再「一个模型挂 = 23 家全挂」。父级 ov 30s 轮询刷新；用户改动后 300ms 防抖保存。 */}
      <div className="mt-2 rounded-md bg-slate-50/50 px-3 py-1.5">
        <ModelChain
          chain={ov?.settings.llm_fallback_chain ?? []}
          onChange={onChainChange}
        />

        <Switch
          checked={aiScrape}
          onChange={setAiScrape}
          label="AI 自动抓取"
          hint="每轮把到期公司的最新新闻交给 AI 提取关键节点"
          disabled={monitorOn}
        />
        <Switch
          checked={autoAnalyze}
          onChange={setAutoAnalyze}
          label="自动 AI 分析"
          hint="无外部 Agent 时用 LLM/本地引擎兜底"
          disabled={monitorOn}
        />
      </div>

      {/* 关键口径 + 近 7 日事件量（纯展示，已拆到 MonitorStats） */}
      <MonitorStats
        ov={ov}
        last={last}
        lastRunText={lastRunText}
        act={act}
        agents={agents}
        pending={pending}
        planned={planned}
        picked={picked}
        scrapeLimit={scrapeLimit}
        intervalMin={intervalMin}
      />
      <IngestLog ingest={ingest} onRetryFailures={onRetryFailures} />
    </Card>
  )
}
