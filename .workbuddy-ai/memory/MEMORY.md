# QuantDesk for IBKR — 项目长期备忘（精简索引）

> ⚠️ 本文件**自动注入**，必须短小（超 ~10KB 会被截断）。细节一律放同目录 **`REFERENCE.md`**：
> R3 腾讯字段 · R4 榜单估值 · R5 AI 任务 · R7 候选池 · R9 数据源 · R11 仓库/忽略项 ·
> R12 情报中心 · R13 事件归类 · R14 缓存刷新 · R15 前端/测试陷阱 · **R17 回测中心小白化 · R18 优化页小白化+术语模块**。**需要细节先读它。**

## 1. 铁律（违反即回归失败）
1. 后端只听 `127.0.0.1`；涨红跌绿（`format.ts`）。
2. 无未来函数：第 t 根收盘信号 t+1 根开盘成交（`backtest.py`）。
3. 回测/实盘共用 `StopTracker`（`risk/stops.py`）。
4. `async def` 端点内禁止同步 DB I/O → `run_in_threadpool`（例外：`engine_start`）。
5. `create_all` 不补列/索引 → 老库靠 `database.py::_MIGRATE_*`。⚠️ **`_migrate()` 吞掉所有 ALTER 异常**，
   缺列会静默存在 —— 排查老库怪错先 `PRAGMA table_info(<表>)`。
6. 前端 hooks 必须在 early return 前（React #300 白屏）；`npm run lint:hooks` 已进构建链。
7. 文件规模：软上限 后端/页面 600、组件 400；硬上限 900/600。**一次只拆一个文件，每步跑回归。**
   **规则已可执行**：`run_checks.py size`（棘轮，基线 `tests/size_baseline.json`，重算用
   `tools/gen_size_baseline.py` 且**只在真拆分后跑**）。⚠️ 它报 FAIL **是正确行为**，别顺手重算洗白。
8. datetime naive/aware 混合是**已知接受项**，不要当 bug 报 —— 但**未捕获的 TypeError** 必须修。
9. 覆写整文件前先核对**全部既有导出**（曾两次丢函数）。
10. AI 只有建议权：下单必须 `ai_proposals` + 人工确认。
11. **后端已有的清单，前端一律不硬编码**（数据源清单、AI 任务清单）。
12. **任何「抓全量→覆盖落盘」必须有覆盖率闸门**（`rankings._accept_refresh`：`fresh >= old*0.8`，见 §R14）。
13. **要输出数字前先查 `source == "synthetic"`**：数据链拿不到真实行情会静默回落随机漫步，
    未知/退市标的也能「算出」现价与支撑阻力 —— 那就是编造。取不到就**如实留空**。
14. **AI 一律手动触发**：打开/刷新页面**不得**自动跑（`autoRun` 已从所有页面移除）。
15. **前端路由必须无条件注册**：`main.py` 的 SPA 回退**不能**按 `dist/index.html` 是否存在来决定 ——
    `npm run build` 会先清空 `dist/`，服务若在构建窗口内启动就会**所有前端路由永久 404**
    （重建也不恢复，必须重启后端）。详见 §R15。

## 2. 最容易静默翻车的坑（详解 §R15）
- ⚠️ **沙箱会杀掉 `init_db()`**（轮转备份 DB 时 unlink 被 safe-delete 拦 → SIGTERM + **零输出**）。
  跑 `run.py` / `run_checks.py` 一律 `dangerouslyDisableSandbox`。症状：**同一命令有时成功、有时静默被杀**。
- ⚠️ **visual 脚本的 CDP 端口绝不能写死**：本机保留段含 **9320–9419 / 9120–9219**，写死 9333/9334/9337
  会让四个脚本一起**静默失效**（WinError 10013）。统一用 `scripts/cdp-port.mjs` 的 `await resolveDebugPort()`。
