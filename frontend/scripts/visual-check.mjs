/**
 * 真实浏览器视觉回归（可选，需要服务已启动）
 * ==========================================
 * `test:render`（render-check.mjs）用 `renderToString` 只能证明「不白屏 + 文案进了 DOM」，
 * 它**看不见**布局：控件宽度被 CSS 吃掉、tooltip 被 `overflow` 裁掉、颜色分档不对、
 * 交互点不动 —— 这些它一律测不出来。
 *
 * 本项目曾因此被用户直接指出「前端没有做好」：只跑 SSR 不等于做完了。
 * 本脚本用 CDP（Chrome DevTools Protocol）驱动**真实 Chrome**，把这类问题变成断言。
 *
 * 零依赖：Node 22 自带全局 WebSocket，不需要 playwright / puppeteer。
 * 只需本机装了 Chrome（默认路径见 CHROME_CANDIDATES，可用 QD_CHROME 覆盖）。
 *
 * 用法：
 *   1) 先启动服务：  cd backend && .venv/Scripts/python.exe run.py
 *   2) 登录拿 token： curl -s -X POST http://127.0.0.1:8787/api/auth/login \
 *        -H "Content-Type: application/json" \
 *        -d '{"username":"trader","password":"QuantDesk#2026"}' | jq -r .access_token
 *   3) 运行：  node scripts/visual-check.mjs http://127.0.0.1:8787/rankings <token> [截图目录]
 *
 * 退出码 0 = 全部通过。
 */
import { spawn } from 'node:child_process'
import { existsSync, mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

import { resolveDebugPort } from './cdp-port.mjs'

const [, , URL_ARG, TOKEN, OUTDIR = 'node_modules/.cache/qd-visual'] = process.argv
if (!URL_ARG || !TOKEN) {
  console.error('用法: node scripts/visual-check.mjs <url> <token> [截图目录]')
  process.exit(2)
}

const DEBUG_PORT = await resolveDebugPort()
const CDP_BASE = `http://127.0.0.1:${DEBUG_PORT}`
const PROFILE = join(process.cwd(), 'node_modules/.cache/qd-visual-profile')
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
    '--window-size=1680,1400',
    'about:blank',
  ],
  { stdio: 'ignore', detached: false },
)

