# QuantDesk for IBKR — 详细参考（REFERENCE）

> 本文件**不会**被自动注入，需要细节时手动读。规则与铁律见 `MEMORY.md`。
>
> 索引：R3 腾讯字段 · R4 榜单估值 · R5 AI 任务 · R7 候选池 · R9 数据源 · R11 仓库/忽略项 ·
> R12 情报中心 · R13 事件归类 · R14 缓存刷新 · R15 前端/测试陷阱

## R3. 腾讯行情字段口径（`company.batch_fields`，148 样本验证）
1/46 中英文名；38/43 换手率%/振幅%；**39/47 PE TTM / EPS TTM**（`价÷47==39` 147/148）；**44/45 流通市值/总市值**（亿美元，`==股本×价` 148/148；曾误把 44 当总市值）；48/49 52周高/低；**51 市净率**；**52 股息率%**；62/63 总股本/流通股本。**41/54/55/57–61 未解码，不要用**（57 曾被误判为 ROE）。

## R4. 榜单估值设计
- PE 不落长缓存：缓存原始字段（TTL 1800s，`runtime/cache/us_fundamentals.json`），`PE = 现价 ÷ 缓存 EPS` 实时合成。
- 排序白名单单点定义 `rankings.SORT_FIELDS` → `api/rankings.py` 正则动态生成（两处硬编码不同步曾致 422）。
- 缺失值排序恒排末尾（旧 `or 0.0` 让缺失值顶最前）；设了区间就排除缺该指标的标的。
- 估值色条用蓝→琥珀中性色阶（不用涨红跌绿）。ROE = PB÷PE，上限 300%。PE 分位按同行业、对全集算（筛选前）。

## R7. 候选观察池 / 技术指标
- 模块：`technicals.py`（2 年日线→指标，TTL 3600s）、`scoring.py`（四维评分纯函数）、`ranking_enrich.py`（逐行注入）；`rankings.py` 只抓行情+组装，保留下划线别名（改名静默断测试）。
- **调用顺序硬约束**：注入基本面 → 技术指标 → PE 分位 → 评分 → 筛选 → 排序。
- 两个静默失效坑：① yfinance 单标的也返回 MultiIndex，压平必须在取列前（曾致 Beta 全废）；② `period="1y"` 只 251 根 <252 → `r1y` 全空，已改 `period="2y"`。
- 评分：四维（估值30/质量30/位置20/趋势20）各 0~100 加权。缺数据维度**不计入、权重重归一** + `low_confidence`（绝不当 0 分）；`MIN_DIMS` 只在 `enabled>=MIN_DIMS` 时拦。估值以同行业 PE 分位为主。ROE 30% 封顶。取消勾选=关维度。
- **诚实性铁律**：规则化策略打不过买入持有（SPY +245%），价值在回撤控制 → 任何评分/筛选不得自称「买入信号」（`test:render` 4 条 + `visual-check` 2 条守卫）。
- 候选池必须**服务端**过滤（`score_min`），不能本地 filter 当前页；默认阈值 70（501 只里 52 只达标）。
- **搜索 `q` 绝不能被 `score_min` 挡掉**：`effective_score_min = None if q else score_min`（用户报障「TMO 搜不出来」根因）。
- 搜索匹配：代码精确/前缀（**不是子串**）；名称拉丁按词首、CJK 按子串（`_CJK_RE`）。命中质量作主排序键，返回前 `pop("_match_rank")`；`enrich()`（注入 `name_cn`）必须早于匹配。
- 规模：`rankings.py`596、`pages/Rankings.tsx`**570**（贴 600 软上限，**下次加功能前先拆**）、`technicals.py`396、`scoring.py`275、`ranking_enrich.py`163、`api/rankings.py`114；组件 `RankingsTable`278 / `cells`216 / `ScoreCell`167 / `ScoreSettings`110 / `SelectionToolbar` / `SmartScreen` / `CompanyProfileModal`。

## R5. AI 任务清单（17，以 `backend/app/ai_tasks*.py` 为准）
symbol_brief / news_digest / ranking_review / market_briefing / backtest_diagnose / optimize_review / strategy_draft / risk_review / portfolio_review / order_diagnose / intel_brief / stock_batch_review / smart_screen / proposal_review / period_review / strategy_code_review / **intel_digest**。

结构化输出：`Task.parse` 钩子（`_extract_json`）→ `run_task` 把 text 解析成 `out["data"]`（目前只有 `smart_screen`）。

新任务要点：
- `proposal_review` 先 `_proposal_checks()` **确定性算冲突再给 LLM**（加仓超上限/总敞口/持仓数满/未设止损/限价偏离/RSI 追高/与引擎 bias 矛盾/无仓卖出），提示词固定扮反方；⚠️ `/ops/overview` 的 positions **没有 `weight`**，必须按 `市值/权益` 反推。
- `period_review` 由 `_period_stats()` 出确定性统计，样本 <20 笔必须写「统计意义有限」。
- `strategy_code_review` 用 8 条模式（`shift(-N)`/`pct_change(-N)`/`bfill`/`fillna(method='bfill')`/`rolling(center=True)`/`interpolate()`/`iloc[i+1]`/`[::-1]`）补沙箱盲区（AST 白名单不查时间语义）。
- `intel_digest` 见 §R12。

## R9. 数据源补充
- `Settings.tsx` 降级链曾硬编码 5 项 → 抽出 `components/DataSourcePanel.tsx`，字段全来自后端 `/market/data-source`。前端 `components/TwelveDataKeys.tsx` 自包含（宽度用 `!w-full`/`min-w-0 flex-1`）。
- 诊断 `tools/_probe_twelvedata.py`（人工跑，耗 1~2 credit）。**交叉验证法**：与 yfinance 逐日比 close，**除权日之后应分毫不差**，之前差一个股息额（`auto_adjust=True`，属预期）。
- 本地库依赖 `pyarrow`（未装则回落 CSV）；`tools/migrate_csv_to_parquet.py` 原地转换；`tools/_diag_ibkr.py` 打印 IB 原始错误码+中文释义。

