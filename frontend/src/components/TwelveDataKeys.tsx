import { AlertTriangle, CheckCircle2, KeyRound, Plus, RefreshCw, Trash2, Zap } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { api } from '../lib/api'
import { Alert, Badge, Button, Card, Input, Progress, Spinner, Switch, useToast } from './ui'

/**
 * TwelveData 多 Key 轮询池管理卡片。
 *
 * 为什么单独一个组件（而不是写进 Settings.tsx）：
 *   `pages/Settings.tsx` 已 955 行，**超过铁律 9 的 900 行硬上限**（冻结文件）。
 *   冻结文件只允许加「一行组件编排」，业务逻辑必须放在自包含组件里。
 *
 * 背景：TwelveData 免费档实测 **8 credits/分钟、800/天**（`/api_usage` 自证），
 * 单账号喂不饱全量标的。多配几个账号后后端会**轮询**分摊，额度线性叠加 ——
 * 卡片上直接显示「合计额度」让用户看到收益。
 */

interface TDKey {
  id: string
  label: string
  masked: string
  enabled: boolean
  used_this_min: number
  per_min_limit: number
  used_today: number
  per_day_limit: number
  cooldown_sec: number
  last_used_sec: number | null
  last_error: string
  total_ok: number
  total_fail: number
  last_usage?: Record<string, any> | null
}

interface TDStatus {
  keys: TDKey[]
  count: number
  enabled: number
  available_now: number
  effective_per_min: number
  effective_per_day: number
  per_min_limit: number
  per_day_limit: number
  env_key_configured: boolean
  next_index: number
}

function ago(sec: number | null): string {
  if (sec == null) return '从未使用'
  if (sec < 60) return `${sec} 秒前`
  if (sec < 3600) return `${Math.floor(sec / 60)} 分钟前`
  return `${Math.floor(sec / 3600)} 小时前`
}

