/**
 * ResultPanel —— 回测结果区
 * ==========================
 * 从 pages/Backtest.tsx 抽出（铁律 9）。自持「结果页签」状态，其余全部受控。
 *
 * 小白友好化的两处关键改动：
 *  ① **先给结论再给指标**：指标表前面插了 `ResultSummary`（一句话结论 + 泼冷水），
 *     不让用户自己去把 24 个指标翻译成人话；
 *  ② **每个指标名都能悬停**：指标名不再是一串看不懂的术语，鼠标放上去就是
 *     「是什么 / 怎么看」（词条见 glossary.ts，key 与后端 metric key 一一对应）。
 */
import { useEffect, useState } from 'react'
import { BarChart3, Download } from 'lucide-react'
import AIAssist from '../AIAssist'
import { EquityChart, MonthlyBars, MonthlyHeatmap } from '../charts'
import { symbolsToList, symbolsToInput } from '../../lib/backtestPrefs'
import { METRIC_LABEL, fmtMoney, fmtNum, fmtRatioPct, signClass } from '../../lib/format'
import type { BacktestResult, TradeRow } from '../../lib/types'
import { Alert, Badge, Button, Card, DataTable, Empty, Stat, Tabs } from '../ui'
import { ResultSummary } from './PlainSummary'
import { TermTip } from '../terms/TermTip'

/** 指标分组。key 必须与 glossary / 后端 METRIC_LABELS 一致（否则悬停没有解释）。 */
const METRIC_GROUPS: { title: string; keys: string[] }[] = [
  { title: '收益', keys: ['total_return', 'cagr', 'excess_cagr', 'best_month', 'worst_month'] },
  { title: '风险', keys: ['volatility', 'max_drawdown', 'max_dd_days', 'var95_daily', 'cvar95_daily'] },
  { title: '风险调整', keys: ['sharpe', 'sortino', 'calmar', 'information_ratio', 'beta'] },
  {
    title: '交易行为',
    keys: ['trades', 'win_rate', 'profit_factor', 'payoff_ratio', 'expectancy', 'avg_bars_held', 'turnover', 'avg_exposure'],
  },
]

const PCT_KEYS = [
  'total_return', 'cagr', 'excess_cagr', 'volatility', 'max_drawdown', 'win_rate',
  'avg_exposure', 'var95_daily', 'cvar95_daily', 'best_month', 'worst_month',
]

/**
 * 只有「方向有意义」的指标才带 +/- 号。
 * ⚠️ 旧实现给所有百分比指标都传了 withSign=true，于是「年化波动 +9.26%」、
 *    「平均持仓比 +13%」也会带加号 —— 波动和持仓比例是**大小**不是**盈亏**，
 *    加号会让小白误以为那是收益。
 */
const SIGNED_KEYS = new Set(['total_return', 'cagr', 'excess_cagr', 'best_month', 'worst_month'])

