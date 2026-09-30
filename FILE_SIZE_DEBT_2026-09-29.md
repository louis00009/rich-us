# 文件规模债清单（铁律 9）

> **扫描时间**：2026-09-29
> **扫描工具**：`tests/size_check.py`（铁律 9 的可执行棘轮），入口 `tests/run_checks.py size`
> **本文档目的**：把「清单靠人记 = 规则不存在」变成一本**可执行、可追踪、可逐条勾掉**的账。
> 背景事故：`TODO.md` 的冻结清单写 `backend/app/intel.py` 1192 行，实际已涨到 **1916**；
> `Backtest.tsx` 写 1086，实际 **1641**。清单本身早就腐烂了 —— 所以现在由 `size_check.py` 机械地扫。

---

## 0. 一句话结论

| 项 | 值 |
|---|---|
| 扫描到的存量债 | **19 个** |
| 其中本轮新引入 | **0 个**（全部是 `HEAD 8eb1ccb` 之前就存在的历史存量） |
| 本文档写就时已还清 | **3 个**（Batch A） |
| 剩余 | **16 个** |
| 棘轮现状 | `run_checks.py size` → **3/3 通过**，无新增超限、无存量增长 |

判定依据：`git log` 显示这 19 个文件在本次工作开始前**均已超过各自软上限**，且行数与基线一致 —— 不是本轮改动造成的。

---

## 1. 背景：规则与判定语义

### 1.1 上限表（铁律 9）

| 类别 | 软上限（超了不许再加功能） | 硬上限（冻结，只允许修 bug） |
|---|---|---|
| 后端模块 `backend/app/**/*.py` | 600 | 900 |
| 前端页面 `frontend/src/pages/**/*.tsx` | 600 | 900 |
| 前端组件 `frontend/src/components/**/*.{ts,tsx}` | 400 | 600 |
| 前端工具 `frontend/src/lib/**/*.ts` | 400 | 600 |

### 1.2 棘轮（ratchet）判定

1. 超过软上限、且**不在基线里** → **FAIL**（新产生的债，一律不许）。
2. 在基线里但**比基线更长** → **FAIL**（存量债不许再长）。
3. 在基线里且未增长 → 通过，但在报告里**列出**（存量债，可见即可治理）。
4. 基线里的文件已降到软上限以内 → 提示**可从基线摘掉**（不算失败）。

- 基线文件：`tests/size_baseline.json`（`{"<相对仓库根的路径>": 行数}`）
- 重算基线：`python tools/gen_size_baseline.py`（**只在真正拆分完成后跑**，否则等于把债锁死；先 `--dry-run` 看差异）

### 1.3 为什么「一次只拆一个文件、每步跑回归」

铁律 9 的操作纪律。拆分是**结构性改动**，一次动多个文件会让失败归因变难（改错了不知道是哪一个）。因此本文档按批次（A–F）推进，每拆完一个文件跑一次 `npm run typecheck` / `run_checks.py`，绿了再动下一个。

---

## 2. 债务总表

按行数降序。**状态**：`已还` / `待还`。