## R12. AI 情报中心升级细节（2026-09-29）
**背景**：用户报「监控总控没有上次运行时间/抓取条数」「下面展示突出不了重点」→ 量化确认：3 天内 587 条事件 1★3 / 2★179 / 3★255 / 4★128 / 5★22，重点被淹；`/intel/events` 从不返回 `stage`。

### 确定性评分
- `app/intel_digest.py`（~510 行）纯函数 `score_event(event, today)` → `{importance, tier, reasons, age_days}`。
- 公式 `(impact/5)*88*freshness*mod`，`mod = 1+(cw-1)*.5+(sw-1)*.5+(src-1)*.5+(sent-1)*.5` 夹在 `[0.92, 1.10]`。
- **`_BASE_MAX=88` + 窄 mod 是关键**：早期 `*100*多项系数` 让 4★/5★ 全饱和 100 → 排序失效；mod 放宽到 `[0.70,1.25]` 又出现 4★ 压 5★ 倒挂。现严格单调：1★16.2–19.4 / 2★32.4–38.7 / 3★48.6–58.1 / 4★64.8–77.4 / 5★81.0–96.8。
- **`_FRESH_FLOOR = 0.80`**：`_freshness` 由 1.0 线性降到 0.80（窗口 3 天），日期未知 0.85。
  原来降到 0.5 → **两天前的 5★ 只剩 54 分被判「可看」**，正是用户抱怨的「重点被埋掉」。
  现窗口内 5★ 恒 ≥ high（最低 88×0.8×0.92 = 64.8）；4★ 在窗口末降为 medium。
- 分档 `TIER_CRITICAL=79 / HIGH=60 / MEDIUM=40`；窗口 `DIGEST_DAYS=3`、`DIGEST_TOP_N=12`、`DIGEST_PER_SYMBOL=2`（critical 免配额）、`_HIGH_IMPACT=4`。
- `_pick_top` 按标的名额挑选；`build_digest(days, symbol, top_n, per_symbol)` → `{date,scope,days,totals,top[],by_symbol[],watch[],notes[]}`。
- ⚠️ `_timing_for()` 的支撑阻力**只能取 `analyze_local(snap,'swing')['levels']['支撑'/'阻力']`**；`market_snapshot()` 里**没有** `levels['支撑']`（只有 `high_52w/low_52w/donchian_*/bb_*/pivot/atr14`），读错返回 None（真实踩过）。watch 上限 8 只；`reduce/avoid` 改写成规避措辞。
- ⚠️⚠️ **必须拦 `source == "synthetic"`**：数据源链路拿不到真实行情时会静默返回合成随机漫步，未知/退市标的也能「算出」现价与支撑阻力 —— 那就是编造。已按既有约定（`api/optimize.py` 告警、`api/trading.py` 拦截）在 `_timing_for` 里拦掉：区间留空 + `note="该标的只有合成行情（无真实数据）…"` + **现价也不展示**，并在清单 `notes` 汇总提示。
- 持久化：`save_digest` / `load_digest` / `ensure_digest` / `digest_llm_context`。

### 表与 API
- 新表 `IntelDigest`（`intel_digests`：digest_date / scope / payload / llm_text / llm_engine / generated_by / event_count / top_count / created_at / updated_at），`create_all` 自动建。
- `GET /intel/digest`（缺则建+落库，首次 ~3.5s，命中缓存 0.01s）、`POST /intel/digest/rebuild`、`POST /intel/digest/record`（**只持久化前端 aiAssist 结果，不调 LLM**）、`GET /intel/digest/history`。
- ⚠️ **别在 intel API 里直接 `run_task`**：第一版写了 `/intel/digest/analyze` 内部调 LLM，违反「全平台 AI 走 `aiAssist` 统一入口」+ render-check AI_POINTS 约定 → 已删除改成 `record`。

### 计数三义（重要）
- run 自报 `events_found` / 按 `run_id` / **按 run 时间窗**。
- 外部 Agent 提交的事件**不带 `run_id`** → `last_run.events_in_db` 显示 0 而库里明明有 524 条。故新增 `app/intel_activity.py` 的 `_run_window()` 出 `events_in_window/analyses_in_window`，UI 展示窗口计数。
- `app/intel_activity.py`（~155 行）：`run_summary(run, db)` / `activity_stats(db, days=7)`（今日/h24/历史 + 7 日 `daily[]` + `last_scrape_at` + `scraped_24h` + `companies_enabled`）/ `last_run(db)`。`agents_seen` 后端返回**已解析 list**（前端类型 `Omit<Run,'agents_seen'> & {agents_seen: string[]}`）。
- `/intel/events` 重写：新增 `min_impact`/`since_days`/`sentiment`/`category`/`stage`/`sort`(`created|importance|occurred`)，助手 `_scored_rows()` 注入 `stage`/`stage_cn`/`importance`/`tier`/`importance_reasons`。
- 调度器 `intel.py` 新增「重活 4」：每个重 tick 都 `build_digest()`+`save_digest(generated_by="scheduler")`（try/except 包住）。

