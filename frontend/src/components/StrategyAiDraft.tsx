/**
 * StrategyAiDraft —— 「用一句话描述策略」→ AI 生成策略草稿
 * =====================================================
 * 策略实验室里「从想法到可配置参数」这一步原本完全靠用户自己想。
 * 这里接上 AI：用户描述想法，AI 从平台现有策略库里挑最接近的基底，
 * 给出进场/离场/参数区间/失效场景/验证计划，用户再照着去配置。
 *
 * 组件自包含（输入框 + 结果），页面只留一行编排 —— 因为
 * `Strategies.tsx`（908 行）已超硬上限，按铁律 9 不得再往里加逻辑。
 */
import { Sparkles } from 'lucide-react'
import { useState } from 'react'
import { Button, Card, Field } from './ui'
import AIAssist from './AIAssist'

const EXAMPLES = [
  '想在震荡市里做均值回归，标的是宽基 ETF',
  '跟随中期趋势，用波动率控制仓位，回撤要小',
  '日内开盘区间突破，只做美股大盘',
  '用配对交易做市场中性，两只相关性高的股票',
]

export default function StrategyAiDraft({ className }: { className?: string }) {
  const [desc, setDesc] = useState('')
  const [submitted, setSubmitted] = useState('')
  const [n, setN] = useState(0)

  const submit = () => {
    const d = desc.trim()
    if (!d) return
    setSubmitted(d)
    setN((x) => x + 1)
  }

  return (
    <div className={className}>
      <Card
        title={
          <span className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-violet-500" />
            用一句话描述你的策略
          </span>
        }
        subtitle="AI 会从平台现有 28 个策略里挑最接近的基底，并给出可配置的进出场与参数区间"
      >
        <div className="space-y-3">
          <Field
            label="策略想法"
            hint="描述越具体越好：市场状态（趋势/震荡）、标的类型、你希望控制的风险"
          >
            <textarea
              className="inp min-h-[80px] resize-y"
              value={desc}
              onChange={(e) => setDesc(e.target.value)}
              placeholder="例如：在震荡市里做均值回归，标的用宽基 ETF，单笔风险不超过 1%"
            />
          </Field>
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-[11px] text-slate-400">试试：</span>
            {EXAMPLES.map((x) => (
              <button
                key={x}
                type="button"
                onClick={() => setDesc(x)}
                className="rounded-md bg-slate-100 px-2 py-1 text-[11px] text-slate-600 transition-colors hover:bg-brand-100 hover:text-brand-700"
              >
                {x}
              </button>
            ))}
          </div>
          <Button variant="primary" onClick={submit} disabled={!desc.trim()} icon={<Sparkles className="h-3.5 w-3.5" />}>
            生成策略草稿
          </Button>

          {submitted && (
            <div className="border-t border-slate-100 pt-3">
              <AIAssist
                mode="inline"
                task="strategy_draft"
                title="策略草稿"
                label="生成草稿"
                runKey={`${submitted}#${n}`}
                payload={{ description: submitted }}
                emptyHint="点击上方「生成草稿」按钮，AI 会给出策略定位、建议基底、进场/离场条件、参数区间与验证计划。"
              />
            </div>
          )}
          <p className="text-[10.5px] leading-relaxed text-slate-400">
            草稿只是配置建议，不构成盈利承诺。生成后请到回测页用 5 年以上数据自行验证。
          </p>
        </div>
      </Card>
    </div>
  )
}