| # | 文件 | 行数 | 超限 | 类别上限 | 批次 | 状态 |
|---|---|---|---|---|---|---|
| 1 | `backend/app/intel.py` | 1916 | **硬 900** | 后端 600/900 | F | ✅ 已还 → `intel/` 包 11 文件（`__init__.py` 121 + 最大域 analysis.py 507，09-30；回归 intel 118/118 + correct 56/56） |
| 2 | `backend/app/brokers/ibkr.py` | 1804 | **硬 900** | 后端 600/900 | F | ✅ 已还 → mixin 拆 5 文件（主文件 217，09-30） |
| 3 | `backend/app/data_provider.py` | 1311 | **硬 900** | 后端 600/900 | F | ✅ 已还 → `providers/` 包 7 数据源文件（主文件 870，仍存量债；api 107/107，09-30） |
| 4 | `frontend/src/pages/LiveTrading.tsx` | 1180 | **硬 900** | 页面 600/900 | C | ✅ 已还 → EngineTab + RightRail 组件（725，仍存量债；渲染 250/250） |
| 5 | `backend/app/engine/live.py` | 1151 | **硬 900** | 后端 600/900 | F | ✅ 已还 → 5 个 _Live*Mixin（组装类 146，09-30） |
| 6 | `backend/app/engine/stream.py` | 1062 | **硬 900** | 后端 600/900 | E | ✅ 已还 → stream_types.py（728，仍存量债） |
| 7 | `frontend/src/pages/Settings.tsx` | 854 | 软 600 | 页面 600/900 | C | ✅ 已还（476，软上限内，可摘除） |
| 8 | `backend/app/ai_analyst.py` | 775 | 软 600 | 后端 600/900 | D | ✅ 已还（338，可摘除） |
| 9 | `backend/app/rankings.py` | 732 | 软 600 | 后端 600/900 | D | ✅ 已还（495，可摘除） |
| 10 | `backend/app/engine/optimizer.py` | 725 | 软 600 | 后端 600/900 | E | ✅ 已还 → optimizer_math.py（509，可摘除） |
| 11 | `backend/app/movers.py` | 691 | 软 600 | 后端 600/900 | D | ✅ 已还（516，可摘除） |
| 12 | `backend/app/strategies/builtin_advanced.py` | 678 | 软 600 | 后端 600/900 | E | ✅ 已还 → `advanced/` 包 9 策略文件（barrel 34） |
| 13 | `frontend/src/components/CandleChart.tsx` | 677 | **硬 600** | 组件 400/600 | B | ✅ 已还（4，可摘除） |
| 14 | `frontend/src/pages/AICopilot.tsx` | 627 | 软 600 | 页面 600/900 | C | ✅ 已还（511，可摘除） |
| 15 | `frontend/src/pages/Risk.tsx` | 622 | 软 600 | 页面 600/900 | C | ✅ 已还 → risk/tabs.tsx（446，可摘除） |
| 16 | `frontend/src/components/rankings/MoversMonitor.tsx` | 483 | 软 400 | 组件 400/600 | B | ✅ 已还（293，可摘除） |
| — | `frontend/src/lib/rankingColumns.ts` | 408 | 软 400 | lib 400/600 | A | ✅ 已还 |
| — | `frontend/src/components/ui.tsx` | 709 | **硬 600** | 组件 400/600 | A | ✅ 已还 |
| — | `frontend/src/components/charts.tsx` | 710 | **硬 600** | 组件 400/600 | A | ✅ 已还 |

> **2026-09-30 收尾**：Batch B/C/D/E/F 全部 16 个文件 ✅ 还清。同期**并行会话**新增 3 个超限文件（不在本清单 19 个之内，属新产生的债，待其功能稳定后另行拆分）：
> `backend/app/intel_digest.py` 662（软 600）· `frontend/src/components/intel/MonitorBar.tsx` 502（软 400）· `frontend/src/components/intel/DailyDigest.tsx` 420（软 400）。
> 基线更新：12 个可摘除文件已从 `size_check` 基线移除；3 个新债**未**写入基线（保持棘轮可见）。
>
> **2026-09-30 二次收尾（01:00 前后）**：上述 3 个新债也已 ✅ 还清（size 3/3 全绿）——
> · `intel_digest.py` 662 → 517：评分纯函数区拆至 `intel_digest_scoring.py`（182，含 score_event 与权重常量，主文件 re-export 保持 `dig.score_event` 路径与打桩兼容）；intel 回归 122/122。
> · `MonitorBar.tsx` 502 → 400：拆出 `LiveStatus.tsx`（84，实时状态条）+ `IngestLog.tsx`（56，入库台账，展开状态自持）。
> · `DailyDigest.tsx` 420 → 364：`digest/HistoryModal.tsx`（78，记录留痕弹窗自含取数）——由并行会话拆出并接线，本会话验证 typecheck/render 通过并清理其 `histOpen` 重复声明残留。
> · 顺带修复：render-check.mjs 策略 key 扫描改为**递归** `strategies/` 目录（Batch E 拆 `advanced/` 包后顶层扫描读不到 9 个策略 key，曾误报 vol_managed_momentum 不存在）；render 250/250。
> 当前存量债仅剩 3 个（data_provider 870 / stream 728 / LiveTrading 725，在基线内不增长）。

### 批次划分逻辑

| 批次 | 内容 | 为什么这么分 |
|---|---|---|
| **A** | 前端纯数据 / barrel（3 个） | 无 JSX、无状态、纯导出聚合 —— 拆分零风险，先拿来验证「拆分→验证」流水线 |
| **B** | 前端小组件（2 个） | 有 JSX 但是「行组件 + 主组件」两层，缝很清晰 |
| **C** | 前端页面（4 个） | 页面是「薄编排层 + 若干卡片」，拆卡片即可 |
| **D** | 后端「同构重复」三兄弟（3 个） | `movers.py` / `rankings.py` 有一批**完全同名同义**的函数，先抽公共模块，一石二鸟 |
| **E** | 后端「数学/策略/流」三块（3 个） | 有明确的领域切面（数学核 vs 求解器、策略族、数据类 vs Hub） |
| **F** | 后端巨型类（4 个） | 必须用 **mixin 拆分**（一个巨型类的方法分散到多个 mixin 文件），最复杂，放最后 |

---

