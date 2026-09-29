/**
 * 组合优化真实浏览器回归（可选，需要服务已启动）
 * ==============================================
 * `test:render` 只能证明「不白屏 + 文案进了 DOM」，它**看不见**：
 *   - 悬浮解释气泡是否真的弹出、有没有被祖先的 overflow 裁掉；
 *   - 新手模式开关切过去以后，高级设置是否真的从「折叠」变成「平铺」；
 *   - 一键推荐配置点下去，表单是否真的被填上（而不是只弹个 toast）；
 *   - 真的跑一次优化之后，结论卡片是否按「人话」渲染（而不是甩一堆指标）。
 *
 * 这几件事恰好就是本次改版（2026-09-29 小白友好化）的全部卖点，
 * 所以必须用真实 Chrome 验一遍，否则等于没做。
 *
 * 用法：
 *   1) 先启动服务：cd backend && .venv/Scripts/python.exe run.py
 *   2) 登录拿 token：
 *        curl -s -X POST http://127.0.0.1:8787/api/auth/login \
 *          -H "Content-Type: application/json" \
 *          -d '{"username":"trader","password":"QuantDesk#2026"}'
 *   3) node scripts/visual-check-optimize.mjs http://127.0.0.1:8787/optimize <token> [截图目录]
 *
 * 退出码 0 = 全部通过。
 */