- ⚠️ **祖先带 `backdrop-filter`/`transform`/`contain` 会成为 `position:fixed` 的包含块** → 全屏层/弹窗/tooltip
  **一律 `createPortal` 到 body**。**`Card` 渲染的是 `<section class="card">` 不是 `div`**
  （`querySelectorAll('div')` 会假通过）；`.inp` 带 `@apply w-full` → `w-44` 无效须 `!w-44`；`.card-hd` 必须 `flex-wrap`。
- **token**：`create_access_token(subject: str, extra)`（在 `app/security.py`，**不是 `app.auth`**），
  **返回 tuple `(token, expiry)`** 必须解包 —— 传错会得到坏 token（能打印但登录态静默失效，一路 FAIL）。
- **Git Bash 里 `curl` 探本机要加 `--noproxy '*'`**（本机设了 `http_proxy`，否则报「积极拒绝」会误判成端口没监听）。
- ⚠️ **外部来源字段先规范化再用**：路由 state / localStorage / 后端 `_j()` 解析的 JSON 列都可能是
  「另一种形态」（数组 vs 逗号串）。曾因 `(prefill.symbols || saved.symbols || [...]).join(',')`
  让 /backtest **用一次就永久崩** —— localStorage 里 `saved.symbols` 恒为串。统一走
  `lib/backtestPrefs.ts` 的 `symbolsToList/symbolsToInput`（`test:render` 有源码级守卫）。
- **行为类需求（「不许自动跑」）DOM 断言无效** → 用 CDP `Network` 域数真实请求次数；判定「出结果了」
  要用**只在结果态出现的信号**（按钮文案变化），别用「空态提示消失」。
- ⚠️ **FastAPI 子 router 的 `prefix` 会与父 router 叠加**：`include_router(sub)` 时子 router 只能写
  `/bridge`，写成 `/intel/bridge` 会变成 `/api/intel/intel/bridge/*`。核对路由**必须查 app 级
  `app.openapi()['paths']`** —— `router.routes` 里的 `_IncludedRouter` 没有 `.methods`，用它比对会**静默漏掉子路由**。
- ⚠️ **`Path.glob("dir/**/*.py")` 在本机 Python 上不匹配顶层文件**（会漏 `app/intel.py`）→ 用 `dir.rglob("*")` + 后缀过滤。
- ⚠️ **visual 脚本用持久化 Chrome profile → 会缓存旧 bundle**：`npm run build` 换 chunk 哈希后，
  缓存里的旧 `index.html` 会去 import **已删除的旧 chunk** → 404 → 白屏 → 断言全红 +
  最后 `find(...).click()` 抛 `Uncaught`（**看不懂的堆栈**）。症状：**同一份代码「先跑通过、rebuild 后再跑就红」**。
  已给 6 个 visual 脚本统一加 `Network.setCacheDisabled`。诊断：删掉 profile 目录再跑，能过即缓存问题。
- ⚠️ 本仓库曾出现**另一个会话并行改代码**。动文件前先看时间戳。

## 3. AI 能力接入（AI Task Hub）
**新增 AI 功能一律走统一入口。** 后端 `ai_tasks.py` + 领域模块 `ai_tasks_{market,analysis,ops,screen,strategy,intel}.py`；
新增 = `_b_xxx`(上下文+提示词) + `_l_xxx`(规则兜底) + `_register(...)`，**不改 API 层**。
API `POST /ai/assist {task,payload,model,force_local}`；前端 `lib/ai.ts` + `components/AIAssist.tsx`（**唯一** AI 卡片）。
**当前 17 个任务，清单以 `backend/app/ai_tasks*.py` 为准**（§R5）；`render-check.mjs` 的 `AI_TASKS` 从后端正则解析。
⚠️ `ai_tasks_ops.py`528 / `ai_tasks_analysis.py`499 逼近 600 → **再加任务要新开模块**。
- ⚠️⚠️ **推理型模型 token 预算（勿改小）**：网关 `cn:glm-5.3-flash` 每次先烧 1800~3200 token 思维链。
  实测 2200/3072→**0 字**；4096→截断；**6144→完整**；8192→网关 502。故 `_MIN=_MAX=6144`、
  `_LLM_TIMEOUT=180s`、前端 `ASSIST_TIMEOUT=240s`。这是「AI 返回空」的真正原因。
  网关偶发 502/429 → 降级本地兜底并**如实标注**，属正确行为。
