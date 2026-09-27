# AI 情报中心 · 外部 Agent 接入指南

> 让 WorkBuddy / Claude Code / Codex 等 AI Agent 联网抓取**当天新闻**，自动产出带真实来源的买入建议，
> 全部沉淀到 QuantDesk「AI 情报中心」（`/intel`）页面。

---

## 架构

```
外部 AI Agent（WorkBuddy / Claude Code / Codex）
    │  ① GET  /api/intel/bridge/poll          领任务（哪些公司该抓了）
    │  ② Agent 自己联网检索当天/近 90 天新闻
    │  ③ POST /api/intel/bridge/events        提交事件（必须带真实来源 URL）
    │  ④ GET  /api/intel/bridge/brief/{sym}   取该标的简报（行情+事件+持仓）
    │  ⑤ POST /api/intel/bridge/analysis      提交买入建议（BUY/SELL/HOLD…）
    │  ⑥ POST /api/intel/bridge/done          结束本轮
    ▼
QuantDesk 情报中心（事件去重建档 → 建议 → 报告 → 可转交易提案）
```

- **鉴权独立**：Bridge 端只认 `X-Intel-Token`（与平台登录/JWT 完全隔离）。
  token 在「AI 情报中心」页面可见/重置，或调 `POST /api/intel/bridge-token/reset`（需登录）重新生成。
- **建议字段归一化**：`recommendation` 大小写/连字符均可（`BUY`/`STRONG-BUY` 自动归一）。

## 快速开始（推荐：用现成客户端脚本）

```bash
cd C:\Users\Louis\Desktop\IBKR\backend
python ..\tools\intel_bridge.py token            # 查看/生成 bridge token（需输平台口令）
python ..\tools\intel_bridge.py poll  --token <TOKEN> --agent workbuddy
# ……agent 联网检索、整理 ev.json / an.json ……
python ..\tools\intel_bridge.py events  --token <TOKEN> --file ev.json
python ..\tools\intel_bridge.py analysis --token <TOKEN> --file an.json
python ..\tools\intel_bridge.py done    --token <TOKEN> --note "本轮完成"
```

## Claude Code / Codex 提示词模板

把下面这段直接发给有联网能力的 AI Agent（Claude Code / Codex / WorkBuddy）：

```text
你是 QuantDesk 的外部情报 Agent。执行以下任务：
1. 运行 `python tools/intel_bridge.py poll --token <TOKEN> --agent claude-code` 获取待研究公司列表；
2. 对每个 symbol，联网检索该公司最近 90 天的关键节点（产品发布/财报/合作/监管/人事），
   要求至少 2 条带真实 URL 的来源，禁止编造；
3. 把事件整理成 ev.json（格式见 tools/intel_bridge.py 文档头），
   运行 `python tools/intel_bridge.py events --token <TOKEN> --file ev.json` 提交；
4. 综合事件与行情给出买入建议 an.json（recommendation: BUY/HOLD/…，confidence 0-100，
   rationale 引用上面的事件），运行 `python tools/intel_bridge.py analysis --token <TOKEN> --file an.json`；
5. 运行 `python tools/intel_bridge.py done --token <TOKEN> --note "本轮完成 N 家"`。
全程不要编造新闻来源；无法确认的信息标注"未证实"。
```

## 字段说明

**事件 events[]**（`category` 可选值见 poll 响应的 `event_categories`）：

| 字段 | 必填 | 说明 |
|---|---|---|
| symbol / title / source_name / source_url | ✅ | 事件必须可溯源 |
| category | ✅ | product / earnings / partnership / regulatory / management / macro / competition / other |
| summary / published_at / sentiment / importance | 建议 | sentiment: positive/neutral/negative；importance: low/medium/high |

**分析 analyses[]**：

| 字段 | 必填 | 说明 |
|---|---|---|
| symbol / recommendation / confidence | ✅ | recommendation: strong_buy/buy/hold/reduce/avoid（大小写均可） |
| rationale / horizon | 建议 | horizon: intraday/swing/position |
| target_price / position_pct / risk_factors / key_evidence | 可选 | 建议落地价格与证据链 |

## 已实测（2026-09-24，WorkBuddy Agent）

- poll 返回 9 家观察公司任务（GOOGL/AAPL/META/AMZN… stale）；
- NVIDIA 当天新闻 4 条（CUDA-Q 量子扩展、Vera Rubin NVL72 MLPerf 首测领先、
  与 Palantir 主权 AI 合作、9/24 股价回落归因）全部入库（0 重复）；
- 提交 `BUY`（置信度 71%、目标价 $260）→ 情报中心正确归档为 `buy / agent=workbuddy`。
