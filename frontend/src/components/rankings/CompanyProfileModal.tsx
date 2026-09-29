/**
 * 公司档案弹窗
 * ============
 * 从 `pages/Rankings.tsx` 抽出来的展示块（该页面已贴 600 行软上限，铁律 9：
 * 加新功能前必须先拆）。这里只负责渲染，取数与序号守卫仍留在页面里。
 */
import { Alert, Badge, Button, Modal, Spinner } from '../ui'

export default function CompanyProfileModal({
  symbol,
  profile,
  loading,
  onClose,
  onRefresh,
  onGoMarket,
}: {
  symbol: string
  profile: any
  loading: boolean
  onClose: () => void
  onRefresh: () => void
  onGoMarket: () => void
}) {
  return (
    <Modal open={!!symbol} onClose={onClose} title={symbol ? `${symbol} · 公司档案` : ''}>
      {loading && (
        <div className="flex items-center justify-center gap-2 py-8 text-sm text-slate-400">
          <Spinner /> 正在获取档案…
        </div>
      )}
      {profile && !loading && (
        <div className="space-y-3">
          {profile.error && !profile.name && (
            <Alert tone="warn" title="档案不可用">
              {profile.error}
            </Alert>
          )}
          {profile.name && (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-lg font-semibold text-slate-900">{profile.name}</span>
                {profile.sector && <Badge tone="brand">{profile.sector}</Badge>}
                {profile.industry && <Badge tone="slate">{profile.industry}</Badge>}
                {profile.country && <Badge tone="slate">{profile.country}</Badge>}
              </div>
              <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-slate-500">
                {profile.market_cap > 0 && (
                  <span>
                    市值 <span className="num font-medium text-slate-700">${(profile.market_cap / 1e9).toFixed(0)}B</span>
                  </span>
                )}
                {profile.ipo_date && (
                  <span>
                    IPO <span className="text-slate-700">{profile.ipo_date}</span>
                  </span>
                )}
                {profile.website && (
                  <a href={profile.website} target="_blank" rel="noreferrer" className="text-brand-600 hover:underline">
                    官网 ↗
                  </a>
                )}
              </div>
              {profile.summary && (
                <div>
                  <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-slate-400">
                    Business Summary
                  </div>
                  <p className="max-h-72 overflow-y-auto whitespace-pre-wrap rounded-lg bg-slate-50 p-3 text-[13px] leading-6 text-slate-600">
                    {profile.summary}
                  </p>
                </div>
              )}
              <div className="flex justify-end gap-2 pt-1">
                <Button onClick={onRefresh}>强制刷新</Button>
                <Button variant="primary" onClick={onGoMarket}>
                  去行情分析
                </Button>
              </div>
            </>
          )}
        </div>
      )}
    </Modal>
  )
}
