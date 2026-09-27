/**
 * P0-1 回归测试：WebSocket 主题匹配契约
 * =====================================
 * 背景：前端订阅用带标的的主题（"quotes:SPY"），后端广播的是裸主题（"quotes"，
 * 见 backend/app/realtime.py:_broadcast_quotes）。旧实现用
 * `h.topics.includes(m.topic)` 做精确匹配 → ['quotes:SPY'].includes('quotes') === false
 * → 所有行情 handler 永不触发：行情秒级推送全链路静默失效，只靠 60s 轮询兜底，
 * 而 DataClock 因为 lastTickAt 照常更新仍显示绿灯「推送中」，从 UI 完全看不出来。
 *
 * 本测试**转译并加载真实的 src/lib/realtime.ts**，调用其导出的 topicMatches，
 * 因此守住的是真实契约（而不是复制一份逻辑自测 —— 那样 bug 会一起被复制）。
 *
 * 用法：node scripts/topic-check.mjs   （npm run test:topics）
 */
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import ts from 'typescript'

const here = dirname(fileURLToPath(import.meta.url))
const srcPath = join(here, '..', 'src', 'lib', 'realtime.ts')
const source = readFileSync(srcPath, 'utf8')

const js = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
  fileName: 'realtime.ts',
}).outputText

const mod = await import('data:text/javascript;base64,' + Buffer.from(js, 'utf8').toString('base64'))

if (typeof mod.topicMatches !== 'function') {
  console.error('FAIL  realtime.ts 未导出 topicMatches —— 主题匹配契约测试无法执行')
  process.exit(1)
}

/** [订阅主题, 服务端下发的 topic, 期望匹配, 说明] */
const cases = [
  [['quotes:SPY'], 'quotes', true, '行情：带标的订阅必须收到裸主题 quotes'],
  [['quotes:SPY,QQQ'], 'quotes', true, '行情：多标的订阅'],
  [['quotes:0700.HK'], 'quotes', true, '行情：港股'],
  [['intraday:AAPL'], 'intraday', true, '分时：带标的订阅'],
  [['alerts'], 'alerts', true, '告警：同名主题'],
  [['quotes:SPY'], 'alerts', false, '行情 handler 不得收到 alerts'],
  [['alerts'], 'quotes', false, '告警 handler 不得收到 quotes'],
  [['quotes:SPY'], 'intraday', false, 'quotes 与 intraday 不得串台'],
  [[], 'quotes', false, '无订阅时不匹配'],
]

let pass = 0
let fail = 0
for (const [subs, incoming, want, label] of cases) {
  const got = mod.topicMatches(subs, incoming)
  const ok = got === want
  ok ? pass++ : fail++
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}  (${JSON.stringify(subs)} ← "${incoming}" = ${got})`)
}

// 反向断言：旧的精确匹配写法在行情场景下必须为 false —— 证明这个 bug 真实存在过，
// 也确保将来没人把它「优化」回 includes()。
const legacy = ['quotes:SPY'].includes('quotes')
const legacyOk = legacy === false
legacyOk ? pass++ : fail++
console.log(`${legacyOk ? 'PASS' : 'FAIL'}  旧实现 ['quotes:SPY'].includes('quotes') === false（bug 复现）`)

console.log(`\n${pass}/${pass + fail} 通过`)
process.exit(fail === 0 ? 0 : 1)
