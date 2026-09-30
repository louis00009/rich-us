import { Activity, Info, RefreshCw, Sparkles } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Spinner } from '../ui'
import { api } from '../../lib/api'
import { MoverFilters } from './MoverFilters'
import { MoverList } from './MoverList'
import type { AiStatus, MoversResp } from './moverTypes'

/**
 * 每日开盘监控 —— 美股全池（SP500 + NDX100 + SP400 + SP600 + 市值补充 + 热门股 ≈ 2240 只）+ 全市场
 * 涨跌幅榜补盲（池外暴跌如 MDB 也可见），实时扫描。
 *
 * 三种用法：
 *  1. 打开页面即看：自动刷新间隔可选（关闭 / 30s / 1min / 2min / 5min，记忆在本地）；
 *  2. 开启「持续监控」：后端常驻线程按所选间隔扫描并写当日审计日志
 *     （关掉页面也在跑，配置持久化，服务重启自动恢复），手动关停即停；
 *  3. 「AI 解读」：下拉选择模型（与「设置 → AI 分析」同一套接入：
 *     默认全局模型 / QD_AI_EXTRA_MODELS 别名 / 网关模型 id），一键解读当前榜单。
 * 另有「刷新」按钮：强制后端立即重抓全池行情（约 1~2 分钟后生效）。
 *
 * ⚠️ 异动提示与 AI 解读都是观察辅助，不是交易信号。
 *
 * 结构：取数与编排在本文件；行列表见 MoverList.tsx，监控/模型控制条见 MoverFilters.tsx，
 * 共享类型见 moverTypes.ts。
 */

const THRESHOLDS = [1, 2, 3, 5, 7, 10]
// 页面自动刷新间隔（秒）；-1 = 关闭自动刷新（手动模式）
const POLL_CHOICES = [-1, 30, 60, 120, 300]

