# Factor AutoResearch 调研与集成可行性评估

> 调研日期：2026-09-29 · 目标项目：[1191091728-bot/factor-autoresearch](https://github.com/1191091728-bot/factor-autoresearch)

## 一、项目识别

搜索 "auto research 因子挖掘" 命中多个同名项目，与需求最匹配的是 **factor-autoresearch**（中文项目，"LLM 自主因子挖掘实验"，上财 AI 金融实训营实践）。它把 Andrej Karpathy 的 autoresearch 自主研究范式移植到量化因子挖掘。同类可混淆项目：`karpathy/autoresearch`（原版，ML 训练实验，非因子）、`carlonicolini/autoresearch-skfolio`（组合优化版）、`dlmastery/autoresearch`（深度学习因子，无社区）、`microsoft/RD-Agent`（微软出品，量化因子/模型演化，13k star，最成熟）。

## 二、核心功能

- **Agent 自主循环**：LLM Agent 修改 `compute_factor.py`（唯一可编辑文件）→ 运行 `train.py` 回测 → 按费后 Sharpe 打分 → 保留（git 前进）/ 回退（git reset）→ 追加 TSV 记录，无限循环。
- **防作弊硬校验**：`FACTOR_NAME` / `FACTOR_DESCRIPTION` 必须与因子同步更新，否则记 crash；`main` 分支禁止跑实验；评估函数 `evaluate_factor` 只读。
- **实验协议**（program.md）：禁止安装新依赖、禁止修改评估逻辑；简洁优先（同分取更简单因子）；支持 `--pp` 持仓期（120/360/1440 分钟）与可选换手率 HSR 惩罚。
- **输出**：`results/pp<pp>.tsv` 完整实验日志 + `factor_keep/` 保留因子快照。

## 三、技术架构

纯 Python（numpy/pandas/pyyaml），无重依赖、无 GPU：

| 层 | 实现 |
|---|---|
| 数据 | BTCUSDT 5min K 线 parquet（币安，约 36MB，不入库），memmap 高性能加载 |
| 因子 | `compute_factor()` 返回 pd.Series；baseline 为 24h 对数动量 |
| 归一化 | 滚动分位数 scale（window=360d，min_periods=30d），只用过去窗口 |
| 回测 | 单因子单标的时序回测：TWAP 价格 pct_change 前瞻收益，换手率 × fee(0.0005) 扣费，输出费后 Sharpe |
| 状态机 | git 分支（实验分支）+ reset 作为保留/回退机制 |
| Agent | 任意文件编辑型 LLM Agent（Claude Code 等），program.md 为章程 |

## 四、代码质量评估

**优点**：
- 代码简洁、类型注解完整、docstring 详尽；防未来函数约束明确且写进协议（禁 shift 负数 / bfill / 全局统计）。
- 费后评估 + 换手率惩罚意识（防低换手偶然高 Sharpe）；TSV append-only 实验日志；防作弊校验是硬编码而非靠 prompt。

**缺陷**：
- **一次性实验仓库**：全库仅 1 个 commit（2026-08-17 "Initial"），1 位贡献者，之后零更新，无测试、无 CI、未见 License。
- **结构性过拟合风险**：回测区间硬编码（start=20210101, end=20221231），单标的（BTC）、单一数据频率，无样本外验证 / WalkForward / Deflated Sharpe——agent 无限迭代同一测试区间等于多重检验，"最优因子" 大概率是过拟合产物。
- **时序单标的范式**：因子是 BTC 时序信号，非美股截面选股因子（无 cross-sectional rank / 分组测试 / IC）。
- 中文注释、实训营作业性质，无社区背书。

## 五、维护活跃度

**不活跃**。创建于 2026-08-17，单 commit、单作者、无 issue/star 记录可查（个人小仓库），属课程实训演示而非持续维护的开源项目。**不应按依赖库引入**，只能当参考实现读源码。

## 六、与 QuantDesk 的集成可行性

### 1）因子挖掘能力如何辅助选股流程

直接照搬不可行，但**范式可完整移植**：

- **错配点**：本项目是加密货币单标的时序因子；QuantDesk 是美股/ETF 全市场（~2241 只）截面选股。因子范式不同（时序收益 vs 截面 rank）。
- **可移植的三原语**（Karpathy 范式的核心价值）：① 唯一编辑点（QuantDesk 对应 `strategies/custom.py` 因子文件）；② 单一标量指标（对应费后 Sharpe / RankIC）；③ 定时循环 + git 状态机 + append-only 日志（对应 `engine/jobs.py` 后台任务体系）。
- **现成安全边界正好接上**：QuantDesk 的 `validate_code` AST 白名单沙箱可直接约束 agent 产出的因子代码——这是本项目没有而我们已有的防线。
- **落点**：挖掘出的因子 → 过沙箱 → 注册为 `signals.py` 新规则候选（进 signal-catalog / 今日关注），与现有 10 条规则互补；再经 `/optimize` 与现有 sizing/护栏进入选股流程。
- **必须补的评估协议**：train/test 时间切分 + WalkForward + Deflated Sharpe + 与现有信号的去重（相关性检查），否则 agent 会把过拟合因子推给选股。

### 2）AI 自动化操作股市的扩展潜力

- 该项目本身**只做研究，不含任何交易执行**；扩展到自动交易需另建执行层。
- 潜力：与 QuantDesk 现有 AI 情报中心（intel）+ movers 解读 + 信号引擎可形成 "挖掘 → 验证 → 信号 → 建议" 的自动研究闭环；实盘仍由三重锁 + 人工确认把关（设计上就该如此）。
- **局限性**：LLM 循环成本（每轮 agent 调用，数百轮烧 token）；Goodhart 风险（agent 会以最高效方式过拟合评估指标）；单标时序范式迁移到美股截面的有效性未经验证。
- **数据依赖**：原项目依赖币安 5min parquet（自备，与美股无关）；换美股需重写 DataLoader，可直接接 QuantDesk 的 `data_provider`（IBKR→缓存→yfinance 降级链），但注意免费源日内数据仅 60 天，日线因子更现实。
- **风险**：过拟合因子上线实盘（最大风险，靠样本外协议 + paper 模式先行压制）；LLM 生成代码的安全（靠 AST 沙箱）；评估函数被间接博弈（因子空间隐式利用区间特性，靠 DSR 与滚动验证缓解）。

## 七、结论

1. **不建议直接集成该项目代码库**——一次性实训实验（1 commit、无测试、无 License、无维护），且数据与因子范式（加密单标时序）与 QuantDesk（美股截面选股）根本错配。
2. **建议移植范式而非代码**：在 QuantDesk 内新建 `factor_lab/`（或挂到 `engine/jobs.py` 长任务体系），实现 "agent 循环修改因子文件 → data_provider 喂数 → 截面回测评估（费后 Sharpe + RankIC + 样本外）→ validate_code 沙箱准入 → signals 注册" 的闭环。参考实现读它的 program.md 防作弊设计即可，评估器必须自研（加样本外 + DSR，这是原项目最大的洞）。
3. **需进一步验证的关键问题**：
   - 美股截面板范式下，agent 循环能否产出**通过样本外检验**的因子（先用日线 + SP500 子集做小规模试点，预算 ~50 轮）；
   - 评估协议设计：切分方式、DSR 阈值、换手惩罚、与现有 10 条信号的增量相关性；
   - LLM 成本/轮次预算与自动化收益是否成正比（对比直接用 RD-Agent 这类成熟框架的性价比）；
   - 若目标是"全自动炒股"，还需验证因子上线后 paper 模式的实际表现周期（建议 ≥1 个月）。

**一句话结论**：项目本身是质量不错的教学演示，不值得集成；其 "唯一编辑点 + 只读评估器 + 费后打分 + git 状态机" 的范式值得花 1–2 天在 QuantDesk 内自建移植版，且必须补上原项目缺失的样本外验证与沙箱准入。
