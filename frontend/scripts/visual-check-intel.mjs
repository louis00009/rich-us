/**
 * 真实浏览器回归 —— AI 情报中心（/intel）
 * ======================================
 * 这个页面在 2026-09-29 被整体重写（pages/Intel.tsx 1335 → 207 行 + 9 个子组件），
 * `renderToString`（test:render）只能证明「不抛错」，证明不了：
 *   · useEffect 拉完数据后页面还是不是好的（SSR 不跑 useEffect）；
 *   · 用户抱怨的三件事是否真的解决了 ——
 *       ① 总控有没有「上次运行 / 抓取条数」；
 *       ② 事件流有没有把重点顶上来（三档分级 + 为什么重要）；
 *       ③ 有没有「AI 强制提示」区，说清哪些重要、什么时机。
 * 所以这里开真实 Chrome，等数据落地后断言**用户能看到的文字**。
 *
 * 另外守住平台铁律：打开页面**不得**自动调用 AI（数真实 /api/ai/assist 请求）。
 *
 * 用法：node scripts/visual-check-intel.mjs http://127.0.0.1:8787/intel <token> [截图目录]
 * 退出码 0 = 全部通过。
 */
import { spawn } from 'node:child_process'
import { existsSync, mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

import { resolveDebugPort } from './cdp-port.mjs'

const [, , URL_ARG, TOKEN, OUTDIR = 'node_modules/.cache/qd-visual'] = process.argv
if (!URL_ARG || !TOKEN) {
  console.error('用法: node scripts/visual-check-intel.mjs <url> <token> [截图目录]')
  process.exit(2)
}

const DEBUG_PORT = await resolveDebugPort()
const CDP_BASE = `http://127.0.0.1:${DEBUG_PORT}`
const PROFILE = join(process.cwd(), 'node_modules/.cache/qd-visual-profile-intel')
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

  // ---- 注入登录态 ----
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

  // ---- 打开情报中心 ----
  aiCalls = 0
  await cdp('Page.navigate', { url: URL_ARG })
  await sleep(14000)

  const page = JSON.parse(
    await evalJs(`(() => {
      const t = document.body.innerText || '';
      const has = (s) => t.includes(s);
      return JSON.stringify({
        len: t.length,
        monitor: has('监控总控'),
        digest: has('AI 每日必读'),
        feed: has('事件流') || has('情报事件'),
        // ① 总控关键口径（用户抱怨「没有上次运行时间 / 抓取多少条」）
        mLastRun: has('上次运行'),
        mBatch: has('本批抓取'),
        mToday: has('今日新增事件'),
        mH24: has('近 24 小时'),
        mScrape: has('上次抓取'),
        mTotal: has('累计'),
        mBars: has('近 7 日事件量'),
        neverRun: has('从未运行'),
        // ③ AI 强制提示区
        dOverview: has('窗口内') && has('必读'),
        dCritical: has('重大'),
        dHigh: has('重要'),
        dTabTop: has('必读清单'),
        dTabSym: has('该盯哪几家'),
        dTabWatch: has('买入时机'),
        dAnalyzeBtn: has('AI 深度解读'),
        dDisclaimer: has('不是投资建议') || has('人工批准'),
        // ② 事件流突出重点
        fHit: has('命中'),
        fTier: has('重大') && (has('可看') || has('低')),
        fWhy: has('为什么重要'),
        fSort: has('按重要度排序'),
        // 白屏哨兵：连标题都没有就是没渲染出来
        white: t.trim().length < 200,
      });
    })()`),
  )

  check(!page.white, '页面不是白屏（渲染出实质内容）', `innerText 长度 ${page.len}`)
  check(page.monitor, '渲染出「监控总控」')
  check(page.digest, '渲染出「AI 每日必读」（强制提示区）')
  check(page.feed, '渲染出事件流区域')

  // ---- ① 总控六项关键口径 ----
  check(page.mLastRun && !page.neverRun, '总控显示「上次运行」及真实批次（不是「从未运行」）')
  check(page.mBatch, '总控显示「本批抓取 / 建议」条数')
  check(page.mToday, '总控显示「今日新增事件」')
  check(page.mH24, '总控显示「近 24 小时」')
  check(page.mScrape, '总控显示「上次抓取」时间')
  check(page.mTotal, '总控显示「累计」')
  check(page.mBars, '总控带「近 7 日事件量」柱状图')

  // ---- ①b 抓取家数：必须能选「全部」，且写明「分批」而不是让人以为漏抓 ----
  // 真实报障：「AI 抓取 0/4 家」——家数写死 4，待抓取却有 28 家，用户以为剩下的被丢了。
  const scrapeCfg = JSON.parse(
    await evalJs(`(() => {
      const sel = [...document.querySelectorAll('select')]
        .find(s => [...s.options].some(o => o.textContent.includes('全部')));
      const t = document.body.innerText || '';
      const m = t.match(/待抓取\\s*(\\d+)\\s*家/);
      return JSON.stringify({
        hasSelect: !!sel,
        opts: sel ? [...sel.options].map(o => o.textContent.trim()) : [],
        pending: m ? Number(m[1]) : null,
        hasTotal: /共\\s*\\d+\\s*家启用/.test(t),
        // 措辞会演进（曾写「每轮自动抓」，加了「指定标的」后改成「每轮另自动抓 3 家轮转」）——
        // 断言**语义锚点**而不是整句：核心是让用户知道调度器在轮转，不是漏抓。
        explainsBatch: t.includes('轮转') || t.includes('刻意分批'),
      });
    })()`),
  )
  check(scrapeCfg.hasSelect, '总控有「本轮家数」下拉（家数不能写死）', JSON.stringify(scrapeCfg.opts))
  check(scrapeCfg.opts.some((o) => o.includes('全部')),
        '「本轮家数」含「全部」选项（想一次跑完就能选）', JSON.stringify(scrapeCfg.opts))
  check(scrapeCfg.pending != null && scrapeCfg.hasTotal,
        '总控写明「待抓取 N 家 / 共 M 家启用」（4 家才有分母可对照）', JSON.stringify(scrapeCfg))
  check(scrapeCfg.explainsBatch,
        '总控解释了分批机制（每轮轮转 / 刻意分批），而不是让用户以为漏抓')

  // ---- ③ AI 强制提示区 ----
  check(page.dOverview, '必读区有概览条（窗口内事件数 / 必读条数）')
  check(page.dCritical && page.dHigh, '必读区区分「重大 / 重要」')
  check(page.dTabTop && page.dTabSym && page.dTabWatch, '必读区三个页签齐备（必读清单 / 该盯哪几家 / 买入时机）')
  check(page.dAnalyzeBtn, '必读区有「AI 深度解读」按钮（手动触发）')
  check(page.dDisclaimer, '必读区有常驻免责说明')

  // ---- ② 事件流突出重点 ----
  check(page.fHit, '事件流有汇总条（命中 N 条）')
  check(page.fTier, '事件流做了三档视觉分级（重大 / 可看）')
  check(page.fWhy, '事件卡写明「为什么重要」')
  check(page.fSort, '事件流默认按重要度排序（不是按时间平铺）')

  // ---- ④ 内容类型筛选：媒体评论（约占入库量 11%）必须能一次滤掉 ----
  // 后端把评论类重要度封顶到 34.9（< 可看档 40），前端再加「媒体」标记 + 内容类型筛选。
  // 这里驱动原生 <select> 真实切换，断言用户看得到的结果，而不是只看选项存在。
  const mediaSel = `[...document.querySelectorAll('select')].find(s => [...s.options].some(o => o.textContent.includes('仅媒体评论')))`
  const mediaOpts = JSON.parse(
    await evalJs(`(() => {
      const sel = ${mediaSel};
      return JSON.stringify({ found: !!sel, opts: sel ? [...sel.options].map(o => o.textContent.trim()) : [] });
    })()`),
  )
  check(mediaOpts.found, '筛选栏有「内容类型」下拉（媒体评论可单独筛）', JSON.stringify(mediaOpts.opts))

  const setMedia = async (label) => {
    const r = await evalJs(`(() => {
      const sel = ${mediaSel};
      if (!sel) return 'no-select';
      const opt = [...sel.options].find(o => o.textContent.trim() === ${JSON.stringify(label)});
      if (!opt) return 'no-option';
      sel.value = opt.value;
      sel.dispatchEvent(new Event('change', { bubbles: true }));
      return 'ok';
    })()`)
    await sleep(2000)
    return r
  }

  // 只在事件流那张卡片里数条目，避免命中别处的列表。
  // ⚠️ 必须按**徽章元素**数，不能按 innerText 找「媒体」二字 —— 真实公司事件的摘要里
  // 会出现「据媒体报道」之类措辞（实测 200 条里 3 条），按文本断言会假报失败。
  const countMarks = `(() => {
    const card = [...document.querySelectorAll('section.card')].find(s => (s.innerText || '').includes('命中'));
    if (!card) return JSON.stringify({ rows: -1, withMark: -1 });
    const rows = [...card.querySelectorAll('li')].filter(li => (li.innerText || '').includes('★'));
    const withMark = rows.filter(li => li.querySelector('[title^="媒体评论"]')).length;
    const t = card.innerText || '';
    return JSON.stringify({ rows: rows.length, withMark, expandedHint: t.includes('条媒体评论') });
  })()`

  await setMedia('仅公司事件')
  const onlyEvents = JSON.parse(await evalJs(countMarks))
  check(onlyEvents.rows > 0 && onlyEvents.withMark === 0,
        '选「仅公司事件」后事件流里不再出现「媒体」徽章', JSON.stringify(onlyEvents))

  await setMedia('仅媒体评论')
  const onlyMedia = JSON.parse(await evalJs(countMarks))
  check(onlyMedia.rows > 0 && onlyMedia.withMark === onlyMedia.rows,
        '选「仅媒体评论」后每条都带「媒体」徽章', JSON.stringify(onlyMedia))
  check(onlyMedia.expandedHint, '选「仅媒体评论」时低影响折叠区自动展开（不会给用户一个空页面）')

  await setMedia('全部内容')

  // ---- 平台铁律：打开页面不得自动跑 AI ----
  check(aiCalls === 0, '打开页面不会自动调用 AI（/ai/assist 0 次）', `调用 ${aiCalls} 次`)

  // ---- 卡片标题栏不被 actions 挤死（4 个按钮 + 未读徽章，真实风险）----
  const hdr = JSON.parse(
    await evalJs(`(() => {
      const el = [...document.querySelectorAll('section.card')]
        .find(s => (s.innerText || '').includes('AI 每日必读'));
      if (!el) return JSON.stringify({ w: -1, why: 'no-card' });
      const left = el.querySelector('header > div');
      if (!left) return JSON.stringify({ w: -1, why: 'no-header-div' });
      const r = left.getBoundingClientRect();
      return JSON.stringify({ w: Math.round(r.width), h: Math.round(r.height) });
    })()`),
  )
  check(hdr.w >= 120, '必读卡片标题栏未被按钮挤成窄条（副标题不会一字一行）',
        `标题栏宽 ${hdr.w}px（期望 ≥120）${hdr.why || ''}`)

  await shot('intel-open.png')

  // ---- 切到「买入时机」：必须给出时机信息，或如实说明没有 ----
  const clickedWatch = await evalJs(`(() => {
    const b = [...document.querySelectorAll('button')].find(x => (x.innerText || '').trim().startsWith('买入时机'));
    if (!b) return 'no-tab';
    b.click(); return 'ok';
  })()`)
  check(clickedWatch === 'ok', '能切到「买入时机」页签', clickedWatch)
  await sleep(1500)
  const watch = JSON.parse(
    await evalJs(`(() => {
      const t = document.body.innerText || '';
      return JSON.stringify({
        zone: t.includes('关注区间'),
        trigger: t.includes('触发条件'),
        invalidation: t.includes('失效参考'),
        noData: t.includes('数据未覆盖'),
        empty: t.includes('暂无时机候选'),
        why: t.includes('量化支撑'),
      });
    })()`),
  )
  // 三种都是**诚实**的合法结果：给了区间 / 明确写「数据未覆盖」/ 当日无候选。
  // 唯一不可接受的是「什么都没有」。
  check(watch.zone || watch.empty, '买入时机页给出内容（关注区间，或如实说明当日无候选）',
        JSON.stringify(watch))
  check(watch.zone ? (watch.trigger || watch.noData) : true,
        '有时机候选时必带触发条件（或写明数据未覆盖）', JSON.stringify(watch))
  check(watch.why || watch.empty, '买入时机页说明价位来源（量化支撑，非估算）')
  await shot('intel-watch.png')

  // ---- 必读清单首条可展开看「为什么重要」----
  await evalJs(`(() => {
    const b = [...document.querySelectorAll('button')].find(x => (x.innerText || '').trim().startsWith('必读清单'));
    if (b) b.click();
  })()`)
  await sleep(1200)
  const top1 = JSON.parse(
    await evalJs(`(() => {
      const t = document.body.innerText || '';
      const m = t.match(/重要度\\s*([0-9.]+)/);
      return JSON.stringify({ importance: m ? Number(m[1]) : null, why: t.includes('为什么重要') });
    })()`),
  )
  check(top1.importance != null && top1.importance > 0,
        '必读清单展示确定性重要度分数', `首条 ${top1.importance}`)
  check(top1.why, '必读条目写明「为什么重要」（规则化理由）')
  await shot('intel-digest.png')

  // ---- 滚动到事件流截图取证 ----
  await evalJs(`(() => {
    const el = [...document.querySelectorAll('section.card')]
      .find(s => (s.innerText || '').includes('命中'));
    if (el) el.scrollIntoView({ block: 'start' });
  })()`)
  await sleep(800)
  await shot('intel-feed.png')

  // ---- ①c 指定标的：能挑具体公司 ----
  // 用户原话：「我可能有重点要跑的，或者我可能就选一家跑」——
  // 原来只能按家数从待抓取清单取前 N 家，无法表达「今天重点跑这几家」。
  // 断言的是**行为**：能打开面板 → 点一家 → 计数与顺序出现、「本轮」家数被禁用 →
  // 刷新后选择仍在（持久化：用户每天要跑，不该每天重挑一遍）。
  // ⚠️ 筹码用 aria-pressed 定位（全项目仅 ScrapePicker 使用），不要按文本找代码 ——
  //    公司名/主题里也可能出现大写字母，会误判。
  const openPicker = await evalJs(`(() => {
    const btn = [...document.querySelectorAll('button')]
      .find(b => (b.innerText || '').trim().startsWith('指定标的'));
    if (!btn) return 'no-button';
    btn.click();
    return 'ok';
  })()`)
  check(openPicker === 'ok', '总控有「指定标的」入口（能挑具体公司，不是只能按家数随机取）', openPicker)
  await sleep(500)

  const panelInfo = JSON.parse(
    await evalJs(`(() => {
      const t = document.body.innerText || '';
      const chips = [...document.querySelectorAll('button[aria-pressed]')];
      return JSON.stringify({
        hasPanel: t.includes('指定抓取标的'),
        chips: chips.length,
        hasQuick: t.includes('全选待抓取') || t.includes('全选启用'),
        hintAuto: t.includes('未选择任何标的'),
      });
    })()`),
  )
  check(panelInfo.hasPanel, '点开后出现「指定抓取标的」面板', JSON.stringify(panelInfo))
  check(panelInfo.chips > 0, '面板列出可勾选的标的筹码', `chips=${panelInfo.chips}`)
  check(panelInfo.hasQuick, '提供快捷选择（全选待抓取 / 全选启用），不必逐个点')
  check(panelInfo.hintAuto, '未选择时如实说明将按「自动（待抓取轮转）」执行')

  // 截图取证前**必须把面板滚进视口**：脚本刚在上面把事件流 scrollIntoView 过，
  // 此时视口停在事件流，而面板在总控卡片里（屏外）—— 直接截图只会拍到事件流，
  // 面板「看起来没渲染」，实际 50 项断言全过（纯截图假象，踩过）。
  const scrolled = await evalJs(`(() => {
    const chip = document.querySelector('button[aria-pressed]');
    const panel = chip && chip.closest('div[class*="border-brand-200"]');
    if (!panel) return 'no-panel';
    panel.scrollIntoView({ block: 'center' });
    return 'scrolled';
  })()`)
  await sleep(700)
  const panelInView = await evalJs(`(() => {
    const chip = document.querySelector('button[aria-pressed]');
    if (!chip) return 'no-chip';
    const r = chip.getBoundingClientRect();
    return r.top >= 0 && r.bottom <= window.innerHeight ? 'in-view' : 'out-of-view';
  })()`)
  check(scrolled === 'scrolled' && panelInView === 'in-view',
        '指定标的面板已滚入视口（否则截图取证是假的）', `${scrolled}/${panelInView}`)

  // 只点一家 —— 「我就选一家跑」必须是最省事的路径
  const pickOne = JSON.parse(
    await evalJs(`(() => {
      const chips = [...document.querySelectorAll('button[aria-pressed="false"]')];
      if (!chips.length) return JSON.stringify({ ok: false });
      const sym = (chips[0].innerText || '').replace(/[^A-Z.\\-]/g, '');
      chips[0].click();
      return JSON.stringify({ ok: true, sym });
    })()`),
  )
  await sleep(700)
  const afterPick = JSON.parse(
    await evalJs(`(() => {
      const t = document.body.innerText || '';
      const m = t.match(/已选\\s*(\\d+)\\s*家/);
      const sel = [...document.querySelectorAll('button[aria-pressed="true"]')];
      const limitSel = [...document.querySelectorAll('select')]
        .find(s => [...s.options].some(o => o.textContent.includes('全部')));
      return JSON.stringify({
        count: m ? Number(m[1]) : null,
        selected: sel.length,
        hasOrder: t.includes('抓取顺序'),
        orderText: (t.match(/抓取顺序：\\s*(\\S+)/) || [])[1] || '',
        limitDisabled: limitSel ? !!limitSel.disabled : null,
      });
    })()`),
  )
  check(pickOne.ok && afterPick.count === 1 && afterPick.selected === 1,
        '点选一家 → 计数为 1（「就选一家跑」可达）', JSON.stringify({ pickOne, afterPick }))
  check(afterPick.hasOrder, '显示「抓取顺序」（点选顺序 = 抓取顺序，后端按序执行）')
  check(afterPick.limitDisabled === true,
        '已指定标的时「本轮」家数被禁用（避免「勾了 N 家却只跑 4 家」）',
        JSON.stringify(afterPick))
  check((afterPick.orderText || '').includes(pickOne.sym),
        '顺序行列出所选标的代码', `${afterPick.orderText} vs ${pickOne.sym}`)
  // 截图放在「已选一家」之后：这样图里能看到序号筹码 + 「抓取顺序：X」确认行
  await shot('intel-picker.png')

  // 持久化：刷新后选择仍在（用户每天要跑，不该每天重挑一遍）
  await cdp('Page.navigate', { url: URL_ARG })
  await sleep(7000)
  const afterReload = JSON.parse(
    await evalJs(`(() => {
      const t = document.body.innerText || '';
      const m = t.match(/已选\\s*(\\d+)\\s*家/);
      return JSON.stringify({
        count: m ? Number(m[1]) : null,
        hasOrder: t.includes('抓取顺序'),
        inStorage: localStorage.getItem('qd.intel.scrape.v1') || '',
      });
    })()`),
  )
  check(afterReload.count === 1 && afterReload.hasOrder,
        '刷新后「指定标的」选择仍在（持久化，不用每天重挑）', JSON.stringify(afterReload))
  check(afterReload.inStorage.includes(pickOne.sym),
        '选择确实落在 localStorage（键 qd.intel.scrape.v1）', afterReload.inStorage)

  // 清空 → 回到自动模式（「本轮」家数恢复可用）
  const cleared = await evalJs(`(() => {
    const b = [...document.querySelectorAll('button')].find(x => (x.innerText || '').trim() === '清空');
    if (!b) return 'no-button';
    if (b.disabled) return 'disabled';
    b.click();
    return 'ok';
  })()`)
  await sleep(700)
  const afterClear = JSON.parse(
    await evalJs(`(() => {
      const t = document.body.innerText || '';
      const limitSel = [...document.querySelectorAll('select')]
        .find(s => [...s.options].some(o => o.textContent.includes('全部')));
      return JSON.stringify({
        hintAuto: t.includes('未选择任何标的'),
        limitEnabled: limitSel ? !limitSel.disabled : null,
        stored: localStorage.getItem('qd.intel.scrape.v1') || '',
      });
    })()`),
  )
  check(cleared === 'ok' && afterClear.hintAuto && afterClear.limitEnabled === true,
        '「清空」后回到自动模式（「本轮」家数恢复可用）', JSON.stringify({ cleared, afterClear }))

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
console.log(`  情报中心渲染回归：${results.length - failed}/${results.length} 项通过`)
console.log(`  截图目录：${OUTDIR}`)
console.log('='.repeat(58))
process.exit(failed ? 1 : 0)
