import {
  Check,
  Code2,
  Filter,
  FlaskConical,
  Info,
  Layers,
  Play,
  Plus,
  Save,
  Sliders,
  Sparkles,
  Trash2,
  Wand2,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Alert,
  Badge,
  Button,
  Card,
  Empty,
  Field,
  Input,
  Loading,
  Modal,
  Select,
  Tabs,
  useToast,
} from '../components/ui'
import { api } from '../lib/api'
import { symbolsToInput } from '../lib/backtestPrefs'
import type { StrategyConfig, StrategyInfo } from '../lib/types'
import StrategyAiDraft from '../components/StrategyAiDraft'
import ParamForm from '../components/strategies/ParamForm'
import CodeStrategyEditor from '../components/strategies/CodeStrategyEditor'
import { CondRow, condToSpec, newCond, type Cond } from '../components/strategies/ruleEditor'

const CAT_TONE: Record<string, 'brand' | 'green' | 'amber' | 'violet' | 'blue'> = {
  趋势动量: 'brand',
  均值回归: 'green',
  进阶前沿: 'violet',
  日内微观: 'amber',
}

/* ================================================================
 * 主页面
 * ================================================================ */
export default function Strategies() {
  const toast = useToast()
  const nav = useNavigate()
  const [tab, setTab] = useState('builtin')

  const [builtin, setBuiltin] = useState<StrategyInfo[]>([])
  const [categories, setCategories] = useState<string[]>([])
  const [filter, setFilter] = useState('')
  const [keyword, setKeyword] = useState('')
  const [loading, setLoading] = useState(true)

  const [detail, setDetail] = useState<StrategyInfo | null>(null)
  const [paramValues, setParamValues] = useState<Record<string, any>>({})

  const [customs, setCustoms] = useState<StrategyConfig[]>([])

  // 规则编辑器
  const [ruleName, setRuleName] = useState('')
  const [direction, setDirection] = useState<'long' | 'short' | 'both'>('long')
  const [entryMode, setEntryMode] = useState<'all' | 'any'>('all')
  const [exitMode, setExitMode] = useState<'any' | 'all'>('any')
  const [entryConds, setEntryConds] = useState<Cond[]>([newCond()])
  const [exitConds, setExitConds] = useState<Cond[]>([])
  const [ruleSymbols, setRuleSymbols] = useState('SPY')
  const [entrySize, setEntrySize] = useState(1)
  const [maxHold, setMaxHold] = useState(0)
  const [ruleCheck, setRuleCheck] = useState<{ ok: boolean; msg: string } | null>(null)

  // 代码策略
  const [codeName, setCodeName] = useState('')
  const [code, setCode] = useState('')
  const [codeCheck, setCodeCheck] = useState<{ ok: boolean; msg: string } | null>(null)
  const [dsl, setDsl] = useState<any>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [b, c, d] = await Promise.all([
        api.get<{ builtin: StrategyInfo[]; categories: string[] }>('/strategies'),
        api.get<{ items: StrategyConfig[] }>('/strategies/custom'),
        api.get<any>('/strategies/dsl'),
      ])
      setBuiltin(b.builtin)
      setCategories(b.categories)
      setCustoms(c.items)
      setDsl(d)
      setCode((prev) => prev || d.code_template)
    } catch (e: any) {
      toast('error', e?.message || '加载策略库失败')
    } finally {
      setLoading(false)
    }
  }, [toast])

  useEffect(() => {
    load()
  }, [load])

  const filtered = useMemo(
    () =>
      builtin.filter(
        (s) =>
          (!filter || s.category === filter) &&
          (!keyword ||
            s.name.toLowerCase().includes(keyword.toLowerCase()) ||
            s.key.toLowerCase().includes(keyword.toLowerCase()) ||
            s.description.includes(keyword) ||
            s.tags.some((t) => t.includes(keyword))),
      ),
    [builtin, filter, keyword],
  )

  const openDetail = (s: StrategyInfo) => {
    setDetail(s)
    setParamValues(Object.fromEntries(s.params.map((p) => [p.key, p.default])))
  }

  const goBacktest = () => {
    if (!detail) return
    nav('/backtest', { state: { strategy_key: detail.key, params: paramValues, name: detail.name } })
  }

  /* ---------- 规则策略保存 ---------- */
  const buildRule = () => ({
    direction,
    entry: { [entryMode]: entryConds.map(condToSpec) },
    exit: exitConds.length ? { [exitMode]: exitConds.map(condToSpec) } : {},
    entry_size: entrySize,
    max_hold_bars: maxHold,
  })

  const checkRule = async () => {
    try {
      const r = await api.post<{ ok: boolean; error?: string }>('/strategies/validate-rule', buildRule())
      setRuleCheck({ ok: r.ok, msg: r.ok ? '规则校验通过，可用于回测与实盘引擎' : r.error || '校验失败' })
    } catch (e: any) {
      setRuleCheck({ ok: false, msg: e?.message || '校验失败' })
    }
  }

  const saveRule = async (thenBacktest = false) => {
    if (!ruleName.trim()) {
      toast('warning', '请先给策略起个名字')
      return
    }
    try {
      const r = await api.post<StrategyConfig>('/strategies/custom', {
        name: ruleName,
        kind: 'rule',
        rule: buildRule(),
        symbols: ruleSymbols.split(',').map((s) => s.trim().toUpperCase()).filter(Boolean),
        notes: '可视化规则策略',
        tags: ['自定义'],
      })
      toast('success', `策略「${r.name}」已保存`)
      await load()
      if (thenBacktest) {
        nav('/backtest', { state: { strategy_key: 'custom_rule', rule: buildRule(), name: r.name, symbols: ruleSymbols.split(',').map((s) => s.trim().toUpperCase()) } })
      } else {
        setTab('mine')
      }
    } catch (e: any) {
      toast('error', e?.message || '保存失败')
    }
  }

  /* ---------- 代码策略 ---------- */
  const checkCode = async () => {
    try {
      const r = await api.post<{ ok: boolean; error?: string; message?: string }>('/strategies/validate-code', { code })
      setCodeCheck({ ok: r.ok, msg: r.ok ? r.message || '通过校验' : r.error || '校验失败' })
    } catch (e: any) {
      setCodeCheck({ ok: false, msg: e?.message || '校验失败' })
    }
  }

  const saveCode = async () => {
    if (!codeName.trim()) {
      toast('warning', '请先给策略起个名字')
      return
    }
    try {
      await api.post('/strategies/custom', { name: codeName, kind: 'code', code, symbols: ['SPY'], tags: ['自定义', 'Python'] })
      toast('success', '代码策略已保存')
      await load()
      setTab('mine')
    } catch (e: any) {
      toast('error', e?.message || '保存失败')
    }
  }

  const deleteCustom = async (c: StrategyConfig) => {
    if (!confirm(`确认删除策略「${c.name}」？`)) return
    try {
      await api.del(`/strategies/custom/${c.id}`)
      toast('success', '已删除')
      load()
    } catch (e: any) {
      toast('error', e?.message || '删除失败')
    }
  }

  const runCustomBacktest = (c: StrategyConfig) => {
    if (c.kind === 'code') {
      nav('/backtest', { state: { strategy_key: 'custom_code', code: c.code, name: c.name, symbols: c.symbols } })
    } else if (c.kind === 'rule') {
      nav('/backtest', { state: { strategy_key: 'custom_rule', rule: c.rule, name: c.name, symbols: c.symbols } })
    } else {
      nav('/backtest', { state: { strategy_key: c.strategy_key, params: c.params, name: c.name, symbols: c.symbols } })
    }
  }

  if (loading && !builtin.length) return <Loading label="正在加载策略库…" />

  return (
    <div className="space-y-5">
      <Card>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Tabs
            value={tab}
            onChange={setTab}
            tabs={[
              { key: 'builtin', label: '内置策略库', badge: builtin.length },
              { key: 'mine', label: '我的策略', badge: customs.length },
              { key: 'rule', label: '可视化规则' },
              { key: 'code', label: 'Python 代码' },
            ]}
          />
          <div className="flex items-center gap-2 text-xs text-slate-500">
            <Sparkles className="h-3.5 w-3.5 text-brand-500" />
            共 {builtin.length} 个内置策略，覆盖趋势 / 均值回归 / 前沿 / 日内四大族
          </div>
        </div>
      </Card>

      {/* ================= 内置策略库 ================= */}
      {tab === 'builtin' && (
        <>
          <Card>
            <div className="flex flex-wrap items-center gap-3">
              <Input
                className="max-w-xs"
                placeholder="搜索策略名称、标签或说明…"
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
              />
              <div className="flex flex-wrap gap-1.5">
                <button
                  onClick={() => setFilter('')}
                  className={`rounded-md px-2.5 py-1.5 text-xs font-medium transition-colors ${
                    !filter ? 'bg-brand-600 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                  }`}
                >
                  全部
                </button>
                {categories.map((c) => (
                  <button
                    key={c}
                    onClick={() => setFilter(c)}
                    className={`rounded-md px-2.5 py-1.5 text-xs font-medium transition-colors ${
                      filter === c ? 'bg-brand-600 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                    }`}
                  >
                    {c}
                  </button>
                ))}
              </div>
              <span className="ml-auto text-xs text-slate-400">
                <Filter className="mr-1 inline h-3 w-3" />
                {filtered.length} 个结果
              </span>
            </div>
          </Card>

          {/* AI 策略草稿：一句话描述想法 → 基底 + 进出场 + 参数区间 + 验证计划 */}
          <StrategyAiDraft />

          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {filtered.map((s) => (
              <Card key={s.key} className="flex flex-col transition-shadow hover:shadow-pop">
                <div className="flex-1">
                  <div className="flex items-start justify-between gap-2">
                    <h3 className="text-sm font-semibold text-slate-800">{s.name}</h3>
                    <Badge tone={CAT_TONE[s.category] || 'slate'}>{s.category}</Badge>
                  </div>
                  <p className="mt-2 line-clamp-4 text-xs leading-relaxed text-slate-500">{s.description}</p>
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {s.tags.map((t) => (
                      <span key={t} className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-500">
                        {t}
                      </span>
                    ))}
                  </div>
                </div>
                <div className="mt-4 flex items-center justify-between border-t border-slate-100 pt-3">
                  <span className="text-[11px] text-slate-400">
                    {s.params.length} 个参数 · 最少 {s.min_bars} 根 bar
                  </span>
                  <div className="flex gap-2">
                    <Button size="sm" icon={<Sliders className="h-3.5 w-3.5" />} onClick={() => openDetail(s)}>
                      参数
                    </Button>
                    <Button
                      size="sm"
                      variant="primary"
                      icon={<Play className="h-3.5 w-3.5" />}
                      onClick={() => {
                        const params = Object.fromEntries(s.params.map((p) => [p.key, p.default]))
                        nav('/backtest', { state: { strategy_key: s.key, params, name: s.name } })
                      }}
                    >
                      回测
                    </Button>
                  </div>
                </div>
              </Card>
            ))}
          </div>
          {!filtered.length && <Empty icon={<FlaskConical className="h-8 w-8" />} title="没有匹配的策略" desc="试试换个关键词或清空筛选" />}
        </>
      )}

      {/* ================= 我的策略 ================= */}
      {tab === 'mine' && (
        <>
          {customs.length === 0 ? (
            <Card>
              <Empty
                icon={<Layers className="h-8 w-8" />}
                title="还没有自定义策略"
                desc="可以切换上方「可视化规则」用指标条件拼一个策略，或用「Python 代码」写一个（受 AST 白名单沙箱保护）"
                action={
                  <div className="flex gap-2">
                    <Button variant="primary" onClick={() => setTab('rule')} icon={<Wand2 className="h-3.5 w-3.5" />}>
                      可视化规则
                    </Button>
                    <Button onClick={() => setTab('code')} icon={<Code2 className="h-3.5 w-3.5" />}>
                      Python 代码
                    </Button>
                  </div>
                }
              />
            </Card>
          ) : (
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {customs.map((c) => (
                <Card key={c.id}>
                  <div className="flex items-start justify-between gap-2">
                    <h3 className="text-sm font-semibold text-slate-800">{c.name}</h3>
                    <Badge tone={c.kind === 'rule' ? 'green' : c.kind === 'code' ? 'violet' : 'brand'}>
                      {c.kind === 'rule' ? '规则策略' : c.kind === 'code' ? '代码策略' : '参数化内置'}
                    </Badge>
                  </div>
                  <p className="mt-2 text-xs text-slate-500">
                    标的：{symbolsToInput(c.symbols) ?? '未指定'} · 更新于 {c.updated_at.slice(0, 10)}
                  </p>
                  {c.notes && <p className="mt-1 text-[11px] text-slate-400">{c.notes}</p>}
                  <div className="mt-3 flex gap-2">
                    <Button size="sm" variant="primary" icon={<Play className="h-3.5 w-3.5" />} onClick={() => runCustomBacktest(c)}>
                      回测
                    </Button>
                    <Button
                      size="sm"
                      icon={<Trash2 className="h-3.5 w-3.5" />}
                      onClick={() => deleteCustom(c)}
                    >
                      删除
                    </Button>
                  </div>
                </Card>
              ))}
            </div>
          )}
        </>
      )}

      {/* ================= 可视化规则编辑器 ================= */}
      {tab === 'rule' && (
        <div className="grid gap-5 xl:grid-cols-3">
          <Card
            className="xl:col-span-2"
            title="进场条件"
            subtitle={`所有条件需${entryMode === 'all' ? '同时满足' : '任意满足其一'}`}
            actions={
              <Tabs
                value={entryMode}
                onChange={(k) => setEntryMode(k as any)}
                tabs={[
                  { key: 'all', label: 'AND（全部）' },
                  { key: 'any', label: 'OR（任一）' },
                ]}
              />
            }
          >
            <div className="space-y-2">
              {entryConds.map((c, i) => (
                <CondRow
                  key={c.id}
                  cond={c}
                  removable={entryConds.length > 1}
                  onChange={(nc) => setEntryConds((s) => s.map((x, j) => (j === i ? nc : x)))}
                  onRemove={() => setEntryConds((s) => s.filter((_, j) => j !== i))}
                />
              ))}
              <Button size="sm" onClick={() => setEntryConds((s) => [...s, newCond()])} icon={<Plus className="h-3.5 w-3.5" />}>
                添加进场条件
              </Button>
            </div>
          </Card>

          <Card title="策略设置">
            <div className="space-y-3">
              <Field label="策略名称">
                <Input value={ruleName} onChange={(e) => setRuleName(e.target.value)} placeholder="例如：RSI 超卖 + 长期趋势向上" />
              </Field>
              <Field label="交易标的（逗号分隔）">
                <Input value={ruleSymbols} onChange={(e) => setRuleSymbols(e.target.value)} placeholder="SPY,QQQ" />
              </Field>
              <Field label="方向">
                <Select value={direction} onChange={(e) => setDirection(e.target.value as any)}>
                  <option value="long">只做多</option>
                  <option value="short">只做空</option>
                  <option value="both">双向（含做空）</option>
                </Select>
              </Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="目标仓位">
                  <Input type="number" step="0.05" min="0.05" max="1" value={entrySize} onChange={(e) => setEntrySize(parseFloat(e.target.value))} />
                </Field>
                <Field label="最大持有 bar" hint="0 = 不限">
                  <Input type="number" min="0" value={maxHold} onChange={(e) => setMaxHold(parseInt(e.target.value, 10))} />
                </Field>
              </div>

              {ruleCheck && (
                <Alert tone={ruleCheck.ok ? 'success' : 'danger'} title={ruleCheck.ok ? '校验通过' : '校验未通过'}>
                  {ruleCheck.msg}
                </Alert>
              )}

              <div className="flex gap-2">
                <Button onClick={checkRule} icon={<Check className="h-3.5 w-3.5" />}>
                  校验规则
                </Button>
                <Button variant="primary" onClick={() => saveRule(false)} icon={<Save className="h-3.5 w-3.5" />}>
                  保存策略
                </Button>
              </div>
              <Button className="w-full" variant="success" onClick={() => saveRule(true)} icon={<Play className="h-3.5 w-3.5" />}>
                保存并立即回测
              </Button>
            </div>
          </Card>

          <Card className="xl:col-span-2" title="离场条件" subtitle="留空则仅靠止损离场（推荐至少配一个止损）"
            actions={
              <Tabs
                value={exitMode}
                onChange={(k) => setExitMode(k as any)}
                tabs={[
                  { key: 'any', label: 'OR（任一）' },
                  { key: 'all', label: 'AND（全部）' },
                ]}
              />
            }
          >
            <div className="space-y-2">
              {exitConds.map((c, i) => (
                <CondRow
                  key={c.id}
                  cond={c}
                  removable
                  onChange={(nc) => setExitConds((s) => s.map((x, j) => (j === i ? nc : x)))}
                  onRemove={() => setExitConds((s) => s.filter((_, j) => j !== i))}
                />
              ))}
              <Button size="sm" onClick={() => setExitConds((s) => [...s, newCond()])} icon={<Plus className="h-3.5 w-3.5" />}>
                添加离场条件
              </Button>
            </div>
          </Card>

          <Card title="生成的规则 JSON" subtitle="可直接复制或修改">
            <pre className="max-h-72 overflow-auto rounded-lg bg-slate-900 p-3 text-[11px] leading-relaxed text-slate-100">
              {JSON.stringify(buildRule(), null, 2)}
            </pre>
            <Alert tone="info" className="mt-3">
              规则策略由后端按白名单指标计算，<span className="font-medium">不执行任何用户代码</span>，
              因此比 Python 代码策略安全得多，推荐优先使用。
            </Alert>
          </Card>
        </div>
      )}

      {/* ================= Python 代码编辑器 ================= */}
      {tab === 'code' && (
        <CodeStrategyEditor
          code={code}
          onCodeChange={setCode}
          codeName={codeName}
          onNameChange={setCodeName}
          codeCheck={codeCheck}
          dsl={dsl}
          onCheck={checkCode}
          onSave={saveCode}
        />
      )}

      {/* ================= 参数弹窗 ================= */}
      <Modal
        open={!!detail}
        onClose={() => setDetail(null)}
        title={detail ? `${detail.name} · 参数设置` : ''}
        width="max-w-2xl"
        footer={
          <>
            <Button onClick={() => setDetail(null)}>关闭</Button>
            <Button variant="primary" onClick={goBacktest} icon={<Play className="h-3.5 w-3.5" />}>
              用此参数回测
            </Button>
          </>
        }
      >
        {detail && (
          <div className="space-y-4">
            <Alert tone="info">
              <span className="font-medium">{detail.category}</span> · {detail.description}
            </Alert>
            <ParamForm
              specs={detail.params}
              values={paramValues}
              onChange={(k, v) => setParamValues((s) => ({ ...s, [k]: v }))}
            />
            <div className="flex items-center gap-2 text-xs text-slate-500">
              <Info className="h-3.5 w-3.5" />
              参数会立即生效于回测；实时引擎使用风控中心里配置的止损与仓位规则。
            </div>
          </div>
        )}
      </Modal>
    </div>
  )
}
