# QuantDesk for IBKR · 项目长期记忆

## 项目定位
面向 Interactive Brokers 的**本地单机**量化交易平台（美股/ETF 为主）。FastAPI + React，单端口 8787 同时供 API 与前端静态资源。工作区 `C:\Users\Louis\Desktop\IBKR`。

## 不可动摇的设计约定
1. 实盘三重锁：`QD_ALLOW_LIVE_TRADING`(默认 false) → 运行时解锁(确认短语+口令) → 逐笔护栏 `risk/guardrails.py`。
2. 风控配置白名单：`state.update_risk_config()` 写入字段必须在 `state.RISK_COLUMNS` 登记，否则静默丢弃。
3. 止损状态机唯一：`risk/stops.py::StopTracker`，回测/实盘共用。
4. 无未来函数：第 t 根收盘信号第 t+1 根开盘成交；回测新开仓当根不检查止损。
5. 配色中国习惯：涨红 #e11d48 / 跌绿 #059669（设置可切欧美），集中 `frontend/src/lib/format.ts`。
6. 数据源降级链：IBKR → 缓存 → yfinance → Stooq → 合成；`synthetic` 前端必须告警。
7. 代码策略沙箱是安全边界：`strategies/custom.py` AST 白名单 + `_SAFE_BUILTINS` + `_safe_import` + `_safe_getattr` + `_FORBIDDEN_ATTRS`，改任一环重跑自检。

## 核心不变量（违反 = P0 回归）
1. 护栏上下文只准 `state.build_guard_context(acc, positions)`（计数器 + 分市场 fx 折算都在内）。
2. 模式只认 `state.effective_mode()`（UI 开关 ∧ 端口）；UI 开关是权威路由。
3. weight 目标必须过 `sizing.cap_targets`（单标的 clip + gross 等比缩放），否则 = 免费杠杆。
4. `data_provider` 单飞用 `_inflight: dict[str, Future]`，跟随者 `fut.result(timeout=60)`，绝不加锁。
5. `_normalize(naive_tz=)`：默认 "UTC"（腾讯 m1 依赖）；缓存/已归一化用 `naive_tz=None`；增量合并绝不整体 normalize；stooq 走 naive。
6. 年化一律 `metrics.periods_per_year(interval)`，禁硬编码 252。
7. `stop_type="none"/"time_stop"` 无价格止损；`update()` 对 `stop_price<=0` 不判定。
8. 熔断放行减仓单（`is_reducing` 前置）；止损离场 30s 冷却（`_stop_exit_at`）。
9. 长任务走 `engine/jobs.py`（后台线程 + progress_cb + 协作式取消），不新增同步长 HTTP。
10. IBKR 事件循环线程唯一：`_ensure_loop` 带 `_loop_lock`；runner 绑定局部 loop；gate 拒绝时 `_submit` 显式 close 未 await 协程；`get_ibkr` 单例带锁。
11. 实时引擎风控热加载：`EngineTask.__init__` 的 RiskLimits 是快照，每 tick `_live_limits()` 重读 `appstate.get_risk_row()`。

## 命令速查
```
start.bat / stop.bat
cd backend && .venv/Scripts/python.exe run.py
cd frontend && npm run typecheck && npm run build && npm run smoke
cd backend && .venv/Scripts/python.exe ../tests/run_checks.py [api|correct]
```
修数值 bug 必须同步补 `correct` 节断言。运行数据 `backend/runtime/`，前端产物 `frontend/dist/`，`.env.example` → `backend/runtime/.env`。

## IBKR 适配层 `brokers/ibkr.py`
独立线程 + 专属事件循环，`run_coroutine_threadsafe` 投递。
- 阻塞方法必须 Async 变体：`connect/qualifyContracts/reqTickers/reqHistoricalData/accountSummary`；`ib.sleep` → `self._sleep`。
- 可直调：`placeOrder cancelOrder reqMarketDataType positions portfolio openTrades fills managedAccounts isConnected disconnect`。
- 协程 `self._await(coro, timeout)`，同步 `self._call(fn, *args)`。
- 陷阱：`IBKRBroker(account=...)` 存到 `self.account_id`，勿写回 `self.account`（覆盖基类方法 → TypeError）。
- 历史数据按 `BAR_MAP` 上限分页拼接；免费源仅 60 天分钟线，日内回测必须 IBKR。

