/**
 * 真实浏览器回归 —— 行情分析页的「AI 一律手动触发」策略
 * ======================================================
 * 用户要求（2026-09-28）：**打开页面 / 刷新页面不得自动跑 AI**，
 * 必须点卡片上的按钮才生成结论（后端自身的定时任务不算，那不在页面里）。
 *
 * 为什么单独一个脚本：这条策略是**运行时行为**，SSR 静态扫描（render-check 里
 * 那条「src 内无 autoRun」）只能守住 `autoRun` 这一个入口 ——
 * 有人改写成 `useEffect(() => aiAssist(...))` 就绕过去了。
 * 这里直接用 CDP 打开 **Network 域**，数 `/api/ai/assist` 的真实请求次数，
 * 是最贴近用户感受的判据。
 *
 * 本项目的推理型模型每次先烧 1800~3200 token 思维链，误触发一次代价很高，
 * 所以这条回归值得单独守住。
 *
 * 用法：node scripts/visual-check-market.mjs http://127.0.0.1:8787/market <token> [截图目录]
 * 退出码 0 = 全部通过。
 */
import { spawn } from 'node:child_process'
import { existsSync, mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

import { resolveDebugPort } from './cdp-port.mjs'

const [, , URL_ARG, TOKEN, OUTDIR = 'node_modules/.cache/qd-visual'] = process.argv
if (!URL_ARG || !TOKEN) {
  console.error('用法: node scripts/visual-check-market.mjs <url> <token> [截图目录]')
  process.exit(2)
}

const DEBUG_PORT = await resolveDebugPort()
const CDP_BASE = `http://127.0.0.1:${DEBUG_PORT}`
const PROFILE = join(process.cwd(), 'node_modules/.cache/qd-visual-profile-market')
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

const CHROME_CANDIDATES = [
  process.env.QD_CHROME,
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
].filter(Boolean)
const chromePath = CHROME_CANDIDATES.find((p) => existsSync(p))
if (!chromePath) {
  console.error('找不到 Chrome/Edge，可用 QD_CHROME 指定可执行文件路径')
  process.exit(2)
}

const results = []
const check = (ok, label, detail = '') => {
  results.push(ok)
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}${!ok && detail ? `  ← ${detail}` : ''}`)
}
mkdirSync(OUTDIR, { recursive: true })

const chrome = spawn(
  chromePath,
  [
    '--headless=new',
    `--remote-debugging-port=${DEBUG_PORT}`,
    `--user-data-dir=${PROFILE}`,
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-gpu',
    '--hide-scrollbars',
    '--window-size=1680,1200',
    'about:blank',
  ],
  { stdio: 'ignore' },
)

let ws
try {
  let target
  for (let i = 0; i < 40 && !target; i++) {
    await sleep(500)
    try {
      target = (await (await fetch(`${CDP_BASE}/json/list`)).json()).find((t) => t.type === 'page')
    } catch {
      /* 还没起来 */
    }
  }
  if (!target) throw new Error('Chrome 调试端口未就绪')

  ws = new WebSocket(target.webSocketDebuggerUrl)
  await new Promise((res, rej) => {
    ws.addEventListener('open', res, { once: true })
    ws.addEventListener('error', rej, { once: true })
  })

  let msgId = 0
  const pending = new Map()
  let aiCalls = 0
  const consoleErrors = []
  ws.addEventListener('message', (ev) => {
    const m = JSON.parse(ev.data)
    if (m.id && pending.has(m.id)) {
      const { resolve, reject } = pending.get(m.id)
      pending.delete(m.id)
      m.error ? reject(new Error(JSON.stringify(m.error))) : resolve(m.result)
    } else if (m.method === 'Network.requestWillBeSent') {
      if ((m.params?.request?.url || '').includes('/ai/assist')) aiCalls += 1
    } else if (m.method === 'Runtime.exceptionThrown') {
      consoleErrors.push(m.params.exceptionDetails?.exception?.description || m.params.exceptionDetails?.text)
    } else if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') {
      consoleErrors.push(m.params.args.map((a) => a.value ?? a.description ?? '').join(' '))
    }
  })
  const cdp = (method, params = {}) =>
    new Promise((resolve, reject) => {
      const i = ++msgId
      pending.set(i, { resolve, reject })
      ws.send(JSON.stringify({ id: i, method, params }))
      setTimeout(() => {
        if (pending.has(i)) {
          pending.delete(i)
          reject(new Error(`CDP 超时: ${method}`))
        }
      }, 40000)
    })
  const evalJs = async (expr) => {
    const r = await cdp('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true })
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text)
    return r.result.value
  }
  const shot = async (name) =>
    writeFileSync(join(OUTDIR, name), Buffer.from((await cdp('Page.captureScreenshot', { format: 'png' })).data, 'base64'))

  await cdp('Page.enable')
  await cdp('Runtime.enable')
  await cdp('Network.enable')
  // 关缓存：`npm run build` 会换 chunk 哈希，持久化 profile 缓存的旧 index.html
  // 会去动态 import **已删除的旧 chunk** → 404 → 白屏（表现为「先跑通过、rebuild 后再跑就红」）。
  await cdp('Network.setCacheDisabled', { cacheDisabled: true })

  // ---- 注入登录态（轮询到同源可写为止，别用固定 sleep）----
  const ORIGIN = new URL(URL_ARG).origin
  await cdp('Page.navigate', { url: new URL('/login', URL_ARG).href })
  let injected = false
  for (let i = 0; i < 25 && !injected; i++) {
    await sleep(600)
    try {
      injected =
        (await evalJs(`(() => {
          if (location.origin !== ${JSON.stringify(ORIGIN)}) return 'pending';
          try {
            localStorage.clear();
            localStorage.setItem('qd_token', ${JSON.stringify(TOKEN)});
            localStorage.setItem('qd_user', 'trader');
            return 'ok';
          } catch (e) { return 'denied'; }
        })()`)) === 'ok'
    } catch {
      /* 页面未就绪 */
    }
  }
  check(injected, '注入登录态成功（localStorage 可写）')

  // ⚠️ 「空态提示消失」**不等于**「出结果了」—— 加载态同样没有空态提示。
  //    只用 hasEmptyHint 判定，会在「AI 正在分析当前页面的数据…」时误判为已完成
  //    （我第一版就是这样，截图里截到的是 loading，断言却是 PASS）。
  //    真正的信号：按钮文案从 label（生成快评）变成「重新生成」。
  const cardState = () =>
    evalJs(`(() => {
      const t = document.body.innerText || '';
      return JSON.stringify({
        hasCard: t.includes('AI 个股快评'),
        hasEmptyHint: t.includes('点击上方「生成快评」按钮'),
        loading: t.includes('AI 正在分析当前页面的数据'),
        hasResult: t.includes('重新生成'),
        isLLM: t.includes('LLM') && !t.includes('本地规则'),
      });
    })()`)

  // AI 卡片在首屏之下，截图前先滚过去 —— 否则交付的截图里根本看不到卡片，
  // 断言虽然读的是 body.innerText（含屏外文字）能过，但人看截图会以为没验证。
  // 返回卡片滚动后的 rect，用来断言「真的进了视口」，而不是盲信 scrollIntoView。
  //
  // ⚠️ 两个踩过的坑：
  //   ① 只查 `div` 会**完全找不到卡片** —— 本项目 `Card` 渲染的是 `<section class="card">`。
  //      于是最内层的「div 且含该文案且有按钮」命中的是右栏容器 `div.space-y-5`（高 1525），
  //      它本来就跨屏 → 断言一度「通过」而截图毫无变化。**取元素前先确认真实标签名。**
  //   ② 别用 `filter(...).pop()` 取最外层：整页容器也含该文案，且恒覆盖视口 → 永远假通过。
  const scrollToCard = () =>
    evalJs(`(() => {
      const el = [...document.querySelectorAll('section.card')]
        .find(s => (s.innerText || '').includes('AI 个股快评') && s.querySelector('button'));
      if (!el) return JSON.stringify({ ok: false, why: 'no-card' });
      el.scrollIntoView({ block: 'center' });
      const r = el.getBoundingClientRect();
      // ⚠️ 不能要求「整张卡片都在视口内」：出结果后卡片高 1132px > 视口 1104px，
      //    永远不可能满足。截图取证只需要**卡片顶部进入视口上半屏**。
      return JSON.stringify({
        ok: r.top >= 0 && r.top < window.innerHeight / 2 && r.bottom > 0,
        top: Math.round(r.top), bottom: Math.round(r.bottom), vh: window.innerHeight,
        h: Math.round(r.height),
      });
    })()`)

  // ---- 1. 打开页面：不得自动跑 AI ----
  aiCalls = 0
  await cdp('Page.navigate', { url: URL_ARG })
  await sleep(12000)
  const opened = JSON.parse(await cardState())
  check(opened.hasCard, '行情页渲染出「AI 个股快评」卡片')
  check(aiCalls === 0, '打开页面不会自动调用 AI', `ai/assist 调用 ${aiCalls} 次`)
  check(opened.hasEmptyHint && !opened.loading && !opened.hasResult,
        '卡片停在空态（提示手动点击），未在加载、也没有旧结果',
        `emptyHint=${opened.hasEmptyHint} loading=${opened.loading} hasResult=${opened.hasResult}`)
  const cardShot = async (name) => {
    const r = JSON.parse(await scrollToCard())
    check(!!r.ok, `AI 卡片已滚入视口（顶部可见）后再截图（${name}）`,
          `top=${r.top} bottom=${r.bottom} vh=${r.vh} h=${r.h} ${r.why || ''}`)
    await shot(name)
  }
  await cardShot('market-open.png')

  // ---- 2. 刷新页面：同样不得自动跑 ----
  aiCalls = 0
  await cdp('Page.reload')
  await sleep(11000)
  check(aiCalls === 0, '刷新页面不会自动调用 AI', `ai/assist 调用 ${aiCalls} 次`)
  const reloaded = JSON.parse(await cardState())
  check(reloaded.hasEmptyHint && !reloaded.loading && !reloaded.hasResult,
        '刷新后卡片回到空态（没有残留结论）',
        `emptyHint=${reloaded.hasEmptyHint} hasResult=${reloaded.hasResult}`)

  // ---- 3. 点按钮 → 必须真的调用（证明只是「不自动」，不是「坏了」）----
  aiCalls = 0
  const clicked = await evalJs(`(() => {
    const b = [...document.querySelectorAll('button')].find(x => x.innerText.includes('生成快评'));
    if (!b) return 'no-button';
    b.click(); return 'ok';
  })()`)
  check(clicked === 'ok', '能点到「生成快评」按钮', clicked)
  await sleep(3000)
  check(aiCalls === 1, '点按钮后确实发起 1 次 AI 调用', `ai/assist 调用 ${aiCalls} 次`)

  // ---- 4. 等结果落地（推理型模型可能几十秒）----
  let final = null
  for (let i = 0; i < 60; i++) {
    await sleep(2500)
    const s = JSON.parse(await cardState())
    if (s.hasResult && !s.loading) { final = s; break }
  }
  check(!!final, 'AI 结果成功渲染（按钮变为「重新生成」且已退出加载态）',
        final ? '' : '等了 150s 仍未出结果')
  if (final) check(!final.hasEmptyHint, '出结果后空态提示消失')
  // ⚠️ 出结果后 actions 会变宽（徽章 + 复制 + 重新生成），在窄栏里会把标题/副标题
  //    挤成 0 宽 → 副标题「每行一个字」竖着排。这是真实出现过的布局缺陷，
  //    根因是 `.card-hd` 没有 flex-wrap（右侧 shrink-0 不可压缩，左侧 min-w-0 可压到 0）。
  const hdr = JSON.parse(await evalJs(`(() => {
    const el = [...document.querySelectorAll('section.card')]
      .find(s => (s.innerText || '').includes('AI 个股快评') && s.querySelector('button'));
    const left = el && el.querySelector('header > div');
    if (!left) return JSON.stringify({ w: -1 });
    return JSON.stringify({ w: Math.round(left.getBoundingClientRect().width) });
  })()`))
  check(hdr.w >= 120, '出结果后卡片标题栏未被按钮挤成窄条（副标题不会一字一行）',
        `标题栏宽 ${hdr.w}px（期望 ≥120）`)
  await cardShot('market-result.png')

  // ---- 5. 切换标的：不得自动重跑，且**旧结果必须被清掉** ----
  // 不清掉的话，切到 MSFT 还挂着 SPY 的结论 —— 比空白更误导。
  //
  // ⚠️ 选择器踩过两次坑，别改回去：
  //    ① 锚文本曾是「重点关注池」，该卡片 2026-09-29 已改名为「我的收藏」→ 断言恒失败
  //       （失败信息是 no-watchlist-card，看着像"卡片没渲染"，其实只是文案变了）。
  //       现在锚定**副标题里的「收藏池」**（页面渲染文本中唯一）。
  //    ② `Card` 渲染的是 `<section class="card">`，**不是 `div`** —— 用
  //       `querySelectorAll('div')` 会假通过/假失败。统一走 `section.card`。
  //    ③ 仍须「含锚文本 **且** 真的含 tbody tr」，否则会取到只有标题、没有表格的那一层。
  aiCalls = 0
  const switched = await evalJs(`(() => {
    const card = [...document.querySelectorAll('section.card')]
      .find(s => (s.innerText || '').includes('收藏池') && s.querySelector('tbody tr'));
    if (!card) return 'no-watchlist-card';
    const trs = [...card.querySelectorAll('tbody tr')];
    if (!trs.length) return 'no-watchlist-row';
    // 当前标的一直显示在搜索框右下角的小徽章上（span 带 bg-brand-50）。
    // 用 className.includes 而不是选择器，避免在模板字符串里转义 text-[10px]。
    const badge = [...document.querySelectorAll('span')].find(s => {
      const cls = String(s.className || '');
      return cls.includes('brand-50') && /^[A-Z^][A-Z0-9.]{0,5}$/.test(s.textContent.trim());
    });
    const cur = badge ? badge.textContent.trim() : '';
    const row = trs.find(tr => tr.innerText.trim().split(/\\s+/)[0] !== cur);
    if (!row) return 'no-other-symbol';
    const next = row.innerText.trim().split(/\\s+/)[0];
    row.click();
    return 'ok:' + cur + '->' + next;
  })()`)
  if (switched.startsWith('ok:')) {
    await sleep(4000)
    const after = JSON.parse(await cardState())
    const nowSym = await evalJs(`(() => {
      const b = [...document.querySelectorAll('span')].find(s => {
        const cls = String(s.className || '');
        return cls.includes('brand-50') && /^[A-Z^][A-Z0-9.]{0,5}$/.test(s.textContent.trim());
      });
      return b ? b.textContent.trim() : '';
    })()`)
    check(nowSym === switched.slice(3).split('->')[1], `点击收藏池真的切了标的（${switched.slice(3)}）`, `当前=${nowSym}`)
    check(aiCalls === 0, '切换标的不会自动重跑 AI', `ai/assist 调用 ${aiCalls} 次`)
    check(after.hasEmptyHint && !after.loading && !after.hasResult,
          '切换标的后旧结果已清空（不留上一只的结论）',
          `emptyHint=${after.hasEmptyHint} loading=${after.loading} hasResult=${after.hasResult}`)
  } else {
    check(false, '能在收藏池里切换标的（用于验证切换行为）', switched)
  }
  await cardShot('market-switch.png')

  check(consoleErrors.length === 0, '浏览器控制台无报错', consoleErrors.slice(0, 2).join(' | '))
} catch (err) {
  check(false, '脚本执行异常', String(err && err.message ? err.message : err))
} finally {
  try {
    ws?.close()
  } catch {
    /* noop */
  }
  chrome.kill()
}

const failed = results.filter((r) => !r).length
console.log('\n' + '='.repeat(58))
console.log(`  行情页 AI 手动触发回归：${results.length - failed}/${results.length} 项通过`)
console.log('='.repeat(58))
process.exit(failed ? 1 : 0)