export default function ResultPanel({
  result,
  capital,
  benchmark,
  commission,
  slippage,
  params,
  onDownload,
}: {
  result: BacktestResult
  capital: number
  benchmark: string
  commission: number
  slippage: number
  params: Record<string, any>
  onDownload: (kind: 'trades' | 'equity' | 'monthly') => void
}) {
  const [tab, setTab] = useState('metrics')
  // 换了一份结果（重新回测 / 载入历史记录）就回到第一个页签
  useEffect(() => {
    setTab('metrics')
  }, [result])

  const m = result.metrics || {}

  return (
    <>
      <Card
        title={
          <span className="flex items-center gap-2">
            <BarChart3 className="h-4 w-4 text-brand-500" />
            {result.strategy_name} · {symbolsToInput(result.symbols) ?? ''}
          </span>
        }
        subtitle={`${result.date_range?.[0] ?? ''} ~ ${result.date_range?.[1] ?? ''} ｜ ${result.bars} 根 K 线 ｜ ${
          result.trade_count
        } 笔交易 ｜ 数据源 ${result.data_source_used || Object.values(result.data_sources || {})[0] || '-'}`}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={m.total_return > 0 ? 'red' : 'green'}>
              累计 {fmtRatioPct(m.total_return, 2, true)}
            </Badge>
            <Button size="sm" icon={<Download className="h-3.5 w-3.5" />} onClick={() => onDownload('trades')}>
              交易明细
            </Button>
            <Button size="sm" icon={<Download className="h-3.5 w-3.5" />} onClick={() => onDownload('equity')}>
              净值曲线
            </Button>
            <Button size="sm" icon={<Download className="h-3.5 w-3.5" />} onClick={() => onDownload('monthly')}>
              全部指标
            </Button>
          </div>
        }
      >
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat
            label="累计收益"
            value={fmtRatioPct(m.total_return, 2, true)}
            tone={m.total_return > 0 ? 'up' : 'down'}
          />
          <Stat
            label="年化收益"
            value={fmtRatioPct(m.cagr, 2, true)}
            tone={m.cagr > 0 ? 'up' : 'down'}
            sub={`及格线 ${fmtRatioPct(m.benchmark_cagr, 2, true)}`}
          />
          <Stat label="夏普比率" value={fmtNum(m.sharpe, 2)} sub={`索提诺 ${fmtNum(m.sortino, 2)}`} />
          <Stat
            label="最大回撤"
            value={fmtRatioPct(m.max_drawdown, 2)}
            tone="down"
            sub={`及格线 ${fmtRatioPct(m.benchmark_max_drawdown, 2)}`}
          />
        </div>
      </Card>

      {/* 一句话结论 + 风险提示：小白最需要的部分，刻意放在指标表之前 */}
      <Card title="这次回测到底怎么样" subtitle="用大白话解释上面的数字">
        <ResultSummary result={result} capital={capital} benchmark={benchmark} />
      </Card>

      {result.strategy_notes?.length > 0 && (
        <Alert tone="info" title="策略提示">
          {result.strategy_notes.join('；')}
        </Alert>
      )}

      <Card
        title={<TermTip id="curve">净值曲线与回撤</TermTip>}
        subtitle="蓝色是你的策略，灰色是及格线；下方阴影是回撤（跌得越深越宽）"
        actions={
          <Tabs
            value={tab}
            onChange={setTab}
            tabs={[
              { key: 'metrics', label: '绩效指标' },
              { key: 'monthly', label: <TermTip id="monthly">月度分析</TermTip> },
              { key: 'trades', label: '交易明细' },
              { key: 'compare', label: '和及格线比' },
            ]}
          />
        }
      >
        <EquityChart data={result.curve} height={340} />

        <div className="mt-5">
          {tab === 'metrics' && (
            <div className="grid gap-5 md:grid-cols-2">
              {METRIC_GROUPS.map((g) => (
                <div key={g.title}>
                  <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">{g.title}</h4>
                  <div className="space-y-1.5">
                    {g.keys.map((k) => {
                      const v = m[k]
                      const isPct = PCT_KEYS.includes(k)
                      const show = isPct
                        ? fmtRatioPct(v, 2, SIGNED_KEYS.has(k))
                        : k === 'trades' || k === 'max_dd_days'
                          ? String(Math.round(Number(v) || 0))
                          : k === 'expectancy'
                            ? fmtMoney(v, 2)
                            : fmtNum(v, 2)
                      const highlight = ['total_return', 'cagr', 'max_drawdown'].includes(k)
                      return (
                        <div key={k} className="flex items-center justify-between border-b border-dashed border-slate-100 pb-1.5">
                          <span className="text-xs text-slate-500">
                            <TermTip id={k}>{METRIC_LABEL[k] || k}</TermTip>
                          </span>
                          <span className={`num text-sm ${highlight ? 'font-semibold ' + signClass(v) : 'font-medium text-slate-700'}`}>
                            {show}
                          </span>
                        </div>
                      )
                    })}
                  </div>
                </div>
              ))}
              <p className="text-[11px] leading-5 text-slate-400 md:col-span-2">
                把鼠标放到任意指标名上，会显示它「是什么 / 怎么看」。
              </p>
            </div>
          )}

          {tab === 'monthly' && (
            <div className="space-y-6">
              <div>
                <h4 className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-400">月度收益热力图（%）</h4>
                <MonthlyHeatmap monthly={result.monthly} />
              </div>
              <div>
                <h4 className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-400">近 36 个月收益</h4>
                <MonthlyBars monthly={result.monthly} height={220} />
              </div>
            </div>
          )}

          {tab === 'trades' && (
            <DataTable<TradeRow>
              rows={result.trades}
              rowKey={(r, i) => `${r.symbol}-${r.entry_time}-${i}`}
              maxHeight="520px"
              empty={<Empty title="本次回测没有产生交易" desc="可能是信号条件过于严格，或未在有效区间触发" />}
              columns={[
                { key: 's', label: <TermTip id="symbol">标的</TermTip>, render: (r) => <span className="font-medium text-slate-800">{r.symbol}</span> },
                {
                  key: 'side',
                  label: <TermTip id="trade_side">方向</TermTip>,
                  render: (r) => <Badge tone={r.side === 'LONG' ? 'red' : 'green'}>{r.side === 'LONG' ? '多' : '空'}</Badge>,
                },
                { key: 'en', label: '入场时间', render: (r) => <span className="num text-slate-500">{r.entry_time}</span> },
                { key: 'ex', label: '离场时间', render: (r) => <span className="num text-slate-500">{r.exit_time}</span> },
                { key: 'ep', label: '买入价', align: 'right', render: (r) => <span className="num">{fmtNum(r.entry_price, 2)}</span> },
                { key: 'xp', label: '卖出价', align: 'right', render: (r) => <span className="num">{fmtNum(r.exit_price, 2)}</span> },
                { key: 'q', label: <TermTip id="qty">数量</TermTip>, align: 'right', render: (r) => <span className="num">{fmtNum(r.qty, 0)}</span> },
                {
                  key: 'p',
                  label: <TermTip id="pnl">盈亏</TermTip>,
                  align: 'right',
                  render: (r) => <span className={`num ${signClass(r.pnl)}`}>{fmtMoney(r.pnl, 2)}</span>,
                },
                {
                  key: 'rp',
                  label: <TermTip id="trade_return">收益率</TermTip>,
                  align: 'right',
                  render: (r) => <span className={`num ${signClass(r.return_pct)}`}>{fmtRatioPct(r.return_pct, 2, true)}</span>,
                },
                {
                  key: 'bh',
                  label: <TermTip id="bars_held">持有</TermTip>,
                  align: 'right',
                  render: (r) => <span className="num text-slate-500">{r.bars_held}</span>,
                },
                {
                  key: 'er',
                  label: <TermTip id="exit_reason">离场原因</TermTip>,
                  render: (r) => <span className="text-xs text-slate-500">{r.exit_reason}</span>,
                },
              ]}
            />
          )}

          {tab === 'compare' && (
            <div className="space-y-5">
              <div className="grid gap-4 sm:grid-cols-3">
                <Stat label="策略年化" value={fmtRatioPct(m.cagr, 2, true)} tone="up" />
                <Stat label="及格线年化" value={fmtRatioPct(m.benchmark_cagr, 2, true)} sub="什么都不做，直接买基准" />
                <Stat
                  label="超额年化"
                  value={fmtRatioPct(m.excess_cagr, 2, true)}
                  tone={m.excess_cagr > 0 ? 'up' : 'down'}
                />
              </div>
              <div className="grid gap-4 sm:grid-cols-3">
                <Stat label="Alpha（年化）" value={fmtRatioPct(m.alpha, 2, true)} />
                <Stat label="Beta" value={fmtNum(m.beta, 2)} />
                <Stat label="信息比率" value={fmtNum(m.information_ratio, 2)} />
              </div>
              <Alert tone="info" title="怎么读这三组数">
                <TermTip id="alpha">Alpha</TermTip> 为正，说明这份收益无法被市场波动（
                <TermTip id="beta">Beta</TermTip>）解释，是策略自己的本事；
                <TermTip id="information_ratio">信息比率</TermTip> 大于 0.5，说明跑赢基准这件事比较稳定。
                如果 Alpha 接近 0 而 Beta 接近 1，那这套策略本质上只是「加了杠杆的买入持有」。
              </Alert>
            </div>
          )}
        </div>
      </Card>

      {/* AI 回测诊断：用本次回测的真实指标做过拟合与收益质量诊断 */}
      <AIAssist
        mode="panel"
        task="backtest_diagnose"
        title="AI 回测诊断"
        desc="基于本次回测的真实指标，诊断过拟合风险、收益质量与改进方向"
        label="诊断这次回测"
        runKey={`${result.run_id ?? ''}:${result.strategy_name}:${symbolsToInput(result.symbols) ?? ''}:${result.bars}`}
        payload={{
          strategy: result.strategy_name,
          symbols: symbolsToList(result.symbols),
          period: result.date_range,
          cost_model: `佣金 ${commission}bps / 滑点 ${slippage}bps`,
          params,
          metrics: result.metrics,
        }}
        emptyHint="点击上方「诊断这次回测」按钮，AI 会重点看交易笔数、换手率、Alpha/Beta 结构，并明确指出结果是否可信。"
      />
    </>
  )
}
