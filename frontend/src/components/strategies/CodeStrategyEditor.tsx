/**
 * CodeStrategyEditor —— 「Python 代码」标签页
 * ============================================
 * 从 `pages/Strategies.tsx` 抽出（铁律 9：页面文件超硬上限，新功能必须先拆）。
 * 纯展示组件：`code` / `codeName` / `codeCheck` / `dsl` 与三个回调全部由页面注入，
 * 页面仍持有全部状态与请求逻辑，行为与拆分前完全一致。
 */
import { AlertTriangle, Check, Save } from 'lucide-react'
import { Alert, Button, Card, Field, Input } from '../ui'
import StrategyCodeReview from './StrategyCodeReview'

export default function CodeStrategyEditor({
  code,
  onCodeChange,
  codeName,
  onNameChange,
  codeCheck,
  dsl,
  onCheck,
  onSave,
}: {
  code: string
  onCodeChange: (v: string) => void
  codeName: string
  onNameChange: (v: string) => void
  codeCheck: { ok: boolean; msg: string } | null
  dsl: any
  onCheck: () => void
  onSave: () => void
}) {
  return (
    <div className="grid gap-5 xl:grid-cols-3">
      <Card className="xl:col-span-2" title="策略代码" subtitle="必须定义 generate(ctx) 并返回目标权重 DataFrame">
        <textarea
          value={code}
          onChange={(e) => onCodeChange(e.target.value)}
          spellCheck={false}
          className="num h-[460px] w-full resize-y rounded-lg border border-slate-300 bg-slate-950 p-4 text-xs leading-relaxed text-slate-100 outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-500/20"
        />
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button onClick={onCheck} icon={<Check className="h-3.5 w-3.5" />}>
            安全校验
          </Button>
          {/* AI 代码审查：沙箱只查安全性，未来函数靠这里兜住 */}
          <StrategyCodeReview code={code} />
          <Button variant="ghost" onClick={() => onCodeChange(dsl?.code_template || '')}>
            恢复模板
          </Button>
          <Button
            variant="primary"
            onClick={onSave}
            icon={<Save className="h-3.5 w-3.5" />}
            className="ml-auto"
          >
            保存策略
          </Button>
        </div>
        {codeCheck && (
          <Alert tone={codeCheck.ok ? 'success' : 'danger'} className="mt-3" title={codeCheck.ok ? '通过校验' : '被拦截'}>
            {codeCheck.msg}
          </Alert>
        )}
      </Card>

      <div className="space-y-5">
        <Card title="策略名称">
          <Field label="保存为" hint="保存后可在「我的策略」中回测">
            <Input value={codeName} onChange={(e) => onNameChange(e.target.value)} placeholder="我的动量策略" />
          </Field>
        </Card>

        <Card title="沙箱规则">
          <Alert tone="warn" title="代码策略属高风险功能">
            服务端会先做 AST 白名单校验，阻止导入系统模块、访问私有属性、调用 eval/exec/open 等。
            即便如此，仍建议仅在本地单用户环境使用。
          </Alert>
          <ul className="mt-3 space-y-2 text-xs text-slate-600">
            <li className="flex gap-2">
              <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-500" />
              允许导入：{dsl?.code_limits?.allowed_imports?.join('、') || 'pandas、numpy、math、statistics'}
            </li>
            <li className="flex gap-2">
              <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-500" />
              可使用 ctx.closes（收盘价矩阵）、ctx.data[代码]（完整 OHLCV）
            </li>
            <li className="flex gap-2">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-500" />
              禁止：import os/sys、eval、exec、open、__import__、__xxx__ 属性、while True
            </li>
            <li className="flex gap-2">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-500" />
              代码长度上限 {dsl?.code_limits?.max_chars || 8000} 字符
            </li>
            <li className="flex gap-2">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-500" />
              沙箱<span className="font-medium">不检查时间语义</span>
              ：shift(-1)、bfill 这类未来函数请用「AI 审查代码」排查
            </li>
          </ul>
        </Card>

        <Card title="可用数据">
          <pre className="overflow-auto rounded-lg bg-slate-50 p-3 text-[11px] leading-relaxed text-slate-600">
{`ctx.closes      # DataFrame(日期 × 标的) 收盘价
ctx.high        # 最高价
ctx.low         # 最低价
ctx.volume      # 成交量
ctx.symbols     # 标的列表
ctx.data['SPY'] # 单标的 OHLCV DataFrame

# 返回示例（等权做多动量最强的 2 只）：
import pandas as pd
def generate(ctx):
    mom = ctx.closes / ctx.closes.shift(60) - 1
    w = pd.DataFrame(0.0, index=ctx.closes.index, columns=ctx.closes.columns)
    w[mom > 0] = 0.5
    return w`}
          </pre>
        </Card>
      </div>
    </div>
  )
}
