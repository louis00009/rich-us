# QuantDesk for IBKR — 代码审查报告（修订版 v2）

> 审查时间：2026-09-27 ｜ 范围：`backend/app`（22,702 行 Python）+ `frontend/src`（14,500 行 TS/TSX）
> **v2 修订说明**：本版对 v1 的每条结论做了**可执行验证**（跑代码、查真实 DB、静态扫描），
> 推翻了 v1 的 2 条结论、细化了 4 条。验证方法与原始输出见 **附录 A**。

---

## 〇、总体评价

这是一个**工程成熟度明显高于同类个人项目**的平台：三重锁实盘安全、AST 沙箱、护栏与审计、
无未来函数的回测口径、清晰的模块边界，都是认真设计过的。

v2 验证后的结论比 v1 **更乐观**：我原先怀疑"合成数据静默冒充真实行情"，
实测发现**代码在多个层面都做了显式告警**（Market 页横幅+徽章、Optimize 页 toast+Alert、
`stream.py` 定义 `MODE_SYNTHETIC` 并写明"前端必须告警"）。v1 这条是**误判**，已更正。

真正的问题集中在两类：
1. **跨层契约没有测试覆盖** —— 前后端 WebSocket 主题格式不一致，全链路静默失效却无人发现；
2. **异步/同步边界处理不一致** —— 33 个 async 端点里 21 个直接跑同步 I/O，其中 8 个含写库。

---

## 一、P0 · 严重（会导致数据错误或全站故障）

### P0-1 前端 WebSocket 行情推送全链路失效（静默）✅ 已验证

**位置**
- 前端分发：`frontend/src/lib/realtime.ts:91` — `if (h.topics.includes(m.topic))`
- 后端推送：`backend/app/realtime.py:117` — `c.push({"topic": "quotes", ...})`
- 订阅方（全部使用 `quotes:<symbol>`）：
  `Market.tsx:291`、`QuickPicks.tsx:42`、`WatchBar.tsx:51`、`Dashboard.tsx:70`、`DataClock.tsx:16`

**验证**（附录 A-1，Node 实跑）：
```
Market (quotes:SPY)  → includes("quotes") = false
AlertsBell (alerts)  → includes("quotes") = false
```
判定恒为 `false`，**所有行情 handler 永不触发**。`alerts` 主题恰好同名，所以告警推送正常 —— 这掩盖了问题。

**影响**：行情页 LIVE 跳动、QuickPicks / WatchBar / Dashboard 秒级刷新**全部是死的**，
只靠 60s 轮询兜底；`realtime.ts:89` 仍无条件更新 `lastTickAt`，DataClock 显示绿灯"推送中"，
**从 UI 完全看不出异常**。

**修复**
```ts
// realtime.ts:91
const hit = h.topics.some((t) => t === m.topic || t.split(':')[0] === m.topic)
if (hit) { ... }
```
并补**端到端用例**：`tests/run_checks.py` 加一个 ws 客户端订阅 `quotes:SPY` → 断言消息被 handler 消费。
TODO T-135 里"ws 协议用例（后续补）"正是缺口 —— **这是该 bug 长期存在的直接原因**。

---

### P0-2 同步 DB I/O 跑在 `async def` 端点里，阻塞事件循环 ✅ 已验证（范围比 v1 更大）

**验证**（附录 A-4，静态扫描全部 `app/api/*`）：**33 个 async 端点中 21 个含同步阻塞 I/O。**

**严重档（含写库或多轮查库，共 8 个）**

| 端点 | 同步调用 |
|---|---|
| `trading.engine_start` | `db.get` / `db.add` / `db.commit` / `db.refresh` + `appstate.get_risk_row` / `risk_limits` |
| `trading.engine_stop` / `engine_stop_all` | `db.execute` / `db.commit` |
| `trading.engine_dry_run` | `db.get` + `appstate.get_risk_row` / `risk_limits` |
| `trading.place_order` | `appstate.build_guard_context`（内部多轮查库）/ `get_risk_row` / `risk_limits` |
| `trading.preview_order` | `appstate.build_guard_context` / `risk_limits` |
| `backtest.run` | `db.add` / `db.commit` / `db.refresh` |
| `risk.exposure` | `appstate.get_broker_settings` / `risk_limits` |

