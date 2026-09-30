# AI 情报中心 · 抓取 / 入库 / 排序 / 权重 梳理与改进建议

> 落盘日期：2026-09-30  
> 适用版本：QuantDesk for IBKR · `backend/app/intel/` 包 + `intel_digest*.py` / `intel_classify.py`  
> 本轮同步：默认抓取模型 → `监hy4-perview`（详见第 7 节）

## 0. 现状速览（四个环节的关键数字）

| 环节 | 关键文件 | 当前关键参数 | 现状问题 |
|---|---|---|---|
| 抓取 | `intel/scrape.py` · `intel/scheduler.py` | `news_limit=15` / 监控 30 分钟一轮 / pinned ≤4 + 漏检 ≤3 · surge_pct=3% | ORCL 类旗舰发布曾被打 2★、监控漏暴涨（已加打标校准 + 异动联动，仍需扩覆盖） |
| 入库 | `intel/events.py` · `intel_classify.py` | dedupe_key = sha1(symbol\|category\|归一化标题) · 评论类封顶 34.9 · 同(发生日,方向)封顶 3 条 | 标题归一只去非 a-z0-9 中文，英文标点 + 大小写已处理，但缩写/数字串未归一（如 `H100` vs `H-100`） |
| 排序 | `intel_digest.py` · `intel_digest_scoring.py` | `_pick_top` 12 条 / 单标的 2 条 / critical 2 条 · `_fold_families` 同(标的,发生日)合并 | 已被旧重大事件钉死的根因已解（09-30 加时效两档），但「特别重大豁免」边界需收窄（rumor 5★ 不应豁免） |
| 权重 | `intel_digest_scoring.py` | `BASE_MAX=88` / mod `[0.92, 1.10]` / `CATEGORY_WEIGHT`/`STAGE_WEIGHT`/`SOURCE_WEIGHT_HINT` / `_freshness` 两档 | 修正系数 `[0.92, 1.10]` 偏窄：4★ 始终压不过 5★，但 5★ 之间强弱分不清 |

## 1. 抓取 / 入库 / 排序 / 权重 · 一句话总览

> 抓取是输入端（多源 + LLM 打标），入库是结构化（dedupe + 归一 + 字段），排序是合规（按 importance + 时效 + 折叠），权重是发动机（建议五大参数改动——见 §8）。

## 2. 抓取策略 · 调整方向

### 2.1 抓取频次（已实现，待扩展）

- **监控每轮 30 分钟**（`interval_minutes` 设置）。建议改为**事件驱动自适应**：
  - 监控内重 tick 轻量 20s 间隔（已实现于 `_check_surge`）；
  - 全量抓取轮转仍按 `interval_minutes`，但当**任一标的当日 ≥ 2 条新增 ≥ 4★** 时自动压缩到 15 分钟；
  - 静默 4 小时后回 60 分钟。
  - 实现点：`intel/scheduler.py::_run_once` 加 `dynamic_decide_next_interval()`，落 `runtime/int_cache/intel_dynamic_interval.json`（TTL 5 分钟）防抖。

### 2.2 抓取范围（已实现，待精细化）

- **重点标的 pinned ≤4 + 漏检 ≤3** = 每轮 ≤7 家（已实现）。建议：
  - **「新近异动」自动池**：当任一非 pinned 标的 7 日内 ≥ 3 条 ≥ 4★ → 自动加入下一轮重点池 1 次，到期轮转（避免重要标的长期漏检）；
  - **行业聚类**：当 ≥ 3 家同业同日报 ≥ 1 条 ≥ 4★ → 拉该行业 GICS 子板块 top 10 市值一并抓（如半导体板块集体回调，先抓 SMH 成分股，板块级归因）；
  - **休眠策略**：连续 5 轮无 ≥ 3★ 事件的标的 → 自动降级 60 分钟间隔，监控到再次异动即恢复。

### 2.3 多源新闻聚合（已实现，待加权）

