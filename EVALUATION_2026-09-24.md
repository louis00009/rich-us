# QuantDesk for IBKR · 完整评估报告

> 评估日期：2026-09-24 ｜ 代码规模：后端 84 个 Python 文件 / 21,392 行，前端 13,013 行 TS/TSX
> 评估方式：全链路代码审查 + **在项目自带虚拟环境跑实证对照实验**（不依赖网络、可复现）
> 现状基线：`run_checks.py` **174/174 全绿**；`eslint rules-of-hooks` 与 `tsc --noEmit` 均零错误

> **✅ 修复状态（2026-09-24 同日执行，两批）**：**第一批** P0-1~P0-6 全部 + P1-1/2/3/4/5/6/7/8/9/11/12/13；
> **第二批** P1-10 + P2 大部分（market/_dt、overview 锁、lots 碎股、volatility 止损符号、停牌 NaN 估值、CSV 注入、
> request-id、rankings 500、_attempts 无界）+ 功能矛盾两项（/ops/kill-switch 口令、提案自批准）+ JWT 撤销/限速绕过 +
> 前端（Risk 0 值保存守卫、账户失败红条、撤单提示、CandleChart 恢复、Rankings 提示）。自检 174→**202** 项全绿；
> smoke 46/46；tsc/build 通过。施工明细见 `TODO.md` 施工日志。
> **未修（长尾，多为体验类）**：移动端适配（T-119）、长任务进度/取消、T-116 键盘导航、T-115 预检 UI、
> 有效前沿视图、配色切换全量化、无障碍（label/Modal/aria-live）、图表触屏滚动与降采样、币种折算 UI（T-112 尾项）、
> 期权模块（T-133）、付费数据源（T-122）。

---

## 〇、一句话结论

**工程质量（规范、注释、自检、文档同步）明显高于平均水平 —— 代码里连 TODO/FIXME 标记都只有 1 处命中。
但"自检全绿"掩盖了 6 个 P0 级真实缺陷：其中 3 个会直接产生错误的交易信号/错误的回测结论，1 个能在高并发下让全站卡死且无法自愈。**

最严重的一条，已用项目自己的代码实测复现：

> **回测默认仓位模式下，`gross_pct` 与 `max_position_pct` 完全不生效。**
> 6 只标的的默认参数跑 2 年 → 实际敞口 **6.1 倍**，总收益 **+6771%**，夏普 **14.16**。
> 同样数据换成其他 4 种仓位模式 → 敞口 **1.0 倍**，总收益 **104.7%**。

也就是说：**过去所有多标的回测结论、网格寻优出的参数、策略之间的横向对比，都是在一套"免费杠杆"假设下跑出来的，不可信。**

---

## 一、缺陷总览

| 级别 | 数量 | 性质 |
|---|---|---|
| **P0** | 6 | 错误交易决策 / 全站停摆 / 账户不可用 |
| **P1** | 13 | 功能静默失效 / 资金安全风险 / 明显体验缺陷 |
| **P2** | 18 | 边界、一致性、打磨项 |

按模块分布：

| 模块 | P0 | P1 | P2 |
|---|---|---|---|
| 回测引擎 `engine/backtest.py` | 1 | 2 | 2 |
| 风控 `risk/*` | 3 | 1 | 1 |
| 实盘引擎 `engine/live.py` | 0 | 4 | 3 |
| 数据链路 `data_provider` / `brokers` | 2 | 4 | 4 |
| 组合优化 `engine/optimizer.py` | 0 | 2 | 3 |
| API / 安全 | 2 | 3 | 5 |
| 前端 | 0 | 6 | 8 |

---

## 二、P0 · 必须立即修复

### P0-1　回测默认仓位模式无组合级约束，现金可被无限打穿

**位置**　`backend/app/engine/backtest.py:237`、`:210`

```python
# :237  weight 模式下，targets 只用逐标的权重 × 权益，没有任何总敞口/单标的限制
targets = {s: float(w_prev[s]) * prev_equity for s in symbols}
# :210  fill() 无条件记账，无现金下限
cash -= qty * px + fee
```

而多标的内置策略输出的是**逐标的**权重，只做逐元素 clip 到 ±1（`strategies/base.py`），**不做 Σ 归一**。
`sizing_method` 的默认值就是 `"weight"`（`api/backtest.py:51`）。