let ws
let cdp
try {
  // ---- 等调试端口就绪 ----
  let target
  for (let i = 0; i < 40 && !target; i++) {
    await sleep(500)
    try {
      const list = await (await fetch(`${CDP_BASE}/json/list`)).json()
      target = list.find((t) => t.type === 'page')
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
  const consoleErrors = []
  ws.addEventListener('message', (ev) => {
    const m = JSON.parse(ev.data)
    if (m.id && pending.has(m.id)) {
      const { resolve, reject } = pending.get(m.id)
      pending.delete(m.id)
      m.error ? reject(new Error(JSON.stringify(m.error))) : resolve(m.result)
    } else if (m.method === 'Runtime.exceptionThrown') {
      consoleErrors.push(m.params.exceptionDetails?.exception?.description || m.params.exceptionDetails?.text)
    } else if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') {
      consoleErrors.push(m.params.args.map((a) => a.value ?? a.description ?? '').join(' '))
    }
  })
  cdp = (method, params = {}) =>
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
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.text || 'eval 失败')
    return r.result.value
  }
  const shot = async (name) => {
    const s = await cdp('Page.captureScreenshot', { format: 'png' })
    const p = join(OUTDIR, name)
    writeFileSync(p, Buffer.from(s.data, 'base64'))
    return p
  }
  const waitRows = async (min = 4) => {
    for (let i = 0; i < 20; i++) {
      if ((await evalJs(`document.querySelectorAll('tbody tr').length`)) >= min) return true
      await sleep(1500)
    }
    return false
  }

  await cdp('Page.enable')
  await cdp('Runtime.enable')
  // ⚠️ 必须关缓存：本脚本用**持久化** Chrome profile（qd-visual-profile），
  //    而 `npm run build` 会先清空 dist/ 并给每个 chunk 换新哈希。
  //    若浏览器命中上次运行缓存的 index.html → 它引用的旧 entry chunk 又去动态 import
  //    **已被删除的旧 Rankings-*.js** → 404 → 路由白屏 → 断言看到空 body，
  //    然后 `find(...).click()` 在 undefined 上抛 Uncaught，整个脚本以看不懂的堆栈中止。
  //    实测：同一份代码「先跑通过、rebuild 后再跑就红」就是它。
  await cdp('Network.enable')
  await cdp('Network.setCacheDisabled', { cacheDisabled: true })

  // ---- 写 token（localStorage 需要**同源**）----
  // ⚠️ 固定 sleep 会偶发失败：SPA 还没起来时页面停在 about:blank，
  //    访问 localStorage 抛 SecurityError → 整个脚本以「Uncaught」中止。
  //    改为轮询「已到目标 origin 且能写 localStorage」。
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
      /* 页面还没就绪 → 重试 */
    }
  }
  check(injected, '注入登录态成功（localStorage 可写）')

  // ---- 1. 全部标的 ----
  await cdp('Page.navigate', { url: URL_ARG })
  await sleep(1500)
  check(await waitRows(), '榜单页渲染出行（数据已加载）')

  const info = JSON.parse(
    await evalJs(`JSON.stringify({
      rows: document.querySelectorAll('tbody tr').length,
      headers: [...document.querySelectorAll('thead th')].map(t=>t.innerText.trim()).filter(Boolean),
      hasPool: document.body.innerText.includes('候选观察池'),
      hasScore: document.body.innerText.includes('综合评分'),
      hasTechFilter: document.body.innerText.includes('技术面'),
      hasDisclaimer: document.body.innerText.includes('不是买入信号'),
    })`),
  )
  check(info.rows > 3, '榜单行数 > 3', `rows=${info.rows}`)
  check(info.headers.includes('综合评分'), '表头含「综合评分」', info.headers.join(','))
  check(info.hasPool && info.hasScore, '页面含候选观察池与综合评分入口')
  check(info.hasTechFilter, '页面含技术面筛选区')
  // 这一条是**诚实性守卫**：评分不能自称买入信号
  check(info.hasDisclaimer, '页面明示「不是买入信号」')

  // ---- 2. 列头悬浮说明真的弹出（portal + fixed 定位，易被 overflow 裁掉）----
  // ⚠️ 必须先 scrollIntoView 再量坐标：排行榜页在表格**之上**还有 5 个面板
  // （PremarketPanel / MoversMonitor / PickCenter / SmartScreen / RankingFilters），
  // 表头默认在首屏之外。CDP 的鼠标坐标是**视口坐标**，对着屏幕外的 y 派发鼠标事件
  // 什么都不会发生 → 本检查会变成一条**恒假失败**（真实踩过：面板增补后 silently 变红）。
  const pos = await evalJs(`(() => {
    const th = [...document.querySelectorAll('thead th')].find(t=>t.innerText.includes('综合评分'));
    if (!th) return null;
    th.scrollIntoView({ block: 'center' });
    return 'scrolled';
  })()`)
  if (pos) await sleep(600)
  const thPos = await evalJs(`(() => {
    const th = [...document.querySelectorAll('thead th')].find(t=>t.innerText.includes('综合评分'));
    if (!th) return null;
    const r = th.getBoundingClientRect();
    // 自检：量完必须真的落在视口内，否则后面的断言没有意义
    const inView = r.top >= 0 && r.bottom <= window.innerHeight && r.left >= 0 && r.right <= window.innerWidth;
    return JSON.stringify({x: Math.round(r.left+r.width/2), y: Math.round(r.top+r.height/2), inView});
  })()`)
  if (thPos) {
    const { x, y, inView } = JSON.parse(thPos)
    if (!inView) check(false, '表头已滚入视口（否则悬停断言无意义）', `y=${y}`)
    await cdp('Input.dispatchMouseEvent', { type: 'mouseMoved', x, y, buttons: 0 })
    await sleep(1000)
    const tip = JSON.parse(
      await evalJs(`(() => {
      const t = document.querySelector('[role="tooltip"]');
      if (!t) return JSON.stringify({ok:false});
      const r = t.getBoundingClientRect();
      // 全文都要读：免责声明在气泡末尾，只截前 120 字符会误判成「没写」
      return JSON.stringify({ok: r.width>0 && r.height>0, w: Math.round(r.width), text: t.innerText});
    })()`),
    )
    check(tip.ok, '悬停列头弹出指标说明气泡（且未被 overflow 裁掉）', JSON.stringify({ ok: tip.ok, w: tip.w }))
    check(!!tip.text && tip.text.includes('不是买入信号'), '综合评分气泡里带「不是买入信号」提示')
    await shot('01-tooltip.png')
  }

  // ---- 3. 控件宽度：.inp 是 @apply w-full 且位于 @tailwind utilities 之后，
  //         普通 w-* 会被吃掉 → 控件撑满整行、筛选面板塌掉。这条守卫专门盯它。----
  const wide = JSON.parse(
    await evalJs(`(() => {
    const bad = [];
    for (const el of document.querySelectorAll('input, select')) {
      const r = el.getBoundingClientRect();
      if (r.width > 900) bad.push({ tag: el.tagName, w: Math.round(r.width), ph: el.placeholder||'' });
    }
    return JSON.stringify(bad);
  })()`),
  )
  check(wide.length === 0, '筛选控件未被 .inp 的 w-full 吃掉宽度', JSON.stringify(wide))

  // ---- 4. 候选观察池：服务端过滤（不是在当前页本地筛）----
  await evalJs(`[...document.querySelectorAll('button')].find(x=>x.innerText.includes('候选观察池')).click(); 'ok'`)
  await sleep(4000)
  const pool = JSON.parse(
    await evalJs(`(() => {
    const ths=[...document.querySelectorAll('thead th')];
    const si=ths.findIndex(t=>t.innerText.includes('综合评分'));
    // 首列是「批量 AI 复核」用的勾选框（可挑选模式下才渲染）——评分列的期望位置随之右移一位。
    // 硬编码 si===1 会在加了勾选框后误报，故按是否出现勾选框动态判断。
    const hasCheckbox = !!ths[0]?.querySelector('input[type=checkbox]');
    const rows=[...document.querySelectorAll('tbody tr')];
    const sc=rows.map(tr=>parseFloat((tr.children[si]||{}).innerText)).filter(n=>!isNaN(n));
    return JSON.stringify({
      si, hasCheckbox, rows: rows.length,
      min: sc.length?Math.min(...sc):null, max: sc.length?Math.max(...sc):null,
      below: sc.filter(n=>n<70).length,
      notice: document.body.innerText.includes('筛选辅助'),
      sortByScore: /排序\\s*综合评分/.test(document.body.innerText),
    });
  })()`),
  )
  check(pool.si === (pool.hasCheckbox ? 2 : 1),
        `评分列位置正确（勾选框${pool.hasCheckbox ? '有' : '无'} → 期望第 ${pool.hasCheckbox ? 2 : 1} 列）`,
        `si=${pool.si} checkbox=${pool.hasCheckbox}`)
  check(pool.rows > 0, '候选池有标的', `rows=${pool.rows}`)
  // 关键：池内不应出现低于阈值的标的 —— 若为本地筛选，只会从当前页里挑，数字会不对
  check(pool.below === 0, `候选池内无低于阈值（70）的标的`, `min=${pool.min} below=${pool.below}`)
  check(pool.min != null && pool.min >= 70, '候选池最低分 ≥ 阈值', `min=${pool.min}`)
  check(pool.sortByScore, '进入候选池自动按评分排序')
  check(pool.notice, '候选池有「筛选辅助」说明')
  await shot('02-pool.png')

  // ---- 5. 评分设置面板 ----
  await evalJs(`[...document.querySelectorAll('button')].find(x=>x.innerText.includes('评分设置')).click(); 'ok'`)
  await sleep(1200)
  const settings = JSON.parse(
    await evalJs(`(() => {
    const rs=[...document.querySelectorAll('input[type=range]')];
    return JSON.stringify({
      ranges: rs.length,
      widths: rs.map(r=>Math.round(r.getBoundingClientRect().width)),
      threshold: (document.body.innerText.match(/≥ \\d+ 分/)||[''])[0],
    });
  })()`),
  )
  check(settings.ranges === 5, '评分设置含 1 个阈值滑杆 + 4 个维度滑杆', `ranges=${settings.ranges}`)
  check(settings.widths.every((w) => w > 40), '滑杆未被压成 0 宽度（布局未塌）', JSON.stringify(settings.widths))
  check(/≥ \d+ 分/.test(settings.threshold), '阈值文案正常显示', settings.threshold)
  await shot('03-settings.png')

  // ---- 6. AI 深度分析弹窗：必须相对**视口**定位 ----
  // 真实踩过（用户报「弹窗根本弹不出来，只有很小一块」）：多选工具条是
  // `sticky top-0 … backdrop-blur`，而 Modal 原本渲染在它的 DOM 子树里 ——
  // `backdrop-filter` 会让该祖先成为 `position: fixed` 的**包含块**，
  // 于是 `inset-0` 不再是视口，弹窗被压进那条工具栏（实测 y=715 而非视口顶部 48）。
  // 修法：Modal 用 createPortal 挂到 body。下面三条断言把「相对视口」钉住。
  await evalJs(`[...document.querySelectorAll('button')].find(x=>x.innerText.includes('评分设置'))?.click(); 'ok'`)
  await sleep(800)
  const picked1 = await evalJs(`(() => {
    const tr=[...document.querySelectorAll('tbody tr')].find(r=>r.querySelector('input[type=checkbox]'));
    if (!tr) return 'no-row';
    tr.querySelector('input[type=checkbox]').click(); return 'ok';
  })()`)
  check(picked1 === 'ok', '能勾选一行（用于 AI 深度分析）', picked1)
  await sleep(1200)
  const openedAi = await evalJs(`(() => {
    const b=[...document.querySelectorAll('button')].find(x=>x.innerText.includes('AI 深度分析'));
    if (!b) return 'no-button';
    b.click(); return 'ok';
  })()`)
  check(openedAi === 'ok', '勾选 1 只后出现「AI 深度分析」按钮', openedAi)
  await sleep(2500)
  const dlg = JSON.parse(
    await evalJs(`(() => {
    const d=document.querySelector('[role=dialog]');
    if (!d) return JSON.stringify({found:false});
    const r=d.getBoundingClientRect();
    return JSON.stringify({
      found:true, x:Math.round(r.x), y:Math.round(r.y),
      w:Math.round(r.width), h:Math.round(r.height), vw:innerWidth,
      // portal 到 body 后：overlay（[role=dialog] 的父节点）的直接父节点就是 body。
      // 注意 [role=dialog] 是**内层面板**，不是 overlay —— 别直接判 d.parentElement。
      parentIsBody: d.parentElement?.parentElement === document.body,
      hasContent: (d.innerText||'').includes('不构成买卖信号'),
    });
  })()`),
  )
  check(dlg.found, 'AI 深度分析弹窗已打开', JSON.stringify(dlg))
  check(dlg.found && dlg.parentIsBody, 'Modal 已 portal 到 body（脱离 backdrop-blur 祖先）',
        `parentIsBody=${dlg.parentIsBody}`)
  check(dlg.found && dlg.y < 200, '弹窗贴近视口顶部（未被祖先的 backdrop-filter 困住）', `y=${dlg.y}`)
  check(dlg.found && Math.abs(dlg.x + dlg.w / 2 - dlg.vw / 2) < 30, '弹窗水平居中于视口',
        `x=${dlg.x} w=${dlg.w} vw=${dlg.vw}`)
  check(dlg.found && dlg.w > 400, '弹窗宽度正常（不是被压成一条）', `w=${dlg.w}`)
  check(dlg.found && dlg.hasContent, '弹窗内常驻免责声明（AI 不是买卖信号）')
  await shot('04-ai-modal.png')

  // ---- 7. 公司档案弹窗：同一张表里的另一个全屏层，也必须相对视口 ----
  await evalJs(`[...document.querySelectorAll('button')].find(x=>x.innerText.trim()==='关闭')?.click(); 'ok'`)
  await sleep(900)
  const openedProfile = await evalJs(`(() => {
    const b=document.querySelector('tbody button[title="查看公司档案"]');
    if (!b) return 'no-symbol-button';
    b.click(); return 'ok';
  })()`)
  check(openedProfile === 'ok', '点击代码可打开公司档案弹窗', openedProfile)
  await sleep(3000)
  const pdlg = JSON.parse(
    await evalJs(`(() => {
    const d=document.querySelector('[role=dialog]');
    if (!d) return JSON.stringify({found:false});
    const r=d.getBoundingClientRect();
    return JSON.stringify({
      found:true, x:Math.round(r.x), y:Math.round(r.y), w:Math.round(r.width), vw:innerWidth,
      parentIsBody: d.parentElement?.parentElement === document.body,
    });
  })()`),
  )
  check(pdlg.found, '公司档案弹窗已打开', JSON.stringify(pdlg))
  check(pdlg.found && pdlg.y < 200, '公司档案弹窗贴近视口顶部（未被祖先困住）', `y=${pdlg.y}`)
  check(pdlg.found && Math.abs(pdlg.x + pdlg.w / 2 - pdlg.vw / 2) < 30, '公司档案弹窗水平居中',
        `x=${pdlg.x} w=${pdlg.w} vw=${pdlg.vw}`)
  await shot('05-profile.png')

  check(consoleErrors.length === 0, '浏览器控制台无报错', consoleErrors.slice(0, 3).join(' | '))
} finally {
  try {
    ws?.close()
  } catch {
    /* noop */
  }
  chrome.kill()
}

const passed = results.filter(Boolean).length
console.log(`\n${'='.repeat(58)}\n  视觉回归：${passed}/${results.length} 项通过`)
if (passed !== results.length) {
  console.log('  失败项：')
  for (const [i, ok] of results.entries()) if (!ok) console.log(`    - #${i + 1}`)
}
console.log(`  截图目录：${OUTDIR}\n${'='.repeat(58)}`)
process.exit(passed === results.length ? 0 : 1)
