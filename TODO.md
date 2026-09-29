# QuantDesk for IBKR · 全平台深度分析与施工总纲（TODO.md）

> 生成时间：2026-09-23 22:40 ｜ 依据：代码全链路审查 + 九轮迭代实测 + 用户反馈
> 使用方法：按优先级 P0 → P5 施工；每项有【涉及文件 / 施工步骤 / 验收标准】；
> 完成一项把 `[ ]` 改 `[x]` 并在文件尾部《施工日志》追加一行。**先做 todo 再写代码的铁律继续生效。**

---

## 〇、现状一句话总结

平台已具备：28 策略 + 回测/优化器 + 9 种止损 + 三重锁实盘安全 + 新闻 4 源 + S&P500 榜单 + 决策可追溯（decision_logs）+ AI 接管 API（/ops/*）+ AI_GUIDE 手册 + 本地/LLM 双引擎研判（本轮起融合实时价）。

三大短板（用户视角）：
1. **数据实时性不彻底** —— AI 研判本轮已修（实时价融合），但提示引擎 alerts、行情页快照、引擎 tick 等链路的实时性程度不一；
2. **AI 接管闭环缺"实时感知"** —— /ops/overview 是拉取式快照，没有推送（#37 WebSocket 未做），AI 与人看到的价格有延迟；
3. **执行层简化** —— 回测撮合是 bar 级、费用是统一 bps、做空校验未接风控、币种未入表。

---

## P0 · 数据实时性与正确性（AI 接管的前提）

### T-101 AI 研判实时价融合 ✅ 已完成（2026-09-23）
- [x] `_merge_realtime()`：实时报价融合进日线最后一根（盘中更新）或追加今日 bar
- [x] `market_snapshot` 输出 `realtime` 块（realtime/mode/quote_source/quote_ts）
- [x] LLM context 增加「实时盘」块；前端 AICopilot 显示「实时盘·来源」绿标 /「非实时」灰标
- 验收：AAPL 分析价 == 实时报价（intraday_update）；0700.HK appended_today（腾讯秒级源）✅

### T-102 提示引擎（alerts）实时化 ✅ 已完成（2026-09-23）
- [x] `alerts.py::_intraday_alerts`：日内急涨/急跌（US±5%/HK±4%，hot/warn）+ 波动预警（±3%，info），dedup 按天+类型
- [x] quote 来源：港股腾讯直连（秒级）/ 其余 get_quote；与日线规则（52周/放量/跳空/RSI）互补
- [x] `record_events` 返回真正入库的事件 → `scan` 结果带 `events` → realtime alerts 循环（60s 触发、90s 冷却）推送到 WebSocket
- 验收：自检 147/147；盘中触发路径 = rt_alerts 线程 → scan → 新事件 → ws 广播 → AlertsBell 即时弹 toast

### T-103 行情页快照（snapshot）实时化标注 [P0]
- [ ] **现状**：`/market/snapshot` 用 `market_snapshot`（本轮已融合实时价）但前端「关键价位与结构」卡片的"现价"显示 snap.price（已是实时价 ✅），需要补数据时间与来源标注；「指标读数」为日线+实时价混合口径，需在 UI 说明。
- [ ] 施工：Market.tsx 侧栏卡片 subtitle 加 `realtime.quote_source + quote_ts`；「指标读数」卡注明"含实时价"。
- 验收：盘中打开行情页，现价与券商/腾讯报价一致（±20s）。

### T-104 分钟级数据接入 AI 研判（可选档）[P0]
- [ ] **现状**：研判只用日线 + 实时价点；日内交易者（5m/15m）看不到分钟级结构。
- [ ] 施工：`market_snapshot(symbol, lookback_days, with_intraday=False)` 增加 `intraday` 块：`fetch_history(interval='5m', 近 5 日)` → 最近 N 根的 VWAP、开盘区间（ORB）、盘中年化波动、分钟级 RSI；horizon == 'intraday' 时前端可请求 `?intraday=1`。
- 涉及：`app/ai_analyst.py`、`app/api/ai.py`、`AICopilot.tsx`
- 验收：intraday 模式下 LLM context 出现分钟级结构块；本地引擎的日内维度分用到它。

### T-105 行情时间戳统一与"数据新鲜度"全局显示 [P1] ✅ 核心完成（2026-09-24）
- [x] Layout 顶栏 DataClock：实时链路状态灯（绿=推送中/黄=停滞/红=断线）+ 最近行情时间（1s 刷新），断线时各页自动降级轮询
- [x] 各响应已带 as_of/ts/quote_age_sec 等时间字段（分时/榜单/AI 快照）
- [ ] 全站 server_time 统一注入（后续小项）

---

## P1 · AI 接管闭环（让 AI 真正"看见并操作"）

### T-106 WebSocket 集中订阅与广播 ✅ 核心已完成（2026-09-23，秒级）
- [x] `app/realtime.py`：主题 hub（连接注册/主题订阅/按连接过滤广播）+ 后台双循环（tick 2s / alerts 60s，守护线程，首个连接接入时自动启动）
- [x] `/api/ws` 主题协议端点：`{"action":"sub","topics":["quotes:AAPL","intraday:SYM","alerts"]}`，per-connection asyncio.Queue + call_soon_threadsafe 跨线程投递；4401 鉴权失败
- [x] 秒级报价源优先级：IBKR 流式缓存（reqMktData 已订阅标的内存直读，0 请求）→ 港股腾讯快照直连（绕过 20s 报价缓存）→ 免费源（rt_delayed 标注）
- [x] 推送消息附带 `rt_t`（交易所本地时间 HH:MM）+ `rt_delayed`
- [x] 前端 `lib/realtime.ts`：单例 WebSocket + 主题引用计数 + 指数退避重连（4401 慢速 15s 等token 刷新）+ 断线恢复自动重订阅
- [x] Market 页接入：顶卡价格 LIVE 实时跳动 + 分时图秒级延伸（同分钟替换尾点/跨分钟追加，均价线递延）
- [x] AlertsBell 接入 `alerts` 主题：新告警秒级到达（轮询保留作降级）
- [ ] T-106b：Dashboard/WatchBar/QuickPicks/AIOps 各页从轮询迁移到 ws（后续）
- 验收：Node ws 客户端实测 sub quotes:0700.HK → 每 4~5s 收到推送（rt_t=HK 本地、delayed=false）；147/147 + smoke 36/36 ✅
- **2026-09-24 T-106b 完成**：WatchBar / QuickPicks / Dashboard 三页报价主链路已迁 WebSocket（轮询放宽至 60s 作降级保底）✅

### T-107 AI 研判 → 建议单 → 人工/自动执行闭环 ✅ 已完成（2026-09-24，实盘链路已补强）
- [x] 新表 `ai_proposals`（symbol/action/size_pct/entry/stop/take_profit/rationale/factors/status/created_by/order_id）
- [x] AI 研判 |score|≥45 且建议仓位 ≥5% 自动生成提案（仅 proposed，**绝不自动执行**）；API 亦可创建（POST /ops/proposals）
- [x] AIOps 页「AI 提案」审批区：批准执行（走完整下单链：熔断→实盘三重锁→护栏→券商下单→落库）/ 拒绝；overview 带 pending_proposals
- [x] 决策日志闭环：PROPOSED → APPROVED → ORDER（order_id 回写）
- [x] **实盘链路补强（2026-09-24）**：实盘模式批准需第四道防线（账户口令强校验，PermissionError 403）；AIOps 实盘就绪红/黄条 + live_ready/live_reason 展示；overview.system 补 live_unlocked；AI_GUIDE 实盘四步手册
- 验收：端到端实测 创建→批准→真实下单（#18）→拒绝路径；重复操作 409；实盘未解锁时批准自动降级模拟并给出原因 ✅

### T-108 AI 接管手册 2.0（含实时协议）✅ 已完成（2026-09-24）
- [x] AI_GUIDE.md 增：/api/ws 主题协议、提案 API（含「AI 禁止调用 approve」硬约束）、实时盘字段、分钟级结构
- [x] /api/ops/guide 机器可读（返回全文，自动同步）

### T-109 多模型并行研判对比 ✅ 核心完成（2026-09-24）
- [x] 配置 `QD_AI_EXTRA_MODELS="name|url|key|model;..."`；_llm_call 按名路由
- [x] /ai/status 返回 extra_models；AnalyzeRequest/ChatRequest 加 model 参数；AICopilot 模型选择器
- [ ] 同一标的并排对比视图（后续迭代）

---

## P2 · 交易执行与风控强化

### T-110 tick 级回测撮合引擎（原 #38）✅ 已完成（2026-09-24）
- [x] BacktestSpec `execution="close"|"intra"`：intra 模式下开盘已跳空穿越止损 → 按开盘价成交（保守口径，多头 min(open,stop)、空头 max(open,stop)）；StopTracker 复用不另写
- [x] 配套 T-111 fee_model 同批落地
- 验收：147→160 项自检全绿（撮合回归无破坏）✅

### T-116 行情选股输入升级 [P1]
- [ ] 搜索下拉支持键盘 ↑↓ 选择 + Enter 确认；输入即时显示"已关注/持仓"角标；支持粘贴 "AAPL, MSFT" 多标的批量加入关注。
- 验收：纯键盘完成"搜 → 选 → 跳转"。

### T-111 费用模型真实化（原 A6）✅ 已完成（2026-09-23）
- [x] `markets/fees.py` 完整分项模型早已就位（US 佣金 $0.0035/股 min $0.35 + SEC/TAF/CAT；港股佣金+印花税 1‰+交易费+SFC/FRC 征费+CCASS）
- [x] 回测接入：BacktestSpec `fee_model="bps"|"market"`，fill() 走 `total_fee()`
- 验收：SPY 100 股 @500 = $0.35（最低佣金）✅；0700.HK 100@300 含印花税 ✅（自检 2 项）

### T-112 币种字段贯穿（原 A7）✅ 已完成（2026-09-23）
- [x] orders/fills 表加 `currency` 列（轻量迁移 ALTER TABLE）；手动下单与 AI 提案执行落库均写 USD/HKD
- [ ] 组合权益按汇率折算（markets/fx.py 已有汇率工具，UI 展示层后续接）

### T-113 做空校验接入风控（原 A8）✅ 已完成（2026-09-23）
- [x] `guardrails.py`：allow_short=false（默认）→ 裸卖拒绝（SHORT_FORBIDDEN）、卖超持仓缩减为平仓、回补超空头缩减；RiskLimits.allow_short + RISK_COLUMNS 白名单 + risk_config 表列
- 验收：自检 4 项（裸空拒/缩减平仓/白名单读写/迁移生效）✅

### T-114 市场感知风控（原 C1）✅ 已完成（2026-09-23）
- [x] allow_extended_hours / hk_max_gross_exposure_pct / max_daily_orders / max_orders_per_minute 均已在 RiskLimits + 白名单（此前已实现）
- [x] 港股每手股数对齐：check_order 内 round_qty（开盘/加仓向下取整到整手，减仓允许碎股）
- 验收：手数对齐警告与 adjusted_qty 生效 ✅

### T-115 订单预检增强（原 C2）✅ 已完成（此前轮次 + 2026-09-23 核验）
- [x] `POST /trading/preview` 已存在：护栏 dry-run + 费用预估 + 组合影响 + 参考价
- [ ] 前端下单弹窗渲染预检结果（后续小项）

---

## P3 · 前端体验打磨

### T-117 K 线图增强（继续迭代）[P2] ✅ 核心完成（2026-09-24）
- [x] 成交量副图加 20 日均量线（放量/缩量一眼可辨，琥珀虚线）
- [x] 悬停 tooltip（本轮早前完成）+ 最高/最低点标注（T-141 批次）
- [ ] 十字线 Y 轴价格跟随标签、对数坐标、截图导出（小项，后续迭代）

### T-118 榜单页增强 [P2] ✅ 核心完成（2026-09-24）
- [x] 排序/方向/条数 localStorage 记忆（刷新保持）
- [ ] 行业热力图 tab、"今日新高/新低"过滤（后续迭代）

### T-119 移动端可用性 [P3]
- [ ] Dashboard/Market/AIOps 三页做响应式断点（xl 以下单列）；表格横滚优化；底部导航。
- 验收：390px 宽度下核心页可操作。

### T-120 通知中心 [P2] ✅ 核心完成（2026-09-24）
- [x] AlertsBell 分桶过滤（全部/未读/高危）
- [x] 浏览器 Notification API 桌面通知（首次使用提供授权按钮；hot/warn 级弹出，tag 去重）
- [x] WebSocket alerts 主题秒级到达（T-106）
- [ ] 按标的过滤、点击跳转带 symbol（小项）

---

## P4 · 数据源与市场扩展

### T-121 数据源健康监控页 ✅ 已完成（2026-09-24）
- [x] Settings「数据」tab 内嵌：各源状态卡（available 点标）+ `recent_errors` 失败原因展示（健康时绿条）+ 一键探测链路（SPY 实时延迟）+ 原有清缓存
- 验收：recent_errors 已在 /market/data-source 暴露 ✅（自检 1 项）

### T-122 Polygon / Databento 付费源适配 [P3]（依赖付费 API Key，待用户开通后施工）

### T-133 期权模块（ covered call / 铁鹰 / 波动率风险溢价 ）[P3]
- [ ] IBKR 期权链（reqSecDefOptParams）→ 到期/行权矩阵 → 策略组合损益图（到期 payoff）→ 建议单（如 covered call: 持仓 + 卖购）。
- 大工程，拆三个子任务：T-133a 数据层 / T-133b 定价与希腊字母（BS + 数值 IV）/ T-133c UI 与提案。
- 验收：SPY covered call 到期损益曲线与券商理论值一致。

### T-134 加密与外汇行情（只读）✅ 已完成（2026-09-24）
- [x] UNIVERSE 增加 BTC-USD / ETH-USD / EURUSD=X（只读行情，搜索/行情分析可用；不在交易白名单）

---

## P5 · 工程质量与安全

### T-135 自检扩充（原 E1，111→180+）[P1] ✅ 核心完成（2026-09-24）
- [x] 新增 13 项：美股/港股费用模型、分钟级结构字段、裸空拒绝（SHORT_FORBIDDEN）、卖超缩减、提案创建/拒绝/重复操作 409/批准执行回写 order_id、overview 待审字段、订单预检、数据源诊断字段
- [x] 现状：`run_checks.py` **160 项全绿**
- [ ] ws 协议用例与币种折算用例（后续补至 180+）

### T-136 AI_GUIDE / README / .env.example 同步（原 E2）✅ 已完成（2026-09-24）
- [x] AI_GUIDE.md：ws 协议 + 提案 API + 实时盘/分钟级结构字段（T-108）
- [x] .env.example 线：QD_AI_EXTRA_MODELS 说明写入 /ai/status note（README 实时性架构一节后续补）

### T-137 性能预算与延迟面板（原 B6 收尾 + D3）✅ 核心完成（2026-09-24）
- [x] Settings 数据源健康卡含探测链路按钮（实时往返延迟）+ recent_errors 展示（与 T-121 合并交付）
- [x] 榜单刷新耗时实测：后台 ~85s 拉齐 503 只、用户侧 <20ms（stale-while-revalidate）
- [ ] p50/p95 分位数统计与缓存命中率展示（后续迭代）

### T-138 安全加固复查 [P2] ✅ 核心完成（2026-09-24）
- [x] /ws 鉴权（token query param，4401）✅（T-106 已实现）
- [x] 实盘三重锁自检用例已在 147 项自检中（环境开关关 → 引擎启动被拒等）✅
- [x] AI 提案硬边界：AI 永远只有建议权，approve 仅人工（AI_GUIDE 明文禁止 AI 调 approve）✅
- [ ] JWT 刷新流程与 IP 维度限流（小项，后续迭代）

### T-139 备份与数据安全 ✅ 已完成（2026-09-24）
- [x] 服务启动时 SQLite `VACUUM INTO` 在线备份 → `runtime/backups/quantdesk-<时间戳>.db`，自动保留最近 7 份
- 验收：启动日志出现备份路径 ✅

### T-140 Docker 化（可选）[P3]（标注可选，跳过）

---

## 附：技术债与铁律（施工时必须遵守）

1. **hooks 必须在 early return 之前**（React #300 白屏教训）；构建链已固化 `npm run lint:hooks`。
2. **.bat/.cmd 只写 ASCII + CRLF**；for 块内 echo 不含裸括号。
3. **SQLAlchemy 唯一键去重**：先查后 add，异常即 rollback（merge 不看唯一键）。
4. **无未来函数**：t 收盘信号 t+1 开盘成交；新开仓当根不查止损。
5. **实盘三重锁**不得绕过或简化；RISK_COLUMNS 白名单外字段会被静默丢弃。
6. **回测/实盘共用 StopTracker**；本机 pandas 3.0（避免 stack/unstack 做 tr）；safe-delete 保护下 dist 清理走 prebuild rename。
7. **后端只监听 127.0.0.1**；配置涨红跌绿（format.ts）。
8. **AI 输出的一切交易动作必须经过 ai_proposals + 人工批准**（T-107 落地前，AI 只允许 ANALYZE/DRY_RUN）。
9. **单文件规模上限与组件化**（2026-09-27 定 —— 不再「先堆着、以后再说」）：
   - **阈值**（软 = 超过后新功能不得再加；硬 = 冻结，只允许修 bug）：

     | 类型 | 软上限 | 硬上限 |
     |---|---|---|
     | 后端模块 `backend/app/**`（`.py`） | 600 | 900 |
     | 前端页面 `frontend/src/pages/**`（`.tsx`） | 600 | 900 |
     | 前端组件 `frontend/src/components/**`（`.tsx`/`.ts`） | 400 | 600 |
     | 前端工具 `frontend/src/lib/**`（`.ts`） | 400 | 600 |

   - **写新代码的规矩**：
     - 新建文件不得超软上限；往已有文件加功能前，**先看它是否已超软上限** ——
       超了就**新建模块**，不要接着加。
     - **前端**：页面只做**编排**（取数 + 布局 + 状态），可复用的业务块一律抽到
       `components/`。**同一页面内重复出现的卡片 / 表格 / 表单块必须抽组件，
       禁止复制粘贴。**
     - **后端**：路由文件（`api/*.py`）只做参数校验与编排；业务逻辑放 `engine/`
       或独立模块，按职责拆（数据获取 / 撮合 / 券商适配 / 编排 各自独立）。
   - **规则已可执行（2026-09-29 补 —— 此前只是「写在文档里」，实测清单全部过期）**：

     本条的旧「冻结清单」已被证伪并删除：清单写 `backend/app/intel.py` 1192 行，实际 **1916**；
     `Backtest.tsx` 写 1086，实际 **1641**；而 `Intel.tsx` 写 1269（已拆完，实际 **329**，在限内）。
     **靠人记的清单 = 不存在的规则。** 现在改为**棘轮（ratchet）守卫**：

     ```bash
     cd backend && .venv/Scripts/python.exe ../tests/run_checks.py size   # 秒级，不联网不碰库
     ```

     - 判定：① 超软上限且**不在基线** → FAIL（新债）；② 在基线但**比基线更长** → FAIL（棘轮被突破）；
       ③ 在基线且未增长 → 通过（存量债在报告里列出）；④ 已降到软上限内 → 提示从基线摘掉。
     - 基线文件 `tests/size_baseline.json`（存量债基线，**2026-09-29 冻结时 27 个 → 同日晚 21 个**：
       `Backtest.tsx` 1641→491、`Optimize.tsx` 861→345 已拆分并摘除，详见施工日志）；
       重算用 `python tools/gen_size_baseline.py` —— ⚠️ **只在真正拆分完成后跑**，否则等于把债锁死。
     - ⚠️ **守卫报 FAIL 不等于「要重算基线」**：同期 `Market.tsx`(972→1017) 与 `Rankings.tsx`(656→658)
       的增长来自**并行会话**，守卫如实报 FAIL 是正确行为。把别人的增长写进基线 = 让棘轮失效。
     - 规则实现见 `tests/size_check.py`。⚠️ 注意它的文件发现用 `rglob` 而非 `Path.glob(".../**/*.py")`：
       后者在本机 Python 上**不匹配顶层文件**，会漏掉 `intel.py` 这个最大的违规者。
   - **拆分纪律**：一次只拆一个文件；每拆一步立刻跑
     `run_checks.py strategies|optimize|api|size` + `tsc` + `vite build` + `smoke`；
     **覆写整个文件前必须先核对它全部的既有导出** —— 本项目已两次因此丢函数
     （`get_profile` 被 Write 覆盖删除，导致 `/market/rankings/profile` 500）。
