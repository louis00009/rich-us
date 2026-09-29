/**
 * StrategyCodeReview —— AI 策略代码审查
 * =======================================
 * 存在的理由：代码策略的 AST 沙箱**只查安全性，不查时间语义** ——
 * `ctx.closes.shift(-1)` 能顺利通过校验，却会跑出一条完全虚假的漂亮曲线。
 * 这个组件把「未来函数 / 数据对齐 / 除零 NaN / 权重越界」摆到台面上。
 *
 * 自包含：只接收当前编辑器里的代码，不依赖页面的任何状态。
 */
import AIAssist from '../AIAssist'

export default function StrategyCodeReview({
  code,
  className,
}: {
  code: string
  className?: string
}) {
  const trimmed = code.trim()
  return (
    <AIAssist
      className={className}
      mode="modal"
      task="strategy_code_review"
      title="AI 策略代码审查"
      desc="逐条检查未来函数、数据对齐、除零 / NaN、权重越界，并给出修改方向"
      label="AI 审查代码"
      payload={{ code }}
      runKey={`${trimmed.length}:${trimmed.slice(0, 64)}`}
      disabled={!trimmed}
      disabledHint="请先填写策略代码。"
      emptyHint="AI 会重点排查未来函数（沙箱不检查时间语义），以及工程健壮性问题。"
    />
  )
}