**中等档（2 个）**：`system.test_broker`、`system.disconnect_broker`（`get_broker_settings` 查库）。
**轻微档（11 个）**：仅 `appstate.log()` 一次审计写入（`ai.do_analyze`、`backtest.compare` 等）。

**影响**：SQLite 写锁 + `commit()` 在事件循环线程上执行，会**冻结整个进程** ——
期间其他引擎 tick、WebSocket 推送、所有 API 请求全部停摆。
TODO 里 "2026-09-26 ⅩⅢ 连接池耗尽事故修复" 只扩容了池，**没解决根因**：同步 I/O 占住事件循环。

**修复**：改同步 `def`（FastAPI 自动丢线程池），或显式 `await run_in_threadpool(...)`。
`account()` / `positions()` 已用此模式，说明写法是现成的，只是没贯彻。**优先修严重档 8 个。**

---

## 二、P1 · 高（逻辑错误 / 资源泄漏 / 安全）

### P1-1 实盘"时间止损"按 tick 计数而非 bar ✅ 已验证

**位置**：`live.py:744` 在 `_execute()` 的 `finally` 里 `self.tick_count += 1`（**每个执行周期 +1**）；
`live.py:401, 416, 728` 把 `self.tick_count` 当 `bar_index` 传给 `StopTracker`；
判定在 `stops.py:183` — `(bar_index - entry_bar) >= time_stop_bars`。

**影响**：实盘数的是**执行次数**。`exec_interval_sec` 可低至 0.02s，配置"5 bar 时间止损"
在实盘 = 0.1~5 秒平仓，而回测里同样 5 = 5 个交易日。**回测结论无法外推。**

**修复**：实盘改传按策略周期对齐的**信号 bar 序号**。

---

### P1-2 实盘信号存在同 bar 前视（与回测口径相反）✅ 已验证

**位置**：`live.py:337` — `_build_signals()` 返回 `w.iloc[[-1]]`（最新、**未收盘**的 bar）；
随后 `live.py:682` 立即按当前价下单。回测则刻意用 `w_np[i-1]` 在第 i 根开盘成交
（`backtest.py:224-226, 247`），README 把"无未来函数"列为第一保证。

**影响**：实盘等于"用 bar t 的收盘价在 bar t 成交"，系统性优于回测 ——
回测漂亮、实盘吃不到。**这是最危险的一类偏差。**

**修复**：实盘取倒数第二根**已完成** bar 的信号，或在 UI/文档明确标注执行口径差异。

---

### P1-3 ATR 不可用时移动止损塌缩到极值价，立即误触发 ✅ 已验证（范围已细化）

**位置**：`stops.py:161` — `av = float(atr_value) if atr_value else 0.0`；
`live.py:412-414` 在 ATR 为 0 时**显式传 `None`**（`self._atr_for(sym) or None`），
`stops.py` 又把 `None` 转成 `0.0` —— 两个文件合起来构成该 bug。

**验证**（附录 A-2，实跑 `StopTracker`）：

| stop_type | ATR 正常 | **ATR 为 None（实盘真实入参）** |
|---|---|---|
| `atr_trailing` | 止损 100→101→102，不触发 ✅ | bar1 止损跳到 **106.00**（=最高价），**bar2 立即触发"ATR移动止损"** ❌ |
| `volatility` | — | 同上，**bar2 立即触发"波动率止损"** ❌ |
| `chandelier` | — | 止损 100→101→102，**不触发** ✅ |

**v1 更正**：v1 称"影响 `atr_trailing`/`chandelier`/`volatility` 三种"是**错的**。
实测 `chandelier` 不受影响 —— 它在 `stops.py:164` 有 `av = max(av, s.r_distance / base_mult)`
兜底。**实际受影响的是 `atr_trailing` 与 `volatility` 两种。**

**额外发现**：`atr_fixed` 在开仓时若 ATR 缺失，`_initial_distance()` 会静默退化为
`ep * stop_value/100`（即 3% 固定止损），而非 3×ATR —— 属同一根因的第二种表现。

