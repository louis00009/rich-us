/**
 * OptimizeConfigPanel —— 组合优化配置面板（小白友好版）
 * =====================================================
 * 与回测页同一套做法：
 *  ① **分步**：原来 14 个控件平铺，不知道从哪看起。现在拆成
 *     「① 放哪些标的 → ② 想要什么效果 → ③ 用多长历史 → ④ 限制条件」四步；
 *  ② **新手模式（默认开）**：协方差估计 / 期望收益估计 / 相关簇阈值 / 单簇上限 /
 *     风险预算这些一眼看不懂的，收进「高级设置」折叠区；关掉即全量平铺 ——
 *     不删功能，只是默认不吓人；
 *  ③ **每个术语都能悬停**：词条在 `components/terms/optimize.ts`。
 *
 * ⚠️ 本组件是**纯受控展示组件**：不持有任何配置状态，全部值/写回由父级传入。
 *    优化配置有「一键推荐」和「恢复默认」两条写入路径，状态必须集中在
 *    Optimize.tsx 一处，拆开必然出现「两个真相」。
 *
 * ⚠️ 问号必须放在 `Button` **外面**：放进 button 里会让「点问号看说明」变成
 *    「顺带触发按钮」，而且 button 嵌 button 是非法嵌套。
 */
import { AlertTriangle, Play, RotateCcw, Wand2 } from 'lucide-react'
import { fmtNum } from '../../lib/format'
import { yearsAgo } from '../../lib/dateRange'
import { parseSymbols } from '../../lib/optimizePrefs'
import { Alert, Button, Card, Field, Input, Select, Switch } from '../ui'
import { Chip, Section, Step } from '../form/parts'
import { TermIcon, TermLabel, TermTip } from '../terms/TermTip'
import { PlanSummary } from './PlainSummary'
import { OBJECTIVE_PRESETS, PERIOD_PRESETS, POOL_PRESETS } from './presets'
import type { Meta, OptForm, OptSetters } from './types'

interface Props {
  meta: Meta | null
  form: OptForm
  set: OptSetters
  beginner: boolean
  onBeginner: (v: boolean) => void
  onApplyRecommended: () => void
  onResetDefaults: () => void
  onRun: () => void
  running: boolean
}

