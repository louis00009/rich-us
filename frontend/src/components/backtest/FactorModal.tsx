/**
 * FactorModal —— 因子 IC 诊断
 * =============================
 * 从 pages/Backtest.tsx 抽出（铁律 9）。自持「周期 / 运行中 / 结果」状态。
 *
 * 行为上做了一处刻意改动：**打开弹窗不再自动开跑**，改成点「开始诊断」才请求。
 * 旧实现是「点按钮 = 打开 + 立刻发起一次长耗时网络请求」，用户看到的是一个
 * 自己动起来的弹窗，且没有中途取消的机会。
 */
import { useState } from 'react'
import { Play } from 'lucide-react'
import { api, LONG_TIMEOUT } from '../../lib/api'
import { fmtNum } from '../../lib/format'
import { Alert, Button, DataTable, Modal, Select, useToast } from '../ui'
import { TermTip } from '../terms/TermTip'

export default function FactorModal({
  open,
  onClose,
  strategyKey,
  params,
  symbols,
  start,
  end,
  interval,
}: {
  open: boolean
  onClose: () => void
  strategyKey: string
  params: Record<string, any>
  symbols: string
  start: string
  end: string
  interval: string
}) {
  const toast = useToast()
  const [horizon, setHorizon] = useState(21)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<any>(null)

  const run = async (h = horizon) => {
    setLoading(true)
    setResult(null)
    try {
      const r = await api.post<any>(
        '/backtest/factor-ic',
        {
          strategy_key: strategyKey,
          params,
          symbols: symbols
            .split(',')
            .map((s) => s.trim().toUpperCase())
            .filter(Boolean),
          start,
          end: end || null,
          interval,
          horizon: h,
        },
        LONG_TIMEOUT,
      )
      setResult(r)
      if (r.ok) toast('success', '因子诊断完成')
    } catch (e: any) {
      setResult({ ok: false, error: e?.message || '因子诊断失败', factors: [] })
    } finally {
      setLoading(false)
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="因子诊断 · IC 分析"
      width="max-w-2xl"
      footer={<Button onClick={onClose}>关闭</Button>}
    >
      <div className="space-y-4">
        <Alert tone="info" title="这是干什么的">
          检验策略里每个「原料指标」（因子）和未来涨跌到底有没有关系。
          <span className="font-medium">只用于评估因子质量，不影响回测信号。</span>
        </Alert>

        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-slate-400">预测周期</span>
          <Select
            value={String(horizon)}
            onChange={(e) => setHorizon(Number(e.target.value))}
            className="!w-40"
          >
            <option value="5">5 日（短线）</option>
            <option value="21">21 日（月度）</option>
            <option value="63">63 日（季度）</option>
          </Select>
          <Button variant="primary" size="sm" loading={loading} onClick={() => run()} icon={<Play className="h-3.5 w-3.5" />}>
            开始诊断
          </Button>
          {loading && <span className="text-xs text-slate-400">正在拉取行情并计算各因子 IC…</span>}
        </div>

        {!result && !loading && (
          <p className="text-xs leading-6 text-slate-400">
            点「开始诊断」后，会拿当前策略的标的与时间区间去算。
            经验门槛：
            <TermTip id="ic_mean">平均 IC</TermTip> 绝对值大于等于 0.03 视为有效，
            <TermTip id="icir">ICIR</TermTip> 大于等于 0.5 视为稳健。
          </p>
        )}

        {result && !loading && (
          <>
            {result.ok ? (
              <DataTable<any>
                rows={result.factors}
                rowKey={(r) => r.name}
                maxHeight="320px"
                columns={[
                  { key: 'n', label: '因子', render: (r) => <span className="font-medium text-slate-700">{r.name}</span> },
                  {
                    key: 'w',
                    label: <TermTip id="factor_weight">权重</TermTip>,
                    align: 'right',
                    render: (r) => <span className="num">{r.weight}</span>,
                  },
                  {
                    key: 'ic',
                    label: <TermTip id="ic_mean">平均 IC</TermTip>,
                    align: 'right',
                    render: (r) =>
                      r.ic_mean == null ? (
                        <span className="text-xs text-slate-400">{r.note || '—'}</span>
                      ) : (
                        <span
                          className={`num font-medium ${
                            Math.abs(r.ic_mean) >= 0.03
                              ? r.ic_mean > 0
                                ? 'text-rose-600'
                                : 'text-emerald-600'
                              : 'text-slate-600'
                          }`}
                        >
                          {fmtNum(r.ic_mean, 3)}
                        </span>
                      ),
                  },
                  {
                    key: 'icir',
                    label: <TermTip id="icir">ICIR</TermTip>,
                    align: 'right',
                    render: (r) =>
                      r.icir == null ? (
                        '—'
                      ) : (
                        <span className={`num ${Math.abs(r.icir) >= 0.5 ? 'font-semibold text-brand-700' : 'text-slate-600'}`}>
                          {fmtNum(r.icir, 2)}
                        </span>
                      ),
                  },
                  {
                    key: 'pos',
                    label: <TermTip id="ic_positive">IC 大于 0 占比</TermTip>,
                    align: 'right',
                    render: (r) =>
                      r.ic_positive_pct == null ? '—' : <span className="num">{(r.ic_positive_pct * 100).toFixed(0)}%</span>,
                  },
                  { key: 'nd', label: '样本数', align: 'right', render: (r) => <span className="num text-slate-500">{r.n_dates}</span> },
                  {
                    key: 'cov',
                    label: <TermTip id="coverage">覆盖率</TermTip>,
                    align: 'right',
                    render: (r) => (r.coverage == null ? '—' : <span className="num text-slate-500">{(r.coverage * 100).toFixed(0)}%</span>),
                  },
                ]}
              />
            ) : (
              <Alert tone="warn" title="无法诊断">
                {result.error || '未知错误'}
              </Alert>
            )}
            <p className="text-[11px] leading-5 text-slate-400">
              注意：诊断过程用未来收益做对账，属于「事后验证」，不能当成交易信号使用。
            </p>
          </>
        )}
      </div>
    </Modal>
  )
}