**实测**（6 只强趋势标的、2 年日线、`gross_pct=100`、`max_position_pct=20`）：

| 仓位模式 | 最大敞口 | 总收益 | 夏普 |
|---|---|---|---|
| **`weight`（默认）** | **6.1x** | **+6771.5%** | 14.16 |
| `atr_risk` | 1.0x | +104.7% | 14.17 |
| `equal_weight` | 1.0x | +104.7% | 14.17 |
| `fixed_pct` | 1.0x | +104.7% | 14.17 |
| `risk_parity` | 1.0x | +104.7% | 14.17 |

**后果**　所有多标的回测都在无保证金利息、无强平约束下用免费杠杆跑出漂亮曲线，实盘必然无法复现。
这是"回测—实盘"失真中最严重的一条，也是参数寻优结果的污染源。

**修法**　`targets` 算完后统一施加两级约束，并给 `fill()` 加现金下限：

```python
pos_cap = prev_equity * spec.max_position_pct / 100.0
targets = {s: float(np.clip(v, -pos_cap, pos_cap)) for s, v in targets.items()}
g = sum(abs(v) for v in targets.values())
gross_cap = prev_equity * spec.gross_pct / 100.0
if gross_cap > 0 and g > gross_cap:
    targets = {s: v * gross_cap / g for s, v in targets.items()}
```

---

### P0-2　单飞锁释放不对称 → 同一标的第 3 次并发请求**永久阻塞**

**位置**　`backend/app/data_provider.py:693-718`

```python
flk = _acquire_flight(f"{symbol}|{interval}")
is_leader = flk.acquire(blocking=False)
try:
    if not is_leader:
        flk.acquire()          # ← 跟随者在这里拿到锁
        if use_cache: ...
finally:
    if is_leader:
        flk.release()          # ← 只有 leader 释放；跟随者永不释放
```

**实测**　模拟 leader + follower1 完成后再起 follower3 → follower3 永久阻塞，
**整个 Python 进程无法退出**，测试进程被 SIGTERM 杀掉。

**触发条件**　同一 `(symbol, interval)` 在缓存未命中窗口内出现 3 次并发。
前端切换标的时并发打出 `history / indicators / snapshot` 三连发**正好命中**（该文件 589-591 行的注释自己描述了这一场景）。

**级联后果**
- anyio 线程池上限 40 被逐个吃干 → 全站 504；
- `realtime.py:222` 的 `_tick_loop` 是**单条**守护线程，`get_quotes → fetch_history` 一旦卡死，
  而 `_started` 守卫永不重启 → **WebSocket 报价推送永久停止且无自愈**；
- `engine/stream.py` 的 `_poller` 走同一把锁 → 行情中枢整体停摆。

**修法**　改成 futures 单飞（跟随者只 `fut.result(timeout=30)`，**绝不加锁**）；
若坚持用 Lock，则 `finally` 必须**无条件** release。

---

### P0-3　`stop_type="none"`（前端默认值）仍然带一个 −25% 隐藏硬止损

**位置**　`backend/app/risk/stops.py:100-101` + `:131-135`

```python
elif cfg.stop_type == "none":
    d = ep * float(cfg.max_stop_pct or 0.25)      # ← 悄悄给了 25% 的止损距离
...
# update() 第 1 步，没有任何 stop_type 守卫：
if side > 0 and low <= s.stop_price:
    return True, self._stop_reason(), min(s.stop_price, high)
```

**实测**　`StopConfig(stop_type="none")` → `initial_stop = 75.00`（成本 100），`low=60` → 返回 `触发=True, reason=止损`。

**矛盾点**　`api/backtest.py:26` 默认就是 `stop_type="none"`，
同一文件 meta 里的标签写着 `{"key":"none","label":"不启用止损","desc":"仅靠策略信号离场"}`。
同理 `stop_type="time_stop"` 落入 `else` 分支拿到 `stop_value=3.0` → 静默叠加一个 3% 价格止损。

**后果**　因为项目铁律要求"回测与实盘共用 StopTracker"，实盘 `_check_stops` 同样会在 −25% 平仓。
策略研发期看到的所有"无止损"曲线都含隐藏止损，**网格寻优（`grid_optimize`）结果整体失真**。

**修法**　在 `update()` 里按 `stop_type` 门控初始价格止损；`none` 时给一条与 `max_stop_pct` 语义解耦的兜底。