## 3. 已还清（Batch A，3 个）

三个都是**前端纯数据 / barrel 聚合**文件，采用同一种手法：**零改动 barrel 拆分**。

### 3.1 `lib/rankingColumns.ts` 408 → `lib/rankingColumns/`（5 文件，合计 455）

| 新文件 | 行数 | 内容 |
|---|---|---|
| `types.ts` | 24 | `MetricTipText`、`RankingColumn` 类型 |
| `base.ts` | 186 | `BASE_COLUMNS`（score/signals/symbol/price/change_pct/amount/market_cap/pe_ttm/pb/roe/div_yield/pct_from_high/sector） |
| `quote.ts` | 95 | `QUOTE_COLUMNS`（volume/eps_ttm/turnover/amplitude/w52_high/w52_low/market_cap_float） |
| `technical.ts` | 123 | `TECHNICAL_COLUMNS`（ma200_rel/ma20_rel/ma_bull/r1y/excess_1y/r3m/rsi14/vol_ann/beta） |
| `index.ts` | 27 | barrel：`RANKING_COLUMNS = [...BASE, ...QUOTE, ...TECHNICAL]`、`COLUMN_MAP`、`DEFAULT_VISIBLE` |

### 3.2 `components/ui.tsx` 709 → `components/ui/`（11 文件，合计 791）

按「控件族」切：`button.tsx`(62)、`card.tsx`(44)、`badge.tsx`(47)、`form.tsx`(110)、`tabs.tsx`(43)、`modal.tsx`(79)、`toast.tsx`(84)、`feedback.tsx`(101)、`data.tsx`(191)、`theme.tsx`(11)、`index.ts`(19)。全部 ≤191 行。

### 3.3 `components/charts.tsx` 710 → `components/charts/`（7 文件，合计 776）

| 新文件 | 行数 | 内容 |
|---|---|---|
| `shared.tsx` | 28 | `AXIS`、`GRID`、`TipBox`（原为文件私有，拆出后**必须 `export`**） |
| `equity.tsx` | 169 | `EquityChart`、`MultiEquityChart` |
| `price.tsx` | 210 | `PriceChart`、`MiniSpark` |
| `monthly.tsx` | 117 | `MonthlyHeatmap`、`MonthlyBars` |
| `score.tsx` | 79 | `ScoreGauge`、`HBar` |
| `portfolio.tsx` | 161 | `EfficientFrontierChart`、`CorrelationMatrix` |
| `index.ts` | 12 | barrel |

原文件在末尾统一 `export const X = memo(XImpl)`；拆分后**每个文件各自带自己的 memo 导出**，不要集中到一个文件。

### 3.4 ⚠️ 一个反直觉的结论：总行数**增加**了

| 文件 | 拆前 | 拆后合计 | 增量 |
|---|---|---|---|
| `rankingColumns` | 408 | 455 | **+47** |
| `ui` | 709 | 791 | **+82** |
| `charts` | 710 | 776 | **+66** |

**这是正常的，不是拆错了。** 增加来自 import 样板 + barrel 重导出。铁律 9 的目标是「**单文件不超上限**」，不是「总行数变少」。任何以「总行数」衡量拆分效果的判断都是错的。

### 3.5 验证记录（Batch A）

| 检查 | 结果 |
|---|---|
| `npm run typecheck` | ✅ 通过 |
| `npm run test:render` | ✅ **240/240** |
| `npm run build` | ✅ 通过（9.44s） |
| `run_checks.py size` | ✅ 存量债 **19 → 16** |
| 基线 | ✅ 已重算，3 个文件自动摘除，**无新增、无增长** |

同时同步更新了 `frontend/scripts/render-check.mjs` 里 3 处被移动的路径引用（`lib/rankingColumns.ts` → `lib/rankingColumns/index.ts` 等）。

---

## 4. 待还清单（16 个）

每项给出：**现状** → **内部结构** → **拆分缝** → **配方**。

### Batch B —— 前端小组件（2 个）

#### B-1. `frontend/src/components/rankings/MoversMonitor.tsx` 483 行（超软 400）

- **内部结构**：`export` 2 个 —— `MoverRow`（行组件）、`MoversMonitor`（主组件）。
- **拆分缝**：主组件与行组件之间没有共享可变状态，行组件是纯展示。
- **配方**：
  - `rankings/MoverRow.tsx` ← 行组件（含涨跌色、徽章）
  - `rankings/MoverFilters.tsx` ← 顶部过滤/排序/刷新工具栏
  - `rankings/MoversMonitor.tsx` 保留取数 + 编排
- **预期**：主组件降到 ~250 行。

#### B-2. `frontend/src/components/CandleChart.tsx` 677 行（**超硬 600**）