- 当前 `fetch_news(symbol, limit, force)` 走 Google News RSS + yfinance + sec（见 `app/news.py`）。
- 建议加**源可信度权重**（与 `SOURCE_WEIGHT_HINT` 联动）：
  - 优先级：SEC filing > Reuters/Bloomberg/WSJ > Yahoo Finance > 聚合器；
  - 单源独有新闻（其他源无重复）→ 影响力减半（去重伪信号；待补 `source_count` 字段，09-30 没改）。

### 2.4 LLM 打标（已加 ORCL 校准，待扩）

- 已在 `_EVENT_HARVEST_PROMPT` 加打标校准（旗舰发布/大额合同 → 4~5★）。建议：
  - **「应给 5★ 而只给了 ≤3★」的负反馈循环**：把 `score_event` 算出来的 importance 与 LLM 自评 impact 对比，差异 > 30 分时把该事件标记 `miscalibrated=true`，落表 `intel_mislabel`（轻量表，schema 详见第 4 节），人工每周过一遍 → 微调 prompt；
  - **二级 prompt**：当 LLM 给 impact ≤ 3 但标题含「acquires」「merger」「guidance」「approves」「earnings beat/miss」「downgrade」「upgrade」「lawsuit」「FDA」等强信号词 → 自动跳到 4~5★（覆盖 OOB 偏差的硬编码校准）；
  - **news_limit**：当前 15，建议提升到 20（每多 1 条 ≈ 折 80 token prompt，14000 token 内完全装得下）。

## 3. 入库结构 · 调整方向

### 3.1 dedupe_key 归一化（已实现，待扩）

- 当前 `_norm_title`: `re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", title.lower())[:60]`
- 建议：
  - **数字串归一**：`h-100` → `h100`，`gpt-4.5` → `gpt45`，`q3`/`q4`/`q1`/`q2` 季度词简写保留（财报常出现）；`+`/`%` 视为无意义符号；
  - **公司名缩写**：解析标题里 `NVDA`/`nvidia`/`英伟达` 三种表述统一映射到 `nvidia`，避免同事件多 dedupe；
  - **时间词剥离**：`2026-09-30`/`Sep 30`/`今日`/`昨日` 等相对/绝对时间词归一（防止「股价 X 昨日 N%」类同事件按日期被判成两条）。

### 3.2 新字段（最小可行增量）

```sql
-- 轻量：与现有 intel_events 一起落，不破坏旧 schema
ALTER TABLE intel_events ADD COLUMN source_count INTEGER DEFAULT 1;        -- 多源重复计数（事件面去重）
ALTER TABLE intel_events ADD COLUMN miscalibrated BOOLEAN DEFAULT 0;      -- LLM 自评 impact 与 score_event 反差超阈值的标记
ALTER TABLE intel_events ADD COLUMN tags TEXT DEFAULT '';                  -- 逗号分隔强信号词：earnings|guidance|merger|...（用于二级校准）
ALTER TABLE intel_events ADD COLUMN half_life_days INTEGER DEFAULT NULL;    -- 业务半衰期（财报事件 30 天、产品发布 14 天、政策 90 天）—— 替代「固定衰减窗口」按事件类型区分
ALTER TABLE intel_settings ADD COLUMN lateral_mislabel BOOLEAN DEFAULT 0;   -- 启用 miscalibrated 自动检测（默认关，避免污染）
ALTER TABLE intel_settings ADD COLUMN scrape_dynamic_interval BOOLEAN DEFAULT 0;  -- 启用动态抓取间隔
```

落表路径：`backend/app/database.py::_MIGRATE_COLUMNS`（已记铁律，漏登记会让该列 INSERT 100% 静默 rejected）。

### 3.3 评论/媒体类（已实现，待定量）