---

### P0-4　口令 > 72 字节 → 注册/改密直接 500，且登录永久失败无提示

**位置**　`backend/app/security.py:28-29`

```python
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode()   # 无 try/except
def verify_password(password: str, hashed: str) -> bool:
    try: ...
    except (ValueError, TypeError):
        return False        # ← 反而悄悄返回 False
```

**实测**（项目 venv，`bcrypt 5.0.0`）：

| 口令 | 结果 |
|---|---|
| `a` × 72 | OK |
| `a` × 73 | `ValueError: password cannot be longer than 72 bytes` |
| `中` × 25（75 字节） | `ValueError` |

而 `SetupRequest.password` 允许 256 字符，`password_strength()` 只要求 ≥10 字符
→ **中文口令 25 个字即触发**。

**后果**　首次注册 500；已注册用户改长口令同样 500；
更糟的是旧用户（口令被旧版截断存储）登录时 `verify_password` 静默返回 False，
**永远登录不上且界面无任何提示**。

**修法**　`hash_password` 前置：`pw.encode()[:72]` 显式截断 + 在 UI 明示"口令按前 72 字节生效"。

---

### P0-5　三个风控参数**永久失效**（UI 能设、能存、能显示，但从不生效）

`GuardContext` 的 `market_exposure` / `orders_today` / `orders_last_minute` 三个字段，
在全部 **4 处构造点**（`api/trading.py:119`、`:174`、`engine/live.py:572`、`proposals.py:228`）**均未赋值**。

实测全仓扫描：`app/` 下除 `guardrails.py` 自身的 dataclass 默认值外，**无任何赋值点**。

→ 后果：

| 风险中心可配置项 | 实际状态 |
|---|---|
| `hk_max_gross_exposure_pct`（港股敞口上限） | 恒不成立（`hk_now` 恒为 0） |
| `max_daily_orders`（日内下单笔数） | 恒不成立 |
| `max_orders_per_minute`（每分钟下单） | 恒不成立 |

`max_orders_per_minute` 的代码注释写明是为防止 IBKR 账户被限流封号 —— **这条保护目前是空的**。

---

### P0-6　日亏/回撤熔断把**减仓单**一起拦掉

**位置**　`backend/app/risk/guardrails.py:223-243`（`is_reducing` 在 249 行才算）

```python
if day_pnl_pct <= -limits.max_daily_loss_pct:
    return GuardResult(False, "当日亏损…当日禁止继续开仓", "DAILY_LOSS_LIMIT")   # ← 拦的是所有方向
if dd_pct <= -limits.max_drawdown_pct:
    return GuardResult(False, "账户回撤…全部禁止开仓", "MAX_DRAWDOWN")
```

文案写"禁止继续开仓"，代码拦的是**所有方向**。

**后果**　触发熔断后引擎既不能止损、也不能按信号离场，只能干等到次日或人工干预。
**与"熔断是保护资金"的设计意图完全相反。**

**修法**　把两个判定移到 `is_reducing` 之后，加 `if not is_reducing:` 守卫。

---

## 三、P1 · 功能静默失效与资金安全风险