- **内部结构**：`export` 3 个 —— `CandleOverlay`、`CandleLevel`、`CandleChart`。
- **拆分缝**：`CandleOverlay`/`CandleLevel` 是**类型 + 常量**，与渲染无关；叠加层（均线/布林/成交量/标记）计算与绘制可分离。
- **配方**：
  - `components/candle/types.ts` ← `CandleOverlay`、`CandleLevel`
  - `components/candle/overlays.ts` ← 叠加层几何计算（MA/BB/量能/标记点）
  - `components/candle/CandleChart.tsx` ← 主组件
  - `components/candle/index.ts` ← barrel（保持 `../CandleChart` 引用不变）
- ⚠️ 注意：**目录嵌套后相对 import 要多一层 `../`**（见 §5.2）。

### Batch C —— 前端页面（4 个）

页面基本都是「薄编排层 + 若干卡片」，拆卡片是标准动作。

#### C-1. `frontend/src/pages/Risk.tsx` 622 行（超软 600）
- **缝**：各风险卡片 —— VaR/回撤、压力测试、相关性矩阵、止损监控、暴露分解。
- **配方**：`components/risk/` 下逐卡片拆（`VarCard.tsx`、`StressCard.tsx`、`CorrelationCard.tsx`、`StopsCard.tsx`），页面保留数据获取与 tab 编排。

#### C-2. `frontend/src/pages/AICopilot.tsx` 627 行（超软 600）
- **缝**：AI 提案列表 / 提案详情 / 人工确认对话框 / 运行日志。
- **配方**：`components/copilot/` 拆 `ProposalList.tsx`、`ProposalDetail.tsx`、`ConfirmDialog.tsx`。
- ⚠️ 铁律 10：AI 只有建议权，下单必须走 `ai_proposals` + **人工确认** —— 拆分时**不要把确认对话框和提交逻辑拆散**，确认语义要保持在一个文件里可读。

#### C-3. `frontend/src/pages/Settings.tsx` 854 行（超软 600）
- **缝**：按设置 tab 天然分块 —— 数据源、风控参数、AI/模型、通知、系统。
- **配方**：`components/settings/` 按 tab 拆 5 个面板，页面只留 tab 状态与保存。
- ⚠️ 铁律 11：**数据源清单、AI 任务清单一律从后端取**，不许在拆出来的面板里硬编码。

#### C-4. `frontend/src/pages/LiveTrading.tsx` 1180 行（**超硬 900**）
- **缝**：订单面板 / 持仓 / 成交 / 引擎控制（启停）/ 任务列表 / 风险横幅。
- **配方**：`components/live/` 拆 `OrderTicket.tsx`、`Positions.tsx`、`Fills.tsx`、`EngineControls.tsx`、`TaskList.tsx`，页面留实时轮询与布局。
- ⚠️ 实时数据 hook 必须在**所有 early return 之前**（React #300 白屏），拆子组件时 hook 要留在子组件自己内部，不要提到页面顶层再透传。

### Batch D —— 后端「同构重复」三兄弟（3 个）

**这三个要一起看**：`movers.py` 与 `rankings.py` 有一批**完全同名同义**的函数，属于复制粘贴出来的重复代码。

| 重复函数 | 说明 |
|---|---|
| `_load_disk` / `_save_disk` | 磁盘缓存读写 |
| `_parse_chunk` | 分块解析 |
| `_fetch_all_quotes` | 全量报价抓取 |
| `_accept_refresh` | **覆盖率闸门**（`fresh >= old * 0.8`，见 §R14） |
| `_bg_refresh` | 后台刷新线程 |
| `quote_cache_meta` | 缓存元信息 |

#### D-1 / D-2. 先抽公共模块 `backend/app/quote_cache.py`
- **配方**：把上表 6 个函数抽到 `quote_cache.py`，`movers.py` 与 `rankings.py` 各自 `from app.quote_cache import ...`。
- ⚠️⚠️ **`_accept_refresh` 是覆盖率闸门，搬家时一个字符都不能改**（铁律 12）：任何「抓全量→覆盖落盘」都必须有 `fresh >= old*0.8` 闸门，否则一次半残抓取会把好数据覆盖成垃圾。搬完要单独跑一次抓取回归。
- 预计这一步就能让两个文件各降 ~150 行。

#### D-2 续. `backend/app/rankings.py` 732 行（超软 600）
- 抽完公共模块后，再把「榜单计算」拆出：`_match_rank`、`_name_match`、`_sort_rows`、`_build_filter` → `rankings_calc.py`；`rankings.py` 留 `constituents` / `refresh_constituents` / `quotes` / `rankings` 编排。

