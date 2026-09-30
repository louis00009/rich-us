/**
 * 下单确认弹窗（从 `pages/LiveTrading.tsx` 拆出，铁律 9，2026-09-30）。
 *
 * 实盘订单的二次确认：标的/方向/数量/类型 + 护栏预检结果（参考价 / 名义 / 佣金 / 占权益）。
 * 纯展示 + 两个回调（关闭 / 提交）。
 */
import { Send } from 'lucide-react'
import { Alert, Badge, Button, Modal } from '../ui'
import { fmtMoney, fmtNum } from '../../lib/format'
import type { Quote } from '../../lib/types'

export default function OrderConfirmModal({
  open,
  onClose,
  onSubmit,
  placing,
  liveOn,
  side,
  symbol,
  qty,
  orderType,
  tif,
  quotes,
  preview,
}: {
  open: boolean
  onClose: () => void
  onSubmit: () => void
  placing: boolean
  /** 实盘模式 → 弹窗内额外渲染高风险提示 */
  liveOn: boolean
  side: 'BUY' | 'SELL'
  symbol: string
  qty: number
  orderType: string
  tif: string
  quotes: Record<string, Quote>
  /** 护栏预检结果（/trading/preview 的响应；字段随后端演进，故用 any） */
  preview: any
}) {
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="确认下单"
      footer={
        <>
          <Button onClick={onClose}>取消</Button>
          <Button variant={side === 'BUY' ? 'danger' : 'success'} loading={placing} onClick={onSubmit} icon={<Send className="h-3.5 w-3.5" />}>
            确认提交
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        {liveOn && (
          <Alert tone="danger" title="⚠️ 实盘订单">
            这笔订单将直接提交到真实券商账户，产生真实资金变动。
          </Alert>
        )}
        <div className="rounded-lg bg-slate-50 p-3.5 text-sm">
          <div className="flex items-center justify-between">
            <span className="text-slate-500">标的</span>
            <span className="font-semibold">{symbol}</span>
          </div>
          <div className="mt-2 flex items-center justify-between">
            <span className="text-slate-500">方向</span>
            <Badge tone={side === 'BUY' ? 'red' : 'green'}>{side}</Badge>
          </div>
          <div className="mt-2 flex items-center justify-between">
            <span className="text-slate-500">数量</span>
            <span className="num font-semibold">
              {preview?.adjusted_qty != null && preview.adjusted_qty !== qty
                ? `${fmtNum(preview.adjusted_qty, 2)} 股（护栏缩减，原 ${fmtNum(qty, 2)}）`
                : `${fmtNum(qty, 2)} 股`}
            </span>
          </div>
          <div className="mt-2 flex items-center justify-between">
            <span className="text-slate-500">类型 / 有效期</span>
            <span>
              {orderType} / {tif}
            </span>
          </div>
          {quotes[symbol] && (
            <div className="mt-2 flex items-center justify-between border-t border-slate-200 pt-2">
              <span className="text-slate-500">预估名义金额</span>
              <span className="num font-semibold">{fmtMoney(qty * quotes[symbol].price, 0)}</span>
            </div>
          )}
        </div>
        {/* T-115：确认弹窗内渲染预检结果（护栏 / 参考 / 成本） */}
        {preview && (
          <div
            className={`rounded-lg border p-3 text-xs ${
              preview.ok ? 'border-emerald-200 bg-emerald-50 text-emerald-800' : 'border-rose-200 bg-rose-50 text-rose-800'
            }`}
          >
            <div className="font-medium">
              护栏校验{preview.ok ? '通过' : '拒绝'}
              {preview.code && preview.code !== 'OK' ? `（${preview.code}）` : ''}
            </div>
            <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-slate-600">
              <span>参考价 {fmtNum(preview.estimated?.reference_price, 2)}</span>
              <span>名义 {fmtMoney(preview.estimated?.notional, 0)}</span>
              <span>佣金 ≈ {fmtMoney(preview.estimated?.commission_estimate, 2)}</span>
              <span>占权益 {preview.estimated?.pct_of_equity}%</span>
            </div>
            {preview.warnings?.length > 0 && (
              <ul className="mt-1.5 list-disc pl-4 text-amber-700">
                {preview.warnings.map((w: string, i: number) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
    </Modal>
  )
}
