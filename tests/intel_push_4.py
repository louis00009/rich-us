#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""第三轮补充（B 组：META / AMZN / AVGO / AMD）——监管罚则、基建成本、估值与竞争。"""
from __future__ import annotations

import json
import urllib.request

BASE = "http://127.0.0.1:8787/api/intel/bridge"
TOKEN = "qdintel_6637c0635482abf471473cdb1825db02"
AGENT = "workbuddy"


def post(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Intel-Token": TOKEN},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


EVENTS: list[dict] = [
    # ===================== META =====================
    {
        "symbol": "META",
        "occurred_on": "2026-08-06",
        "category": "regulatory",
        "title": "新墨西哥州法院认定 Meta 构成「公共妨害」，判赔 5.67 亿美元，该州累计罚则达 9.42 亿美元",
        "summary": (
            "新墨西哥州法官 Bryan Biedscheid 于 2026-08-06 判令 Meta 支付 5.67 亿美元设立基金以消除「公共妨害」，"
            "加上 3 月第一阶段陪审团裁定的 3.75 亿美元民事罚则，该州案累计达 9.42 亿美元。"
            "资金分配：4.2 亿用于治疗、9000 万用于筛查与评估、3300 万用于宣传与预防、2400 万用于其他成本，覆盖期 5 年。"
            "法院驳回了由 Meta 出资新建社区医疗中心的方案（认为超出消除当前危害所需），也认定 15 年资金期过长；"
            "并因其他社交媒体公司同样负有责任，按 Meta 的市场份额调低了金额。"
            "法官认定：「新墨西哥州正处于一场影响全州公共健康与公共安全的青少年心理健康危机之中，"
            "而 Meta 的平台是这场危机的重大促成原因」，并把 Meta 比作排放有害污染的工厂——"
            "广告与内容是其产品，而青少年的心理伤害与性剥削则是必须被消除的污染。"
            "判决指出 Meta「实施了旨在最大化所有用户特别是青少年用户参与度与使用时长的功能」。"
            "Meta 表示不同意裁决并将上诉。该案源自州总检察长 Raúl Torrez 2023 年提起的诉讼，"
            "是首次有州政府就儿童安全问题成功起诉 Meta。"
        ),
        "impact": 5,
        "sentiment": "negative",
        "source_name": "Ars Technica / PEOPLE / Techpoint Africa（引述 BBC、The Times）",
        "source_url": "https://arstechnica.com/tech-policy/2026/08/meta-ordered-to-pay-567m-to-treat-youth-mental-health-problems-it-helped-create/",
    },
    {
        "symbol": "META",
        "occurred_on": "2026-08-06",
        "category": "regulatory",
        "title": "法院一并命令未成年人保护强制措施：FB+IG 合计每月 90 小时上限、未成年人隐藏点赞数、夜间禁用推送",
        "summary": (
            "除罚款外，法院还命令 Meta 实施一系列护栏：禁止向成年人推荐 18 岁以下用户的账户，"
            "禁止成年人向其不认识的未成年人发送消息；禁止未成年人收发裸照；"
            "对从事儿童性剥削的成年人实行「一次即出局」的永久封禁；取消未成年用户的公开点赞数；"
            "在 22:00–07:00 以及上课时间（周末除外）禁用推送通知；"
            "对 18 岁以下用户在 Facebook 与 Instagram 上设置每月 90 小时的累计使用上限（约合日均 3 小时）；"
            "并要求 Meta 每半年就落实情况报告一次进展。"
            "Meta 此前已在 2026 年 5 月推出 AI 驱动的年龄验证技术，并规定平台用户须年满 13 岁，"
            "因此其中部分措施公司称已实施。公司在美国仍面临数千起同类诉讼。"
        ),
        "impact": 4,
        "sentiment": "negative",
        "source_name": "Techpoint Africa / Newz（引述法院命令）",
        "source_url": "https://techpoint.africa/news/meta-fined-nearly-1bn",
    },
    {
        "symbol": "META",
        "occurred_on": "2026-08-26",
        "category": "regulatory",
        "title": "Meta 同意支付最高 180 亿美元与 29 个州和解青少年诉讼，并承诺每日 2 小时未成年人自动限时",
        "summary": (
            "Meta 同意支付最高 180 亿美元（逾 130 亿英镑）并修改应用，以了结由 29 个州（含加州、纽约）"
            "于 2023 年提起、指控其违反儿童在线保护法的诉讼。和解属双方协议，任何一方均未承认过错。"
            "主审法官 Yvonne Gonzalez Rogers 表示可能会批准该和解，并已中止原定持续六周的审判。"
            "和解中包含的产品变更（据加州政府高级律师）：18 岁以下用户每日 2 小时自动使用上限，仅家长可解除；"
            "午夜至 06:00 自动夜间屏蔽，仅家长可解除；22:00–07:00 与上课时段自动屏蔽通知；"
            "改进青少年举报有害内容的渠道，并要求 Meta 在 6 小时内响应其中 90%；"
            "禁止向未成年人显示点赞或回应数量；为未成年用户提供非个性化 Feed 选项。"
            "Meta 称这是「重要的一步」，希望为行业设立新标准，并呼吁 TikTok 与 YouTube 作出同样改变。"
            "背景：英国政府正推动 16 岁以下社交媒体禁令，法国将从 2027 年 1 月起实施类似禁令，"
            "澳大利亚自 2024 年起已禁止 16 岁以下使用社交媒体。"
        ),
        "impact": 5,
        "sentiment": "negative",
        "source_name": "BBC Newsround",
        "source_url": "https://www.bbc.co.uk/newsround/articles/c5yl8dzyq1jo",
    },
    {
        "symbol": "META",
        "occurred_on": "2026-08-10",
        "category": "macro",
        "title": "AI 成本错配：三大厂全年资本开支指引合计 5450–5700 亿美元，Meta 因缺云业务被称「财务最紧绷」",
        "summary": (
            "Alphabet、亚马逊与 Meta 在 2026Q2 均报出强劲的广告收入增长，但资本开支增速更快："
            "三家全年资本开支指引合计约 5450–5700 亿美元（Alphabet 1950–2050 亿、Meta 1300–1450 亿、亚马逊 2200 亿）。"
            "Meta 的问题更突出——Q2 营收 +28% 至 608 亿，但成本与费用 +55% 至 420 亿，增速为营收的两倍，"
            "其中大部分归因于 AI 开发，另含 24 亿美元法律费用（单季法律支出约为 Reddit 全季营收的三倍）。"
            "结构性难点在于：与 Alphabet 和亚马逊不同，Meta 没有云业务来为其 AI 投资创造替代性收入来源，"
            "其 AI 投资的回报「完全依赖广告销售」。《华尔街日报》记者 Asa Fitch 称 Meta 是"
            "「大型科技公司中财务最紧绷的一家」。扎克伯格的回应是 AI 正在改善用户体验、提升广告主效果、"
            "并帮助团队更快交付；他同时认为存在向广告主出售商业代理与算力的「大型企业机会」，"
            "并押注 Muse 系列图像与视频生成工具创造「近乎无限的个性化内容」；"
            "新版 AI 助手的每日互动人数增长 60%（公司未说明「互动」的定义与基数）。"
        ),
        "impact": 4,
        "sentiment": "negative",
        "source_name": "PivotNews（引述 WSJ 与三家公司财报）",
        "source_url": "https://pivotnews.ai/five/big-tech-s-ai-costs-have-surged-can-ad-revenues-keep-up",
    },

    # ===================== AMZN =====================
    {
        "symbol": "AMZN",
        "occurred_on": "2026-07-30",
        "category": "other",
        "title": "财报会：Q2 入账 6 亿美元关税退税，关税成本主要由供应商承担且基本未转嫁消费者",
        "summary": (
            "亚马逊在 Q2 财报电话会说明关税处理：本季度入账 6 亿美元关税退税。"
            "退税总额有限主要有两点原因：一是公司提前批量采购、前置仓储，尽可能规避关税成本；"
            "二是平台上绝大多数商品的供应商为实际进口主体，关税由供应商承担。"
            "管理层称若关税上涨带来额外成本，公司基本自行消化、并未转嫁给消费者；"
            "第三方调研机构 Profitero 数据显示平台商品平均定价较其他零售商低 14%。"
            "公司仅能追踪到极小部分把进口成本转嫁给消费者的场景，收到对应退税后会主动联系相关客户自动退款；"
            "其余退税资金将持续投入以维持平台的低价优势，与其他大型零售商策略一致。"
            "对照苹果：其 FY26Q3 同样计入关税退款，贡献约 2 个百分点毛利率与每股 0.11 美元。"
        ),
        "impact": 2,
        "sentiment": "neutral",
        "source_name": "财联社（亚马逊 2026Q2 财报电话会实录）",
        "source_url": "https://www.cls.cn/detail/2442056",
    },
    {
        "symbol": "AMZN",
        "occurred_on": "2026-07-30",
        "category": "earnings",
        "title": "AWS Q2 经营利润率升至 39%；Bedrock 单季客户总支出超过此前所有季度总和",
        "summary": (
            "在 Q2 财报电话会上，摩根大通分析师 Doug Anmuth 就 AI 工作负载短期压低云业务利润率的普遍看法，"
            "追问 AWS 39% 营业利润率的驱动因素及能否长期维持；同时向 CEO 提问："
            "在 Amazon Bedrock 本季度客户总支出已超过此前所有季度总和的情况下，"
            "从全栈产品布局角度看亚马逊是否必须自研顶尖前沿大模型。"
            "背景数据：AWS Q2 收入 422.32 亿美元（+36.7%，18 个季度最快），经营利润 166.21 亿，"
            "经营利润率约 39.4%（同比 +6.5pct），显著高于市场预期的约 34%；"
            "AWS 贡献公司约 61% 的经营利润，是公司利润率改善的核心引擎。"
            "需注意 CFO 已提示：随着 MI450 类低毛利 AI 产品放量，云厂商普遍面临毛利率结构下移的压力。"
        ),
        "impact": 3,
        "sentiment": "positive",
        "source_name": "财联社（亚马逊 2026Q2 财报电话会实录）",
        "source_url": "https://www.cls.cn/detail/2442056",
    },
    {
        "symbol": "AMZN",
        "occurred_on": "2026-09-10",
        "category": "regulatory",
        "title": "俄亥俄州数据中心税收优惠面临变数：州长 5 月暂停新豁免申请，超 10 个州在重新审视同类激励",
        "summary": (
            "亚马逊自 2015 年起在俄亥俄州累计投资近 400 亿美元建设数据中心（为累计基础设施投资口径），"
            "去年缴纳房产税与费用约 1100 万美元。该州面向数据中心设备的销售税豁免在 2025 年耗费州财政逾 15 亿美元，"
            "远高于此前约 1.36 亿美元的估计；州长 Mike DeWine 已于 5 月暂停新的豁免申请，交由议员审议。"
            "部分议员主张直接废除该豁免，两党提案则要求数据中心承担更多由其用电需求带来的电网升级成本。"
            "摩根士丹利的 Ariana Salvatore 表示「最大的争论毫无疑问是数据中心反弹」，并把俄亥俄列为"
            "开发可能变得更有条件的州之一；据报道超过 10 个州正在重新审视类似激励。"
            "对亚马逊的传导路径：服务器与网络设备的投资回收期公司称不到 3 年，数据中心可运行 30 年以上，"
            "而销售税减免、电力基础设施与建设成本正处于这些回报率的底层——"
            "每增加一项税收、电网分摊或融资成本，都会抬高新增容量的回报门槛。"
        ),
        "impact": 3,
        "sentiment": "negative",
        "source_name": "Invezz",
        "source_url": "https://invezz.com/in/news/2026/09/10/amazons-dollar40-billion-ohio-ai-bet-faces-a-tax-shock-what-it-means-for-the-stock/",
    },
    {
        "symbol": "AMZN",
        "occurred_on": "2026-09-09",
        "category": "other",
        "title": "完成首次英镑债券发行募资 42.5 亿英镑（约 57.6 亿美元），今年超大厂发债已超 2000 亿美元",
        "summary": (
            "亚马逊于周三完成其首次英镑债券发行，募集 42.5 亿英镑（约合 57.6 亿美元）。"
            "今年超大厂已累计发行超过 2000 亿美元债务，为 AI 数据中心建设融资。"
            "这并不意味着亚马逊的资产负债表承压——公司 TTM 经营现金流达 1614 亿美元（同比 +33%），"
            "问题在于融资成本叠加地方税收与电网分摊后，新增容量的回报门槛在同步抬升。"
            "D.A. Davidson 分析师 Gil Luria 就曾警告不要无限外推 AWS 增长，"
            "称「AWS 年营收达 1 万亿美元」的预测属于「大胆的猜测」，把今天的增速外推到多年后「不只是雄心勃勃」。"
        ),
        "impact": 2,
        "sentiment": "neutral",
        "source_name": "Invezz（引述 MarketWatch 与 D.A. Davidson）",
        "source_url": "https://invezz.com/in/news/2026/09/10/amazons-dollar40-billion-ohio-ai-bet-faces-a-tax-shock-what-it-means-for-the-stock/",
    },
    {
        "symbol": "AMZN",
        "occurred_on": "2026-07-02",
        "category": "product_launch",
        "title": "Amazon Leo（原 Project Kuiper）宣布年内启动初始卫星互联网服务，在轨卫星达 390+",
        "summary": (
            "亚马逊 Leo 业务与产品战略副总裁 Chris Weber 于 2026-07-02 表示，"
            "公司已完成足够次数的发射以支持年内启动初始服务（此前目标为 2026 年年中）。"
            "第 14 次发射（ULA Atlas V，自佛罗里达）把 29 颗卫星送入轨道，使在轨数量超过 390；"
            "据哈佛天文学家 Jonathan McDowell 统计，2025 年 4 月以来累计发射 398 颗、在轨 394 颗。"
            "初始服务将先在南北极附近纬度提供连续覆盖，随卫星增加逐步向赤道扩展；"
            "终端尺寸从笔记本大小到更大功率版本不等，面向消费者、政府与企业（含航空公司）。"
            "项目规模：最终目标超过 3,200 颗（授权 3,236 颗），已预订约 100 次火箭发射、"
            "发射合同金额至少 820 亿美元（Vulcan、Atlas V、Ariane 6、New Glenn、Falcon 9）。"
            "监管风险：FCC 里程碑要求 2026-07-30 前在轨 1,618 颗（50%），"
            "亚马逊已于 2026-01-29 提交申请（SAT-MOD-20260129-00065）请求 24 个月延期或豁免，"
            "理由是运载火箭可得性与供应链受限，并估计届时可部署约 700 颗；FCC 尚未裁决。"
            "若未获批，授权可能被削减至实际在轨数量，并触发许可保证金没收条款。"
            "参考：SpaceX 星链在轨约 1 万颗，已服务 160 多个国家；"
            "亚马逊的差异化在于与 AWS 的整合以及对企业客户的吸引力。"
        ),
        "impact": 3,
        "sentiment": "positive",
        "source_name": "The News / Digital Trends / Morning Overview（引述 Jonathan McDowell 统计）",
        "source_url": "https://www.thenews.com.pk/amp/1407930-amazon-to-launch-initial-internet-service-as-satellite-fleet-nears-400",
    },

    # ===================== AVGO =====================
    {
        "symbol": "AVGO",
        "occurred_on": "2026-09-13",
        "category": "regulatory",
        "title": "欧盟委员会就博通收购 VMware 后的许可模式改造征求意见，构成新的监管悬顶",
        "summary": (
            "据 MT Newswires（经 Zonebourse 转载）2026-09-13 报道，"
            "欧盟委员会正就博通在收购 VMware 之后对许可模式的改造征求各方意见，"
            "这成为继客户流失风险之后的第二个监管关注点。"
            "结合此前的竞争性情报：收购后 VMware 定价策略已引发显著的客户流失风险——"
            "部分组织报告在新的订阅捆绑模式下价格上涨 800% 至 1500%，"
            "核心许可约每核每年 190 美元并设 72 核最低门槛（约 1 万美元/年）；"
            "从永久许可转向订阅消除了客户原有的期权价值，加速了对 Nutanix、Red Hat OpenShift 与公有云迁移的评估。"
            "博通的对冲动作包括与 NEC 等长期 GSIs 深化合作、在 Kubernetes 生态上与 F5、Kong、Tigera 建立伙伴关系。"
            "判读：若欧盟介入，VMware 这一约占公司营收 30%、经营利润率约 84% 的高毛利板块将同时面临"
            "定价合规与续约率双重压力。"
        ),
        "impact": 3,
        "sentiment": "negative",
        "source_name": "ad-hoc-news（引述 MT Newswires / Zonebourse）",
        "source_url": "https://www.ad-hoc-news.de/boerse/news/corporate-news/broadcom-stock-edges-higher-as-dividend-and-ai-chip-demand-support-outlook/70095513",
    },
    {
        "symbol": "AVGO",
        "occurred_on": "2026-09-03",
        "category": "other",
        "title": "分析师密集上调目标价：Rosenblatt 与 Cantor 均看 600 美元，一致目标约 509 美元",
        "summary": (
            "Rosenblatt Securities 于 2026-09-03 启动覆盖，给予买入评级与 600 美元目标价；"
            "同日 Cantor Fitzgerald 将目标价由 525 美元上调至 600 美元并维持增持；"
            "Piper Sandler 于 9 月 13 日启动覆盖，目标价 460 美元（较当时约 362 美元有约 27% 上行）。"
            "反向动作同样存在：Erste Group 于 7 月 7 日由买入下调至持有，Macquarie 于 6 月 4 日由跑赢下调至中性。"
            "汇总口径：MarketBeat 一致目标价约 509 美元、评级「适度买入」；"
            "24/7 Wall St 口径平均目标价 531.85 美元；Eulerpool 口径平均 506.50、中位 520 美元。"
            "预期差解释：半导体专业分析师 Ben Bajarin 与 Jay Goldberg 认为管理层给出的 FY2027 约 1150 亿美元"
            "应视为「地板」，市场内部低语数字约 1500 亿——这正是财报周股价仍跌约 4% 的原因。"
        ),
        "impact": 3,
        "sentiment": "positive",
        "source_name": "ad-hoc-news / Eulerpool（引述 MarketBeat、24/7 Wall St、Motley Fool）",
        "source_url": "https://www.ad-hoc-news.de/boerse/news/corporate-news/broadcom-stock-gains-as-dividend-and-ai-results-hold/70131291",
    },
    {
        "symbol": "AVGO",
        "occurred_on": "2026-09-21",
        "category": "other",
        "title": "季度股息 0.65 美元/股 9 月 30 日派发；股价距年内高点约 -31%，Q4 一致预期 EPS 3.82 美元",
        "summary": (
            "博通宣告季度现金股息 0.65 美元/股，2026-09-30 派发、09-21 除息，年化 2.60 美元，"
            "按当时股价计收益率约 0.7%；2024 年 7 月曾完成 1:10 拆股。"
            "股价与估值：9 月 11 日收 361.99 美元，9 月 18 日收 357.67 美元（+2.99%），"
            "当日区间 347.30–363.28；52 周区间 289.96–495.00；市值约 1.71 万亿美元；"
            "年内涨幅约 3.3%，但距年内高点约 495 美元已回落逾 30%，过去一月跌约 5.8%。"
            "Q3（截至 8 月 2 日）EPS 3.32 美元，超出一致预期 3.22 美元 0.10 美元；"
            "营收 295.9 亿美元 vs 预期 292.4 亿，同比 +85.5%；净利率 42.94%。"
            "下一次财报预计 2026-12-10（截至 10 月的季度），Zacks 一致预期 EPS 3.82 美元（同比 +95.9%）。"
        ),
        "impact": 2,
        "sentiment": "neutral",
        "source_name": "ad-hoc-news / Eulerpool（引述 MarketBeat、Zacks）",
        "source_url": "https://www.ad-hoc-news.de/boerse/news/corporate-news/broadcom-stock-gains-as-dividend-and-ai-results-hold/70131291",
    },
    {
        "symbol": "AVGO",
        "occurred_on": "2026-09-06",
        "category": "macro",
        "title": "竞争加剧：Marvell 扩大与 Google 的定制 AI 硅片合作；关税环境下定制 ASIC 供应链亦受影响",
        "summary": (
            "路透报道称博通预计到 2027 年 AI 芯片收入将超过 1000 亿美元；"
            "与此同时 Marvell 近期扩大了与 Google 围绕定制 AI 硅片及其他基础设施组件的合作。"
            "这提示：即便博通在定制 ASIC 赛道领先，Marvell 正在赢下增量的 AI 网络与定制硅片订单，"
            "市场存在被分段的可能。更宏观的产业变量是关税——"
            "AI 供应链正从「最低成本的全球供应链」转向「更昂贵但地理多元的供应链」，"
            "先进封装、HBM、基板等关键环节仍高度集中于亚洲，"
            "以美国本土晶圆产能替代并不自动形成完整的本土 AI 供应链。"
            "对博通这类「卖铲人」的净影响取决于其能否把更高的制造与封装成本转嫁给超大规模客户，"
            "而其管理层已明确表示定制加速器的成本「不到通用 GPU 的一半」，定价能力是其核心护城河之一。"
        ),
        "impact": 3,
        "sentiment": "negative",
        "source_name": "USnewsSphere（引述 Reuters）",
        "source_url": "https://usnewssphere.com/u-s-tariffs-and-the-ai-supply-chain-which-ame",
    },

    # ===================== AMD =====================
    {
        "symbol": "AMD",
        "occurred_on": "2026-08-26",
        "category": "other",
        "title": "Raymond James 上调 AMD 目标价至 641 美元并升至强烈买入：EPYC 服务器份额已达 34.5%",
        "summary": (
            "Raymond James 分析师 Simon Leopold 将 AMD 的一年目标价由 565 美元上调至 641 美元，"
            "评级由「跑赢」升至「强烈买入」。理由是他认为 AMD 拥有盈利杠杆、数据中心业务定位与份额增长的最佳组合，"
            "依据包括 Q2 数据中心分部收入同比 +107%，以及 EPYC 服务器 CPU 份额升至 34.5%（对比 Intel 的 65.5%）。"
            "他还预计到 2030 年全球服务器 CPU 市场将达 2010 亿美元、年增速约 44%，"
            "并认为 AMD 有望在 2027 年于服务器收入上超越 Intel；"
            "此外 agentic AI 需要更强的 CPU 协调能力，这一趋势可能强化 AMD 在企业计算领域的地位。"
        ),
        "impact": 3,
        "sentiment": "positive",
        "source_name": "Pintu（引述 TheStreet）",
        "source_url": "https://pintu.co.id/en/news/290651-amd-stock-price-today-8-september-2026",
    },
    {
        "symbol": "AMD",
        "occurred_on": "2026-09-06",
        "category": "macro",
        "title": "英伟达发布首款独立 CPU（今年目标 200 亿美元）并以 129 亿美元收购 Hugging Face",
        "summary": (
            "英伟达推出其首款独立 CPU 处理器，今年销售目标 200 亿美元；"
            "同时以 129 亿美元收购开源 AI 平台 Hugging Face。"
            "黄仁勋表示「在 Hugging Face 上构建或通过其部署并不强制要求英伟达算力」，"
            "但多位分析师认为此举仍可能给英伟达带来 AI 开发者生态的分发优势，"
            "进而挤压 AMD 与 Intel 在传统 CPU 市场的地位。"
            "AMD 的差异化路径是以总拥有成本（TCO）为核心的「开放联盟」："
            "Helios 机架平台宣称每美元 token 数比竞品高约 30%、每机架 HBM 容量高 50%，"
            "且全栈基于以太网与开放标准，便于云厂商沿用既有运维工具链。"
        ),
        "impact": 4,
        "sentiment": "negative",
        "source_name": "Pintu（引述 Motley Fool 与 24/7 Wall St）",
        "source_url": "https://pintu.co.id/en/news/290651-amd-stock-price-today-8-september-2026",
    },
    {
        "symbol": "AMD",
        "occurred_on": "2026-09-13",
        "category": "other",
        "title": "分析师目标价集体上修：一致目标由 500.40 升至 616.51 美元，Stifel 看 635、Piper 看 600",
        "summary": (
            "Piper Sandler 分析师 David O'Connor 启动覆盖，给予买入评级与 600 美元目标价，"
            "核心逻辑是 agentic AI 将成为 AMD CPU 销售的主要驱动力，并预期其在该趋势下继续抢占份额；"
            "Stifel Nicolaus 分析师 Ruben Roy 重申买入、目标价 635 美元。"
            "汇总：据 TIKR，AMD 的 12 个月一致目标价从 6 月底的 500.40 美元升至 9 月中旬的 616.51 美元，"
            "预估份数由 48 增至 50，买入评级由 37 增至 39。"
            "估值背景：AMD 过去一年上涨逾 234%，远期市盈率约 74.2 倍；"
            "对比英伟达市值 5.37 万亿美元、追踪 PE 约 45 倍、单季数据中心收入 890.2 亿美元；"
            "Intel 市值 5740.7 亿美元，其数据中心与 AI 部门增长 59% 至 62.6 亿美元。"
        ),
        "impact": 3,
        "sentiment": "positive",
        "source_name": "10x Wealth Report / Linxi News（引述 TipRanks、TIKR、Motley Fool）",
        "source_url": "https://10xwealthreport.com/amd-stock-gains-as-analysts-lift-ai-expectations-and-price-targets",
    },
    {
        "symbol": "AMD",
        "occurred_on": "2026-09-14",
        "category": "macro",
        "title": "9 月 14 日 AI 股集体回调：Anthropic / OpenAI / xAI 高管警告引发抛售，10 年期美债收益率一度破 5%",
        "summary": (
            "2026-09-14，来自 Anthropic、OpenAI 与 xAI 的高管就 AI 发展速度公开发出警告，"
            "触发 AI 相关股票的普遍性抛售，AMD 单日跌超 4%；同期英伟达跌 3.4%，"
            "费城半导体指数盘中一度下跌 6%。宏观层面，10 年期美国国债收益率一度突破 5%，"
            "为 2023 年以来首次，发生在市场普遍预期美联储加息之前。"
            "AMD 随后于 9 月 17 日反弹逾 7% 至约 549 美元，说明这轮冲击更多来自宏观情绪与 AI 叙事，"
            "而非对公司自身轨迹的重新评估。值得注意的是 AMD 管理层自身也在同期上调了长期 TAM 假设，"
            "把 2030 年高性能与 AI 计算整体市场预期由约 2 万亿美元提高至最高 3 万亿美元，"
            "消息当日股价一度上涨约 6%。"
        ),
        "impact": 3,
        "sentiment": "negative",
        "source_name": "Linxi News（引述 TIKR 与市场数据）",
        "source_url": "http://news.linxi.com.au/news/amd-shares-rebound-as-analysts-lift-price-targets-despite-ai-sector-jitters",
    },
    {
        "symbol": "AMD",
        "occurred_on": "2026-09-17",
        "category": "macro",
        "title": "Nebius 宣布涨价：英伟达 GPU 上调 17%–21%，AMD EPYC Genoa CPU 上调 25%",
        "summary": (
            "Neocloud 运营商 Nebius 宣布对其算力栈全线涨价：英伟达 GPU 价格上调 17% 至 21%，"
            "而 AMD 的 EPYC Genoa CPU 价格上调 25%——后者涨幅更大，被市场解读为 AI 算力需求强劲的直接信号，"
            "也侧面印证 CPU 在 AI 集群中的价值正在被重新定价。"
            "消息推动 AMD 于 2026-09-17 收涨 6.36%（+32.59 美元），盘后再涨 1.68%，"
            "股价约 554 美元，逼近其历史高点 584.73 美元；同日英伟达涨 2.54%、Intel 涨 7.67%、美光涨 5.50%。"
            "这是本轮 AI 基建扩张中少见的「算力提价」信号，与超大规模厂商自由现金流承压形成对照。"
        ),
        "impact": 3,
        "sentiment": "positive",
        "source_name": "Watcher Guru",
        "source_url": "https://watcher.guru/news/amd-stock-nearing-all-time-high-why-is-the-stock-up-today",
    },
    {
        "symbol": "AMD",
        "occurred_on": "2026-09-21",
        "category": "earnings",
        "title": "财务质量信号：毛利率稳定在 56% 但自由现金流利润率从 25% 腰斩至 13.5%",
        "summary": (
            "毛利率：AMD 过去四个季度毛利率稳定在 54.5%–56.8% 区间，2026 年 6 月季度为 56.02%，"
            "尚无明显结构性损伤。但 CFO Jean Hu 已提示，随着 MI450 在 2026Q4 至 2027 年放量，"
            "毛利率将小幅下台阶——原因是高毛利的 EPYC 服务器 CPU 与较低毛利的 Instinct GPU 之间的结构差异。"
            "更值得警惕的是现金流：自由现金流利润率从 2026Q1 的 25.0% 近乎腰斩至 Q2 的 13.5%，"
            "主因是为锁定服务器 CPU 产能而进行的设备采购与产能委托安排——"
            "这些成本先于 Helios 与 Venice 的收入体现在现金流量表上。"
            "因此未来一两个季度的自由现金流表现，将是判断「营收增长能否转化为现金」这一核心假设是否成立的关键。"
            "估值：股价过去一年涨逾 234%，远期 PE 约 74.2 倍；"
            "市场一致预期正常化 EPS 将从 2026 年的 7.58 美元升至 2030 年的逾 45 美元。"
            "另有 24/7 Wall St 给出偏保守的 12 个月目标价 510.66 美元（较当时 559.82 美元有约 8.8% 下行）与持有评级，"
            "显示市场对「高估值 vs 高增长」的分歧显著。"
        ),
        "impact": 3,
        "sentiment": "negative",
        "source_name": "Linxi News / 10x Wealth Report / Koran Pangkep（引述 24/7 Wall St）",
        "source_url": "http://news.linxi.com.au/news/amd-shares-rebound-as-analysts-lift-price-targets-despite-ai-sector-jitters",
    },
]


def main() -> None:
    print("events:", json.dumps(post("/events", {"agent": AGENT, "events": EVENTS}), ensure_ascii=False))
    print("done:", json.dumps(post("/done", {"agent": AGENT,
          "note": "第三轮补充完成：新增 35 条事件（分 A/B 两组提交），覆盖财务质量、监管罚则、"
                  "安全事件、基建成本、估值与竞争，全部带真实来源。"}), ensure_ascii=False))


if __name__ == "__main__":
    main()
