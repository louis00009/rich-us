/**
 * 可视化规则编辑器的条件行
 * ==========================
 * 从 `pages/Strategies.tsx` 抽出（铁律 9：页面文件已超硬上限，新功能必须先拆）。
 * 这里只放**无状态**的条件行原语（OPS / 指标白名单 / CondRow / condToSpec），
 * 条件数组本身仍由页面持有。
 *
 * ⚠️ `IND_OPTIONS` 必须与后端 `strategies/custom.py` 的
 * `ALLOWED_RULE_INDICATORS` 保持一致，否则会出现「前端能选、后端报不支持」。
 * 注意：这里**不暴露 shift** —— 负位移会读取未来数据（构成未来函数），
 * 后端 `validate_rule` 已显式拒绝，前端不提供入口。
 */
import { Trash2 } from 'lucide-react'
import { Button, Input, Select } from '../ui'

export const OPS = [
  { key: '>', label: '大于' },
  { key: '<', label: '小于' },
  { key: '>=', label: '大于等于' },
  { key: '<=', label: '小于等于' },
  { key: 'cross_above', label: '上穿' },
  { key: 'cross_below', label: '下穿' },
]

export const IND_OPTIONS = [
  { key: 'close', label: '收盘价', needPeriod: false },
  { key: 'open', label: '开盘价', needPeriod: false },
  { key: 'high', label: '最高价', needPeriod: false },
  { key: 'low', label: '最低价', needPeriod: false },
  { key: 'volume', label: '成交量', needPeriod: false },
  { key: 'sma', label: '简单均线 SMA', needPeriod: true },
  { key: 'ema', label: '指数均线 EMA', needPeriod: true },
  { key: 'hma', label: 'Hull 均线 HMA', needPeriod: true },
  { key: 'rsi', label: 'RSI', needPeriod: true },
  { key: 'macd', label: 'MACD 线', needPeriod: false },
  { key: 'macd_hist', label: 'MACD 柱', needPeriod: false },
  { key: 'atr', label: 'ATR 真实波幅', needPeriod: true },
  { key: 'natr', label: 'ATR 占比 %', needPeriod: true },
  { key: 'adx', label: 'ADX 趋势强度', needPeriod: true },
  { key: 'plus_di', label: '+DI', needPeriod: true },
  { key: 'minus_di', label: '-DI', needPeriod: true },
  { key: 'bb_upper', label: '布林上轨', needPeriod: true },
  { key: 'bb_lower', label: '布林下轨', needPeriod: true },
  { key: 'bb_pctb', label: '布林 %B', needPeriod: true },
  { key: 'zscore', label: 'Z 分数', needPeriod: true },
  { key: 'roc', label: '变动率 ROC %', needPeriod: true },
  { key: 'vol_ratio', label: '量比', needPeriod: true },
  { key: 'cci', label: 'CCI', needPeriod: true },
  { key: 'mfi', label: 'MFI 资金流量', needPeriod: true },
  { key: 'cmf', label: '蔡金资金流 CMF', needPeriod: true },
  { key: 'efficiency_ratio', label: '效率比 ER', needPeriod: true },
  { key: 'realized_vol', label: '已实现波动率', needPeriod: true },
  { key: 'donchian_upper', label: '唐奇安上轨', needPeriod: true },
  { key: 'donchian_lower', label: '唐奇安下轨', needPeriod: true },
  { key: 'vwap', label: '滚动 VWAP', needPeriod: true },
  { key: 'dist_sma50', label: '距 SMA50 偏离', needPeriod: false },
  { key: 'dist_sma200', label: '距 SMA200 偏离', needPeriod: false },
]

export interface Cond {
  id: number
  leftKind: 'indicator' | 'const'
  leftInd: string
  leftPeriod: number
  leftConst: number
  op: string
  rightKind: 'indicator' | 'const'
  rightInd: string
  rightPeriod: number
  rightConst: number
}

let cid = 1