#### D-3. `backend/app/movers.py` 691 行（超软 600）
- 抽完公共模块后，再把「监控循环」拆出：`_monitor_cfg`、`set_monitor_cfg`、`monitor_status`、`_monitor_loop`、`_ensure_thread`、`resume_monitor` → `movers_monitor.py`；`movers.py` 留 `movers` / `analyze` / `market_screen` / 日志。

#### D-4. `backend/app/ai_analyst.py` 775 行（超软 600）
- **内部结构**：20 个顶层函数，两条独立路径 —— 本地规则（`analyze_local` / `_build_readings` / `_match_strategies`）与 LLM（`analyze_with_llm` / `_llm_config_for` / `_llm_call` / `_news_context`），另有组合视角（`_portfolio_view` / `_correlation`）。
- **配方**：`ai_analyst_local.py`（本地规则）+ `ai_analyst_llm.py`（LLM 路径），`ai_analyst.py` 保留 `analyze` 门面与 `ai_configured` / `extra_ai_models`。
- ⚠️ 拆 LLM 路径时注意**推理型模型 token 预算**（`_MIN=_MAX=6144`）与网关降级兜底逻辑，这些常量不能跟着文件乱放。

### Batch E —— 后端「数学 / 策略 / 流」（3 个）

#### E-1. `backend/app/engine/optimizer.py` 725 行（超软 600）
- **内部结构**：26 个顶层函数 + 2 个类（`OptimizeError`、`SolveInput`）。
- **缝**：清晰的「数学核 ↔ 求解器」分层。
- **配方**：
  - `engine/optimizer_math.py` ← `to_returns`、`ledoit_wolf_diag`、`ewma_cov`、`estimate_cov`、`_ewma_mean`、`bayes_stein_mean`、`estimate_mean`、`_proj_simplex_box`、`_proj_halfspace`、`project`、`is_feasible`、`correlation_clusters`
  - `engine/optimizer.py` 留求解器：`solve`、`frontier_points`、`_mv_score`、`_min_variance`、`_risk_parity`、`_inverse_vol`、`_equal_weight`、`_max_sharpe`、`portfolio_stats`、`asset_stats`、`optimize_portfolio`

#### E-2. `backend/app/strategies/builtin_advanced.py` 678 行（超软 600）
- **内部结构**：9 个策略类 —— `MlAlphaRidge`、`VolManagedMomentum`、`RegimeAdaptive`、`DualThrust`、`VcpBreakout`、`GridTrading`、`RiskParityAlloc`、`EnsembleVote`、`MultiFactorScore`。
- **配方**：按策略族拆包 —— `strategies/advanced/{ml.py, trend.py, regime.py, breakout.py, grid.py, alloc.py, ensemble.py, factor.py}`，`builtin_advanced.py` 变成**注册表 barrel**（import 各策略并登记）。
- ⚠️ 无未来函数铁律：搬家**不要**顺手改任何 `shift` / 信号时序，纯搬。

#### E-3. `backend/app/engine/stream.py` 1062 行（**超硬 900**）
- **内部结构**：4 个类（`SymbolState`、`Subscriber`、`HubStats`、`MarketDataHub`）+ 6 个顶层函数（`_num`、`_price`、`tick_from_quote`、`_iso_now`、`get_hub`、`shutdown_hub`）。
- **缝**：3 个小类 + 4 个工具函数是**纯数据类型与工具**，与 Hub 主体（含 51 个方法）无强耦合。
- **配方**：
  - `engine/stream_types.py` ← `SymbolState`、`Subscriber`、`HubStats`、`_num`、`_price`、`tick_from_quote`、`_iso_now`
  - `engine/stream.py` 留 `MarketDataHub` + `get_hub` / `shutdown_hub`
- ⚠️ `get_hub()` 是**单例入口**，被大量模块 import —— 拆分后 `stream.py` 必须继续导出它（barrel 或原地保留）。

### Batch F —— 后端巨型类（4 个，最难）

这 4 个的核心难点相同：**一个巨型类，方法数 50+**，必须用 **mixin 拆分**（§5.5）。

