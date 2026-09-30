// 设置页「券商连接」tab（FILE_SIZE_DEBT Batch C-3 拆分）
// ⚠️ 数据源清单（presets / setup_guide）一律来自后端 /system/broker，不许硬编码。
import { Activity, RefreshCw, Save, Unplug } from 'lucide-react'
import { Alert, Button, Card, Field, Input, Select, Switch } from '../ui'
import { fmtNum } from '../../lib/format'
import type { BrokerCfg } from './types'

interface BrokerTabProps {
  cfg: BrokerCfg
  presets: any[]
  guide: string[]
  testResult: any
  saving: boolean
  testing: boolean
  onUpd: (patch: Partial<BrokerCfg>) => void
  onSave: () => void
  onTest: () => void
  onDisconnect: () => void
  onResetSim: () => void
}

export default function BrokerTab({
  cfg, presets, guide, testResult, saving, testing,
  onUpd, onSave, onTest, onDisconnect, onResetSim,
}: BrokerTabProps) {
  return (
    <div className="grid gap-5 xl:grid-cols-3">
      <Card className="xl:col-span-2" title="券商配置" subtitle="默认使用内置模拟券商，零资金风险">
        <div className="space-y-4">
          <Field label="券商提供方">
            <Select value={cfg.provider} onChange={(e) => onUpd({ provider: e.target.value as any })}>
              <option value="simulated">内置模拟券商（推荐先用它跑通全流程）</option>
              <option value="ibkr">Interactive Brokers (IBKR)</option>
            </Select>
          </Field>

          {cfg.provider === 'ibkr' && (
            <>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="TWS / Gateway 主机">
                  <Input value={cfg.host} onChange={(e) => onUpd({ host: e.target.value })} />
                </Field>
                <Field label="端口" hint="纸面 7497(TWS)/4002(GW) ｜ 实盘 7496(TWS)/4001(GW)">
                  <Input type="number" value={cfg.port} onChange={(e) => onUpd({ port: parseInt(e.target.value || '7497', 10) })} />
                </Field>
                <Field label="Client ID" hint="同一 TWS 上多个客户端需用不同 ID">
                  <Input type="number" value={cfg.client_id} onChange={(e) => onUpd({ client_id: parseInt(e.target.value || '17', 10) })} />
                </Field>
                <Field label="账户号（可选）" hint="留空则自动使用第一个受管账户">
                  <Input value={cfg.account} onChange={(e) => onUpd({ account: e.target.value })} />
                </Field>
              </div>

              <div className="flex flex-wrap gap-1.5">
                {presets
                  .filter((p) => p.key !== 'simulated')
                  .map((p) => (
                    <button
                      key={p.key}
                      onClick={() => onUpd({ host: p.host, port: p.port, provider: 'ibkr' })}
                      className={`rounded-md px-2.5 py-1.5 text-xs transition-colors ${
                        cfg.port === p.port ? 'bg-brand-600 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                      }`}
                    >
                      {p.label} · {p.host}:{p.port}
                    </button>
                  ))}
              </div>

              <Switch
                checked={cfg.readonly}
                onChange={(v) => onUpd({ readonly: v })}
                label="只读模式（推荐保持开启）"
                hint="开启后本平台只能读取账户与持仓，无法通过 IBKR 下单。需要下单时再关闭。"
              />

              <div className="grid gap-3 sm:grid-cols-2">
                <Field
                  label="行情类型"
                  hint="无实时行情订阅时请用「延迟」；做日内交易建议订阅后改为「实时」"
                >
                  <Select value={cfg.market_data_type} onChange={(e) => onUpd({ market_data_type: parseInt(e.target.value, 10) })}>
                    <option value={1}>1 · 实时行情（需订阅）</option>
                    <option value={2}>2 · 冻结行情</option>
                    <option value={3}>3 · 延迟行情（默认，无需订阅）</option>
                    <option value={4}>4 · 延迟冻结行情</option>
                  </Select>
                </Field>
                <div className="flex items-end pb-1">
                  <Switch
                    checked={cfg.use_rth}
                    onChange={(v) => onUpd({ use_rth: v })}
                    label="仅使用常规交易时段数据"
                    hint="做日内策略建议保持开启；关闭后包含盘前盘后"
                  />
                </div>
              </div>

              <Alert tone="info" title="行情权限说明">
                IBKR 的实时行情需要单独订阅（美股约 $1.5–4.5/月，可用非专业用户费率）。
                未订阅时用「延迟行情」也能正常回测与看盘，但
                <span className="font-medium">日内策略不宜基于延迟价实盘成交</span>。
              </Alert>

              {cfg.port === 7496 || cfg.port === 4001 ? (
                <Alert tone="danger" title="⚠️ 当前配置的是实盘端口">
                  即使端口指向实盘，下单仍受「环境变量 + 运行时解锁 + 逐笔护栏」三重保护。
                  请先在风控中心复核限额，再考虑解锁实盘。
                </Alert>
              ) : null}
            </>
          )}

          <div className="flex flex-wrap gap-2">
            <Button variant="primary" loading={saving} onClick={onSave} icon={<Save className="h-4 w-4" />}>
              保存配置
            </Button>
            <Button loading={testing} onClick={onTest} icon={<Activity className="h-4 w-4" />}>
              测试连接
            </Button>
            <Button onClick={onDisconnect} icon={<Unplug className="h-4 w-4" />}>
              断开连接
            </Button>
          </div>

          {testResult && (
            <Alert tone={testResult.ok ? 'success' : 'danger'} title={testResult.ok ? '连接成功' : '连接失败'}>
              {testResult.message}
              {testResult.ok && testResult.account?.equity !== undefined && (
                <div className="mt-2 grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
                  <span>
                    权益 <b className="num">${fmtNum(testResult.account.equity, 0)}</b>
                  </span>
                  <span>
                    现金 <b className="num">${fmtNum(testResult.account.cash, 0)}</b>
                  </span>
                  <span>
                    买入力 <b className="num">${fmtNum(testResult.account.buying_power, 0)}</b>
                  </span>
                  <span>
                    账户 <b>{testResult.account.account_id}</b>
                  </span>
                </div>
              )}
            </Alert>
          )}
        </div>
      </Card>

      <div className="space-y-5">
        {cfg.provider === 'ibkr' && (
          <Card title="IBKR 准备工作" subtitle="在 TWS 中完成以下设置后才能连接">
            <ol className="space-y-2.5">
              {guide.map((g, i) => (
                <li key={i} className="flex gap-2 text-xs leading-relaxed text-slate-600">
                  <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-brand-100 text-[10px] font-semibold text-brand-700">
                    {i + 1}
                  </span>
                  {g.replace(/^\d+\.\s*/, '')}
                </li>
              ))}
            </ol>
            <Alert tone="warn" className="mt-4" title="端口被占用？">
              IB Gateway 与 TWS 不能同时占用同一端口。若提示连接失败，先确认只有一个客户端在运行且 API 已启用。
            </Alert>
          </Card>
        )}

        <Card title="模拟券商" subtitle="内置虚拟账户，用于全链路演练">
          <div className="space-y-3 text-xs text-slate-600">
            <p>
              模拟券商按最新行情 + 2bp 滑点即时撮合，佣金按
              <span className="num"> max(0.0035/股, 0.35, 名义×0.005%) </span>
              计算。账户状态持久化在本地数据库，重启不丢失。
            </p>
            <p className="text-slate-500">
              它同样会穿过全部风控护栏，因此是验证策略与风控逻辑最安全的方式。
            </p>
            <Button onClick={onResetSim} icon={<RefreshCw className="h-3.5 w-3.5" />}>
              重置模拟账户
            </Button>
          </div>
        </Card>
      </div>
    </div>
  )
}