import { spawn } from 'node:child_process'
import { existsSync, mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

import { resolveDebugPort } from './cdp-port.mjs'

const [, , URL_ARG, TOKEN, OUTDIR = 'node_modules/.cache/qd-visual'] = process.argv
if (!URL_ARG || !TOKEN) {
  console.error('用法: node scripts/visual-check-optimize.mjs <url> <token> [截图目录]')
  process.exit(2)
}

// ⚠️ 端口绝不能写死：本机保留段含 9120–9219 / 9320–9419，写死会让脚本静默失效
const DEBUG_PORT = await resolveDebugPort()
const CDP_BASE = `http://127.0.0.1:${DEBUG_PORT}`
const PROFILE = join(process.cwd(), 'node_modules/.cache/qd-visual-profile-optimize')
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
try {
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
  const pageErrors = []
  ws.addEventListener('message', (ev) => {
    const m = JSON.parse(ev.data)
    if (m.id && pending.has(m.id)) {
      const { resolve, reject } = pending.get(m.id)
      pending.delete(m.id)
      m.error ? reject(new Error(JSON.stringify(m.error))) : resolve(m.result)
    } else if (m.method === 'Runtime.exceptionThrown') {
      pageErrors.push(m.params.exceptionDetails?.exception?.description || m.params.exceptionDetails?.text)
    } else if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') {
      pageErrors.push(m.params.args.map((a) => a.value ?? a.description ?? '').join(' '))
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
      }, 60000)
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
  /** 把鼠标移到某个选择器的元素中心（触发 React 的 onMouseEnter）。 */
  const hover = async (selector, nth = 0) => {
    const box = await evalJs(`(() => {
      const els = document.querySelectorAll(${JSON.stringify(selector)});
      const el = els[${nth}];
      if (!el) return null;
      el.scrollIntoView({ block: 'center' });
      const r = el.getBoundingClientRect();
      return JSON.stringify({ x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2) });
    })()`)
    if (!box) return false
    const { x, y } = JSON.parse(box)
    await cdp('Input.dispatchMouseEvent', { type: 'mouseMoved', x, y, buttons: 0 })
    await sleep(400)
    return true
  }
  /** 点按钮（用 DOM 上的 click()，比坐标点击稳）。 */
  const clickByText = async (sel, text) => {
    const ok = await evalJs(`(() => {
      const el = [...document.querySelectorAll(${JSON.stringify(sel)})].find(e => e.innerText.trim().includes(${JSON.stringify(text)}));
      if (!el) return false;
      el.click();
      return true;
    })()`)
    await sleep(400)
    return ok
  }
  /** 读某个 Field 下的输入框值（按 label 文本定位）。 */
  const readField = (labelText) =>
    evalJs(`(() => {
      const lab = [...document.querySelectorAll('label.lbl')].find(l => l.textContent.includes(${JSON.stringify(labelText)}));
      if (!lab || !lab.parentElement) return null;
      const inp = lab.parentElement.querySelector('input');
      return inp ? inp.value : null;
    })()`)
  /** 某个 Chip 是否处于选中态（选中 = brand 边框）。 */
  const chipActive = (text) =>
    evalJs(`(() => {
      const b = [...document.querySelectorAll('button')].find(e => e.innerText.trim() === ${JSON.stringify(text)});
      return !!b && String(b.className).includes('border-brand-300');
    })()`)

  await cdp('Page.enable')
  await cdp('Runtime.enable')
  // 关缓存：`npm run build` 会换 chunk 哈希，持久化 profile 缓存的旧 index.html
  // 会去动态 import **已删除的旧 chunk** → 404 → 白屏（表现为「先跑通过、rebuild 后再跑就红」）。
  await cdp('Network.enable')
  await cdp('Network.setCacheDisabled', { cacheDisabled: true })

  // ---- 注入登录态（localStorage 需要同源）----
  const ORIGIN = new URL(URL_ARG).origin
  await cdp('Page.navigate', { url: new URL('/login', URL_ARG).href })
  let injected = false
  for (let i = 0; i < 25 && !injected; i++) {
    await sleep(600)
    try {
      injected =
        (await evalJs(`(() => {
          if (location.origin !== ${JSON.stringify(ORIGIN)}) return false;
          try {
            localStorage.clear();
            localStorage.setItem('qd_token', ${JSON.stringify(TOKEN)});
            localStorage.setItem('qd_user', 'trader');
            return true;
          } catch (e) { return false; }
        })()`)) === true
    } catch {
      /* 页面还没就绪 → 重试 */
    }
  }
  check(injected, '注入登录态成功（localStorage 可写）')

  // ---- 进入优化页 ----
  await cdp('Page.navigate', { url: URL_ARG })
  await sleep(2000)
  // 等 /optimize/meta 回来（目标下拉/chips 就绪）
  let ready = false
  for (let i = 0; i < 20 && !ready; i++) {
    ready = await evalJs(`document.body.innerText.includes('最大夏普')`)
    if (!ready) await sleep(800)
  }
  check(ready, '优化页加载出后端元信息（目标选项已渲染）')

  const body = await evalJs('document.body.innerText')

  // ---- 1. 四步向导骨架 ----
  for (const t of ['放哪些标的', '想要什么效果', '用多长历史', '限制条件', '开始优化']) {
    check(body.includes(t), `页面上出现「${t}」`)
  }
  check(body.includes('第一次用？照这个顺序来'), '空态给出「照这个顺序来」的上手引导')
  check(body.includes('还没算过权重'), '空态标题是「还没算过权重」而不是专业术语')
  // 用「按钮是否存在」判定新手模式，而不是搜文案（空态引导语里也提到过这个按钮名）
  const recBtnOn = await evalJs(
    `[...document.querySelectorAll('button')].some(b => b.innerText.trim() === '一键填入推荐配置')`,
  )
  check(recBtnOn, '新手模式默认开启（「一键填入推荐配置」按钮可见）')

  // ---- 2. 新手模式下高级项是折叠的，且真的在 DOM 里（没被删功能）----
  // ⚠️ 必须用 `textContent` 而不是 `innerText`：`innerText` 会**排除折叠 `<details>`
  //    里的内容**，用它验「折叠区里的字段还在不在」必然假失败（实测踩过）。
  const advanced = JSON.parse(
    await evalJs(`JSON.stringify({
      details: document.querySelectorAll('details').length,
      hasCov: document.body.textContent.includes('协方差估计'),
      hasCluster: document.body.textContent.includes('单簇上限'),
      hasBudget: document.body.textContent.includes('启用风险预算'),
      hasFrontier: document.body.textContent.includes('计算有效前沿'),
    })`),
  )
  check(advanced.details >= 1, '新手模式下存在折叠区（details ≥ 1）', `details=${advanced.details}`)
  check(
    advanced.hasCov && advanced.hasCluster && advanced.hasBudget && advanced.hasFrontier,
    '高级项仍然在 DOM 里（只是折叠）—— 功能没有被删掉',
    JSON.stringify(advanced),
  )

  const p1 = await shot('opt-01-beginner.png')
  console.log(`      截图：${p1}`)

  // ---- 3. 悬浮解释：这是用户这次的核心诉求，必须真的弹出 ----
  const hovered = await hover('[aria-label="标的池 说明"]')
  check(hovered, '找到「标的池」的悬浮触发器')
  const tip = await evalJs(`(() => {
    const el = document.querySelector('[role="tooltip"]');
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return JSON.stringify({
      text: el.innerText,
      inside: r.left >= 0 && r.top >= 0 && r.right <= innerWidth + 1 && r.bottom <= innerHeight + 1,
      w: Math.round(r.width),
    });
  })()`)
  check(!!tip, '鼠标悬停后弹出解释气泡')
  if (tip) {
    const t = JSON.parse(tip)
    check(t.text.includes('是什么') && t.text.includes('怎么看'), '气泡含「是什么 / 怎么看」两段')
    check(/一篮子|组合/.test(t.text), '气泡正文是「人话」解释（不是专业定义）', t.text.slice(0, 60))
    // ⚠️ 卡片祖先有 overflow 时气泡会被裁掉 —— 这是必须守住的回归点
    check(t.inside, '气泡没有被祖先的 overflow 裁掉（完整落在视口内）', `w=${t.w}`)
    const p2 = await shot('opt-02-tooltip.png')
    console.log(`      截图：${p2}`)
  }
  // 移开鼠标后气泡应消失
  await cdp('Input.dispatchMouseEvent', { type: 'mouseMoved', x: 5, y: 5, buttons: 0 })
  await sleep(400)
  check(!(await evalJs(`!!document.querySelector('[role="tooltip"]')`)), '鼠标移开后气泡自动收起')

  // ---- 4. 行内术语（虚线下划线文字）也能悬停 ----
  // 目标是「本次要做什么」预览里的「等权基准」—— 这一页的判断核心就是它，
  // 所以必须是可悬停的行内解释，而不是只有问号图标。
  const inlineTip = await evalJs(`(() => {
    return [...document.querySelectorAll('span')].filter(
      e => String(e.className).includes('border-dotted') && e.innerText.trim() === '等权基准',
    ).length;
  })()`)
  check(inlineTip > 0, '人话预览里的行内术语（等权基准）挂了悬浮解释')

  // ---- 5. 一键推荐配置真的填进了表单 ----
  const applied = await clickByText('button', '一键填入推荐配置')
  check(applied, '点击「一键填入推荐配置」')
  await sleep(600)
  // ⚠️ 不能用 `input[type=number]` 的第一个：上限/总仓位也是 number 输入，
  //    而且折叠区里的输入框**也存在于 DOM**，会抢到选择器。按 Field 的 label 文本定位。
  const symbolsVal = await readField('标的池')
  check(
    typeof symbolsVal === 'string' && symbolsVal.split(',').length >= 4 && symbolsVal.includes('SPY'),
    '推荐配置把标的池填成了一篮子（含 SPY）',
    String(symbolsVal),
  )
  const activeFive = await chipActive('近 5 年')
  check(activeFive, '推荐配置把历史区间切到「近 5 年」')
  const activeSharpe = await chipActive('最大夏普')
  check(activeSharpe, '推荐配置把优化目标切到「最大夏普」')
  const summary = await evalJs(
    `(document.body.innerText.match(/本次要做什么[\\s\\S]{0,260}/) || [''])[0]`,
  )
  check(summary.includes('等权基准'), '「本次要做什么」用人话复述了配置，并点明要和等权基准比', summary.slice(0, 100))
  check(/最多占\s*35%/.test(summary) || summary.includes('35%'), '人话预览里说明了单标的上限')
  const p3 = await shot('opt-03-applied.png')
  console.log(`      截图：${p3}`)

  // ---- 6. 关掉新手模式 → 高级项平铺（不是消失）----
  const switched = await evalJs(`(() => {
    const sw = document.querySelector('[role="switch"]');
    if (!sw) return false;
    sw.click();
    return true;
  })()`)
  check(switched, '点击「新手模式」开关')
  await sleep(600)
  const pro = JSON.parse(
    await evalJs(`JSON.stringify({
      details: document.querySelectorAll('details').length,
      hasCov: document.body.textContent.includes('协方差估计'),
      // ⚠️ 不能用 body.innerText 搜文案：空态引导语里也写着「一键填入推荐配置」，
      //    那样断言永远为真、永远不报错。必须直接问「按钮还在不在」。
      hasRecBtn: [...document.querySelectorAll('button')].some(b => b.innerText.trim() === '一键填入推荐配置'),
    })`),
  )
  check(pro.details === 0, '关掉新手模式后所有高级项平铺展示（无折叠）', `details=${pro.details}`)
  check(pro.hasCov, '专业模式下协方差估计等高级项仍然在')
  check(!pro.hasRecBtn, '专业模式下不再显示「一键填入推荐配置」')
  const p4 = await shot('opt-04-pro.png')
  console.log(`      截图：${p4}`)

  // 切回新手模式，让后面跑的是小白会看到的形态
  await evalJs(`(() => { const sw = document.querySelector('[role="switch"]'); if (sw) sw.click(); })()`)
  await sleep(500)

  // ---- 7. 真跑一次优化 → 结论卡片 ----
  // 这一块只在**有结果时**才渲染，SSR 断言覆盖不到，必须在这里验。
  // 用推荐配置（6 只 ETF / 近 5 年），本机有本地历史库时很快；网络源则可能慢一些。
  const started = await clickByText('button', '开始优化')
  check(started, '点击「开始优化」')
  let hasResult = false
  for (let i = 0; i < 60 && !hasResult; i++) {
    await sleep(1000)
    hasResult = await evalJs(`document.body.textContent.includes('这次优化到底怎么样')`)
    // 出错就早点退出，不必空等
    const failed = await evalJs(`document.body.innerText.includes('优化失败')`)
    if (failed) break
  }
  check(hasResult, '跑完优化后渲染出「这次优化到底怎么样」（人话结论卡片）')

  if (hasResult) {
    const card = await evalJs(`(() => {
      const c = [...document.querySelectorAll('section.card')].find(s => s.textContent.includes('这次优化到底怎么样'));
      return c ? c.innerText : '';
    })()`)
    check(/一句话结论/.test(card), '结论卡片里有「一句话结论」', card.slice(0, 60))
    check(/等权基准/.test(card), '结论里用「等权基准」说明对比对象（不用「基准标的」）')
    check(!/基准标的/.test(card), '结论里不出现「基准标的」这种让人看不懂的说法')
    check(/夏普/.test(card), '结论里用夏普比率做对比', card.slice(0, 140))
    // 缺数据时不能编造「等权 0.00」这种数字
    check(!/等权基准是\s*0\.00\s*（/.test(card), '结论没有编造「等权 0.00」的假数字', card.slice(0, 160))

    await evalJs(`(() => {
      const c = [...document.querySelectorAll('section.card')].find(s => s.textContent.includes('这次优化到底怎么样'));
      if (c) c.scrollIntoView({ block: 'start' });
    })()`)
    await sleep(500)
    const p5 = await shot('opt-05-result-summary.png')
    console.log(`      截图：${p5}`)

    // 指标名悬停 → 弹出「是什么 / 怎么看」
    const hoveredMetric = await evalJs(`(() => {
      const el = [...document.querySelectorAll('span')].find(
        e => String(e.className).includes('border-dotted') && e.innerText.trim() === '目标权重',
      );
      if (!el) return false;
      el.scrollIntoView({ block: 'center' });
      const r = el.getBoundingClientRect();
      window.__qdOptTip = { x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2) };
      return true;
    })()`)
    check(hoveredMetric, '权重表里的「目标权重」挂了悬浮解释')
    if (hoveredMetric) {
      const pt = await evalJs('JSON.stringify(window.__qdOptTip)')
      const { x, y } = JSON.parse(pt)
      await cdp('Input.dispatchMouseEvent', { type: 'mouseMoved', x, y, buttons: 0 })
      await sleep(450)
      const mt = await evalJs(`(() => {
        const el = document.querySelector('[role="tooltip"]');
        if (!el) return null;
        const r = el.getBoundingClientRect();
        return JSON.stringify({
          text: el.innerText,
          inside: r.left >= 0 && r.top >= 0 && r.right <= innerWidth + 1 && r.bottom <= innerHeight + 1,
        });
      })()`)
      check(!!mt, '悬停指标名后弹出解释气泡')
      if (mt) {
        const t = JSON.parse(mt)
        check(/仓位|占多少/.test(t.text), '「目标权重」的解释是「人话」', t.text.slice(0, 60))
        check(t.inside, '指标解释气泡没有被表格的 overflow 裁掉')
      }
    }

    // 三个结果 tab 都要能切（组件拆分后未断链）
    for (const [tabName, marker] of [
      ['有效前沿', '最大夏普射线'],
      ['相关性', '蓝色为同向'],
      ['备注', '本轮参数'],
    ]) {
      const ok = await clickByText('button', tabName)
      await sleep(500)
      const shown = await evalJs(`document.body.textContent.includes(${JSON.stringify(marker)})`)
      check(ok && shown, `「${tabName}」tab 能正常切换渲染`)
    }
    const p6 = await shot('opt-06-result.png')
    console.log(`      截图：${p6}`)
  }

  // ---- 8. 页面没有运行期报错 ----
  const realErrors = pageErrors.filter((e) => e && !/useLayoutEffect|ResizeObserver loop/.test(e))
  check(realErrors.length === 0, '页面无运行期 JS 报错', realErrors.slice(0, 2).join(' | '))
} catch (e) {
  check(false, '脚本执行完成', String(e && e.message).slice(0, 300))
} finally {
  try {
    if (ws) ws.close()
  } catch {
    /* ignore */
  }
  chrome.kill()
}

const failed = results.filter((r) => !r).length
console.log(`\n${'='.repeat(58)}`)
console.log(`  组合优化视觉回归：${results.length - failed}/${results.length} 项通过`)
if (failed) {
  console.log(`  失败 ${failed} 项`)
}
console.log('='.repeat(58))
process.exit(failed ? 1 : 0)
