/**
 * 当前持仓表（从 `pages/LiveTrading.tsx` 拆出，铁律 9，2026-09-30）。
 *
 * 含浮盈与占比；每行「平仓」按钮把该持仓反向填进下单表单（由父级 onClose 实现）。
 * 纯展示 + 一个回调。
 */
import { Button, Card, DataTable, Empty } from '../ui'
import { fmtMoney, fmtNum, signClass } from '../../lib/format'
import type { PositionItem } from '../../lib/types'

export default function PositionsTable({
  positions,
  onClose,
}: {
  positions: PositionItem[]
  /** 点「平仓」：把该持仓的反向单填进下单表单 */
  onClose: (row: PositionItem) => void
}) {
  return (
    <Card title="当前持仓" subtitle="含浮盈与占比" dense>
      <DataTable<PositionItem>
        rows={positions}
        rowKey={(r) => r.symbol}
        maxHeight="300px"
        empty={<Empty title="无持仓" />}
        columns={[
          { key: 's', label: '标的', render: (r) => <span className="font-medium">{r.symbol}</span> },
          { key: 'q', label: '数量', align: 'right', render: (r) => <span className="num">{fmtNum(r.quantity, 2)}</span> },
          { key: 'c', label: '成本', align: 'right', render: (r) => <span className="num">{fmtNum(r.avg_cost, 2)}</span> },
          { key: 'l', label: '现价', align: 'right', render: (r) => <span className="num">{fmtNum(r.last_price, 2)}</span> },
          { key: 'm', label: '市值', align: 'right', render: (r) => <span className="num">{fmtMoney(r.market_value, 0)}</span> },
          {
            key: 'p',
            label: '盈亏',
            align: 'right',
            render: (r) => <span className={`num ${signClass(r.unrealized_pnl)}`}>{fmtMoney(r.unrealized_pnl, 0)}</span>,
          },
          {
            key: 'w',
            label: '占比',
            align: 'right',
            render: (r) => <span className="num text-slate-500">{r.weight.toFixed(1)}%</span>,
          },
          {
            key: 'a',
            label: '',
            align: 'right',
            render: (r) => (
              <Button size="sm" onClick={() => onClose(r)}>
                平仓
              </Button>
            ),
          },
        ]}
      />
    </Card>
  )
}
