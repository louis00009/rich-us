import { RotateCcw } from 'lucide-react'
import { Input, Select } from '../ui'

/**
 * 榜单数值筛选面板：快速方案预设 + 估值区间 + 技术面 + 排除亏损。
 *
 * 状态用字符串保存（不是 number）：输入框清空时必须能表达「不筛选」，
 * 而 `Number('') === 0` 会把「没填」误当成「上限 0」，把所有股票筛没。
 * 转成数字只发生在构造请求参数的那一步（见 page 里的 buildParams）。
 */
export interface RankingFiltersValue {
  peMin: string
  peMax: string
  pbMax: string
  capMin: string
  divMin: string
  roeMin: string
  fromHighMax: string
  excludeLoss: boolean
  /* ---- 技术面 ---- */
  rsiMin: string
  rsiMax: string
  maPos: '' | 'above' | 'below'
  onlyBull: boolean
  volMax: string
  betaMax: string
  req1yMin: string
  excessMin: string
}

export const EMPTY_FILTERS: RankingFiltersValue = {
  peMin: '',
  peMax: '',
  pbMax: '',
  capMin: '',
  divMin: '',
  roeMin: '',
  fromHighMax: '',
  excludeLoss: false,
  rsiMin: '',
  rsiMax: '',
  maPos: '',
  onlyBull: false,
  volMax: '',
  betaMax: '',
  req1yMin: '',
  excessMin: '',
}

export interface FilterPreset {
  key: string
  label: string
  hint: string
  value: RankingFiltersValue
}

/** 快速方案。只使用本页**真实存在**的指标 —— 没有营收增速等 B 档数据就不做「成长型」。 */
export const PRESETS: FilterPreset[] = [
  {
    key: 'value',
    label: '低估价值',
    hint: 'PE 0~20、PB ≤ 3、排除亏损 —— 便宜且确实在赚钱',
    value: { ...EMPTY_FILTERS, peMin: '0', peMax: '20', pbMax: '3', excludeLoss: true },
  },
  {
    key: 'dividend',
    label: '高股息',
    hint: '股息率 ≥ 3%、市值 ≥ 500 亿 —— 现金流型配置',
    value: { ...EMPTY_FILTERS, divMin: '3', capMin: '500' },
  },
  {
    key: 'quality',
    label: '高 ROE',
    hint: 'ROE ≥ 20%、PE ≤ 40、排除亏损 —— 又便宜又能赚钱',
    value: { ...EMPTY_FILTERS, roeMin: '20', peMax: '40', excludeLoss: true },
  },
  {
    key: 'below_book',
    label: '破净',
    hint: 'PB ≤ 1、排除亏损 —— 股价跌破净资产，多见于金融/周期股',
    value: { ...EMPTY_FILTERS, pbMax: '1', excludeLoss: true },
  },
  {
    key: 'oversold',
    label: '超跌',
    hint: '距 52 周高回撤 ≥ 30% —— 位置低，但要自己判断是不是基本面变坏',
    value: { ...EMPTY_FILTERS, fromHighMax: '-30' },
  },
  {
    key: 'large',
    label: '大盘蓝筹',
    hint: '市值 ≥ 2000 亿美元 —— 流动性最好的一批',
    value: { ...EMPTY_FILTERS, capMin: '2000' },
  },
  {
    key: 'trend',
    label: '趋势向上',
    hint: '站上 200 日均线 + 均线多头排列 —— 只看趋势健康的一批',
    value: { ...EMPTY_FILTERS, maPos: 'above', onlyBull: true },
  },
  {
    key: 'calm',
    label: '低波动',
    hint: '年化波动 ≤ 25%、Beta ≤ 1.2 —— 波动小、跟大盘同步，适合稳健仓位',
    value: { ...EMPTY_FILTERS, volMax: '25', betaMax: '1.2' },
  },
]