- 当前 `is_commentary(title, summary)` 命中后 importance 封顶 34.9（永不进必读）。建议：
  - 封顶从 34.9 → **28.0**（连「可看」都不让进，彻底出局）—— 理由：分析师调价 / 行情播报若 35 分能进可看，会反向稀释「公司自身事件」的密度；
  - **「付费墙」首发**：标题以 `Why '| drop it|Top picks` 等排名性标题 → 同 comment 类封顶；
  - **二次校验**：summary 里有 `we believe|we think|in our view|analysts say|upgrade to|downgrade to` → 视为评论类，无论标题。

### 3.4 实时刷新触点（已实现三层）

- `add_events(inserted>0)` 尾 → `intel_digest.refresh_async("events")`
- `add_analysis` 尾 → `refresh_async("analysis")`
- `_check_surge` 记异动 → `refresh_async("surge")`
- GET `/intel/digest` → `refresh_if_stale()` 兜底（30s 节流）
- 建议补：**抓取批次结束**（无论新增 N 条）也触发一次 `refresh_async("scrape_done")` —— 已实现于 `intel/scrape.py::ai_scrape_companies` 每家批完时，但**整批结束**没有汇总触发。如果整批跨多家都无新增，必读就不更新（其实总数没变，OK），但**有新增**的抓取应统一触发。建议 `ai_scrape_companies` 末尾加一次 `refresh_async("ai_scrape")` 做整批兜底。

## 4. 排序规则 · 调整方向

### 4.1 当前排序（已稳定，2026-09-30 三处加固）

- 排序键：`-importance, -impact, occurred_on, -id`（`score_event` 已算 importance）
- `_pick_top`：`per_symbol=2` / `critical_per_symbol=2` / `top_n=12`
- `_fold_families`：同 (symbol, occurred_on) 留 importance 最高
- 建议：
  - **`top_n` 个性化**：用户硬要求「必读 12 条」是默认值，建议加可读（设置页 `daily_digest_top_n` 8/12/20）。当前 12 条在 4★ 集中涌入时仍不够；
  - **critical 配额进一步收紧**：从 2 降到 1 时太苛刻，建议**软配额**：当 critical 候选 ≥ 3 家、其中 ≥ 1 家 24h 内有 ≥ 2 条 critical → 启用「5★ 集中度限制」：单标的最多 1 条 critical + 1 条非 critical，让必读位给更多标的；
  - **去重后 quota 利用率**：`_fold_families` 后还要过滤 `commentary`，建议合并到一个过滤函数避免二次扫描。

### 4.2 同题折叠窗口（建议扩）

- 当前按 `occurred_on` 同日折叠。建议扩到 **24 小时窗口**（按 `occurred_at` 计算）：
  - 实战中「财报发布」事件常跨 24 小时有「盘前预告」与「盘后正式发布」两条，被折叠掉用户也能接受；
  - 副作用：跨日同主题事件不再折叠（如周一传闻 + 周三确认）—— 这是 4★ / 5★ 跨档演化，反而该保留。

### 4.3 totals.today（已实现）

- 按 `created_at` 本地日历日统计。建议同时落**「新增 ≥ 4★ 数」**、`「新增 critical 数」` 让用户在 `totals` 上看到「今日新增 N · 重大 M」，避免「总数 35 全是 3★」的假象。

## 5. 权重计算 · 调整方向（重点）

### 5.1 修正系数区间（建议放宽）

- 当前 `mod ∈ [0.92, 1.10]`（±10%）。
- 问题：5★ 与 5★ 之间、4★ 与 4★ 之间，重要度差不超过 ±10%，用户看不出差距。
- 建议放宽到 **`mod ∈ [0.85, 1.18]`**（±15~18%）：
  - 计算 5★ 区间：从 `[80.9, 96.8]` 扩到 `[74.8, 103.8]` —— critical 阈值 79 → 强正向 5★ 进 critical，普通 5★ 边缘；
  - 但要先确认 TIER_CRITICAL/HIGH/MEDIUM 阈值（79/60/40）按新 BASE 重新校准（见 5.3）。