### 前端
- 拆包 `src/components/intel/`：`types.ts`396 / `DailyDigest`**500** / `EventFeed`436 / `Timeline`285 / `MonitorBar`263 / `AiProposals`249 / `BridgeGuide`179 / `CompanyList`176 / `RunsPanel`173。`pages/Intel.tsx` 1335 → **207**（薄编排层）。
- ⚠️ `api/intel.py` 已 **612**、`intel.py` **1474**，均超软上限，下次动它们先拆。
- `MonitorBar.tsx`：6 个固定指标格（上次运行 / 本批抓取·建议 / 今日新增事件 / 近24小时 / 上次抓取 / 累计）+ 7 日 `DailyBars` CSS 迷你柱图。
- `EventFeed.tsx`：重要性优先排序；critical/high 展开大卡片（带「为什么重要」chips），medium/low 折叠成单行；筛选栏 sort/min_impact/since_days/sentiment/category/stage；低影响区可折叠。
- `DailyDigest.tsx`：未读徽标用 `localStorage['qd.intel.digest.seen']`；3 页签（必读清单 / 该盯哪几家 / 买入时机）；`TopItem`/`SymbolRow`/`WatchCard`（关注区间/触发/失效/RSI/ATR）；「AI 深度解读」→ `aiAssist('intel_digest',{digest})` → `POST /intel/digest/record`；常驻免责行；历史 Modal。
- ⚠️ `AIAssist.tsx` 的 `MarkdownLite` 已从 `function` 改 `export function`（DailyDigest 复用）。
- 守卫：`render-check.mjs` AI_POINTS 新增 `['src/components/intel/DailyDigest.tsx', "aiAssist('intel_digest'"]`。

### 回归守卫
- 后端 `tests/run_checks.py intel`（**86 项**）：重要度单调性（N★最好 < (N+1)★最差）、分档与影响度对齐、
  新鲜度不越档、理由非套话、**评论类硬封顶**（5★+财报+权威源也进不了必读）、单标的配额 + critical 免配额、
  清单结构/诚实性（全篇不出现「买入信号/建议买入」）、synthetic 拦截、`_timing_for` 缺数据留空、
  **归类/阶段推断**（含每条反例）、落库 upsert + 清理、接口契约（overview/events/digest history/record，含空解读 400）。
  ⚠️ 该段**先于** TestClient 直连 DB，所以开头必须显式 `init_db()`（TestClient 才走 main lifespan）。
- 前端 `npm run test:visual:intel`（`scripts/visual-check-intel.mjs`，**30 项**，真实 Chrome）：白屏哨兵、总控六格口径、必读区三页签 + 免责、事件流三档分级 + 「为什么重要」+ 默认按重要度排序、**打开页面不得自动调 AI**（CDP 数 `/ai/assist` 次数）、必读卡片标题栏宽 ≥120px、切「买入时机」必须给出内容或如实说明无候选。

### 已知未解 / 待办
- ✅ `intel_events.stage` 覆盖率已由 §R13 的入库口归类规则从 **2% 提到 9.7%**，`category=other` 从 47% 降到 41%
  （剩余未归类多为标题本身无信号，属**可接受**的缺标签；再往上提只能靠改外部 Agent 的提交提示词）。
- 探测新闻时见过 FINNHUB SSL 错误（环境问题，yahoo-rss 仍可用）。
- `intel_analyses.outcome_benchmark` 曾在老库缺失（运行中的服务是加该列之前启动的旧进程，
  `_migrate()` 从没跑过）。已手工 `init_db()` 补上。⚠️ `_migrate()` **吞掉所有 ALTER 异常**，
  缺列会静默存在 —— 排查老库怪错时先 `PRAGMA table_info(<表>)`。
- `render-check.mjs` 原断言 `S&amp;P 500` 已失效（Rankings 改版后徽标变「美股 N」）→ 已改为断言 `美股`。

## R11. 仓库 / 忽略项
- 远端 `git@github.com:louis00009/rich-us.git`（**SSH**）。分支 `main`。首提 `b88b8d8`。
  推送 `GIT_SSH_COMMAND="ssh -o BatchMode=yes" git push`。
- 已忽略：`backend/runtime/*`、`.backup-*/`、`frontend/.cdp-profile/`、`*_checks_out.txt`、
  `node_modules/`、`dist/`、`.venv/`、`runtime/ibkr_bars/*`。
- ⚠️ 只靠 `.gitignore` 会漏真实泄漏 → 提交前必做**内容级**扫描（skill `git-safe-publish`）。

## R13. 事件归类 / 阶段推断（`app/intel_classify.py`，2026-09-29）
**为什么**：`stage` 覆盖率只有 2%、`category` 47% 落 `other`。提交侧不可控 ——
`bridge_guide()` 与内置抓取提示词**早就写了** confirmed/negotiating/rumor 的定义，反复强调仍只有 2%。
所以补齐必须放在**入库口**：所有入库路径（Bridge `POST /events`、内置抓取、autofetch）都过
`intel.add_events`，在那里做归一化，对提交方零要求。

### 接口
- `is_commentary(title, summary="")` / `infer_category(title)` / `infer_stage(title)` / `normalize_event(raw)`。
- `intel.py::add_events()` 里调用 `normalize_event`，⚠️ **必须在算 `dedupe_key` 之前**（key 含 category，
  顺序错了会让「同一事件重复提交」漏判成两条）。
- `intel._event_row()` 返回 `commentary` 字段 → 前端 `EventItem.commentary`。

### 设计边界
- **只补空，绝不覆盖**：提交方给了值就尊重提交方（它的原文上下文比标题全）。
- **宁缺勿猜**：规则命中才写，不命中留空 / 留 `other`。缺标签可接受，**错标签不可接受** ——
  `stage` 会经 `STAGE_WEIGHT` 影响重要度排序，错标一个 `confirmed` 就是给噪音加权。
- **只用标题判**：摘要是数百字正文，几乎必然出现「或将/可能/计划」这类对冲词，拿摘要判阶段会把
  「已签署」误判成传闻（实测过）。阶段是**标题级**判断。
- **评论类不归类**：媒体评论/行情播报/分析师调价不是公司事件。
- 不推断 `sentiment` / `impact`：这两项提交方覆盖率已 100%，且属于**判断**而非**归类**。

