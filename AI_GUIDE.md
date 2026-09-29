# QuantDesk AI 操作手册（AI Takeover Guide）

> 本手册面向**任何**接入本平台的 LLM / Agent。目标是：读完本页 + 调一次
> `GET /api/ops/overview`，即可在无人工解释的情况下理解平台、评估状态并安全操作。
> 机器可读版本：`GET /api/ops/guide`（返回本文件全文）。

---

## 0. 平台是什么（一句话）

QuantDesk 是**本机单用户**的量化交易平台（FastAPI + React，单端口 8787，仅监听 127.0.0.1），
覆盖 美股 + 港股：行情（IBKR 流式 / 腾讯 / yfinance / Finnhub）、策略回测、组合优化、
实时交易引擎（模拟盘/实盘三重锁）、新闻聚合、智能提示、决策全程可回溯。

## 1. 接入与认证

```bash
# 1) 登录拿 token（本机单用户）
POST /api/auth/login  {"username": "...", "password": "..."}
# 返回 {"access_token": "...", ...}，有效期 12h

# 2) 之后所有请求带
Authorization: Bearer <access_token>
```

- 完整接口清单：`GET /api/openapi.json`（Swagger UI：`/api/docs`）
- 登录限速：连续 8 次失败锁定 300s —— **不要暴力重试**，口令失败立即停下询问用户

## 2. AI 接管的第一步（固定顺序）

```
1. GET  /api/ops/overview        ← 一屏拿到全部上下文（响应自带「字段说明」）
2. GET  /api/ops/decisions?limit=50   ← 读最近的决策历史，理解上一个决策者的思路
3. GET  /api/system/status        ← 确认 mode（模拟/实盘）、kill_switch、券商连接
4. 一切操作前先评估：熔断开关是否开启？券商是否连接？现在是哪个市场的交易时段？
```

## 2.5 实时数据（WebSocket，秒级）

```
ws://127.0.0.1:8787/api/ws?token=<access_token>
→ {"action":"sub","topics":["quotes:AAPL,0700.HK","intraday:AAPL","alerts"]}
← {"topic":"quotes","data":[{symbol,price,change_pct,rt_t,rt_delayed,...}]}   2 秒一拍
← {"topic":"alerts","data":[新事件]}
```

- `rt_t` = 交易所本地时间；`rt_delayed=true` 表示免费源延迟（美股无 IBKR 时 ~20s）
- 断线自动重连后**必须重新 sub**（服务端不持久化订阅）

## 2.6 AI 提案（交易建议单）—— AI 只有建议权

```
POST /api/ops/proposals        {"symbol":"AAPL","action":"BUY","size_pct":5,
                                "rationale":"…","entry":300,"stop":285,"take_profit":330}
                               → status=proposed（仅登记，绝不自动下单）
POST /api/ops/proposals/{id}/approve   ← 仅限人工（AI 禁止调用此接口！）
POST /api/ops/proposals/{id}/reject    ← 人工拒绝（记入决策日志）
```

- 批准后系统走**与手动下单完全一致**的护栏（熔断/实盘三重锁/仓位上限/做空开关/港股手数），执行结果回写 `order_id`
- AI 研判评分 |score| ≥ 45 且建议仓位 ≥ 5% 时会自动生成提案（single-symbol 时）

### 实盘模式（IBKR 实盘端口）下批准提案

四道防线缺一不可，全部由**人工**完成：
1. 环境变量 `QD_ALLOW_LIVE_TRADING=true`（backend/runtime/.env，改后重启服务）
2. `POST /api/trading/live-unlock`（确认短语 `I UNDERSTAND THE RISK` + 账户口令）
3. 券商已配置为 IBKR 且端口为实盘（TWS 7496 / Gateway 4001）
4. 批准接口需带 `{"password": "<账户口令>"}`（实盘下批准 = 下真单，后端强校验口令）

`GET /api/ops/overview` 的 `system.live_ready / live_reason` 实时反映链路状态；未就绪时批准自动降级为模拟执行并给出来原因。

## 3. 你能做什么（操作面）

