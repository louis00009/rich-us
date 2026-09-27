/**
 * 全局 ErrorBoundary（P1-11）
 * ============================
 * 修复前：全项目无任何 ErrorBoundary，而页面大量使用裸 `.toFixed()` 等链式取值 ——
 * 后端任一字段缺失/改名都会让整页 React 卸载白屏（连侧边栏都没有）。
 *
 * 用法：在 main.tsx 包住 <App />。页面级若需局部降级，可再用一层包住可疑子树。
 */
import { Component, type ErrorInfo, type ReactNode } from 'react'

type Props = { children: ReactNode }
type State = { error: Error | null }

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // 控制台留全量栈便于排查；不自动上报（本地单机应用）
    // eslint-disable-next-line no-console
    console.error('[ErrorBoundary]', error, info.componentStack)
  }

  render() {
    const { error } = this.state
    if (!error) return this.props.children
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50 p-6">
        <div className="w-full max-w-lg rounded-xl border border-rose-200 bg-white p-6 shadow-sm">
          <div className="mb-3 flex items-center gap-2">
            <span className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-rose-100 text-lg">💥</span>
            <h1 className="text-base font-semibold text-slate-800">页面渲染出错</h1>
          </div>
          <p className="mb-3 text-sm text-slate-600">
            界面在渲染过程中遇到未捕获的异常（通常是后端返回了缺失字段或格式变更）。
            应用其余部分仍在运行 —— 刷新本页即可恢复。
          </p>
          <pre className="mb-4 max-h-40 overflow-auto rounded-lg bg-slate-50 p-3 text-xs leading-relaxed text-rose-700">
            {error.message || String(error)}
          </pre>
          <div className="flex gap-2">
            <button
              onClick={() => window.location.reload()}
              className="inline-flex h-9 items-center rounded-lg bg-brand-600 px-4 text-sm font-medium text-white hover:bg-brand-700"
            >
              刷新页面
            </button>
            <button
              onClick={() => this.setState({ error: null })}
              className="inline-flex h-9 items-center rounded-lg border border-slate-300 bg-white px-4 text-sm text-slate-700 hover:bg-slate-50"
            >
              重试渲染
            </button>
          </div>
        </div>
      </div>
    )
  }
}
