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
import { ListChecks, Play, Satellite, Square } from 'lucide-react'
import { Badge, Button, Card, Select, Switch } from '../ui'
import ScrapePicker from './ScrapePicker'
import { DailyBars, Metric } from './MonitorMetrics'
import { fmtDuration, fmtSince, fmtUtc, type Overview } from './types'

const INTERVALS = [5, 10, 15, 30, 60, 120]

export default function MonitorBar({
  ov,
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
}: {
  ov: Overview | null
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
        <div className="flex flex-wrap items-center justify-end gap-1.5">
          {/* 指定标的：勾选即精确批次。用户有重点标的 / 只想跑一家时用这个，
              不必碰运气看「待抓取前 N 家」轮到谁。选择结果持久化，刷新后仍在。 */}
          <Button
            size="sm"
            variant={picked ? 'primary' : 'ghost'}
            icon={<ListChecks className="h-3.5 w-3.5" />}
            disabled={!!scrapeJob}
            aria-expanded={pickerOpen}
            title={
              picked
                ? `已指定 ${scrapeSymbols.length} 家：${scrapeSymbols.join(' → ')}\n点此修改`
                : '从观察标的里挑要抓的公司（点选顺序 = 抓取顺序）。不选则按「本轮」家数自动取待抓取清单'
            }
            onClick={() => setPickerOpen((v) => !v)}
          >
            指定标的{picked ? ` ${scrapeSymbols.length}` : ''}
          </Button>
          {/* 本轮家数：**必须让用户能改**。写死 4 家 + 不解释，用户会以为「只抓了 4 家、其余被漏掉」，
              而实际是「待抓取 28 家、每轮小批量轮转」。默认 4 家（约 2~6 分钟），想一次跑完选「全部」。
              ⚠️ 已指定标的时禁用 —— 勾了 7 家却只跑 4 家是最像 bug 的行为，宁可显式禁用并说明。 */}
          <label
            className="flex items-center gap-1 text-[11px] text-slate-500"
            title={
              picked
                ? `已指定 ${scrapeSymbols.length} 家标的，本轮家数不生效（指定即精确批次）。\n清空指定后此项恢复。`
                : '「AI 立即抓取」本轮最多抓几家。\n' +
                  '单家 = 1 次多源新闻聚合 + 最多 2 次 LLM 调用；推理型模型每次先烧上千 token 思维链，' +
                  '所以家数越多越慢（默认 4 家约 2~6 分钟）。\n' +
                  '监控运行时调度器每轮另自动抓 3 家轮转，长期会把全部标的覆盖一遍。'
            }
          >
            本轮
            <Select
              value={String(scrapeLimit)}
              onChange={(e) => setScrapeLimit(Number(e.target.value))}
              className="!w-28"
              disabled={!!scrapeJob || picked}
            >
              {[4, 8, 12].map((n) => (
                <option key={n} value={n}>
                  最多 {n} 家
                </option>
              ))}
              <option value={0}>{pending > 0 ? `全部 ${pending} 家` : '全部待抓取'}</option>
            </Select>
          </label>
          <Button
            variant="secondary"
            icon={<Satellite className="h-3.5 w-3.5" />}
            loading={busy === 'ai-scrape'}
            disabled={ov ? !ov.llm.configured : false}
            title={
              ov?.llm.configured
                ? `立即执行一轮：新闻抓取 → AI 提取关键节点 → 生成买入建议（无需开启监控）。当前选择：${
                    picked
                      ? `指定标的 ${scrapeSymbols.join('、')}（${scrapeSymbols.length} 家）`
                      : scrapeLimit <= 0
                        ? `全部待抓取（${pending} 家）`
                        : `最多 ${scrapeLimit} 家`
                  }`
                : '请先到「设置 → AI 分析」配置 base_url / api_key / model'
            }
            onClick={onAiScrape}
          >
            AI 立即抓取
          </Button>
          {monitorOn ? (
            <Button variant="danger" icon={<Square className="h-3.5 w-3.5" />} loading={busy === 'monitor'} onClick={onStop}>
              截止并归档
            </Button>
          ) : (
            <Button variant="success" icon={<Play className="h-3.5 w-3.5" />} loading={busy === 'monitor'} onClick={onStart}>
              一键开启监控
            </Button>
          )}
        </div>
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
            监控开启时调度器每轮另自动抓 3 家轮转（周期 {intervalMin} 分钟），全部标的会被逐步覆盖；
            想只跑重点公司就用「指定标的」挑，想一次跑完把「本轮」改成「全部」。
          </div>
          {last?.note && <div className="mt-0.5 truncate text-slate-400">批次备注：{last.note}</div>}
        </div>
      </div>
    </Card>
  )
}