export default function MoversMonitor({ onOpenProfile }: { onOpenProfile: (sym: string) => void }) {
  const [threshold, setThreshold] = useState<number>(() => {
    const n = Number(localStorage.getItem('qd_movers_th'))
    return THRESHOLDS.includes(n) ? n : 3
  })
  const [intervalSec, setIntervalSec] = useState<number>(() => {
    const n = Number(localStorage.getItem('qd_movers_iv'))
    return [30, 60, 120, 300].includes(n) ? n : 60
  })
  const [model, setModel] = useState<string>(() => localStorage.getItem('qd_movers_model') || '')
  const [pollSec, setPollSec] = useState<number>(() => {
    const n = Number(localStorage.getItem('qd_movers_poll'))
    return POLL_CHOICES.includes(n) ? n : 30
  })
  const [data, setData] = useState<MoversResp | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [aiStatus, setAiStatus] = useState<AiStatus | null>(null)
  const [aiText, setAiText] = useState('')
  const [aiEngine, setAiEngine] = useState('')
  const [aiBusy, setAiBusy] = useState(false)
  const [monBusy, setMonBusy] = useState(false)
  const [manualBusy, setManualBusy] = useState(false)
  const seqRef = useRef(0)

  const load = useCallback(async () => {
    const seq = ++seqRef.current
    try {
      const r = await api.get<MoversResp>(
        `/market/rankings/movers?threshold=${threshold}&limit=12`,
        15_000,
      )
      if (seq !== seqRef.current) return
      setData(r)
      setError('')
    } catch (e: any) {
      if (seq !== seqRef.current) return
      setError(e?.message || '监控加载失败')
    } finally {
      if (seq === seqRef.current) setLoading(false)
    }
  }, [threshold])

  useEffect(() => {
    load()
    if (pollSec < 0) return undefined        // 自动刷新已关闭（手动模式）
    const t = setInterval(load, pollSec * 1000)
    return () => clearInterval(t)
  }, [load, pollSec])

  /** 手动刷新：强制后端立即重抓全池行情（立即返回旧数据；抓完由延时补拉取到新数据）。 */
  const refreshNow = async () => {
    setManualBusy(true)
    try {
      const r = await api.get<MoversResp>(
        `/market/rankings/movers?threshold=${threshold}&limit=12&force=true`,
        30_000,
      )
      setData(r)
      setError('')
      // 全池 ~2240 只抓取约 1~2 分钟：错峰补拉两次（load 自带序号防乱序）
      window.setTimeout(load, 45_000)
      window.setTimeout(load, 120_000)
    } catch (e: any) {
      setError(e?.message || '手动刷新失败')
    } finally {
      setManualBusy(false)
    }
  }

  // 模型清单：与「设置 → AI 分析」「AI Copilot」同一来源（别名 + 网关全部模型）
  useEffect(() => {
    api
      .get<AiStatus>('/ai/status', 15_000)
      .then(setAiStatus)
      .catch(() => setAiStatus(null))
  }, [])

  const postMonitor = async (patch: Record<string, unknown>, _okMsg?: string) => {
    setMonBusy(true)
    try {
      await api.post('/market/rankings/movers/monitor', patch, 15_000)
      localStorage.setItem('qd_movers_iv', String(intervalSec))
      localStorage.setItem('qd_movers_model', model)
      await load()
    } catch (e: any) {
      setError(e?.message || '监控开关操作失败')
    } finally {
      setMonBusy(false)
    }
  }

  const monitorOn = !!data?.monitor?.running || !!data?.monitor?.cfg?.enabled
  const analyzeNow = async () => {
    setAiBusy(true)
    setAiText('')
    try {
      const r = await api.post<{ engine: string; text: string; llm_error?: string }>(
        '/market/rankings/movers/analyze',
        { model, threshold, limit: 10 },
        150_000,
      )
      setAiText(r.text || '（无内容）')
      setAiEngine(r.engine || '')
    } catch (e: any) {
      setAiText(`解读失败：${e?.message || '未知错误'}`)
      setAiEngine('error')
    } finally {
      setAiBusy(false)
    }
  }

  const changeInterval = (v: number) => {
    setIntervalSec(v)
    if (monitorOn) postMonitor({ interval: v })
  }
  const changeModel = (v: string) => {
    setModel(v)
    localStorage.setItem('qd_movers_model', v)
  }

  const session = data?.status?.session
  const sessionLabel = data?.status?.session_label
    ?? (session === 'regular' ? '交易中' : session === 'extended' ? '盘前盘后' : '休市')
  const sessionCls =
    session === 'regular'
      ? 'bg-emerald-50 text-emerald-700'
      : session === 'extended'
        ? 'bg-amber-50 text-amber-700'
        : 'bg-slate-100 text-slate-500'
  const topRepeat = data?.log?.top_repeat ?? []

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-3">
      {/* 头部：标题 + 市场状态 + 数据时间 + 自动刷新 + 手动刷新 */}
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <Activity className="h-3.5 w-3.5 text-brand-600" />
        <span className="text-xs font-semibold text-slate-700">每日开盘监控</span>
        <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${sessionCls}`}>
          {session === 'regular' && <span className="mr-1 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500 align-middle" />}
          {sessionLabel}
        </span>
        <span className="text-[11px] text-slate-400">
          {data
            ? `${data.universe}${data.market_extra ? ` + 全市场榜 ${data.market_extra} 只` : ''}`
            : ''}
        </span>
        {loading && !data && <Spinner />}
        <span className="ml-auto text-[10px] text-slate-400" title="行情真正抓取完成的时刻（非页面刷新时刻）">
          行情更新于 <span className="num text-slate-600">{data?.quotes_updated?.slice(11) || '—'}</span>
          {data?.refreshing && <span className="ml-1 text-brand-600">· 后台刷新中…</span>}
        </span>
        <span className="inline-flex items-center gap-1 text-[10px] text-slate-400">
          自动刷新
          <select
            value={pollSec}
            onChange={(e) => {
              const v = Number(e.target.value)
              setPollSec(v)
              localStorage.setItem('qd_movers_poll', String(v))
            }}
            className="rounded border border-slate-200 bg-white px-1 py-0.5 text-[11px] text-slate-700"
            title="页面轮询间隔；关闭后仍可手动刷新，也不影响后端常驻监控"
          >
            {POLL_CHOICES.map((s) => (
              <option key={s} value={s}>
                {s < 0 ? '关闭' : s < 60 ? `${s} 秒` : `${s / 60} 分钟`}
              </option>
            ))}
          </select>
        </span>
        <button
          onClick={refreshNow}
          disabled={manualBusy}
          className="inline-flex items-center gap-1 rounded border border-brand-200 px-1.5 py-0.5 text-[11px] text-brand-700 transition-colors hover:bg-brand-50 disabled:opacity-50"
          title="强制后端立即重抓全池行情（约 1~2 分钟后生效，期间不影响查看当前榜单）"
        >
          {manualBusy ? <Spinner /> : <RefreshCw className="h-3 w-3" />}
          刷新
        </button>
      </div>

      {/* 控制条：持续监控开关 + 间隔 + 模型 + AI 解读 */}
      <MoverFilters
        data={data}
        monitorOn={monitorOn}
        monBusy={monBusy}
        threshold={threshold}
        intervalSec={intervalSec}
        model={model}
        aiStatus={aiStatus}
        aiBusy={aiBusy}
        onMonitorToggle={(patch) => postMonitor(patch)}
        onIntervalChange={changeInterval}
        onModelChange={changeModel}
        onAnalyze={analyzeNow}
      />
      {data?.monitor?.last_error && (
        <p className="mb-2 rounded bg-amber-50 px-2 py-1 text-[11px] text-amber-800">
          监控最近一轮异常：{data.monitor.last_error}
        </p>
      )}

      {error && <p className="mb-2 rounded bg-rose-50 px-2 py-1 text-[11px] text-rose-700">{error}</p>}
      {data?.note && (
        <p className="mb-2 flex items-start gap-1 rounded bg-slate-50 px-2 py-1 text-[11px] leading-4 text-slate-500">
          <Info className="mt-px h-3 w-3 shrink-0" />
          {data.note}
        </p>
      )}

      {aiText && (
        <div className="mb-2 rounded-lg border border-brand-100 bg-brand-50/40 px-3 py-2">
          <div className="mb-1 flex items-center gap-1.5 text-[10px] font-semibold text-brand-700">
            <Sparkles className="h-3 w-3" />
            AI 解读{aiEngine === 'llm' ? ` · ${model || aiStatus?.model || '默认模型'}` : ' · 本地统计兜底'}
            <button onClick={() => setAiText('')} className="ml-auto text-slate-400 hover:text-slate-600">
              收起
            </button>
          </div>
          <p className="whitespace-pre-wrap text-[11px] leading-5 text-slate-700">{aiText}</p>
        </div>
      )}

      {/* 双榜：暴涨 / 暴跌 —— 配色跟随全局设置（涨=红 / 欧美习惯自动反转） */}
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-lg border border-slate-100 bg-slate-50/40 p-2">
          <MoverList rows={data?.gainers ?? []} side="up" threshold={data?.threshold ?? threshold} onOpenProfile={onOpenProfile} />
        </div>
        <div className="rounded-lg border border-slate-100 bg-slate-50/40 p-2">
          <MoverList rows={data?.losers ?? []} side="down" threshold={data?.threshold ?? threshold} onOpenProfile={onOpenProfile} />
        </div>
      </div>

      {/* 当日统计：累计触发 + 持续异动（反复上榜）标的 */}
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] leading-4 text-slate-400">
        <span>
          今日已记录 <span className="num font-medium text-slate-600">{data?.log?.events ?? 0}</span> 次异动 ·
          涉及 <span className="num font-medium text-slate-600">{data?.log?.symbols ?? 0}</span> 只标的
        </span>
        {topRepeat.length > 0 && (
          <span className="min-w-0 truncate">
            持续异动：
            {topRepeat.map((d) => (
              <span key={d.symbol} className="mr-1.5">
                <button
                  onClick={() => onOpenProfile(d.symbol)}
                  className="font-medium text-slate-500 underline decoration-dotted hover:text-brand-700"
                >
                  {d.symbol}
                </button>
                <span className="num"> ×{d.hits}</span>
              </span>
            ))}
          </span>
        )}
        <span className="ml-auto shrink-0">
          行情约 15 分钟延迟 · 异动与 AI 解读均为观察辅助，不是交易信号
        </span>
      </div>
    </div>
  )
}
