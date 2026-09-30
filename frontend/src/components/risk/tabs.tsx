// 风控页共享常量与子 tab（FILE_SIZE_DEBT Batch C-1 拆分）
import { ScrollText, ShieldAlert, ShieldCheck, TrendingDown, AlertTriangle } from 'lucide-react'
import {
  Badge,
  Card,
  DataTable,
  Empty,
  Loading,
  Progress,
  Select,
} from '../ui'
import { fmtAgo, fmtDateTime, fmtMoney, fmtNum } from '../../lib/format'
import type { AuditRow, RiskConfig } from '../../lib/types'
import AIAssist from '../AIAssist'

export const STOP_GALLERY = [
  { key: 'none', label: '不启用', desc: '仅靠策略信号离场' },
  { key: 'fixed_pct', label: '固定百分比', desc: '自成本价固定百分比，简单直接', param: '百分比 %' },
  { key: 'pct_trailing', label: '百分比移动', desc: '跟随最高价回撤百分比离场', param: '百分比 %' },
  { key: 'atr_fixed', label: 'ATR 固定', desc: '以 N 倍 ATR 为距离，随波动自适应', param: 'ATR 倍数' },
  { key: 'atr_trailing', label: 'ATR 移动', desc: '最高价 − N×ATR，趋势策略标配', param: 'ATR 倍数' },
  { key: 'chandelier', label: '吊灯止损', desc: '取更宽的 ATR 距离，避免过早离场', param: 'ATR 倍数' },
  { key: 'breakeven', label: '保本止损', desc: '浮盈达 R 后把止损移到成本价', param: 'R 触发点' },
  { key: 'time_stop', label: '时间止损', desc: '持满 N 根 bar 仍无表现即离场', param: 'bar 数' },
  { key: 'volatility', label: '波动率自适应', desc: 'ATR 放大时同步放宽，防噪声扫出', param: 'ATR 倍数' },
]

export const SIZING = [
  { key: 'weight', label: '策略权重直用', desc: '把策略输出的目标权重直接当作权益占比（回测最常用）' },
  { key: 'fixed_fraction', label: '固定比例', desc: '每笔按权益固定百分比建仓' },
  { key: 'risk_parity_vol', label: '波动率平价', desc: '按波动率倒数分配，低波动多配' },
  { key: 'atr_risk', label: '固定风险（ATR）', desc: '单笔最大亏损锁定为权益的 N%，机构标准做法' },
  { key: 'kelly_capped', label: '凯利公式（封顶）', desc: '按胜率与盈亏比推算最优仓位' },
  { key: 'equal_weight', label: '等权分配', desc: '所有标的均分仓位' },
]

/** 实时敞口 tab：持仓敞口明细 + 组合指标 + AI 风控体检。 */
export function ExposureTab({ expo, cfg }: { expo: any; cfg: RiskConfig | null }) {
  return (
    <div className="grid gap-5 xl:grid-cols-3">
      <Card className="xl:col-span-2" title="持仓敞口明细" subtitle="每个标的的占用与剩余额度">
        <DataTable<any>
          rows={expo?.positions || []}
          rowKey={(r) => r.symbol}
          empty={<Empty title="当前无持仓" />}
          columns={[
            { key: 's', label: '标的', render: (r) => <span className="font-medium">{r.symbol}</span> },
            { key: 'q', label: '数量', align: 'right', render: (r) => <span className="num">{fmtNum(r.quantity, 2)}</span> },
            { key: 'm', label: '市值', align: 'right', render: (r) => <span className="num">{fmtMoney(r.market_value, 0)}</span> },
            { key: 'p', label: '占权益', align: 'right', render: (r) => <span className="num">{r.pct}%</span> },
            {
              key: 'h',
              label: '剩余额度',
              width: '180px',
              render: (r) => (
                <div className="flex items-center gap-2">
                  <div className="w-24">
                    <Progress value={r.pct} max={Math.max(r.pct + r.headroom_pct, 1)} tone={r.pct > 18 ? 'red' : 'brand'} height="h-1" />
                  </div>
                  <span className="num text-xs text-slate-500">+{r.headroom_pct}%</span>
                </div>
              ),
            },
          ]}
        />
      </Card>

      <Card title="组合指标">
        {expo ? (
          <div className="space-y-3">
            {[
              ['账户权益', fmtMoney(expo.equity, 2)],
              ['现金', fmtMoney(expo.cash, 2)],
              ['净敞口', `${fmtMoney(expo.net_exposure, 0)} (${expo.net_pct}%)`],
              ['总敞口', `${fmtMoney(expo.gross_exposure, 0)} (${expo.gross_pct}%)`],
              ['多头市值', fmtMoney(expo.long_value, 0)],
              ['空头市值', fmtMoney(expo.short_value, 0)],
              ['持仓数量', String(expo.positions?.length ?? 0)],
            ].map(([k, v]) => (
              <div key={k} className="flex items-center justify-between border-b border-dashed border-slate-100 pb-2">
                <span className="text-xs text-slate-500">{k}</span>
                <span className="num text-sm font-medium text-slate-700">{v}</span>
              </div>
            ))}
          </div>
        ) : (
          <Loading />
        )}
      </Card>

      {/* AI 风控体检：检查参数自洽性 + 当前敞口的真实风险点 */}
      <AIAssist
        mode="panel"
        task="risk_review"
        title="AI 风控体检"
        desc="检查参数之间的自洽性（如单标的上限 × 持仓数 vs 总敞口上限）与当前敞口风险"
        label="体检这套风控"
        payload={{ config: cfg, exposure: expo }}
        runKey={`${cfg?.max_position_pct}:${cfg?.max_gross_exposure_pct}:${cfg?.max_open_positions}:${expo?.gross_pct}`}
        disabled={!cfg}
        disabledHint="风控配置未加载。"
        emptyHint="AI 会指出哪些约束实际上永远不会被触发，并给出具体调整区间与极端行情情景推演。"
      />
    </div>
  )
}