**影响**：实盘（`_atr_for` 失败或接管非策略标的时返回 0）会在**下一个 tick 被强制平仓**。

**修复**：ATR 无效时**跳过**移动止损更新，而不是用 0 参与计算。

---

### P1-4 引擎停止时不撤销交易所侧的保护性委托 ✅ 已验证

**位置**：`live.py:476-486`（`_cancel_protective`）只在**平仓/换仓**时被调用；
`live.py:982-986` 的 `_loop` `finally` 与 `live.py:1041-1048` 的 `stop()` **都没有调用它**
（已验证：`finally` 只有 `_detach_hub` / `running=False` / `_update_run_row` / 审计日志）。

**影响**：引擎停止或进程掉线后，`protective_orders` 里挂在 IBKR 侧的 GTC `STP/LMT` 单仍存活。
原意是"掉线也有保护"，但**平仓后残留的止损单在无持仓时会反向开仓**（STP 触发即成裸空/裸多）。
这是资金安全的实质风险。

**修复**：`stop()` 与 `_loop` 收尾遍历 `protective_orders` 全部撤销，并写审计。

---

### P1-5 缓存文件读写无锁，`to_csv` 非原子 ✅ 已验证

**位置**：`data_provider.py:297-316` — `merged.to_csv(path)` 直接覆写（截断+写入，非原子）；
`_read_cache`（`251-294`）无锁。

**验证后的细化**：`_read_cache` 的 `except Exception: return None` 意味着**行中截断**的 CSV
通常抛 `ParserError` → 返回 None → 缓存未命中 → 回落网络（**这是良性路径**）。
真正的风险是**行边界截断**：`read_csv` 成功但只读到部分行，若请求未带 `end`，
覆盖度校验（`279-293`）不会拦截 → 静默返回**短数据**。
`_write_cache` 的"读-合并-写"还会丢更新。

**修复**：写临时文件后 `os.replace` 原子替换；按 `(symbol, interval)` 加文件锁。

---

### P1-6 `Conn.topics` 跨线程读写导致推送间歇丢失 ✅ 已验证

**位置**：`realtime.py:32`（set 定义）、`78-87`（`subscribe/unsubscribe` **未持 `_lock`**，在事件循环线程执行）、
`45-55`（`symbols()` 迭代）、`111-117`（后台 tick 线程读）。

**影响**：后台 `_tick_loop` 遍历 set 的同时事件循环线程增删 → `RuntimeError: Set changed size
during iteration`，被 `realtime.py:233` 的宽 `except` 吞掉 → **推送随机丢一拍**，
日志里只有一行 `tick 异常`。

**修复**：`subscribe/unsubscribe` 持 `_lock`，或维护不可变快照原子替换。

---

### P1-7 后台任务线程无上限、GC 不触发、进度写入无锁 ✅ 已验证

**位置**：`engine/jobs.py:38-73`。

**影响**
- `jobs.py:72` 每次 `start()` 裸起 `daemon` 线程，**无并发上限**（反复提交寻优 → 线程膨胀）；
- `_gc_locked()` 只在 `start()` 内调用（`jobs.py:52`），不再提交新任务时**过期结果永不回收**；
- `progress()`（`jobs.py:55-57`）无锁写、`get()` 持锁读，存在撕裂。

**修复**：`ThreadPoolExecutor(max_workers=N)` + 独立定时 GC + 进度更新进锁。

---

### P1-8 Sortino 分母口径错误 ✅ 已验证（附实测偏差）

**位置**：`metrics.py:95-96` — `downside = excess[excess < 0]`，再取 `downside.std(ddof=1)`。
标准下行偏差应为 `sqrt(mean(min(r − MAR, 0)²))`（全样本、除以 N）。

**验证**（附录 A-3，500 个正态样本实跑）：
```
负收益样本 245 / 500
实现的“下行标准差” = 0.006762
标准下行偏差       = 0.007874     比值 1.164x
实现 Sortino = 0.8040   标准口径 = 0.6905   → 高估约 16%
```
**影响**：分母偏小 → Sortino 系统性偏高。**量级取决于负样本占比**（本样本 ≈16%），
足以影响多策略对比页的排序，但不像 v1 暗示的那样夸张。

