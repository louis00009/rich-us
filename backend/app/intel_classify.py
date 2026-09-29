"""事件归类与前瞻阶段推断（确定性规则，不调 LLM）
==================================================

**为什么需要它**：实测 3294 条事件的字段覆盖率是

    category  100%（但 47% 落在 other）
    stage       2%（只有 82 条有值）

提交侧不可控：提示词里早就写了 `stage`（`bridge_guide()` 与内置抓取提示词都写了
confirmed/negotiating/rumor 的定义），但外部 Agent 与 LLM 抽取基本不填 ——
**同一份提示词反复强调也仍然只有 2%**。所以「补齐」必须放在**入库口**做归一化：
所有入库路径（Bridge `POST /events`、内置 AI 抓取、autofetch）都经过
`intel.add_events`，在那里补最稳、且对提交方零要求。

设计边界（与项目诚实性铁律一致）
--------------------------------
· **只补空，绝不覆盖**：提交方给了值就尊重提交方 —— 它的上下文（原文）比标题更全。
· **宁缺勿猜**：规则命中才写；不命中就留空 / 留 `other`。缺标签是**可接受**的，
  错标签不可接受 —— 因为 `stage` 会经 `intel_digest.STAGE_WEIGHT` 影响重要度排序，
  错标一个 `confirmed` 就是给噪音加权。
· **只用标题判 stage**：摘要是长文本，几乎必然出现「或将/可能/计划」这类对冲词，
  拿摘要判阶段会把「已签署」误判成传闻（实测过）。阶段是**标题级**判断。
· **评论类不归类**：媒体评论（"3 Reasons to Hold…"/"What You Should Know"/行情播报）
  不是公司事件。不加这道闸，"3 AI Stocks With Revenue Growth" 会因为命中 `revenue`
  被归成 `earnings` 拿到 1.25 倍权重 —— 那是把噪音当信号。
· **可核对**：规则只读 `title`/`summary`，用户在同一张卡片上就能看到依据，不是黑箱。
· 不推断 `sentiment` / `impact`：这两项提交方覆盖率已 100%，且属于**判断**而非**归类**。

调参纪律（踩过的坑，改规则前先读）
----------------------------------
1. **短英文词必须加 `\\b`**：`ship` 会命中 `Starship`、`wins` 会命中 `winsome`。
   所有英文 token 一律 `\\bxxx\\b`。
2. **中文没有词边界，通用名词不能用**：`客户`（"跨客户数据暴露率"）、`供应`（"供应约束"）、
   `订单`（"借特斯拉订单发起挑战"）、`收入` 都会误命中。只用**专指短语**。
3. **单字不能进规则**：`已`、`拟`（命中"虚拟"）、`通过`（"通过率"）曾让准确率崩掉。
4. 改完必须跑 `tests/run_checks.py intel` —— 里面钉住了「规则不得误判」的样例。
5. **单测不够，还要对着全量标题人工抽样看一遍**：`tools/intel_probe_classify.py`
   （只读，逐类打印将要新归类的真实标题）。当初正是靠它抓出 5 处单测覆盖不到的误判：
   「How to Play X Stock Now」荐股稿、「【美股盘前】」综述、内部人交易（`COO sells $X in stock`）、
   表态稿（`坚称/驳斥`）、分析稿（`Both a Wise Offensive and Defensive Move`）。
   发现新误判 → 改规则 + **把它加进 run_checks 的反例清单**（否则下次调参又会踩回去）。
"""
from __future__ import annotations

import re
from typing import Any

