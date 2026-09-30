// 实盘页「策略实时引擎」tab（FILE_SIZE_DEBT Batch C-4 拆分）
// 引擎相关状态（策略/间隔/模式/保护单/演练）自包含于本组件；
// 页面只传 strategyList / mode / runs / openOrderCount / onReload。
import { Ban, Gauge, RefreshCw, Square, Zap } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Alert,
  Badge,
  Button,
  DataTable,
  Empty,
  Field,
  Input,
  Select,
  Switch,
  useToast,
} from '../ui'
import { api } from '../../lib/api'
import { fmtAgo, fmtMoney, fmtNum } from '../../lib/format'
import type { StrategyConfig } from '../../lib/types'

/** /trading/engine 的 runs 行（字段与订单流水不同） */
export interface EngineRun {
  id: number
  mode: string
  status: string
  tick_count: number
  last_tick?: string
  strategy_id: number
}

interface EngineTabProps {
  strategyList: StrategyConfig[]
  mode: any
  /** /trading/engine 的 runs 列表（含历史运行） */
  runs: EngineRun[]
  openOrderCount: number
  onReload: () => void
}

export default function EngineTab({ strategyList, mode, runs, openOrderCount, onReload }: EngineTabProps) {
  const toast = useToast()
  const activeRuns = runs.filter((r) => r.status === 'RUNNING')
  const [engineStrategy, setEngineStrategy] = useState<number | ''>('')
  const [engineInterval, setEngineInterval] = useState(60)
  const [engineMode, setEngineMode] = useState<'paper' | 'live'>('paper')
  const [placeProtective, setPlaceProtective] = useState(true)
  const [dryRun, setDryRun] = useState<any>(null)
  const [engineBusy, setEngineBusy] = useState(false)

  const startEngine = async () => {
    if (!engineStrategy) {
      toast('warning', '请先选择要运行的策略')
      return
    }
    if (engineMode === 'live' && mode?.mode !== 'live') {
      toast('warning', '请先把交易模式切换到实盘，或改用模拟盘运行引擎')
      return
    }
    if (
      engineMode === 'live' &&
      !confirm(
        '⚠️ 即将以【实盘】模式启动策略引擎。\n\n' +
          '引擎会自动下单，真实资金将发生变动。\n' +
          '请确认：\n' +
          '1) 风控限额已复核\n' +
          '2) 熔断开关未启用\n' +
          '3) 策略已在模拟盘充分验证\n\n' +
          '确定继续？',
      )
    )
      return
    setEngineBusy(true)
    try {
      const r = await api.post<any>('/trading/engine/start', {
        strategy_id: engineStrategy,
        mode: engineMode,
        interval_sec: engineInterval,
        place_protective: placeProtective,
      })
      toast(engineMode === 'live' ? 'warning' : 'success', r.message)
      onReload()
    } catch (e: any) {
      toast('error', e?.message || '启动失败')
    } finally {
      setEngineBusy(false)
    }
  }

  const stopAllEngines = async () => {
    if (!confirm('确认一键停止全部运行中的策略引擎？已有持仓不会被自动平仓。')) return
    try {
      const r = await api.post<any>('/trading/engine/stop-all')
      toast('success', r.message)
      onReload()
    } catch (e: any) {
      toast('error', e?.message || '操作失败')
    }
  }

  const cancelAllOrders = async () => {
    if (!confirm('确认撤销当前券商连接下的全部挂单？')) return
    try {
      const r = await api.post<any>('/trading/cancel-all')
      toast('success', r.message)
      onReload()
    } catch (e: any) {
      toast('error', e?.message || '撤单失败')
    }
  }

  const stopEngine = async (sid: number) => {
    try {
      await api.post(`/trading/engine/stop/${sid}`)
      toast('success', '引擎已停止')
      onReload()
    } catch (e: any) {
      toast('error', e?.message || '停止失败')
    }
  }

  const runDry = async () => {
    if (!engineStrategy) {
      toast('warning', '请先选择策略')
      return
    }
    setEngineBusy(true)
    try {
      const r = await api.post<any>(`/trading/engine/dry-run/${engineStrategy}`)
      setDryRun(r)
      toast('info', `演练完成：计划 ${r.planned_orders.length} 笔，拦截 ${r.blocked.length} 笔`)
    } catch (e: any) {
      toast('error', e?.message || '演练失败')
    } finally {
      setEngineBusy(false)
    }
  }

  return (
    <div className="mt-4 space-y-4">
      <Alert tone={mode?.live_ready ? 'danger' : 'info'} title={mode?.live_ready ? '实盘通道已就绪，可启动实盘引擎' : '实时引擎 · 当前可用：模拟盘'}>
        引擎按设定间隔执行：拉取行情 → 跑策略 → 与当前持仓差分 → 通过风控护栏 → 下单。
        每笔调仓都会写入审计日志。
        {!mode?.live_ready && (
          <>
            <br />
            实盘模式尚未解锁（{mode?.live_reason}）。完成三重锁的前两道后即可在此启动实盘引擎。
          </>
        )}
      </Alert>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Field label="选择策略" hint="来自「我的策略」">
          <Select value={engineStrategy} onChange={(e) => setEngineStrategy(e.target.value ? parseInt(e.target.value, 10) : '')}>
            <option value="">— 请选择 —</option>
            {strategyList.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}（{s.kind}）
              </option>
            ))}
          </Select>
        </Field>
        <Field label="运行模式">
          <Select value={engineMode} onChange={(e) => setEngineMode(e.target.value as 'paper' | 'live')}>
            <option value="paper">模拟盘（零风险）</option>
            <option value="live" disabled={!mode?.live_ready}>
              {mode?.live_ready ? '实盘 ⚠️（真实资金）' : '实盘（未解锁）'}
            </option>
          </Select>
        </Field>
        <Field label="运行间隔（秒）" hint="最小 10 秒">
          <Input type="number" min="10" max="3600" value={engineInterval} onChange={(e) => setEngineInterval(parseInt(e.target.value || '60', 10))} />
        </Field>
        <div className="flex items-end gap-2">
          <Button className="flex-1" onClick={runDry} loading={engineBusy} icon={<Gauge className="h-3.5 w-3.5" />}>
            演练（不下单）
          </Button>
          <Button
            className="flex-1"
            variant={engineMode === 'live' ? 'danger' : 'primary'}
            onClick={startEngine}
            loading={engineBusy}
            icon={<Zap className="h-3.5 w-3.5" />}
          >
            {engineMode === 'live' ? '启动实盘引擎' : '启动引擎'}
          </Button>
        </div>
      </div>

      <Switch
        checked={placeProtective}
        onChange={setPlaceProtective}
        label="实盘持仓自动挂交易所侧保护单（强烈建议开启）"
        hint="建仓后立即在 IBKR 侧挂 GTC 止损单（必要时含止盈单），平仓时自动撤销。这样即使引擎进程掉线，持仓依然有保护。"
      />

      <div className="flex flex-wrap gap-2">
        <Button variant="secondary" onClick={stopAllEngines} icon={<Square className="h-3.5 w-3.5" />}>
          一键停止全部引擎（{activeRuns.length}）
        </Button>
        <Button variant="secondary" onClick={cancelAllOrders} icon={<Ban className="h-3.5 w-3.5" />}>
          撤销全部挂单（{openOrderCount}）
        </Button>
        <Button variant="secondary" onClick={onReload} icon={<RefreshCw className="h-3.5 w-3.5" />}>
          刷新
        </Button>
      </div>

      {strategyList.length === 0 && (
        <Alert tone="warn">
          尚未创建自定义策略。请先前往
          <Link to="/strategies" className="mx-1 font-medium underline">
            策略实验室
          </Link>
          创建规则或代码策略。
        </Alert>
      )}

      {dryRun && (
        <div className="rounded-lg border border-slate-200 p-3.5">
          <div className="flex items-center gap-2 text-sm font-medium text-slate-700">
            <Gauge className="h-4 w-4" />演练结果（未真实下单）
          </div>
          <div className="mt-2 space-y-2 text-xs">
            <div className="text-slate-500">
              账户权益 {fmtMoney(dryRun.account_equity, 2)} · 目标权重：
              <span className="num ml-1">{JSON.stringify(dryRun.target_weights)}</span>
            </div>
            {dryRun.planned_orders?.length ? (
              dryRun.planned_orders.map((o: any, i: number) => (
                <div key={i} className="flex items-center gap-2">
                  <Badge tone={o.side === 'BUY' ? 'red' : 'green'}>{o.side}</Badge>
                  <span className="font-medium">{o.symbol}</span>
                  <span className="num">{fmtNum(o.quantity, 2)} 股</span>
                  <span className="text-slate-400">目标名义 {fmtMoney(o.target_notional, 0)}</span>
                </div>
              ))
            ) : (
              <p className="text-slate-400">本次无调仓需求（目标权重与当前持仓差异小于 0.5% 权益）</p>
            )}
            {dryRun.blocked?.map((b: any, i: number) => (
              <div key={i} className="flex items-center gap-2 text-amber-700">
                <Ban className="h-3.5 w-3.5" />
                {b.symbol} {b.side} 被拦截：{b.reason}（{b.code}）
              </div>
            ))}
            {dryRun.errors?.map((e: string, i: number) => (
              <div key={i} className="text-rose-600">
                {e}
              </div>
            ))}
          </div>
        </div>
      )}

      <DataTable<EngineRun>
        rows={runs}
        rowKey={(r) => r.id}
        empty={<Empty title="引擎尚未运行过" desc="选择一个策略并点击「启动引擎」" />}
        columns={[
          { key: 'id', label: '运行 ID', render: (r) => <span className="num text-slate-500">#{r.id}</span> },
          { key: 'm', label: '模式', render: (r) => <Badge tone={r.mode === 'live' ? 'red' : 'brand'}>{r.mode}</Badge> },
          {
            key: 'st',
            label: '状态',
            render: (r) => (
              <Badge tone={r.status === 'RUNNING' ? 'green' : r.status === 'ERROR' ? 'red' : 'slate'} dot={r.status === 'RUNNING'}>
                {r.status}
              </Badge>
            ),
          },
          { key: 't', label: 'tick 数', align: 'right', render: (r) => <span className="num">{r.tick_count}</span> },
          { key: 'lt', label: '最近 tick', render: (r) => <span className="text-xs text-slate-500">{r.last_tick ? fmtAgo(r.last_tick) : '—'}</span> },
          {
            key: 'a',
            label: '',
            align: 'right',
            render: (r) =>
              r.status === 'RUNNING' ? (
                <Button size="sm" variant="danger" icon={<Square className="h-3 w-3" />} onClick={() => stopEngine(r.strategy_id)}>
                  停止
                </Button>
              ) : null,
          },
        ]}
      />
    </div>
  )
}
