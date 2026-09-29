/**
 * AdvancedSettings —— 回测的「高级设置」区块
 * ===========================================
 * 从 ConfigPanel.tsx 抽出（铁律 9：组件 600 行硬上限）。
 *
 * 内容 = 数据周期 / 数据源 / 手续费 / 滑点 / 止损止盈 / 仓位算法。
 * 小白模式下整块折进「高级设置（一般不用改）」；关掉新手模式后平铺，
 * 和重构前的专业面板完全一致 —— **功能一个都没少，只是默认不吓人**。
 */
import type { DataSourceInfo } from '../../lib/types'
import { Field, Input, Select } from '../ui'
import { Section } from '../form/parts'
import { TermLabel } from '../terms/TermTip'
import type { ConfigForm, ConfigSetters, MetaResp } from './types'

export default function AdvancedSettings({
  meta,
  dsInfo,
  form,
  set,
  collapsed,
}: {
  meta: MetaResp | null
  dsInfo: DataSourceInfo | null
  form: ConfigForm
  set: ConfigSetters
  collapsed: boolean
}) {
  const stopValueLabel =
    form.stopType.startsWith('atr') || form.stopType === 'chandelier' || form.stopType === 'volatility'
      ? 'ATR 倍数'
      : form.stopType === 'time_stop'
        ? 'bar 数（忽略）'
        : '百分比 %'

  return (
    <Section title={collapsed ? '高级设置（一般不用改）' : '交易成本与执行'} tip="interval" collapsed={collapsed}>
      <Field
        label={<TermLabel id="interval">数据周期（K线周期）</TermLabel>}
        hint="新手用日线即可；周期越短交易越频繁、成本越高"
      >
        <Select value={form.interval} onChange={(e) => set.setInterval(e.target.value)}>
          <option value="1d">日线 (1d) · 推荐</option>
          <option value="1wk">周线 (1wk)</option>
          <option value="1h">小时线 (1h) · 免费源约 180 天</option>
          <option value="30m">30 分钟 (30m) · 免费源约 60 天</option>
          <option value="15m">15 分钟 (15m) · 免费源约 60 天</option>
          <option value="5m">5 分钟 (5m) · 免费源约 60 天</option>
        </Select>
      </Field>

      <Field
        label={<TermLabel id="data_source">数据源</TermLabel>}
        hint={
          dsInfo?.providers?.ibkr?.available
            ? 'IBKR 已连接，日内数据可回溯数年'
            : 'IBKR 未连接 —— 选「IBKR 优先」会自动降级到免费源'
        }
      >
        <Select value={form.dataSource} onChange={(e) => set.setDataSource(e.target.value)}>
          <option value="auto">自动（yfinance → Stooq → 合成）</option>
          <option value="ibkr">IBKR 优先（与实盘价格一致）</option>
        </Select>
      </Field>

      <div className="grid grid-cols-2 gap-3">
        <Field label={<TermLabel id="commission">手续费 (bp)</TermLabel>} hint="单边万分之">
          <Input
            type="number"
            step="0.5"
            value={form.commission}
            onChange={(e) => set.setCommission(parseFloat(e.target.value || '0'))}
          />
        </Field>
        <Field label={<TermLabel id="slippage">滑点 (bp)</TermLabel>}>
          <Input
            type="number"
            step="0.5"
            value={form.slippage}
            onChange={(e) => set.setSlippage(parseFloat(e.target.value || '0'))}
          />
        </Field>
      </div>

      <Field label={<TermLabel id="stop">止损方式</TermLabel>}>
        <Select value={form.stopType} onChange={(e) => set.setStopType(e.target.value)}>
          {meta?.stop_types.map((s) => (
            <option key={s.key} value={s.key}>
              {s.label}
            </option>
          ))}
        </Select>
      </Field>
      {form.stopType !== 'none' && (
        <>
          <p className="text-[11px] text-slate-400">{meta?.stop_types.find((s) => s.key === form.stopType)?.desc}</p>
          <div className="grid grid-cols-2 gap-3">
            <Field label={stopValueLabel}>
              <Input
                type="number"
                step="0.1"
                value={form.stopValue}
                onChange={(e) => set.setStopValue(parseFloat(e.target.value || '3'))}
              />
            </Field>
            <Field label={<TermLabel id="r_multiple">R 倍止盈</TermLabel>} hint="0=关闭">
              <Input
                type="number"
                step="0.5"
                value={form.takeProfitR}
                onChange={(e) => set.setTakeProfitR(parseFloat(e.target.value || '0'))}
              />
            </Field>
          </div>
          <Field label="时间止损 (bar)" hint="0 = 关闭；持满 N 根无表现即离场">
            <Input
              type="number"
              value={form.timeStop}
              onChange={(e) => set.setTimeStop(parseInt(e.target.value || '0', 10))}
            />
          </Field>
        </>
      )}

      <Field label={<TermLabel id="sizing">仓位算法</TermLabel>}>
        <Select value={form.sizing} onChange={(e) => set.setSizing(e.target.value)}>
          {meta?.sizing_methods.map((s) => (
            <option key={s.key} value={s.key}>
              {s.label}
            </option>
          ))}
        </Select>
      </Field>
      <p className="text-[11px] text-slate-400">{meta?.sizing_methods.find((s) => s.key === form.sizing)?.desc}</p>
      {(form.sizing === 'atr_risk' || form.sizing === 'kelly_capped') && (
        <Field label="每笔风险 %">
          <Input
            type="number"
            step="0.1"
            value={form.riskPct}
            onChange={(e) => set.setRiskPct(parseFloat(e.target.value || '1'))}
          />
        </Field>
      )}
    </Section>
  )
}