10. **datetime 口径：维持现状，不统一**（2026-09-27 决策，**不要再当 bug 提**）：
    当前是「写入 aware UTC → 存进 naive 列 → 回读丢时区」的混合口径。
    已知它会导致 naive/aware 比较抛 `TypeError`（历史踩坑 3 次），
    但全局统一会**改变数据库时间字段语义**，历史数据与新增数据有混用风险，
    收益不抵风险，故**明确决定不改**。新增代码请遵守：
    - 不要假设从 DB 读出的时间字段带时区（`row.created_at.tzinfo` 通常是 `None`）；
    - 与 DB 时间比较前，先确认两侧 tzinfo 状态，必要时统一成 naive UTC 再比；
    - 需要绝对时刻时用 `datetime.now(timezone.utc)`，**不要**直接与 DB 值相减。

### T-141 当日分时走势图 ✅ 已完成（2026-09-23；2026-09-24 补休市回退与日线实时 bar）
- [x] 后端 `/market/intraday`（1m 切片 + 累计均价 VWAP + 昨收基准 + delayed 标注）
- [x] **休市回退（2026-09-24）**：非交易时段自动展示最近交易日分时，响应带 `trade_date/is_today`，前端明示"最近交易日 X 的分时"；加载失败显示错误文案（不再无限 loading）
- [x] **K 线/折线图当日实时 bar（2026-09-24）**：`/market/history` 1d 响应融合实时价为末根（realtime=true），副标题标注"末根为实时价"——解决"K 线模式看不到当日走势"
- [x] 港股分钟源：腾讯 `minute/query`（完整当日分时，累计量差分还原，09:30~16:08 港交所本地时间）
- [x] 美股：yfinance 1m（~15 分钟延迟，UI 明确标注；IBKR 连接后 fetch_history 自动切实时源）
- [x] 时区语义统一：所有源写入缓存前统一为「真实时刻的 NY naive」，展示层 HK 用 NY→HK 还原（曾因腾讯 HK-as-UTC 与 yfinance aware→NY 两种语义混写缓存导致分时错日）
- [x] 前端 `IntradayChart.tsx`：价格线+均价线+昨收虚线+涨跌分域填充（红涨绿跌）+量副图+悬停明细；Market 页图表类型新增「分时」tab，30s 自动刷新 + WebSocket 实时延伸
- 验收：SPY 分时回退 2026-09-23（390 根，is_today=false）；0700.HK 今日盘中 85 根实时（tencent-hk-m1）；日线 realtime=true 末根实时价 ✅