- 同步把 `mod = 1 + (cw-1)*0.5 + (sw-1)*0.5 + (src-1)*0.5 + (sent-1)*0.5` 改成自适应：来源权重 `(src-1)*0.7`（影响放大），类别 `(cw-1)*0.5` 不变。

### 5.2 时效曲线（已两档，待收窄豁免）

- 当前：5★ 缓衰减豁免，4★ 及以下陡衰减。
- 建议收窄豁免到 **「confirmed + 5★」**：
  - 条件加 `stage == "confirmed"`：`rumor` 5★ 走标准曲线（陡衰减）；
  - 实证 `confirmed 5★ age3 importance` 仍 ≥ 70 → 保留 high 档；`rumor 5★ age3` 因 mod 已被 rumor 系数压到 ~64 → 跌出 high。让「传闻级重大」从必读滑落，符合用户「时效性也很重要」的本意。

### 5.3 类别 / 阶段 / 来源权重（建议量化更新）

| 类别 | 当前 | 建议 | 理由 |
|---|---|---|---|
| `earnings` | 1.25 | **1.30** | 财报直接改盈利预期，加权该最高；与 merger 拉开 |
| `partnership` | 1.20 | **1.25** | 大额合同/积压订单（如 ORCL 6640 亿）应与财报等量 |
| `regulatory` | 1.15 | **1.20** | 重大监管可一票否决（FDA 拒批 / FAA 停飞），提权 |
| `product_launch` | 1.10 | **1.15** | 旗舰发布（如 ORCL Agent 平台）应与监管平级 |
| `model_release` | 1.10 | **1.15** | AI 模型发布影响中期基本面，提升 |
| `macro` | 0.90 | **0.85** | 宏观一般对单股弱相关，下调 |
| `personnel` | 0.85 | **0.75** | 人事常是噪音，CEO/首席科学家级别另说（要靠二级 prompt）|
| `other` | 0.80 | 不变 | |

| 阶段 | 当前 | 建议 | 理由 |
|---|---|---|---|
| `confirmed` | 1.25 | **1.30** | 已敲定事实是最大加权 |
| `negotiating` | 1.00 | **0.95** | 在谈口径应略低于普通未分类 |
| `rumor` | 0.65 | **0.55** | 传闻更低，与 confirmed 拉开 |
| `""` | 1.00 | **0.95** | 普通事件略低于默认（让 negotiating 高于它） |

| 来源权重 | 当前 | 建议 |
|---|---|---|
| sec / gov / fda / faa | 1.15 | **1.20**（一手监管最高）|
| reuters / bloomberg / wsj / ir. / company | 1.10 | 1.10（不变）|
| cnbc / ft.com | 1.05 | **1.08** |
| 其他 | 1.00 | 1.00 |

### 5.4 direction（方向）权重

- 当前：`negative=1.08` / `positive=1.0` / `neutral=0.92`
- 问题：负向优先 8% 太小，5★ 利空 vs 5★ 利好分不出。
- 建议改为 `negative=1.18` / `positive=1.05` / `neutral=0.88`：负向最大幅度更高（风险优先于机会），正向微调（机会不应平于中性），中性下调（中立叙述的更弱）。

### 5.5 TIER 阈值（建议重校）

- 当前：CRITICAL 79 / HIGH 60 / MEDIUM 40。
- 配合 5.1 mod 放宽与 5.3 权重重，建议：
  - **CRITICAL 82**（强 5★ 独有）：5★ plain 最差 `88×1×0.85=74.8` 不进 critical；5★ + best mods `88×1.18=103.8` 进。
  - **HIGH 62**：保持。
  - **MEDIUM 42**：略提（让 4★ day1 边缘项不轻易掉进 medium）。
- 这些数值改动后必须**同步更新 run_checks.py 的 scoring 断言**（同 5.1 配套）。

### 5.6 importance 上限（建议保留 100 封顶）

