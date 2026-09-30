/**
 * 每日必读 · 记录留痕弹窗（自含取数）
 *
 * 从 DailyDigest 拆出（FILE_SIZE_DEBT：主文件超 400 行软上限）。
 * 证明「AI 主动分析并记录」确实落盘：每轮监控/每次重算都会在这里留一条。
 */
import { useEffect, useState } from 'react'
import { Badge, Button, Empty, Modal, useToast } from '../../ui'
import { api } from '../../../lib/api'
import { fmtUtc } from '../types'

interface HistoryItem {
  id: number
  digest_date: string
  scope: string
  event_count: number
  top_count: number
  generated_by: string
  has_llm_text: boolean
  llm_engine: string
  created_at: string | null
  updated_at: string | null
}

export default function HistoryModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const toast = useToast()
  const [hist, setHist] = useState<HistoryItem[]>([])

  useEffect(() => {
    if (!open) return
    api
      .get<{ items: HistoryItem[] }>('/intel/digest/history?limit=20')
      .then((r: { items: HistoryItem[] }) => setHist(r.items))
      .catch((e: any) => toast('error', e.message))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="每日必读 · 记录留痕"
      width="max-w-2xl"
      footer={<Button onClick={onClose}>关闭</Button>}
    >
      {hist.length === 0 ? (
        <Empty title="暂无记录" desc="监控每轮会自动生成并落库；也可点「重算」立即生成一条" />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-slate-200 text-left text-slate-400">
                <th className="py-2 pr-3 font-medium">归集日</th>
                <th className="py-2 pr-3 font-medium">窗口事件</th>
                <th className="py-2 pr-3 font-medium">必读条数</th>
                <th className="py-2 pr-3 font-medium">AI 解读</th>
                <th className="py-2 pr-3 font-medium">来源</th>
                <th className="py-2 pr-3 font-medium">更新时间</th>
              </tr>
            </thead>
            <tbody>
              {hist.map((h) => (
                <tr key={h.id} className="border-b border-slate-50 text-slate-600">
                  <td className="num py-2 pr-3 font-semibold text-slate-700">{h.digest_date}</td>
                  <td className="num py-2 pr-3">{h.event_count}</td>
                  <td className="num py-2 pr-3">{h.top_count}</td>
                  <td className="py-2 pr-3">{h.has_llm_text ? <Badge tone="violet">已记录</Badge> : <span className="text-slate-400">未生成</span>}</td>
                  <td className="py-2 pr-3">{h.generated_by === 'scheduler' ? '调度器自动' : h.generated_by}</td>
                  <td className="py-2 pr-3 text-slate-400">{h.updated_at ? fmtUtc(h.updated_at) : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Modal>
  )
}
