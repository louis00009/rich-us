# QuantDesk for IBKR · 项目长期记忆

## 定位
本地单机量化平台（IBKR 美股/ETF）。FastAPI+React，单端口 8787。工作区 `C:\Users\Louis\Desktop\IBKR`。

## 设计铁律
1. 实盘三重锁：`QD_ALLOW_LIVE_TRADING` → 运行时解锁 → `guardrails.py` 逐笔护栏。
2. 风控字段须登记 `state.RISK_COLUMNS`；止损状态机唯一 `risk/stops.py::StopTracker`。
3. 无未来函数：t 收盘信号 t+1 开盘成交；回测新开仓当根不查止损。
4. 涨红 #e11d48 / 跌绿 #059669，集中 `frontend/src/lib/format.ts`。
5. 数据源降级链 IBKR→缓存→yfinance→Stooq→合成；synthetic 前端必须告警（`app/providers/` 包）。
6. 策略沙箱 `strategies/custom.py` AST 白名单是安全边界，改任一环重跑自检。
7. 包内延迟导入必须 `from ..`（拆包单点 ImportError 被 try/except 吞 = 监控瘫痪）；机械抽取带行数锁。

## 核心不变量
- 护栏只准 `state.build_guard_context`；模式只认 `state.effective_mode()`。
- weight 必过 `sizing.cap_targets`；data_provider 单飞 `_inflight` dict，绝不加锁。
- `_normalize(naive_tz=)` 默认 UTC，缓存合并用 None；年化用 `metrics.periods_per_year()`。
- 长任务走 `engine/jobs.py`；IBKR 事件循环线程唯一 `_ensure_loop`+锁；实时引擎每 tick `_live_limits()` 重读风控。

## 命令
`start.bat/stop.bat`；backend `.venv/Scripts/python.exe run.py`；frontend `npm run typecheck && build && smoke`；
自检 `tests/run_checks.py [data|strategies|optimize|api|rankings|screener|ai|td|intel|correct|size|all]`。
修数值 bug 补 correct 节断言。运行数据 `backend/runtime/`，`.env` → `backend/runtime/.env`。

## IBKR 适配层 `brokers/ibkr.py`
独立线程+专属事件循环 `run_coroutine_threadsafe`。阻塞方法必须 Async 变体；`ib.sleep`→`self._sleep`；协程 `self._await`、同步 `self._call`。陷阱：`account=...` 存 `self.account_id` 勿写回 `self.account`。免费源仅 60 天分钟线，日内回测必须 IBKR。

## 组合优化 `engine/optimizer.py`
纯 numpy（无 scipy/cvxpy 勿引入）。协方差去均值、期望收益用原始收益；放宽约束必须暴露 `effective_max_weight`；求解后必须 `project()`；`_ascend_bb` 用 BB 步长；标的<2 或交易日<40 → 400；save 代码过 AST 白名单。

## 榜单缓存 `app/cacheio.py` + universe
写一律 `atomic_write_json`，读 `load_json_snapshot`，冷启动 `ensure_seed`。池 ≈2241 只；api.nasdaq.com 封 python TLS → `refresh_mcap_extra` 用 subprocess curl；NDX 表头带角标须子串匹配。company.enrich 冷却 60s/300s。

## 开盘监控 `movers.py`
行情 TTL 180s + stale-while-revalidate + 覆盖率闸门 0.8；quotes_updated≠updated；force=true 手动重抓；movers_monitor 自恢复。P0：模块级缓存赋值要 global；线程要 `.start()`；测试打桩 yfinance 走真函数。

## AI 情报中心（`app/intel/` 包 + `intel_digest*.py` + `api/intel*.py`）
- 实时刷新铁律：add_events/add_analysis 挂钩 `refresh_async`（session_scope 外调用）；GET /digest 走 `refresh_if_stale`（30s 节流）；并发合并 `_refresh_lock`+`_refresh_pending`。
- **时效两档曲线（09-30）**：`intel_digest_scoring._freshness(age, impact)` —— 5★ 特别重大缓衰减 (1.0,0.9333,0.8667,0.80) 豁免；其余陡衰减 (1.0,0.88,0.66,0.45)，4★ 第 3 天掉 low，reasons 带「时效衰减：已隔 N 天」。旧 0.80 统一下限 =「必读永远旧闻」根因。
- 排序：critical 配额 2；`_fold_families` 同(标的,发生日)留最高；totals.today 按入库本地日。
- **全部新闻视图（09-30）**：DailyDigest 第 4 页签「全部新闻」→ `digest/NewsFlow.tsx`（`GET /intel/events?sort=created&since_days=N`，自含取数+30s 轮询），必读为空时页签仍可见。
- Bridge token 以 `backend/runtime/bridge_token.txt` 为准。Google News RSS 并发整批 0 → 串行+0.4s。bridge/analysis 请求体 `{"agent","analyses":[...]}`；events 单批 ≤100。端点 400 必须 `e.read()` 读 body。
- LLM 必带 `reasoning_effort="low"`（否则 HTTP 200 正文空）；预算 5000/补试 6000，上限 6144。新增调用 grep `_llm_call(` 逐个检查。
- `session_scope` 是 `autoflush=False`：同批插入后查重前显式 `flush()`。
- 加列必须登记 `database.py _MIGRATE_COLUMNS`。验证闭环：horizon 分档窗口 + SPY 超额收益对账；verify 三段式（网络调用不进写事务）。
- **测试残留（TESTZZ/TIMECHK 等）会占必读/brief 排序**，跑完 run_checks 需清真实库残留（09-30 清过 5 条）。
- 监控补强（09-30）：`_check_surge` 价格异动联动（surge_pct 默认 3%，≥7%→5★）；`pinned_symbols` 重点标的优先抓；`/intel/live` + `/intel/scrape-log`。
- run_checks 插断言前先 `grep "^def test_"` 确认节归属（intel 是独立节 `run_checks.py intel`，correct 节跑不到 intel 评分断言）。

## 服务重启
- 服务必须带系统代理；`QD_OPEN_BROWSER=0`。拉起：PowerShell(dangerouslyDisableSandbox) `Start-ScheduledTask QuantDeskServer`，轮询 `/api/health`。
- 热更两步：先杀 8787 监听进程再 Start-ScheduledTask（对运行中任务是 no-op）；验证看进程 StartTime。PowerShell stdout 被吞 → 写临时文件 bash cat。
- `Start-Process`/后台拉起的进程 ~5–10 分钟被会话回收，别反复代拉。
- safe-delete 护栏对 unlink 抛 SystemExit(1)：清理路径捕 BaseException。

## 调试坑
- 测 127.0.0.1 必须 `--noproxy "*"`；bash `cd` 常被剥离用绝对路径；`/tmp` 不可写用 `backend/runtime/tmp/`。
- Edit 偶发假成功：改完 grep 验证。多会话并行会互覆文件，每步改完立即验证。
- pandas 3.0：弃 stack/unstack 用 np.fmax。前端 build 不跑 tsc。`include_router` 惰性：枚举路由走 `app.openapi()`。

## 待扩展
实盘实时引擎 · 期权模块 · Black-Litterman/Ledoit-Wolf · 付费数据源 · 事件日市场反应(event study) · 多引擎观点交叉面板。
