import { KeyRound, Lock, Radar, ShieldCheck, User } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, Input, useToast } from '../components/ui'
import { useAuth } from '../store/auth'

export default function Login({ mode }: { mode: 'setup' | 'login' }) {
  const { login, setup } = useAuth()
  const nav = useNavigate()
  const toast = useToast()
  const isSetup = mode === 'setup'

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setErr('')
    if (isSetup && password !== confirm) {
      setErr('两次输入的口令不一致')
      return
    }
    setLoading(true)
    try {
      if (isSetup) {
        await setup(username, password)
        toast('success', '初始化完成，欢迎使用 QuantDesk')
      } else {
        await login(username, password)
        toast('success', '登录成功')
      }
      nav('/dashboard', { replace: true })
    } catch (e: any) {
      setErr(e?.message || '操作失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-slate-50 via-brand-50/40 to-slate-100 p-4">
      <div className="w-full max-w-md">
        <div className="mb-6 text-center">
          <div className="mx-auto mb-3 flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-brand-500 to-brand-700 text-white shadow-lg shadow-brand-500/25">
            <Radar className="h-7 w-7" />
          </div>
          <h1 className="text-xl font-semibold text-slate-900">QuantDesk</h1>
          <p className="mt-1 text-sm text-slate-500">面向 IBKR 的 AI 量化交易平台</p>
        </div>

        <div className="card p-6">
          <h2 className="text-sm font-semibold text-slate-800">
            {isSetup ? '首次启动 · 创建管理员账户' : '登录'}
          </h2>
          <p className="mt-1 text-xs text-slate-500">
            {isSetup
              ? '该账户用于保护策略、风控配置与券商凭据。口令以 bcrypt 加盐哈希存储，服务无法逆向还原。'
              : '请输入你的账户口令。连续失败将触发临时锁定。'}
          </p>

          <form onSubmit={submit} className="mt-5 space-y-4">
            <div>
              <label className="lbl">用户名</label>
              <div className="relative">
                <User className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <Input
                  className="pl-9"
                  value={username}
                  autoComplete="username"
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="trader"
                  required
                  minLength={3}
                />
              </div>
            </div>

            <div>
              <label className="lbl">口令</label>
              <div className="relative">
                <Lock className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <Input
                  className="pl-9"
                  type="password"
                  value={password}
                  autoComplete={isSetup ? 'new-password' : 'current-password'}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder={isSetup ? '至少 10 位，含大小写/数字/符号中三类' : '••••••••••'}
                  required
                  minLength={isSetup ? 10 : 1}
                />
              </div>
            </div>

            {isSetup && (
              <div>
                <label className="lbl">确认口令</label>
                <div className="relative">
                  <KeyRound className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                  <Input
                    className="pl-9"
                    type="password"
                    value={confirm}
                    autoComplete="new-password"
                    onChange={(e) => setConfirm(e.target.value)}
                    required
                  />
                </div>
              </div>
            )}

            {err && (
              <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">{err}</div>
            )}

            <Button type="submit" variant="primary" size="lg" className="w-full" loading={loading}>
              {isSetup ? '创建并进入' : '登录'}
            </Button>
          </form>
        </div>

        <div className="mt-5 flex items-start gap-2 rounded-lg border border-slate-200 bg-white/70 px-3.5 py-3 text-xs text-slate-500">
          <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-emerald-500" />
          <div>
            <p className="font-medium text-slate-600">安全默认</p>
            <p className="mt-0.5">
              服务仅监听 127.0.0.1；实盘交易需「环境变量 + 运行时解锁 + 逐笔护栏」三重确认，默认
              <span className="font-medium text-slate-700">完全无法下实盘单</span>。
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