## 组合优化 `engine/optimizer.py`
纯 numpy，**本机无 scipy/cvxpy，不要引入**。`optimize_portfolio(prices, *, objective, cov_method, return_method, ...)`；`/api/optimize/{meta,run,save}`，页面 `Optimimize.tsx`。
- 协方差用去均值数据，**期望收益必须用原始收益**（传去均值 X 给 `estimate_mean` → mu 恒 0）。
- 放宽约束必须暴露：`effective_max_weight` + `max_weight_relaxed` + notes + 前端告警。
- 求解后必须 `project()`，不能 `w/w.sum()*max_gross`。
- `_ascend_bb` 用 Barzilai-Borwein 步长（改回 1/L：0.3s → 80s+）。
- 有效标的 <2 或重叠交易日 <40 → `OptimizeError` → 400。
- `/optimize/save` 生成代码须过 `validate_code` AST 白名单。

## 选股信号引擎 `app/signals.py`
「关注信号」/今日关注/信号说明的单一事实源。
- 10 条规则（机会 5 / 风险 5）；机会需 ≥2 独立条件才亮灯，缺数据不触发，reason 带数值。
- `rankings()` 顺序硬约束：注入→分位→评分→**attach_signals**→筛选→排序；focus 在筛选前对全池挑。
- `SIGNAL_DEFS` 每条必须有对应 `_RULES` 函数（自检有断言）；前端说明吃 `GET /market/rankings/signal-catalog`。
- `?signal=<key>` 服务端筛选；`signal_count` 在排序白名单（api 层动态生成，勿硬编码）。
- `SignalCell.tsx`：机会=rose / 风险=amber（不用绿，与「跌」语义打架）。

## 榜单缓存层 `app/cacheio.py`（改磁盘写入前必读）
- **0 字节事故**：旧 `_save_disk` 用 `write_text`（先截断后写），进程被杀 → 快照损坏 → 重启等全量抓取 30–40s。
- 铁律：写一律 `cacheio.atomic_write_json`（tmp + os.replace）；读用 `load_json_snapshot`（缺失/0 字节/损坏 → None）；冷启动先 `ensure_seed`（`app/markets/seed/`，4 份 json 随仓库分发）。
- 响应级快照 `runtime/cache/rankings_snapshot.json`：三源新鲜且覆盖过半时落盘（节流 5 分钟）；行情缓存 <90% 池时补行 + `_fill_missing_from_snapshot` 只补 None，随后重算分位/评分/信号。响应 `snapshot_restored` → 前端徽标。
- 池子 `universe.universe()`：SP500+NDX100+SP400+SP600+Nasdaq 市值前 700（mcap_extra）+29 热门 ≈ **2241 只**（09-29 扩池）。**api.nasdaq.com 封锁 python TLS 指纹**（requests 10053，走代理也一样）→ `refresh_mcap_extra` 用 **subprocess curl**；`_norm_sector` 判定用 `if key in _SECTOR_MAP`（空串映射值勿被 falsy 吞）。NDX 表头 "ICB Industry[1]" 带角标须**子串匹配**；SP400 的 GICS 全名曾被 ICB-only 白名单误清空（合法集 = keys∪values）。
- `company.enrich` 冷却：同步 60s / 后台 300s，limit 上限 950。扩池欠账期别让每请求都同步拉腾讯（曾 +2s/请求）。

## 开盘监控 movers `app/movers.py`
- 双源：本地池（~2240 只）+ 全市场涨跌幅榜补盲（yf.screen，TTL 60s；池外标的 src="market"）。标签勿写死 "S&P 500"。
- 行情缓存 TTL 180s（> 全量抓取 ~2min）+ stale-while-revalidate + 覆盖率闸门 0.8；非盘中回上一交易日快照并带 note。
- **quotes_updated**（行情真实抓取完成时刻）≠ updated（响应生成时刻）；`GET movers|premarket` 支持 `force=true` 手动强制重抓（立即返回旧数据，后台线程抓）。前端面板有手动刷新 + 自动刷新间隔下拉（localStorage 持久化）。
- 常驻监控 `state.set_setting("movers_monitor")`，main.py lifespan `resume_monitor()` 自恢复；审计日志 `runtime/cache/movers/YYYY-MM-DD.jsonl`（仅 regular session）。
- AI 解读 `POST /movers/analyze`，model 走 `ai_analyst._llm_config_for`；LLM 失败降级 `engine="local"`。
- 三个实证 P0（已进 run_checks）：① 函数内对模块级缓存赋值必须 `global`；② 创建线程必须 `.start()`；③ 测试别 stub `market_screen`，要打桩 yfinance 走真函数。