#### F-1. `backend/app/intel.py` 1916 行（**超硬 900**）
- **内部结构**：1 个类 `IntelScheduler`（54 个方法）+ **46 个顶层函数**。
- **缝**：顶层函数本身就已经按业务域聚集，非常清晰。
- **配方**：`intel.py` → `intel/` 包：
  | 新文件 | 内容 |
  |---|---|
  | `intel/bridge.py` | `bridge_base_url`、`bridge_guide`、`bridge_log`、`pending_tasks`、`_gen_token`、`reset_bridge_token` |
  | `intel/settings.py` | `ensure_settings`、`save_settings`、`ensure_default_companies` |
  | `intel/events.py` | `_norm_title`、`_norm_event_time`、`make_dedupe_key`、`add_events`、`_seen_add`、`_event_row` |
  | `intel/scrape.py` | `_touch_scrape`、`scrape_batch`、`ai_scrape_companies`、`ai_harvest_events` |
  | `intel/analysis.py` | `auto_analyze_symbol`、`analysis_due_symbols`、`_local_analysis`、`_llm_analysis`、`_sanitize_analysis`、`add_analysis`、`_analysis_row`、`company_brief` |
  | `intel/verify.py` | `verify_due_analyses`、`_calibrate`、`_brier`、`verify_stats`、`_hold_hit`、`_hit_for`、`_close_on_or_before`、`_run_row` |
  | `intel/report.py` | `write_report`、`_render_report`、`window_days_for` |
  | `intel/timeline.py` | `timeline`、`_event_face`、`_event_face_weights`、`_rec_from_score`、`_vol_position_scale` |
  | `intel/scheduler.py` | `IntelScheduler`（用 mixin 组装）+ `resume_on_startup` |
- ⚠️ `IntelScheduler` 的 mixin 拆分要**按调度阶段**切（取数 / 分析 / 校验 / 上报），不要按字母序切。
- ⚠️ `intel_classify.py`、`intel_digest.py`、`intel_activity.py` 已经是独立模块 —— 拆 `intel.py` 时**不要**把它们卷进来。

#### F-2. `backend/app/brokers/ibkr.py` 1804 行（**超硬 900**）
- **内部结构**：`_ContractSpec` + `IBKRBroker`（64 个 def + 1 个 async def）+ 3 个顶层函数（`_silent`、`_apply_status_snapshot`、`get_ibkr`）。
- **缝**：`IBKRBroker` 的方法天然分成 4 个能力域。
- **配方**：`brokers/` 下 mixin 拆分：
  | 新文件 | 内容 |
  |---|---|
  | `brokers/ibkr_conn.py` | 连接/事件：`connect`、`disconnect`、`connected`、`_register_events`、`_on_error`、`_on_disconnected`、`_gate`、`_require`、`_ensure_loop`、`_call`、`_await`、`_submit`、`_sleep`、`_import_ib`、`invalidate_caches`、`_apply_market_data_type`、`_apply_status_snapshot` |
  | `brokers/ibkr_market.py` | 行情/合约：`get_tick`、`subscribe`、`unsubscribe`、`streamed_symbols`、`stream_status`、`_on_pending_tickers`、`_tick_from_ticker`、`_spec`、`_contract`、`display_symbol`、`_ticker_row`、`_tick_row`、`_empty_row`、`snapshot`、`_snapshot_once`、`history`、`quote`、`quotes` |
  | `brokers/ibkr_account.py` | 账户/持仓：`account`、`positions`、`_summary`、`open_orders`、`today_fills`、`status` |
  | `brokers/ibkr_orders.py` | 下单/回报：`place_order`、`cancel_order`、`cancel_all`、`order_status_snapshot`、`_status_from_trade`、`_on_order_status`、`_on_exec_details`、`_on_commission`、`_remember_exec`、`_record_report_latency`、`_ensure_writer`、`_enqueue_write`、`_writer_loop`、`_apply_write`、`drain_writes` |
  | `brokers/ibkr.py` | `_ContractSpec` + `class IBKRBroker(IbkrConnMixin, IbkrMarketMixin, IbkrAccountMixin, IbkrOrderMixin, Broker)` + `get_ibkr` |
- ⚠️⚠️ `broker.connected == True` **≠** 数据农场可用：TWS 报 2103/2105 时 TCP 仍活，`history()` **静默返回空且 `error=""`**。拆 `history()` 时不要动探活逻辑。
- ⚠️ `IBKRBroker` 有 `__init__` 与大量实例属性（`_lock`、`_writer`、缓存等）—— mixin 方法依赖这些属性，**属性初始化必须留在组装类 `ibkr.py` 的 `__init__`**，mixin 只提供方法。

