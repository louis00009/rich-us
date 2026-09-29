/**
 * 页面渲染回归（无需后端）
 * ========================
 * 把页面真正渲染一遍（react-dom/server），守住两类问题：
 *  ① **白屏类**：hooks 顺序违规（React #300）、未定义组件、props 写错、越界取值。
 *     项目为这类问题专门立过铁律（hooks 必须在 early return 之前），但一直缺回归用例。
 *  ② **契约类**：列头/说明文案/筛选控件是否真的进了 DOM，以及每个指标的悬浮说明
 *     是否齐备（「是什么 / 怎么看」）。
 *
 * 为什么能跑通而旧的 DOM 冒烟被废弃：旧版走路由懒加载 chunk（环境脆弱）；
 * 这里用 esbuild 直接把页面模块打成单文件再 import，绕开 lazy chunk。
 * 也只做 renderToString —— useEffect 不执行，因此**不发任何网络请求**。
 *
 * 用法：node scripts/render-check.mjs   （npm run test:render）
 * 新增页面：在 PAGES 里加一项即可。
 */
import esbuild from 'esbuild'
import { existsSync, mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const root = join(here, '..')
const src = (p) => join(root, 'src', p)

/** 页面 + 需要一起打包的上下文导出（Provider / 常量）。 */
const PAGES = [
  {
    name: 'Rankings',
    entry: `export { default as Page } from ${JSON.stringify(src('pages/Rankings.tsx'))}
export { ToastProvider } from ${JSON.stringify(src('components/ui.tsx'))}
export { DEFAULT_VISIBLE, RANKING_COLUMNS } from ${JSON.stringify(src('lib/rankingColumns.ts'))}
`,
    // 渲染成功后必须出现在 HTML 里的关键内容
    expect: [
      // 榜单页头部徽标（原为「S&P 500」，改版后按实际标的数展示「美股 N」）
      '美股',
      '快速方案',
      '低估价值',
      '高股息',
      '破净',
      '超跌',
      '市盈率 PE',
      '市净率 PB',
      'ROE',
      '股息率',
      '距 52 周高',
      '排除亏损标的',
      '列（',
      // ---- 候选观察池 ----
      '全部标的',
      '候选观察池',
      '评分设置',
      '综合评分',
      // ---- 技术面筛选控件 ----
      '技术面',
      'RSI(14)',
      '200 日均线',
      '均线多头排列',
      '年化波动 ≤',
      'Beta ≤',
      '超额 SPY ≥',
    ],
    // 悬浮说明触发器（气泡正文只在 hover 时进 DOM，所以验 aria-label）
    // ⚠️ 只列**默认可见**的列 —— 隐藏列的表头根本不渲染，写了必然误报。
    tips: ['市盈率 PE', '市净率 PB', 'ROE', '股息率', '距 52 周高', '总市值', '成交额', '综合评分'],
    // 该页自己的额外断言
    extra: ({ mod, html, check }) => {
      const cols = mod.DEFAULT_VISIBLE
      check(
        cols.includes('pe_ttm') && cols.includes('pb') && cols.includes('roe') && cols.includes('div_yield'),
        '默认可见列含 PE/PB/ROE/股息率',
        cols.join(','),
      )
      check(cols.includes('score'), '默认可见列含「综合评分」', cols.join(','))
      const list = mod.RANKING_COLUMNS
      const thin = list.filter((c) => !c.tip || !c.tip.title || !c.tip.what || !c.tip.how)
      check(thin.length === 0, '每个指标都有「是什么 / 怎么看」说明', `缺文案：${thin.map((c) => c.key).join(',')}`)
      // 文案是纯字符串（不是 Markdown）—— 写 `**强调**` 会在气泡里显示成字面星号
      const md = list.filter((c) =>
        [c.tip?.title, c.tip?.what, c.tip?.how, c.tip?.warn].some((s) => typeof s === 'string' && s.includes('**')),
      )
      check(md.length === 0, '提示文案不含 Markdown 语法（否则气泡里显示字面星号）', md.map((c) => c.key).join(','))
      const pe = (list.find((c) => c.key === 'pe_ttm') || {}).tip || {}
      check(/回本/.test(pe.what || ''), 'PE 说明讲清「是什么」')
      check(/同行业/.test(pe.how || ''), 'PE 说明讲清「怎么看」（需与同行比）')
      check(!!pe.warn && /亏损|失真/.test(pe.warn), 'PE 说明标注了负 PE / 一次性损益陷阱')
      const div = (list.find((c) => c.key === 'div_yield') || {}).tip || {}
      check(/股息陷阱/.test(div.warn || ''), '股息率说明标注了「股息陷阱」风险')
      check(html.includes('aria-label="市盈率 PE 指标说明"'), 'PE 列头真的挂上了说明触发器')

      // ---- 候选观察池 / 评分 ----
      // 新增的技术指标列必须齐备（否则用户打开「列」会发现少了指标）
      const need = ['score', 'ma200_rel', 'ma20_rel', 'ma_bull', 'r1y', 'excess_1y', 'r3m', 'rsi14', 'vol_ann', 'beta']
      const absent = need.filter((k) => !list.some((c) => c.key === k))
      check(absent.length === 0, '技术指标与评分列都已定义', `缺：${absent.join(',')}`)
      const sortable = need.filter((k) => !(list.find((c) => c.key === k) || {}).sortable)
      check(sortable.length === 0, '新增列全部可排序', `不可排序：${sortable.join(',')}`)

      // **最重要的一条**：评分绝不能自称「买入信号」。
      // 本项目自己的复盘结论是规则化策略收益上打不过买入持有 ——
      // 若文案写成「可买入」就是无依据的承诺，会误导用户的分析。
      const score = (list.find((c) => c.key === 'score') || {}).tip || {}
      check(/不是买入信号|不是买卖信号|筛选辅助/.test(score.warn || ''),
        '综合评分文案明确声明「不是买入信号」', String(score.warn || '').slice(0, 60))
      check(/缺数据|数据不全/.test(score.warn || ''),
        '综合评分文案说明了缺数据的处理方式（不计入总分）')

      // RSI 必须标注「钝化」陷阱（否则会被当成卖出信号用）
      const rsi = (list.find((c) => c.key === 'rsi14') || {}).tip || {}
      check(/钝化/.test(rsi.warn || ''), 'RSI 说明标注了强趋势下的钝化陷阱')
      // Beta 说明要提到与大盘同步的解读口径
      const beta = (list.find((c) => c.key === 'beta') || {}).tip || {}
      check(/大盘|SPY/.test(beta.how || ''), 'Beta 说明讲清「怎么看」（相对大盘放大）')
      // 均线是滞后指标 —— 不标会让用户以为它领先
      const ma = (list.find((c) => c.key === 'ma200_rel') || {}).tip || {}
      check(/滞后/.test(ma.warn || ''), '均线说明标注了「滞后」属性')

      // 页面上必须出现「非买入信号」的免责说明（不能只写在 tooltip 里）
      check(/不是买入信号/.test(html), '页面正文有「不是买入信号」的免责说明')
    },
  },
  {
    // AI 助手是「全平台接入点」的公共 UI —— 它自己白屏就等于所有接入点全废
    name: 'AIAssist',
    entry: `export { default as Page } from ${JSON.stringify(src('components/AIAssist.tsx'))}
export { ToastProvider } from ${JSON.stringify(src('components/ui.tsx'))}
`,
    expect: ['AI 解读', '生成 AI 解读'],
    extra: ({ html, check }) => {
      check(html.includes('让 AI 基于当前页面的真实数据'), 'AIAssist 未运行时渲染出空态引导')
      check(html.includes('不构成买卖信号'), 'AIAssist 自带「不构成买卖信号」免责说明')
    },
  },
  {
    // 回测中心（2026-09-29 小白友好化）
    // 这个页面刚被从 1641 行拆成「编排层 + 10 个组件」，是白屏风险最高的一处；
    // 同时它承载了「术语必须能悬停解释」这个用户需求，所以把术语覆盖面也做成断言。
    name: 'Backtest',
    entry: `export { default as Page } from ${JSON.stringify(src('pages/Backtest.tsx'))}
export { ToastProvider } from ${JSON.stringify(src('components/ui.tsx'))}
export { GLOSSARY } from ${JSON.stringify(src('components/terms/index.ts'))}
export { BEGINNER_STRATEGIES, SYMBOL_PRESETS, BENCHMARK_PRESETS, PERIOD_PRESETS, RECOMMENDED } from ${JSON.stringify(src('components/backtest/presets.ts'))}
export { summarizeResult } from ${JSON.stringify(src('components/backtest/PlainSummary.tsx'))}
`,
    expect: [
      // 四步向导的骨架必须真的渲染出来（用户需求：把配置简化成看得懂的步骤）
      '回测配置',
      '新手模式',
      '一键填入推荐配置',
      '用哪个策略',
      '买哪些股票',
      '回测多长时间',
      '本金与及格线',
      '开始回测',
      // 小白看不懂的两个词，必须换成「带解释的说法」
      '股票代码（标的）',
      '对比基准（及格线）',
      // 空态引导（第一屏看到的东西）
      '第一次用？照这个顺序来',
      // 新手模式下「周期/数据源/成本/止损/仓位」要收起来
      '高级设置（一般不用改）',
      '进阶工具',
    ],
    // 术语悬浮触发器（气泡正文只在 hover 时进 DOM，所以验 aria-label）
    termTips: [
      '策略',
      '标的（股票代码）',
      '初始资金（虚拟本金）',
      '对比基准（及格线）',
      '回测时长',
      '新手模式',
    ],
    extra: ({ mod, check }) => {
      const G = mod.GLOSSARY

      // ---- ① 词条本身要写全「是什么 / 怎么看」----
      const thin = Object.entries(G).filter(([, t]) => !t.what || !t.how)
      check(thin.length === 0, '每个术语都写清了「是什么 / 怎么看」', `缺文案：${thin.map(([k]) => k).join(',')}`)
      check(Object.keys(G).length >= 40, `术语表覆盖足够多的词（${Object.keys(G).length} 个）`)
      // 气泡是纯文本，写 Markdown 强调会显示字面星号
      const md = Object.entries(G).filter(([, t]) =>
        [t.title, t.what, t.how, t.warn].some((s) => typeof s === 'string' && s.includes('**')),
      )
      check(md.length === 0, '术语文案不含 Markdown 语法（否则气泡里显示字面星号）', md.map(([k]) => k).join(','))

      // ---- ② 组件里引用的每个术语 id 都必须存在 ----
      // ⚠️ TermTip / TermIcon 在词条缺失时**会直接抛错**（这是刻意的：写错 id 应该
      //    立刻炸，而不是静默少一个解释）。所以这条断言等于在守「不许白屏」。
      const ids = new Set()
      const btDir = join(root, 'src/components/backtest')
      for (const f of readdirSync(btDir)) {
        if (!f.endsWith('.tsx')) continue
        const raw = readFileSync(join(btDir, f), 'utf8')
        for (const m of raw.matchAll(/<(?:TermTip|TermIcon|TermLabel)\s+id="([a-z0-9_]+)"/g)) ids.add(m[1])
      }
      // 指标分组里的 key 是**动态**传给 TermTip 的（id={k}），正则抓不到，单独解析
      const rp = readFileSync(join(btDir, 'ResultPanel.tsx'), 'utf8')
      for (const m of rp.matchAll(/keys:\s*\[([^\]]+)\]/g)) {
        for (const k of m[1].matchAll(/'([a-z0-9_]+)'/g)) ids.add(k[1])
      }
      const missing = [...ids].filter((k) => !G[k])
      check(missing.length === 0, `回测页引用的每个术语都有解释（共 ${ids.size} 个）`, `缺词条：${missing.join(',')}`)
      // 反向兜底：正则失效会得到 0 个 id，这条断言守住「守卫本身静默失效」
      check(ids.size >= 25, `从 backtest 组件解析出足够多的术语引用（${ids.size} 个）`)

      // ---- ③ 预设值的 key 必须真的存在于后端策略表 ----
      // 写错的后果是「按钮点下去策略下拉框没反应」，界面上毫无报错。
      const backendKeys = new Set()
      const stratDir = join(root, '..', 'backend', 'app', 'strategies')
      for (const f of readdirSync(stratDir)) {
        if (!/^builtin.*\.py$/.test(f)) continue
        const s = readFileSync(join(stratDir, f), 'utf8')
        for (const m of s.matchAll(/^\s*key\s*=\s*"([a-z0-9_]+)"/gm)) backendKeys.add(m[1])
      }
      check(backendKeys.size >= 20, `从后端策略文件解析出策略 key（${backendKeys.size} 个）`)
      const badRec = mod.BEGINNER_STRATEGIES.filter((b) => !backendKeys.has(b.key)).map((b) => b.key)
      check(badRec.length === 0, '新手推荐策略的 key 都存在于后端策略表', `不存在：${badRec.join(',')}`)
      check(
        backendKeys.has(mod.RECOMMENDED.strategyKey),
        `一键推荐配置用的策略 key 存在（${mod.RECOMMENDED.strategyKey}）`,
      )
      check(
        mod.SYMBOL_PRESETS.length >= 3 && mod.BENCHMARK_PRESETS.length >= 3 && mod.PERIOD_PRESETS.length >= 3,
        '标的 / 基准 / 时长三组快捷选项都已提供',
      )
      const periods = mod.PERIOD_PRESETS.map((p) => p.years)
      check(periods.includes(3) && periods.includes(5), '时长预设包含 3 年与 5 年（回测可信度门槛）', periods.join(','))

      // ---- ④ 「一句话结论」的判定逻辑：缺数据必须说缺，绝不能按 0 编造 ----
      // 这是本项目最容易出事的一类 bug：`Number(undefined) → NaN → 兜底成 0`，
      // 界面会显示「同期基准是 +0.0%，你跑赢了」—— 一个完全凭空的结论，
      // 而且构建 / typecheck / 渲染全都拦不住。
      const S = mod.summarizeResult

      const noBench = S({ total_return: 0.3, trades: 5, max_drawdown: -0.2 }, 300, 100000)
      check(noBench.verdict === 'unknown', '记录缺基准数据时结论是「判不了」而不是「跑赢」', noBench.verdict)
      check(noBench.hasBench === false, '缺基准数据时 hasBench=false（界面据此隐藏对比文案）')
      check(
        noBench.caveats.some((c) => /没有存基准/.test(c)),
        '缺基准数据时如实说明「没存这项数据」',
        noBench.caveats.join(' | '),
      )
      check(noBench.cap === 100000 && noBench.finalEq === 130000, '缺 final_equity 时用 初始本金×(1+收益) 兜底', `${noBench.cap}/${noBench.finalEq}`)

      const win = S(
        { total_return: 0.3, benchmark_total_return: 0.1, excess_cagr: 0.05, trades: 60, max_drawdown: -0.1, final_equity: 130000 },
        1200,
        100000,
      )
      check(win.verdict === 'win' && win.enough, '超额为正且样本充足 → 判定跑赢')
      const lose = S(
        { total_return: 0.05, benchmark_total_return: 0.1, excess_cagr: -0.08, trades: 60, max_drawdown: -0.1 },
        1200,
        100000,
      )
      check(lose.verdict === 'lose', '超额显著为负 → 判定没跑赢')
      check(lose.caveats.some((c) => /不值得用真钱/.test(c)), '没跑赢时给出「不值得用真钱去跑」的结论')
      const tie = S(
        { total_return: 0.1, benchmark_total_return: 0.1, excess_cagr: 0.005, trades: 60, max_drawdown: -0.1 },
        1200,
        100000,
      )
      check(tie.verdict === 'tie', '超额在 ±2 个百分点内 → 判定「基本打平」（不把噪声当能力）')
      const thinSample = S({ total_return: 0.3, benchmark_total_return: 0.1, excess_cagr: 0.05, trades: 5 }, 1200, 100000)
      check(!thinSample.enough && thinSample.caveats.some((c) => /只成交了 5 笔/.test(c)), '交易样本 < 30 笔时主动泼冷水')
      // 载入历史记录时主面板本金可能已被改过 —— 必须优先用记录自带的
      const capMismatch = S({ total_return: 0.3, initial_capital: 50000, final_equity: 65000, trades: 60 }, 1200, 100000)
      check(capMismatch.cap === 50000, '初始本金优先取记录自带值（避免用主面板的当前值算错金额）', String(capMismatch.cap))
      const shortRange = S({ total_return: 0.05, benchmark_total_return: 0.02, excess_cagr: 0.03, trades: 60 }, 200, 100000)
      check(shortRange.caveats.some((c) => /不到 2 年/.test(c)), '回测区间 < 2 年时提示区间太短')
      const deepDd = S(
        { total_return: 0.5, benchmark_total_return: 0.1, excess_cagr: 0.1, trades: 60, max_drawdown: -0.45 },
        1200,
        100000,
      )
      check(deepDd.caveats.some((c) => /太深了/.test(c)), '最大回撤 > 30% 时提示「实盘拿不住」')
    },
  },
  {
    // 组合优化（2026-09-29 小白友好化）
    // 这个页面刚被从 861 行拆成「编排层 + components/optimize/*」，白屏风险高；
    // 同时它的核心判断（有没有打赢等权基准）刚被抽成纯函数，必须直接断言。
    name: 'Optimize',
    entry: `export { default as Page } from ${JSON.stringify(src('pages/Optimize.tsx'))}
export { ToastProvider } from ${JSON.stringify(src('components/ui.tsx'))}
export { GLOSSARY } from ${JSON.stringify(src('components/terms/index.ts'))}
export { summarizeOptimize } from ${JSON.stringify(src('components/optimize/PlainSummary.tsx'))}
export { POOL_PRESETS, OBJECTIVE_PRESETS, PERIOD_PRESETS, RECOMMENDED } from ${JSON.stringify(src('components/optimize/presets.ts'))}
export { parseSymbols, parseBudget } from ${JSON.stringify(src('lib/optimizePrefs.ts'))}
`,
    expect: [
      // 四步向导的骨架
      '优化配置',
      '新手模式',
      '一键填入推荐配置',
      '放哪些标的',
      '想要什么效果',
      '用多长历史',
      '限制条件',
      '开始优化',
      // 空态引导（第一屏看到的东西）
      '还没算过权重',
      '第一次用？照这个顺序来',
      // 新手模式下高级项要收起来
      '高级设置（一般不用改）',
      // 快捷池与目标选项真的渲染出来了
      '股债商均衡',
      '最大夏普',
    ],
    termTips: ['组合优化', '标的池', '优化目标', '单标的上限', '总仓位', '新手模式', '起始日期'],
    extra: ({ mod, check }) => {
      const G = mod.GLOSSARY
      const S = mod.summarizeOptimize

      // ---- ① 优化页引用的每个术语 id 都必须存在 ----
      // TermTip / TermIcon 在词条缺失时**会直接抛错**，所以这条断言等于在守「不许白屏」。
      const ids = new Set()
      const scan = (rel) => {
        const raw = readFileSync(join(root, rel), 'utf8')
        for (const m of raw.matchAll(/<(?:TermTip|TermIcon|TermLabel)\s+id="([a-z0-9_]+)"/g)) ids.add(m[1])
      }
      for (const f of readdirSync(join(root, 'src/components/optimize'))) {
        if (f.endsWith('.tsx')) scan(`src/components/optimize/${f}`)
      }
      scan('src/pages/Optimize.tsx')
      const missing = [...ids].filter((k) => !G[k])
      check(missing.length === 0, `优化页引用的每个术语都有解释（共 ${ids.size} 个）`, `缺词条：${missing.join(',')}`)
      // 反向兜底：正则失效会得到 0 个 id，这条守住「守卫本身静默失效」
      check(ids.size >= 12, `从优化页解析出足够多的术语引用（${ids.size} 个）`)

      // ---- ② 优化页专属词条确实进了合并词典（而不是只有回测那本） ----
      for (const k of [
        'portfolio_optimize',
        'equal_weight',
        'effective_n',
        'diversification_ratio',
        'risk_contrib',
        'risk_concentration',
        'efficient_frontier',
        'synthetic_data',
      ]) {
        check(!!G[k], `词典里有优化页专属词条「${k}」`)
      }
      // 等权基准是这一页的判断核心，解释必须点明判断标准
      check(
        /打不过|打不赢|跑不赢/.test(G.equal_weight.how + G.equal_weight.warn),
        '「等权基准」的解释说明了「打不过就直接用等权」这个判断标准',
      )
      // 合成数据的警告不能含糊 —— 它是随机生成的假价格
      check(/随机|假/.test(G.synthetic_data.what), '「合成行情」的解释说清了它是随机生成的假价格')
      // 约束无解时必须说明「这份权重不满足你的原始约束」
      check(/不满足|退回/.test(G.optimizer_infeasible.warn), '「约束无解」的解释警告了退回解不满足原始约束')

      // ---- ③ 预设值必须与后端一致 ----
      const optSrc = readFileSync(join(root, '..', 'backend', 'app', 'engine', 'optimizer.py'), 'utf8')
      const objBlock = (optSrc.match(/^OBJECTIVES\s*=\s*\[([\s\S]*?)\]/m) || [])[1] || ''
      const backendObjectives = [...objBlock.matchAll(/"([a-z_]+)"/g)].map((m) => m[1])
      check(backendObjectives.length >= 4, `从后端解析出优化目标清单（${backendObjectives.length} 个）`)
      const badObj = mod.OBJECTIVE_PRESETS.filter((o) => !backendObjectives.includes(o.key)).map((o) => o.key)
      check(badObj.length === 0, '优化目标快捷选项的 key 都存在于后端', `不存在：${badObj.join(',')}`)
      check(
        backendObjectives.includes(mod.RECOMMENDED.objective),
        `一键推荐配置用的目标存在（${mod.RECOMMENDED.objective}）`,
      )
      // 每个标的池都要能解析出 ≥2 个合法标的（否则按钮点下去等于空池）
      const badPools = mod.POOL_PRESETS.filter((p) => mod.parseSymbols(p.symbols).length < 2).map((p) => p.name)
      check(badPools.length === 0, '每个快捷标的池都能解析出至少 2 个标的', badPools.join(','))
      check(mod.POOL_PRESETS.length >= 3 && mod.parseSymbols(mod.RECOMMENDED.symbols).length >= 2,
        '快捷标的池数量足够且一键推荐的池子有效')
      const periods = mod.PERIOD_PRESETS.map((p) => p.years)
      check(periods.includes(3) && periods.includes(5), '历史区间预设包含 3 年与 5 年', periods.join(','))

      // ---- ④ 自由文本输入的解析必须严格 ----
      check(
        JSON.stringify(mod.parseSymbols('spy, qqq  spy')) === JSON.stringify(['SPY', 'QQQ']),
        '标的解析：大写归一 + 去重 + 保序',
        JSON.stringify(mod.parseSymbols('spy, qqq  spy')),
      )
      check(mod.parseSymbols('SPY QQQ\tIWM').length === 3, '标的解析支持空格/制表符分隔')
      check(mod.parseSymbols('@@@ $$$').length === 0, '标的解析剔除非法字符（不把垃圾当成代码）')
      const bud = mod.parseBudget('SPY:3, TLT:2, bad:-1, GLD:abc')
      check(bud.SPY === 3 && bud.TLT === 2, '风险预算解析出合法项')
      check(bud.bad === undefined && bud.GLD === undefined, '风险预算丢弃负数与非数字（不让 NaN 进求解器）', JSON.stringify(bud))

      // ---- ⑤ 「一句话结论」的判定逻辑 ----
      // 这一页最容易被误读的地方：跑出一组权重，用户要知道它到底值不值得用。
      const base = {
        objective: 'max_sharpe',
        feasible: true,
        symbols: ['A', 'B', 'C', 'D'],
        portfolio: { sharpe: 1.2, effective_n: 3.5, gross: 1.0 },
        benchmark_equal_weight: { sharpe: 0.9 },
        clusters: [],
        synthetic_symbols: [],
      }
      check(S(base).verdict === 'win', '夏普明显高于等权 → 判定打赢')
      check(S({ ...base, portfolio: { ...base.portfolio, sharpe: 0.5 } }).verdict === 'lose', '夏普明显低于等权 → 判定没打赢')
      check(
        S({ ...base, portfolio: { ...base.portfolio, sharpe: 0.92 } }).verdict === 'tie',
        '夏普差在 0.05 以内 → 判定打平（不把估计噪声当成能力）',
      )
      check(S({ ...base, objective: 'equal_weight' }).verdict === 'not_opt', '目标本身就是等权 → 不判「打赢自己」')
      const inf = S({ ...base, feasible: false })
      check(inf.verdict === 'infeasible', '约束无解 → 判定「这不是优化结果」')
      check(inf.caveats.some((c) => /不满足你的原始约束/.test(c)), '约束无解时明确说「不满足你的原始约束」')
      check(
        S({ ...base, portfolio: { ...base.portfolio, sharpe: 0.5 } }).caveats.some((c) => /直接用等权|改用等权|不如/.test(c)),
        '没打赢等权时给出「直接用等权」的结论',
      )

      // ⚠️ 诚实性：缺字段不许按 0 编造（回测页踩过同一个坑）
      const noSharpe = S({ ...base, portfolio: {}, benchmark_equal_weight: {} })
      check(noSharpe.verdict === 'unknown', '缺夏普比率时判定「判不了」而不是「打赢」', noSharpe.verdict)
      check(noSharpe.caveats.some((c) => /缺夏普比率/.test(c)), '缺夏普比率时如实说明缺的是什么')
      check(S(null).verdict === 'unknown', '没有结果时返回 unknown（不抛错）')

      // ⚠️ 合成行情：随机生成的权重没有任何意义
      const synth = S({ ...base, synthetic_symbols: ['A', 'B', 'C', 'D'] })
      check(synth.verdict === 'unknown' && synth.allSynthetic, '全部标的都是合成行情 → 判定不可用', synth.verdict)
      check(synth.caveats.some((c) => /合成|随机生成/.test(c)), '合成行情时给出明确警告')
      const partSynth = S({ ...base, synthetic_symbols: ['A'] })
      check(
        partSynth.verdict === 'win' && partSynth.caveats.some((c) => /A/.test(c)),
        '部分标的合成时仍给结论，但点名是哪几个不可信',
      )

      // 名义分散、实际集中
      const conc = S({ ...base, portfolio: { ...base.portfolio, effective_n: 1.2 } })
      check(conc.caveats.some((c) => /有效标的数/.test(c)), '有效标的数远小于名义数时提示「名义上的分散没有真的发生」')
      check(S({ ...base, clusters: [['A', 'B']] }).caveats.some((c) => /高相关簇/.test(c)), '存在高相关簇时提示伪分散风险')
      check(
        S({ ...base, portfolio: { ...base.portfolio, gross: 0.8 } }).caveats.some((c) => /总仓位/.test(c)),
        '未满仓时提示与满仓基准直接比会失真',
      )
    },
  },
]