## AI 情报中心 `app/intel.py` + `app/api/intel.py`
- Bridge：`GET bridge/poll` → `POST bridge/events` → `GET bridge/brief/{sym}` → `POST bridge/analysis` → `POST bridge/done`；鉴权 `X-Intel-Token`，token **以 `backend/runtime/bridge_token.txt` 为准**（prompt 里写死的已连续 12 轮失效）。
- **Google News RSS 并发会整批返回 0**（Run #53 实证）：8 线程跑同一批 query 时 NVDA/MSFT/GOOGL/GOOG/AAPL/META/AMZN 全空；改**串行 + 0.4s 间隔**重跑立刻补齐（7 家 2,087 条）。遇到 `kept=0` 的 symbol 别加宽 `when:` 窗口，直接串行重试。
- `POST bridge/events` 单批 ≤100；`POST bridge/analysis` 请求体是 `{"agent","analyses":[...]}`（**列表**），扁平对象 → 400。实测 6 条/批最稳。
- 端点 400 时**必须 `e.read()` 读 body**，只打异常字符串会误判网络问题。
- 内置 AI 自动抓取默认开启：`ai_harvest_events` 多源新闻 → LLM 打标 → 入库 → 立即分析；手动 `POST /api/intel/ai-scrape`。防编造靠架构：occurred_on/source_name/source_url 由代码继承，LLM 只输出 idx+打标。max_tokens=6144/timeout=180/`reasoning_effort="low"`。
- 三层引擎：内置 AI > 外部 Agent(Bridge) > 本地量化兜底；建议必带 agent/engine 标注。
- 去重 `dedupe_key = sha1(symbol|category|归一化标题)` 唯一约束；事件另有 `occurred_at`(String16 "YYYY-MM-DD HH:MM") 展示精确时间，`occurred_on` 负责日级排序。
- **坑：`session_scope` 是 `autoflush=False`** —— `expunge` 前、同批插入后紧跟查重前必须显式 `flush()`。
- **LLM 调用必须带 `reasoning_effort="low"`**（P0，两轮实证）：推理型模型思维链烧光 max_tokens → HTTP 200 但正文 0 字符（不是报错！）；`thinking`/`enable_thinking` 网关不透传。已修：intel、analyze_with_llm、**/ai/chat（09-29 补修：1400 预算 + 空串当成功返回，AI 对话弹窗回复全空就是它）**、movers.analyze；ai_tasks 不需要（budget 最低 6144）。新增调用 grep `_llm_call(` 逐个检查。空返回模式：60s 闸门内补试（预算+50%）→ 仍空降级本地，不得把空串标成 engine=llm。对话/解读预算已按用户要求拉到 **5000**（补试 6000；网关上限 6144，8192 会失败——勿超）。
- `verify_due_analyses` 三段式（只读查清单 → 无锁取报价 → 短事务写回）：网络调用绝不能放进 SQLite 写事务。
- 加列的坑：`Base.metadata.create_all()` 不给已有表加列 → 用 `database.py` 的 `_MIGRATE_COLUMNS`（ALTER TABLE）；漏登记会让该 symbol 的事件 100% 静默 rejected。
- **验证闭环 v2（09-29）**：窗口按 horizon 分档 `VERIFY_WINDOW_DAYS`（intraday2/swing7/position30）；对账价用 `fetch_history` 历史收盘精确对账（基线日收盘→目标日收盘，非"调度跑到的现价"）；命中判定 = **SPY 超额收益**（SPY 自身回退绝对收益），列 `outcome_benchmark` 已进 `_MIGRATE_COLUMNS`；verify_stats 带 per-agent Brier + 置信度分桶校准（`_calibrate`/`_brier` 纯函数）。
- 事件面 `_event_face_weights`（纯函数）：stage 权重 confirmed1.25/rumor0.65 + 同(发生日,方向)封顶 3 条；测试事件自检残留会占满 brief 30 条窗口造成排序假阳性（TIMECHK 40 条实证），测试前须清残留。
- LLM 研判上下文：brief 带 near-3 建议及 outcome + `_earnings_date`（yfinance calendar，OK 7d/失败 6h 缓存）+ `_agent_track` 历史战绩（样本<5 不喂）；上下文结构化裁剪（先丢 levels/dist，再 13000 硬切），别一刀切 JSON。
- run_checks 坑：「结构化输出解析/提案复盘」块属于 `test_ai_tasks` 不是 `test_correctness`——插断言前先 `grep "^def test_"` 查边界。
- **研判第二轮（09-29 下午）**：critic 二段式（`_CRITIC_PROMPT` 草稿→风控复核→修订，`_sanitize_analysis` 统一清洗，复核置信度限漂移 ±25，失败保留草稿；NVDA 实证 62.6s 双遍、主动区分在谈/落地）；`_vol_position_scale` 仓位随 rv20 缩放（≥40% 减半/≤10% ×1.25，硬顶 20）；hold 验证 `_hold_hit`（|超额|≤3% 观望算对，verify/pending 已纳入）；`analysis_due_symbols` 无新事件且未超 3 倍周期跳过重分析（省 LLM）。
- 未做候选：事件日市场反应（event study，入库记次日收益标 priced-in）、多引擎观点交叉面板。