**修复**
```python
downside_dev = float(np.sqrt(np.mean(np.minimum(excess, 0.0) ** 2)))
if downside_dev <= 0: return 0.0
return float(excess.mean() / downside_dev * np.sqrt(ppy))
```

---

### P1-9 前端异步请求竞态：旧响应覆盖新状态 ✅ 已验证

**位置**
- `Rankings.tsx:67-79`（`openProfile`）— 已核实：`setProfileSym(sym)` 后 `await`，
  无序号守卫，`setProfile(r)` 可被过期响应覆盖 → 弹窗标题是 B、内容是 A 的公司档案；
- `AICopilot.tsx:114-136`（`analyze`）— 已核实：`setResult(r)` / `setActiveSym(...)` 同样无守卫；
- `Intel.tsx:235-239`（`PriceOverlay`）。

**对照**：`Market.tsx:198-220` 已有正确的 `seqRef` 序号守卫模式，只是没推广。

**修复**：统一采用 `seqRef` 模式，过期响应直接丢弃；effect cleanup 里置 `dead` 防卸载后 `setState`。

---

### P1-10 寻优轮询定时器无卸载清理 ✅ 已验证

**位置**：`Backtest.tsx:281-318`。已核实：`clearInterval` 仅出现在 `pollOptJob` 内部
（286/294/311 三处），**全文件无 `useEffect(() => () => clearInterval(optPollRef.current), [])`**。

**影响**：寻优进行中切走页面 → 定时器持续轮询、在已卸载组件上 `setState`（泄漏 + 无谓请求）。

**修复**：补卸载清理 effect。

---

### P1-11 令牌放在 WebSocket URL 查询串 ✅ 已验证

**位置**：`realtime.ts:54`、`api.ts:125` — `?token=${encodeURIComponent(token)}`。

**影响**：JWT 进入浏览器历史、代理/服务器访问日志、Referer 头。
后端 `ws.py` 已支持 4401 鉴权失败，改造面很小。

**修复**：连接建立后首帧发送 `{"action":"auth","token":...}`，或走 `Sec-WebSocket-Protocol`。

---

## 三、P2 · 中（性能 / 可维护性 / 边界情况）

