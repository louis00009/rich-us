# QuantDesk for IBKR · 项目长期记忆

## 项目定位
面向 Interactive Brokers 的**本地单机** AI 量化交易平台。
工作区：`C:\Users\Louis\Desktop\IBKR`。
用户交易品种以**美股 / ETF** 为主。

## 不可动摇的设计约定（修改代码前必读）

1. **实盘三重锁必须保留**
   ① 环境变量 `QD_ALLOW_LIVE_TRADING`（默认 false）
   ② 运行时解锁（确认短语 + 口令）
   ③ 逐笔风控护栏（`risk/guardrails.py`）
   任何重构都不得绕过或简化这三层。

2. **风控配置的可写字段白名单**
   所有通过 `state.update_risk_config()` 写入的字段必须在 `state.RISK_COLUMNS` 中登记，
   否则会被静默丢弃（曾因遗漏 `kill_switch` 导致熔断失效）。

3. **回测与实盘共用同一止损状态机**
   `risk/stops.py` 的 `StopTracker` 是唯一实现，禁止在回测或实盘中另写一套。

4. **无未来函数**
   第 t 根 bar 收盘生成的信号只能在第 t+1 根 bar 开盘成交。
   回测中新开仓当根不检查止损（`entry_bar == i` 时跳过）。

5. **配色遵循中国习惯**
   涨 = 红（#e11d48），跌 = 绿（#059669），可在设置中切换为欧美习惯。
   实现集中在 `frontend/src/lib/format.ts`。

6. **数据源三级降级**：yfinance → Stooq → 合成行情。
   返回 `synthetic` 时前端必须显示警告条（非真实数据）。

7. **代码策略沙箱是安全边界**
   `strategies/custom.py` 的 AST 白名单 + `_SAFE_BUILTINS` + `_safe_import` + `_safe_getattr`
   + `_FORBIDDEN_ATTRS`（文件 I/O 接口）都在防护链路内，修改任一环都要重新跑自检。

## 命令速查

```bash
# 启动
start.bat                                     # Windows 一键（建环境+装依赖+构建+启动）
cd backend && .venv/Scripts/python.exe run.py  # 手动

# 前端构建 / 类型检查
cd frontend && npm run build
cd frontend && npm run typecheck

# 自检（202 项）
cd backend && .venv/Scripts/python.exe ../tests/run_checks.py
cd backend && .venv/Scripts/python.exe ../tests/run_checks.py optimize   # 只跑组合优化
cd backend && .venv/Scripts/python.exe ../tests/run_checks.py api        # 只跑 API（99 项）

# 组合优化真实行情端到端演示（需服务已启动）
cd backend && .venv/Scripts/python.exe ../tests/optimize_e2e.py

# 前端渲染检查（需服务已启动，账户需为 trader/QuantDesk#2026）
cd frontend && npm run smoke
```

## 组合优化模块（`engine/optimizer.py`）—— 改动前务必阅读

纯 numpy 实现，**本机没有 scipy / cvxpy，不要引入**。

- 对外主函数：`optimize_portfolio(prices, *, objective, cov_method, return_method, ...)`，
  `prices` 为 `index=日期, columns=标的, values=收盘价`。
- 接口：`GET /api/optimize/meta`、`POST /api/optimize/run`、`POST /api/optimize/save`；
  页面 `frontend/src/pages/Optimize.tsx`（侧栏「组合优化」）。
- 6 个目标：`max_sharpe` / `min_variance` / `max_return` / `risk_parity` / `inverse_vol` / `equal_weight`。

### 不可破坏的设计约定
1. **协方差用去均值后的数据，期望收益必须用原始收益**。
   若把去均值后的 `X` 传给 `estimate_mean`，`mu` 恒为 0，优化结果无意义（踩过一次）。
2. **任何"放宽用户约束"的行为必须显式暴露**：`constraints.effective_max_weight`
   + `constraints.max_weight_relaxed` + `notes` 里写清楚 + 前端告警条。
   静默把 15% 上限改成 16.67% 是不可接受的（用户的约束就是风控）。
3. **求解结束后必须重新 `project()` 而不是按和归一化**——
   `w / w.sum() * max_gross` 会把触顶权重推回上限之上，破坏盒约束与簇约束。
4. 输入不足（有效标的 < 2、重叠交易日 < 40）抛 `OptimizeError`，由 API 转 400。
5. `_ascend_bb` 用 Barzilai-Borwein 步长。改回固定 `1/L` 会让单次求解从 0.3s 退化到 80s+。
6. `POST /optimize/save` 生成的代码策略要能被 `validate_code` 的 AST 白名单放行
   （不含 import / lambda / 文件 I/O）。

