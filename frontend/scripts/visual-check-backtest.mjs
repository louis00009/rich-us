/**
 * 回测中心真实浏览器回归（可选，需要服务已启动）
 * ==============================================
 * `test:render` 只能证明「不白屏 + 文案进了 DOM」，它**看不见**：
 *   - 悬浮解释气泡是否真的弹出（气泡正文只在 hover 时才进 DOM，SSR 断言不到）；
 *   - 气泡有没有被祖先的 `overflow` / 卡片边界裁掉；
 *   - 新手模式开关切过去以后，高级设置是否真的从「折叠」变成「平铺」；
 *   - 一键推荐配置点下去，表单是否真的被填上（而不是只弹个 toast）。
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
 *   3) node scripts/visual-check-backtest.mjs http://127.0.0.1:8787/backtest <token> [截图目录]
 *
 * 退出码 0 = 全部通过。
 */
import { spawn } from 'node:child_process'
import { existsSync, mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

import { resolveDebugPort } from './cdp-port.mjs'

const [, , URL_ARG, TOKEN, OUTDIR = 'node_modules/.cache/qd-visual'] = process.argv
if (!URL_ARG || !TOKEN) {
  console.error('用法: node scripts/visual-check-backtest.mjs <url> <token> [截图目录]')
  process.exit(2)
}

// ⚠️ 端口绝不能写死：本机保留段含 9120–9219 / 9320–9419，写死会让脚本静默失效
const DEBUG_PORT = await resolveDebugPort()
const CDP_BASE = `http://127.0.0.1:${DEBUG_PORT}`
const PROFILE = join(process.cwd(), 'node_modules/.cache/qd-visual-profile-backtest')
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
  // 真实网络请求清单 —— 用来验「打开弹窗不会自动跑」（DOM 断言查不出这件事）
  const requests = []
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
    } else if (m.method === 'Network.requestWillBeSent') {
      requests.push(m.params.request.url)
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
  const click = async (selector, nth = 0) => {
    const ok = await hover(selector, nth)
    if (!ok) return false
    await cdp('Input.dispatchMouseEvent', { type: 'mousePressed', x: 1, y: 1, button: 'left', clickCount: 1, buttons: 1 })
    await cdp('Input.dispatchMouseEvent', { type: 'mouseReleased', x: 1, y: 1, button: 'left', clickCount: 1, buttons: 0 })
    await sleep(300)
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

  await cdp('Page.enable')
  await cdp('Runtime.enable')
  await cdp('Network.enable')
  // 关缓存：`npm run build` 会换 chunk 哈希，持久化 profile 缓存的旧 index.html
  // 会去动态 import **已删除的旧 chunk** → 404 → 白屏（表现为「先跑通过、rebuild 后再跑就红」）。
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

  // ---- 进入回测页 ----
  await cdp('Page.navigate', { url: URL_ARG })
  await sleep(2000)
  // 等策略列表加载完（策略下拉里有 option 才算就绪）
  let ready = false
  for (let i = 0; i < 20 && !ready; i++) {
    ready = await evalJs(`document.querySelectorAll('select option').length > 5`)
    if (!ready) await sleep(800)
  }
  check(ready, '回测页加载出策略列表（后端元信息已就绪）')

  const body = await evalJs('document.body.innerText')

  // ---- 1. 四步向导骨架 ----
  for (const t of ['用哪个策略', '买哪些股票', '回测多长时间', '本金与及格线', '开始回测']) {
    check(body.includes(t), `页面上出现「${t}」`)
  }
  check(body.includes('第一次用？照这个顺序来'), '空态给出「照这个顺序来」的上手引导')
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
      hasPeriod: document.body.textContent.includes('数据周期（K线周期）'),
      hasStop: document.body.textContent.includes('止损方式'),
      hasSizing: document.body.textContent.includes('仓位算法'),
    })`),
  )
  check(advanced.details >= 2, '新手模式下存在折叠区（details ≥ 2）', `details=${advanced.details}`)
  check(
    advanced.hasPeriod && advanced.hasStop && advanced.hasSizing,
    '高级项仍然在 DOM 里（只是折叠）—— 功能没有被删掉',
    JSON.stringify(advanced),
  )

  const p1 = await shot('bt-01-beginner.png')
  console.log(`      截图：${p1}`)

  // ---- 3. 悬浮解释：这是用户这次的核心诉求，必须真的弹出 ----
  const hovered = await hover('[aria-label="对比基准（及格线） 说明"]')
  check(hovered, '找到「对比基准（及格线）」的悬浮触发器')
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
    check(t.text.includes('及格线') && t.text.includes('什么都不做'), '气泡正文是「人话」解释（不是专业定义）', t.text.slice(0, 60))
    check(t.text.includes('是什么') && t.text.includes('怎么看'), '气泡含「是什么 / 怎么看」两段')
    // ⚠️ 卡片/表格祖先有 overflow 时气泡会被裁掉 —— 这是必须守住的回归点
    check(t.inside, '气泡没有被祖先的 overflow 裁掉（完整落在视口内）', `w=${t.w}`)
    const p2 = await shot('bt-02-tooltip.png')
    console.log(`      截图：${p2}`)
  }
  // 移开鼠标后气泡应消失
  await cdp('Input.dispatchMouseEvent', { type: 'mouseMoved', x: 5, y: 5, buttons: 0 })
  await sleep(400)
  check(!(await evalJs(`!!document.querySelector('[role="tooltip"]')`)), '鼠标移开后气泡自动收起')

  // ---- 4. 行内术语（虚线下划线文字）也能悬停 ----
  // 目标是人话预览里的「及格线」——用户明确说过看不懂「基准标的」这个词，
  // 所以这一处必须是可悬停的行内解释，而不是只有问号图标。
  const inlineTip = await evalJs(`(() => {
    const els = [...document.querySelectorAll('span')].filter(
      e => String(e.className).includes('border-dotted') && e.innerText.trim() === '及格线',
    );
    return els.length;
  })()`)
  check(inlineTip > 0, '人话预览里的行内术语（及格线）挂了悬浮解释')

  // ---- 5. 一键推荐配置真的填进了表单 ----
  const applied = await clickByText('button', '一键填入推荐配置')
  check(applied, '点击「一键填入推荐配置」')
  await sleep(600)
  // ⚠️ 不能用 `input[type=number]` 的第一个：策略参数（如「快线周期」默认 20）也是
  //    number 输入，而且它们**在折叠区里也存在于 DOM**，会抢到选择器。
  //    按 Field 的 label 文本定位，才是稳定的做法。
  const filled = JSON.parse(
    await evalJs(`(() => {
      const cfg = [...document.querySelectorAll('section.card')].find(s => s.textContent.includes('回测配置'));
      const byLabel = (text) => {
        const lab = [...document.querySelectorAll('label.lbl')].find(l => l.textContent.includes(text));
        if (!lab || !lab.parentElement) return null;
        const inp = lab.parentElement.querySelector('input');
        return inp ? inp.value : null;
      };
      const btns = [...document.querySelectorAll('button')].map(b => b.innerText.trim());
      return JSON.stringify({
        symbols: byLabel('股票代码'),
        capital: byLabel('初始资金'),
        hasCfg: !!cfg,
        activeFiveYear: btns.includes('近 5 年'),
        summary: (document.body.innerText.match(/本次要做什么[\\s\\S]{0,200}/) || [''])[0],
      });
    })()`),
  )
  check(filled.symbols === 'SPY', '推荐配置把标的填成 SPY', String(filled.symbols))
  check(filled.capital === '100000', '推荐配置把本金填成 100000', String(filled.capital))
  check(
    filled.summary.includes('SPY') && filled.summary.includes('双均线'),
    '「本次要做什么」用人话复述了配置',
    filled.summary.slice(0, 80),
  )
  const p3 = await shot('bt-03-applied.png')
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
      hasPeriod: document.body.textContent.includes('数据周期（K线周期）'),
      // ⚠️ 不能用 body.innerText 搜文案：空态引导语里也写着「一键填入推荐配置」，
      //    那样断言永远为真、永远不报错。必须直接问「按钮还在不在」。
      hasRecBtn: [...document.querySelectorAll('button')].some(b => b.innerText.trim() === '一键填入推荐配置'),
    })`),
  )
  check(pro.details === 0, '关掉新手模式后所有高级项平铺展示（无折叠）', `details=${pro.details}`)
  check(pro.hasPeriod, '专业模式下数据周期等高级项仍然在')
  check(!pro.hasRecBtn, '专业模式下不再显示「一键填入推荐配置」')
  const p4 = await shot('bt-04-pro.png')
  console.log(`      截图：${p4}`)

  // ---- 7. 结果区：点历史记录 → 人话结论 + 指标悬浮解释 ----
  // 这一块是本次改版的重点（用户抱怨的正是「一堆指标看不懂」），
  // 但它只在**有结果时**才渲染，SSR 断言覆盖不到，必须在这里验。
  const rowClicked = await evalJs(`(() => {
    const tr = document.querySelector('tbody tr');
    if (!tr) return false;
    tr.click();
    return true;
  })()`)
  check(rowClicked, '点击历史回测记录（无需联网即可拿到一份结果）')
  let hasResult = false
  for (let i = 0; i < 20 && !hasResult; i++) {
    await sleep(600)
    hasResult = await evalJs(`document.body.textContent.includes('这次回测到底怎么样')`)
  }
  check(hasResult, '结果区渲染出「这次回测到底怎么样」（人话结论卡片）')

  if (hasResult) {
    const summary = await evalJs(
      `(() => {
        const card = [...document.querySelectorAll('section.card')].find(s => s.textContent.includes('这次回测到底怎么样'));
        return card ? card.innerText : '';
      })()`,
    )
    check(/一句话结论/.test(summary), '结论卡片里有「一句话结论」', summary.slice(0, 60))
    check(/变成/.test(summary) && /\$/.test(summary), '结论里用「$X 变成 $Y」而不是裸数字', summary.slice(0, 120))
    check(/及格线/.test(summary), '结论里用「及格线」而不是「基准标的」（和左侧配置面板用词一致）')
    check(!/基准标的/.test(summary), '结论里不再出现「基准标的」这种让人看不懂的说法')
    check(/最难受的时候/.test(summary), '结论里用大白话解释最大回撤')
    // 有基准数据时不能出现「基准 0.0%」这种凭空的数字
    check(!/拿着」是 \+?0\.0%/.test(summary), '结论没有编造「基准 0.0%」的假数字', summary.slice(0, 160))

    // 把结论卡片滚到视口顶部截一张，便于人工复核排版
    await evalJs(`(() => {
      const card = [...document.querySelectorAll('section.card')].find(s => s.textContent.includes('这次回测到底怎么样'));
      if (card) card.scrollIntoView({ block: 'start' });
    })()`)
    await sleep(500)
    const p5 = await shot('bt-05-result-summary.png')
    console.log(`      截图：${p5}`)

    // 指标名悬停 → 弹出「是什么 / 怎么看」
    const hoveredMetric = await evalJs(`(() => {
      const el = [...document.querySelectorAll('span')].find(
        e => String(e.className).includes('border-dotted') && e.innerText.trim() === '夏普比率',
      );
      if (!el) return false;
      el.scrollIntoView({ block: 'center' });
      const r = el.getBoundingClientRect();
      window.__qdMetricTip = { x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2) };
      return true;
    })()`)
    check(hoveredMetric, '指标表里的「夏普比率」挂了悬浮解释')
    if (hoveredMetric) {
      const pt = await evalJs('JSON.stringify(window.__qdMetricTip)')
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
        check(/性价比/.test(t.text), '夏普比率的解释是「人话」（用性价比打比方）', t.text.slice(0, 60))
        check(t.inside, '指标解释气泡没有被表格的 overflow 裁掉')
        const p7 = await shot('bt-07-metric-tip.png')
        console.log(`      截图：${p7}`)
      }
    }
    const p6 = await shot('bt-06-result.png')
    console.log(`      截图：${p6}`)
  }

  // ---- 8. 三个进阶工具弹窗（本次被搬到独立文件，必须逐个开一次）----
  // ⚠️ 用 DOM 的 click() 而不是坐标点击：按钮可能在折叠区或视口外。
  const closeDialog = async () => {
    await evalJs(`(() => {
      const c = [...document.querySelectorAll('button')].find(b => b.getAttribute('aria-label') === '关闭对话框');
      if (c) c.click();
    })()`)
    await sleep(400)
  }
  const openModal = async (btnText, expectText) => {
    const ok = await clickByText('button', btnText)
    if (!ok) return { ok: false, shown: false }
    await sleep(800)
    const shown = await evalJs(`document.body.textContent.includes(${JSON.stringify(expectText)})`)
    await closeDialog()
    return { ok: true, shown }
  }

  const opt = await openModal('参数寻优', '参数寻优 · 网格搜索')
  check(opt.ok && opt.shown, '「参数寻优」弹窗能打开（组件拆分后未断链）')

  const cmp = await openModal('多策略对比', '所有策略使用')
  check(cmp.ok && cmp.shown, '「多策略对比」弹窗能打开（组件拆分后未断链）')

  // 因子诊断：打开**不得**自动发请求（旧实现是「点按钮 = 打开 + 立刻跑」）
  const before = requests.length
  const facOk = await clickByText('button', '因子诊断')
  check(facOk, '点击「因子诊断」')
  await sleep(900)
  const facState = JSON.parse(
    await evalJs(`JSON.stringify({
      title: document.body.textContent.includes('因子诊断 · IC 分析'),
      startBtn: [...document.querySelectorAll('button')].some(b => b.innerText.trim() === '开始诊断'),
    })`),
  )
  check(facState.title, '「因子诊断」弹窗能打开（组件拆分后未断链）')
  check(facState.startBtn, '因子诊断弹窗里有明确的「开始诊断」按钮')
  const newReqs = requests.slice(before).filter((u) => /factor-ic/.test(u))
  check(newReqs.length === 0, '打开因子诊断不会自动发起计算（必须点「开始诊断」才跑）', newReqs.join(','))
  await closeDialog()

  // ---- 9. 页面没有运行期报错 ----
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
console.log(`  回测中心视觉回归：${results.length - failed}/${results.length} 项通过`)
if (failed) {
  console.log(`  失败 ${failed} 项`)
}
console.log('='.repeat(58))
process.exit(failed ? 1 : 0)
