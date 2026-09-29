/**
 * FrontierTab —— 有效前沿 tab
 * ============================
 * 从 `ResultPanel.tsx` 抽出（铁律 9：组件 400 行软上限，抽出前 ResultPanel 424 行）。
 * 纯展示，无状态：数据全部来自 result。
 *
 * 这块的阅读门槛最高（横轴风险、纵轴收益、三种标记点），所以配一段人话说明，
 * 而不是只丢一张散点图。
 */
import { EfficientFrontierChart } from '../charts'
import { DataTable } from '../ui'
import { fmtNum, fmtRatioPct, signClass } from '../../lib/format'
import type { OptResult } from './types'

export default function FrontierTab({ result }: { result: OptResult }) {
  return (
    <div className="space-y-3 px-3 pb-3">
      <EfficientFrontierChart
        points={result.frontier}
        current={{ ret: result.portfolio.ann_return, vol: result.portfolio.ann_vol }}
        equalWeight={{
          ret: result.benchmark_equal_weight.ann_return,
          vol: result.benchmark_equal_weight.ann_vol,
        }}
        assets={result.assets}
      />
      <p className="text-xs text-slate-500">
        横轴为年化波动、纵轴为年化收益。灰色散点是各标的自身位置，金色三角为 1/N 等权基准，紫色星号为当前优化解。
        理论上最优组合应落在前沿曲线与「最大夏普射线」的切点上 —— 若它反而落在曲线内侧，
        说明约束（单标的上限 / 簇上限）把它从最优点上拽了回来，这是正常现象，不是算错了。
      </p>
      <DataTable
        columns={[
          {
            key: 'i',
            label: '#',
            width: '48px',
            render: (_r, i) => <span className="num text-slate-400">{i + 1}</span>,
          },
          {
            key: 'lam',
            label: 'λ',
            align: 'right',
            render: (r: any) => <span className="num text-slate-500">{fmtNum(r.lambda, 4)}</span>,
          },
          {
            key: 'vol',
            label: '年化波动',
            align: 'right',
            render: (r: any) => <span className="num">{fmtRatioPct(r.vol)}</span>,
          },
          {
            key: 'ret',
            label: '年化收益',
            align: 'right',
            render: (r: any) => <span className={`num ${signClass(r.ret)}`}>{fmtRatioPct(r.ret, 2, true)}</span>,
          },
          {
            key: 'sharpe',
            label: '夏普',
            align: 'right',
            render: (r: any) => <span className="num">{fmtNum(r.sharpe, 3)}</span>,
          },
        ]}
        rows={result.frontier}
        maxHeight="320px"
      />
    </div>
  )
}