- **本地兜底也不能骗人**：平台没有的字段不拿别的指标顶替，显式写「平台暂无对应字段」。
- `AIAssist.run()` 用 `payloadRef` 取最新 payload（闭包会过期；对象字面量进依赖数组会无限重跑）。

## 4. 数据源 / 本地历史库（细节 §R9）
- 链：`local → ibkr → cache → yfinance → stooq → twelvedata → finnhub`（`prefer` 显式指定时跳过本地库）。
  本地库读侧 `app/hist_store.py`（**只读不写**），写侧 `tools/ibkr_ingest.py`。
  **诚实性铁律：请求区间超出本地覆盖必须返回 None**，绝不用部分数据冒充完整历史（已灌库 4.8~66ms vs 网络 7530ms）。
- ⚠️ **`broker.connected==True` ≠ 数据农场可用**：TWS 报 2103/2105 时 TCP 仍活，`history()`
  **静默返回空且 `error=""`**。灌库器必须**真实请求探活 + 断点续传 + 自动重连**。
- TwelveData 免费档 **8 credits/分、800/天**；finnhub **无 K 线权限**。⚠️ **限流可能是 HTTP 200 + body `{"code":429}`**。
  三个静默坑：`_normalize` **非幂等**；TwelveData datetime 是**无时区墙钟**（须 `tz_localize("America/New_York")`
  后由 `fetch_history` 做**唯一一次**归一化）；`outputsize=5000` 分支**不认 `end`** → 会读到**未来数据**。
- IBKR 管**价格历史 + 实时看盘 + 实盘执行**；**基本面/财报完全没有**。

## 5. 测试与验证
- 后端：`cd backend && .venv/Scripts/python.exe ../tests/run_checks.py [data|strategies|optimize|api|rankings|screener|twelvedata|ai|intel]`
  （`TestClient` 进程内，**无需起服务**；⚠️ 需 `dangerouslyDisableSandbox`）。`data`/`api`/`all` 联网极慢。
- 前端：`npm run typecheck | lint:hooks | build | test:topics | test:render | test:visual | test:visual:settings | test:visual:market | test:visual:intel | smoke`
  （后四个 visual 都要传 `<url> <token>`；`smoke` 需后端）。**只跑 `renderToString` 不算「前端做好了」。**

## 6. 重启服务 / 确认改动生效
- **改后端代码后 8787 不会自动生效**。用户报「AI 报错 / 行为没变」先确认是不是旧进程。
- 重启：① `taskkill //PID <pid> //F`（PID 取 `netstat -ano | grep LISTEN | grep :8787`）
  ② `cd backend && QD_OPEN_BROWSER=0 .venv/Scripts/python.exe run.py > runtime/service_restart.log 2>&1`
  （**必须 `dangerouslyDisableSandbox` + `run_in_background`**）③ `sleep 12` 后查端口 + `curl --noproxy '*' /api/health`。
- **前端改完必须 `npm run build`，8787 直接服务 `dist/`（无需重启后端）。** 端口 **8787**；临时实例避开保留段 **7778–7877**。
  ⚠️ `start.bat` 是**前台阻塞**的，不能用于后台重启。⚠️ 本机 **PowerShell 工具完全无输出**，用 bash 的 `taskkill`/`netstat`。
