/**
 * ConfigPanel —— 回测配置面板（小白友好版）
 * =========================================
 * 用户原话（2026-09-29）：「回测中心对于我（小白）来说太难用了 …… 基准标的和标的
 * 我理解不了，希望把这套东西尽可能简化、易于理解，并且针对一些词汇都有鼠标悬浮的解释」。
 *
 * 所以这里做了三件事，而不是把原来的表单换个皮：
 *  ① **分步**：原来 13 个控件平铺在一起，不知道从哪看起。现在拆成
 *     「① 用哪个策略 → ② 买哪些股票 → ③ 回测多久 → ④ 本金与及格线」四步，
 *     并且把这一步「为什么要有」写进 label 里（如「对比基准（及格线）」）；
 *  ② **新手模式（默认开）**：只留必填项，其余收进「高级设置」折叠区；
 *     关掉它就是原来的全量专业面板 —— 不删功能，只是默认不吓人；
 *  ③ **每个术语都能悬停**：策略 / 标的 / 本金 / 基准 / 周期 / 数据源 / 手续费 /
 *     滑点 / 止损 / 仓位，以及结果页的每一个指标，都挂 `TermTip`（见 components/terms/）。
 *
 * ⚠️ 本组件是**纯受控展示组件**：不持有任何配置状态，全部值/写回由父级传入。
 *    唯一例外是「时长是否展开自定义日期」这个纯 UI 开关（`customDates`）。
 *    这样做的原因是回测配置有 prefill / localStorage / 参数记忆三条写入路径，
 *    状态必须集中在 Backtest.tsx 一处，拆开必然出现「两个真相」。
 *
 * 排版零件在 `parts.tsx`，高级设置区块在 `AdvancedSettings.tsx`，共享类型在 `types.ts`
 * （铁律 9：组件 600 行硬上限，本文件此前已顶到 648 行）。
 */
import { Calendar, FlaskConical, GitCompare, Play, Settings2, Star, Wand2 } from 'lucide-react'
import { useState } from 'react'
import { symbolsToList } from '../../lib/backtestPrefs'
import { fmtMoney } from '../../lib/format'
import type { DataSourceInfo, StrategyConfig, StrategyInfo } from '../../lib/types'
import ParamForm from '../strategies/ParamForm'
import { Badge, Button, Card, Field, Input, Select, Switch } from '../ui'
import AdvancedSettings from './AdvancedSettings'
import { Chip, Section, Step } from '../form/parts'
import { PlanSummary } from './PlainSummary'
import { TermIcon, TermLabel, TermTip } from '../terms/TermTip'
import {
  ADVANCED_CATEGORIES,
  BEGINNER_STRATEGIES,
  BENCHMARK_PRESETS,
  PERIOD_PRESETS,
  SYMBOL_PRESETS,
  yearsAgo,
} from './presets'
import type { ConfigForm, ConfigSetters, MetaResp } from './types'

// 类型从 types.ts 统一出口再导出一次：页面只认 ConfigPanel 这一个入口，
// 不必知道内部被拆成了几个文件。
export type { ConfigForm, ConfigSetters, MetaResp } from './types'

interface Props {
  meta: MetaResp | null
  builtin: StrategyInfo[]
  customs: StrategyConfig[]
  dsInfo: DataSourceInfo | null
  currentStrategy: StrategyInfo | null
  form: ConfigForm
  set: ConfigSetters
  beginner: boolean
  onBeginner: (v: boolean) => void
  onStrategyChange: (v: string) => void
  onApplyRecommended: () => void
  onRun: () => void
  running: boolean
  onOpenWatch: () => void
  onOpenOptimize: () => void
  onOpenCompare: () => void
  onOpenFactor: () => void
}