## 施工日志（倒序追加）

- 2026-09-29 深夜：**组合优化页「小白友好化」+ 术语/排版模块提升 + 规模债真还**。承前一条（回测中心小白化），用户说「可以 继续做吧」，于是把同一套做法复制到优化页，并顺手把两个共享模块从业务目录里提出来。

  **① 术语词典与排版零件提升为共享模块（先做，因为它是优化页的前置）**
  - 回测页的 `components/backtest/glossary.ts` + `TermTip.tsx` → **`components/terms/`**（`glossary.ts` 通用+回测 351 行、`optimize.ts` 优化专属 187 行、`index.ts` 合并入口 50 行、`TermTip.tsx` 102 行）。
  - `components/backtest/parts.tsx`（Chip/Step/Section）→ **`components/form/parts.tsx`**。
  - 理由：优化页要用同一本词典、同一套零件，去 `import` 一个 `backtest/` 下的东西是**反向依赖**，迟早各自漂移出副本。8 个回测组件的 import 路径同步更新，render-check 路径与文案卫生清单同步。
  - ⚠️ **合并词典时显式检测重名并抛错**：`{...A, ...B}` 裸合并会让后写的词条**静默覆盖**先写的解释，界面上不报任何错。第一次合并就抓到一处（`interval` 在两个领域文件里都有），已删重。这类问题构建/typecheck/渲染全都拦不住，所以让它直接炸。

  **② 优化页：861 → 345 行（页面软上限 600）**
  - 拆成 `components/optimize/`：`ConfigPanel`(341) / `ResultPanel`(370) / `FrontierTab`(70) / `PlainSummary`(307) / `SaveModal`(62) / `presets`(92) / `types`(100)。页面只留状态 + 取数 + 组装。
  - 新增 `lib/optimizePrefs.ts`（标的池/风险预算的严格解析 + 配置持久化）、`lib/dateRange.ts`（`yearsAgo`，从 `backtest/presets.ts` 提出 —— 优化页也要用，复制一份等于让「UTC 会得到昨天」这个坑各自漂移一次）。
  - 三件套照搬回测页：**① 四步向导**（放哪些标的 → 想要什么效果 → 用多长历史 → 限制条件）；**② 新手模式默认开**（协方差估计 / 期望收益估计 / 相关簇阈值 / 单簇上限 / 风险预算收进 `<details>`，关掉即全量平铺 —— 功能一个没删）；**③ 每个术语都能悬停**（新增 25 条优化专属词条，数值门槛全部取自后端 `_OBJECTIVE_META` / `_COV_META` / `portfolio_stats`，不是编的经验值）。
  - **一句话结论 = 有没有打赢等权基准**（页面自己的注释就写着「打不过就别优化」）。判定抽成纯函数 `summarizeOptimize`，判定口径：夏普差 >0.05 算赢、<-0.05 算输、±0.05 内算打平（不把估计噪声当能力）；目标本身就是等权 → `not_opt`；约束无解 → `infeasible`。
  - **诚实性**：全部标的是合成行情 → 判定 `unknown` 并明说「随机生成的假价格，没有任何参考价值」；部分合成 → 保留结论但点名是哪几个；缺夏普字段 → `unknown` + 如实说缺什么，**绝不按 0 编造**。

  **③ 守卫**
  - `render-check.mjs` 新增 Optimize 条目（**+69 条**，总数 163 → **232**）：四步骨架、术语触发器、21 个术语 id 全覆盖、优化目标 key 与后端 `OBJECTIVES` 对齐、标的池可解析性、自由文本解析（大写归一/去重/保序/剔除垃圾/丢弃 NaN 预算）、以及 **15 条 `summarizeOptimize` 纯函数断言**（含合成行情与缺字段两条诚实性）。
  - 新增 `scripts/visual-check-optimize.mjs`（`npm run test:visual:optimize`）：**44/44** 真实 Chrome，含「气泡不被祖先 overflow 裁掉」「关掉新手模式后高级项平铺且推荐按钮消失」「一键推荐真的填进表单（按 label 定位，不用 `input[type=number]`）」「真跑一次优化后结论卡片按人话渲染」「三个 tab 都能切」。
  - 顺手修了 3 处新断言暴露的问题：`termTips` 必须写**词条的 title**（我写了「开始日期」而词条 title 是「起始日期」）；「没打赢等权」这句结论原本写在 JSX 里、纯函数断言不到 → 移进 `caveats`；新写的 `PlainSummary` 里有一个 `**加粗**` 漏进了模板字符串（被文案卫生检查抓住）。

  **④ 规模债**
  - `size_baseline.json` 摘掉 `Optimize.tsx: 861`（与前一日的 `Backtest.tsx: 1641` 同理）。存量债 **27 → 21**。
  - `run_checks.py size` 仍报 `Market.tsx`(972→1017) 与 `Rankings.tsx`(656→658) 两项 FAIL —— **并行会话的改动，不是本轮**，按规矩**没有重算基线**（把别人的增长写进基线会让棘轮失效）。已把这条判断写进 TODO 铁律 9。

  **回归**：`typecheck` / `lint:hooks` / `build` 全绿；`test:topics` 10/10；`test:render` **232/232**；`test:visual:optimize` **44/44**、`test:visual:backtest` **45/45**（术语模块搬运后复验）；`run_checks.py size` 无新增超限文件。