| 操作 | 接口 | 安全约束 |
|---|---|---|
| 读账户/持仓 | `GET /api/trading/account`、`/api/trading/positions` | 无风险 |
| 读行情 | `GET /api/market/quote?symbols=AAPL,0700.HK` | 无风险 |
| 读榜单 | `GET /api/market/rankings?sort=change_pct&limit=50` | 无风险 |
| 读新闻/公告 | `GET /api/news?symbol=0700.HK` | 无风险 |
| AI 分析 | `POST /api/ai/analyze`（结果自动落决策日志） | 无风险 |
| AI 助手（16 类任务） | `POST /api/ai/assist`、`GET /api/ai/tasks` | 无风险，只读数据 + 生成文本 |
| **试算订单** | `POST /api/trading/preview` | 无风险，永远先 preview 再下单 |
| **下单** | `POST /api/trading/order` | 必过风控护栏；实盘需环境变量+运行时解锁双重开关 |
| 撤单 | `POST /api/trading/cancel/{order_id}`、`/cancel-all` | 不可逆 |
| 启停引擎 | `POST /api/trading/engine/start`、`POST /api/ops/engine/{id}/stop` | 停引擎会停掉止损跟踪 |
| dry-run 引擎 | `POST /api/trading/engine/dry-run/{strategy_id}` | **强烈建议接管后先跑一轮 dry-run** |
| 一键熔断 | `POST /api/ops/kill-switch?enable=true` | 紧急止损用：启用后所有新订单被拒 |
| 回测 | `POST /api/backtest/run` | 无风险 |

## 4. 安全边界（必须遵守）

1. **实盘三重锁**：环境变量 `QD_ALLOW_LIVE_TRADING` → 运行时解锁（确认短语+口令）→
   逐笔风控护栏。任何一层锁着，实盘单都会被拒 —— **不要尝试绕过**。
2. **每笔订单都会被护栏检查**：仓位上限/总敞口/日内亏损/回撤熔断/交易时段/黑名单。
   被拒时响应里有 `code` 与原因 —— 读懂再决定是否调整参数，不要盲目重试。
3. **港股特殊规则**：无原生市价单（平台自动转进取限价单）、TIF 只有 DAY/GTC、按每手整数倍交易。
4. **不可逆操作**（下单/撤单/停引擎/熔断）执行前，若与用户预期可能不一致，先向用户确认。
5. **决策必须可回溯**：你通过 `/api/ai/analyze` 产生的分析会自动落 `decision_logs`；
   引擎的每一笔单（含被拦原因）也在其中。出问题时的回查入口是
   `GET /api/ops/decisions?symbol=XXX`。

## 5. 决策回溯的数据结构

`GET /api/ops/decisions` 返回的每条记录：

```
actor     谁决定的：engine:<策略id> | ai:<模型名> | user:<用户名>
action    做了什么：BUY | SELL | STOP | SKIP:<原因> | ANALYZE | DRY_RUN
decision  一句话结论
reasoning 依据摘要（AI 分析时是 LLM 报告）
context   当时的因子快照（行情源/目标权重/权益/信号年龄/被拦原因…）—— JSON
order_id  关联订单（若有）
```

## 6. 如何让不同的大模型接入（模型无关设计）

平台与模型解耦在两个层面：

**层面一：平台内置的「AI 分析师」**（报告生成，不直接交易）
在 `backend/runtime/.env` 配置任意 **OpenAI 兼容** 服务后重启即可：

```ini
QD_AI_BASE_URL=https://api.openai.com        # 或 DeepSeek/Kimi/Qwen/GLM/OpenRouter/Ollama
QD_AI_API_KEY=sk-xxx
QD_AI_MODEL=gpt-4o-mini                      # deepseek-chat / moonshot-v1-8k / qwen-plus / glm-4 ...
```