// Node 里没有 localStorage：页面可能在 useState 初始化时就读它
const store = new Map()
globalThis.localStorage = {
  getItem: (k) => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => store.set(k, String(v)),
  removeItem: (k) => store.delete(k),
}

const React = (await import('react')).default
const { renderToString } = await import('react-dom/server')
const { MemoryRouter } = await import('react-router-dom')

const results = []
const check = (ok, label, detail = '') => {
  results.push(ok)
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}${!ok && detail ? `  ← ${detail}` : ''}`)
}

// 产物必须落在 node_modules 内 —— 外部依赖（react / react-router / lucide）是
// 运行时 import 的裸包名，Node 从产物所在目录向上找 node_modules。
// 放系统临时目录会 ERR_MODULE_NOT_FOUND；放仓库里又会污染工作区。
const work = join(root, 'node_modules', '.cache', 'qd-render')
rmSync(work, { recursive: true, force: true })
mkdirSync(work, { recursive: true })
try {
  for (const page of PAGES) {
    console.log(`\n================ ${page.name} ================`)
    const entry = join(work, `${page.name}-entry.tsx`)
    const out = join(work, `${page.name}-bundle.mjs`)
    writeFileSync(entry, page.entry)

    await esbuild.build({
      entryPoints: [entry],
      bundle: true,
      format: 'esm',
      platform: 'node',
      outfile: out,
      jsx: 'automatic',
      external: ['react', 'react-dom', 'react/jsx-runtime', 'react-router-dom', 'lucide-react', 'recharts', 'clsx'],
      logLevel: 'error',
    })

    const mod = await import(pathToFileURL(out).href)

    let html = ''
    try {
      html = renderToString(
        React.createElement(MemoryRouter, null, React.createElement(mod.ToastProvider, null, React.createElement(mod.Page, null))),
      )
      check(html.length > 500, `${page.name} 渲染成功（无白屏异常）`, `${html.length} 字符`)
    } catch (e) {
      check(false, `${page.name} 渲染成功（无白屏异常）`, String(e && e.message).slice(0, 200))
    }

    for (const s of page.expect) {
      check(html.includes(s), `${page.name} 渲染出「${s}」`)
    }
    for (const label of page.tips || []) {
      check(html.includes(`aria-label="${label} 指标说明"`), `列头「${label}」挂载了悬浮说明触发器`)
    }
    for (const label of page.termTips || []) {
      check(html.includes(`aria-label="${label} 说明"`), `术语「${label}」挂载了悬浮说明触发器`)
    }
    page.extra({ mod, html, check })
  }
} finally {
  rmSync(work, { recursive: true, force: true })
}

// ============ 文案卫生 ============
// 界面文案是纯文本（不是 Markdown）。写了 `**强调**` 会在页面上原样显示星号 ——
// 实测在提示气泡和告警横幅里都犯过，且构建/typecheck/lint 都不会报。
// 只检查源码里的非注释部分（注释里写 ** 是合法的）。
console.log('\n================ 文案卫生 ================')
const SRC_FILES = [
  'src/pages/Rankings.tsx',
  'src/components/rankings/InfoTip.tsx',
  'src/components/rankings/RankingFilters.tsx',
  'src/components/rankings/RankingsTable.tsx',
  'src/components/rankings/cells.tsx',
  'src/components/rankings/ScoreCell.tsx',
  'src/components/rankings/ScoreSettings.tsx',
  // 榜单页 2026-09-29 拆分出来的两个 UI 片段：文案卫生同样适用
  // （拆分最容易漏的就是「新文件不在检查清单里」—— 于是它里面的文案再没人管）。
  'src/components/rankings/FilterBar.tsx',
  'src/components/rankings/PoolAiReview.tsx',
  'src/lib/rankingColumns.ts',
  // 术语词典（2026-09-29 从 components/backtest/ 提升为 components/terms/ ——
  // 回测页与组合优化页共用同一本词典，优化页去 import backtest/ 下的东西是反向依赖）。
  // 术语气泡文案同样是纯文本，写了 `**强调**` 会在气泡里原样显示星号，
  // 构建 / typecheck 都拦不住。
  'src/components/terms/glossary.ts',
  'src/components/terms/optimize.ts',
  'src/components/terms/index.ts',
  'src/components/terms/TermTip.tsx',
  // 表单排版零件与术语组件（2026-09-29 从 components/backtest/ 提升为共享，
  // 因为组合优化页也要用）。文案卫生同样适用。
  'src/components/form/parts.tsx',
  'src/components/backtest/ConfigPanel.tsx',
  'src/components/backtest/AdvancedSettings.tsx',
  'src/components/backtest/types.ts',
  'src/components/backtest/PlainSummary.tsx',
  'src/components/backtest/ResultPanel.tsx',
  'src/components/backtest/CompareModal.tsx',
  'src/components/backtest/OptimizeModal.tsx',
  'src/components/backtest/FactorModal.tsx',
  'src/components/backtest/HistoryPanel.tsx',
  'src/components/backtest/WatchPicker.tsx',
  'src/components/backtest/presets.ts',
  // 组合优化（2026-09-29 小白友好化）：同一套文案卫生要求
  'src/components/optimize/ConfigPanel.tsx',
  'src/components/optimize/ResultPanel.tsx',
  'src/components/optimize/FrontierTab.tsx',
  'src/components/optimize/PlainSummary.tsx',
  'src/components/optimize/SaveModal.tsx',
  'src/components/optimize/types.ts',
  'src/components/optimize/presets.ts',
]
for (const rel of SRC_FILES) {
  const raw = readFileSync(join(root, rel), 'utf8')
  const code = raw.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '')
  check(!code.includes('**'), `${rel} 的界面文案不含 Markdown 强调语法`)
}

// ============ AI 接入点完整性 ============
// 两条最容易静默出错的路径，构建与 typecheck 都拦不住：
//  ① 任务名拼错 —— 前端照常渲染、点击后后端返回 400「未知 AI 任务」，
//     而页面只显示一句报错，很容易被当成「AI 坏了」；
//  ② 接入点被误删 —— 重构/拆分页面时把 <AIAssist> 顺手删掉，无人发现。
// 这里做静态源码扫描守住这两点。
console.log('\n================ AI 接入点 ================')

/**
 * 任务白名单**从后端解析**，不在这里硬编码。
 *
 * 教训：这份清单曾经是写死的 13 项，后端一加任务就立刻「假失败」
 * （报「xxx 不在注册表内」，但后端其实早就 `_register` 了）。
 * 后端已有的清单，前端一律不要写死 —— 单一事实来源在后端。
 */
const AI_TASKS = (() => {
  const keys = new Set()
  const backendDir = join(root, '..', 'backend', 'app')
  for (const f of readdirSync(backendDir)) {
    if (!/^ai_tasks.*\.py$/.test(f)) continue
    const src = readFileSync(join(backendDir, f), 'utf8')
    for (const m of src.matchAll(/_register\(\s*"([a-z_]+)"/g)) keys.add(m[1])
  }
  return [...keys].sort()
})()

/** 每个接入点：文件 → 必须出现的标记（组件标签或任务名）。 */
const AI_POINTS = [
  ['src/components/AIAssist.tsx', '<Card'],
  ['src/components/NewsPanel.tsx', 'task="news_digest"'],
  ['src/components/CompanyIntel.tsx', 'task="intel_brief"'],
  ['src/components/OrderAiDiagnose.tsx', 'task="order_diagnose"'],
  ['src/components/StrategyAiDraft.tsx', 'task="strategy_draft"'],
  // 行情页 2026-09-29 拆分为「编排层 + components/market/*」后，
  // 侧栏（含 AI 个股快评）搬到了 SidePanel —— 断言跟着走，
  // 同时补一条「页面确实渲染了侧栏」，避免拆完两边都断链却无人发现。
  ['src/pages/Market.tsx', '<SidePanel'],
  ['src/components/market/SidePanel.tsx', 'task="symbol_brief"'],
  // 榜单页 2026-09-29 拆分为「编排层 + components/rankings/*」后，
  // AI 候选池点评（含估值/评分免责说明）搬到了 PoolAiReview —— 断言跟着走，
  // 同时补一条「页面确实渲染了点评卡片」，避免拆完两边都断链却无人发现。
  ['src/pages/Rankings.tsx', '<PoolAiReview'],
  ['src/components/rankings/PoolAiReview.tsx', 'task="ranking_review"'],
  // 回测中心 2026-09-29 拆分为「编排层 + components/backtest/*」后，
  // AI 诊断卡片随结果区一起搬到了 ResultPanel —— 断言要跟着走，
  // 同时补一条「页面确实渲染了结果区」，避免拆完两边都断链却无人发现。
  ['src/pages/Backtest.tsx', '<ResultPanel'],
  ['src/components/backtest/ResultPanel.tsx', 'task="backtest_diagnose"'],
  // 组合优化 2026-09-29 同样拆分为「编排层 + components/optimize/*」，
  // AI 解读卡片随结果区搬到了 ResultPanel —— 断言跟着走，
  // 同时补一条「页面确实渲染了结果区」，避免拆完两边都断链却无人发现。
  ['src/pages/Optimize.tsx', '<OptimizeResultPanel'],
  ['src/components/optimize/ResultPanel.tsx', 'task="optimize_review"'],
  ['src/pages/Risk.tsx', 'task="risk_review"'],
  ['src/pages/Portfolio.tsx', 'task="portfolio_review"'],
  ['src/pages/Dashboard.tsx', 'task="market_briefing"'],
  ['src/pages/AIOps.tsx', '<OrderAiDiagnose'],
  ['src/pages/LiveTrading.tsx', '<OrderAiDiagnose'],
  ['src/pages/Strategies.tsx', '<StrategyAiDraft'],
  // 榜单页的两个新接入点：多选批量分析 + 智能选股
  ['src/pages/Rankings.tsx', '<SelectionToolbar'],
  ['src/pages/Rankings.tsx', '<SmartScreen'],
  ['src/components/rankings/SelectionToolbar.tsx', 'task="stock_batch_review"'],
  ['src/components/rankings/SmartScreen.tsx', "'smart_screen'"],
  // 批准前反方质询 / 交易复盘 / 策略代码审查（未来函数）
  ['src/components/ProposalAiReview.tsx', 'task="proposal_review"'],
  ['src/components/PeriodReviewAi.tsx', 'task="period_review"'],
  ['src/components/strategies/StrategyCodeReview.tsx', 'task="strategy_code_review"'],
  ['src/pages/AIOps.tsx', '<ProposalAiReview'],
  ['src/pages/Portfolio.tsx', '<PeriodReviewAi'],
  ['src/components/strategies/CodeStrategyEditor.tsx', '<StrategyCodeReview'],
  // 情报中心「AI 每日必读」：走统一 aiAssist 入口（任务名必须在后端注册表内）
  ['src/components/intel/DailyDigest.tsx', "aiAssist('intel_digest'"],
]

for (const [rel, marker] of AI_POINTS) {
  const raw = readFileSync(join(root, rel), 'utf8')
  check(raw.includes(marker), `${rel} 仍挂载 AI 接入点（${marker}）`)
}

// 白名单是从后端解析出来的，解析失败（路径写错/正则失效）会得到空数组，
// 那样下面的检查会**全部通过** —— 必须显式守住这个静默失效。
check(
  AI_TASKS.length >= 16,
  `从 backend/app/ai_tasks*.py 解析出任务白名单（${AI_TASKS.length} 个）`,
  AI_TASKS.length === 0 ? '解析到 0 个任务，白名单守卫已静默失效' : '',
)

// 全量扫描 src 下所有 tsx，任何 task="..." 都必须是后端已注册的 key。
// 同时扫 `aiAssist('xxx')` —— 直接调用调用层的接入点（如智能选股要拿结构化结果，
// 用不了通用卡片）同样必须命中注册表，否则点下去只会拿到 400。
const walk = (dir) => {
  const out = []
  for (const e of readdirSync(join(root, dir), { withFileTypes: true })) {
    const rel = `${dir}/${e.name}`
    if (e.isDirectory()) out.push(...walk(rel))
    else if (e.name.endsWith('.tsx')) out.push(rel)
  }
  return out
}
const badTasks = new Set()
for (const rel of walk('src')) {
  const raw = readFileSync(join(root, rel), 'utf8')
  const names = [
    ...[...raw.matchAll(/\btask="([a-z_]+)"/g)].map((m) => m[1]),
    ...[...raw.matchAll(/\baiAssist\(\s*'([a-z_]+)'/g)].map((m) => m[1]),
  ]
  for (const n of names) {
    if (!AI_TASKS.includes(n)) badTasks.add(`${rel}: ${n}`)
  }
}
check(
  badTasks.size === 0,
  `所有 AI 任务名都在后端注册表内（共 ${AI_TASKS.length} 个任务）`,
  [...badTasks].join('；'),
)

// ---- AI 一律手动触发：不得在「打开 / 刷新页面」时自动跑 ----
// 用户要求（2026-09-28）：除后端自身的定时任务（如 Intel 自动监控）外，
// 任何 AI 卡片都必须**点按钮**才生成结论。
// 历史上 4 个接入点带 `autoRun`，其中行情页会在「打开页面 / 每次切换标的」时
// 静默调用 LLM —— 而本项目的推理型模型每次先烧 1800~3200 token 思维链，
// 既费额度又完全出乎用户预期（用户报障原话：不应该一进页面就自己跑）。
// 这里做源码级守卫：src 里除 AIAssist 自身的实现外，不允许出现 `autoRun`。
const autoRunSites = []
for (const rel of walk('src')) {
  if (rel === 'src/components/AIAssist.tsx') continue // 组件自身的 prop 定义与实现
  const raw = readFileSync(join(root, rel), 'utf8')
  if (/\bautoRun\b/.test(raw)) autoRunSites.push(rel)
}
check(
  autoRunSites.length === 0,
  'AI 卡片一律手动触发（src 内无 autoRun 使用点）',
  autoRunSites.join('、'),
)

// ============ 页面初始化健壮性 ============
// 教训（2026-09-29 用户报障「/backtest 页面加载出错」）：
// Backtest 初始化写成 `(prefill.symbols || saved.symbols || ['SPY','QQQ']).join(',')`，
// 而 localStorage 里的 saved.symbols **恒为逗号串** —— 首次访问后每次再进页面都
// TypeError 整页崩。构建 / typecheck / lint 全拦不住（类型上 string[] 与 string 混用）。
// 这里做源码级守卫：凡是对「外部来源的 symbols」调 .join()，必须走规范化函数。
console.log('\n================ 初始化健壮性 ================')
const unsafeSymbolJoin = []
for (const rel of ['src/pages/Backtest.tsx', 'src/pages/Optimize.tsx', 'src/pages/Strategies.tsx']) {
  if (!existsSync(join(root, rel))) continue
  const raw = readFileSync(join(root, rel), 'utf8')
  const code = raw.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '')
  // (a || b || [...]).join(  ← 经典形态：右侧默认值是数组，左侧可能是字符串
  if (/\([^()]*\bsymbols\b[^()]*\|\|[^()]*\)\s*\.join\(/.test(code)) unsafeSymbolJoin.push(`${rel}: (…|| […]).join(…)`)
  // prefill.symbols.join( / saved.symbols.join( ← 直接对外部来源 join
  if (/\b(?:prefill|saved|d|c|r|it)\.symbols\s*(?:\?\.)?\s*\.join\(/.test(code)) unsafeSymbolJoin.push(`${rel}: x.symbols.join(…)`)
}
check(
  unsafeSymbolJoin.length === 0,
  'symbols 一律先规范化再拼接（不许直接 .join）',
  unsafeSymbolJoin.join('；'),
)

const prefsRaw = readFileSync(join(root, 'src/lib/backtestPrefs.ts'), 'utf8')
check(
  /export function symbolsToInput/.test(prefsRaw) && /export function symbolsToList/.test(prefsRaw),
  'backtestPrefs 导出 symbolsToInput / symbolsToList 规范化函数',
)

// ============ 抓取标的持久化（同一类陷阱的第二个实例） ============
// 情报中心「指定标的」把选择存 localStorage。若读取时不规范化，会重演 /backtest 的
// 「首次访问正常、第二次崩」—— 因为 localStorage 里可能是逗号串而不是数组。
// 守卫：读写必须经 lib/intelPrefs（内部复用 symbolsToList），页面不得直接碰 localStorage。
// ⚠️ 断言前**必须剥掉注释**：这些文件的文档里正好写着「localStorage」「interval*1.2」
//    这类字样，不剥就会把「解释这个坑的注释」当成「踩这个坑的代码」（实测踩过）。
console.log('\n================ 抓取标的持久化 ================')
const stripComments = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '')

const intelPrefsPath = join(root, 'src/lib/intelPrefs.ts')
check(existsSync(intelPrefsPath), 'lib/intelPrefs.ts 存在（抓取标的持久化单一入口）')
if (existsSync(intelPrefsPath)) {
  const ip = stripComments(readFileSync(intelPrefsPath, 'utf8'))
  check(
    /export function loadScrapeSymbols/.test(ip) && /export function saveScrapeSymbols/.test(ip),
    'intelPrefs 导出 loadScrapeSymbols / saveScrapeSymbols',
  )
  check(/symbolsToList/.test(ip), 'intelPrefs 复用 symbolsToList 规范化（不自己手搓解析）')
  check(/localStorage/.test(ip), 'intelPrefs 确实是 localStorage 的读写入口')
}

const intelPageCode = stripComments(readFileSync(join(root, 'src/pages/Intel.tsx'), 'utf8'))
check(
  /loadScrapeSymbols/.test(intelPageCode) && /saveScrapeSymbols/.test(intelPageCode),
  'Intel 页经 intelPrefs 读写抓取标的（规范化入口唯一）',
)
check(!/localStorage/.test(intelPageCode), 'Intel 页不直接使用 localStorage（一律走 lib 规范化）')

// 真实风险：把 symbols 从请求体删掉 → 界面能选、后端收不到，静默退回「按家数取前 N 家」。
// 这是「看起来生效、实际没生效」的典型，光看界面测不出来，只能源码级守。
const scrapeCallAt = intelPageCode.indexOf("'/intel/ai-scrape'")
const scrapeCall = scrapeCallAt >= 0 ? intelPageCode.slice(scrapeCallAt, scrapeCallAt + 400) : ''
check(scrapeCallAt >= 0 && /symbols:/.test(scrapeCall), '抓取请求体携带 symbols（界面选了就必须发给后端）')

const monitorCode = stripComments(readFileSync(join(root, 'src/components/intel/MonitorBar.tsx'), 'utf8'))
check(
  /<ScrapePicker/.test(monitorCode) && /pendingSymbols=/.test(monitorCode),
  'MonitorBar 挂载指定标的拾取器，并把后端待抓取清单传进去（不自行推算）',
)
const pickerPath = join(root, 'src/components/intel/ScrapePicker.tsx')
check(existsSync(pickerPath), 'ScrapePicker.tsx 存在')
// 待抓取判定含 interval*1.2 窗口，前端不得自行推算 —— 一旦出现就是口径分叉的开始
check(
  !/1\.2/.test(monitorCode) && !/1\.2/.test(stripComments(readFileSync(pickerPath, 'utf8'))),
  '前端不自行推算「待抓取」（1.2 倍窗口只在后端）',
)

const passed = results.filter(Boolean).length
console.log(`\n${'='.repeat(58)}`)
console.log(`  渲染回归：${passed}/${results.length} 项通过`)
if (passed !== results.length) {
  console.log('  失败项：')
  for (const [i, ok] of results.entries()) if (!ok) console.log(`    - #${i + 1}`)
}
console.log('='.repeat(58))
process.exit(passed === results.length ? 0 : 1)