| # | 问题 | 位置 | 验证结论 | 建议 |
|---|---|---|---|---|
| P2-1 | 高频过滤列缺索引 | `models.py:86, 95, 184, 186, 270` | ✅ **查真实 DB 确认**：`orders.mode`、`orders.status`、`engine_runs.strategy_id`、`engine_runs.status`、`engine_runs.mode`、`ai_proposals.order_id` **均无索引**（`orders.symbol/created_at`、`ai_proposals.status/symbol` 有） | 加 `index=True` |
| P2-2 | 合成行情在下单路径无守卫 | `data_provider.py:1008-1014` → `trading.py:166-170, 185-190` | ✅ **v1 此处判断有误，详见下方 P2-2 详情** | 下单路径校验 `quote["source"]=="synthetic"` 时拒绝或强提示 |
| P2-3 | naive/aware datetime 混用 | `models.py:21-22, 103, 187`；`trading.py:461, 480` | 代码确认；TODO 记录已踩坑 3 次 | 统一 naive UTC，或列改 `DateTime(timezone=True)` |
| P2-4 | 券商 `host` 无校验 → SSRF | `schemas.py:301`；`system.py:73-89` | ✅ 确认：`/broker/test` 连接配置的任意 `host:port`。**但需已认证调用方**（单用户本机应用）→ 定级中等 | 限定 `127.0.0.1/localhost` |
| P2-5 | 输入无界：`symbol` 无长度校验、`sma(\d+)` 周期无上限、无全局限流 | `market.py:112, 331, 359-360` | 代码确认 | 加 `max_length`、周期上限、`Query(ge,le)` |
| P2-6 | 可能为 `null` 的字段直接 `.toFixed()` | `Rankings.tsx:307`、`WatchBar.tsx:108`、`Portfolio.tsx:188/207` | 代码确认（同行 `price` 已保护，`change_pct` 漏了） | `fmtPct` / `Number(v) \|\| 0` 兜底 |
| P2-7 | `repeat()` 未 clamp，外部输入可致白屏 | `Intel.tsx:419, 857, 858` | ✅ 确认 **3 处**：`'★'.repeat(e.impact)` / `'☆'.repeat(5 - e.impact)`。`impact` 由**外部 AI Agent 提交**，>5 → 负数 → `RangeError` | `Math.max(1, Math.min(5, e.impact \|\| 3))`（`CompanyIntel.tsx:195` 已有正确写法） |
| P2-8 | 图表组件未 `memo` | `components/charts.tsx` | 代码确认 | `memo()` + 稳定 `formatter` 引用 |
| P2-9 | 年化因子常量冲突 + 死代码 | `optimizer.py:28, 54` | ✅ **已确认是死代码**：`PERIODS_PER_YEAR` 与 `annualize()` **全项目零引用**，`252*7` vs `metrics.py` 的 `252*6.5` 冲突目前**无实际影响**，属潜在陷阱 | 删除死代码 |
| P2-10 | 保护性止盈锚定用 `avg_price or px` | `live.py:466` | 代码确认：IBKR 异步下单时 `avg_price` 常为 0 → 用当前价锚定 R | 用 `tr.s.entry_price` |
| P2-11 | 未按实际成交量更新持仓/止损 | `live.py:695-733` | 代码确认：用请求 `qty` 而非 `filled` 更新 `ctx.open_positions` 并建 `StopTracker` | 以券商回填 `filled_qty/avg_price` 为准 |
| P2-12 | 嵌套线程池 | `data_provider.py:1034`（`get_quotes` 内建 8 线程），调用方 `market.py:107` 已在线程池 | 代码确认 | 复用单一受限执行器 |
| P2-13 | 依赖全部 `>=` 无锁定 | `backend/requirements.txt` | 确认（本机已跑 pandas 3.0，属破坏性大版本） | 引入 lock 文件 |
| P2-14 | 巨型文件 | `brokers/ibkr.py` 1784 行、`intel.py` 1192、`live.py` 1058、`Intel.tsx` 1260、`LiveTrading.tsx` 1129 | 已统计 | 按职责拆分 |
| P2-15 | 后端无 lint/类型门禁 | — | 确认（前端有 `tsc` + `lint:hooks`，Python 侧无 ruff/mypy） | 接入 ruff + mypy |
| P2-16 | `/market/history` 的 `count` 与 `dates` 长度不符 | `market.py:150 vs 179` | 代码确认：`tail=df.tail(3000)` 但非实时路径 `count=len(df)` | `count=len(tail)` |

### P2-2 详情（v1 的 P0-3，**已更正**）

**v1 的错误结论**：v1 称"合成行情静默冒充真实数据、前端当普通日线渲染"。**这是错的。**
实测发现代码在多层都做了显式告警：

| 位置 | 告警方式 |
|---|---|
| `Market.tsx:519-521` | ⚠️ 横幅："当前显示的是**合成数据**（非真实行情）…" |
| `Market.tsx:575, 855` | `source === 'synthetic'` → 琥珀色 Badge |
| `Optimize.tsx:212-213, 488-490` | toast 警告 + `Alert tone="warn"`："…不可用于实盘" |
| `optimize.py:141-147` | 后端返回 `synthetic_symbols` + 警告文案 |
| `engine/stream.py:31, 67, 997` | 定义 `MODE_SYNTHETIC`，注释写明"**前端必须告警**" |
| `Settings.tsx:512, 699` | 文档化说明 |

**真正残留的缺口**（收窄后的准确版本）：
1. **`/trading/order` 无合成守卫**：`trading.py:166` 用 `get_quote` 取参考价，
   而 `get_quote` → `fetch_history` → 可返回合成价（`data_provider.py:1008-1014`）。
   `/trading/preview` 会在响应里回带 `quote.source`（可察觉），
   但 **`/trading/order` 的响应（`trading.py:228-234`）不含 `source`** → 下单方无从得知参考价来自假数据。
