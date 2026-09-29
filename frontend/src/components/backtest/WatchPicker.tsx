/**
 * WatchPicker —— 从「关注列表」挑回测标的
 * ========================================
 * 从 pages/Backtest.tsx 抽出（铁律 9：页面文件已超硬上限）。
 * 自持「加载 / 勾选」状态，父级只需要告诉它「打开」和「当前已有哪些标的」。
 *
 * ⚠️ 用 ref 读当前的 symbols，而不是把它放进 useEffect 依赖：
 *    放依赖会让「父级 symbols 一变就重新拉取 + 重置勾选」，
 *    而确认回写 symbols 恰恰会触发这个变化 —— 表现为弹窗内容闪一下。
 */
import { useEffect, useRef, useState } from 'react'
import { api } from '../../lib/api'
import { symbolsToList } from '../../lib/backtestPrefs'
import { fmtNum } from '../../lib/format'
import { Button, Empty, Loading, Modal, useToast } from '../ui'

export default function WatchPicker({
  open,
  symbols,
  onClose,
  onConfirm,
}: {
  open: boolean
  symbols: string
  onClose: () => void
  onConfirm: (merged: string) => void
}) {
  const toast = useToast()
  const [items, setItems] = useState<any[]>([])
  const [sel, setSel] = useState<string[]>([])
  const [loading, setLoading] = useState(false)

  const symRef = useRef(symbols)
  symRef.current = symbols

  useEffect(() => {
    if (!open) return
    let alive = true
    setLoading(true)
    setSel(symbolsToList(symRef.current))
    api
      .get<{ items: any[] }>('/watchlist')
      .then((r) => {
        if (alive) setItems(r.items || [])
      })
      .catch((e: any) => toast('error', e?.message || '加载关注列表失败'))
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [open, toast])

  const confirm = () => {
    const current = symbolsToList(symRef.current)
    const all = [...new Set([...current, ...sel])]
    const merged = all.slice(0, 10)
    onConfirm(merged.join(','))
    toast(
      'success',
      `已加入 ${sel.length} 只收藏标的（共 ${merged.length} 只${all.length > 10 ? '，超出 10 只的部分已截断' : ''}）`,
    )
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="从关注列表选择标的"
      width="max-w-lg"
      footer={
        <>
          <Button onClick={onClose}>取消</Button>
          <Button variant="primary" disabled={!sel.length} onClick={confirm}>
            加入所选（{sel.length}）
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        {loading && <Loading label="加载关注列表…" />}
        {!loading && items.length === 0 && (
          <Empty title="关注列表为空" desc="先在美股榜单或行情页点击星标加入关注，再回到这里选择。" />
        )}
        {!loading && items.length > 0 && (
          <>
            <p className="text-xs text-slate-400">
              勾选后点击「加入所选」，将与现有标的合并（去重，最多 10 只）。
            </p>
            <div className="max-h-80 space-y-1 overflow-y-auto">
              {items.map((w) => (
                <label
                  key={w.symbol}
                  className="flex cursor-pointer items-center gap-2 rounded-lg border border-slate-100 px-3 py-2 text-sm hover:bg-slate-50"
                >
                  <input
                    type="checkbox"
                    className="h-3.5 w-3.5 rounded border-slate-300 text-brand-600"
                    checked={sel.includes(w.symbol)}
                    onChange={(e) =>
                      setSel((s) => (e.target.checked ? [...new Set([...s, w.symbol])] : s.filter((x) => x !== w.symbol)))
                    }
                  />
                  <span className="font-medium text-slate-800">{w.symbol}</span>
                  <span className="truncate text-xs text-slate-400">{w.name_cn || w.note || ''}</span>
                  <span className="num ml-auto text-xs text-slate-500">{w.price ? fmtNum(w.price, 2) : ''}</span>
                </label>
              ))}
            </div>
          </>
        )}
      </div>
    </Modal>
  )
}
