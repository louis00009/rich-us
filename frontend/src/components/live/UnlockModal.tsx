/**
 * 实盘解锁 / 锁定弹窗（从 `pages/LiveTrading.tsx` 拆出，铁律 9，2026-09-30）。
 *
 * 三道锁的第二道：逐字输入确认短语 + 账户口令。第一道（环境变量）未开时明确告知，
 * 这是刻意设计的安全门槛，不是 bug。
 */
import { Alert, Button, Field, Input, Modal } from '../ui'

export default function UnlockModal({
  open,
  onClose,
  mode,
  busy,
  phrase,
  setPhrase,
  pwd,
  setPwd,
  onUnlock,
}: {
  open: boolean
  onClose: () => void
  /** /trading/mode 的响应（含 live_unlocked / live_env_gate / confirm_phrase） */
  mode: { live_unlocked?: boolean; live_env_gate?: boolean; confirm_phrase?: string } | null
  busy: boolean
  phrase: string
  setPhrase: (v: string) => void
  pwd: string
  setPwd: (v: string) => void
  /** enable=true 解锁 / false 锁定 */
  onUnlock: (enable: boolean) => void
}) {
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={mode?.live_unlocked ? '锁定实盘通道' : '解锁实盘通道'}
      footer={
        <>
          <Button onClick={onClose}>取消</Button>
          {mode?.live_unlocked ? (
            <Button variant="primary" loading={busy} onClick={() => onUnlock(false)}>
              确认锁定
            </Button>
          ) : (
            <Button
              variant="danger"
              loading={busy}
              disabled={phrase.trim() !== (mode?.confirm_phrase || '') || !pwd}
              onClick={() => onUnlock(true)}
            >
              确认解锁
            </Button>
          )}
        </>
      }
    >
      {mode?.live_unlocked ? (
        <Alert tone="info" title="当前实盘已解锁">
          锁定后将无法再进行实盘下单，可随时重新解锁。是否确认锁定？
        </Alert>
      ) : (
        <div className="space-y-4">
          <Alert tone="danger" title="⚠️ 高风险操作">
            解锁实盘后，在实盘模式下的每一笔订单都会真实成交。请确认你理解并接受全部资金风险。
          </Alert>
          {!mode?.live_env_gate && (
            <Alert tone="warn" title="第一道锁尚未开启">
              需要先设置环境变量 <code className="rounded bg-slate-200 px-1">QD_ALLOW_LIVE_TRADING=true</code> 并重启服务，
              才可能解锁实盘。这是刻意设计的安全门槛。
            </Alert>
          )}
          <Field label={`逐字输入确认短语：${mode?.confirm_phrase || ''}`}>
            <Input value={phrase} onChange={(e) => setPhrase(e.target.value)} placeholder={mode?.confirm_phrase} className="num" />
          </Field>
          <Field label="账户口令">
            <Input type="password" value={pwd} onChange={(e) => setPwd(e.target.value)} autoComplete="current-password" />
          </Field>
        </div>
      )}
    </Modal>
  )
}