## 实时引擎风控热加载（`engine/live.py`）
`EngineTask.__init__` 拿到的 `RiskLimits` 是**快照**。任何运行期的熔断/限额变更
必须通过 `_live_limits()` 每 tick 重读 `appstate.get_risk_row()`，
否则「熔断」在引擎运行期间形同虚设（曾经就是 P0）。

## 评估修复新增的设计不变量（2026-09-24，违反即回归 P0）
1. **护栏上下文只准用 `state.build_guard_context(acc, positions)` 构造**——
   计数器（orders_today/last_minute）+ 分市场敞口 fx 折算都在里面；
   手写 GuardContext = 三条风控静默失效（踩过一次 P0-5）。
2. **模式数据源只认 `state.effective_mode()`**（UI 开关 ∧ 端口）。
   UI 开关（current_mode）是权威路由：paper 状态强制模拟券商，端口 7496 也不能真实下单。
   展示/口令门控/下单路由必须同源，禁止只用端口推导。
3. **回测/实盘 weight 模式目标必须过 `sizing.cap_targets`**（单标的 clip + gross 等比缩放）；
   回测买单有现金下限。逐标的权重不做 Σ 约束 = 免费杠杆（6 标的曾跑出 6.1x）。
4. **data_provider 单飞是 Future 实现**（`_inflight: dict[str, cf.Future]`），
   跟随者只 `fut.result(timeout=60)` 绝不加锁——Lock 版释放不对称会永久死锁（P0-2）。
5. **`_normalize(naive_tz=)`**：默认 "UTC"（腾讯 m1 依赖）；缓存/已归一化数据一律
   `naive_tz=None`（幂等）。增量合并**绝不再整体 normalize**（每次漂移 4h，P1-1）。
   stooq 日期走 naive_tz=None（交易日无时刻语义）。
6. **年化一律 `metrics.periods_per_year(interval)`**，禁止硬编码 252（1h 曾被低估 √7 倍）。
7. `stop_type="none"/"time_stop"` 无价格止损（stop_price=0）；update() 对 stop_price<=0 不判定。
8. 熔断（日亏/回撤）**放行减仓单**（is_reducing 前置判定）；止损离场有 30s 冷却（`_stop_exit_at`）。
9. 自检新增 `run_checks.py correct` 节（27 项数值正确性断言，总计 208 项）——
   修数值 bug 必须同步补"数值正确"类断言，功能存在类断言抓不住这类回归。
12. **长任务一律走 `engine/jobs.py`**（后台线程 + progress_cb + 协作式取消），
    不要新增同步长 HTTP；网格寻优已迁移（optimize-async / job/{id} / job/{id}/cancel）。
10. **IBKR 事件循环线程必须唯一**：`_ensure_loop` 有 `_loop_lock` 保护、runner 绑定局部 loop 变量；
    并发首调曾双线程 run_forever 同一循环崩溃（"already running"）。gate 拒绝时 `_submit` 必须显式
    close 未 await 的协程。`get_ibkr` 单例创建有锁。
11. **重启服务用独立隐藏进程**（Start-Process -WindowStyle Hidden，日志 runtime/service.out|err.log），
    不要用工具会话托管 —— 高并发时段会被连带终止（两次实证）。

## 关键路径
- 运行数据（数据库 / 密钥 / 缓存）：`backend/runtime/`
- 前端构建产物：`frontend/dist/`（由 FastAPI 挂载，单端口 8787）
- 环境变量样例：`.env.example`（复制为 `backend/runtime/.env`）

## IBKR 适配层（`brokers/ibkr.py`）—— 改动前务必阅读

### 必须使用 Async 变体，否则会抛 "This event loop is already running"
我们用独立线程 + 专属事件循环持有 IB 连接，通过 `run_coroutine_threadsafe` 投递。

- ❌ **会阻塞的同步方法**（内部调 `run_until_complete`）→ 必须用 Async 变体：
  `connect` → `connectAsync`
  `qualifyContracts` → `qualifyContractsAsync`
  `reqTickers` → `reqTickersAsync`
  `reqHistoricalData` → `reqHistoricalDataAsync`
  `accountSummary` → `accountSummaryAsync`
  `ib.sleep(x)` → `asyncio.sleep(x)`（封装为 `self._sleep`）
- ✅ **可安全直接调用**（纯发送或读缓存）：
  `placeOrder` `cancelOrder` `reqMarketDataType` `positions` `portfolio`
  `openTrades` `fills` `managedAccounts` `isConnected` `disconnect`
- 提交协程用 `self._await(coro, timeout)`，提交同步调用用 `self._call(fn, *args)`。

