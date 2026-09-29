/**
 * 行情页 · 图表区（主图 + 技术指标 + 成交量）
 *
 * 含：加载态 / 无数据态、公司情报切换、K 线·分时·折线三态、快速周期选择框、
 * 技术指标副图与成交量图。
 *
 * 从 `pages/Market.tsx` 抽出（铁律 9 拆分，2026-09-29）。
 */
import { LineChart as LineIcon, Star } from 'lucide-react'
import { Badge, Card, Empty, Loading, Tabs } from '../ui'
import CandleChart from '../CandleChart'
import IntradayChart from '../IntradayChart'
import { PriceChart } from '../charts'
import CompanyIntel from '../CompanyIntel'
import { fmtNum, getColorMode, signClass } from '../../lib/format'
import type { Quote } from '../../lib/types'
import { QUICK_RANGES } from './constants'
import type { ChartType, HistoryResp, IntradayResp } from './types'

export interface OverlayLine {
  name: string
  data: (number | null)[]
  color: string
  dashed?: boolean
}
export interface LevelLine {
  value: number
  label: string
  color: string
}
export interface SubSeries {
  data: (number | null)[]
  extra: any[]
  label: string
  unit: string
}

export function ChartPanel({
  loading,
  hist,
  view,
  setView,
  chartType,
  setChartType,
  intra,
  intraError,
  overlays,
  levels,
  subChart,
  setSubChart,
  subSeries,
  symbol,
  watchedSet,
  favBusy,
  toggleWatched,
  shownQuote,
  range,
  applyQuick,
}: {
  loading: boolean
  hist: HistoryResp | null
  view: 'chart' | 'intel'
  setView: (v: 'chart' | 'intel') => void
  chartType: ChartType
  setChartType: (v: ChartType) => void
  intra: IntradayResp | null
  intraError: string
  overlays: OverlayLine[]
  levels: LevelLine[]
  subChart: string
  setSubChart: (v: string) => void
  subSeries: SubSeries
  symbol: string
  watchedSet: Set<string>
  favBusy: boolean
  toggleWatched: () => void
  shownQuote: Quote | undefined
  range: string
  applyQuick: (key: string) => void
}) {
  return (
    <div className="space-y-5 xl:col-span-3 xl:order-1">
      {loading && !hist ? (
        <Card>
          <Loading label="正在获取行情…" />
        </Card>
      ) : hist ? (
        view === 'intel' ? (
          <CompanyIntel symbol={symbol} />
        ) : (
          <>
            <Card
              title={
                <span className="flex items-center gap-2">
                  {hist.symbol}
                  {/* 收藏按钮：一键加入/移出关注列表，收藏后出现在快速选择与下方收藏池 */}
                  <button
                    onClick={toggleWatched}
                    disabled={favBusy}
                    title={watchedSet.has(symbol) ? '取消收藏' : '收藏到我的关注'}
                    className="rounded p-0.5 transition-colors hover:bg-slate-100 disabled:opacity-50"
                  >
                    <Star
                      className={`h-4 w-4 transition-colors ${
                        watchedSet.has(symbol) ? 'fill-amber-400 text-amber-400' : 'text-slate-300 hover:text-amber-400'
                      }`}
                    />
                  </button>
                  {shownQuote && (
                    <span className={`num text-base ${signClass(shownQuote.change_pct)}`}>
                      {fmtNum(shownQuote.price, 2)}
                      <span className="ml-2 text-xs">
                        {shownQuote.change > 0 ? '+' : ''}
                        {fmtNum(shownQuote.change, 2)} ({shownQuote.change_pct > 0 ? '+' : ''}
                        {shownQuote.change_pct.toFixed(2)}%)
                      </span>
                      <span className="ml-2 inline-flex items-center gap-1 text-[10px] text-emerald-600">
                        <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" />
                        LIVE
                      </span>
                    </span>
                  )}
                </span>
              }
              subtitle={
                chartType === 'intraday' && intra
                  ? `${intra.is_today ? '当日' : `交易日 ${intra.trade_date || ''}`}分时 ｜ ${intra.count} 根 1 分钟 ｜ 数据源 ${intra.source}${intra.delayed ? '（约 15 分钟延迟）' : '（实时）'}`
                  : `${hist.count} 根 bar ｜ 数据源 ${hist.source}${hist.realtime ? '（末根为实时价）' : ''} ｜ ${hist.dates[0]?.slice(0, 10)} ~ ${hist.dates[hist.dates.length - 1]?.slice(0, 10)}`
              }
              actions={
                <div className="flex items-center gap-2">
                  <Badge tone={hist.source === 'synthetic' ? 'amber' : hist.source === 'ibkr' ? 'green' : 'slate'}>
                    {hist.source}
                  </Badge>
                  <Tabs
                    value={view}
                    onChange={(k) => setView(k as 'chart' | 'intel')}
                    tabs={[
                      { key: 'chart', label: '图表' },
                      { key: 'intel', label: '公司情报' },
                    ]}
                  />
                  <span className="mx-1 h-5 w-px bg-slate-200" />
                  <Tabs
                    value={chartType}
                    onChange={(k) => setChartType(k as ChartType)}
                    tabs={[
                      { key: 'candle', label: 'K 线' },
                      { key: 'intraday', label: '分时' },
                      { key: 'line', label: '折线' },
                    ]}
                  />
                </div>
              }
            >
              {/* 快速周期选择框：分时(24H) / 一周 / 一月 / 3 月 / 半年 / 1 年 */}
              <div className="mb-3 flex flex-wrap items-center gap-1.5">
                <span className="mr-1 text-[11px] text-slate-400">快速周期</span>
                <button
                  onClick={() => setChartType('intraday')}
                  className={`rounded-lg border px-2.5 py-1 text-xs transition-colors ${
                    chartType === 'intraday'
                      ? 'border-brand-400 bg-brand-50 font-semibold text-brand-700'
                      : 'border-slate-200 text-slate-600 hover:border-brand-300 hover:bg-slate-50'
                  }`}
                >
                  分时 (24H)
                </button>
                {QUICK_RANGES.map((q) => (
                  <button
                    key={q.key}
                    onClick={() => applyQuick(q.key)}
                    className={`rounded-lg border px-2.5 py-1 text-xs transition-colors ${
                      chartType !== 'intraday' && range === q.key
                        ? 'border-brand-400 bg-brand-50 font-semibold text-brand-700'
                        : 'border-slate-200 text-slate-600 hover:border-brand-300 hover:bg-slate-50'
                    }`}
                  >
                    {q.label}
                  </button>
                ))}
                <span className="ml-2 hidden text-[11px] text-slate-300 sm:inline">
                  1 周/1 月含小时线；更细周期与区间用上方「周期区间 / K 线周期」自定义
                </span>
              </div>
              {chartType === 'candle' ? (
                <CandleChart
                  dates={hist.dates}
                  open={hist.open}
                  high={hist.high}
                  low={hist.low}
                  close={hist.close}
                  volume={hist.volume}
                  overlays={overlays}
                  levels={levels}
                  height={430}
                  showVolume
                  colorMode={getColorMode()}
                />
              ) : chartType === 'intraday' ? (
                intra ? (
                  <>
                    <IntradayChart
                      points={intra.points}
                      prevClose={intra.prev_close}
                      height={430}
                      colorMode={getColorMode()}
                    />
                    {intra.is_today === false && (
                      <div className="mt-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
                        当前非交易时段（或数据未更新），展示的是最近交易日 <b>{intra.trade_date}</b> 的分时走势。
                      </div>
                    )}
                    {intra.delayed && (
                      <div className="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                        ⚠️ 当前分时来自免费源（{intra.source}），日内数据约有 15 分钟延迟；接入 IBKR 行情后自动切换为实时。
                      </div>
                    )}
                  </>
                ) : intraError ? (
                  <div className="py-16 text-center text-sm text-slate-400">
                    {intraError}
                    <div className="mt-1 text-[11px] text-slate-300">30 秒后自动重试；也可切换数据源或稍后再试</div>
                  </div>
                ) : (
                  <div className="py-16 text-center text-sm text-slate-400">正在加载分时…（30 秒自动刷新）</div>
                )
              ) : (
                <PriceChart dates={hist.dates} close={hist.close} overlays={overlays} levels={levels} height={430} />
              )}
            </Card>
            {view === 'chart' && (
              <>
                <Card
                  title="技术指标"
                  actions={
                    <Tabs
                      value={subChart}
                      onChange={setSubChart}
                      tabs={[
                        { key: 'rsi', label: 'RSI' },
                        { key: 'macd', label: 'MACD' },
                        { key: 'adx', label: 'ADX' },
                        { key: 'vol', label: '波动率' },
                      ]}
                    />
                  }
                >
                  <PriceChart
                    dates={hist.dates}
                    close={subSeries.data as number[]}
                    overlays={subSeries.extra}
                    height={190}
                  />
                </Card>

                <Card title="成交量" subtitle="用于识别放量突破与缩量整理">
                  <PriceChart dates={hist.dates} close={hist.volume} height={150} />
                </Card>
              </>
            )}
          </>
        )
      ) : (
        <Card>
          <Empty icon={<LineIcon className="h-8 w-8" />} title="未获取到行情" desc="请检查标的代码，或稍后重试" />
        </Card>
      )}
    </div>
  )
}