# ------------------------------------------------------------------
# 评论 / 行情播报 / 分析师动作识别
# ------------------------------------------------------------------
# 命中即视为「媒体评论或行情播报」，不是公司事件：不参与归类，也不参与阶段推断。
_COMMENTARY_RE = re.compile(
    r"(?:"
    # 英文 listicle / 荐股 / 行情播报。
    # ⚠️ 数字与中心名词之间常有修饰语（"3 **AI** Stocks With…"、"5 **Top** ETFs"），
    # 所以允许一个可选前置词；否则这类标题会漏过闸门，再被 `\brevenue\b` 归成 earnings。
    r"^\s*\d+\s+(?:\S+\s+)?(?:best|great|top|reasons?|stocks?|things?|ways?|etfs?|picks?)\b"
    r"|^\s*(?:report|market chatter|exclusive)\s*:"
    r"|\bshould you (?:buy|sell|hold)\b|\bwhat you should know\b|\bwhat'?s going on\b"
    r"|\bhere'?s (?:where|what|why|how)\b|\bbetter buy\b|\bbuy, sell, or hold\b"
    r"|\bzacks\b|\bmotley fool\b|\banalyst blog\b|\bhighlights?\b"
    r"|\bstock market (?:today|now|update)\b|\bmarket (?:wrap|recap|today)\b"
    r"|\bdow (?:slides?|jumps?|rises?|falls?|closes?)\b"
    r"|\bstock (?:moves?|drops?|jumps?|rises?|falls?|slides?|surges?|soars?|pops?)\b"
    r"|\b(?:preview|recap|roundup|week in review|things to know|everything you need to know)\b"
    r"|\bhow to (?:play|trade|buy|sell|own)\b|\bwhat (?:it|this) means\b|\bcould get\b"
    r"|\bthe (?:bull|bear) case\b|\b(?:wise|smart|bold|shrewd) (?:offensive|defensive|acquisition|deal|move)\b"
    r"|\bis [a-z0-9 .()'-]{0,40}\bstock\b"
    r"|\bstock (?:looks?|at a premium|is (?:rising|falling|up|down))\b"
    r"|\b(?:bad week|worst|slump|sell-?off|rally|outlook for)\b"
    # 持仓/机构披露（13F 之类，不是公司事件）
    r"|\bstocks? (?:acquired|held|owned|bought|sold) by\b"
    r"|\b(?:sells?|buys?) \$[\d.,]+\s*(?:million|billion)?\s*in stock\b"
    r"|\b(?:wealth|asset|capital|fund|investment) management\b|\b13F\b|\binstitutional\b"
    r"|\bbillionaire\b|\bsold every\b|\bthe case for\b|\bgrowth potential\b"
    # 中文：盘点/复盘/解读/表态类
    r"|盘点|一览|复盘|十大|三大|五大|该如何|能不能买|值得买吗|涨了|跌了"
    r"|目标价|目标股价|评级(?:上调|下调)|重申.{0,6}(?:评级|目标)"
    r"|【[^】]{0,12}(?:盘前|盘后|早盘|午盘|收盘|复盘|综述|播报|盘点)】"
    r"|盘前必读|盘后必读|市场综述|收盘综述|一周综述|本周前瞻|下周前瞻|早盘播报|午间播报"
    r"|坚称|驳斥|直言|喊话|放话|回击|炮轰"
    r")",
    re.I,
)

# 分析师动作（调价/评级）单独识别：常被写进正式标题，但同样不是公司自身事件
_ANALYST_RE = re.compile(
    r"(?:目标价|目标股价|一致目标|评级|买入评级|增持评级|减持评级|"
    r"price target|overweight|underweight|outperform|upgrade[sd]?|downgrade[sd]?|"
    r"initiates? coverage|raises? (?:its )?target|cuts? (?:its )?target)",
    re.I,
)

# 阶段只判标题：摘要过长且充满对冲词（见模块 docstring）
_STAGE_TEXT_LIMIT = 300


def is_commentary(title: str, summary: str = "") -> bool:
    """是否媒体评论/行情播报/分析师动作 —— 而非公司自身事件。"""
    text = f"{title or ''} {summary or ''}"[:400]
    return bool(_COMMENTARY_RE.search(text) or _ANALYST_RE.search(text))


