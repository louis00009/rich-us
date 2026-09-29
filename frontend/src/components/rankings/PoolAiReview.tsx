/**
 * 榜单页 · AI 候选池点评 + 估值/评分口径免责说明
 *
 * AI 只解读「当前筛选条件筛出来的这一批」，**不是买入建议**。
 *
 * 从 `pages/Rankings.tsx` 抽出（铁律 9 拆分，2026-09-29）。
 *
 * 注意：`sort` / `dir` 分开传入而不是传一个拼好的字符串 —— 因为
 * ① 载荷里的 `sort` 需要 `` `${sort} ${dir}` ``（空格分隔，后端提示词按此拼）
 * ② `runKey` 需要 `` `${sort}:${dir}:...` ``（冒号分隔）
 * 两者格式不同，若只传拼好的字符串会悄悄改掉 runKey 的取值，
 * 导致「换排序方向但 runKey 不变 → AI 结果不重置」这类隐蔽回归。
 */
import AIAssist from '../AIAssist'
import type { RankRow } from './RankingsTable'

export function PoolAiReview({
  rows,
  universeTotal,
  matched,
  scoreMin,
  sort,
  dir,
  view,
  threshold,
}: {
  rows: RankRow[]
  universeTotal: number | undefined
  matched: number | undefined
  scoreMin: number | undefined
  sort: string
  dir: 'asc' | 'desc'
  view: 'all' | 'pool'
  threshold: number
}) {
  return (
    <>
      <AIAssist
        mode="panel"
        task="ranking_review"
        title="AI 候选池点评"
        desc="解读这批标的的共同特征、值得深挖的 3 个、以及需要警惕的陷阱"
        label="点评候选池"
        payload={{
          universe_total: universeTotal,
          matched,
          score_min: scoreMin,
          sort: `${sort} ${dir}`,
          rows: rows.slice(0, 40).map((r) => ({
            symbol: r.symbol,
            name: r.name,
            name_cn: r.name_cn,
            sector: r.sector,
            price: r.price,
            change_pct: r.change_pct,
            pe: r.pe_ttm,
            pb: r.pb,
            roe_pct: r.roe,
            score: r.score,
            dimensions: r.score_dims,
            rsi14: r.rsi14,
            ret_1y_pct: r.r1y,
          })),
        }}
        runKey={`${sort}:${dir}:${rows.length}:${view === 'pool' ? threshold : ''}`}
        disabled={rows.length === 0}
        disabledHint="当前筛选结果为空，先放宽条件再点评。"
        emptyHint="AI 会指出这批标的的共同画像、值得优先深挖的标的，以及估值/ROE 失真等常见陷阱。"
      />

      <p className="px-1 text-[11px] leading-5 text-slate-400">
        估值与股息率来自第三方行情源（TTM 口径），行情有延迟；PE 由榜单现价 ÷ 缓存 EPS 实时计算，
        可用页面上的现价与 EPS 自行验算。技术指标（均线 / RSI / 波动率 / Beta）由 1 年日线本地计算，
        每日更新一次，Beta 与超额收益以 SPY 为基准并按交易日对齐。
        <br />
        <strong className="font-medium text-slate-500">综合评分是筛选辅助，不是买入信号。</strong>
        本项目的复盘结论是：规则化策略在收益上打不过买入持有，其真实价值在于回撤控制。
        评分只负责把 500 多只缩小到你愿意逐个看的一小撮，最终判断请结合公司档案、行业与自身持仓情况。
        本页不构成投资建议。
      </p>
    </>
  )
}