export default function OptimizeConfigPanel({
  meta,
  form,
  set,
  beginner,
  onBeginner,
  onApplyRecommended,
  onResetDefaults,
  onRun,
  running,
}: Props) {
  const symbols = parseSymbols(form.symbolsText)
  const objective = meta?.objectives.find((o) => o.key === form.objective)
  const activePool = POOL_PRESETS.find((p) => p.symbols === form.symbolsText)

  // 单标的上限 × 标的数 < 总仓位时约束不可行 —— 前端先提示，避免用户白等一次计算。
  // 判据与后端 `is_feasible()` 一致（含 1e-9 容差）。
  const capInfeasible =
    symbols.length > 1 && (form.maxWeight / 100) * symbols.length < form.maxGross / 100 - 1e-9
  const minGrossPct = Math.floor((form.maxWeight / 100) * symbols.length * 100)

  return (
    <Card
      className="xl:col-span-1"
      title={
        <span className="flex items-center gap-1.5">
          优化配置
          <TermIcon id="portfolio_optimize" />
        </span>
      }
      subtitle={beginner ? '按 ①②③④ 填完就能跑，其余用推荐值' : '协方差与期望收益均为历史估计，不含前瞻信息'}
      actions={
        <>
          <Button size="sm" icon={<RotateCcw className="h-3.5 w-3.5" />} onClick={onResetDefaults}>
            恢复默认
          </Button>
          <Button
            size="sm"
            variant="primary"
            icon={<Play className="h-3.5 w-3.5" />}
            loading={running}
            onClick={onRun}
            disabled={symbols.length < 2}
          >
            {running ? '求解中…' : '开始优化'}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {/* ---------------- 模式开关 ---------------- */}
        <div className="space-y-2 rounded-lg bg-slate-50 p-3">
          <Switch
            checked={beginner}
            onChange={onBeginner}
            label={<TermLabel id="beginner_mode">新手模式</TermLabel>}
            hint="只留必填项，协方差估计、簇上限这些收进「高级设置」。关掉它可以看到全部参数。"
          />
          {beginner && (
            <Button size="sm" className="w-full" icon={<Wand2 className="h-3.5 w-3.5" />} onClick={onApplyRecommended}>
              一键填入推荐配置
            </Button>
          )}
        </div>

        {/* ---------------- ① 标的池 ---------------- */}
        <Step n={1} title="放哪些标的" tip="symbol_pool">
          <Field
            label={<TermLabel id="symbol_pool">标的池</TermLabel>}
            hint={
              symbols.length
                ? `已识别 ${symbols.length} 个：${symbols.join(' · ')}`
                : '至少 2 个，逗号或空格分隔，例如 SPY, TLT, GLD'
            }
          >
            <Input
              value={form.symbolsText}
              onChange={(e) => set.setSymbolsText(e.target.value.toUpperCase())}
              placeholder="SPY, TLT, IEF, GLD, DBC, VNQ"
            />
          </Field>
          <div className="flex flex-wrap gap-1.5">
            {POOL_PRESETS.map((p) => (
              <Chip
                key={p.name}
                active={activePool?.name === p.name}
                title={p.note}
                onClick={() => set.setSymbolsText(p.symbols)}
              >
                {p.name}
              </Chip>
            ))}
          </div>
          {activePool && <p className="text-[11px] leading-5 text-slate-500">{activePool.note}</p>}
          <p className="text-[11px] leading-5 text-slate-400">
            想用别的股票就在输入框里手输。把鼠标放到「标的池」旁边的小问号上，有说明。
          </p>
        </Step>

        {/* ---------------- ② 优化目标 ---------------- */}
        <Step n={2} title="想要什么效果" tip="objective">
          {beginner ? (
            <div className="flex flex-wrap gap-1.5">
              {OBJECTIVE_PRESETS.map((o) => (
                <Chip key={o.key} active={form.objective === o.key} onClick={() => set.setObjective(o.key)}>
                  {o.label}
                </Chip>
              ))}
            </div>
          ) : (
            <Field label={<TermLabel id="objective">优化目标</TermLabel>} hint={objective?.desc}>
              <Select value={form.objective} onChange={(e) => set.setObjective(e.target.value)}>
                {(meta?.objectives ?? []).map((o) => (
                  <option key={o.key} value={o.key}>
                    {o.label}
                  </option>
                ))}
              </Select>
            </Field>
          )}
          {beginner && objective && (
            <p className="text-[11px] leading-5 text-slate-500">
              {objective.desc}
              {OBJECTIVE_PRESETS.find((o) => o.key === form.objective)?.why
                ? ` ${OBJECTIVE_PRESETS.find((o) => o.key === form.objective)!.why}`
                : ''}
            </p>
          )}
        </Step>

        {/* ---------------- ③ 历史区间 ---------------- */}
        <Step n={3} title="用多长历史" tip="start_date">
          <div className="flex flex-wrap gap-1.5">
            {PERIOD_PRESETS.map((p) => (
              <Chip key={p.years} active={form.start === yearsAgo(p.years)} onClick={() => set.setStart(yearsAgo(p.years))}>
                {p.label}
              </Chip>
            ))}
          </div>
          <Field label="开始日期">
            <Input type="date" value={form.start} onChange={(e) => set.setStart(e.target.value)} />
          </Field>
          <p className="text-[11px] leading-5 text-slate-400">
            协方差是用这段历史估出来的。区间太短，估出来的权重就只是在拟合噪声。
          </p>
        </Step>

        {/* ---------------- ④ 限制条件 ---------------- */}
        <Step n={4} title="限制条件" tip="max_weight">
          <div className="grid grid-cols-2 gap-3">
            <Field
              label={<TermLabel id="max_weight">单标的上限（%）</TermLabel>}
              hint={`上限 × ${symbols.length} 个 = 最多配到 ${minGrossPct}%，必须 ≥ 总仓位`}
            >
              <Input
                type="number"
                min={1}
                max={100}
                value={form.maxWeight}
                onChange={(e) => set.setMaxWeight(Number(e.target.value))}
              />
            </Field>
            <Field label={<TermLabel id="max_gross">总仓位（%）</TermLabel>} hint="100% 为满仓，设 80% 就是留 20% 现金">
              <Input
                type="number"
                min={1}
                max={100}
                value={form.maxGross}
                onChange={(e) => set.setMaxGross(Number(e.target.value))}
              />
            </Field>
          </div>
          {capInfeasible && (
            <Alert tone="warn" title="约束不可行：单标的上限 × 标的数 小于 总仓位">
              当前 {form.maxWeight}% × {symbols.length} = {form.maxWeight * symbols.length}%，小于总仓位{' '}
              {form.maxGross}%。求解器会自动把上限放宽到 {(form.maxGross / symbols.length).toFixed(1)}% 并显式标注；
              想严格守住 {form.maxWeight}%，请把总仓位降到 {minGrossPct}% 以下，或者多加几个标的。
            </Alert>
          )}
        </Step>

        {/* ---------------- 高级设置 ---------------- */}
        <Section title="高级设置（一般不用改）" tip="cov_method" collapsed={beginner}>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={<TermLabel id="cov_method">协方差估计</TermLabel>} hint={meta?.cov_methods.find((o) => o.key === form.covMethod)?.desc}>
              <Select value={form.covMethod} onChange={(e) => set.setCovMethod(e.target.value)}>
                {(meta?.cov_methods ?? []).map((o) => (
                  <option key={o.key} value={o.key}>
                    {o.label}
                  </option>
                ))}
              </Select>
            </Field>
            <Field
              label={<TermLabel id="return_method">期望收益估计</TermLabel>}
              hint={meta?.return_methods.find((o) => o.key === form.returnMethod)?.desc}
            >
              <Select value={form.returnMethod} onChange={(e) => set.setReturnMethod(e.target.value)}>
                {(meta?.return_methods ?? []).map((o) => (
                  <option key={o.key} value={o.key}>
                    {o.label}
                  </option>
                ))}
              </Select>
            </Field>
            <Field
              label={<TermLabel id="corr_threshold">相关簇阈值（%）</TermLabel>}
              hint="相关系数 ≥ 阈值即视为同一伙（同涨同跌）"
            >
              <Input
                type="number"
                min={0}
                max={100}
                value={form.corrThreshold}
                onChange={(e) => set.setCorrThreshold(Number(e.target.value))}
              />
            </Field>
            <Field label={<TermLabel id="max_cluster_weight">单簇上限（%）</TermLabel>} hint="伪分散防护：同一伙标的总权重不超过此值">
              <Input
                type="number"
                min={1}
                max={100}
                value={form.maxCluster}
                onChange={(e) => set.setMaxCluster(Number(e.target.value))}
              />
            </Field>
            <Field label={<TermLabel id="risk_free">无风险利率（%）</TermLabel>} hint="用于计算夏普比率，填 0 也能用">
              <Input
                type="number"
                step={0.1}
                value={form.riskFree}
                onChange={(e) => set.setRiskFree(Number(e.target.value))}
              />
            </Field>
            <Field label="数据周期">
              <Select value={form.interval} onChange={(e) => set.setInterval(e.target.value)}>
                <option value="1d">日线</option>
                <option value="1wk">周线</option>
              </Select>
            </Field>
          </div>

          <div className="space-y-3 pt-1">
            <Switch
              checked={form.longOnly}
              onChange={set.setLongOnly}
              label={<TermLabel id="long_only">仅做多</TermLabel>}
              hint="关闭则允许负权重（做空/杠杆）。本机回测暂不支持负仓位撮合。"
            />
            <Switch
              checked={form.includeFrontier}
              onChange={set.setIncludeFrontier}
              label={<TermLabel id="include_frontier">计算有效前沿</TermLabel>}
              hint="关闭可显著加快求解"
            />
            <Switch
              checked={form.useBudget}
              onChange={set.setUseBudget}
              label={<TermLabel id="risk_budget">启用风险预算</TermLabel>}
              hint="只在「风险平价」目标下生效。格式：SPY:3, TLT:2, GLD:1"
            />
            {form.useBudget && (
              <Input
                value={form.budgetText}
                onChange={(e) => set.setBudgetText(e.target.value)}
                placeholder="SPY:3, TLT:2, GLD:1"
              />
            )}
          </div>
        </Section>

        {/* ---------------- 人话预览 + 运行 ---------------- */}
        <PlanSummary
          poolName={activePool?.name ?? ''}
          symbols={symbols}
          objectiveLabel={objective?.label ?? ''}
          start={form.start}
          maxWeight={form.maxWeight}
          maxGross={form.maxGross}
        />

        <Button
          variant="primary"
          size="lg"
          className="w-full"
          loading={running}
          onClick={onRun}
          disabled={symbols.length < 2}
          icon={<Play className="h-4 w-4" />}
        >
          开始优化
        </Button>
        <p className="flex items-center justify-center gap-1 text-center text-[11px] leading-5 text-slate-400">
          <AlertTriangle className="h-3 w-3" />
          优化器只决定权重，不替你判断标的该不该买。当前已识别 {fmtNum(symbols.length, 0)} 个标的。
        </p>
      </div>
    </Card>
  )
}
