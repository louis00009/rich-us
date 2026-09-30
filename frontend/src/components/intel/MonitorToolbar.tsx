/**
 * 监控总控 · 工具栏
 *
 * 从 `MonitorBar.tsx` 抽出（铁律 9，2026-09-30：该文件 443 行，超组件软上限 400）。
 * 纯展示 + 回调透传，不含任何业务状态 —— 抽出来零风险，MonitorBar 只剩编排。
 *
 * 四个动作：① 指定标的（勾选即精确批次）② 本轮家数 ③ AI 立即抓取 ④ 开启/截止监控。
 * ⚠️ 「指定标的」按钮只负责开合拾取器；真正的 `<ScrapePicker>` 仍挂在 MonitorBar 里
 *    （render-check 的守卫要求 `MonitorBar.tsx` 自己挂载它并传 `pendingSymbols`）。
 */
import type { Dispatch, SetStateAction } from 'react'
import { ListChecks, Play, Satellite, Square } from 'lucide-react'
import { Button, Select } from '../ui'
import type { Overview } from './types'

export default function MonitorToolbar({
  ov,
  pending,
  picked,
  scrapeSymbols,
  scrapeLimit,
  setScrapeLimit,
  scrapeJob,
  busy,
  monitorOn,
  pickerOpen,
  setPickerOpen,
  onAiScrape,
  onStart,
  onStop,
}: {
  ov: Overview | null
  /** 到期待抓取的家数（与外部 Agent 的 poll 同一口径） */
  pending: number
  /** 非空 = 「指定标的」模式：勾选即精确批次，scrapeLimit 不生效 */
  picked: boolean
  scrapeSymbols: string[]
  scrapeLimit: number
  setScrapeLimit: (v: number) => void
  scrapeJob: { id: string; progress: number; total: number; note: string } | null
  busy: string
  monitorOn: boolean
  pickerOpen: boolean
  setPickerOpen: Dispatch<SetStateAction<boolean>>
  onAiScrape: () => void
  onStart: () => void
  onStop: () => void
}) {
  return (
    <div className="flex flex-wrap items-center justify-end gap-1.5">
      {/* 指定标的：勾选即精确批次。用户有重点标的 / 只想跑一家时用这个，
          不必碰运气看「待抓取前 N 家」轮到谁。选择结果持久化，刷新后仍在。 */}
      <Button
        size="sm"
        variant={picked ? 'primary' : 'ghost'}
        icon={<ListChecks className="h-3.5 w-3.5" />}
        disabled={!!scrapeJob}
        aria-expanded={pickerOpen}
        title={
          picked
            ? `已指定 ${scrapeSymbols.length} 家：${scrapeSymbols.join(' → ')}\n点此修改`
            : '从观察标的里挑要抓的公司（点选顺序 = 抓取顺序）。不选则按「本轮」家数自动取待抓取清单'
        }
        onClick={() => setPickerOpen((v) => !v)}
      >
        指定标的{picked ? ` ${scrapeSymbols.length}` : ''}
      </Button>
      {/* 本轮家数：**必须让用户能改**。写死 4 家 + 不解释，用户会以为「只抓了 4 家、其余被漏掉」，
          而实际是「待抓取 28 家、每轮小批量轮转」。默认 4 家（约 2~6 分钟），想一次跑完选「全部」。
          ⚠️ 已指定标的时禁用 —— 勾了 7 家却只跑 4 家是最像 bug 的行为，宁可显式禁用并说明。 */}
      <label
        className="flex items-center gap-1 text-[11px] text-slate-500"
        title={
          picked
            ? `已指定 ${scrapeSymbols.length} 家标的，本轮家数不生效（指定即精确批次）。\n清空指定后此项恢复。`
            : '「AI 立即抓取」本轮最多抓几家。\n' +
              '单家 = 1 次多源新闻聚合 + 最多 2 次 LLM 调用；推理型模型每次先烧上千 token 思维链，' +
              '所以家数越多越慢（默认 4 家约 2~6 分钟）。\n' +
              '监控运行时调度器每轮另自动抓 3 家轮转，长期会把全部标的覆盖一遍。'
        }
      >
        本轮
        <Select
          value={String(scrapeLimit)}
          onChange={(e) => setScrapeLimit(Number(e.target.value))}
          className="!w-28"
          disabled={!!scrapeJob || picked}
        >
          {[4, 8, 12].map((n) => (
            <option key={n} value={n}>
              最多 {n} 家
            </option>
          ))}
          <option value={0}>{pending > 0 ? `全部 ${pending} 家` : '全部待抓取'}</option>
        </Select>
      </label>
      <Button
        variant="secondary"
        icon={<Satellite className="h-3.5 w-3.5" />}
        loading={busy === 'ai-scrape'}
        disabled={ov ? !ov.llm.configured : false}
        title={
          ov?.llm.configured
            ? `立即执行一轮：新闻抓取 → AI 提取关键节点 → 生成买入建议（无需开启监控）。当前选择：${
                picked
                  ? `指定标的 ${scrapeSymbols.join('、')}（${scrapeSymbols.length} 家）`
                  : scrapeLimit <= 0
                    ? `全部待抓取（${pending} 家）`
                    : `最多 ${scrapeLimit} 家`
              }`
            : '请先到「设置 → AI 分析」配置 base_url / api_key / model'
        }
        onClick={onAiScrape}
      >
        AI 立即抓取
      </Button>
      {monitorOn ? (
        <Button variant="danger" icon={<Square className="h-3.5 w-3.5" />} loading={busy === 'monitor'} onClick={onStop}>
          截止并归档
        </Button>
      ) : (
        <Button variant="success" icon={<Play className="h-3.5 w-3.5" />} loading={busy === 'monitor'} onClick={onStart}>
          一键开启监控
        </Button>
      )}
    </div>
  )
}
