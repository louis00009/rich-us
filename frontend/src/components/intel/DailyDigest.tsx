/**
 * AI 每日必读（强制提示）
 *
 * 用户需求原文：「做一个部分是 AI 的强制提示，解释每天从新闻里面抓出来的信息
 * 有哪些是非常重要的，这些信息需要被 AI 主动分析并且记录，提醒用户可以买入这些
 * 股票、在什么时机是一个好的机会。」
 *
 * 三条需求分别对应本组件的三块：
 *   ① 「哪些非常重要」 → 后端确定性重要度排序后的必读清单（含「为什么重要」理由）
 *   ② 「主动分析并且记录」 → 清单由调度器每轮自动生成并落库（纯规则、不调 LLM，
 *      所以每轮都能跑）；AI 深度解读是可选增强，**手动触发**（遵守项目铁律：
 *      打开/刷新页面不得自动跑 AI）。留痕可在「历史记录」里查。
 *   ③ 「什么时机是好机会」 → 时机页签：关注区间 / 触发条件 / 失效条件，
 *      价位全部来自平台量化支撑阻力，缺失就如实写「数据未覆盖」。
 *
 * 边界：这是**提醒与观察序列**，不是买入信号 —— 卡片底部常驻免责行，
 * 且措辞统一用「关注 / 观察 / 时机」，不使用「建议买入」。
 *
 * 结构（铁律 9 拆分，2026-09-29）：本文件此前 501 行、超 400 软上限，
 * 三个纯展示子组件与 localStorage 副作用已抽到 `./digest/`：
 *   `digest/seen.ts`（已读标记）、`digest/TopItem.tsx`、`digest/SymbolRow.tsx`、
 *   `digest/WatchCard.tsx`。本文件只保留编排（取数 + 状态 + 页签布局）。
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Bell, BookOpenCheck, History, RefreshCw, Sparkles, Target, TrendingUp } from 'lucide-react'
import { Badge, Button, Card, Empty, Select, Tabs, useToast } from '../ui'
import { api } from '../../lib/api'
import { aiAssist } from '../../lib/ai'
import { MarkdownLite } from '../AIAssist'
import { markSeen, readSeen } from './digest/seen'
import HistoryModal from './digest/HistoryModal'
import { SymbolRow } from './digest/SymbolRow'
import { TopItem } from './digest/TopItem'
import { WatchCard } from './digest/WatchCard'
import NewsFlow from './digest/NewsFlow'
import { type Digest, fmtSince, fmtUtc, sentimentColor } from './types'

export default function DailyDigest({
  onRefreshParent,
  refreshToken = 0,
}: {
  onRefreshParent?: () => void
  refreshToken?: number
}) {
  const toast = useToast()
  const [d, setD] = useState<Digest | null>(null)
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState('')
  const [tab, setTab] = useState('top')
  const [histOpen, setHistOpen] = useState(false)
  const [seenDate, setSeenDate] = useState('')
  const [expanded, setExpanded] = useState(true)
  /* 自动更新间隔（分钟，0=关闭）：到点自动「重算」。重算是纯规则计算（不调 LLM），
     所以可以放心定时跑；AI 深度解读依旧只手动触发（项目铁律：打开页面不得自动跑 AI）。
     选择持久化在 localStorage，跨会话生效。 */
  const [autoMin, setAutoMin] = useState<number>(() => {
    try {
      return Number(localStorage.getItem('qd.intel.digest.autorefresh') || 0)
    } catch {
      return 0
    }
  })

  const changeAuto = (v: number) => {
    setAutoMin(v)
    try {
      localStorage.setItem('qd.intel.digest.autorefresh', String(v))
    } catch {
      /* localStorage 不可用时仅本次会话生效 */
    }
  }

  const load = useCallback(
    (rebuild = false, silent = false) => {
      if (!silent) setLoading(true)
      const req = rebuild ? api.post<Digest>('/intel/digest/rebuild', {}) : api.get<Digest>('/intel/digest')
      req
        .then((data) => {
          setD(data)
          /* 兼容旧落库 payload（没有 top_date 字段）：自动重算一次补齐日期 —— 纯规则计算，非 LLM，只递归这一次 */
          if (!rebuild && (data.by_symbol?.length ?? 0) > 0 && (data.by_symbol[0] as any)?.top_date === undefined) {
            load(true)
          }
        })
        .catch((e) => {
          if (!silent) toast('error', e.message)
        })
        .finally(() => {
          if (!silent) setLoading(false)
        })
    },
    [toast],
  )

  useEffect(() => {
    load()
    setSeenDate(readSeen()[new Date().toISOString().slice(0, 10)] || '')
  }, [load])

  /* 实时性保证 ①：父级 refreshToken 变化（抓取任务完成 / 监控动作）→ 立即重载。
     GET 是轻量的（有落库行且不落后于最新事件时只读一行），后端发现落后会自动重算。 */
  useEffect(() => {
    if (!refreshToken) return
    load()
  }, [refreshToken, load])

  /* 实时性保证 ②：30s 轻量轮询。监控在后台抓到新数据时，就算用户没有做任何操作，
     每日必读也会在半分钟内自动出现新内容（后端过期判定 + 节流，正常情况只读一行）。 */
  useEffect(() => {
    const t = setInterval(() => load(false, true), 30_000)
    return () => clearInterval(t)
  }, [load])

  /* 自动更新：到点自动「重算」（规则计算，非 LLM）。必须在 load 声明之后注册。 */
  useEffect(() => {
    if (!autoMin) return
    const t = setInterval(() => load(true), autoMin * 60_000)
    return () => clearInterval(t)
  }, [autoMin, load])

  const runAnalyze = async () => {
    if (!d) return
    setBusy('analyze')
    try {
      // 走全平台统一 AI 入口（AI Task Hub）：任务名必须是后端已注册的 key。
      // llm_text 不回传，避免把上一次的解读再塞进 prompt 浪费 token。
      const { llm_text: _prev, ...payload } = d
      const res = await aiAssist('intel_digest', { digest: payload })
      if (!res.text) throw new Error('AI 返回空内容')
      // 落库留痕 —— 用户要求「这些信息需要被 AI 主动分析并且记录」
      const rec = await api.post<Digest>('/intel/digest/record', {
        text: res.text,
        engine: res.engine,
        llm_error: res.llm_error || '',
      })
      setD(rec)
      toast(
        res.engine === 'llm' ? 'success' : 'warning',
        res.engine === 'llm' ? 'AI 深度解读已生成并记录' : 'AI 网关不可用，已用规则化摘要兜底并如实标注',
      )
      onRefreshParent?.()
    } catch (e: any) {
      toast('error', e.message)
    } finally {
      setBusy('')
    }
  }

  /** 用户真正「看过」才算已读：展开/收起或切换页签都算确认 —— 未读徽章才有意义 */
  const acknowledge = useCallback(() => {
    if (!d?.digest_date) return
    markSeen(d.digest_date)
    setSeenDate(new Date().toISOString())
  }, [d?.digest_date])

  const toggle = () => {
    setExpanded((v) => !v)
    acknowledge()
  }

  const totals = d?.totals ?? {}
  const unread = Boolean(d?.digest_date) && !seenDate && (totals.top ?? 0) > 0
  const dateLabel = d?.digest_date ? `归集日 ${d.digest_date} · 窗口 ${d.days} 天` : '尚未生成'
  const coverage = useMemo(() => {
    const ev = totals.events ?? 0
    const top = totals.top ?? 0
    return ev > 0 ? Math.round((top / ev) * 100) : 0
  }, [totals.events, totals.top])

  return (
    <Card
      className="shrink-0"
      bodyClass="space-y-3"
      title={
        <span className="flex items-center gap-2">
          AI 每日必读
          {unread && (
            <span className="inline-flex items-center gap-1 rounded-full bg-rose-600 px-2 py-0.5 text-[11px] font-semibold text-white">
              <Bell className="h-3 w-3" />
              未读
            </span>
          )}
        </span>
      }
      subtitle={`${dateLabel} · 由规则确定性地从当日新闻里挑出必读条目（非 LLM 判断），AI 深度解读为可选增强`}
      actions={
        <div className="flex flex-wrap items-center gap-1.5">
          <label
            className="flex items-center gap-1 text-[11px] text-slate-500"
            title="定时自动「重算」每日必读（规则计算，不调 AI、不烧 token）。AI 深度解读仍需手动点击。"
          >
            自动更新
            <Select value={String(autoMin)} onChange={(e) => changeAuto(Number(e.target.value))} className="!w-[86px]">
              <option value={0}>关闭</option>
              <option value={5}>5 分钟</option>
              <option value={15}>15 分钟</option>
              <option value={30}>30 分钟</option>
              <option value={60}>60 分钟</option>
            </Select>
          </label>
          <Button size="sm" variant="ghost" icon={<History className="h-3.5 w-3.5" />} onClick={() => setHistOpen(true)}>
            记录
          </Button>
          <Button size="sm" variant="ghost" icon={<RefreshCw className="h-3.5 w-3.5" />} loading={loading} onClick={() => load(true)}>
            重算
          </Button>
          <Button
            size="sm"
            variant="primary"
            icon={<Sparkles className="h-3.5 w-3.5" />}
            loading={busy === 'analyze'}
            disabled={!d?.available || (totals.top ?? 0) === 0}
            title={
              d?.llm_configured
                ? '让 AI 解读今日必读：谁最重要、为什么、时机与风险（手动触发，不会自动运行）'
                : '未配置 AI：仍可用规则化摘要兜底'
            }
            onClick={runAnalyze}
          >
            AI 深度解读
          </Button>
          <Button size="sm" variant="ghost" onClick={toggle}>
            {expanded ? '收起' : '展开'}
          </Button>
        </div>
      }
    >
      {/* 概览条：不论展开与否都在，保证「强制提示」始终可见（在滚动区外） */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-lg border border-brand-100 bg-brand-50/50 px-3 py-2 text-[11px]">
        <span className="text-slate-600">
          窗口内 <b className="num text-slate-900">{totals.events ?? 0}</b> 条事件
          {(totals.today ?? 0) > 0 && (
            <span className="text-emerald-600">
              {' '}· 今日新增 <b className="num">{totals.today}</b>
            </span>
          )}
        </span>
        <span className="text-rose-600">重大 {totals.critical ?? 0}</span>
        <span className="text-amber-600">重要 {totals.high ?? 0}</span>
        <span className="text-slate-300">|</span>
        <span style={{ color: sentimentColor('positive') }}>利好 {totals.positive ?? 0}</span>
        <span style={{ color: sentimentColor('negative') }}>利空 {totals.negative ?? 0}</span>
        <span className="text-slate-300">|</span>
        <span className="text-slate-600">
          必读 <b className="num text-slate-900">{totals.top ?? 0}</b> 条 · 涉及{' '}
          <b className="num text-slate-900">{totals.symbols ?? 0}</b> 只标的
        </span>
        {/* 心跳：最新入库时刻 —— 数据到了必读就同步，这条让「更新」可见可查 */}
        {d?.last_event_at && (
          <span className="text-slate-600" title={`最新事件入库于 ${fmtUtc(d.last_event_at)}`}>
            最新入库 <b className="num text-slate-900">{fmtSince(d.last_event_at)}</b>
          </span>
        )}
        {coverage > 0 && <span className="text-slate-400">（仅占事件总量的 {coverage}%）</span>}
        {/* 用户硬要求：具体日期优先 —— 相对时间只作括号辅助 */}
        <span className="ml-auto flex items-center gap-2 text-slate-400">
          {d?.updated_at && (
            <span title={`更新时刻：${fmtUtc(d.updated_at)}`}>
              更新 {fmtUtc(d.updated_at)}（{fmtSince(d.updated_at)}）
            </span>
          )}
          {d?.generated_by && <Badge tone="slate">{d.generated_by === 'scheduler' ? '调度器自动记录' : '手动生成'}</Badge>}
        </span>
      </div>

      {/* 展开内容不再限高（2026-09-30）：必读本就只留 top N 条，全量展开配合
          页面级滚动，可读性最好 —— 旧的卡片内滚（40vh→60vh 两版）都被用户抱怨可视度差。
          页签常驻（2026-09-30）：「全部新闻」在必读为空时也要能看 —— 那正是
          「系统在跑但暂无高影响事件」时查看原始新闻流的入口。 */}
      {!expanded ? null : (
        <div className="space-y-3">
          <Tabs
            value={tab}
            onChange={(k) => {
              setTab(k)
              acknowledge()
            }}
            tabs={[
              { key: 'top', label: '必读清单', badge: d?.top.length ?? 0 },
              { key: 'symbols', label: '该盯哪几家', badge: d?.by_symbol.length ?? 0 },
              { key: 'watch', label: '买入时机', badge: d?.watch.length ?? 0 },
              { key: 'news', label: '全部新闻' },
            ]}
          />

          {tab === 'news' ? (
            /* 全部新闻流：近 N 天入库的全量事件，按入库时间倒序（新抓的排最上） */
            <NewsFlow refreshToken={refreshToken} />
          ) : !d?.available || (totals.top ?? 0) === 0 ? (
            <Empty
              icon={<BookOpenCheck className="h-8 w-8" />}
              title={loading ? '正在生成今日必读…' : '今日没有达到必读阈值的条目'}
              desc={
                loading
                  ? '首次生成需要给候选标的读量化快照，约 5~8 秒'
                  : '监控每轮会自动重算并记录；也可点右上「重算」。若长期为空，说明抓取到的信息里没有高影响事件。'
              }
            />
          ) : (
            <>

          {tab === 'top' && (
            <>
              <ul className="space-y-2">
                {d.top.map((it, i) => (
                  <TopItem key={it.id} it={it} rank={i + 1} />
                ))}
              </ul>
              {d.notes.length > 0 && (
                <div className="rounded-lg bg-slate-50 px-3 py-2 text-[11px] leading-relaxed text-slate-400">
                  {d.notes.map((n) => (
                    <div key={n}>· {n}</div>
                  ))}
                </div>
              )}
            </>
          )}

          {tab === 'symbols' && (
            <>
              <p className="text-[11px] text-slate-400">
                按「最高重要度」排序 —— 决定今天把研究时间花在哪几家。AI 判定列来自最近一次建议（不一定是今天）。
              </p>
              <ul className="space-y-1.5">
                {d.by_symbol.map((s) => (
                  <SymbolRow key={s.symbol} s={s} />
                ))}
              </ul>
            </>
          )}

          {tab === 'watch' && (
            <>
              <p className="text-[11px] text-slate-400">
                入选条件：出现高重要度利好事件，或 AI 判定看多。价位全部取自平台量化支撑/阻力与 ATR，
                取不到就写「数据未覆盖」—— 不做估算，也不构成买入指令。
              </p>
              {d.watch.length === 0 ? (
                <Empty icon={<Target className="h-8 w-8" />} title="暂无时机候选" desc="当日没有出现高重要度利好事件、也没有看多判定" />
              ) : (
                <ul className="space-y-2">
                  {d.watch.map((w) => (
                    <WatchCard key={w.symbol} w={w} />
                  ))}
                </ul>
              )}
            </>
          )}

          {/* AI 深度解读结果（手动触发后才会有） */}
          {d.llm_text ? (
            <div className="rounded-lg border border-violet-200 bg-violet-50/40 p-3">
              <div className="mb-1.5 flex flex-wrap items-center gap-2 text-[11px]">
                <Sparkles className="h-3.5 w-3.5 text-violet-500" />
                <span className="font-semibold text-violet-800">AI 深度解读</span>
                <Badge tone={d.llm_engine === 'llm' ? 'violet' : 'slate'}>{d.llm_engine === 'llm' ? '大模型生成' : '规则化兜底'}</Badge>
                {d.updated_at && <span className="ml-auto text-slate-400">记录于 {fmtUtc(d.updated_at)}</span>}
              </div>
              <MarkdownLite text={d.llm_text} />
            </div>
          ) : (
            <div className="flex flex-wrap items-center gap-2 rounded-lg border border-dashed border-slate-200 px-3 py-2.5 text-[11px] text-slate-500">
              <TrendingUp className="h-3.5 w-3.5 text-slate-400" />
              尚未生成 AI 深度解读。点右上「AI 深度解读」让 AI 逐条说明：谁最重要、为什么、时机与风险
              <span className="ml-auto text-slate-400">（手动触发，打开页面不会自动跑）</span>
            </div>
          )}

          <p className="text-[11px] text-slate-400">
            本清单为研究与观察用途，不构成投资建议；平台所有交易动作必须经 AI 提案 + 人工批准。
          </p>
            </>
          )}
        </div>
      )}

      {/* 记录留痕弹窗：自含取数，拆到 digest/HistoryModal（FILE_SIZE_DEBT） */}
      <HistoryModal open={histOpen} onClose={() => setHistOpen(false)} />
    </Card>
  )
}