| # | 位置 | 问题 | 证据/后果 |
|---|---|---|---|
| P1-1 | `data_provider.py:285,674` | 增量更新对已归一化的缓存**二次归一化** | 实测：输入 `2026-09-21 19:00` → 一次 `15:00` → 二次 `11:00`，**每次漂移 4h**；日线 TTL 6h，命中率 100% |
| P1-2 | `brokers/ibkr.py:1131,1148` | 分钟/小时历史：naive `start_ts` 与 tz-aware bar index 比较 → `TypeError`，且在 try 之外，被 `data_provider.py:649` 的 `except: pass` 静默吞掉、不写 `_last_errors` | **项目主打的"IBKR 分钟级回溯数年"完全不可用**；美股分时永远走 yfinance 1m（仅 5 天、~15 分钟延迟），且运维看不出来 |
| P1-3 | `news/ibkr_news.py:49,73` | 用了阻塞版 `reqHistoricalNews`（应 Async）；`reqNewsBullets` 方法不存在（实测 `hasattr(IB,'reqNewsBullets') == False`，实际为 `reqNewsBulletins`），两处都被 `except: return []` 吞掉 | IBKR 新闻功能等于不存在 |
| P1-4 | `engine/optimizer.py:322-325` | BB 步长符号错误：凹目标上升方向 `sᵀy < 0`，条件写 `sy > 1e-18` 恒不成立 | 实测 6 资产：`max_sharpe` 得 Sharpe **26.33**，正确写法参照解 **29.37**，**差 10.4%**。（注：`min_variance` 因有 `step*=0.5` 回退自矫正，与参照解差距 0.00%，**不受影响**） |
| P1-5 | `trading.py:117` / `live.py:567` / `proposals.py:226` | 敞口用 `p.market_value`（**原币**）与 `acc.equity`（USD base）混比。`fx.py` 文件头自己写着"直接相加就是错的" | 港股持仓被虚增约 **7.8 倍**敞口；单标的/总敞口上限在港股上形同虚设 |
| P1-6 | `engine/live.py:572 → 650` | 同 tick 循环内从不回写 `ctx.gross_exposure` / `open_positions` | 10 只标的各 20% 目标权重 → 一轮 tick 全部通过检查，实际建仓 **200%** |
| P1-7 | `engine/live.py:416,452` | 止损平仓与保护性委托**绕过 `check_order`**；且平仓后 tracker reset 被下一 tick 接管重建同参数止损 | 黑名单/交易时段/单笔金额/做空校验在止损单上全失效；可能**隔 tick 重复下市价卖单**（`exec_interval_sec` 可设 0.05s） |
| P1-8 | `engine/metrics.py:12,70,159,196` | 年化因子硬编码 252，`rf` 恒为 0（调用方不传） | `BacktestSpec.interval` 支持 1h/30m/15m/5m/1wk → **1h 回测夏普与波动率低 √7≈2.65 倍**，1wk 高 0.45 倍 |
| P1-9 | `api/trading.py:28` vs `:294` | 下单通道由**券商端口**推导，界面显示的 `mode` 来自 `appstate.current_mode()`（重启恒回 paper） | 三重锁仍生效（非越权），但**状态误导**：显示"模拟盘"时可能真实下单。且 AIOps 实盘口令提示用 `current_mode` 判定 → 端口 7496 + 显示 paper 时**不弹口令框，批准必然 403，功能不可用** |
| P1-10 | openapi `security` 为空 | 13 个 GET 路由无 Bearer 依赖：`/market/{universe,quote,overview,data-source,snapshot,indicators,catalog}`、`/strategies`、`/strategies/dsl`、`/backtest/meta`、`/optimize/meta`、`/health`、`/intel/bridge/*` | bridge 有自己的 token、health/auth 合理；但 market 几个会**触发外网抓取**，存在资源放大面。绑 127.0.0.1 + CORS 白名单缓解了大部分风险 |
| P1-11 | `frontend/src/main.tsx`、`App.tsx` | **全项目无 ErrorBoundary**（grep 零匹配），而页面有大量裸 `.toFixed()`（`Dashboard.tsx:197`、`Market.tsx:507`、`Portfolio.tsx:167`、`Intel.tsx:494`…） | 后端任一字段缺失/改名 → **整页白屏**，连侧边栏都没有 |
| P1-12 | `pages/Market.tsx:201-221` | `load()` 里 `Promise.allSettled` 后直接 setState，**无 seq/symbol 守卫**（文件里有 `symbolRef` 但只用在 2.5s 重试分支） | 快速切换标的时：标题显示 B，K 线/指标/52 周价位全是 A 的；叠加"LIVE 实时价"角标 → **极易据错误数据下单** |
| P1-13 | `Dashboard.tsx:37-56`、`Portfolio.tsx:34-47`、`AIOps.tsx:52-61`、`AIOps.tsx:105-116`、`LiveTrading.tsx:854` | 多处请求失败既吞异常又把 `loading` 置 false | 账户接口失败 → 显示**"权益 $0.00、现金 $0.00"**且无告警；AIOps 首屏失败 = 空白壳页面；**撤单失败无提示**；**一键熔断失败无提示**（按钮转一下就恢复，用户不知道熔断有没有开） |

---

## 四、P2 · 边界与打磨