| 供应商 | BASE_URL | 示例 MODEL |
|---|---|---|
| OpenAI | https://api.openai.com | gpt-4o-mini |
| DeepSeek | https://api.deepseek.com | deepseek-chat |
| Kimi | https://api.moonshot.cn | moonshot-v1-8k |
| 通义千问 | https://dashscope.aliyuncs.com/compatible-mode/v1 | qwen-plus |
| 智谱 GLM | https://open.bigmodel.cn/api/paas/v4 | glm-4-flash |
| OpenRouter | https://openrouter.ai/api/v1 | 任意模型名 |
| 本地 Ollama | http://127.0.0.1:11434/v1 | llama3.1 / qwen2.5 |

验证：`GET /api/ai/status` → `llm_configured: true, model: <你配的名字>`。
切换模型 = 改 `.env` 一行 + 重启。每次分析的决策日志都会记下当时用的模型名，
因此**不同模型的判断历史天然可对比**。

**层面一之二：AI 任务中枢（`/api/ai/assist`）—— 平台内建的 16 个 AI 接入点**

除了「AI 研判 / AI Copilot」，平台里还有 16 处功能点接入了 AI。它们**共用同一个入口**，
不需要你为每个功能点单独写接口：

```bash
GET  /api/ai/tasks                       # 列出全部 AI 任务（key / 标题 / 说明）
POST /api/ai/assist
     {"task": "backtest_diagnose",       # 任务名，见下表
      "payload": { ...该任务需要的真实数据... },
      "model": "",                       # 空 = 跟随「设置 → AI 分析」的全局模型
      "force_local": false}              # true = 跳过 LLM，只要规则化兜底
→ {"task":"…","title":"…","engine":"llm"|"local","text":"…","facts":{…},"llm_error":"…","data":{…}}
```

`data` 只在**结构化任务**里出现（登记时给了 `parse` 钩子）—— 目前只有 `smart_screen`，
它返回可直接作用到榜单筛选面板的条件。

| task | 用在哪 | 需要什么 payload |
|---|---|---|
| `symbol_brief` | 行情页 · AI 个股快评 | `{symbol, horizon?}` |
| `news_digest` | 新闻面板 · AI 新闻要点 | `{symbol, items?}`（不给 items 则后端自己抓） |
| `ranking_review` | 榜单页 · AI 候选池点评 | `{rows[], matched?, score_min?, sort?}` |
| `market_briefing` | 首页 · AI 盘面简报 | `{quotes[], account?, positions?}` |
| `backtest_diagnose` | 回测页 · AI 回测诊断 | `{strategy, symbols, metrics, params?}` |
| `optimize_review` | 优化页 · AI 寻优解读 | `{best, best_metrics?, baseline?, top_neighbors?}` |
| `strategy_draft` | 策略实验室 · AI 策略草稿 | `{description}` |
| `risk_review` | 风控中心 · AI 风控体检 | `{config, exposure?, positions?}` |
| `portfolio_review` | 持仓页 · AI 组合点评 | `{positions[], account?, exposure?}` |
| `order_diagnose` | 实盘页 / AIOps · 订单诊断 | `{orders[], limits?, mode?}` |
| `intel_brief` | 公司情报 · AI 情报解读 | `{symbol, events[], pipeline?}` |
| `stock_batch_review` | 榜单页 · 勾选 1 只/多只 → 深度分析 / 横向对比 | `{rows[], context?}`（≤12 只） |
| `smart_screen` | 榜单页 · 智能选股（自然语言 → 筛选条件） | `{query, sectors?[], sorts?[]}` → 返回 `data.filters` |
| `proposal_review` | AI 接管中心 · 批准前的**反方质询** | `{proposal, limits?, positions[]?, account?, mode?}` |
| `period_review` | 持仓页 · 交易复盘（盈亏归因 + 决策链条问题） | `{orders[], positions[]?, account?, decisions[]?, period?}` |
| `strategy_code_review` | 策略实验室 · 自定义策略**代码审查**（未来函数） | `{code}` |

设计约定（改代码时请遵守）：

1. **数据不编造**：payload 必须来自平台真实数据；后端只做裁剪与校验，
   大模型只做归纳与判断（提示词里已写死「不得编造价格/财报/新闻」）。
2. **降级可用**：未配置 LLM 时，每个任务都有确定性的**规则化兜底**，
   返回 `engine="local"`；页面不会空白也不会报错。因此前端**不需要**区分两种模式。
