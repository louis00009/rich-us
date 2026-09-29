/**
 * SaveStrategyModal —— 把一组权重另存为「恒定目标权重」策略
 * =========================================================
 * 从 `pages/Optimize.tsx` 抽出（铁律 9）。纯受控：名字与开关状态都由父级持有。
 */
import { Save } from 'lucide-react'
import { fmtRatioPct } from '../../lib/format'
import { Alert, Badge, Button, Field, Input, Modal } from '../ui'
import type { OptResult } from './types'

interface Props {
  open: boolean
  onClose: () => void
  onSave: () => void
  saving: boolean
  name: string
  setName: (v: string) => void
  result: OptResult | null
}

export default function SaveStrategyModal({ open, onClose, onSave, saving, name, setName, result }: Props) {
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="把权重另存为策略"
      footer={
        <>
          <Button onClick={onClose}>取消</Button>
          <Button variant="primary" loading={saving} onClick={onSave} icon={<Save className="h-3.5 w-3.5" />}>
            保存
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <Alert tone="info">
          将生成一个「恒定目标权重」的代码策略：每根 bar 输出同一组权重，引擎按权重再平衡。
          保存后可在「策略实验室」直接回测，或挂到实时引擎上运行。
        </Alert>
        <Field label="策略名称" hint="需唯一，建议带上目标与区间，例如「最大夏普-股债商均衡-2021起」">
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="最大夏普 · 股债商均衡" />
        </Field>
        {result && (
          <div className="rounded-lg border border-slate-200 p-3 text-xs">
            <div className="mb-1 font-medium text-slate-600">即将保存的权重</div>
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(result.weights)
                .filter(([, v]) => Math.abs(v) > 1e-6)
                .sort((a, b) => b[1] - a[1])
                .map(([k, v]) => (
                  <Badge key={k} tone="brand">
                    {k} {fmtRatioPct(v, 1)}
                  </Badge>
                ))}
            </div>
          </div>
        )}
      </div>
    </Modal>
  )
}