### 调参纪律（踩过的坑，改规则前先读）
1. **短英文词必须加 `\b`**：`ship` 会命中 `Starship`，`wins` 会命中 `winsome`。
2. **中文没有词边界，通用名词不能用**：`客户`（"跨客户数据暴露率"）、`供应`（"供应约束"）、
   `订单`（"借特斯拉订单发起挑战"）、`收入`、`授权`（"服务预先授权"）都会误命中。只用**专指短语**。
3. **单字不能进规则**：`已`、`拟`（命中"**虚**拟"）、`通过`（"通过率"）曾让准确率崩掉。
4. **别收 `不可抗力`**（几乎只出现在合同/融资结构披露里，曾把一份收益率披露误归成 regulatory）。
5. **财季代号要锚定**：`FY26Q4` 可以，光写 `Q[1-4]` 会命中 `Q.E.P` → 用 `\bFY\d{2}\s*Q[1-4]\b` 这类形式。
6. **对冲词否决**：`infer_stage` 命中 confirmed 后还要过 `_SPECULATIVE_RE`（有望/或将/预计/接近/拟/计划/
   may/could/plans），有对冲词就**不判 confirmed**，返回 None。
7. **listicle 头部允许一个修饰词**：`3 AI Stocks With…` 里数字后面不是 `Stocks` 而是 `AI`，
   漏掉就会被 `\brevenue\b` 归成 earnings → 头部写成 `^\s*\d+\s+(?:\S+\s+)?(?:stocks?|…)\b`。
8. 改完必须跑 `tests/run_checks.py intel` —— 里面钉住了「规则不得误判」的样例，每条反例都对应一次真实误判。

### 效果（3280 条真实事件）
- dry-run：category 改 181（product_launch 57 / earnings 55 / personnel 28 / partnership 25 / regulatory 11 /
  macro 3 / model_release 2），stage 改 221（confirmed 199 / negotiating 13 / rumor 9），
  357 条判为评论，1 条因 `dedupe_key` 冲突跳过。
- 落地后：`category=other` 47% → **41.2%**；`stage` 覆盖 2% → **9.7%**。
- 回填工具 `tools/intel_backfill_classify.py`（**默认 dry-run**，`--apply` 写库）。
  只补空；改 category 时**同步重算 `dedupe_key`**；新 key 已被占用则**跳过该行**（绝不合并/删数据）；**幂等**（第二遍 0 改动）。

### 评论类的重要度封顶（`intel_digest._COMMENTARY_CAP = 34.9`）
- 评论类**硬封顶**到 34.9（严格低于 `TIER_MEDIUM=40`）→ **永远进不了必读清单**。
  为什么封顶而不是乘系数：系数会被 `impact` 这个主导项放大 —— 「3 AI Stocks With Revenue Growth」
  若判 4★，乘 0.5 仍有 32 分，再叠类别/来源加成就能挤进必读。
- `score_event` 里命中即**直接返回**单条理由「媒体评论/行情播报，非公司自身事件（不参与重点判定）」，
  不再叠加其他理由（否则用户会以为评分出错）。
- `by_symbol` 的 `positive/negative/high_impact` 也**不计入评论类**，与必读口径一致。
- 前端：`EventFeed` 折叠行加「媒体」标记；筛选栏加**内容类型** `media`（`""`/`exclude`/`only`）；
  汇总条显示「媒体评论 N」。⚠️ `media` 不是 DB 列（现算），所以启用该筛选时后端要**多取一批**
  （`limit*12` / `limit*4`），否则过滤后凑不满。
  `_scored_rows(..., by_importance=)`：⚠️ **只有 `sort=importance` 才允许重排**，否则 `sort=created`
  在「多取一批后截断」时会被悄悄改成按重要度排序。

## R14. 缓存刷新铁律
`rankings._bg_refresh` 曾**无条件覆盖**：yfinance 部分超时（228/503）时把 503 只覆盖成 228，**静默无报错**。
- 闸门 `_accept_refresh(fresh, old)`：`fresh >= old*0.8` 才覆盖，拒绝时写 `_refresh_state["error"]`。
  `fundamentals._bg_refresh` 用 `{**old, **fresh}` 合并，天然安全。
- 榜单只数变少先查 `runtime/cache/sp500_quotes.json`，**不要**查 `app/markets/sp500.json`
  （成分股，503 从未变）；`refresh_constituents()` 是死代码。
  恢复：直接调 `_fetch_all_quotes()` + `_save_disk()`（~72s）。

## R15. 前端 / 测试陷阱（完整清单）
- **`.inp`**（`index.css`，位于 `@tailwind utilities` **之后**，`@apply w-full`）→ `<Input>`/`<Select>` 上
  普通 `w-44` 无效，必须 `!w-44`。
- **表格外层 `overflow-x-auto` 会裁 `<th>` 内绝对定位气泡** → `createPortal` + `fixed`。
- ⚠️ **祖先带 `backdrop-filter`/`transform`/`will-change`/`contain` 会成为 `position:fixed` 的包含块**
  → `inset-0` 不再是视口（真实踩过：`SelectionToolbar` 子树里的 `<Modal>` 只显示成一条）。
  **`ui.tsx::Modal` 已改 `createPortal(…, document.body)`；新写全屏层/弹窗/tooltip 一律 portal 到 body。**
  守卫：`visual-check.mjs` 第 6 段。
- **`.card-hd` 必须带 `flex-wrap`**（右侧 actions `shrink-0`、左侧标题 `min-w-0`，窄栏里副标题会
  **每行一个字**竖排）。守卫：`visual-check-market.mjs` 断言 `header > div` 宽 ≥120px。
