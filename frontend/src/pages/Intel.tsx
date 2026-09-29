/**
 * AI 情报中心 —— 事件驱动研究流水线
 *
 * 页面只做**编排**：数据拉取、动作分发、布局。
 * 具体视图全部拆到 `components/intel/*`（原文件 1335 行已超 900 行硬上限）：
 *   · MonitorBar   监控总控（上次运行 / 抓取条数 / 今日新增 / 覆盖情况）
 *   · DailyDigest  AI 每日必读（强制提示：哪些重要、为什么、什么时机）
 *   · EventFeed    事件流（重要度三档分级 + 筛选 + 低影响折叠）
 *   · CompanyList  观察标的
 *   · Timeline     价格叠加层 + 公司时间线
 *   · AiProposals  AI 买入建议 + 建议验证
 *   · BridgeGuide  外部 Agent 接入与提示词
 *   · RunsPanel    历史批次与归档报告
 *
 * 流水线：外部 AI Agent（WorkBuddy / Claude Code / Codex）通过 Bridge API 抓取
 * 互联网信息 → 提交美股核心公司关键节点 → 结合量化快照提交买入建议；
 * 未配置外部 Agent 时内置 LLM/本地量化引擎自动兜底。
 * 截止后整批节点与建议自动落盘为 Markdown 报告。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Empty, Modal } from '../components/ui'
import { api } from '../lib/api'
import { loadScrapeSymbols, saveScrapeSymbols } from '../lib/intelPrefs'
import { useToast } from '../components/ui'
import MonitorBar from '../components/intel/MonitorBar'
import DailyDigest from '../components/intel/DailyDigest'
import EventFeed from '../components/intel/EventFeed'
import CompanyList from '../components/intel/CompanyList'
import BridgeGuide, { type Guide } from '../components/intel/BridgeGuide'
import RunsPanel from '../components/intel/RunsPanel'
import { LatestHint, ProposalCard, VerifyCard } from '../components/intel/AiProposals'
import { TimelineView } from '../components/intel/Timeline'
import type { Analysis, Company, EventItem, Overview, Run } from '../components/intel/types'

export default function Intel() {
  const toast = useToast()
  const [ov, setOv] = useState<Overview | null>(null)
  const [guide, setGuide] = useState<Guide | null>(null)
  const [analyses, setAnalyses] = useState<Analysis[]>([])
  const [events, setEvents] = useState<EventItem[]>([])
  const [evFilter, setEvFilter] = useState('')
  const [refreshToken, setRefreshToken] = useState(0)
  const [zoomOpen, setZoomOpen] = useState(false)
  const [intervalMin, setIntervalMin] = useState(30)
  const [autoAnalyze, setAutoAnalyze] = useState(true)
  const [aiScrape, setAiScrape] = useState(true)
  /* 本轮抓取家数：0 = 全部待抓取。默认 4 —— 单家要 1 次新闻聚合 + 最多 2 次 LLM 调用，
     推理型模型每次先烧上千 token 思维链，一次点「全部」会跑十几分钟。
     所以默认小批量，想一次跑完由用户显式选「全部」。 */
  const [scrapeLimit, setScrapeLimit] = useState(4)
  /* 指定标的（有序 = 抓取顺序）：非空即精确批次，scrapeLimit 不生效。
     用户每天都要跑且有固定重点标的 → 必须持久化，否则每天重挑一遍。
     ⚠️ 读取必须走 loadScrapeSymbols 规范化（localStorage 里不保证是数组，
     直接 JSON.parse 当数组用会「首次正常、第二次崩」—— 与 /backtest 同一类陷阱）。 */
  const [scrapeSymbols, setScrapeSymbols] = useState<string[]>(() => loadScrapeSymbols())
  const applyScrapeSymbols = useCallback((list: string[]) => {
    setScrapeSymbols(list)
    saveScrapeSymbols(list)
  }, [])
  const [busy, setBusy] = useState('')
  /* 抓取模型选择：空 = 设置页默认模型；选项来自 /ai/status（别名 + 网关全模型） */
  const [model, setModel] = useState('')
  const [modelOptions, setModelOptions] = useState<string[]>([])
  const [defaultModel, setDefaultModel] = useState('')
  /* 立即抓取改为后台任务：轮询进度 + 逐家失败明细反馈（旧同步版 30s 必超时且无进度） */
  const [scrapeJob, setScrapeJob] = useState<{ id: string; progress: number; total: number; note: string } | null>(null)
  const scrapeTimer = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    api
      .get<{ model: string; extra_models: string[] }>('/ai/status')
      .then((d) => {
        setDefaultModel(d.model || '')
        setModelOptions(d.extra_models || [])
      })
      .catch(() => {})
    return () => {
      if (scrapeTimer.current) clearInterval(scrapeTimer.current)
    }
  }, [])

  const loadOverview = useCallback(() => {
    api
      .get<Overview>('/intel/overview')
      .then((d) => {
        setOv(d)
        setIntervalMin(d.settings.interval_minutes)
        setAutoAnalyze(d.settings.auto_analyze)
        setAiScrape(d.settings.ai_scrape ?? true)
      })
      .catch((e) => toast('error', e.message))
  }, [toast])

  const loadGuide = useCallback(() => {
    api.get<Guide>('/intel/bridge/guide').then(setGuide).catch(() => {})
  }, [])

  const loadAnalyses = useCallback(() => {
    api
      .get<{ items: Analysis[] }>(`/intel/analyses?limit=40${evFilter ? `&symbol=${evFilter}` : ''}`)
      .then((d) => setAnalyses(d.items))
      .catch(() => {})
  }, [evFilter])

  useEffect(() => {
    loadOverview()
    loadGuide()
    const t = setInterval(loadOverview, 30000)
    return () => clearInterval(t)
  }, [loadOverview, loadGuide])

  useEffect(loadAnalyses, [loadAnalyses])

  const running = ov?.scheduler.current_run ?? null
  const monitorOn = Boolean(ov?.settings.monitor_enabled && ov?.scheduler.scheduler_alive)

  /** EventFeed 拉完数据回传，供「AI 买入建议」里的依据事件交叉引用 —— 避免重复请求 */
  const handleEvents = useCallback((items: EventItem[]) => setEvents(items), [])

  /* ---------------- 动作 ---------------- */
  const act = async (key: string, fn: () => Promise<any>, okMsg: string) => {
    setBusy(key)
    try {
      await fn()
      toast('success', okMsg)
      loadOverview()
      setRefreshToken((x) => x + 1)
      loadAnalyses()
    } catch (e: any) {
      toast('error', e.message)
    } finally {
      setBusy('')
    }
  }

  const startMonitor = () =>
    act(
      'monitor',
      () => api.post('/intel/monitor/start', { interval_minutes: intervalMin, auto_analyze: autoAnalyze, ai_scrape: aiScrape }),
      `监控已开启（周期 ${intervalMin} 分钟）`,
    )

  const stopMonitor = () => act('monitor', () => api.post('/intel/monitor/stop'), '监控已截止，报告已归档')

  const stopScrapePoll = () => {
    if (scrapeTimer.current) {
      clearInterval(scrapeTimer.current)
      scrapeTimer.current = null
    }
  }

  /* 内置 AI 立即抓取（后台任务版）：提交 → 2s 轮询进度 → 完成后汇总成功/失败明细。
     旧同步版问题：4 家公司要 2~6 分钟，前端 30s 超时报错但后端还在跑，用户全程无感知。
     范围由用户选，不再写死 4：
       · 未指定标的 → 按 scrapeLimit（0 = 全部待抓取）从待抓取清单取；
       · 指定标的   → 勾选即精确批次（后端不再按 limit 截断），点选顺序即抓取顺序。
     「勾了 7 家却只跑 4 家」是最容易被当成 bug 的行为，所以两种模式互斥且界面明示。 */
  const aiScrapeNow = () => {
    if (scrapeJob) return
    setBusy('ai-scrape')
    const pending = ov?.stats.tasks_pending ?? 0
    const picked = scrapeSymbols.length > 0
    const planned = picked
      ? scrapeSymbols.length
      : scrapeLimit <= 0
        ? pending
        : Math.min(scrapeLimit, pending || scrapeLimit)
    api
      .post<{ job_id: string }>('/intel/ai-scrape', {
        symbols: picked ? scrapeSymbols : [],
        limit: picked ? 0 : scrapeLimit,
        with_analysis: true,
        model,
      })
      .then((d) => {
        setScrapeJob({ id: d.job_id, progress: 0, total: planned, note: '任务已提交，等待调度…' })
        toast(
          'info',
          picked
            ? `抓取任务已启动（指定 ${planned} 家：${scrapeSymbols.join('、')}，每家约 30~90 秒），下方显示实时进度，可随时取消`
            : `抓取任务已启动（${planned} 家，每家约 30~90 秒），下方显示实时进度，可随时取消`,
        )
        scrapeTimer.current = setInterval(() => {
          api
            .get<{ status: string; progress: number; total: number; note: string; error: string; result: any }>(
              `/intel/job/${d.job_id}`,
            )
            .then((job) => {
              setScrapeJob((prev) => (prev ? { ...prev, progress: job.progress, total: job.total, note: job.note || '' } : prev))
              if (job.status === 'running') return
              stopScrapePoll()
              setScrapeJob(null)
              setBusy('')
              if (job.status === 'error') {
                toast('error', `抓取失败：${job.error}`)
              } else {
                const r = job.result || {}
                const errs: { symbol: string; error: string }[] = r.errors || []
                const summary = `抓取完成：${r.count ?? 0} 家 · 新增 ${r.events_inserted ?? 0} 条事件${r.cancelled ? '（已取消，未完成部分跳过）' : ''}`
                if (errs.length > 0) {
                  const detail = errs
                    .slice(0, 3)
                    .map((e) => `${e.symbol}：${e.error}`)
                    .join('；')
                  toast('warning', `${summary}。${errs.length} 家失败 —— ${detail}${errs.length > 3 ? ' 等' : ''}`)
                } else {
                  toast('success', summary)
                }
              }
              loadOverview()
              setRefreshToken((x) => x + 1)
              loadAnalyses()
            })
            .catch(() => {})
        }, 2000)
      })
      .catch((e) => {
        setBusy('')
        toast('error', e.message)
      })
  }

  const cancelScrape = () => {
    if (!scrapeJob) return
    api
      .post(`/intel/job/${scrapeJob.id}/cancel`)
      .then(() => toast('info', '已请求取消，当前公司处理完后停止'))
      .catch((e) => toast('error', e.message))
  }

  return (
    /* 布局铁律：不管上方（监控总控 + 每日必读）内容多少，底部三栏必须完整展示。
     · 根容器固定视口高度但允许溢出滚动（main 本身可滚，双保险）；
     · 下方 grid 有 min-h 保底 —— 上方卡片再高，也只会让页面出滚动条，绝不挤压 grid。 */
    <div className="flex h-[calc(100vh-88px)] min-h-[760px] flex-col gap-3 overflow-y-auto pr-0.5">
      <MonitorBar
        ov={ov}
        monitorOn={monitorOn}
        running={running}
        intervalMin={intervalMin}
        setIntervalMin={setIntervalMin}
        aiScrape={aiScrape}
        setAiScrape={setAiScrape}
        autoAnalyze={autoAnalyze}
        setAutoAnalyze={setAutoAnalyze}
        scrapeLimit={scrapeLimit}
        setScrapeLimit={setScrapeLimit}
        scrapeSymbols={scrapeSymbols}
        setScrapeSymbols={applyScrapeSymbols}
        busy={busy}
        model={model}
        setModel={setModel}
        modelOptions={modelOptions}
        defaultModel={defaultModel}
        scrapeJob={scrapeJob}
        onCancelScrape={cancelScrape}
        onStart={startMonitor}
        onStop={stopMonitor}
        onAiScrape={aiScrapeNow}
      />

      {/* AI 每日必读：强制提示区，固定在总控正下方（最显眼的位置） */}
      <DailyDigest onRefreshParent={loadOverview} />

      <div className="grid min-h-[460px] flex-1 grid-cols-12 gap-3">
        <div className="col-span-2 flex min-h-0 flex-col">
          <CompanyList
            companies={ov?.companies ?? []}
            enabled={ov?.stats.companies_enabled ?? 0}
            total={ov?.stats.companies_total ?? 0}
            selected={evFilter}
            onSelect={setEvFilter}
            onToggle={(c: Company, v: boolean) => act(`c-${c.id}`, () => api.put(`/intel/companies/${c.id}`, { enabled: v }), '已更新')}
            onAnalyze={(s) => act(`an-${s}`, () => api.post(`/intel/analyze/${s}`), `${s} 分析已生成`)}
            onDelete={(c: Company) => act(`d-${c.id}`, () => api.del(`/intel/companies/${c.id}`), '已移除')}
            onSync={() => act('sync-watch', () => api.post('/intel/companies/sync-watchlist'), '已与关注列表同步')}
            onAdd={(form) => act('add', () => api.post('/intel/companies', form), `已添加 ${form.symbol}`)}
            busy={busy}
          />
        </div>

        <div className="col-span-7 flex min-h-0 flex-col">
          <EventFeed
            companies={ov?.companies ?? []}
            symbol={evFilter}
            onSymbolChange={setEvFilter}
            analyses={analyses}
            refreshToken={refreshToken}
            onZoom={() => setZoomOpen(true)}
            onData={handleEvents}
          />
        </div>

        <div className="col-span-3 flex min-h-0 flex-col gap-3 overflow-y-auto pr-0.5">
          <LatestHint analyses={analyses} />
          <BridgeGuide
            guide={guide}
            onReload={loadGuide}
            busy={busy}
            onResetToken={() =>
              act('token', () => api.post('/intel/bridge-token/reset'), 'Token 已重置（旧 Token 立即失效）').then(loadGuide)
            }
          />
          <ProposalCard analyses={analyses} events={events} />
          <VerifyCard />
          <RunsPanel runs={(ov?.runs ?? []) as Run[]} />
        </div>
      </div>

      {/* 时间线放大弹窗（近全屏） */}
      <Modal
        open={zoomOpen}
        onClose={() => setZoomOpen(false)}
        title={evFilter ? `${evFilter} · 关键节点时间线（放大视图）` : '请先在左侧选择一家公司'}
        width="!max-w-[96vw]"
        className="h-[94vh] flex flex-col"
        bodyClass="min-h-0 flex-1 overflow-y-auto"
      >
        {evFilter ? (
          <div className="space-y-4 pr-1">
            <TimelineView symbol={evFilter} events={events} analysis={analyses.find((a) => a.symbol === evFilter) ?? null} big />
          </div>
        ) : (
          <Empty title="未选择公司" desc="先在左侧观察标的列表点击一家公司，再点放大" />
        )}
      </Modal>
    </div>
  )
}