- 判断后端已加载：进程启动时间 > 源码 mtime。判断前端最新：grep `dist/assets/*.js` 确认新字符串在内。
- ⚠️ **「后台重启任务报 failed」/「查端口说没监听」都可能是假警报**：① 另一重启顶掉旧进程 →
  旧任务收到子进程退出即报 failed，**新进程是好的**；② 重启窗口内旧已死、新未 bind。
  **判据：等 10~15 秒复查端口 + `curl --noproxy '*' /api/health`，再下结论。**
  `> service_restart.log` 是**截断**写入，两进程先后写会得到「头是新 banner、尾是旧日志」的
  混合内容，别据此判崩溃；`tasklist //FI "PID eq N"` 才可靠。`run.py` 是 `reload=False`，
  `Started server process [PID]` 的 PID 就是服务本身。详见 §R15。

## 7. 情报中心（2026-09-29 大改）
- 后端新增 `intel_digest.py`（确定性重要性评分 + 每日必读）、`intel_activity.py`（运行/活动统计）、
  `intel_classify.py`（事件归类/阶段推断）、`api/intel_digest.py`、`ai_tasks_intel.py`（任务 `intel_digest`）；新表 `IntelDigest`。
- 前端 `pages/Intel.tsx` → 薄编排层，拆到 `src/components/intel/`（11 个文件）。
- **抓取范围可选**：「本轮」家数（4/8/12/全部）**或**「指定标的」拾取器（`ScrapePicker`，
  点选顺序=抓取顺序，选择持久化在 `qd.intel.scrape.v1` / `lib/intelPrefs.ts`）。
  后端 `intel.scrape_batch()`：**显式 symbols 即精确批次，不被 limit 截断**。
  「待抓取」唯一事实源 = `overview.stats.pending_symbols`，前端**不得**自行推算 `interval*1.2`。
- 回归：`run_checks.py intel` **104** + `test:render` **104**（含源码级守卫）+ `test:visual:intel` **50**（真实 Chrome）。
- **细节见 §R12（评分/API/计数三义/文件规模）、§R13（归类规则）、§R16（抓取范围）。**

## 8. 前端「人话词典」与共享排版零件（2026-09-29 起）
- **术语悬浮解释只有一个入口**：`components/terms/`（`glossary.ts` 通用+回测 / `optimize.ts` 优化专属 /
  `index.ts` 合并注册表 + `term()` / `TermTip.tsx` 唯一实现）。
  查词**一律走 `index.ts` 的 `term()`**，不要直接 import 领域文件（会漏另一个领域的词条）。
- 词条三段式：**是什么（生活类比）/ 怎么看（可执行动作）/ 注意（只写会导致误判的坑）**。
  数值门槛必须取自后端实现，不许编经验值。正文是**纯文本**，写 `**加粗**` 会在气泡里显示字面星号
  （render-check 的「文案卫生」会拦）。
- ⚠️ 合并词典时**显式检测重名并抛错**：`{...A, ...B}` 裸合并会让后写的词条**静默覆盖**先写的解释。
- 表单排版零件 `components/form/parts.tsx`（`Chip` / `Step` / `Section`）同样共享。
  ⚠️ `Section` 用 `<details>` 折叠时内容**仍在 DOM**（断言「功能没被删」要用 `textContent`，不是 `innerText`）。
- 「小白友好化」的标准三件套：**分步向导 + 新手模式默认开（高级项折叠不删）+ 每个术语可悬停**，
  外加跑前「本次要做什么」的人话预览、跑后一句话结论（判定逻辑**抽成纯函数**供单元断言）。
  已做：回测中心（§R17）、组合优化（§R18）。

## 9. 仓库
- 远端 `git@github.com:louis00009/rich-us.git`（**SSH**；本机 HTTPS 到 github 有 TLS 故障，勿改）。分支 `main`。
  推送 `GIT_SSH_COMMAND="ssh -o BatchMode=yes" git push`。忽略项清单见 §R11。
- 提交前必做**内容级**密钥扫描（`backend/_checks_out.txt` 曾含真 FINNHUB key）→ skill `git-safe-publish`。