3. **AI 只有建议权**：所有任务的提示词都显式禁止输出「买入/卖出信号」；
   交易动作仍必须走 `ai_proposals` + 人工批准（§2.6）。
4. **可追溯**：分析/诊断类任务（`symbol_brief`/`backtest_diagnose`/`optimize_review`/
   `risk_review`/`portfolio_review`/`order_diagnose`/`proposal_review`/`period_review`/
   `strategy_code_review`）会写入 `decision_logs`（action=`ASSIST`）；
   纯展示类的简报只写审计日志，避免刷屏决策历史。
5. **新增接入点**：在 `backend/app/ai_tasks_market.py`（行情类）/
   `ai_tasks_analysis.py`（分析类）/ `ai_tasks_ops.py`（运营类）/
   `ai_tasks_screen.py`（选股类）/ `ai_tasks_strategy.py`（策略类）里写一个
   `_b_xxx`（构造上下文与提示词）+ `_l_xxx`（规则化兜底），再 `_register(...)` 登记即可，
   **不需要改 API 层**；前端用 `<AIAssist task="xxx" payload={...} />` 一行接入。
   需要**结构化结果**（给前端消费）的任务，额外传 `parse=_extract_json`。
   新增任务后记得同步三处守卫：`frontend/scripts/render-check.mjs` 的 `AI_TASKS`
   与 `AI_POINTS`，以及 `tests/run_checks.py` 的 `ai` 子集。
6. **推理型模型的 token 预算（重要，勿改小）**：`_MIN_TOKEN_BUDGET=6144`。
   实测当前网关的 `cn:glm-5.3-flash` 是推理模型，**每次先烧掉 1800~3200 token 思维链**，
   正文还要 ~1000-1500。预算给小了会返回 **HTTP 200 但 content 为空**（`finish_reason=length`），
   表现为「AI 一直转圈然后显示本地兜底」。`max_tokens` 超过 6144 反而会让网关 502。
   同时 `_LLM_TIMEOUT=180s`（默认 90s 会卡在边界，慢调用变成 ReadTimeout）。
   **绝不允许** `engine="llm"` 却展示本地兜底文案 —— 要么真 LLM 文本，要么标 `local` + `llm_error`。

**层面二：外部 Agent（如 Claude/其他助手）直接操作平台**
不需要平台内嵌任何 SDK —— 你（Agent）只需：
1. 登录拿 token（§1）；
2. 拉 OpenAPI + overview（§2）；
3. 按本手册 §3-4 调用 REST 接口。
所有端点都是标准 JSON REST，任何能发 HTTP 请求的模型都能操作。

## 7. 信息读取速查（数据在哪）

| 想知道 | 接口 |
|---|---|
| 全部上下文（一次拿全） | `GET /api/ops/overview` |
| 账户/持仓/订单/成交 | `/api/trading/account` `/positions` `/orders` `/fills` |
| 引擎运行状态与统计 | `GET /api/trading/engine`（每条含 runtime_stats） |
| 某标的 K 线/指标/快照 | `/api/market/history` `/indicators` `/snapshot` |
| 美股 Top 500 榜单 | `GET /api/market/rankings` |
| 公司档案（英文名/介绍） | `GET /api/market/rankings/profile?symbol=AAPL` |
| 新闻/港交所公告 | `GET /api/news?symbol=` |
| 关注列表 | `GET /api/watchlist` |
| 智能提示 | `GET /api/alerts`、`POST /api/alerts/scan` |
| 交易路径延迟 | `GET /api/system/latency` |
| 决策历史 | `GET /api/ops/decisions` |
| 回测历史 | `GET /api/backtest/runs` |
| AI 能力清单 | `GET /api/ai/tasks` |

## 8. 一个标准的接管会话（示例流程）

