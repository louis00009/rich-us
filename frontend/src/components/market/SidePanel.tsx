/**
 * 行情页 · 侧栏（关键价位 / 区间收益 / 指标读数 / AI 个股快评）
 *
 * 从 `pages/Market.tsx` 抽出（铁律 9 拆分，2026-09-29）。
 */
import { Card, KV, Loading } from '../ui'
import AIAssist from '../AIAssist'
import { fmtNum, fmtRatioPct, signClass } from '../../lib/format'
import type { SnapResp } from './types'

export function SidePanel({ snap, symbol }: { snap: SnapResp | null; symbol: string }) {
  return (
    <div className="space-y-5">
      <Card
        title="关键价位与结构"
        subtitle={
          <span className="flex flex-wrap items-center gap-2">
            <span>{snap ? `截至 ${snap.last_date}` : ''}</span>
            {snap?.realtime?.realtime ? (
              <span
                className="inline-flex items-center gap-1 rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-700"
                title={`报价来源 ${snap.realtime.quote_source || '-'} · ${snap.realtime.quote_ts || ''}`}
              >
                <span className="inline-block h-1.5 w-1.5 rounded-full bg-emerald-500" />
                实时价 · {snap.realtime.quote_source}
              </span>
            ) : (
              <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-500" title={snap?.realtime?.note || ''}>
                日线口径
              </span>
            )}
          </span>
        }
      >
        {snap ? (
          <div className="space-y-3">
            <KV
              cols={1}
              items={[
                { k: '现价', v: fmtNum(snap.price, 2) },
                { k: '52 周最高', v: fmtNum(snap.levels?.high_52w, 2) },
                { k: '52 周最低', v: fmtNum(snap.levels?.low_52w, 2) },
                {
                  k: '距 52 周高点',
                  v: (
                    <span className={signClass(snap.dist?.to_52w_high ?? 0)}>
                      {fmtRatioPct((snap.dist?.to_52w_high ?? 0) / 100, 2, true)}
                    </span>
                  ),
                },
                { k: 'SMA50', v: fmtNum(snap.ma?.sma50, 2) },
                { k: 'SMA200', v: fmtNum(snap.ma?.sma200, 2) },
                { k: 'ATR(14)', v: fmtNum(snap.indicators?.atr14, 2) },
                { k: 'ATR 占比', v: `${fmtNum(snap.indicators?.atr_pct, 2)}%` },
                { k: '枢轴价', v: fmtNum(snap.levels?.pivot, 2) },
              ]}
            />
          </div>
        ) : (
          <Loading />
        )}
      </Card>

      <Card title="区间收益" subtitle="用于判断动量强弱">
        {snap ? (
          <div className="space-y-2">
            {[
              ['1 日', snap.returns?.['1d']],
              ['5 日', snap.returns?.['5d']],
              ['1 月', snap.returns?.['1m']],
              ['3 月', snap.returns?.['3m']],
              ['6 月', snap.returns?.['6m']],
              ['1 年', snap.returns?.['1y']],
              ['年初至今', snap.returns?.ytd],
            ].map(([label, v]) => (
              <div key={label as string} className="flex items-center justify-between border-b border-dashed border-slate-100 pb-1.5">
                <span className="text-xs text-slate-500">{label}</span>
                <span className={`num text-sm font-medium ${signClass(v as number)}`}>
                  {v === null || v === undefined ? '—' : `${Number(v) > 0 ? '+' : ''}${Number(v).toFixed(2)}%`}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <Loading />
        )}
      </Card>

      <Card title="指标读数" subtitle={snap?.realtime?.realtime ? '已融合实时价计算' : ''}>
        {snap ? (
          <div className="space-y-2">
            {[
              ['RSI(14)', snap.indicators?.rsi14, 2],
              ['MACD 柱', snap.indicators?.macd_hist, 4],
              ['ADX(14)', snap.indicators?.adx14, 1],
              ['+DI', snap.indicators?.plus_di, 1],
              ['-DI', snap.indicators?.minus_di, 1],
              ['布林 %B', snap.indicators?.bb_pctb, 3],
              ['量比', snap.indicators?.vol_ratio, 2],
              ['CMF(20)', snap.indicators?.cmf20, 3],
              ['Z 分数', snap.indicators?.zscore20, 2],
              ['效率比', snap.indicators?.efficiency_ratio, 3],
              ['Hurst', snap.indicators?.hurst, 3],
            ].map(([label, v, d]) => (
              <div key={label as string} className="flex items-center justify-between border-b border-dashed border-slate-100 pb-1.5">
                <span className="text-xs text-slate-500">{label}</span>
                <span className="num text-sm font-medium text-slate-700">
                  {v === null || v === undefined ? '—' : Number(v).toFixed(d as number)}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <Loading />
        )}
      </Card>

      {/* AI 个股快评：复用「设置 → AI 分析」的全局模型；未配置时走本地规则兜底 */}
      <AIAssist
        mode="panel"
        task="symbol_brief"
        title="AI 个股快评"
        desc="状态判定 · 多空依据 · 关键价位 · 该警惕什么"
        label="生成快评"
        runKey={symbol}
        payload={{ symbol }}
        disabled={!snap}
        disabledHint="行情未加载，无法生成快评。"
        emptyHint="点击上方「生成快评」按钮，AI 会基于当前标的的行情、指标与本地引擎结论给出一段可执行快评。"
      />
    </div>
  )
}
