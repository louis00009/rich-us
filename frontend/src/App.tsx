import { Component, Suspense, lazy, useEffect, useState } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import Layout from './components/Layout'
import { Loading, ThemeVars } from './components/ui'
import { downColor, getColorMode, upColor } from './lib/format'
import Login from './pages/Login'
import { useAuth } from './store/auth'

// chunk 加载失败兜底：新版本发布后旧 html 引用的 chunk 已被归档，lazy 加载 404。
// 没有这个兜底就是白屏（用户端反复「页面有问题」的另一半根因）。
class ChunkErrorBoundary extends Component<{ children: React.ReactNode }, { err: Error | null }> {
  state = { err: null as Error | null }
  static getDerivedStateFromError(err: Error) {
    return { err }
  }
  render() {
    if (this.state.err) {
      const msg = String(this.state.err?.message || this.state.err)
      const isChunk = /dynamically imported module|Loading chunk|Failed to fetch/i.test(msg)
      return (
        <div className="flex h-screen flex-col items-center justify-center gap-3 bg-slate-50 text-center">
          <div className="text-lg font-semibold text-slate-800">
            {isChunk ? '检测到新版本已发布' : '页面加载出错'}
          </div>
          <div className="max-w-md text-sm text-slate-500">
            {isChunk ? '浏览器缓存的旧页面引用了已更新的文件，点击刷新即可继续。' : msg.slice(0, 200)}
          </div>
          <button
            onClick={() => window.location.reload()}
            className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700"
          >
            刷新页面
          </button>
        </div>
      )
    }
    return this.props.children
  }
}

// 路由级代码分割：12 个页面各自成 chunk，首包只加载当前页（bundle 903KB → 主包 ~250KB）
const Dashboard = lazy(() => import('./pages/Dashboard'))
const Market = lazy(() => import('./pages/Market'))
const Rankings = lazy(() => import('./pages/Rankings'))
const Strategies = lazy(() => import('./pages/Strategies'))
const Backtest = lazy(() => import('./pages/Backtest'))
const Optimize = lazy(() => import('./pages/Optimize'))
const Intel = lazy(() => import('./pages/Intel'))
const LiveTrading = lazy(() => import('./pages/LiveTrading'))
const Portfolio = lazy(() => import('./pages/Portfolio'))
const Risk = lazy(() => import('./pages/Risk'))
const AICopilot = lazy(() => import('./pages/AICopilot'))
const AIOps = lazy(() => import('./pages/AIOps'))
const Settings = lazy(() => import('./pages/Settings'))

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { token, ready } = useAuth()
  const loc = useLocation()
  if (!ready) return <Loading label="正在初始化…" className="h-screen" />
  if (!token) return <Navigate to="/login" state={{ from: loc.pathname }} replace />
  return <>{children}</>
}

export default function App() {
  const { initialized, ready, token } = useAuth()
  const [colorMode, setCM] = useState(getColorMode())

  useEffect(() => {
    const h = () => setCM(getColorMode())
    window.addEventListener('qd-colormode', h)
    return () => window.removeEventListener('qd-colormode', h)
  }, [])

  if (!ready) return <Loading label="正在连接后端…" className="h-screen" />

  return (
    <>
      <ThemeVars up={upColor()} down={downColor()} />
      <ChunkErrorBoundary>
      <Suspense fallback={<Loading label="加载页面…" className="h-screen" />}>
        <Routes>
          <Route path="/login" element={initialized === false ? <Login mode="setup" /> : token ? <Navigate to="/dashboard" replace /> : <Login mode="login" />} />
          <Route
            element={
              <RequireAuth>
                <Layout />
              </RequireAuth>
            }
          >
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/market" element={<Market />} />
            <Route path="/rankings" element={<Rankings />} />
            <Route path="/strategies" element={<Strategies />} />
            <Route path="/backtest" element={<Backtest />} />
            <Route path="/optimize" element={<Optimize />} />
            <Route path="/intel" element={<Intel />} />
            <Route path="/trading" element={<LiveTrading />} />
            <Route path="/portfolio" element={<Portfolio />} />
            <Route path="/risk" element={<Risk />} />
            <Route path="/ai" element={<AICopilot />} />
            <Route path="/aiops" element={<AIOps />} />
            <Route path="/settings" element={<Settings />} />
          </Route>
          <Route path="*" element={<Navigate to={token ? '/dashboard' : '/login'} replace />} />
        </Routes>
      </Suspense>
      </ChunkErrorBoundary>
    </>
  )
}