- 2026-09-29：**回测中心「小白友好化」重构（用户驱动的体验改造）**。用户原话：「回测中心对于我（小白）来说太难用了，很多东西我都不懂，**基准标的和标的我理解不了**，希望把这套东西尽可能简化、设计得易于理解，并且**针对一些词汇都有鼠标悬浮的解释**」。三条诉求分别落地：

  - **① 简化**：`Backtest.tsx` **1641 → 491 行**（同时解决超硬上限），拆成「编排层 + `components/backtest/*` 12 个文件」。视觉上从「一屏参数墙」变成**四步向导**：用哪个策略 → 买哪些股票 → 回测多长时间 → 本金与及格线。
  - **② 易于理解**：**新手模式默认开**，高级项（数据周期/数据源/手续费/滑点/止损止盈/仓位算法）收进 `<details>`；关掉即全量平铺 —— **功能一个没删**（有断言守着「折叠区内容仍在 DOM 里」）。小白看不懂的两个词直接改名：**「标的」→「股票代码（标的）」**、**「基准标的」→「对比基准（及格线）」**，并解释成「什么都不做的对照组」。
  - **③ 悬浮解释**：新建人话词典，词条按**「是什么 / 怎么看 / 注意」**三段写（生活化类比 + 可执行动作 + 只写会让人误判的坑），覆盖配置项、23 个结果指标、交易明细列与三个进阶工具。
  - **顺带抓到两个构建/typecheck/lint/SSR 全都拦不住的真 bug**：① **编造结论** —— 历史记录缺 `benchmark_total_return` 时 `Number(undefined) → 0`，页面显示「同期基准是 +0.0%，你跑赢了」；改为 `Number.isFinite` 存在性判断 + `verdict='unknown'` + 明说「没有存基准数据」，并把判定逻辑抽成纯函数 `summarizeResult` 直接单元断言。② **符号误导** —— 指标表给所有百分比都加了 `+`，导致「年化波动 **+**9.26%」看着像收益；改为只有真正有方向的指标才带符号。
  - **行为改动**：因子诊断弹窗**打开不再自动跑**（必须点「开始诊断」）—— 用 CDP 的 `Network` 域数真实请求次数验证（DOM 断言区分不了「自动」与「手动」）。
  - **回归**：`test:render` **161/161**（回测页贡献 42 项）、新增 `test:visual:backtest` **45/45**。
  - 文档/记忆：`FIXES_2026-09-27.md` 新增 **C-9**（P2-14 从「立规矩」到「真还债」，含棘轮守卫与被证伪的旧冻结清单）、`REFERENCE.md` 新增 **§R17**。

- 2026-09-27 ⅩⅥ：**「对交易/调研真正有意义」的 AI 接入点补全 + 修一个未来函数漏洞**。用户诉求：再找找还有哪些地方值得接 AI，但**只做对实盘交易或调研有决策价值的**，不要到处加。
  
  **先做审计，再动手**：把 14 个页面 + 16 个 API 模块 + 策略引擎全过了一遍，按「是否影响真金白银或研究结论」筛出 3 个值得做、5 个明确劝退（纯展示页、每张图配点评、语料级情绪面板、财报日风险窗口、策略衰减诊断 —— 后两个缺数据管线，不建）。结论：值得做的是**批准前的反方质询**、**交易复盘**、**策略代码审查**。

  **⚠️ 顺带挖出一个真 bug（非 AI，性质严重）**
  - `strategies/custom.py::_operand_df` 的 `shift` **没有正负校验**：规则里写 `shift: -1` 会取到**未来一根**的值 → 直接构成未来函数，且能通过 API 提交、静默产出一条漂亮但虚假的回测曲线。这是**铁律 2 的实打实漏洞**。
  - 修法：`_validate_cond` 里拒绝负 shift / 非整数 shift（`RuleStrategy.__init__` 每次构造都会调 `validate_rule`，因此保存期与执行期都覆盖），`_operand_df` 里再加一道兜底 raise（防将来重构绕过校验后静默读未来数据）。
  - 回归：`tests/run_checks.py` 的 `strategies` 子集加 8 条断言（shift=-1/-60/1.5/True/'x' 必须拒绝，0/1/5 必须放行）。**前端本来就没暴露 shift**，所以漏洞仅 API 可达 —— 但仍必须堵。

  **后端（新 1 文件 + 3 个任务，任务总数 16）**
  - `app/ai_tasks_ops.py` 新增 `proposal_review`（提案二次研判）。核心是 `_proposal_checks()` —— **先确定性算出冲突再交给 LLM**，不让模型去猜本可以算准的数字：加仓后超单标的上限 / 总敞口超限 / 持仓数已满 / 未设止损 / 限价偏离现价 / RSI 超买追多 / 与本地引擎 bias 方向矛盾 / 无仓却卖出。提示词固定扮演**反方**（devil's advocate），并要求「若批准，最坏情况是什么」。规则结果同时作为本地兜底。兼容 `/ops/overview`（positions 无 `weight`）与 `/trading/positions` 两种口径 —— 缺 weight 时按 `市值/权益` 反推，否则超限检查会**静默失效**。
  - `app/ai_tasks_analysis.py` 新增 `period_review`（交易复盘）。`_period_stats()` 把订单/持仓/决策压成确定性统计量：成交与异常笔数、买卖比、标的集中度、手续费、**被拒原因频次**（同一 code 反复出现 = 配置问题而非偶发）、赢家/输家数。样本 < 20 笔时明确写「统计意义有限」。
  - `app/ai_tasks_strategy.py`（**新模块**，`ai_tasks_ops/analysis` 都已逼近 600 软上限，按领域再拆一层）新增 `strategy_code_review`。**补的是沙箱的盲区**：AST 白名单只查安全性、**不查时间语义**，`ctx.closes.shift(-1)` 能顺利通过校验。这里用 8 条高置信度模式（`shift(-N)`、`pct_change(-N)`、`bfill/backfill`、`fillna(method='bfill')`、`rolling(center=True)`、`interpolate()`、`iloc[i+1]`、`[::-1]`）确定性检测，LLM 只做解释与补充。
  - `api/ai.py`：`_DECISION_TASKS` 加入 3 个新任务（提案复核直接参与批准决策链，必须可追溯）。

  **前端（新 5 文件 + 1 次拆分）**
  - ⚠️ **先拆后加（铁律 9）**：`pages/Strategies.tsx` 已 **912 行，超硬上限 900**（冻结线）。抽出 3 个组件：`components/strategies/ParamForm.tsx`（105）、`ruleEditor.tsx`（202，含 OPS/指标白名单/CondRow/condToSpec）、`CodeStrategyEditor.tsx`（Python 代码标签页）。页面 **912 → 551**，回到 600 软上限以内。拆分**一次一个文件**，每步跑 typecheck。
  - `components/ProposalAiReview.tsx`：自包含，批准按钮旁一行。自己拉 `/risk/config` + `/trading/positions` + `/trading/account`（`/ops/overview` 的持仓不含 weight），鼠标移入刷新，避免用过期持仓复核。`AIOps.tsx` 只加 1 行挂载。
  - `components/PeriodReviewAi.tsx`：订单/持仓/账户由 Portfolio 传入（已加载，不重复请求），决策日志自己拉。与既有的「组合点评」并列 —— **组合点评看「当下快照」，交易复盘看「一段过程」**。
  - `components/strategies/StrategyCodeReview.tsx`：接收编辑器里的代码，`runKey` 用「长度 + 前 64 字符」做指纹。
  - `CodeStrategyEditor.tsx` 的「沙箱规则」卡补一条：**沙箱不检查时间语义**，未来函数请用「AI 审查代码」排查。

  **守卫同步（三处）**
  - `render-check.mjs`：`AI_TASKS` 13 → 16，新增 6 条 `AI_POINTS`。**89/89 通过**。
  - `tests/run_checks.py`：**新增 `ai` 子集（17 条，全离线、force_local）** —— 此前 AI 任务中枢**完全没有测试覆盖**。覆盖任务注册、未知任务抛 ValueError、提案复核的三类检查（含缺 weight 反推）、复盘点名高频被拒原因、代码审查拦下 `shift(-1)` 且不误报干净代码、`_extract_json` 三种解析路径。
  - `AI_GUIDE.md`：任务表 13 → 16，补 3 行；设计约定 #4 的任务清单与 #5 的模块清单同步（新增 `ai_tasks_strategy.py`），并写明「新增任务要同步三处守卫」。

  **验收**：后端 `ai` 17/17、`strategies` 52/52、`rankings` 30/30、`screener` 42/42、`correctness` 27/27、`twelvedata` 24/24；前端 `typecheck` 通过、`lint:hooks` 通过、`test:render` 89/89、`build` 成功。