2. **回测结果仅"显示"来源，未"警示"**：`backtest.py:392-394` 返回 `data_sources` / `data_source_used`，
   `Backtest.tsx:208, 590` 会把它显示出来（如"数据源 synthetic"），
   但**没有 Optimize 页那样的醒目告警**。

**修复**：`/trading/order` 在 `quote["source"] == "synthetic"` 时拒绝（或强制二次确认）并回带 `source`；
Backtest 页对 `synthetic` 复刻 Optimize 的 `Alert`。

---

## 四、P3 · 低（建议但非必须）

- **`metrics.py:81`**：`period_returns` 只 `fillna(0)`，未清理 `±inf`。权益出现 0 时 `pct_change` 产生 `±inf`，被 `_safe()` 吞成 0 → Sharpe/波动率/Alpha **静默归零**而不报错。建议 `replace([inf,-inf], nan).fillna(0)`。
- **`metrics.py:85`**：`ret.std(ddof=1) == 0` 浮点精确比较，应 `< 1e-12`。
- **`metrics.py:45`**：`max_dd_days` 实际返回 **bar 计数**，label 已改"最长水下期(bar)"，函数注释仍写"天数"。
- **`data_provider.py:208`**：`_yahoo_search` 失败写空结果并缓存 10 分钟（负缓存掩盖恢复）。
- **`data_provider.py:172, 670, 984-1014`**：模块级缓存无容量上限、无锁。
- **`data_provider.py:389, 431`**：用户 symbol 未编码拼进 URL 查询串，应改 `params=`。
- **`ops.py:56`**：`get_broker()` 未传 cfg，与 `trading.py:_broker_and_mode()` 路由逻辑不一致。
- **`config.py:45-47`**：`.env` 解析器不处理行内注释（值含 `#` 被截断）、`strip("'\"")` 会误删合法引号。
- **`Backtest.tsx:782-791`**：删除历史回测的 `await api.del(...)` 无 `try/catch`。
- **`AICopilot.tsx:395/416`**：`((v - active.price) / active.price) * 100`，`price=0` → `Infinity/NaN`。
- **前端 `any` 泛滥**：`LiveTrading.tsx:59-64`、`api.ts:77/94`；`LiveTrading.tsx:908` 非空断言 `acc!.equity`。
- **`lib/format.ts:147-153`**：`fmtMetric` 每次调用新建 3 个 `Set`，应提为模块常量。
- **无速率限制**：默认仅监听 `127.0.0.1`，但设计上要接 AI Agent（持 token），
  无节流的慢接口（`alerts/scan` 102s，TODO 已列遗留）会拖垮全站。

---

## 五、做得好的地方（建议保持）

1. **三重锁实盘安全**（`config.py:87` / `state.py:298-309` / `guardrails.py`）设计到位；
   熔断时**放行减仓单**（`guardrails.py:225-249`）这个细节尤其专业。
2. **AST 沙箱**（`strategies/custom.py:264-403`）覆盖模块导入、名称、属性、字符串常量、
   运行时 `__import__`/`getattr` 五个层面，还封堵 `pd.read_pickle` 绕过路径。
3. **无未来函数的回测口径**（`backtest.py:224-247`）+ 回测/实盘共用 `StopTracker`。
4. **合成数据的降级告警体系**（`stream.py` MODE_SYNTHETIC + 前端横幅/徽章/Alert）——
   v1 低估了这部分，实测比预期完善。
5. **审计留痕**（`state.py:22-28`）失败不阻塞主流程但打控制台，权衡得当。
6. **自检体系**（208 项 `run_checks.py` + 46 项 smoke）覆盖面不错，缺的是**跨层契约用例**（见 P0-1）。

---

## 六、建议的修复顺序（v2）

| 优先级 | 事项 | 理由 |
|---|---|---|
| 1 | **P0-1** WS 主题匹配 + 补端到端用例 | 一行修复，恢复整个实时链路；补测试防复发 |
| 2 | **P0-2** 严重档 8 个 async 端点 | 与已发生的全站 500 同源，未根治的根因 |
| 3 | **P1-1 / P1-2 / P1-3** 实盘与回测口径对齐 | 三者叠加会让"回测验证过的策略"在实盘表现完全不同 |
| 4 | **P1-4** 引擎停止撤销保护性委托 | 资金安全实质风险（残留单反向开仓） |
| 5 | **P2-2** 下单路径合成数据守卫 | 唯一残留的"假数据进交易链路"缺口 |
| 6 | **P1-5 / P1-6 / P1-7** 并发与资源 | 稳定性 |
| 7 | 其余 P1-8 ~ P1-11、P2 各项 | 正确性与体验 |