/** 已启用的筛选条件数量（用于「已启用 N 项」提示）。 */
export function countActive(v: RankingFiltersValue): number {
  const nums = [
    v.peMin, v.peMax, v.pbMax, v.capMin, v.divMin, v.roeMin, v.fromHighMax,
    v.rsiMin, v.rsiMax, v.volMax, v.betaMax, v.req1yMin, v.excessMin,
  ]
  return (
    nums.filter((x) => x.trim() !== '').length +
    (v.excludeLoss ? 1 : 0) +
    (v.onlyBull ? 1 : 0) +
    (v.maPos ? 1 : 0)
  )
}

/** 当前值命中哪个预设（用于高亮）；无匹配返回 null。 */
export function matchPreset(v: RankingFiltersValue): string | null {
  const hit = PRESETS.find((p) => JSON.stringify(p.value) === JSON.stringify(v))
  return hit ? hit.key : null
}

function NumField({
  label,
  value,
  onChange,
  placeholder,
  unit,
}: {
  label: string
  value: string
  onChange: (s: string) => void
  placeholder?: string
  unit?: string
}) {
  return (
    <div>
      <div className="mb-1 whitespace-nowrap text-[11px] text-slate-400">{label}</div>
      <div className="flex items-center gap-1">
        <Input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          inputMode="decimal"
          // 必须用 `!w-16`：全局 `.inp` 里是 `@apply w-full`，且它在 index.css 里位于
          // `@tailwind utilities` **之后** —— 同等特异性下后者胜出，普通 `w-16` 会被吃掉，
          // 输入框会撑满整行（筛选面板被拉成一堆整行控件）。
          className="!w-16 py-1 text-center text-xs"
        />
        {unit && <span className="text-[11px] text-slate-400">{unit}</span>}
      </div>
    </div>
  )
}