export default function TwelveDataKeys() {
  const toast = useToast()
  const [st, setSt] = useState<TDStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')
  const [newKey, setNewKey] = useState('')
  const [newLabel, setNewLabel] = useState('')
  const [adding, setAdding] = useState(false)
  const [busy, setBusy] = useState<string>('')   // 正在操作的 key id

  const load = useCallback(async () => {
    try {
      setSt(await api.get<TDStatus>('/market/twelvedata'))
      setErr('')
    } catch (e: any) {
      setErr(e?.message || '读取失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const add = async () => {
    const k = newKey.trim()
    if (!k) return
    setAdding(true)
    try {
      const r = await api.post<any>('/market/twelvedata/keys', { key: k, label: newLabel.trim() })
      setSt(r.status)
      setNewKey('')
      setNewLabel('')
      toast('success', `已添加 ${r.entry?.masked ?? '密钥'}`)
    } catch (e: any) {
      toast('error', e?.message || '添加失败')
    } finally {
      setAdding(false)
    }
  }

  const patch = async (id: string, body: any) => {
    setBusy(id)
    try {
      const r = await api.patch<any>(`/market/twelvedata/keys/${id}`, body)
      setSt(r.status)
    } catch (e: any) {
      toast('error', e?.message || '更新失败')
    } finally {
      setBusy('')
    }
  }

  const del = async (id: string, masked: string) => {
    setBusy(id)
    try {
      const r = await api.del<any>(`/market/twelvedata/keys/${id}`)
      setSt(r.status)
      toast('success', `已删除 ${masked}`)
    } catch (e: any) {
      toast('error', e?.message || '删除失败')
    } finally {
      setBusy('')
    }
  }

  const test = async (id: string) => {
    setBusy(id)
    try {
      const r = await api.post<any>(`/market/twelvedata/keys/${id}/test`, undefined, 30_000)
      setSt(r.status)
      if (r.ok) {
        const u = r.usage || {}
        toast('success', `密钥有效：本分钟 ${u.current_usage ?? '?'}/${u.plan_limit ?? '?'}，当日 ${u.daily_usage ?? '?'}/${u.plan_daily_limit ?? '?'}`)
      } else {
        toast('error', `密钥不可用：${r.error || '未知原因'}`)
      }
    } catch (e: any) {
      toast('error', e?.message || '实测失败')
    } finally {
      setBusy('')
    }
  }

  const resetCooldown = async () => {
    try {
      const r = await api.post<any>('/market/twelvedata/reset-cooldown')
      setSt(r.status)
      toast('success', r.cleared > 0 ? `已清除 ${r.cleared} 个冷却` : '当前没有处于冷却的密钥')
    } catch (e: any) {
      toast('error', e?.message || '操作失败')
    }
  }

  if (loading) {
    return (
      <Card title="TwelveData 多 Key 轮询">
        <div className="py-6 text-center"><Spinner /></div>
      </Card>
    )
  }

  const keys = st?.keys ?? []

  return (
    <Card
      title="TwelveData 多 Key 轮询"
      actions={
        <div className="flex items-center gap-2">
          <Button className="!px-2 !py-1 text-[11px]" onClick={resetCooldown}>
            清除冷却
          </Button>
          <Button className="!px-2 !py-1 text-[11px]" icon={<RefreshCw className="h-3 w-3" />} onClick={load}>
            刷新
          </Button>
        </div>
      }
    >
      {err && <Alert tone="danger" title="读取失败">{err}</Alert>}

      <p className="text-xs leading-5 text-slate-500">
        TwelveData 免费档实测为 <strong className="font-medium">8 次/分钟、800 次/天</strong>
        （单账号）。注册多个账号后在此逐个添加，后端会<strong className="font-medium">按轮询分摊</strong>
        ，可用额度随账号数线性叠加。密钥以密文落库，界面只显示掩码。
      </p>

      {st && (
        <div className="mt-3 grid grid-cols-2 gap-2">
          <div className="rounded-lg border border-slate-200 px-2.5 py-2">
            <div className="text-[10px] uppercase tracking-wide text-slate-400">密钥</div>
            <div className="num text-sm font-semibold text-slate-700">
              {st.enabled} 启用 <span className="text-slate-400">/ {st.count}</span>
            </div>
          </div>
          <div className="rounded-lg border border-slate-200 px-2.5 py-2">
            <div className="text-[10px] uppercase tracking-wide text-slate-400">当前可用</div>
            <div className={`num text-sm font-semibold ${st.available_now > 0 ? 'text-emerald-600' : 'text-amber-600'}`}>
              {st.available_now}
            </div>
          </div>
          <div className="rounded-lg border border-brand-100 bg-brand-50/50 px-2.5 py-2">
            <div className="text-[10px] uppercase tracking-wide text-brand-500">合计额度 / 分钟</div>
            <div className="num text-sm font-semibold text-brand-700">{st.effective_per_min}</div>
          </div>
          <div className="rounded-lg border border-brand-100 bg-brand-50/50 px-2.5 py-2">
            <div className="text-[10px] uppercase tracking-wide text-brand-500">合计额度 / 天</div>
            <div className="num text-sm font-semibold text-brand-700">{st.effective_per_day}</div>
          </div>
        </div>
      )}

      {/* ---- 添加 ----
          卡片位于「数据与缓存」三列网格的第 3 列（窄），所以纵向排布；
          两个输入框并排会在 ~290px 宽度下换行错位。 */}
      <div className="mt-4 rounded-lg border border-dashed border-slate-300 bg-slate-50/60 p-3">
        <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-slate-600">
          <Plus className="h-3.5 w-3.5" />
          添加密钥
        </div>
        <div className="space-y-2">
          <Input
            value={newKey}
            onChange={(e) => setNewKey(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') add()
            }}
            placeholder="TwelveData API Key（32 位）"
            className="!w-full py-1.5 text-xs"
          />
          <div className="flex items-center gap-2">
            <Input
              value={newLabel}
              onChange={(e) => setNewLabel(e.target.value)}
              placeholder="备注（如：账号A）"
              className="min-w-0 flex-1 py-1.5 text-xs"
            />
            <Button
              onClick={add}
              disabled={adding || !newKey.trim()}
              icon={adding ? <Spinner /> : <KeyRound className="h-3.5 w-3.5" />}
            >
              添加
            </Button>
          </div>
        </div>
        {st?.env_key_configured && (
          <p className="mt-2 text-[10.5px] leading-4 text-slate-400">
            .env 里的 <code className="rounded bg-slate-100 px-1">TWELVEDATA_API_KEY</code> 仅用于首次播种；
            之后以本列表为准（在这里删除后不会被 .env 重新加回）。
          </p>
        )}
      </div>

      {/* ---- 列表 ---- */}
      <div className="mt-4 space-y-2">
        {keys.length === 0 && (
          <div className="rounded-lg border border-dashed border-slate-200 px-3 py-6 text-center text-xs text-slate-400">
            还没有配置密钥 —— 未配置时行情降级链会跳过 TwelveData。
          </div>
        )}
        {keys.map((k, i) => {
          const cooling = k.cooldown_sec > 0
          return (
            <div key={k.id} className="rounded-lg border border-slate-200 p-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-slate-100 text-[10px] font-semibold text-slate-600">
                  {i + 1}
                </span>
                <span className="text-sm font-medium text-slate-800">{k.label}</span>
                <code className="rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-500">{k.masked}</code>
                {st && st.next_index === i && st.count > 1 && (
                  <Badge tone="brand">下一个</Badge>
                )}
                {cooling && <Badge tone="amber">冷却 {k.cooldown_sec}s</Badge>}
                {!k.enabled && <Badge tone="slate">已停用</Badge>}
                {k.enabled && !cooling && <Badge tone="green">可用</Badge>}
                <div className="ml-auto flex items-center gap-2">
                  <Button
                    className="!px-2 !py-1 text-[11px]"
                    icon={<Zap className="h-3 w-3" />}
                    disabled={busy === k.id}
                    onClick={() => test(k.id)}
                  >
                    实测
                  </Button>
                  <Button
                    className="!px-2 !py-1 text-[11px]"
                    icon={<Trash2 className="h-3 w-3" />}
                    disabled={busy === k.id}
                    onClick={() => del(k.id, k.masked)}
                  >
                    删除
                  </Button>
                </div>
              </div>

              <div className="mt-2.5 grid gap-2 sm:grid-cols-2">
                <Progress
                  value={k.used_this_min}
                  max={k.per_min_limit}
                  tone={k.used_this_min >= k.per_min_limit ? 'amber' : 'brand'}
                  label={<><span>本分钟</span><span className="num">{k.used_this_min}/{k.per_min_limit}</span></>}
                />
                <Progress
                  value={k.used_today}
                  max={k.per_day_limit}
                  tone={k.used_today >= k.per_day_limit ? 'amber' : 'brand'}
                  label={<><span>当日</span><span className="num">{k.used_today}/{k.per_day_limit}</span></>}
                />
              </div>

              <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[10.5px] text-slate-400">
                <span>最近使用：{ago(k.last_used_sec)}</span>
                <span>成功 {k.total_ok} · 失败 {k.total_fail}</span>
                {k.last_usage?.plan_category && (
                  <span>套餐：{String(k.last_usage.plan_category)}</span>
                )}
                {k.last_error && (
                  <span className="inline-flex items-center gap-1 text-amber-600">
                    <AlertTriangle className="h-3 w-3" />
                    {k.last_error}
                  </span>
                )}
              </div>

              <div className="mt-2 border-t border-slate-100 pt-2">
                <Switch
                  checked={k.enabled}
                  disabled={busy === k.id}
                  onChange={(v) => patch(k.id, { enabled: v })}
                  label={<span className="text-[11px] text-slate-500">参与轮询</span>}
                />
              </div>
            </div>
          )
        })}
      </div>

      {keys.length > 1 && (
        <div className="mt-3 flex items-start gap-1.5 rounded-lg border border-emerald-100 bg-emerald-50/60 px-2.5 py-2 text-[11px] text-emerald-700">
          <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>
            已配置 {keys.filter((k) => k.enabled).length} 个账号，额度按轮询叠加到{' '}
            <strong className="font-medium">{st?.effective_per_min}/分钟</strong>。
            命中限流时该账号会自动冷却，请求切换到下一个账号，不会整体失败。
          </span>
        </div>
      )}
    </Card>
  )
}