- **`Card` 渲染的是 `<section class="card">`，不是 `div`** —— `querySelectorAll('div')` 会命中外层栏容器，
  导致断言**假通过**。
- 文案字符串不是 Markdown，`**强调**` 会显示字面星号。新字段要做回落，否则老后端显示 `undefined`。
- ⚠️⚠️ **visual 脚本的 CDP 调试端口绝不能写死**：Windows 保留端口段（本机含 **9320–9419**、9120–9219）
  里的端口 `bind()` 直接失败（WinError 10013），表现为 Chrome 进程活着但 devtools 起不来、
  只报含糊的「调试端口未就绪」。**仓库原写死的 9333/9334/9337 全踩中，四个脚本一起静默失效。**
  已统一改用 `scripts/cdp-port.mjs` 的 `await resolveDebugPort()`（探测 + `QD_CDP_PORT` 覆盖），候选 9222 起。
  查保留段：`netsh interface ipv4 show excludedportrange protocol=tcp`。
- ⚠️ Git Bash 里 `curl` 探本机端口要加 `--noproxy '*'`（本机设了 `http_proxy`，否则报
  「upstream connection failed / 积极拒绝」，会误判成端口没监听）。
- 三个 visual 脚本都要传 `<url> <token>`；token 现造：`create_access_token(username, {'uid': id})`
  （**签名是 `(subject: str, extra)`**，在 `app/security.py`，且**返回 tuple `(token, expiry)`** ——
  传 dict 会得到坏 token，能打印但登录态静默失效，一路 FAIL）。
- **行为类需求（「不许自动跑」）DOM 断言无效** → 用 CDP `Network` 域数真实请求次数。
  判定「出结果了」要用**只在结果态出现的信号**（按钮文案 `生成快评`→`重新生成`），别用「空态提示消失」。
- ⚠️ **CDP 的鼠标坐标是视口坐标 → 悬停类断言必须先 `scrollIntoView`**。真实踩过：
  `visual-check.mjs` 的「悬停列头弹气泡」只量了 `<th>` 的 rect 就直接派发 `mouseMoved`，
  排行榜页在表格**之上**有 5 个面板（PremarketPanel/MoversMonitor/PickCenter/SmartScreen/RankingFilters），
  表头默认在首屏之外 → 鼠标事件落在屏幕外 → 检查变成**恒假失败**（面板增补后 silently 变红，
  很容易被误读成「功能坏了」）。修法：先 `th.scrollIntoView({block:'center'})` + sleep，**再重新量** rect，
  并断言 rect 真的落在视口内（否则后面的断言没有意义）。
  同类风险：任何 `getBoundingClientRect()` 之后直接派发鼠标/点击事件的检查。
- ⚠️ **后端 `run_checks.py` 会被前台超时杀掉**：`intel` 段会为 watch 清单逐个取量化快照（走网络，
  yfinance 每标的可达 20s），服务同时在跑时很容易超过工具默认 120s → 进程被 SIGTERM、
  输出文件只写到一半。**用 `run_in_background` 跑**，不要在前台等。
- ⚠️ **`npm run build` 会先清空 `dist/`，而 8787 直接服务 `dist/`** → 构建那几秒里访问页面会
  500，服务日志报 `RuntimeError: File at path ...frontend/dist/index.html does not exist`。
  **这是构建窗口的正常现象，不是服务坏了** —— 别急着重启后端。判断方法：`ls frontend/dist/index.html`
  是否已重新出现 + mtime 是否比 `src/**` 新。
  同理：若 `find frontend/src -newer frontend/dist/index.html` 有输出，说明有人的改动**还没构建**，
  **不要替别人构建**（可能把半成品编进产物），先确认那是谁的在途改动。
- ⚠️⚠️ **SPA 回退绝不能按「产物是否存在」条件注册**（2026-09-29 真实事故，全站 404）：
  `main.py` 原写法是 `if (FRONTEND_DIST / "index.html").exists():` 里才注册 `/` 与
  `/{full_path:path}`，否则只注册一个返回 JSON 占位的 `/`。
  而 `npm run build` **会先清空 `dist/`**（vite `emptyOutDir`）→ 只要服务是在**构建窗口内**启动的，
  那一刻 `index.html` 就不存在 → 回退路由**永远不注册** → 之后 `/intel`、`/rankings` 等**全部 404**，
  浏览器只看到 `{"detail":"Not Found"}`（截图取证时极易误判成「前端白屏/前端崩了」），
  而且**重新构建也不会恢复 —— 必须重启后端**。
  修法：**无条件注册**回退路由，把「产物是否就绪」推迟到**请求时**判断
  （`_frontend_index()`：就绪返回 `FileResponse`，未就绪返回**可操作**的 503 + 「请执行 npm run build，
  无需重启后端」）。`app.mount("/assets", ..., check_dir=False)` 同理 —— 目录此刻可能还不存在。
  ⚠️ 顺带一个 FastAPI 坑：处理函数返回注解写成 `FileResponse | JSONResponse` 会让 FastAPI 尝试
  当 Pydantic 响应模型解析并**启动即崩**（`FastAPIError: Invalid args for response field`）→
  装饰器上必须加 `response_model=None`。
  守卫：`run_checks.py intel` 里断言 `/{full_path:path}` 在 `app.routes` 中 + 产物缺失时返回 503
  且提示含 `npm run build`。
- ⚠️ **改后端后重启服务要挑时机**：若同时在 `npm run build`，就会踩到上面那条（构建清空 dist →
  服务按「未构建」启动）。**先确认 `dist/index.html` 存在，再启动服务。**
- 测试里遍历 `app.routes` 会误判（惰性 `_IncludedRouter` 不展开）→ 用 `inspect.signature(get_endpoint)`
  或静态扫 `app/api/*`。