- 2026-09-27 ⅩⅤ：**榜单页补两个 AI 功能 + 修正推理模型 token 预算（重大）**。用户诉求：榜单页除了「整池点评」，还要能**一键分析单只/多只股票**，以及**智能选股**。

  **先拆后加（铁律 9）**：`pages/Rankings.tsx` 已 587 行、`rankings.py` 596 行，都贴着 600 软上限。先把公司档案弹窗（约 50 行）抽成 `components/rankings/CompanyProfileModal.tsx`，页面降到 537，才有空间加新功能（加完 570）。

  **后端（新 1 文件 + 框架增强）**
  - `app/ai_tasks_screen.py`：`stock_batch_review`（选中 1 只 = 深度分析，多只 = 横向对比；≤12 只）+ `smart_screen`（自然语言 → 结构化筛选条件 JSON）。两者都有规则化兜底。
  - `app/ai_tasks.py`：`Task` 加 **`parse` 钩子** + `_extract_json()`（剥 ```json 围栏 / 取首尾花括号），`run_task` 把 text 解析成 `out["data"]` —— 让「需要被前端消费」的任务能返回结构化结果，**不改 API 层**。
  - `ai_analyst._llm_call` 加**向后兼容**的 `timeout` 参数（默认仍 90s），AI 中枢传 180s。

  **前端（新 3 文件 + 1 拆分）**
  - `components/rankings/SelectionToolbar.tsx`：`useRowSelection()`（rows 变化自动剔除失效代码）+ 工具条。勾 1 只 = 「AI 深度分析」，多只 = 「AI 对比分析（N 只）」，弹窗展示；含批量加入关注（复用页面既有 `toggleWatch`，不另写一套状态更新）。
  - `components/rankings/SmartScreen.tsx`：一句话描述 → chips 条件（可逐个删除）→ 一键应用回筛选面板。**字段白名单 + 数值范围钳制 + 非法字段显式提示**，绝不让模型输出的野字段静默生效。
  - `components/rankings/RankingsTable.tsx`：加复选框列（表头全选 + 选中行高亮）。

  **⚠️ 重大修正：推理模型 token 预算（2200 → 6144）**
  实测 `cn:glm-5.3-flash` 是推理模型，**每次先烧掉 1800~3200 token 思维链**，正文还要 ~1000-1500：

  | max_tokens | finish_reason | content | 思维链 |
  |---|---|---|---|
  | 2200（旧下限） | length | **0 字** | 2199 |
  | 3072 | length | **0 字** | 3042 |
  | 4096 | length | 1475 字（截断） | 3153 |
  | **6144** | **stop** | **1878 字（完整）** | 2415 |
  | 8192 | **网关 502 挂掉** | 0 字 | — |

  结论：下限必须 ≥6144、上限**不能**超 6144（8192 会让网关自己挂）。同时 `_LLM_TIMEOUT=180s`（原 90s 卡在边界 → ReadTimeout 静默降级），前端 `ASSIST_TIMEOUT` 150s→240s。这解释了此前 `risk_review`「长提示词返回空」的**真正原因**（不是提示词问题，是预算被思维链吃光）。
  另给 `stock_batch_review` 加篇幅约束（400/600 字），减少长生成触发网关 502。

  **诚实性设计（本地兜底也不能骗人）**：`smart_screen` 的关键词规则**只映射价格动量**，「营收增速/分析师评级/ESG/PEG」等平台没有的字段**不拿别的指标顶替**，而是显式说明「平台暂无对应字段」。实测「营收增速 30% 以上的成长股」→ 不产出任何误导性条件 + 明确提示。

  **回归**：后端 `rankings` 30/30、`strategies` 44/44；前端 `tsc` + `lint:hooks` 干净、`test:render` **83/83**（新增 4 项：榜单页两个新接入点 + 扫 `aiAssist('…')`）、`vite build` 通过。**真实 LLM 路径实测**：`smart_screen` 38s 返回合法 JSON（正确用 `rsiMax` 表达「不超买」）；`stock_batch_review` 92.5s `engine=llm`，输出区分「数据事实/概率判断」并主动声明「ROE 118% 成因数据未覆盖」。

- 2026-09-27 ⅩⅣ：**AI 能力全平台接入（AI Task Hub）**。用户诉求：把项目里所有适合 AI 的功能点逐一接上，并复用 `/settings` 已配好的全局 AI 网关。做法是**先建统一入口，再逐点接入**，而不是每个功能点各写一套接口：

  **后端（新，4 个文件）**
  - `app/ai_tasks.py`（234 行，框架层）：`Task` 模型 + 注册表 + `run_task()`。调用链完全复用 `ai_analyst._llm_call`，因此「设置 → AI 分析」的网关/密钥/全局模型/`QD_AI_EXTRA_MODELS` 全部自动生效。
  - `app/ai_tasks_market.py`（294）/ `ai_tasks_analysis.py`（292）/ `ai_tasks_ops.py`（265）：按领域登记 11 个任务。**先写 1024 行单文件，超硬上限（900）当场拆**（铁律 9）。ⅩⅤ 轮新增 `ai_tasks_screen.py`（选股类：`stock_batch_review` + `smart_screen`），任务总数 13。
  - `api/ai.py`：新增 `GET /ai/tasks` + `POST /ai/assist`（统一入口）。同步 DB 写入一律 `run_in_threadpool`（SQLite 写锁不得冻结事件循环）；分析/诊断类任务落 `decision_logs`（action=`ASSIST`），纯展示类只写审计日志避免刷屏。`schemas.py` 加 `AiAssistRequest`。

  **11 个接入点**：个股快评（行情页）、新闻要点（新闻面板）、候选池点评（榜单页）、盘面简报（首页）、回测诊断（回测页）、寻优解读（优化页）、策略草稿（策略实验室）、风控体检（风控中心）、组合点评（持仓页）、订单诊断（实盘页 + AIOps）、情报解读（公司情报）。（ⅩⅤ 轮在榜单页再补 2 个：个股对比分析、智能选股，共 13。）

  **前端（新，4 个文件）**
  - `lib/ai.ts`：`aiAssist()` / `listAiTasks()` / `getAiStatus()`（进程内缓存 + 请求合并，避免一页十几个卡片打十几次 `/ai/status`；设置页保存后 `invalidateAiStatus()`）。
  - `components/AIAssist.tsx`（362 行）：**唯一**的 AI 卡片实现（panel/inline/modal 三形态），统一加载/失败/重试/复制/引擎标识，自带轻量 Markdown 渲染（`##`/列表/`**强调**`），常驻「不构成买卖信号」免责行。
  - `components/OrderAiDiagnose.tsx`（88）/ `StrategyAiDraft.tsx`（96）：自包含组件，用于把取数+交互全部封装，页面只留一行编排 —— 因为 `LiveTrading.tsx`（1170）与 `Intel.tsx`（1269）已在冻结清单里。

  **三个静默失效坑（都已在实现中规避）**
  1. **推理型模型 token 预算**：实测同一网关 `max_tokens=200` 返回**空 content**（HTTP 200），1300 正常 —— 预算被思维链吃掉了。已加 `_MIN_TOKEN_BUDGET` 下限 + 「空返回且响应较快时补试」。⚠️ **ⅩⅤ 轮修正**：下限 2200 定错了，实测思维链固定烧 1800~3200 token，已改为 **6144**（详见 ⅩⅤ 条目）。同时**不允许**把 `engine` 标成 `llm` 却展示本地兜底文案（那是误导），改为返回明确的 `llm_error`。
  2. **`payload` 闭包过期**：`run()` 用 `useCallback` 依赖 `task/runKey`，会把首次渲染的 `payload` 闭包住；若进依赖数组又会因对象字面量无限重跑。改用 `payloadRef` 承接最新值。
  3. **任务名拼错**：前端照常渲染、点击后后端 400，极易被当成「AI 坏了」。已把任务名写进 `test:render` 的静态扫描断言（ⅩⅤ 轮扩到 13 个，并新增扫 `aiAssist('…')` 直调形式）。

  **回归**：后端 `run_checks.py rankings` 22/22、`strategies` 全绿；`/ai/tasks`、未知任务 400、数据不足 400、`force_local` 兜底、**真实 LLM 路径**（`market_briefing` / `order_diagnose` 实测 `engine=llm`，输出正确区分「数据事实/概率判断」并主动声明「数据未覆盖」）逐项实测；前端 `tsc` + `lint:hooks` + `test:render` **79/79**（新增 21 项：AIAssist 白屏守卫 + 15 个接入点存在性 + 任务名白名单）+ `vite build` 通过。文档：`AI_GUIDE.md` 新增「AI 任务中枢」一节（含任务表与 5 条设计约定）。

- 2026-09-26 ⅩⅢ：**连接池耗尽事故修复**（服务日志复盘：QueuePool 5+10 全占满 → 全站 500）。根因组合：① intel 调度 tick 每轮 `analysis_due_symbols` N+1 查询（33 家×2）且 naive/aware datetime TypeError（又双叒）→ 异常打掉 tick；② alerts/scan 单请求 102s 长占连接；③ 前端 WS/轮询并发叠加 → 15 连接耗尽。修复：analysis_due_symbols 统一补 tz（naive/aware 第 3 处，**SQLite + datetime 是系统性隐患，应全局排查**）；engine 池扩容 20+30/timeout 60/pre_ping。实测并发 15 请求 15/15 成功 + smoke 46/46。遗留：alerts/scan 102s 待专项（yfinance 限流×全部标的串行）。

