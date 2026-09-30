// AI Copilot 的「关键价位」卡片（FILE_SIZE_DEBT Batch C-2 拆分）
import { Card } from '../ui'
import { fmtNum } from '../../lib/format'
import type { AIResult } from '../../lib/types'

export function LevelsCard({ active }: { active: AIResult }) {
  return (
    <Card title="关键价位" subtitle="支撑取低于现价、阻力取高于现价的有效结构位">
      <div className="grid gap-5 sm:grid-cols-2">
        <div>
          <div className="mb-2 flex items-center gap-2">
            <span className="text-xs font-semibold uppercase tracking-wide text-emerald-600">支撑位</span>
            <div className="h-px flex-1 bg-emerald-100" />
          </div>
          <div className="space-y-2">
            {active.levels?.支撑?.length ? (
              active.levels.支撑.map((v, i) => (
                <div key={i} className="flex items-center justify-between rounded-lg border border-emerald-100 bg-emerald-50/50 px-3 py-2">
                  <span className="text-xs text-slate-500">S{i + 1}</span>
                  <span className="num text-sm font-semibold text-emerald-700">{fmtNum(v, 2)}</span>
                  <span className="num text-xs text-slate-500">
                    {/* P3：旧实现直接除以 active.price —— 价格为 0 时输出
                        "Infinity%" / "NaN%"。这里显式兜底。 */}
                    {active.price
                      ? `${(((v - active.price) / active.price) * 100).toFixed(2)}%`
                      : '—'}
                  </span>
                </div>
              ))
            ) : (
              <p className="text-xs text-slate-400">现价下方未识别到有效支撑</p>
            )}
          </div>
        </div>
        <div>
          <div className="mb-2 flex items-center gap-2">
            <span className="text-xs font-semibold uppercase tracking-wide text-rose-600">阻力位</span>
            <div className="h-px flex-1 bg-rose-100" />
          </div>
          <div className="space-y-2">
            {active.levels?.阻力?.length ? (
              active.levels.阻力.map((v, i) => (
                <div key={i} className="flex items-center justify-between rounded-lg border border-rose-100 bg-rose-50/50 px-3 py-2">
                  <span className="text-xs text-slate-500">R{i + 1}</span>
                  <span className="num text-sm font-semibold text-rose-700">{fmtNum(v, 2)}</span>
                  <span className="num text-xs text-slate-500">
                    {/* P3：同支撑位 —— 价格为 0 时不得输出 Infinity/NaN */}
                    {active.price
                      ? `${(((v - active.price) / active.price) * 100).toFixed(2)}%`
                      : '—'}
                  </span>
                </div>
              ))
            ) : (
              <p className="text-xs text-slate-400">现价上方未识别到有效阻力</p>
            )}
          </div>
        </div>
      </div>
    </Card>
  )
}