**后端**
- `market.py:227` 引用未定义的 `_dt` → `NameError` 被 `except` 吞掉 → 美股盘中 `is_today` 恒为 false
- `market.py:268` `async with asyncio.Lock()` 在协程内每次新建锁，双检锁完全失效（`:256` 的 `_ovw_lock` 定义了从未使用）
- `trading.py:38` `_currency_of`：`s.endswith(".HK") or s.endswith(".HK")` 重复条件（复制粘贴）
- `trading.py:318` `row.kill_switch = row.kill_switch` 自赋值死代码，且所在 session 不 commit
- `lots.py:75-102` `round_qty` 的 `allow_odd_lot_sell` 参数声明后从未使用 → 港股碎股永远被取整到 0，小额持仓卖不掉
- `stops.py:156-159` 波动率自适应止损用 `abs(log(ratio))` → ATR **收缩时也放宽**，与注释相反
- `stops.py:138-141` 保本止损直接赋值未与当前止损取有利方向（实测本例未复现，取决于 4 周的收益 low<class 条件）
- `stops.py:144-162` 移动止损当根更新但不当根判定 → 长上影线场景系统性少触发
- `backtest.py:308-312` NaN 价格按 0 估值 → 停牌期间权益断崖，毁掉 `max_drawdown`/`calmar`
- `backtest.py`、`optimizer.py` 裸字典下标 (`result['metrics']['total_return']`) → 缺键即 500
- `api/backtest.py` CSV 导出未做公式注入防护
- `security.py:108-112` `_attempts` 字典无界增长，且 key 含用户名 → 轮换用户名可绕过 8 次锁定
- `deps.py` 无 token 撤销机制 → 改密/登出后旧 JWT 仍可用至 12h TTL 期满
- `rankings.py:52` `constituents()` 直接读快照文件，缺失即裸 500
- `main.py:235` 统一 500 响应只有异常类名，无 request-id，日志与响应无法关联

**前端**
- 图表移动端完全不可用：`CandleChart.tsx:348` `touchAction:'none'` 吃掉页面滚动；AlertsBell 固定 `w-[400px]` 在 375px 屏溢出
- `CandleChart.tsx:219-240` hover 每次 mousemove 触发 3 次 setState；无降采样 → 4600 根 bar 时掉帧到个位数 FPS
- `CandleChart.tsx:81-93` ResizeObserver 依赖 `[]` 且 early-return 分支不挂 ref → 空数据挂载后**永久失效**，图表按硬编码 900px 绘制，滚轮缩放无反应（提示语仍显示）
- `LiveTrading.tsx:140-148` state updater 里直接 `arr.push` 改旧数组 → StrictMode 下每 tick 追加两次
- `Risk.tsx:186-263` 风控数值清空后回退 `'0'` → 保存 `max_position_pct=0` → **之后每笔订单都被护栏拒绝**，而 UI 提示"已保存"
- `Rankings.tsx:245-260` 搜索无结果时整表空白，无任何"无匹配"提示
- 配色切换只覆盖一半：`ui.tsx:625,632`、`charts.tsx:305`、`CandleChart.tsx:288+`、`IntradayChart.tsx:193+` 硬编码了 rose/emerald
- 无障碍：所有 `<label>` 无 `htmlFor/id` 关联；Modal 无 `role="dialog"`/焦点陷阱；Toast 无 `aria-live`
- `Rankings.tsx:285` `{r.price}` 未格式化 → 浮点尾数漏出（`421.55999999`）
- 定时器未清理：`Market.tsx:214`、`AIOps.tsx:79/101/114`、`ui.tsx:328`
- `Portfolio.tsx:178` `Progress max={20}` 硬编码，风控改了不跟随

---

## 五、功能不完善清单（按用户价值排序）

