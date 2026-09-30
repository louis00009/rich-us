import { Play, Sparkles, Square } from 'lucide-react'
import { Spinner } from '../ui'
import type { AiStatus, MoversResp } from './moverTypes'

// 常驻监控扫描间隔（秒）
const INTERVALS = [30, 60, 120, 300]

interface MoverFiltersProps {
  data: MoversResp | null
  monitorOn: boolean
  monBusy: boolean
  threshold: number
  intervalSec: number
  model: string
  aiStatus: AiStatus | null
  aiBusy: boolean
  onMonitorToggle: (patch: Record<string, unknown>) => void
  onIntervalChange: (v: number) => void
  onModelChange: (v: string) => void
  onAnalyze: () => void
}

/** 控制条：持续监控开关 + 扫描间隔 + 模型选择 + AI 解读按钮。 */
export function MoverFilters({
  data,
  monitorOn,
  monBusy,
  threshold,
  intervalSec,
  model,
  aiStatus,
  aiBusy,
  onMonitorToggle,
  onIntervalChange,
  onModelChange,
  onAnalyze,
}: MoverFiltersProps) {
  const extraModels = aiStatus?.extra_models ?? []
  const cnModels = aiStatus?.models_by_realm?.cn ?? []
  const globalModels = aiStatus?.models_by_realm?.global ?? []
  return (
    <div className="mb-2 flex flex-wrap items-center gap-2 rounded-lg bg-slate-50 px-2 py-1.5">
      {monitorOn ? (
        <button
          onClick={() => onMonitorToggle({ enabled: false })}
          disabled={monBusy}
          className="inline-flex items-center gap-1 rounded-md bg-rose-50 px-2 py-1 text-[11px] font-semibold text-rose-700 transition-colors hover:bg-rose-100 disabled:opacity-50"
          title="关停后端常驻监控（停止后台扫描，页面手动轮询不受影响）"
        >
          <Square className="h-3 w-3" />
          关停监控
        </button>
      ) : (
        <button
          onClick={() => onMonitorToggle({ enabled: true, threshold, interval: intervalSec, model })}
          disabled={monBusy}
          className="inline-flex items-center gap-1 rounded-md bg-emerald-50 px-2 py-1 text-[11px] font-semibold text-emerald-700 transition-colors hover:bg-emerald-100 disabled:opacity-50"
          title="开启后端常驻监控：按所选间隔持续扫描并记录，关页面也在跑，服务重启自动恢复"
        >
          <Play className="h-3 w-3" />
          开启持续监控
        </button>
      )}
      {monitorOn && (
        <span className="inline-flex items-center gap-1 text-[10px] text-emerald-700" title="后端常驻监控运行中">
          <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" />
          运行中 · 已扫 {data?.monitor?.scans ?? 0} 轮
          {data?.monitor?.last_scan ? ` · 最近 ${data.monitor.last_scan.slice(11, 19)}` : ''}
        </span>
      )}
      <span className="text-[11px] text-slate-400">扫描间隔</span>
      <select
        value={intervalSec}
        onChange={(e) => onIntervalChange(Number(e.target.value))}
        className="rounded border border-slate-200 bg-white px-1.5 py-0.5 text-[11px] text-slate-700"
        title="常驻监控的扫描间隔"
      >
        {INTERVALS.map((s) => (
          <option key={s} value={s}>
            {s < 60 ? `${s}s` : `${s / 60}min`}
          </option>
        ))}
      </select>
      <span className="text-[11px] text-slate-400">模型</span>
      <select
        value={model}
        onChange={(e) => onModelChange(e.target.value)}
        className="max-w-40 rounded border border-slate-200 bg-white px-1.5 py-0.5 text-[11px] text-slate-700"
        title="AI 解读使用的模型（与「设置 → AI 分析」同一套接入）"
      >
        <option value="">默认模型{aiStatus?.model ? `（${aiStatus.model}）` : ''}</option>
        {extraModels.length > 0 && (
          <optgroup label="别名 / 已接入">
            {extraModels.map((m) => (
              <option key={m} value={m}>{m}</option>
            ))}
          </optgroup>
        )}
        {cnModels.length > 0 && (
          <optgroup label="国内">
            {cnModels.map((m) => (
              <option key={m} value={m}>{m}</option>
            ))}
          </optgroup>
        )}
        {globalModels.length > 0 && (
          <optgroup label="国际">
            {globalModels.map((m) => (
              <option key={m} value={m}>{m}</option>
            ))}
          </optgroup>
        )}
      </select>
      <button
        onClick={onAnalyze}
        disabled={aiBusy || !data}
        className="inline-flex items-center gap-1 rounded-md border border-brand-200 px-2 py-1 text-[11px] font-medium text-brand-700 transition-colors hover:bg-brand-50 disabled:opacity-50"
        title="用所选模型解读当前暴涨/暴跌榜单（行情 + 部分标的新闻标题）"
      >
        {aiBusy ? <Spinner /> : <Sparkles className="h-3 w-3" />}
        AI 解读
      </button>
      {!aiStatus?.llm_configured && (
        <span className="text-[10px] text-slate-400" title="在「设置 → AI 分析」配置网关后即可用模型解读">
          未配 LLM · 解读为本地统计
        </span>
      )}
    </div>
  )
}
