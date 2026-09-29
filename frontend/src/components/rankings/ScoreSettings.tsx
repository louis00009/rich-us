/**
 * 评分设置面板：候选池阈值滑杆 + 四维权重开关。
 *
 * 从 `pages/Rankings.tsx` 拆出来（铁律 9：页面只做编排，可复用业务块抽到 components/）。
 * 页面只保留 view / threshold / weights 三个状态，面板自己负责交互细节。
 *
 * 两个刻意的设计：
 *  ① **权重不必凑成 100** —— 后端会归一化。要求用户凑满 100 会让人为了「凑数」
 *     去调他其实不在意的维度，反而污染了评分。
 *  ② **取消勾选 = 权重 0 = 该维度关闭**，而不是「记 0 分」。0 分会把标的往下拉，
 *     关闭则是不参与 —— 这两者语义完全不同，后端 `score_row` 已按后者实现。
 */

export interface Weights {
  valuation: number
  quality: number
  position: number
  trend: number
}

export const DEFAULT_W: Weights = { valuation: 30, quality: 30, position: 20, trend: 20 }

export const DIM_LABELS: Record<keyof Weights, string> = {
  valuation: '估值',
  quality: '质量',
  position: '位置',
  trend: '趋势',
}

export const DIM_HINTS: Record<keyof Weights, string> = {
  valuation: '便宜度：同行业 PE 分位为主，PB 与股息率为辅',
  quality: '赚钱能力：ROE 为主（30% 以上封顶，过高常是回购使净资产变小）',
  position: '位置：距 52 周高的回撤深度，跌得越多分越高',
  trend: '趋势：现价相对 MA200 / MA60 的位置与中期动量，高波动扣分',
}

export default function ScoreSettings({
  threshold,
  onThreshold,
  weights,
  onWeights,
  poolCount,
  onReset,
}: {
  threshold: number
  onThreshold: (n: number) => void
  weights: Weights
  onWeights: (w: Weights) => void
  /** 当前阈值下符合的标的数（由后端 bands 统计，非当前页条数） */
  poolCount: number | null
  onReset: () => void
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white px-3 py-2.5">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className="text-[11px] font-medium text-slate-500">候选池阈值</span>
        <input
          type="range"
          min={0}
          max={100}
          step={1}
          value={threshold}
          onChange={(e) => onThreshold(Number(e.target.value))}
          className="h-1 w-48 accent-brand-600"
          aria-label="候选池评分阈值"
        />
        <span className="num text-xs font-semibold text-brand-700">≥ {threshold} 分</span>
        {poolCount != null && (
          <span className="text-[11px] text-slate-400">当前共 {poolCount} 只符合</span>
        )}
        <button onClick={onReset} className="ml-auto text-[11px] text-slate-400 hover:text-brand-700">
          恢复默认（30/30/20/20 · 阈值 70）
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-slate-100 pt-2.5">
        {(Object.keys(DEFAULT_W) as (keyof Weights)[]).map((k) => (
          <div key={k} className="flex items-center gap-2" title={DIM_HINTS[k]}>
            <label className="flex w-24 cursor-pointer items-center gap-1.5 text-xs text-slate-600">
              <input
                type="checkbox"
                checked={weights[k] > 0}
                onChange={(e) => onWeights({ ...weights, [k]: e.target.checked ? DEFAULT_W[k] : 0 })}
                className="h-3.5 w-3.5 rounded border-slate-300 text-brand-600"
              />
              {DIM_LABELS[k]}
            </label>
            <input
              type="range"
              min={0}
              max={60}
              step={5}
              value={weights[k]}
              disabled={weights[k] === 0}
              onChange={(e) => onWeights({ ...weights, [k]: Number(e.target.value) })}
              className={`h-1 w-24 ${weights[k] === 0 ? 'opacity-30' : 'accent-brand-600'}`}
              aria-label={`${DIM_LABELS[k]}权重`}
            />
            <span className="num w-8 text-[11px] tabular-nums text-slate-500">{weights[k]}</span>
          </div>
        ))}
      </div>

      <p className="mt-2 text-[11px] leading-5 text-slate-400">
        权重会自动归一化，不必凑成 100。取消勾选 = 该维度不计入总分（适合你暂时不关心某个维度时）。
        注意：分数只反映<strong className="font-medium">数据齐全</strong>的那部分，缺数据的标的会被标「数据不全」。
      </p>
    </div>
  )
}
