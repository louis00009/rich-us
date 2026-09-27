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

---
*本文件由平台维护；接口变更时以 `/api/openapi.json` 为准。*