/** 审计日志 tab：下单 / 风控变更 / 登录与实盘解锁留痕。 */
export function AuditTab({
  audit, levelFilter, onLevelFilter,
}: {
  audit: AuditRow[]
  levelFilter: string
  onLevelFilter: (v: string) => void
}) {
  const filteredAudit = audit.filter((a) => !levelFilter || a.level === levelFilter)
  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          <ScrollText className="h-4 w-4" />审计日志
        </span>
      }
      subtitle="所有下单、风控变更、登录与实盘解锁操作都会留痕"
      actions={
        <Select className="w-36" value={levelFilter} onChange={(e) => onLevelFilter(e.target.value)}>
          <option value="">全部级别</option>
          <option value="INFO">INFO</option>
          <option value="WARN">WARN</option>
          <option value="CRITICAL">CRITICAL</option>
        </Select>
      }
      dense
    >
      <DataTable<AuditRow>
        rows={filteredAudit}
        rowKey={(r) => r.id}
        maxHeight="620px"
        empty={<Empty title="暂无日志" />}
        columns={[
          { key: 't', label: '时间', render: (r) => <span className="num text-xs text-slate-500" title={fmtDateTime(r.ts)}>{fmtAgo(r.ts)}</span> },
          {
            key: 'lv',
            label: '级别',
            render: (r) => (
              <Badge tone={r.level === 'CRITICAL' ? 'red' : r.level === 'WARN' ? 'amber' : 'slate'}>{r.level}</Badge>
            ),
          },
          { key: 'a', label: '动作', render: (r) => <span className="font-mono text-xs text-slate-600">{r.action}</span> },
          { key: 'ac', label: '操作者', render: (r) => <span className="text-xs text-slate-500">{r.actor}</span> },
          { key: 'd', label: '详情', render: (r) => <span className="text-xs text-slate-600">{r.detail}</span> },
        ]}
      />
    </Card>
  )
}

/** 止损机制说明 + 推荐组合（止损与仓位 tab 的右侧栏）。 */
export function StopsSideCards() {
  return (
    <div className="space-y-5">
      <Card title="止损机制说明">
        <ul className="space-y-2.5 text-xs text-slate-600">
          <li className="flex gap-2">
            <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-brand-500" />
            <span>回测与实盘使用<span className="font-medium">同一套止损状态机</span>，保证「回测即实盘」。</span>
          </li>
          <li className="flex gap-2">
            <TrendingDown className="mt-0.5 h-3.5 w-3.5 shrink-0 text-brand-500" />
            <span>移动止损只朝有利方向推进，绝不会反向放宽。</span>
          </li>
          <li className="flex gap-2">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-500" />
            <span>止损判定使用 bar 内最高/最低价，而非收盘价 —— 避免高估收益。</span>
          </li>
          <li className="flex gap-2">
            <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0 text-rose-500" />
            <span>「不启用止损」在杠杆或高波动品种上极其危险，请谨慎选择。</span>
          </li>
        </ul>
      </Card>

      <Card title="推荐组合">
        <div className="space-y-3 text-xs">
          <div className="rounded-lg border border-slate-200 p-3">
            <div className="font-medium text-slate-700">趋势跟随</div>
            <div className="mt-1 text-slate-500">
              ATR 移动止损（3 倍）+ 固定风险仓位（1%）。让盈利奔跑、把单笔亏损锁死。
            </div>
          </div>
          <div className="rounded-lg border border-slate-200 p-3">
            <div className="font-medium text-slate-700">均值回归</div>
            <div className="mt-1 text-slate-500">
              ATR 固定止损（2 倍）+ R 倍止盈（1.5R）+ 时间止损（10 bar）。避免久拖不决。
            </div>
          </div>
          <div className="rounded-lg border border-slate-200 p-3">
            <div className="font-medium text-slate-700">组合配置</div>
            <div className="mt-1 text-slate-500">
              吊灯止损（3.5 倍）+ 波动率平价仓位。低波动标的自然多配，组合波动率更平稳。
            </div>
          </div>
        </div>
      </Card>
    </div>
  )
}