| 优先级 | 缺口 | 现状 |
|---|---|---|
| **高** | **移动端可用性（T-119）** | 表格横滚尚未优化，图表在触屏上完全不可交互且屏蔽页面滚动 |
| **高** | **长任务进度反馈** | 回测/寻优/优化最长挂 300s，无百分比、无已耗时、**不可取消**；超时后前端丢弃结果，用户只能干等 |
| **高** | **错误可见性** | 见 P1-13。缺全局 ErrorBoundary + 统一的错误态组件 |
| 中 | 选股搜索无键盘导航（T-116） | 不支持 ↑↓ 选择 + Enter，不能粘贴 `AAPL, MSFT` 批量加入 |
| 中 | 下单弹窗未渲染预检结果（T-115） | `POST /trading/preview` 已就绪，UI 没接 |
| 中 | 组合权益未做币种折算（T-112） | `markets/fx.py` 已就绪，回测与 UI 都没接 |
| 中 | AI 提案允许"自提案 + 自批准" | `proposals.decide()` 不校验批准人 ≠ 创建人；实盘有口令兜底，模拟盘无隔离 |
| 中 | `/ops/kill-switch?enable=false` 免口令解除熔断 | 与 `/risk/kill-switch` 的口令要求直接矛盾（AIOps 页面走的就是这条路径） |
| 中 | 有效前沿/多模型对比视图 | 后端 `frontier_points` 与多模型已支持，无 UI |
| 低 | 期权模块（T-133） | 完全未开始。已拆 T-133a/b/c 三个子任务，可行 |
| 低 | 付费数据源（T-122） | 依赖用户开通 API Key |
| 低 | 通知中心按标的过滤、K 线对数坐标/截图导出 | 打磨项 |

**已经做得好的地方**（不应被上述问题掩盖）：
- 实盘三重锁 + AI 提案第四道防线，链路完整
- 28 个策略 + AST 白名单代码沙箱（`strategies/custom.py`）
- 决策可追溯 `decision_logs`（322 条）+ 审计日志
- WebSocket 主题协议 + 有界队列（不存在背压失控）
- 174 项自检 + AI_GUIDE 机读手册 + README 线与 `.env.example` 同步
- 代码里几乎零 TODO/FIXME，**注释质量与 self-documenting 程度高**

---

## 六、建议修复顺序

**第一批（本周，影响资金安全与数据可信度）**
1. P0-1 回测敞口约束 + 现金下限 —— 影响所有回测结论
2. P0-3 `stop_type=none` 隐藏止损 —— 一行门控，影响面最大
3. P0-2 单飞锁改 futures —— 一行级改动，但解除全站卡死风险
4. P0-4 bcrypt 72 字节 —— 一行前置截断
5. P0-6 熔断放行减仓单 + P0-5 补齐三个计数器

**第二批（下一迭代）**
6. P1-1/P1-2 时区归一化幂等化 + IBKR 分钟线时区修复（同一根因，一起改）
7. P1-6 实盘 tick 内敞口快照回写；P1-7 止损单走护栏
8. P1-8 `compute_metrics` 增加 `periods_per_year`
9. P1-9 统一 mode 数据源；P1-10 补齐缺失路由鉴权
10. P1-11/P1-12/P1-13 前端 ErrorBoundary + 请求竞态 + 错误可见性

**第三批（体验）**
11. P1-4 优化器 BB 步长（`sy < -1e-18`）
12. 移动端、长任务进度、无障碍、配色统一

> **每次修复都应同步补一条自检用例。** 现有的 174 项自检覆盖了"功能存在"，
> 但缺少"数值正确"类断言 —— 这正是 P0-1/P0-3/P1-4 能一路全绿通过的原因。
> 建议新增三类对照测试：无约束最小方差 vs 解析解、回测敞口 ≤ gross_pct、止损行为与 `stop_type` 一一对应。

---

## 七、附录：复现方式

本次评估的实证结论均可用以下方式复现（需在项目 venv 内）：

```bash
cd backend
.venv/Scripts/python.exe -c "
import bcrypt
bcrypt.hashpw('a'*73, bcrypt.gensalt(rounds=4))   # -> ValueError
"

cd backend && .venv/Scripts/python.exe -c "
from app.data_provider import _normalize
import pandas as pd
idx = pd.to_datetime(['2026-09-21 19:00:00'])
df = pd.DataFrame({'open':1.,'high':1.,'low':1.,'close':1.,'volume':1.}, index=idx)
print(_normalize(_normalize(df)).index)          # -> 11:00:00（漂移 8h）
"

cd backend && .venv/Scripts/python.exe -c "
from app.risk.stops import StopTracker, StopConfig
tr = StopTracker(StopConfig(stop_type='none')); tr.open(1, 100.0, 0, None)
print(tr.update(high=101., low=60., close=70., atr_value=None, bar_index=1))   # -> (True, '止损', 75.0)
"
```

回测敞口问题：构造 6 只同向趋势标的 + monkeypatch `app.engine.backtest.fetch_many`，
`dual_ma_trend` + `sizing_method='weight'` → `max(curve[i]['exposure']) == 6.1`。