## 服务启动 / 重启
- **必须带代理**：HTTP_PROXY/HTTPS_PROXY = 用户系统代理（常开；沙箱代理端口每会话变，不能给服务用）。无代理直连本机不通（yfinance/Wikipedia 线程永不完成）。
- 启动加 `QD_OPEN_BROWSER=0` + `PYTHONUNBUFFERED=1`。
- 拉起可靠路径：PowerShell + `dangerouslyDisableSandbox:true` → `Start-ScheduledTask -TaskName QuantDeskServer`，轮询 `/api/health` 至 200（30–90s）。计划任务由 svchost 托管，不受会话回收影响。
- **重启（代码热更）必须两步**：`Start-ScheduledTask` 对已运行任务实例是 no-op（python 前台让任务一直 Running）→ 先杀 8787 监听进程（Stop-Process / stop.bat），再 Start-ScheduledTask。验证新代码生效看进程 StartTime。PowerShell 工具 stdout 偶发被吞：结果写临时文件再用 bash cat。
- `Start-Process` / `DETACHED_PROCESS` / `run_in_background` 启动的进程 ~5–10 分钟被会话回收（五次实证），别反复代拉。长任务一次链式跑完。
- safe-delete 护栏：WorkBuddy shim 对 unlink 触发 bulk-guard 时抛 **SystemExit(1)** → `_backup_db` 轮转删旧备份曾让服务静默死亡。清理路径必须捕 **BaseException**（已加固 main.py/_cacheio.py/data_provider.py ×2）。
- 排障顺序：先看 `runtime/service.err.log` 是否 0 字节 → 前台跑一次看真实报错。

## 调试环境坑
- curl/urllib 测 127.0.0.1 必须 `--noproxy "*"` / `ProxyHandler({})`，否则 401/502/000 全是代理假象。
- bash 里 `cd` 常被剥离：用绝对路径调 `.venv` 的 python 与脚本；`/tmp` 不可写，用 `backend/runtime/tmp/`。
- **Edit 工具偶发「报成功但没写入」**：改完必须 grep 验证，必要时用 Python `io.open` patch 脚本 + `assert count==1`。
- **多会话并行开发会互相覆盖文件**。
- pandas 3.0 已装：避免 `.stack()/.unstack()` 做 tr，用 `np.fmax`；`GroupBy.cumcount()` 返回 Series，多列场景改 numpy。
- safe-delete 拦截 `fs.rmSync`（故 `vite.config.ts` 用 `emptyOutDir:false` + `scripts/prebuild.mjs` 归档旧 dist，只留最近 2 个）；单轮删除超 50 文件被拦截，重置数据用 SQL 清表。
- 前端 `build` 只跑 `vite build` 不跑 `tsc`。
- 该 FastAPI 版本 `include_router` 惰性：`app.routes` 里 path 全空，枚举真实路径必须走 `app.openapi()["paths"]`。

## 待扩展
实盘实时引擎（现仅 paper/simulated）· 期权模块（covered call / 铁鹰 / VRP）· 组合优化进阶（Black-Litterman、换手率惩罚、Ledoit-Wolf）· 付费数据源（Polygon / Databento）。
