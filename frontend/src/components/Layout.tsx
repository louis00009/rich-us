import {
  Activity,
  BarChart3,
  Bot,
  CandlestickChart,
  Cog,
  FlaskConical,
  LayoutDashboard,
  LogOut,
  Menu,
  BotMessageSquare,
  Radar,
  Satellite,
  Scaling,
  ShieldAlert,
  Trophy,
  Wallet,
  X,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import AlertsBell from './AlertsBell'
import DataClock from './DataClock'
import { api } from '../lib/api'
import { getColorMode, setColorMode, type ColorMode } from '../lib/format'
import type { SystemStatus } from '../lib/types'
import { useAuth } from '../store/auth'
import { Badge, Button, Modal } from './ui'

const NAV = [
  { to: '/dashboard', label: '仪表盘', icon: LayoutDashboard, desc: '账户总览与市场快照' },
  { to: '/market', label: '行情分析', icon: CandlestickChart, desc: 'K 线与技术指标' },
  { to: '/rankings', label: '美股榜单', icon: Trophy, desc: 'S&P 500 涨跌与成交排行' },
  { to: '/strategies', label: '策略实验室', icon: FlaskConical, desc: '内置策略与自定义策略' },
  { to: '/backtest', label: '回测中心', icon: BarChart3, desc: '历史回测与参数寻优' },
  { to: '/optimize', label: '组合优化', icon: Scaling, desc: '权重求解与有效前沿' },
  { to: '/intel', label: 'AI 情报中心', icon: Satellite, desc: '公司关键节点与 AI 买入建议' },
  { to: '/trading', label: '实盘交易', icon: Activity, desc: '下单与实时引擎' },
  { to: '/portfolio', label: '持仓组合', icon: Wallet, desc: '持仓与订单流水' },
  { to: '/risk', label: '风控中心', icon: ShieldAlert, desc: '护栏与熔断' },
  { to: '/ai', label: 'AI 研判', icon: Bot, desc: '量化分析与策略匹配' },
  { to: '/aiops', label: 'AI 接管中心', icon: BotMessageSquare, desc: 'AI 视角：在看什么·做什么·为什么' },
  { to: '/settings', label: '系统设置', icon: Cog, desc: '券商连接与安全' },
]

export default function Layout() {
  const { username, logout } = useAuth()
  const loc = useLocation()
  const [open, setOpen] = useState(false)
  const [status, setStatus] = useState<SystemStatus | null>(null)
  const [colorMode, setCM] = useState<ColorMode>(getColorMode())
  const [userMenu, setUserMenu] = useState(false)

  useEffect(() => {
    let alive = true
    const load = () =>
      api
        .get<SystemStatus>('/system/status')
        .then((s) => alive && setStatus(s))
        .catch(() => {})
    load()
    const t = setInterval(load, 20000)
    return () => {
      alive = false
      clearInterval(t)
    }
  }, [loc.pathname])

  useEffect(() => setOpen(false), [loc.pathname])

  const current = NAV.find((n) => loc.pathname.startsWith(n.to))

  const toggleColor = () => {
    const next: ColorMode = colorMode === 'cn' ? 'us' : 'cn'
    setColorMode(next)
    setCM(next)
    window.dispatchEvent(new Event('qd-colormode'))
  }

  return (
    <div className="flex h-full bg-slate-50">
      {/* 侧边栏 */}
      <aside
        className={`fixed inset-y-0 left-0 z-40 w-64 shrink-0 border-r border-slate-200 bg-white transition-transform lg:static lg:translate-x-0 ${
          open ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <div className="flex h-14 items-center justify-between border-b border-slate-100 px-4">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-brand-500 to-brand-700 text-white shadow-sm">
              <Radar className="h-4.5 w-4.5" style={{ height: 18, width: 18 }} />
            </div>
            <div className="leading-tight">
              <div className="text-sm font-semibold text-slate-900">QuantDesk</div>
              <div className="text-[10px] text-slate-400">IBKR 量化交易平台</div>
            </div>
          </div>
          <button className="rounded p-1 text-slate-400 lg:hidden" onClick={() => setOpen(false)}>
            <X className="h-4 w-4" />
          </button>
        </div>

        <nav className="space-y-0.5 overflow-y-auto p-2.5" style={{ maxHeight: 'calc(100% - 56px)' }}>
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              className={({ isActive }) =>
                `group flex items-start gap-3 rounded-lg px-3 py-2.5 transition-colors ${
                  isActive ? 'bg-brand-50 text-brand-700' : 'text-slate-600 hover:bg-slate-50'
                }`
              }
            >
              {({ isActive }) => (
                <>
                  <n.icon className={`mt-0.5 h-4 w-4 shrink-0 ${isActive ? 'text-brand-600' : 'text-slate-400'}`} />
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-medium">{n.label}</span>
                    <span className="mt-0.5 block truncate text-[11px] text-slate-400">{n.desc}</span>
                  </span>
                </>
              )}
            </NavLink>
          ))}
        </nav>
      </aside>

      {open && <div className="fixed inset-0 z-30 bg-slate-900/30 lg:hidden" onClick={() => setOpen(false)} />}

      {/* 主区 */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex h-14 shrink-0 items-center gap-3 border-b border-slate-200 bg-white/90 px-4 backdrop-blur">
          <button className="rounded-md p-1.5 text-slate-500 hover:bg-slate-100 lg:hidden" onClick={() => setOpen(true)}>
            <Menu className="h-5 w-5" />
          </button>

          <div className="min-w-0 flex-1">
            <h1 className="truncate text-sm font-semibold text-slate-800">{current?.label ?? 'QuantDesk'}</h1>
            <p className="truncate text-[11px] text-slate-400">{current?.desc ?? ''}</p>
          </div>

          <div className="hidden items-center gap-2 sm:flex">
            {status?.kill_switch && (
              <Badge tone="red" dot>
                熔断已启用
              </Badge>
            )}
            {status?.mode === 'live' ? (
              <Badge tone="red" dot>
                实盘模式
              </Badge>
            ) : (
              <Badge tone="brand" dot>
                模拟盘
              </Badge>
            )}
            <Badge tone={status?.broker === 'ibkr' ? 'green' : 'slate'}>
              {status?.broker === 'ibkr' ? `IBKR ${status.broker_host}` : '内置模拟券商'}
            </Badge>
          </div>

          <DataClock />

          <AlertsBell />

          <button
            onClick={toggleColor}
            title="切换涨跌配色（当前：中国习惯 红涨绿跌）"
            className="hidden rounded-md border border-slate-200 px-2 py-1 text-[11px] text-slate-500 hover:bg-slate-50 sm:block"
          >
            {colorMode === 'cn' ? '红涨绿跌' : '绿涨红跌'}
          </button>

          <div className="relative">
            <button
              onClick={() => setUserMenu((v) => !v)}
              className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm text-slate-600 hover:bg-slate-100"
            >
              <span className="flex h-6 w-6 items-center justify-center rounded-full bg-brand-100 text-[11px] font-semibold text-brand-700">
                {(username || 'U').slice(0, 1).toUpperCase()}
              </span>
              <span className="hidden max-w-[90px] truncate sm:block">{username}</span>
            </button>
            {userMenu && (
              <>
                <div className="fixed inset-0 z-10" onClick={() => setUserMenu(false)} />
                <div className="absolute right-0 z-20 mt-1 w-56 rounded-lg border border-slate-200 bg-white p-2 shadow-pop">
                  <div className="border-b border-slate-100 px-2 pb-2 text-xs text-slate-500">
                    当前账户：<span className="font-medium text-slate-700">{username}</span>
                    <div className="mt-1 text-[11px] text-slate-400">{status?.runtime_dir}</div>
                  </div>
                  <button
                    onClick={() => {
                      setUserMenu(false)
                      logout()
                    }}
                    className="mt-1 flex w-full items-center gap-2 rounded-md px-2 py-2 text-sm text-rose-600 hover:bg-rose-50"
                  >
                    <LogOut className="h-3.5 w-3.5" />
                    退出登录
                  </button>
                </div>
              </>
            )}
          </div>
        </header>

        <main className="min-h-0 flex-1 overflow-y-auto p-4 lg:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

/* 退出确认（未使用，保留给未来扩展） */
export function ConfirmModal({
  open,
  onClose,
  onConfirm,
  title,
  body,
  confirmText = '确认',
  danger,
}: {
  open: boolean
  onClose: () => void
  onConfirm: () => void
  title: string
  body: React.ReactNode
  confirmText?: string
  danger?: boolean
}) {
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      footer={
        <>
          <Button onClick={onClose}>取消</Button>
          <Button
            variant={danger ? 'danger' : 'primary'}
            onClick={() => {
              onConfirm()
              onClose()
            }}
          >
            {confirmText}
          </Button>
        </>
      }
    >
      {body}
    </Modal>
  )
}