export default function RankingFilters({
  value,
  onChange,
  onReset,
  matched,
}: {
  value: RankingFiltersValue
  onChange: (v: RankingFiltersValue) => void
  onReset: () => void
  matched: string | null
}) {
  const set = (patch: Partial<RankingFiltersValue>) => onChange({ ...value, ...patch })
  const active = countActive(value)

  return (
    <div className="rounded-xl border border-slate-200 bg-white px-3 py-2.5">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-[11px] text-slate-400">快速方案</span>
        {PRESETS.map((p) => (
          <button
            key={p.key}
            title={p.hint}
            onClick={() => onChange(matched === p.key ? EMPTY_FILTERS : p.value)}
            className={`rounded-full px-2.5 py-1 text-xs transition-colors ${
              matched === p.key
                ? 'bg-brand-50 font-semibold text-brand-700 ring-1 ring-brand-200'
                : 'text-slate-500 hover:bg-slate-50'
            }`}
          >
            {p.label}
          </button>
        ))}
        <button
          onClick={onReset}
          disabled={active === 0}
          className={`ml-auto inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs transition-colors ${
            active > 0 ? 'text-slate-500 hover:bg-slate-50 hover:text-brand-700' : 'cursor-default text-slate-300'
          }`}
        >
          <RotateCcw className="h-3 w-3" />
          重置{active > 0 ? `（${active} 项）` : ''}
        </button>
      </div>

      <div className="mt-2.5 flex flex-wrap items-end gap-x-4 gap-y-2 border-t border-slate-100 pt-2.5">
        <div>
          <div className="mb-1 whitespace-nowrap text-[11px] text-slate-400">市盈率 PE(TTM)</div>
          <div className="flex items-center gap-1">
            <Input
              value={value.peMin}
              onChange={(e) => set({ peMin: e.target.value })}
              placeholder="0"
              inputMode="decimal"
              className="!w-14 py-1 text-center text-xs"
            />
            <span className="text-[11px] text-slate-300">–</span>
            <Input
              value={value.peMax}
              onChange={(e) => set({ peMax: e.target.value })}
              placeholder="不限"
              inputMode="decimal"
              className="!w-16 py-1 text-center text-xs"
            />
          </div>
        </div>
        <NumField
          label="市净率 PB ≤"
          value={value.pbMax}
          onChange={(s) => set({ pbMax: s })}
          placeholder="不限"
        />
        <NumField
          label="ROE ≥"
          value={value.roeMin}
          onChange={(s) => set({ roeMin: s })}
          placeholder="不限"
          unit="%"
        />
        <NumField
          label="股息率 ≥"
          value={value.divMin}
          onChange={(s) => set({ divMin: s })}
          placeholder="不限"
          unit="%"
        />
        <NumField
          label="总市值 ≥"
          value={value.capMin}
          onChange={(s) => set({ capMin: s })}
          placeholder="不限"
          unit="亿美元"
        />
        <NumField
          label="距 52 周高 ≤"
          value={value.fromHighMax}
          onChange={(s) => set({ fromHighMax: s })}
          placeholder="-30"
          unit="%"
        />
        <label className="flex cursor-pointer items-center gap-1.5 pb-1 text-xs text-slate-600">
          <input
            type="checkbox"
            checked={value.excludeLoss}
            onChange={(e) => set({ excludeLoss: e.target.checked })}
            className="h-3.5 w-3.5 rounded border-slate-300 text-brand-600"
          />
          排除亏损标的
        </label>
      </div>

      {/* 技术面：数据来自 1 年日线（独立缓存，冷启动需约 1 分钟补齐） */}
      <div className="mt-2.5 flex flex-wrap items-end gap-x-4 gap-y-2 border-t border-slate-100 pt-2.5">
        <span className="pb-1 text-[11px] text-slate-400">技术面</span>
        <div>
          <div className="mb-1 whitespace-nowrap text-[11px] text-slate-400">RSI(14)</div>
          <div className="flex items-center gap-1">
            <Input
              value={value.rsiMin}
              onChange={(e) => set({ rsiMin: e.target.value })}
              placeholder="0"
              inputMode="decimal"
              className="!w-14 py-1 text-center text-xs"
            />
            <span className="text-[11px] text-slate-300">–</span>
            <Input
              value={value.rsiMax}
              onChange={(e) => set({ rsiMax: e.target.value })}
              placeholder="不限"
              inputMode="decimal"
              className="!w-16 py-1 text-center text-xs"
            />
          </div>
        </div>
        <div>
          <div className="mb-1 whitespace-nowrap text-[11px] text-slate-400">200 日均线</div>
          <Select
            value={value.maPos}
            onChange={(e) => set({ maPos: e.target.value as RankingFiltersValue['maPos'] })}
            className="!w-28 py-1 text-xs"
          >
            <option value="">不限</option>
            <option value="above">站上</option>
            <option value="below">跌破</option>
          </Select>
        </div>
        <NumField
          label="年化波动 ≤"
          value={value.volMax}
          onChange={(s) => set({ volMax: s })}
          placeholder="不限"
          unit="%"
        />
        <NumField
          label="Beta ≤"
          value={value.betaMax}
          onChange={(s) => set({ betaMax: s })}
          placeholder="不限"
        />
        <NumField
          label="近 1 年 ≥"
          value={value.req1yMin}
          onChange={(s) => set({ req1yMin: s })}
          placeholder="不限"
          unit="%"
        />
        <NumField
          label="超额 SPY ≥"
          value={value.excessMin}
          onChange={(s) => set({ excessMin: s })}
          placeholder="不限"
          unit="%"
        />
        <label className="flex cursor-pointer items-center gap-1.5 pb-1 text-xs text-slate-600">
          <input
            type="checkbox"
            checked={value.onlyBull}
            onChange={(e) => set({ onlyBull: e.target.checked })}
            className="h-3.5 w-3.5 rounded border-slate-300 text-brand-600"
          />
          均线多头排列
        </label>
      </div>
    </div>
  )
}