# ------------------------------------------------------------------
# 类别推断（只在提交方留空或给了 other 时使用）
# ------------------------------------------------------------------
# ⚠️ 顺序即优先级，先匹配先赢。刻意的排序：
#   · earnings 在 product_launch 之前 —— 「发布财报」是财报事件；
#   · regulatory 在 product_launch 之前 —— 「获 FAA 许可后发射」是监管事件；
#   · partnership 在 product_launch 之前 —— 「与 X 签署协议」优先读作合作。
_CATEGORY_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("earnings", re.compile(
        r"财报|业绩|营收|营业收入|净利|净利润|每股收益|毛利率|营业利润|"
        r"业绩指引|财报指引|全年指引|指引(?:上调|下调|维持)|"
        r"资本开支|资本支出|回购|股息|分红|派发|"
        # 财季代号：标题里出现 "FY26Q4" / "Q4 2026" 基本只可能是财报。
        # ⚠️ 必须锚定「FY+两位年」或「Q+四位年」—— 光写 `Q[1-4]` 会命中 "Q.E.P"。
        r"\bFY\d{2}\s*Q[1-4]\b|\bQ[1-4]\s*FY\d{2}\b|\bQ[1-4]\s*\d{4}\b|"
        r"\bEPS\b|\bbeats? (?:estimates|expectations|forecasts)\b|"
        r"\bmisses? (?:estimates|expectations|forecasts)\b|"
        r"\bearnings\b|\brevenue\b|\bprofit\b|\bmargins?\b|"
        r"\bguidance\b|\boutlook\b|\bbuybacks?\b|\bdividends?\b|\bquarterly results\b",
        re.I)),
    ("regulatory", re.compile(
        r"监管|反垄断|罚款|处罚|诉讼|起诉|上诉|裁定|判决|裁决|法院|法官|陪审团|禁令|"
        r"合规|法案|立法|制裁|关税|出口管制|许可证|获批|批准|审查|备案|判赔|罚金|"
        # ⚠️ 刻意不收 `不可抗力` —— 它几乎只出现在**合同/融资结构**披露里，
        # 曾把一份「Blue Owl 开发期收益率」披露误归成 regulatory。
        r"反垄断调查|监管调查|立案调查|刑事调查|"
        r"\bSEC\b|\bFTC\b|\bDOJ\b|\bFDA\b|\bFAA\b|欧盟|\bDMA\b|\bDSA\b|"
        r"antitrust|regulator|lawsuit|litigation|\bprobe\b|investigation|\bcourt\b|\bjudge\b|"
        r"\bjury\b|penalt(?:y|ies)|\bfines?\b|tariffs?|sanctions?|export control|\bfiling\b",
        re.I)),
    ("partnership", re.compile(
        r"合作|联盟|协议|合同|签约|续签|签署|签订|合资|合营|供货|授权|中标|框架协议|备忘录|"
        r"并购|收购|合并|入股|战略投资|独家供应|供应协议|"
        r"赢得.{0,10}(?:合同|订单)|获得.{0,10}(?:合同|订单)|斩获.{0,10}(?:合同|订单)|"
        r"partnership|\bagreements?\b|\bcontracts?\b|\bjoint venture\b|\bJV\b|"
        r"teams? up|collaborat|mergers?|\bacquisitions?\b|\bacquires?\b|\bacquiring\b|"
        r"\bto acquire\b|takeovers?|stake in",
        re.I)),
    ("product_launch", re.compile(
        r"发布|上市|推出|开售|发售|量产|投产|下线|揭幕|亮相|上线|开通|开幕|开工|动工|开建|"
        r"扩建|产能|工厂|产线|设施|基地|交付|出货|首飞|发射|入轨|溅落|"
        r"\blaunch(?:es|ed)?\b|\bunveil(?:s|ed)?\b|\brelease[sd]?\b|\bdebuts?\b|"
        r"roll ?out|premiere|in stores|\bships?\b|\bshipping\b|\bopens\b|\bopened\b|\bopening\b|"
        r"\bfactor(?:y|ies)\b|\bplants?\b|\bfacilit(?:y|ies)\b|\bcapacity\b|\bproduction\b",
        re.I)),
    ("model_release", re.compile(
        r"大模型|模型|算法|架构|推理|训练|参数规模|基准测试|多模态|"
        r"\bGPT\b|\bGemini\b|\bLlama\b|\bClaude\b|\bGrok\b|\bLLM\b|\bbenchmarks?\b|\bmultimodal\b",
        re.I)),
    ("personnel", re.compile(
        r"\bCEO\b|\bCFO\b|\bCTO\b|\bCOO\b|首席(?:执行官|财务官|技术官|运营官|科学家)|"
        r"高管|董事会|任命|离职|辞职|卸任|辞任|接任|加盟|裁员|换帅|"
        r"layoffs?|appoint(?:ed|ment)?|resign(?:ed|s)?|steps? down",
        re.I)),
    ("macro", re.compile(
        r"美联储|加息|降息|通胀|通缩|\bCPI\b|\bPPI\b|非农|失业率|\bGDP\b|\bPMI\b|衰退|"
        r"原油|油价|天然气|金价|铜价|汇率|国债收益率|宏观|行业景气|"
        r"\bFed\b|inflation|recession|\bmacro\b|\beconomy\b|treasury yields?",
        re.I)),
]


def infer_category(title: str, summary: str = "") -> str | None:
    """从**标题**推断事件类别。**不确定就返回 None**（调用方保留 other）。

    ⚠️ 刻意忽略 `summary`：摘要是数百字的正文，几乎总会提到别的关键词
    （实测「iPhone 17 Pro 退出销售体系」的摘要里出现"发布"，于是被误判成产品发布）。
    标题才是事件的「一句话定义」，也是用户在卡片上直接看到的依据。
    """
    text = (title or "")[:300].strip()
    if not text:
        return None
    if is_commentary(text):
        return None          # 评论类不归类（见模块 docstring）
    for cat, pat in _CATEGORY_RULES:
        if pat.search(text):
            return cat
    return None