```bash
TOK=$(curl -s -X POST .../api/auth/login -d '{"username":"trader","password":"***"}' | jq -r .access_token)

# 1) 看状态
curl -s .../api/ops/overview -H "Authorization: Bearer $TOK"

# 2) 发现引擎 A 目标权重 AAPL=30% 但当前持仓 0%，想验证
curl -s ".../api/trading/preview" -H "Authorization: Bearer $TOK" \
  -d '{"symbol":"AAPL","side":"BUY","quantity":10,"order_type":"MKT"}'

# 3) 试算通过后（可选）手动下单，或让引擎自行执行
# 4) 事后回溯
curl -s ".../api/ops/decisions?symbol=AAPL&limit=20" -H "Authorization: Bearer $TOK"
```

## 9. 你要改代码时的约定（开发侧）

本手册前 8 节讲的是「怎么**操作**平台」。如果你还要**改这个仓库的代码**，
先读 `TODO.md` 末尾的《技术债与铁律》—— 其中两条最容易踩：

- **铁律 9 · 文件规模与组件化**：软上限（**超过就不得再加功能**）后端/页面 **600 行**、
  组件 **400 行**；硬上限（**冻结，只修 bug**）后端/页面 **900 行**、组件 **600 行**。
  ⚠️ **不要再维护「冻结清单」** —— 2026-09-29 已证伪并删除：旧清单写 `intel.py` 1192（实际 **1916**）、
  写 `Backtest.tsx` 1086（实际 **1641**），而 `Intel.tsx` 早就拆到 329 却还挂在清单上。
  **靠人记的清单 = 不存在的规则。** 唯一事实源是**棘轮守卫**，跑它：

  ```bash
  cd backend && .venv/Scripts/python.exe ../tests/run_checks.py size   # 秒级，不联网不碰库
  ```

  判定：① 超软上限且**不在基线** → FAIL（新债）；② 在基线但**比基线更长** → FAIL（棘轮被突破）；
  ③ 在基线且未增长 → 通过；④ 已降到软上限内 → 提示从基线摘掉。基线 `tests/size_baseline.json`，
  重算用 `python tools/gen_size_baseline.py` —— ⚠️ **只在真正拆分完成后跑**，否则等于把债锁死。
  ⚠️ **守卫报 FAIL ≠ 要重算基线**：若 FAIL 的文件**不是你改的**（并行会话在改），**保持 FAIL**，
  把别人的增长写进基线会让棘轮彻底失效。
  新功能必须**按组件 / 模块拆开写**：前端页面只做编排（取数 + 布局 + 状态），
  可复用业务块抽到 `components/`，重复出现的卡片/表格/表单块**禁止复制粘贴**；
  后端路由文件只做参数校验与编排，业务逻辑放 `engine/` 或独立模块。
- **铁律 10 · datetime 口径**：naive/aware 混合口径是**已知且已决定不改**的状态，
  **不要再当 bug 报**。写代码时不要假设从 DB 读出的时间字段带时区。
- **前端「人话词典」与共享零件**（2026-09-29 起）：给界面加术语悬浮解释**一律走
  `frontend/src/components/terms/`**（查词用 `index.ts` 的 `term()`，**不要另写一份气泡实现** ——
  那份实现里的 portal + `position:fixed` 修法必须只有一处）。词条三段式
  （是什么 / 怎么看 / 注意），**正文是纯文本**，写 `**加粗**` 会在气泡里显示字面星号
  （render-check 的「文案卫生」会拦）。表单排版零件 `components/form/parts.tsx`
  （`Chip`/`Step`/`Section`）。做「小白友好化」页面时的标准三件套：**分步向导 +
  新手模式默认开（高级项折叠、但不删）+ 每个术语可悬停**，外加跑前「本次要做什么」人话预览、
  跑后一句话结论（判定逻辑**抽成纯函数**并加单元断言）。已做：回测中心、组合优化。

改动完成后必须自证：

```bash
cd backend && .venv/Scripts/python.exe ../tests/run_checks.py   # 后端自检（按子集跑更快）
cd frontend && npm run typecheck && npm run lint:hooks && npm run build
```

> 覆写整个文件前**务必先核对它全部的既有导出** —— 本项目已两次因为整文件覆写而丢函数。

---
*本文件由平台维护；接口变更时以 `/api/openapi.json` 为准。*