export default function ConfigPanel({
  meta,
  builtin,
  customs,
  dsInfo,
  currentStrategy,
  form,
  set,
  beginner,
  onBeginner,
  onStrategyChange,
  onApplyRecommended,
  onRun,
  running,
  onOpenWatch,
  onOpenOptimize,
  onOpenCompare,
  onOpenFactor,
}: Props) {
  // 仅 UI 开关：新手模式下默认只显示时长预设，点「自定义」才露出日期框
  const [customDates, setCustomDates] = useState(false)

  const symList = symbolsToList(form.symbols)
  const usingPreset = PERIOD_PRESETS.some((p) => form.start === yearsAgo(p.years) && !form.end)
  const showDates = !beginner || customDates || !usingPreset
  const advCat = !!currentStrategy && ADVANCED_CATEGORIES.includes(currentStrategy.category)
  const beginnerWhy = BEGINNER_STRATEGIES.find((b) => b.key === form.strategyKey)?.why
  const strategyValue = form.customId === '' ? form.strategyKey : `custom:${form.customId}`

  const toggleSymbol = (s: string) => {
    const next = symList.includes(s) ? symList.filter((x) => x !== s) : [...symList, s]
    set.setSymbols(next.join(','))
  }

  /** 新手模式下的策略下拉：推荐的排前面，其余归入「全部策略」。 */
  const renderStrategyOptions = () => {
    if (!beginner) {
      return (
        <>
          <optgroup label="内置策略">
            {builtin.map((s) => (
              <option key={s.key} value={s.key}>
                [{s.category}] {s.name}
              </option>
            ))}
          </optgroup>
          {customs.length > 0 && (
            <optgroup label="我的策略">
              {customs.map((c) => (
                <option key={`c${c.id}`} value={`custom:${c.id}`}>
                  {c.name}（{c.kind === 'rule' ? '规则' : c.kind === 'code' ? '代码' : '内置'}）
                </option>
              ))}
            </optgroup>
          )}
        </>
      )
    }
    const recKeys = BEGINNER_STRATEGIES.map((b) => b.key)
    const rec = builtin.filter((s) => recKeys.includes(s.key))
    const rest = builtin.filter((s) => !recKeys.includes(s.key))
    return (
      <>
        <optgroup label="新手推荐（规则简单）">
          {rec.map((s) => (
            <option key={s.key} value={s.key}>
              {s.name}
            </option>
          ))}
        </optgroup>
        <optgroup label="全部策略（含进阶）">
          {rest.map((s) => (
            <option key={s.key} value={s.key}>
              {s.name} · {s.category}
            </option>
          ))}
        </optgroup>
        {customs.length > 0 && (
          <optgroup label="我的策略">
            {customs.map((c) => (
              <option key={`c${c.id}`} value={`custom:${c.id}`}>
                {c.name}
              </option>
            ))}
          </optgroup>
        )}
      </>
    )
  }

  return (
    <Card
      className="xl:col-span-1"
      title={
        <span className="flex items-center gap-1.5">
          回测配置
          <TermIcon id="strategy" />
        </span>
      }
      subtitle={
        beginner ? (
          '按 ①②③④ 填完就能跑，其余用推荐值'
        ) : (
          <>
            信号延迟一根成交，<TermTip id="no_lookahead">无未来函数</TermTip>
          </>
        )
      }
    >
      <div className="space-y-4">
        {/* ---------------- 模式开关 ---------------- */}
        <div className="space-y-2 rounded-lg bg-slate-50 p-3">
          <Switch
            checked={beginner}
            onChange={onBeginner}
            label={<TermLabel id="beginner_mode">新手模式</TermLabel>}
            hint="只留必填项，其余收进「高级设置」。关掉它可以看到全部参数。"
          />
          {beginner && (
            <Button size="sm" className="w-full" icon={<Wand2 className="h-3.5 w-3.5" />} onClick={onApplyRecommended}>
              一键填入推荐配置
            </Button>
          )}
        </div>

        {/* ---------------- ① 策略 ---------------- */}
        <Step n={1} title="用哪个策略" tip="strategy">
          <Field label={<TermLabel id="strategy">策略</TermLabel>}>
            <Select value={strategyValue} onChange={(e) => onStrategyChange(e.target.value)}>
              {renderStrategyOptions()}
            </Select>
          </Field>

          {currentStrategy && (
            <div className="rounded-lg bg-slate-50 p-3">
              <p className="text-[11px] leading-relaxed text-slate-600">{currentStrategy.description}</p>
              {beginner && beginnerWhy && (
                <p className="mt-1.5 text-[11px] leading-relaxed text-brand-700">新手提示：{beginnerWhy}</p>
              )}
              {beginner && advCat && (
                <p className="mt-1.5 text-[11px] leading-relaxed text-amber-700">
                  这是进阶策略（{currentStrategy.category}），建议先用「新手推荐」里的跑通一次再回来试。
                </p>
              )}
              <div className="mt-2 flex flex-wrap gap-1">
                <Badge tone="slate">{currentStrategy.category}</Badge>
                {currentStrategy.multi_symbol && <Badge tone="blue">支持多标的</Badge>}
                {!beginner && <Badge tone="slate">≥{currentStrategy.min_bars} bar</Badge>}
                {currentStrategy.params.length > 0 && <Badge tone="violet">{currentStrategy.params.length} 个参数</Badge>}
                {currentStrategy.tags.slice(0, 3).map((t) => (
                  <Badge key={t} tone="amber">
                    {t}
                  </Badge>
                ))}
              </div>
            </div>
          )}

          {currentStrategy && currentStrategy.params.length > 0 && (
            <Section
              title={
                beginner
                  ? `策略参数（${currentStrategy.params.length}）· 不懂就别改`
                  : `策略参数（${currentStrategy.params.length}）`
              }
              collapsed={beginner}
            >
              <ParamForm
                specs={currentStrategy.params}
                values={form.params}
                onChange={(k, v) => set.setParams({ ...form.params, [k]: v })}
              />
            </Section>
          )}
        </Step>

        {/* ---------------- ② 股票 ---------------- */}
        <Step n={2} title="买哪些股票" tip="symbol">
          <Field label={<TermLabel id="symbol">股票代码（标的）</TermLabel>}>
            <div className="flex gap-2">
              <Input
                value={form.symbols}
                onChange={(e) => set.setSymbols(e.target.value.toUpperCase())}
                placeholder="SPY"
              />
              <Button size="sm" icon={<Star className="h-3.5 w-3.5" />} onClick={onOpenWatch} title="从关注列表选择">
                收藏
              </Button>
            </div>
          </Field>
          <div className="flex flex-wrap gap-1.5">
            {SYMBOL_PRESETS.map((p) => (
              <Chip key={p.value} active={symList.includes(p.value)} title={p.note} onClick={() => toggleSymbol(p.value)}>
                {p.label}
              </Chip>
            ))}
          </div>
          <p className="text-[11px] leading-5 text-slate-400">
            点上面的标签可以直接加进来，再点一下去掉。想用别的股票就在输入框里手输，多个代码用英文逗号隔开（例如
            SPY,QQQ）。
          </p>
        </Step>

        {/* ---------------- ③ 时长 ---------------- */}
        <Step n={3} title="回测多长时间" tip="period">
          <div className="flex flex-wrap gap-1.5">
            {PERIOD_PRESETS.map((p) => (
              <Chip
                key={p.years}
                active={form.start === yearsAgo(p.years) && !form.end}
                onClick={() => {
                  set.setStart(yearsAgo(p.years))
                  set.setEnd('')
                  setCustomDates(false)
                }}
              >
                {p.label}
              </Chip>
            ))}
            <Chip active={customDates} title="自己指定起止日期" onClick={() => setCustomDates((v) => !v)}>
              <span className="inline-flex items-center gap-1">
                <Calendar className="h-3 w-3" />
                自定义
              </span>
            </Chip>
          </div>
          {showDates && (
            <div className="grid grid-cols-2 gap-3">
              <Field label="开始日期">
                <Input type="date" value={form.start} onChange={(e) => set.setStart(e.target.value)} />
              </Field>
              <Field label="结束日期" hint="留空=今天">
                <Input type="date" value={form.end} onChange={(e) => set.setEnd(e.target.value)} />
              </Field>
            </div>
          )}
          {beginner && !showDates && (
            <p className="text-[11px] leading-5 text-slate-400">
              建议至少 3 年，最好能覆盖一轮完整的涨和跌，否则结论不可信。
            </p>
          )}
        </Step>

        {/* ---------------- ④ 本金与及格线 ---------------- */}
        <Step n={4} title="本金与及格线" tip="capital">
          <Field label={<TermLabel id="capital">初始资金（虚拟本金）</TermLabel>} hint="只影响金额大小，不影响收益率百分比">
            <Input
              type="number"
              value={form.capital}
              onChange={(e) => set.setCapital(parseFloat(e.target.value || '100000'))}
            />
          </Field>
          <Field
            label={<TermLabel id="benchmark">对比基准（及格线）</TermLabel>}
            hint="什么都不做、直接买它拿着不动的收益。跑不赢它，说明这套规则不如躺着不动。"
          >
            <Input value={form.benchmark} onChange={(e) => set.setBenchmark(e.target.value.toUpperCase())} />
          </Field>
          <div className="flex flex-wrap gap-1.5">
            {BENCHMARK_PRESETS.map((b) => (
              <Chip key={b.value} active={form.benchmark === b.value} onClick={() => set.setBenchmark(b.value)}>
                {b.label}
              </Chip>
            ))}
            {symList.length > 0 && (
              <Chip
                active={form.benchmark === symList[0]}
                title={`把第一个标的 ${symList[0]} 当作及格线`}
                onClick={() => set.setBenchmark(symList[0])}
              >
                和 {symList[0]} 一样
              </Chip>
            )}
          </div>
        </Step>

        {/* ---------------- 高级设置 ---------------- */}
        <AdvancedSettings meta={meta} dsInfo={dsInfo} form={form} set={set} collapsed={beginner} />

        {/* ---------------- 进阶工具 ---------------- */}
        {/* ⚠️ 问号必须放在 Button **外面**：放进 button 里会让「点问号看说明」变成
            「顺带打开弹窗」，而且 button 嵌 button 是非法嵌套。 */}
        <Section title="进阶工具" collapsed={beginner}>
          <div className="flex items-center gap-1.5">
            <Button className="flex-1" icon={<Settings2 className="h-3.5 w-3.5" />} onClick={onOpenOptimize}>
              参数寻优
            </Button>
            <TermIcon id="grid_search" />
          </div>
          <div className="flex items-center gap-1.5">
            <Button className="flex-1" icon={<GitCompare className="h-3.5 w-3.5" />} onClick={onOpenCompare}>
              多策略对比
            </Button>
            <TermIcon id="compare" />
          </div>
          <div className="flex items-center gap-1.5">
            <Button className="flex-1" icon={<FlaskConical className="h-3.5 w-3.5" />} onClick={onOpenFactor}>
              因子诊断
            </Button>
            <TermIcon id="factor_ic" />
          </div>
        </Section>

        {/* ---------------- 人话预览 + 运行 ---------------- */}
        <PlanSummary
          strategyName={currentStrategy?.name || ''}
          symbols={symList}
          start={form.start}
          end={form.end}
          capital={form.capital}
          benchmark={form.benchmark}
        />

        <Button
          variant="primary"
          size="lg"
          className="w-full"
          loading={running}
          onClick={onRun}
          icon={<Play className="h-4 w-4" />}
        >
          开始回测
        </Button>
        <p className="text-center text-[11px] leading-5 text-slate-400">
          全部指标在本地计算，不消耗任何外部额度。
          {form.capital !== 100000 && ` 本次本金 ${fmtMoney(form.capital, 0)}。`}
        </p>
      </div>
    </Card>
  )
}