### 命名陷阱
`IBKRBroker(self.account=...)` 会把账户号存到 **`self.account_id`**。
**不要**写回 `self.account` —— 那会覆盖基类的 `account()` 方法，
导致 `broker.account()` 直接 `TypeError`（第一版就是因此坏掉的）。

### 历史数据分页
IB 对单次请求时长有硬限制，见 `BAR_MAP`。`history()` 会按周期上限向后翻页拼接。
免费源只有 60 天分钟数据，IBKR 可回溯数年 —— 日内回测必须用 IBKR。

## 数据源提供者注册机制
`data_provider.register_history_provider(name, provider)` 注册外部源。
`provider` 需实现 `history(symbol, start, end, interval)` 与 `snapshot(symbols)`。
IBKR 的适配器在 `brokers/__init__.py::IBKRDataProvider`，导入时自动注册。
降级链：**IBKR → 本地缓存 → yfinance → Stooq → 合成**。
切换入口：`data_provider.set_preferred(name)`，API 为 `/api/market/data-source`。

## 前端构建约束（重要）
主机启用了 safe-delete 保护，会拦截 `fs.rmSync`，
导致 Vite 的 `emptyOutDir: true` 阶段直接失败。

**已采用的方案**：`vite.config.ts` 中 `emptyOutDir: false`，
新增 `scripts/prebuild.mjs`（npm `prebuild` 钩子）用 **rename 归档**旧 `dist/`
到 `dist.old-<时间戳>`（rename 不受拦截），只保留最近 2 个。
请勿改回 `emptyOutDir: true`。

## 提交前必跑
```bash
cd backend && .venv/Scripts/python.exe ../tests/run_checks.py    # 202 项
cd frontend && npm run typecheck && npm run build && npm run smoke  # 46 项
```

## AI 情报中心（`app/intel.py` + `app/api/intel.py`）—— 2026-09-24 新增
事件驱动研究流水线：外部 AI Agent 抓取互联网 → 公司关键节点 → AI 买入建议。

- 三层引擎：外部 Agent（Bridge）> 内置 LLM（QD_AI_*）> 本地量化兜底；建议必带 agent/engine 标注。
- **Bridge 鉴权独立**：`X-Intel-Token`（存 intel_settings，页面可重置），与 JWT/交易账户完全隔离。
- Bridge 协议：`GET bridge/poll` → `POST bridge/events` → `GET bridge/brief/{sym}` → `POST bridge/analysis` → `POST bridge/done`。
- 事件去重：`dedupe_key = sha1(symbol|category|归一化标题)`，唯一约束。
- 一键开启/截止 = IntelRun（running→finished），截止时 Markdown 报告落盘
  `runtime/intel/reports/run-<id>-<ts>.md`；`monitor_enabled` 持久化，重启后 `resume_on_startup()` 自动续跑。
- 调度器 `IntelScheduler`：轻 tick 20s（报价/计数），重 tick 按周期（任务整备 + 自动分析，每轮最多 3 家）。
- 页面 `pages/Intel.tsx`（路由 `/intel`）；smoke 断言含 Intel chunk。
- **坑：`session_scope` 是 `autoflush=False`** —— `expunge` 前、以及「同批插入后紧跟查重」前
  都必须显式 `flush()`，否则修改静默丢失 / 同批重复漏检（save_settings、add_events 均踩过）。

## 已知环境约束
- **pandas 3.0 已装**：避免 `.stack()/.unstack()` 做 tr 计算，用 `np.fmax` 直接构造。
- `DataFrameGroupBy.cumcount()` 返回 **Series**，多列场景需改用 numpy（见 `builtin_intraday._day_arrays`）。
- 主机有 safe-delete 保护：单轮删除超过 50 个文件会被拦截。
  重置数据请用 SQL 清表，或删除 `backend/runtime/quantdesk.db`（会连带丢失账户）。
- 前端 `build` 脚本只跑 `vite build`，不跑 `tsc`（避免类型告警阻塞产物）。
- **该 FastAPI 版本的 `include_router` 是惰性的**：`app.routes` / `api_router.routes` 里
  是 `_IncludedRouter` 包装对象，`getattr(r, "path")` 全为空字符串。
  要枚举真实路径必须走 `app.openapi()["paths"]`（自检脚本里已按此写法）。
- `frontend/scripts/prebuild.mjs` 归档旧 dist 时只保留最近 2 个 `dist.old-*`。

## 待扩展方向
- 实盘实时引擎（当前只允许 paper/simulated 运行）
- 期权模块（covered call / 铁鹰 / 波动率风险溢价）
- 组合优化进阶：Black-Litterman 观点融合、换手率惩罚项、协方差收缩的 Ledoit-Wolf
  完整版（当前是对角收缩近似）
- 数据源扩展（Polygon / Databento 等付费源）
