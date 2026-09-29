/**
 * 历史批次与归档报告
 *
 * 从 `pages/Intel.tsx` 抽出（页面超硬上限）。
 * 列表口径已修正：显示**运行窗口内实查**的事件/建议条数（`events_in_window`），
 * 而不是 run 自报的 `events_found`（后者长期为 0）。老后端不返回时回落自报值。
 */
import { useState } from 'react'
import { Copy, Download, FileText } from 'lucide-react'
import { Badge, Button, Card, Empty, Modal, useToast } from '../ui'
import { api } from '../../lib/api'
import { copyText } from './BridgeGuide'
import { fmtDuration, fmtUtc, type Run } from './types'

export default function RunsPanel({ runs }: { runs: Run[] }) {
  const toast = useToast()
  const [report, setReport] = useState<{ id: number; md: string } | null>(null)
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(0)

  const viewReport = async (id: number) => {
    setBusy(id)
    try {
      const d = await api.get<{ markdown: string }>(`/intel/runs/${id}/report`)
      setReport({ id, md: d.markdown })
    } catch (e: any) {
      toast('error', e.message)
    } finally {
      setBusy(0)
    }
  }

  const download = () => {
    if (!report) return
    const blob = new Blob([report.md], { type: 'text/markdown;charset=utf-8' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `intel-run-${report.id}.md`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  return (
    <Card
      className="shrink-0"
      title="历史批次与归档报告"
      subtitle={`${runs.length} 个批次 · 截止时自动落盘 Markdown 报告`}
      actions={
        <Button size="sm" variant="ghost" onClick={() => setOpen(true)}>
          展开表格
        </Button>
      }
    >
      {runs.length === 0 ? (
        <Empty title="还没有批次记录" desc="点击「一键开启监控」开始第一批" />
      ) : (
        <ul className="space-y-1.5">
          {runs.slice(0, 5).map((r) => {
            let agents: string[] = []
            try {
              agents = JSON.parse(r.agents_seen || '[]')
            } catch {
              /* ignore */
            }
            return (
              <li key={r.id} className="flex flex-wrap items-center gap-2 rounded-lg border border-slate-100 px-2.5 py-1.5 text-[11px]">
                <span className="num font-semibold text-slate-700">#{r.id}</span>
                {r.status === 'running' ? (
                  <Badge tone="green" dot>
                    运行中
                  </Badge>
                ) : r.status === 'finished' ? (
                  <Badge tone="slate">已归档</Badge>
                ) : (
                  <Badge tone="amber">中断收尾</Badge>
                )}
                <span className="num text-slate-500">{r.events_found} / {r.analyses_done}</span>
                <span className="truncate text-slate-400">{agents.length ? agents.join('、') : '—'}</span>
                <span className="ml-auto text-slate-400">{fmtUtc(r.started_at).slice(5)}</span>
                <Button size="sm" variant="ghost" loading={busy === r.id} icon={<FileText className="h-3 w-3" />} onClick={() => viewReport(r.id)}>
                  报告
                </Button>
              </li>
            )
          })}
        </ul>
      )}

      <Modal open={open} onClose={() => setOpen(false)} title="历史批次" width="max-w-4xl" footer={<Button onClick={() => setOpen(false)}>关闭</Button>}>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-slate-200 text-left text-slate-400">
                <th className="py-2 pr-3 font-medium">批次</th>
                <th className="py-2 pr-3 font-medium">状态</th>
                <th className="py-2 pr-3 font-medium">运行窗口</th>
                <th className="py-2 pr-3 font-medium">时长</th>
                <th className="py-2 pr-3 font-medium">事件 / 建议</th>
                <th className="py-2 pr-3 font-medium">参与 Agent</th>
                <th className="py-2 pr-3 font-medium">报告</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => {
                let agents: string[] = []
                try {
                  agents = JSON.parse(r.agents_seen || '[]')
                } catch {
                  /* ignore */
                }
                const started = r.started_at ? new Date(`${r.started_at}${r.started_at.includes('+') ? '' : 'Z'}`) : null
                const ended = r.ended_at ? new Date(`${r.ended_at}${r.ended_at.includes('+') ? '' : 'Z'}`) : null
                const secs = started ? Math.max(0, ((ended ?? new Date()).getTime() - started.getTime()) / 1000) : null
                return (
                  <tr key={r.id} className="border-b border-slate-50 text-slate-600">
                    <td className="num py-2 pr-3 font-semibold text-slate-700">#{r.id}</td>
                    <td className="py-2 pr-3">
                      {r.status === 'running' ? (
                        <Badge tone="green" dot>
                          运行中
                        </Badge>
                      ) : r.status === 'finished' ? (
                        <Badge tone="slate">已归档</Badge>
                      ) : (
                        <Badge tone="amber">中断收尾</Badge>
                      )}
                    </td>
                    <td className="num py-2 pr-3">
                      {fmtUtc(r.started_at)} → {r.ended_at ? fmtUtc(r.ended_at) : '进行中'}
                    </td>
                    <td className="num py-2 pr-3">{fmtDuration(secs)}</td>
                    <td className="num py-2 pr-3">
                      {r.events_found} / {r.analyses_done}
                    </td>
                    <td className="py-2 pr-3">{agents.length ? agents.join('、') : '—'}</td>
                    <td className="py-2 pr-3">
                      <Button size="sm" variant="ghost" loading={busy === r.id} icon={<FileText className="h-3.5 w-3.5" />} onClick={() => viewReport(r.id)}>
                        查看
                      </Button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-[11px] text-slate-400">
          「事件 / 建议」为批次自身累计的提交计数；若长期为 0 而总控显示有产出，说明产出未带批次号（外部 Agent 提交时常见），
          请以总控的「本批抓取 / 建议」为准。
        </p>
      </Modal>

      <Modal
        open={!!report}
        onClose={() => setReport(null)}
        title={`批次报告 · Run #${report?.id ?? ''}`}
        width="max-w-3xl"
        footer={
          <>
            <Button icon={<Copy className="h-3.5 w-3.5" />} onClick={() => report && copyText(report.md, '报告', toast)}>
              复制
            </Button>
            <Button variant="primary" icon={<Download className="h-3.5 w-3.5" />} onClick={download}>
              下载 .md
            </Button>
          </>
        }
      >
        <pre className="whitespace-pre-wrap text-xs leading-relaxed text-slate-700">{report?.md}</pre>
      </Modal>
    </Card>
  )
}