- ⚠️ **沙箱会杀掉 `init_db()`**：它轮转备份 DB 并 unlink → `sitecustomize.py` safe-delete 拦截 →
  进程被 SIGTERM 且**零输出**。所以 `run.py` 与 `run_checks.py` 都要 `dangerouslyDisableSandbox`。
  典型症状：**同一命令有时成功、有时静默被杀**（极易误判成 flaky 测试）。
- ⚠️ 本机 **PowerShell 工具完全无输出**；从 bash 调 `powershell.exe` 被安全策略拒 →
  用 bash 的 `taskkill`/`netstat`/`tasklist`（`wmic` 在本机也返回空）。
- ⚠️ 本仓库曾出现**另一个会话并行改代码**。动文件前先看时间戳。


---

## R16. 抓取范围：家数 vs 指定标的（2026-09-29）

**用户诉求（原话）**：「我肯定每天都是需要跑的…你要么在运行的时候让我选择具体跑哪家，
而不是随机选择 4 家，我可能有重点要跑的，或者我可能就选一家跑。」

### 两种模式（互斥，界面明示）
| 模式 | 触发 | 请求体 | 批次 |
|---|---|---|---|
| 自动 | 未选任何标的 | `{symbols:[], limit:4\|8\|12\|0}` | 从**待抓取清单**取前 N 家（`0`=全部） |
| 指定标的 | 勾了 ≥1 家 | `{symbols:[...], limit:0}` | **就是勾选清单**，点选顺序 = 抓取顺序 |

- 后端核心是**纯函数** `app/intel.py::scrape_batch(symbols, pending, limit)`：
  `if symbols:` 直接用它（**不截断**）；否则 `pending if limit<=0 else pending[:max(1,limit)]`。
  抽成纯函数就是为了能单测（`run_checks.py intel` 有 9 条）。
- ⚠️ **曾经的 bug 就是这个**：前端把家数写死 4 → 用户看到「0/4 家」以为剩下 28 家被漏掉。
  分批本身没错（单家 = 1 次新闻聚合 + 最多 2 次 LLM 调用，推理型模型每次先烧 1800~3200 token），
  **错在没告诉用户、且无法表达「只跑这几家」**。
- API 侧归一化 `api/intel.py::_norm_scrape_symbols`：大写/去空格/**保序去重**/夹到 `_SCRAPE_MAX=60`；
  **非序列输入一律按空**（防止把 `'NVDA,MSFT'` 当成一个标的代码）。

### 「待抓取」的唯一事实源
`GET /intel/overview` → `stats.pending_symbols: string[]`（与 `tasks_pending` **同一次查询**得出，
不得两次各算）。判定含 `interval_minutes * 1.2` 窗口 → **前端一律不自行推算**，
`render-check.mjs` 有源码级守卫禁止前端出现 `1.2`。

### 前端
- `lib/intelPrefs.ts`：`loadScrapeSymbols()` / `saveScrapeSymbols()`，键 `qd.intel.scrape.v1`。
  **复用 `backtestPrefs.symbolsToList`**（同一类「外部来源 symbols」陷阱，不复制第二份实现）。
  兼容 `{symbols:[...]}` / `{symbols:'A,B'}` / 裸数组三种历史形态。
- `components/intel/ScrapePicker.tsx`：搜索 + 快捷（全选待抓取/全选启用/清空）+ 筹码点选
  （选中带 ①②③ 序号 = 抓取顺序）+ 「抓取顺序：A → B → C」确认行 + 耗时预估（0.5~1.5 分钟/家）。
  待抓取筹码带琥珀点；停用标的**仍可勾选**（显式指定优先于 `enabled`）。
- `MonitorBar.tsx`：已选时**禁用**「本轮」家数并说明原因（避免「勾了 7 家却只跑 4 家」）；
  面板渲染条件 `pickerOpen || picked`，且 onChange 里 `if (!list.length) setPickerOpen(true)`
  —— **清空后保持展开**（用户多半想换一批，不是让面板消失）。
- 文件规模：加完功能 `MonitorBar` 涨到 432 > 组件软上限 400 → 把 `Metric`/`DailyBars`
  抽到 `components/intel/MonitorMetrics.tsx`（53 行），回到 384。

### 验证（都是实测，不是「应该能跑」）
- 单测：`scrape_batch(["nvda"," msft "], pool, 1) == ["NVDA","MSFT"]`（limit 被忽略）等 9 条。
- **live**：`POST /intel/ai-scrape {"symbols":["NVDA"],"limit":0}` → job `total=1`、note「正在抓取 NVDA」；
  `{"symbols":["msft"," aapl ","MSFT"],"limit":4}` → `total=2`（去重/大小写/空格都归一，limit 被忽略）。
- 浏览器：`test:visual:intel` 50 项（含「点选一家→计数 1」「刷新后仍在」「清空后回到自动模式」）。

### 守卫（render-check.mjs「抓取标的持久化」段，10 项）
`intelPrefs` 必须导出两函数且复用 `symbolsToList`；Intel 页**不许出现 `localStorage`**；
请求体必须带 `symbols:`（删掉会静默退回「按家数取前 N 家」，界面看不出来）；
前端不许出现 `1.2`。
⚠️ **这些「禁止型」守卫必须先剥注释** —— 否则会被「解释这个坑的注释」命中（本轮真踩了两次）。

---

## R17. 回测中心「小白友好化」重构（2026-09-29）

### 用户诉求（原话）
「回测中心对于我（小白）来说太难用了 …… **基准标的和标的**我理解不了，希望把这套东西
尽可能简化、设计得易于理解，并且**针对一些词汇都有鼠标悬浮的解释**。」