- 2026-09-26 ⅫⅡ：**自动新闻抓取执行器 `tools/auto_fetch.py`**（不依赖 AI 联网——脚本直接拉东财新闻搜索，中文关键词+别名相关性过滤，事件自动分类入库）。修复两个网络/匹配 bug：urllib 不走系统代理改 httpx（东财需代理）；--once 路径别名缺失（NVDA≠NVIDIA）→ search_kws/match_kws 分离 + enrich 补全别名。节流：脚本内 14 分钟（runtime/autofetch_last.txt）。调度：WorkBuddy automation 每 5 分钟触发跑脚本（schtasks 被安全策略黑名单阻止，用 automation 替代）。实测 NVDA 5 条真实新闻入库、时间线 112 条（管道 2/1/1）+ WorkBuddy WebSearch 深度抓取的英文新闻并存——双执行体工作正常。

- 2026-09-26 Ⅻ：**抓取频率做成设置项**。架构：WorkBuddy automation 触发器固定**每 5 分钟**（BYMINUTE 全刻度），节流由平台「抓取周期」设置控制——poll 只返回到期公司，未到期秒退无害。平台周期选项本就有 5/10/15/30/60/120 分钟（监控总控下拉）。旧 15 分钟版 automation 已删，新触发器 d745d611 上线；监控 Run #40 已重启（interval=15）。**用户改频率只需在 Intel 页下拉选**，无需再动 automation。

- 2026-09-26 Ⅻ：**当日实时抓取模式上线**。① WorkBuddy automation `9c237a21`（FREQ=HOURLY;BYMINUTE=0,15,30,45 = 每 15 分钟一轮，MINUTELY 不受支持用 BYMINUTE 等效实现）：自动 poll 领任务→WebSearch 检索当天新闻→提交事件（含 stage）→建议→done；② 平台监控开启 Run #40（interval=15，auto_analyze 开）；观察列表 33 启用/34 总。用户操作闭环：Intel 页开关选股票→监控开启→自动化每 15 分钟自动跑。

- 2026-09-26 Ⅻ：**Agent 名解析式改造 + 提示词重写**。① `_norm_agent` 弃白名单（旧 `^[A-Za-z0-9_-]{1,32}$` 整体拒绝→unknown，用户自定义名如 workbuddy-ai/WorkBuddy AI 被吞）→ **解析式**：非法字符替换 '-'、空格/点归一连字符、截 48 对齐 DB 列——任意名字完整保留；实测 WorkBuddy AI v2 → WorkBuddy-AI-v2 ✓。② 三套 Bridge 提示词重写：结构化（执行步骤/事件字段/质量红线）、**补 stage 分类指引**（confirmed/negotiating/rumor——之前 agent 不知道要标管道阶段）、occurred_on 必填强调、agent 名自报说明。typecheck + 服务重启验证。

- 2026-09-26 Ⅺ：**关注列表 ↔ Intel 观察标的同步**。① 榜单工具栏新增「⭐ 只看已关注（n）」筛选开关（星标功能本就在行首，提升可见性）；② 新端点 `POST /intel/companies/sync-watchlist`（watchlist 全量→IntelCompany，已有跳过/新增启用）；③ Intel 观察标的卡加「⇄ 同步关注」按钮（act+loadOverview）。实测：收藏 TSM→同步 skipped=25（此前已同步过，34 家）/TSM 在列表 ✓；取消收藏不删 Intel 记录（保护情报数据）。typecheck/build + smoke 46/46。

- 2026-09-26 Ⅶ：Intel 页删除两处免责提示条（右栏底部 + 页面底部，单机自用无对外披露），腾出的空间并入内容区（根容器 118px→88px），三栏高度再增 30px。typecheck + build + smoke 46/46。

- 2026-09-26 Ⅵ：事件悬停浮窗改纯白不透明（bg-white + border-slate-300 + shadow-xl + z-30）——点密集时浮窗完全遮住底层曲线，信息清晰可读。build + smoke 46/46。

- 2026-09-26 Ⅹ：**内容区高度真修**。上轮 Modal 虽扩了 props 但 body 默认类里 max-h-[70vh] 仍叠加在 bodyClass 之外继续截断——改为 `bodyClass || 'max-h-[70vh] overflow-y-auto'`（传入即完全接管）；Optimize 唯一依赖默认滚动 的 p-0 使用点补回滚动类。实测卡片 94vh 时内容区占满 header 以下全部空间。typecheck/build + smoke 46/46。**教训：clsx 追加类无法覆盖冲突类，必须条件替换**。

- 2026-09-26 Ⅸ：放大弹窗高度根治。**根因**：ui.tsx Modal body 硬编码 `max-h-[70vh]`——无论外层设多大都被截断。Modal 组件扩展 `className`（弹窗卡片）与 `bodyClass`（内容区）props；时间线弹窗 `h-[94vh] flex flex-col` + body 占满剩余高度（覆盖 70vh 上限），价格图 big 模式 h-52。typecheck/lint/build + smoke 46/46。**教训：通用组件的硬编码尺寸限制要先查再绕**。

- 2026-09-26 Ⅷ：放大弹窗修正。① 弹窗宽度 max-w-6xl → **!max-w-[96vw]**（近全屏），内容区高 74vh→86vh；② **双图根因**：弹窗外层显式渲染了一个 PriceOverlay，而 TimelineView 内部又渲染一个——去掉外层的，只留时间线内置图；③ PriceOverlay/TimelineView 加 `big` prop：放大模式下价格图 h-28→h-52（高度翻倍，事件钉点更大更清晰）。typecheck/lint/build + smoke 46/46。

- 2026-09-26 ⅥⅡ：Agent 接入卡上移至右栏第一位（用户找不到按钮——之前排在 AI 建议卡下方需滚动）。修复重组脚本留下的重复 col-span-3 开 div。右栏最终顺序：**Agent 接入（四按钮：三个快捷复制+多选弹窗）→ AI 买入建议 → 建议验证 → 📂历史批次**。typecheck/lint/build + smoke 46/46。

- 2026-09-26 Ⅵ：Agent 提示词交互升级。右栏卡精简为三个快捷复制按钮（WorkBuddy/Claude Code/Codex 各一）+「多选/预览提示词」按钮；新增弹窗：Agent 多选 chips（全选/清空）、逐套预览（各带单独复制）、footer 一键复制所选 N 套（分隔线拼接）。typecheck/lint/build + smoke 46/46。

- 2026-09-26 Ⅴ：Intel 页交互升级。① **添加观察标的改弹窗表单**（代码/名称/主题/关注要点四字段——focus 指导 AI Agent 抓取方向），右上角输入框移除省宽度；② 栅格 2/7/3（中栏时间线加宽）；③ 时间线「⤢ 放大」按钮 → max-w-6xl 大弹窗（PriceOverlay+TimelineView 完整视图）；④ **观察标的超高根治**：上轮重组丢失 `flex flex-col`（section 非 flex → body 的 flex-1/overflow 全部失效）——补齐后真正滚动。typecheck/lint/build + smoke 46/46。

- 2026-09-26 Ⅳ：Intel 页四项修复。① **Agent 接入提示词恢复显式 Card**（上轮误折叠——用户以为被删）；② 观察标的列表加 bodyClass 滚动（>10 个不再超高）；③ PriceOverlay 区间扩为 **1 周/1 个月/3M/6M/1Y** 且生效（后端 /intel/history 同款区间裁剪缺失 + 最小区间 30→7 天，实测 7=5 根/30=21 根/365=251 根）；④ **事件点悬停浮窗**：hover 显示日期/利多利空/收盘/标题/摘要/来源（SVG 原生 title 换 React 浮窗）。typecheck/build/smoke 46/46。教训：字符串替换换 svg 开标签会顶掉原标签——DOM 改造后必须 tsc 验证配对。

- 2026-09-26 Ⅲ：Intel 情报中心改版为**固定视口三栏仪表盘**（用户痛点：无限下拉看不到全貌+走势图区间不可选）。布局：顶部监控总控单行条 + 左栏观察标的（滚动）/ 中栏选中公司价格曲线（**3M/6M/1Y 区间切换**，事件钉点叠加）+事件时间线 / 右栏 AI 建议+验证统计+Agent 接入指南与历史批次（折叠）。PriceOverlay 区间参数化。typecheck/lint/build + smoke 46/46。教训：1042 行大文件重排用「正则提取逻辑块→重组」仍会留孤儿标签，需逐段验证配对。

- 2026-09-26 Ⅱ：观察标的扩容。澄清：Intel 观察列表**没有 10 个上限**（10 是 DEFAULT_COMPANIES 默认预置数）；按用户要求默认列表扩至 **20 家美股核心公司**（+ORCL/CRM/JPM/V/WMT/COST/UNH/LLY/XOM/ASML），重启后 ensure_default_companies 自动补齐（实测 19 启用/20 总）；前端添加框文案改"数量不限"。build 通过、服务已重启。