#### F-3. `backend/app/data_provider.py` 1311 行（**超硬 900**）
- **内部结构**：3 个类（`SymbolInfo`、`_LocalHistProvider`、`TwelveDataProvider`）+ 49 个顶层函数。
- **缝**：`_from_*` 系列（各数据源解析）是天然的一源一文件。
- **配方**：
  | 新文件 | 内容 |
  |---|---|
  | `providers/yfinance.py` | `_from_yfinance`、`v_yf`、`_mark_yf_fail`、`_mark_yf_ok`、`yf_breaker_active`、`_yf_incremental_bounded` |
  | `providers/stooq.py` | `_stooq_symbol`、`_from_stooq`、`v_st` |
  | `providers/tencent_hk.py` | `_tencent_hk_code`、`_from_tencent_hk`、`_from_tencent_hk_m1`、`_from_tencent_hk_quote`、`v_tencent_hk`、`v_tencent_hk_m1` |
  | `providers/finnhub.py` | `_from_finnhub`、`v_fh` |
  | `providers/twelvedata.py` | `_from_twelvedata`、`v_td`、`TwelveDataProvider`、`register_twelvedata_provider` |
  | `providers/synthetic.py` | `_synthetic`、`_market_of` |
  | `data_provider.py` | 链与缓存编排：`fetch_history`、`fetch_many`、`get_quote(s)`、`_cache_*`、`_chain_*`、`register_*`、`provider_status`、`SymbolInfo`、`_LocalHistProvider`、`_normalize` |
- ⚠️⚠️ **搬家不许改语义**（§R9 三个静默坑）：
  1. `_normalize` **非幂等** —— 只能被调用一次，位置不能变。
  2. TwelveData 的 datetime 是**无时区墙钟**，必须 `tz_localize("America/New_York")` 后由 `fetch_history` 做**唯一一次**归一化。
  3. `outputsize=5000` 分支**不认 `end`** → 会读到**未来数据**。这个分支搬家时原样保留。
- ⚠️ 诚实性铁律（铁律 13）：请求区间超出本地覆盖必须返回 `None`；`source == "synthetic"` 的数字是**随机漫步编造的**，不许当真实行情输出。

#### F-4. `backend/app/engine/live.py` 1151 行（**超硬 900**）
- **内部结构**：`EngineTick`(45–60)、**`EngineTask`(60–1145，约 1085 行，21 个 def + 5 个 async def)**、`BacktestSpecLite`(1145–)。
- **缝**：`EngineTick` / `BacktestSpecLite` 是纯数据类，与 `EngineTask` 无耦合；`EngineTask` 方法按**执行阶段**成簇。
- **配方**：
  - `engine/live_types.py` ← `EngineTick`、`BacktestSpecLite`
  - `EngineTask` 按阶段 mixin 拆：
    | mixin | 方法 |
    |---|---|
    | `_LiveSignalMixin` | `_build_signals`、`_refresh_signals`、`_signal_age_sec`、`_atr_for`、`_quotes` |
    | `_LiveRiskMixin` | `_live_limits`、`_check_stops`、`_place_protective`、`_cancel_protective`、`_cancel_all_protective` |
    | `_LiveExecMixin` | `_execute`、`_persist_order`、`_log_exec_decision`、`_snapshot_positions` |
    | `_LiveHubMixin` | `_attach_hub`、`_detach_hub`、`_on_hub_tick` |
    | `_LiveRuntimeMixin` | `_loop`、`run_once`、`runtime_stats`、`_update_run_row`、`start`、`stop` |
  - `engine/live.py` 组装 `class EngineTask(...)` + `__init__`
- ⚠️ 铁律 3：回测与实盘**共用 `StopTracker`**（`risk/stops.py`）—— `_check_stops` 搬家时**必须继续走 `StopTracker`**，不许另写一份止损逻辑。
- ⚠️ 铁律 2：无未来函数，`_build_signals` 的时序语义原样搬。

---

## 5. 拆分技术手册

### 5.1 零改动 barrel 拆分（前端 + 后端通用）

**核心事实**：删掉 `foo.ts`、新建 `foo/index.ts` 后，所有 `./foo`、`../components/foo`、`from app.foo import X` 的解析**完全不变**。
→ **消费者一行都不用改**，这就是 Batch A 敢先上的原因。

- 前端：`components/ui.tsx` → `components/ui/index.ts` ✅
- 后端：`app/intel.py` → `app/intel/__init__.py` ✅（`from app.intel import X` 不变）

**前提校验**：确认 `vite.config.ts` **没有 `manualChunks`** 配置（本仓库已确认无），否则拆 barrel 会改变 chunk 划分。

### 5.2 目录嵌套的路径陷阱

文件下沉一层后，**每一条相对 import 都要多一层 `../`**：

```ts
// 拆前（components/charts.tsx）
import { fmt } from "../lib/format";
// 拆后（components/charts/price.tsx）
import { fmt } from "../../lib/format";   // ← 多一个 ../
```

**这个坑非常容易漏**，且症状是 typecheck 报一堆 `Cannot find module`。Batch A 的 `charts` 拆分就踩了，最后用脚本统一重写路径才收敛。

### 5.3 含 JSX 的文件必须是 `.tsx`

Batch A 的 `charts/shared.ts` 里含 JSX（`TipBox`），但扩展名是 `.ts` → 报 `TS1005` / `TS1161`。
**只要文件里有 `<Tag>`，扩展名就必须是 `.tsx`**，哪怕它只是个工具文件。