### 落地形态：三件事，不是换皮
1. **四步向导**：`① 用哪个策略 → ② 买哪些股票 → ③ 回测多长时间 → ④ 本金与及格线`。
   术语全部换成带解释的说法：`标的 → 股票代码（标的）`、`基准标的 → 对比基准（及格线）`、
   `数据周期 → 数据周期（K线周期）`、`佣金 → 手续费`。
2. **新手模式（默认开）**：必填项留在外面，其余（周期/数据源/成本/止损/仓位 + 三个进阶工具）
   收进 `<details>` 折叠区。关掉开关 = 原来的全量专业面板，**功能一个没删**。
   ⚠️ 用 `<details>` 而不是条件渲染，内容始终在 DOM —— SSR 断言才验得到「没被删」。
3. **术语悬浮解释**：`glossary.ts`（56 词，按「是什么 / 怎么看 / 注意」三段）+
   `TermTip.tsx`（`TermTip` 行内虚线下划线 / `TermIcon` 问号 / `TermLabel` 标签）。
   覆盖配置项、全部 23 个结果指标、交易明细列、三个进阶工具。
   ⚠️ `TermTip` 在词条缺失时**直接抛错**（刻意）：写错 id 应该立刻炸，而不是静默少一个解释。

### 文件拆分（铁律 9）
`pages/Backtest.tsx` **1641 → 491 行**，UI 拆到 `components/backtest/`：
`glossary.ts`(344) `presets.ts`(90) `types.ts`(66) `TermTip.tsx`(105) `parts.tsx`(91)
`ConfigPanel.tsx`(399) `AdvancedSettings.tsx`(147) `PlainSummary.tsx`(178+) `ResultPanel.tsx`(287)
`HistoryPanel.tsx`(156) `OptimizeModal.tsx`(372) `CompareModal.tsx`(333) `FactorModal.tsx`(188)
`WatchPicker.tsx`(116)。
- 状态**全部留在 Backtest.tsx**（prefill / localStorage / 参数记忆三条写入路径的唯一真相）；
  子组件是纯受控展示件。唯一例外：各弹窗自持自己的运行态。
- `types.ts` 存在是为了**打断 ConfigPanel ↔ AdvancedSettings 的循环引用**。
- `size_baseline.json` 已把 `Backtest.tsx: 1641` 摘掉（真拆分 → 棘轮奖励）。

### ⚠️ 顺带修掉的诚实性缺陷（本轮最有价值的发现）
「一句话结论」原按 `Number(undefined) → 0` 处理缺失字段 → 旧历史记录没有
`benchmark_total_return` / `excess_cagr` 时，页面会显示
**「同期基准是 +0.0%，你跑赢了」** —— 一个凭空编出来的结论，
构建 / typecheck / lint / SSR **全都不报**。
修法：`summarizeResult()` 抽成**纯函数**，先 `Number.isFinite` 判「有没有这个字段」再决定说不说；
缺数据时 verdict = `unknown`（「判不了」）+ 明说缺数据。
另外 `初始本金` 优先取 `metrics.initial_capital`（载入历史记录时主面板的 capital 可能已改）。
> 铁律 13 的又一次实例：**取不到就如实留空，绝不拿 0 顶替。**

### 顺手修掉的小口径错误
指标表原给**所有**百分比指标传 `withSign=true` → 「年化波动 +9.26%」「平均持仓比 +13%」
带加号。波动/持仓比是**大小**不是**盈亏**，加号会误导。改为只对
`total_return / cagr / excess_cagr / best_month / worst_month` 带符号。

### 行为改动（需知情）
- 因子诊断弹窗**打开不再自动跑**：旧实现是「点按钮 = 打开 + 立刻发起长耗时请求」，
  现在必须点「开始诊断」。用 CDP `Network` 域断言 `factor-ic` 请求数为 0。
- 「一键填入推荐配置」：双均线趋势跟踪 · SPY · 近 5 年 · 本金 10 万 · 及格线 SPY。
  `RECOMMENDED.strategyKey` 必须存在于后端策略表（render-check 从
  `backend/app/strategies/builtin_*.py` 解析 key 后断言）。

### 回归（全绿）
`typecheck` / `lint:hooks` / `build` / `test:topics`(10/10) /
`test:render` **161/161**（新增 Backtest 页 42 项，含 `summarizeResult` 的 11 条纯函数断言）/
`test:visual:backtest` **45/45**（新增，`scripts/visual-check-backtest.mjs`）。
`test:visual:settings` 13/13、`test:visual:intel` 51/51。
⚠️ `test:visual:market` 15/16（`no-watchlist-card`）与 `run_checks.py size` 的
Market/Rankings 两项 FAIL **都不是本轮引入的** —— 是并行会话在改 Market/Rankings
（Market.tsx 972→1017、Rankings.tsx 656→658，时间戳晚于本轮）。已按规矩**不重算基线**
（重算等于把别人的增长洗白）。

### 新增守卫（`render-check.mjs`）
- 文案卫生清单加入 `components/backtest/*`（气泡文案里的 `**` 会显示成字面星号）。
- `AI_POINTS`：`task="backtest_diagnose"` 随结果区搬到 `ResultPanel.tsx`，
  并补一条 `pages/Backtest.tsx 仍渲染 <ResultPanel>`，防「拆完两边都断链」。
- 术语覆盖面：正则扫 `components/backtest/*.tsx` 里所有
  `<TermTip|TermIcon|TermLabel id="...">` + 解析 `ResultPanel` 的 `keys: [...]`（动态 id 抓不到），
  逐个断言存在于 `GLOSSARY`；并反向断言「解析出的 id ≥ 25」防守卫静默失效。
- `summarizeResult` 纯函数断言：缺基准→unknown、缺 final_equity 兜底、±2pp 判打平、
  样本<30 泼冷水、本金取记录自带值、区间<2年、回撤>30%。

---

