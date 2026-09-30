// 设置页「AI 分析」与「安全与实盘」tab（FILE_SIZE_DEBT Batch C-3 拆分）
import { CheckCircle2, KeyRound, Lock, Save, ShieldCheck, Unplug, XCircle } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Alert, Badge, Button, Card, Field, Input, Select } from '../ui'
import { getUser } from '../../lib/api'
import type { SystemStatus } from '../../lib/types'

interface AiTabProps {
  aiCfg: any
  aiModels: any
  aiKeyInput: string
  aiSaving: boolean
  aiTesting: boolean
  onAiCfg: (updater: (c: any) => any) => void
  onKeyInput: (v: string) => void
  onSaveAi: () => void
  onTestAi: () => void
}

export function AiTab({
  aiCfg, aiModels, aiKeyInput, aiSaving, aiTesting,
  onAiCfg, onKeyInput, onSaveAi, onTestAi,
}: AiTabProps) {
  return (
    <div className="grid gap-5 xl:grid-cols-3">
      <Card
        className="xl:col-span-2"
        title="AI 全局模型"
        subtitle="AI 研判 / AI Copilot 的默认模型。下拉列出网关的全部国内与国际模型，保存即生效，无需重启"
      >
        <div className="space-y-4">
          <Field
            label="分析模型"
            hint={
              aiModels?.ok
                ? `网关共 ${((aiModels.cn || []).length + (aiModels.global || []).length)} 个模型（国内 ${(aiModels.cn || []).length} · 国际 ${(aiModels.global || []).length}）`
                : '网关不可达：请先运行 aistart.bat 启动 AI 服务'
            }
          >
            <Select
              value={aiCfg.model}
              onChange={(e) => onAiCfg((c: any) => ({ ...c, model: e.target.value }))}
            >
              {(aiModels?.cn || []).length > 0 && (
                <optgroup label={`国内模型（${(aiModels.cn || []).length}）`}>
                  {aiModels.cn.map((m: string) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                </optgroup>
              )}
              {(aiModels?.global || []).length > 0 && (
                <optgroup label={`国际模型（${(aiModels.global || []).length}）`}>
                  {aiModels.global.map((m: string) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                </optgroup>
              )}
              {aiCfg.model && !(aiModels?.cn || []).includes(aiCfg.model) && !(aiModels?.global || []).includes(aiCfg.model) && (
                <option value={aiCfg.model}>{aiCfg.model}（当前，网关清单中未返回）</option>
              )}
            </Select>
          </Field>

          {aiModels?.ok === false && (
            <Alert tone="danger" title="网关不可达">
              {aiModels?.error || '未知错误'} —— 请确认已运行 IBKR 目录下的 aistart.bat（或 wbm.sh start）。
            </Alert>
          )}
          {aiModels?.ok && (aiModels?.global || []).length === 0 && (
            <Alert tone="info" title="没有看到国际模型？">
              网关按密钥的版本归属过滤清单。到 WorkBuddy 面板（127.0.0.1:16689）「密钥」页，把当前密钥的版本改为「不限定」，即可解锁全部国际模型。
            </Alert>
          )}

          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="网关地址（OpenAI 兼容）" hint="仅允许本机回环地址">
              <Input
                value={aiCfg.base_url || ''}
                onChange={(e) => onAiCfg((c: any) => ({ ...c, base_url: e.target.value }))}
                placeholder="http://127.0.0.1:16689"
              />
            </Field>
            <Field label="网关密钥" hint={aiCfg.api_key ? `当前：${aiCfg.api_key}（留空 = 保持不变）` : '面板「密钥」页签发的 wbk_ 密钥'}>
              <Input
                type="password"
                value={aiKeyInput}
                onChange={(e) => onKeyInput(e.target.value)}
                placeholder={aiCfg.api_key ? '留空保持现有密钥' : 'wbk_...'}
              />
            </Field>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={onSaveAi} disabled={aiSaving}>
              <Save className="h-4 w-4" />
              {aiSaving ? '保存中…' : '保存 AI 配置'}
            </Button>
            <Button variant="secondary" onClick={onTestAi} disabled={aiTesting}>
              <Unplug className="h-4 w-4" />
              {aiTesting ? '测试中…' : '测试连通（真实调用一次）'}
            </Button>
          </div>
        </div>
      </Card>

      <Card title="说明" subtitle="这条链路走的是什么">
        <div className="space-y-3 text-sm opacity-80">
          <p>
            保存后，平台<strong className="font-medium">所有 AI 功能</strong>都会走这里配置的网关：
            AI 研判、AI Copilot，以及散落在各页的 AI 助手卡片（行情页个股快评与新闻要点、
            榜单候选池点评、回测诊断、寻优解读、风控体检、组合点评、订单诊断、情报解读、盘面简报）。
            额度来自 WorkBuddy 账号池，按调用计费，在面板「调用日志」里逐条可查。
          </p>
          <p>
            未配置网关时不会报错：每个 AI 助手都会退回<span className="font-medium">确定性的本地规则兜底</span>，
            页面照常可用，只是少了自然语言深度解读。
          </p>
          <p>
            单次分析也可以临时换模型：AI 页的「模型」下拉（仅本次生效）；
            这里改的是全局默认。
          </p>
          <p>
            Claude Code 编码助手用的是另一份配置
            （.claude/settings.local.json），与本卡互不影响。
          </p>
        </div>
      </Card>
    </div>
  )
}

interface SecurityTabProps {
  status: SystemStatus | null
  audit: any
  onOpenPwd: () => void
}

export function SecurityTab({ status, audit, onOpenPwd }: SecurityTabProps) {
  return (
    <div className="grid gap-5 xl:grid-cols-3">
      <Card className="xl:col-span-2" title="实盘交易三重锁" subtitle="三道锁全部打开才可能下出实盘单">
        <div className="space-y-4">
          {[
            {
              n: '①',
              title: '环境变量开关',
              on: status?.live_env_gate,
              desc: '需要在后端启动前设置 QD_ALLOW_LIVE_TRADING=true。这是编译期级别的硬闸门，防止误配置。',
              fix: '在 backend/runtime/.env 写入 QD_ALLOW_LIVE_TRADING=true 后重启服务',
            },
            {
              n: '②',
              title: '运行时解锁',
              on: status?.live_unlocked,
              desc: '在「实盘交易」页面逐字输入确认短语 I UNDERSTAND THE RISK 并输入账户口令，才能解锁。',
              fix: '前往「实盘交易」页面点击「解锁实盘」',
            },
            {
              n: '③',
              title: '逐笔风控护栏',
              on: true,
              desc: '每一笔订单都要通过单标的限额、总敞口、日亏上限、回撤熔断、白黑名单、交易时段等全部检查。',
              fix: '',
            },
          ].map((l) => (
            <div
              key={l.n}
              className={`flex items-start gap-3 rounded-lg border p-3.5 ${
                l.on ? 'border-emerald-200 bg-emerald-50/50' : 'border-slate-200 bg-slate-50'
              }`}
            >
              <span className={`text-xl font-bold ${l.on ? 'text-emerald-600' : 'text-slate-300'}`}>{l.n}</span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-slate-800">{l.title}</span>
                  {l.on ? (
                    <Badge tone="green">
                      <CheckCircle2 className="mr-0.5 h-3 w-3" />
                      已开启
                    </Badge>
                  ) : (
                    <Badge tone="slate">
                      <XCircle className="mr-0.5 h-3 w-3" />
                      未开启
                    </Badge>
                  )}
                </div>
                <p className="mt-1 text-xs leading-relaxed text-slate-500">{l.desc}</p>
                {!l.on && l.fix && <p className="mt-1.5 text-[11px] text-brand-600">如何开启：{l.fix}</p>}
              </div>
            </div>
          ))}

          <Alert tone={status?.live_ready ? 'danger' : 'success'} title={status?.live_ready ? '⚠️ 实盘通道当前已就绪' : '🛡️ 实盘通道当前已锁定'}>
            {status?.live_reason}
          </Alert>

          <div className="flex gap-2">
            <Link to="/trading">
              <Button variant="primary" icon={<Lock className="h-3.5 w-3.5" />}>
                前往实盘交易页管理解锁
              </Button>
            </Link>
            <Link to="/risk">
              <Button icon={<ShieldCheck className="h-3.5 w-3.5" />}>复核风控限额</Button>
            </Link>
          </div>
        </div>
      </Card>

      <div className="space-y-5">
        <Card title="账户安全">
          <div className="space-y-3">
            <div className="flex items-center justify-between border-b border-dashed border-slate-100 pb-2">
              <span className="text-xs text-slate-500">登录账户</span>
              <span className="flex items-center gap-2 text-sm font-medium text-slate-700">
                {getUser() || '—'}
                <Badge tone="green">已认证</Badge>
              </span>
            </div>
            <p className="text-xs text-slate-500">
              口令使用 bcrypt（cost=12）加盐哈希存储，服务端无法还原明文。会话使用 JWT 放在
              Authorization 头中，不使用 Cookie，因此天然免疫 CSRF。
            </p>
            <Button onClick={onOpenPwd} icon={<KeyRound className="h-3.5 w-3.5" />}>
              修改口令
            </Button>
          </div>
        </Card>

        <Card title="服务安全基线">
          <div className="space-y-2 text-xs text-slate-600">
            {[
              ['仅监听本机回环地址', status ? `未暴露（${status.broker_host}）` : '—'],
              ['会话令牌有效期', '12 小时'],
              ['登录失败锁定', '8 次 / 5 分钟'],
              ['请求体大小限制', '4 MB'],
              ['安全响应头', '已启用'],
              ['凭据加密', 'Fernet (AES-128-CBC + HMAC)'],
              ['审计留痕', `${audit?.audit_total ?? 0} 条记录`],
            ].map(([k, v]) => (
              <div key={k} className="flex items-center justify-between border-b border-dashed border-slate-100 pb-1.5">
                <span className="text-slate-500">{k}</span>
                <span className="font-medium text-slate-700">{v}</span>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  )
}