### 5.4 文件私有 → 必须 `export`

拆分前是**文件私有**的常量/函数，被兄弟文件引用时**必须加 `export`**。
Batch A 的 `AXIS`、`GRID`、`TipBox` 就是这种情况 —— 漏了就是 `TS2304: Cannot find name`。

### 5.5 mixin 拆分巨型类（Batch F 专用）

一个类几千行时，按**能力域**把方法分散到多个 mixin 文件，组装类继承它们：

```python
# brokers/ibkr_orders.py
class IbkrOrderMixin:
    def place_order(self, ...): ...

# brokers/ibkr.py
class IBKRBroker(IbkrConnMixin, IbkrMarketMixin, IbkrAccountMixin, IbkrOrderMixin, Broker):
    def __init__(self, ...):
        ...  # 实例属性初始化留在组装类
```

**纪律**：
1. **实例属性初始化留在组装类的 `__init__`** —— mixin 只提供方法，不负责属性。
2. **按业务阶段切，不要按字母序切** —— 否则等于没切，只是把文件打散。
3. 每个 mixin 拆完立刻跑该模块的回归（`run_checks.py api` / 对应领域检查）。
4. MRO 顺序要保证 `Broker`（抽象基类）在最后。

### 5.6 写拆分脚本时：**用 Write 工具写文件，不要用 heredoc**

Git Bash（MSYS）会把 heredoc 里的 `\s` 篡改成 `/s`，让 Python 正则**静默匹配失败**（返回 `None` 而不是报错）。
Batch A 就因此踩过一次。**所有拆分脚本一律用 Write 工具落盘成 `runtime/_split_*.py` 再执行**，并且脚本里加**字节级自检**：

```python
assert _orig == _rebuilt, "拆分丢行/重复行！"
```

这条断言是 Batch A 三个拆分全部安全的根本保证 —— 它证明「原文件每一行都在、且只出现一次」。

---

## 6. 验证与收尾清单

### 6.1 每拆完一个文件

| 步骤 | 命令 |
|---|---|
| 前端类型 | `cd frontend && npm run typecheck` |
| 前端渲染 | `cd frontend && npm run test:render`（期望 **240/240**） |
| 前端构建 | `cd frontend && npm run build` |
| 规模棘轮 | `cd backend && .venv/Scripts/python.exe ../tests/run_checks.py size` |
| 后端回归 | `cd backend && .venv/Scripts/python.exe ../tests/run_checks.py <data\|strategies\|api\|rankings\|screener\|ai\|intel>` |

> ⚠️ `run_checks.py` 需要 `dangerouslyDisableSandbox`（沙箱会杀 `init_db()`）。
> ⚠️ 改完后端代码后 8787 **不会自动生效**，需重启服务。

### 6.2 一批拆完后

1. `python tools/gen_size_baseline.py --dry-run` —— 确认**只有「摘除」，没有「新增/增长」**。
2. 确认无误后 `python tools/gen_size_baseline.py` 写入。
3. 复跑 `run_checks.py size`，确认 3/3 通过且无 stale 提示。

### 6.3 进度追踪

| 批次 | 文件数 | 已还 | 剩余 |
|---|---|---|---|
| A | 3 | ✅ 3 | 0 |
| B | 2 | 0 | 2 |
| C | 4 | 0 | 4 |
| D | 3 | 0 | 3 |
| E | 3 | 0 | 3 |
| F | 4 | 0 | 4 |
| **合计** | **19** | **3** | **16** |

### 6.4 建议优先级

1. **Batch B**（2 个，小）—— 继续用低成本验证流水线。
2. **Batch D 的公共模块抽取** —— 一次改动同时降 `movers.py` 与 `rankings.py`，性价比最高。
3. **Batch C**（4 个页面）—— 机械但量大，适合批量推进。
4. **Batch E** → **Batch F** —— 难度递增，Batch F 必须最后做且逐个跑领域回归。

---

## 附：本清单**不包含**的既有问题

以下问题在本轮工作中发现并已处理，但**不属于**规模债，故不在此表：

| 问题 | 位置 | 处理 |
|---|---|---|
| 真实 `TWELVEDATA_API_KEY` 被当作测试夹具硬编码 | `tests/run_checks.py:2325` | ✅ 已改为合成假密钥 `deadbeefcafe1234...`；`git log -S` 确认**从未提交** |
| 临时产物被 `git add -A` 带入暂存区 | 仓库根 `rk_*.json`、`rk_*.txt`、`prem_test.txt`、`tools/*.log` | ✅ 已加入 `.gitignore` |