export function newCond(): Cond {
  return {
    id: cid++,
    leftKind: 'indicator',
    leftInd: 'rsi',
    leftPeriod: 14,
    leftConst: 0,
    op: '<',
    rightKind: 'const',
    rightInd: 'sma',
    rightPeriod: 200,
    rightConst: 30,
  }
}

export function CondRow({
  cond,
  onChange,
  onRemove,
  removable,
}: {
  cond: Cond
  onChange: (c: Cond) => void
  onRemove: () => void
  removable: boolean
}) {
  const li = IND_OPTIONS.find((i) => i.key === cond.leftInd)
  const ri = IND_OPTIONS.find((i) => i.key === cond.rightInd)
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50/60 p-3">
      <div className="grid gap-2 lg:grid-cols-[1fr_auto_1fr_auto]">
        {/* 左操作数 */}
        <div className="flex gap-2">
          <Select
            className="w-24"
            value={cond.leftKind}
            onChange={(e) => onChange({ ...cond, leftKind: e.target.value as any })}
          >
            <option value="indicator">指标</option>
            <option value="const">常数</option>
          </Select>
          {cond.leftKind === 'const' ? (
            <Input
              type="number"
              step="0.01"
              className="flex-1"
              value={cond.leftConst}
              onChange={(e) => onChange({ ...cond, leftConst: parseFloat(e.target.value || '0') })}
            />
          ) : (
            <>
              <Select className="flex-1" value={cond.leftInd} onChange={(e) => onChange({ ...cond, leftInd: e.target.value })}>
                {IND_OPTIONS.map((o) => (
                  <option key={o.key} value={o.key}>
                    {o.label}
                  </option>
                ))}
              </Select>
              {li?.needPeriod && (
                <Input
                  type="number"
                  className="w-20"
                  value={cond.leftPeriod}
                  onChange={(e) => onChange({ ...cond, leftPeriod: parseInt(e.target.value || '14', 10) })}
                />
              )}
            </>
          )}
        </div>

        <Select className="w-28" value={cond.op} onChange={(e) => onChange({ ...cond, op: e.target.value })}>
          {OPS.map((o) => (
            <option key={o.key} value={o.key}>
              {o.label}
            </option>
          ))}
        </Select>

        {/* 右操作数 */}
        <div className="flex gap-2">
          <Select
            className="w-24"
            value={cond.rightKind}
            onChange={(e) => onChange({ ...cond, rightKind: e.target.value as any })}
          >
            <option value="const">常数</option>
            <option value="indicator">指标</option>
          </Select>
          {cond.rightKind === 'const' ? (
            <Input
              type="number"
              step="0.01"
              className="flex-1"
              value={cond.rightConst}
              onChange={(e) => onChange({ ...cond, rightConst: parseFloat(e.target.value || '0') })}
            />
          ) : (
            <>
              <Select className="flex-1" value={cond.rightInd} onChange={(e) => onChange({ ...cond, rightInd: e.target.value })}>
                {IND_OPTIONS.map((o) => (
                  <option key={o.key} value={o.key}>
                    {o.label}
                  </option>
                ))}
              </Select>
              {ri?.needPeriod && (
                <Input
                  type="number"
                  className="w-20"
                  value={cond.rightPeriod}
                  onChange={(e) => onChange({ ...cond, rightPeriod: parseInt(e.target.value || '14', 10) })}
                />
              )}
            </>
          )}
        </div>

        <Button variant="ghost" size="sm" onClick={onRemove} disabled={!removable} icon={<Trash2 className="h-3.5 w-3.5" />} />
      </div>
    </div>
  )
}

export function condToSpec(c: Cond) {
  const leftSpec = c.leftKind === 'const' ? { const: c.leftConst } : { indicator: c.leftInd, period: c.leftPeriod }
  const rightSpec = c.rightKind === 'const' ? { const: c.rightConst } : { indicator: c.rightInd, period: c.rightPeriod }
  return { left: leftSpec, op: c.op, right: rightSpec }
}