---

# 附录 A · 验证方法与原始输出

本附录记录 v2 的验证手段，供复核。**共 7 项检查，5 项确认、2 项推翻 v1 结论。**

### A-1 WS 主题匹配（Node 实跑）→ **确认 P0-1**
```js
handlers = [{topics:['quotes:SPY']}, {topics:['alerts']}];  msg = {topic:'quotes'}
Market     (quotes:SPY) → includes("quotes") = false
AlertsBell (alerts)     → includes("quotes") = false
```

### A-2 `stops.py` ATR 缺失（实跑 `StopTracker`）→ **确认 P1-3，但缩小范围**
```
[ATR 正常]     atr_trailing  bar1 止损=100.00 bar2=101.00 bar3=102.00  触发=False
[ATR 为 None]  atr_trailing  bar1 止损=106.00 bar2 触发=True "ATR移动止损"
[ATR 为 None]  volatility    bar1 止损=106.00 bar2 触发=True "波动率止损"
[ATR 为 None]  chandelier    bar1 止损=100.00 bar2=101.00 bar3=102.00  触发=False   ← v1 误判
```

### A-3 Sortino（500 样本实跑）→ **确认 P1-8，附量级**
```
负收益样本 245/500
实现口径 0.006762   标准口径 0.007874   比值 1.164x
Sortino 实现 0.8040 → 标准 0.6905（高估约 16%）
```

### A-4 async 端点同步 I/O（静态扫描 33 个 async 端点）→ **确认 P0-2，范围扩大**
```
33 个 async 端点，21 个含同步阻塞 I/O
严重档 8：engine_start / engine_stop / engine_stop_all / engine_dry_run /
          place_order / preview_order / backtest.run / risk.exposure
中等档 2：test_broker / disconnect_broker      轻微档 11：仅 appstate.log
```
> 过程中发现：本环境 FastAPI 使用惰性 `_IncludedRouter`，`app.routes` 不展开子路由
> （直接遍历只能看到 8 条）。**若后续要写路由级测试，必须递归展开或改用源码扫描**，
> 否则会得出"端点不存在"的错误结论 —— 我第一版脚本就踩了这个坑。

### A-5 数据库索引（读真实 `runtime/quantdesk.db`）→ **确认 P2-1，并新增 2 项**
```
orders:        mode ✗   status ✗   symbol ✓   created_at ✓
engine_runs:   strategy_id ✗   status ✗   mode ✗
ai_proposals:  status ✓   symbol ✓   order_id ✗
fills:         order_id ✓        audit_logs: action ✓  ts ✓
```

### A-6 合成数据告警链路（grep + 源码阅读）→ **推翻 v1 的 P0-3**
命中告警位置：`Market.tsx:519-521/575/855`、`Optimize.tsx:212-213/488-490`、
`optimize.py:141-147`、`stream.py:31/67/997`、`Settings.tsx:512/699`。
→ 结论改为 P2-2（下单路径守卫 + 回测页告警）。

### A-7 死代码与前端项（grep + 源码阅读）→ **确认 P2-9 / P1-9 / P1-10 / P2-7**
```
annualize( / PERIODS_PER_YEAR → 仅 optimizer.py:28,54 两处定义，零调用点
Rankings.tsx:67-79 openProfile      → 无序号守卫（竞态）
AICopilot.tsx:114-136 analyze       → 无序号守卫
Backtest.tsx clearInterval          → 仅 286/294/311，均在轮询函数内，无卸载清理
Intel.tsx repeat(                    → 419 / 857 / 858 三处未 clamp
```

---

*本报告未修改任何代码。v1 → v2 的结论变化已在正文逐条标注；所有结论可通过文中所列
`文件:行号` 与附录 A 的方法复核。*