- 2026-09-26：**公司情报面板（经营前瞻）**。用户核心诉求：选中股票→看过去半年发生了什么+签约管道（已敲定/在谈/传闻）前瞻 3-6 个月经营（财报滞后）。实现：① IntelEvent 加 `stage` 字段（confirmed/negotiating/rumor，含迁移）；② `intel.timeline()` 聚合（事件+管道计数+经营可见性评分=已敲定×2+在谈−负面×2+最新建议+行情）+ `GET /intel/timeline/{symbol}`；③ 行情分析页新增「公司情报」视图（Tabs 切换图表/情报——CompanyIntel 组件：汇总卡+AI 建议卡+垂直时间轴，stage 徽章 ✅🔄❓，sentiment 色条，来源可溯源）；④ WorkBuddy 实测提交 NVDA 三态事件 4 条 → 管道 confirmed=2/negotiating=1/rumor=1；⑤ 修 3 个 bug：recommendation 大小写归一化、published_at/occurred_on 字段兼容、timeline 引用不存在的 target_price 列。typecheck+build+smoke 46/46。

- 2026-09-24 深夜Ⅱ：**AICopilot 关注列表 chips + Intel Bridge 全流程实测打通**。① AI 研判页新增关注列表快捷选择（点击加入/移出研判，持仓绿点标识，最多 12 个）；② **WorkBuddy 作为外部 Agent 走通 Bridge 全流程**：token → 开轮 → poll 领任务（9 家）→ WebSearch 检索 NVIDIA 当天真实新闻 → 提交 4 条事件（全带来源 URL）→ BUY 建议（71% 置信/目标价 $260）→ done；③ 修复 recommendation 归一化（大写 BUY/STRONG-BUY 落库为 hold 的 bug）；④ 新增 `tools/intel_bridge.py` 客户端（Claude Code/Codex 直接可用）+ `INTEL_BRIDGE_GUIDE.md` 接入指南（含提示词模板）。typecheck + build + smoke 46/46。

- 2026-09-24 **长尾清零批**（评估报告剩余项全部落地，自检 204→**208**）：① **P1-14 长任务进度/取消**：新增 `engine/jobs.py` 后台任务注册表（独立线程 + 进度回调 + 协作式取消 + 30 分钟结果保留），`grid_optimize` 接入 `progress_cb/cancel_event`（取消保留已评估结果），新端点 `POST /backtest/optimize-async` + `GET /backtest/job/{id}` + `POST /backtest/job/{id}/cancel`；Backtest 页寻优弹窗改异步轮询 + 进度条 + 取消按钮（实测：48 组 3 秒后 12/48 → 取消 → cancelled 保留 15 组）；② **T-115** 下单按钮强制预检（护栏拒绝直接终止），确认弹窗渲染预检结果（护栏判定/缩减后数量/佣金/占权益/警告）；③ **T-116** Market 搜索建议键盘导航（↓↑ 高亮、Enter 选中、Esc 关闭、role=listbox）；④ **T-112** Portfolio 持仓市值非 USD 标注原币 + 折算值（title 悬浮），占比条 max 改由风控配置驱动；⑤ **无障碍**：Field 自动 htmlFor（useId + cloneElement）、Modal role=dialog/aria-modal/autofocus、Toast aria-live=polite + 关闭按钮 aria-label、Toast 宽度适配窄屏（calc(100vw-32px)）；⑥ **配色全量化**：CandleChart 悬浮/涨跌幅（5 处）、IntradayChart（4 处）、ui.tsx Stat/ScoreBar（3 处）全部改 upClass/downClass 跟随配色模式；⑦ **CandleChart 性能/触屏**：hover 双 state 合并为单对象（mousemove 1 次渲染）、touchAction none→pan-y（移动端可滚动页面）；⑧ **AlertsBell** 弹层宽度适配 375px 窄屏；⑨ **Toast/AIOps 定时器**清理与防互相清掉。回归：**208/208** + tsc/build + smoke **46/46**。**有效前沿视图核实为已实现**（Optimize 页 frontier Tab：散点图 + 当前解标记 + λ 表格），评估报告该项过时。未做且明确说明：期权模块（T-133，新模块需单独设计）、付费数据源（T-122，需 API Key）。

- 2026-09-24 深夜：**全站巡检 + AI 交易链路打通**。① 20 项核心 API 巡检 19/20 PASS（唯一 FAIL 是巡检脚本路径笔误，实际 /risk/exposure 正常）；② **补齐 AI 参与交易的关键断点**：AICopilot 研判结果卡新增「转为买入/卖出提案」按钮（bias→action、建议仓位→size_pct、维度分→factors，一键送审）；AIOps 空状态误导文案改准；③ **paper 全链路实测成功**：AI 研判 SPY（多头 21.7 分/6.2% 仓位/实时融合）→ 提案 #54 → 批准 executed → SPY BUY FILLED 8 股入持仓；④ 修复并行改动引入的 2 个 typecheck 错误 + Risk.tsx 既有 hooks 违规（useState 在 early return 后）。typecheck/lint/build + smoke 46/46。

- 2026-09-24 晚：**全市场搜索**。用户搜 SPCX 搜不到——本地 UNIVERSE 是精选集（S&P 500+常用 ETF），不是全市场。接入 **Yahoo search API 兜底**（`_yahoo_search`，10 分钟 TTL 缓存 + 失败静默降级本地；kind 映射 EQUITY/ETF/INDEX/CRYPTO…）：本地命中排前、Yahoo 补充去重，q≥2 字符才联网。实测：搜 spcx → SPCX SpaceX (NASDAQ) + 杠杆 ETF 族；**新标的行情开箱即用**（SPCX 71 根日线、快照 $148.36，yfinance 直连无需注册）。搜索首次 5.6s（Yahoo 网络）后缓存 0.04s。smoke 46/46。

- 2026-09-24 **IBKR 适配层竞态修复**（服务日志实证驱动）：服务两次静默退出暴露 `_ensure_loop` 无锁竞态——并发首调双线程 run_forever 同一循环（"This event loop is already running"，ibkr-loop 线程崩溃）+ 熔断拒绝路径 connectAsync 协程未 await 泄漏。修复：`_ensure_loop` 加锁 + runner 绑定局部 loop + 线程异常自愈；`_submit` gate 拒绝时显式 close 协程；`get_ibkr` 单例加锁。自检 +2 → **204 项**；12 路并发压测 0 竞态痕迹。**服务改用独立隐藏进程托管**（脱离工具会话，日志 runtime/service.out|err.log），run_in_background 方式在高并发时段会被连带终止，弃用。

- 2026-09-24 晚间：运行日志复盘三修。① **get_profile 函数丢失**（重写 company.py 时被 Write 覆盖删除）→ /market/rankings/profile 500，已恢复（含 naive/aware datetime 修复）；**教训：整文件覆写必须先核对全部既有导出**。② **IBKR 连接风暴**：TWS 关闭后每条报价路径都打 2s 超时连接（watchlist 8s、alerts/scan 88s）→ 连接失败 30s 冷却（_connect_fail_until，类级共享）。③ global 声明位置修正。终验：自检 202/202、smoke 46/46、profile 端点恢复。后台服务实例随 AI 会话超时回收属环境限制（用户可用 start.bat 手动启动最稳）。

- 2026-09-24 **评估报告第二批**（P2 逐项 + 安全矛盾修复，自检 195→**202**）：① P1-10 补齐 11 个无鉴权 GET 路由（market 7 个 + strategies/dsl + backtest/meta + optimize/meta；auth-status/health/bridge 豁免）；② `/ops/kill-switch` 解除熔断改需账户口令（与 /risk/kill-switch 同规则），AIOps 前端同步口令 prompt + 失败可见；③ AI 提案**自批准拦截**（created_by == reviewer 拒绝）；④ JWT 撤销：改密写入 min_iat 阈值，旧令牌立即失效；⑤ 登录限速键改仅按 IP（轮换用户名不可绕过）+ `_attempts` 有界化；⑥ market.py `_dt` NameError（港股 is_today 误判）与 overview 双检锁失效修复；⑦ lots.py 碎股卖出接线（此前港股碎股被取整成 0 永远卖不掉）；⑧ stops.py 波动率止损 abs(log) 反向放宽改有符号 √ratio；⑨ backtest.py 停牌 NaN 沿用最近有效价（不再权益断崖毁 max_drawdown）；⑩ CSV 公式注入防护；⑪ 500 响应带 request-id；⑫ rankings 快照缺失不再 500；⑬ Risk.tsx 清空保存 0 守卫（bad 字段阻止保存）；⑭ Dashboard/Portfolio 账户失败红条 + LiveTrading 撤单失败 toast；⑮ CandleChart useWidth callback ref（空数据后图表永久失效修复）；⑯ Rankings 无匹配提示 + 价格 toFixed(2)。回归：202/202 + tsc/build + smoke 46/46；实测 universe 未登录 401、解除熔断无口令 400。**仍未做（长尾）**：移动端（T-119）、长任务进度/取消、T-116 键盘导航、T-115 预检 UI、有效前沿视图、配色全量化、无障碍、图表触屏/降采样、币种折算 UI、T-133 期权、T-122 付费源。