# ------------------------------------------------------------------
# 前瞻管道阶段推断（只在提交方留空时使用）
# ------------------------------------------------------------------
# 顺序即优先级：**rumor 最先**（传闻句常含「或将/据悉」），
# **negotiating 在 confirmed 之前**（「接近敲定」不能读成已敲定）。
_STAGE_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("rumor", re.compile(
        r"传闻|据悉|据报道|据外媒|消息人士|知情人士|有消息称|或将|或可能|可能会|预计将|"
        r"尚未证实|未证实|疑似|据传|"
        r"\brumou?rs?\b|reportedly|sources say|is said to|speculat",
        re.I)),
    ("negotiating", re.compile(
        r"洽谈|磋商|谈判|正在商谈|商谈中|协商|在谈|初步协议|意向书|意向|投标|竞标|尽调|尽职调查|"
        r"接近(?:达成|敲定|签署|完成|获批|发布|推出|上市|量产|投产)|"
        r"in (?:advanced )?talks|negotiat|due diligence|letter of intent|\bLOI\b|bidding for",
        re.I)),
    ("confirmed", re.compile(
        r"签署|签订|已签|续签|敲定|(?<!未)达成|完成|正式|宣布|公告|获批|批准|生效|落地|中标|"
        r"赢得|落成|开幕|开工|动工|交割|确认|断地|破土|"
        r"\bsigned\b|\bcompleted\b|\bclosed\b|\bapproved\b|\bconfirmed\b|"
        r"\bannounce[sd]?\b|\bwins?\b|\bwon\b|\bfinali[sz]ed\b|\beffective\b|"
        r"\bcommits?\b|\bcommitted\b|\bsecures\b|\bsecured\b|\bbreaks? ground\b",
        re.I)),
]


# 对冲词：出现在标题里就**不能**判 confirmed（见 infer_stage 的「对冲词否决」）
_SPECULATIVE_RE = re.compile(
    r"有望|或将|或可能|可能会|预计|接近|拟|计划|考虑|正在|寻求|据报|据悉|传闻|"
    r"目标为|预计将|打算|酝酿|筹备|可能|should|may\b|could\b|expects?\b|plans?\b",
    re.I,
)


def infer_stage(title: str, summary: str = "") -> str | None:
    """从**标题**推断前瞻管道阶段。**不确定就返回 None**（留空是合法的）。

    ⚠️ 刻意忽略 `summary`：摘要里几乎必然出现对冲词，会把已敲定的事实误判成传闻。
    ⚠️ **对冲词否决**：标题里出现「有望 / 或将 / 预计 / 接近 / 拟 / 计划」等措辞时，
    即使命中 confirmed 关键词也**不判 confirmed** —— 不能在模糊标题上宣称「已敲定」。
    """
    text = (title or "")[:_STAGE_TEXT_LIMIT].strip()
    if not text:
        return None
    if is_commentary(text):
        return None          # 评论/分析师动作没有「管道阶段」
    for stage, pat in _STAGE_RULES:
        if not pat.search(text):
            continue
        if stage == "confirmed" and _SPECULATIVE_RE.search(text):
            return None      # 有对冲词 → 不宣称已敲定（宁缺勿猜）
        return stage
    return None


# ------------------------------------------------------------------
# 入库归一化
# ------------------------------------------------------------------
def normalize_event(raw: dict[str, Any]) -> dict[str, Any]:
    """就地补齐单条事件的 category / stage，返回同一个 dict。

    只补空：
      · `category` 缺失或为 `other` → 规则推断（推断不出就保持 other）；
      · `stage` 缺失 → 规则推断（推断不出就留空）。

    调用方必须在**计算 dedupe_key 之前**调用它 —— `dedupe_key` 含 category，
    先归一化再算 key 才能保证「同一事件重复提交」仍被判为重复。
    """
    title = str(raw.get("title") or "")
    summary = str(raw.get("summary") or "")
    cat = str(raw.get("category") or "").strip()
    if not cat or cat == "other":
        got = infer_category(title, summary)
        if got:
            raw["category"] = got
    if not str(raw.get("stage") or "").strip():
        got = infer_stage(title, summary)
        if got:
            raw["stage"] = got
    return raw