## R18. 组合优化页「小白友好化」+ 术语/排版模块提升（2026-09-29 深夜）

承 R17（回测中心小白化）。用户只说了一句「可以 继续做吧」，于是把同一套做法复制到优化页。

### 一、先把共享模块从业务目录里提出来（**前置动作，不是顺手**）
优化页要用回测页那本术语词典和那套排版零件，直接 `import 'components/backtest/...'` 是
**反向依赖**，迟早各自漂移出一份副本。所以先搬：

| 原位置 | 新位置 | 行数 |
|---|---|---|
| `components/backtest/glossary.ts` | `components/terms/glossary.ts` | 351（通用+回测） |
| —（新建） | `components/terms/optimize.ts` | 187（优化专属 25 条） |
| —（新建） | `components/terms/index.ts` | 50（合并注册表 + `term()`） |
| `components/backtest/TermTip.tsx` | `components/terms/TermTip.tsx` | 102 |
| `components/backtest/parts.tsx` | `components/form/parts.tsx` | 94（Chip/Step/Section） |

⚠️ **合并词典必须显式检测重名并抛错**：`{...A, ...B}` 裸合并会让后写的词条**静默覆盖**先写的
解释，界面上毫无报错。第一次合并就抓到一处（`interval` 两处都有），已删重。
⚠️ 搬完要 `grep -rn "<旧路径>" scripts/` —— render-check 的 `SRC_FILES`（文案卫生）与 entry
导出路径都要同步，漏了会**静默少检查一批文件**。

### 二、优化页 861 → 345 行
拆成 `components/optimize/`：`ConfigPanel`(341) / `ResultPanel`(370) / `FrontierTab`(70) /
`PlainSummary`(307) / `SaveModal`(62) / `presets`(92) / `types`(100)。
新增 `lib/optimizePrefs.ts`（标的池与风险预算的**严格解析** + 配置持久化）、
`lib/dateRange.ts`（`yearsAgo`，从 `backtest/presets.ts` 提出 —— 两个页面都要用，
复制一份等于让「`toISOString` 是 UTC、东八区凌晨会得到昨天」这个坑各自漂移一次）。

### 三、三件套（照搬回测页）
1. **四步向导**：`① 放哪些标的 → ② 想要什么效果 → ③ 用多长历史 → ④ 限制条件`。
2. **新手模式默认开**：协方差估计 / 期望收益估计 / 相关簇阈值 / 单簇上限 / 风险预算 /
   仅做多 / 有效前沿 / 无风险利率 / 数据周期 收进 `<details>`，关掉即平铺 —— **功能一个没删**。
3. **术语悬浮**：新增 25 条优化词条，**数值门槛全部取自后端实现**（`_OBJECTIVE_META` /
   `_COV_META` / `portfolio_stats`：分散化比率 = Σwσ/σ_p、有效标的数 = 1/HHI、
   风险集中度 = max|rc|/|Σrc|、默认阈值 35%/100%/85%/50%），不是编的经验值。

### 四、判定核心 = 有没有打赢等权基准
页面自己的注释就写着「打不过就别优化」。抽成纯函数 `summarizeOptimize`：

| 条件 | verdict |
|---|---|
| 全部标的是合成行情 | `unknown`（**不可用**，必须明说） |
| 缺 `portfolio.sharpe` 或 `benchmark_equal_weight.sharpe` | `unknown`（**绝不按 0 编造**） |
| `feasible === false` | `infeasible`（退回解**不满足原始约束**） |
| `objective === 'equal_weight'` | `not_opt`（等权没有「打赢自己」可言） |
| 夏普差 > +0.05 / < −0.05 / 其余 | `win` / `lose` / `tie`（±0.05 内是估计噪声，不是能力） |

另给 6 类 caveat：部分标的合成、约束无解、目标即等权、有效标的数 < 名义数一半、
存在高相关簇、未满仓（与满仓基准比会失真）。

### 五、新增守卫
- `render-check.mjs` 新增 Optimize 条目，总数 **163 → 232**（+69）。含 21 个术语 id 全覆盖、
  优化目标 key 与后端 `OBJECTIVES` 对齐、标的池可解析性、自由文本解析
  （大写归一/去重/保序/剔除垃圾/丢弃 NaN 预算）、**15 条 `summarizeOptimize` 纯函数断言**。
- `scripts/visual-check-optimize.mjs`（`npm run test:visual:optimize`）**44/44** 真实 Chrome。
- 新断言当场暴露 3 个问题并已修：① `termTips` 要写**词条的 title**（我写了「开始日期」，
  词条 title 是「起始日期」）；② 「没打赢等权」这句结论原本在 JSX 里、纯函数断言不到 → 移进
  `caveats`；③ 新写的 `PlainSummary` 有个 `**加粗**` 漏进模板字符串（被文案卫生检查抓住）。

### 六、规模债
`size_baseline.json` 摘掉 `Optimize.tsx: 861`（与前一日的 `Backtest.tsx: 1641` 同理），
存量债 **27 → 21**。`run_checks.py size` 仍报 `Market.tsx`(972→1017) / `Rankings.tsx`(656→658)
FAIL —— **并行会话的改动**，按规矩**不重算基线**（把别人的增长写进基线 = 让棘轮失效）。
已把这条判断写进 `TODO.md` 铁律 9。

### 七、回归
`typecheck` / `lint:hooks` / `build` 绿；`test:topics` 10/10；`test:render` **232/232**；
`test:visual:optimize` **44/44**、`:backtest` **45/45**、`:settings` **13/13**、`:intel` **51/51**；
`run_checks.py size` 无新增超限文件。

### 八、仍未做
`Market.tsx`(1017，超硬上限) 与 `Rankings.tsx`(658) 的拆分**属于并行会话**，本轮没碰。
其余存量债见 `size_baseline.json`。