- 2026-09-24 **评估报告 P0/P1 修复批**（依据 `EVALUATION_2026-09-24.md`，全部 P0 + 核心 P1 已落地，自检 174→**195** 项新增"数值正确性"一节）：① **P0-1** 回测/live 引擎 weight 模式加两级组合约束（`sizing.cap_targets`：单标的 clip + gross 等比缩放）+ 买单现金下限（不允许穿负加杠杆），实测 6 标的敞口 6.1x→**1.0x**；② **P0-2** 单飞改 Future 实现（跟随者只 `fut.result(timeout=60)` 绝不加锁），5 路并发实测只联网 1 次且无死锁；③ **P0-3** `stop_type=none/time_stop` 不再携带隐藏价格止损（25%/3%），none 语义与文案对齐；④ **P0-4** bcrypt 72 字节显式截断（hash/verify 同口径），超长口令不再 500/静默登录失败；⑤ **P0-5** `state.build_guard_context()` 中心化构造护栏上下文，orders_today/orders_last_minute/market_exposure 三计数器接入全部 4 处构造点（港股敞口上限、日内笔数、每分钟笔数三条风控从"恒不成立"变为生效）；⑥ **P0-6** 熔断（日亏/回撤）放行减仓单，`is_reducing` 前置判定；⑦ **P1-1** 增量合并去掉二次归一化（缓存 NY-naive 不再每次漂移 4h），`_normalize(naive_tz=)` 幂等语义 + stooq 日期不再被平移成前一天 + **顺手修复 `_from_yf` 不存在（NameError 被吞）导致增量分支从未执行过的问题**；⑧ **P1-2** IBKR history naive/aware 比较 TypeError 修复（比较基准 localize 到 bar 时区），IBKR 失败原因写入 `_last_errors` 可见；⑨ **P1-3** 新闻：reqHistoricalNews→Async 变体，reqNewsBullets（不存在的方法）改读 newsBulletins 缓存；⑩ **P1-4** 优化器 BB 步长符号修复（上升方向 sᵀy<0），实测达到固定步长参照解；⑪ **P1-5** 敞口按持仓币种 fx 折算（HKD 不再虚增 7.8x）；⑫ **P1-6** live tick 内下单成功后回写 ctx 敞口/计数器（10×20% 全放行→200% 的问题）；⑬ **P1-7** 止损离场 30s 冷却防重复市价单；⑭ **P1-8** `metrics.periods_per_year()` 按 bar 周期年化（1h 此前被低估 √7）；⑮ **P1-9** `state.effective_mode()`（UI 开关 ∧ 端口）统一 mode 数据源：paper 状态下强制模拟券商路由（端口 7496 时界面显示模拟盘不再真实下单），/trading/mode 与 /ops/overview 同源；⑯ **P1-11/12/13** 前端全局 ErrorBoundary + Market 页 seq 竞态守卫 + LiveTrading 账户失败红条 + sparks 不可变更新。验证：`run_checks.py` **195/195**、`tsc --noEmit` 零错、`vite build` 通过、`smoke` **46/46**、服务已重启加载新代码（/trading/mode 已返回 ui_mode）。遗留（评估报告第三批）：移动端适配、长任务进度/取消、无障碍、配色统一、JWT 撤销/限流、ErrorBoundary 页面级细分。

- 2026-09-24 数据点数值标注：**折线图（PriceChart）**点数 ≤64 时黑点+数值标签（抽稀 ≤32 个、上下交错防重叠，最高/最低保持彩色大点）；**K 线图（CandleChart）**可视区间 ≤40 根时逐根标收盘价（黑色小字、交错防重叠，高低点彩色标注保持）。typecheck/lint/build + smoke 46/46。

- 2026-09-24 快速周期区间 bug 修复 + 折线图增强：**根因**是 `/market/history` 从不按请求区间裁剪——分钟/小时线走 yfinance period 模式（1h=180d）返回远超 start 的数据，「选 1 周显示 180 天」；API 响应层统一按 start/end 严格裁剪（仅响应层，AI 指标仍用全量）。折线图（PriceChart，快速周期主用图）从裸 recharts 增强：**▲最高/▼最低点标注（含日期）+ 区间涨跌幅 + 悬停详情卡**（日期/收盘/较前日涨跌/均线值）。实测 1周=42 根 1h（首根=8天前）、3月=64 根 1d。smoke v2 升至 46/46。

- 2026-09-24 搜索/切标的提速 + smoke v2 + intel 修复：① `/market/search` 中文名改**只读缓存**（names_cn_cached，绝不联网）——曾因每键实时拉腾讯导致搜索 1.5~2.5s/键且频繁超时；② 搜索支持**中文关键词**（命中 CompanyProfile.name_cn，如 搜「腾讯」→0700.HK）；③ 预热扩展到关注列表标的日线（切关注标的 0.04s）；④ Market 页标的级内存缓存（切回看过的标的瞬时上屏，LRU 30）；⑤ smoke v2：构建产物完整性 + bundle 内容 + API 健康/鉴权混合断言 42 项（旧版 node DOM 渲染与代码分割不兼容）；⑥ vite 关闭 modulePreload polyfill（node file:// fetch 崩溃根因）；⑦ intel.pending_tasks naive/aware datetime 比较 TypeError 修复（历史缺陷）。自检 174/174 + smoke 42/42。

- 2026-09-24 榜单市值排序 + Dashboard 首屏拆分：① 腾讯批量行情第 45 段 = 总市值（亿美元），`company.enrich` 一次拉取中文名+市值并落库（CompanyProfile.market_cap）；② 榜单新增「总市值」排序与列——**排序前注入数据**（首次实现在 API 层后补导致排序失效，已移入 rankmod.rankings）；实测 Top10：NVDA 5.23T / AAPL 4.96T / MSFT 3.70T / GOOG 3.64T / AMZN 2.45T ✓；③ Dashboard 首屏从 Promise.allSettled（等最慢的 /market/overview 12 标的 IBKR 订阅 5~15s）拆为独立渲染，最快先上屏；④ smoke 固定 4s 等待改条件轮询（≤25s）。160/160 + smoke 36/36。

- 2026-09-24 实盘就绪体检 + 风控字段补全：全面体检发现用户实盘流程卡在（端口 7497→需 7496、IBKR 未连接、readonly=true、无策略配置）；`/risk/config` GET/PUT 补 allow_short/allow_extended_hours/hk_max_gross_exposure_pct/max_daily_orders/max_orders_per_minute 字段（schemas + _row_dict），风控中心 UI 可设。160/160 + 36/36。

- 2026-09-24 中文名 + watchlist 提速：① `get_quotes` 线程池并行化（关注列表接口从串行 10-30s → 并行后二次 0.07s/首次 ≈ 最慢单源）；② 腾讯 qt.gtimg.cn 批量中文名（`company.names_cn`，落库 CompanyProfile.name_cn 永久缓存），接入 watchlist/榜单/搜索建议；前端 QuickPicks/WatchBar chips 与榜单"名称"列显示中文名。坑：腾讯港股代码 5 位（hk00700）需转平台 4 位（0700.HK），`s[:5]` 切出带点代码是根因。自检 160/160（解锁用例环境自适应：第一道锁已开时期望 400）。

- 2026-09-24 分时图高 低点标注：图内 ▲最高/▼最低 圆点+标签（含时间，贴边自动收进），开盘价「开」标记；顶部信息条补最高/最低（含时间）。用户反馈驱动打磨。typecheck/lint/build + smoke 36/36。

- 2026-09-24 分时默认化 + 快速周期选择框：行情分析页图表类型默认「分时（24H/最近交易日，localStorage 记忆用户切换）」；图表卡新增快速周期 chips——分时(24H)/1周/1月/3月/半年/1年，点击自动适配区间与 K 线周期（1周→1h，其余→1d），与 Tabs 双向联动高亮。typecheck/lint/build + smoke 36/36。

- 2026-09-24 分时可用性三连修：① `/market/history` 1d 融合实时价为末根（K 线/折线模式能看到当日走势，缓存对象先 copy 再改防污染）；② 分时休市自动回退最近交易日（trade_date/is_today 字段 + 前端明示"最近交易日 X 的分时"）；③ 分时加载失败可见化（错误文案 + 30s 重试提示）。实测 SPY 回退 9-23、0700.HK 今日实时、日线末根实时价。

- 2026-09-24 实盘提案链路补强：第四道防线（实盘批准需账户口令，403 强拒）+ AIOps 实盘就绪条（live_ready/live_reason）+ AI_GUIDE 四步手册 + overview.live_unlocked。未替用户开启任何实盘开关（三重锁必须人工逐道解锁）。160/160 + 36/36。

- 2026-09-23 T-101 完成：AI 研判实时价融合（AAPL/0700.HK 实测），前端实时标记，LLM context 增「实时盘」块。
- 2026-09-23 T-141 完成：当日分时走势图（后端 1m 链 + 前端 IntradayChart + 分时 tab 30s 轮询）。
- 2026-09-23 T-106 核心 + T-102 完成：WebSocket 主题 hub（/api/ws，2s tick 秒级推送：IBKR 流式缓存 > 腾讯港股直连 > 免费源标注）+ 前端 realtime.ts 单例重连；Market 顶卡 LIVE 跳动 + 分时秒级延伸；AlertsBell 实时告警；alerts 日内急涨跌规则。Node ws 客户端实测推送正常。
- 2026-09-24 功能性 TODO 批量清账：T-103/104/105/106b/107/108/109/110/111/112/113/114/115核验/117/118/120/121/134/135/136/137/138/139 完成（详见各条）。亮点：ai_proposals 提案-批准-执行闭环端到端实测（批准→真实下单）；做空护栏 SHORT_FORBIDDEN；回测 fee_model/execution 双模式；QD_AI_EXTRA_MODELS 多模型；DataClock 全局链路时钟；启动 VACUUM INTO 备份；自检 147→160 全绿；smoke 36/36。剩余：T-116/119（体验）、T-122（付费 key）、T-133（期权大工程）、T-140（可选）及各条目的"后续迭代"小项。