- 当前 `round(max(0, min(100, ...)))`。不改。防止排序退化。

## 6. 默认抓取模型变更（2026-09-30）

- 设置位置：`backend/runtime/.env`（`QD_AI_MODEL`）或运行时 DB `settings["ai_settings"]`（设置页「AI 分析」）
- 当前值：`gpt-4o-mini`（config.py 默认）
- 本次修改为：**`监hy4-perview`**
- 注意：项目无模型白名单——任何字符串会透传给网关。若网关未注册该模型，AI 调用会失败；当前 `_llm_call` / `ai_harvest_events` 已有优雅降级（落 `local` engine），不会导致系统崩溃，但「AI 抓取」会回退到只跑本地量化分析，无 LLM 打标。
- 如 `监hy4-perview` 是某具体模型的代号，请确认其已在所配 `QD_AI_BASE_URL` 网关的 `/v1/models` 列表内（前端「AI 抓取」下拉会自动拉）。

## 7. 立即可落地的参数建议（一周内可上）

按**改动量小 / 风险低 / 收益可见**排序：

| # | 改动 | 文件 | 预计行数 | 预期收益 |
|---|---|---|---|---|
| 1 | 评论封顶 34.9 → **28.0** | `intel_digest_scoring.py` | 1 | 清除「评论类挤可看」 |
| 2 | 5★ 豁免加 `confirmed` 限制 | `intel_digest_scoring.py` | 3 | 传闻级 5★ 走陡衰减 |
| 3 | CATEGORY_WEIGHT 8 项调整 | `intel_digest_scoring.py` | 7 | 财报/合同/监管重大事件排序更明显 |
| 4 | STAGE_WEIGHT 4 项微调 | `intel_digest_scoring.py` | 4 | confirmed/rumor 差距拉大 |
| 5 | direction 权重 1.08/1.0/0.92 → **1.18/1.05/0.88** | `intel_digest_scoring.py` | 1 | 多空分开清晰 |
| 6 | mod 区间 [0.92,1.10] → **[0.85,1.18]** | `intel_digest_scoring.py` | 1 | 5★ 内强弱可分 |
| 7 | TIER 阈值 79/60/40 → **82/62/42** | `intel_digest_scoring.py` | 3 | 与新权重配套 |
| 8 | `totals.today` 旁加 `critical_today` / `high_today` | `intel_digest.py` | 6 | 总览条「今日新增 N · 重大 M」 |
| 9 | `_norm_title` 加数字串归一 | `intel/events.py` | 5 | `H-100` vs `H100` 同事件不重 |
| 10 | `source_count` 字段 + 自动去重增益 | `models.py` / `intel/events.py` | 30 | 单源独有新闻减半（防伪信号）|
| 11 | `ai_scrape_companies` 末尾整批兜底 `refresh_async` | `intel/scrape.py` | 4 | 多家批跑完后必读必更新 |
| 12 | `news_limit` 15 → 20 | `intel/scrape.py` | 2 | 每家多 5 条新闻，覆盖更多 |
| 13 | 抓取频率动态化（建议先灰度） | `intel/scheduler.py` | 40 | 异动期间响应更快 |
| 14 | 默认抓取模型 → **`监hy4-perview`**（已落，见 §6） | `runtime/.env` 或 DB | 1 | 落用户指定值 |

总改动 ≤ 100 行（核心 1-7 项 < 25 行）；高收益项是 3、5、10、11、14。

## 8. 中长期可演进（不在本周）

- 事件半衰期 `half_life_days` 替代固定窗口衰减（§5.1 节字段）
- LLM 自校准循环（miscalibrated → 周人工过 → prompt 微调）
- 行业聚类抓取 + 板块级归因面板
- 多引擎观点交叉（AI 解读 + 本地量化 + 桥接外部 Agent）
- 事件日市场反应（event study）：事件入库时记次日收益标 `priced_in` 字段
- 付费数据源接入（Polygon / Databento）补充分钟线异动检测