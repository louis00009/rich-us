# QuantDesk AI 情报监控 · 外部 Agent 抓取（agent: workbuddy）

## 执行记录

### 2026-09-26 19:06（Run #44）— watchlist 扩至 25 家，71 事件 + 25 建议
- poll 返回 **25 家全 stale**。watchlist 从 19 扩到 25，新增 **0700.HK(腾讯) / MU / INTC / SNDK / DELL / BE / GOOG / CSCO / PLTR / QCOM / MPWR / TSM**，
  全部只有 2-5 条存量；NVDA / META / AMD / CRM / V / COST / ASML 本轮 fresh 未派发。
- 提交 **71 条人工精写事件**（inserted=71, duplicates=0, rejected=0）+ **25 条建议**（inserted=25, errors=0），POST /done 成功。
  库内 intel_events 2348 → 2419。脚本 `backend/runtime/intel_payload_r44.py`（events / analysis / done 子命令），
  brief 落盘 `backend/runtime/briefs_r44/`。
- Token 仍为 `qdintel_dc61...27f9`（**连续第 5 轮验证：脚本入参写死的 `qdintel_6637...db02` 永久失效，开跑前必须读 `backend/runtime/bridge_token.txt`**）。
- 建议分布：**buy × 8**（MSFT 74/7、GOOGL 70/7、GOOG 70/3、TSM 78/8、AVGO 72/5、LLY 72/6、JPM 70/5、QCOM 66/3）
  / **hold × 13** / **reduce × 1**（ORCL）。总仓位 **79%**，留 21% 现金。
- **ORCL 从 hold 下调为 reduce**（本轮唯一评级变动）：不可抗力通知书虽是惯例，但 FT 披露的合同细节改变风险定价——
  延迟付款不能豁免付息与 Blue Owl 股权回报义务、carry cost 最长三年、供电风险合同明确由甲骨文承担；
  叠加 180 亿美元建设债跌破 90 美分、管道投运推迟至 2027-02。

**本轮最重要的可复用发现（下轮必读）：**
1. **Google News RSS 已从本机不可达**（`news.google.com/rss/search` 返回 WinError 10060 连接超时；上一轮 Run #38/39 还可用）。
   → **批量 RSS 抓取路线本轮失效**，`backend/runtime/intel_harvest_r44.py` 空转 26 分钟后被 kill，0 产出。
   下轮开跑前**先花 30 秒单独测一次 RSS 连通性**（`intel_harvest_r44.py` 前几行即可判断），不可达就直接走人工精写，别浪费 25 分钟。
2. **8787 端口会瞬时拒绝连接（WinError 10061）**：本轮事件提交与 /done 各踩一次，间隔几秒后 curl 重试即恢复（poll=200）。
   → **所有 POST 必须带重试**。`intel_payload_r44.py` 的 `post()` 已内置 5 次 × 5 秒重试，下轮直接复用。
   这也解释了为什么「服务可用性检查」不要只做一次。
3. **本轮 0 duplicate 的做法**：先按 symbol dump `intel_events` 的 count + max(occurred_on)，
   一眼分辨「薄标的（2-5 条）」与「密标的（100+ 条）」；对密标的改写**机制/数字/合同结构**，不改写结论。
   例：AVGO 已入库 AI 收入 167 亿 → 改写表外 SPV 融资包（1000 亿上限、敞口上限 290 亿、CDS +28bp）与 FY27/FY28 1150/2300 亿路径。
4. **brief 的 `snapshot.dist` + `regime_hint` 是建议里最有信息量的字段**（to_52w_high / RSI / ADX / RV20），
   比 `recent_events`（只 30 条、排序不可靠）有用得多。本轮每家建议都绑定了具体 RSI/ADX/距高点数字。
5. **SPCX 的 snapshot source 是 `synthetic`** —— 显示 1 日 -32.64%、RSI 12.5、ytd -60.4%，**不是真实行情**，建议里必须显式标注不可用于决策。
6. **0700.HK 的 quote source 是 `tencent-hk`、snapshot 是 `cache`** —— 港股报价延迟，建议里需提示与实时报价交叉验证。

**本轮信息质量坑：**
- `kalkine.com` 的礼来 Q2 数字（营收 230 亿、Mounjaro+Zepbound 149 亿）无独立第二源交叉，已弃用不用，
  改用 Fierce Pharma 的 IQVIA 周处方（可溯源）+ MHRA 批准（可溯源）+ 休斯顿 65 亿工厂（可溯源）。
- LLY 休斯顿工厂与英国 MHRA 批准的**原始报道未带确切日期**，已按「媒体于 9 月下旬报道」处理并选最接近日期（09-25 / 09-21），下轮若需精确日期要回原源核对。

## 下一轮待办
- **最高优先级：TSLA 10/01 Roadster 揭幕（是否给定价与量产时间表）+ 10/02 Q3 交付（43.5 万-47.5 万区间）。**
- **GOOGL 10/01 Suncatcher MVP 卫星发射**（4 颗 Trillium TPU 首次在轨跑 Gemini；芯片全功率 15 分钟即需停机降温）。
- **SPCX Starship Flight 14 定于 09/28 7:15 CT**（原定 09/22 已推迟 6 天，仍待 FAA 许可）——首次入轨 + 首次部署 26 颗 Starlink V3。
- **UNH：NYP 合同 09/30 到期的最终结果**（若破裂则 10/01 起转网络外，距 10/15 开放投保仅三周）。
- **MU 09/30 盘后 FY26Q4 财报**（对比营收 500 亿±10 亿 / 毛利率 86% / EPS 31±1）；**DELL Q3 在 11 月下旬**；
  **SNDK FY27Q1 在 11/05**；**腾讯 Q3 定于 11/18 董事会审批 + 考虑派息**。
- **INTC：14A PDK 0.9 是否 10 月如期交付** + 是否有具名外部锚定客户（陈立武明说拿不下可能停掉 14A）。
- **ORCL 10 月投资者日**（降杠杆方案是上调回 hold 的唯一触发点，当前维持 reduce）。
- NFLX 仍未出现在 watchlist（Run #28 遗留项，已连续 16 轮）。
