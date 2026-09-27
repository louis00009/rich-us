#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""第二轮补充：把最近 90 天遗漏的关键节点补齐（自研芯片 / 算力基建 / 监管诉讼 / 人事 / 产品）。"""
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
    # ===================== MSFT =====================
    {
        "symbol": "MSFT",
        "occurred_on": "2026-09-01",
        "category": "product_launch",
        "title": "自研 Maia 200 已在爱荷华与亚利桑那数据中心投产，Maia 300 计划 2026 年秋季发布",
        "summary": (
            "Maia 200（2026-01-26 发布，TSMC 3nm，约 1400 亿晶体管，216GB HBM3e、7TB/s 带宽，约 750W）已在爱荷华与亚利桑那的数据中心部署，"
            "现承载 Microsoft 365 Copilot 与 OpenAI 模型的推理负载，成为微软首个大规模商用自研 AI 硅片。"
            "微软称其 FP4 性能约 10 PFLOPS、约为亚马逊 Trainium3 的 3 倍，FP8 性能优于 Google TPU v7，"
            "每美元性能较上一代 Azure 机队硅片提升约 30%。后续产品 Maia 300 正在设计中，"
            "据报道微软正与台积电洽谈 30 万颗以上的产能、目标 2027 年交付，规模明显大于 Maia 200。"
            "注意：以上均为微软自行公布的基准数据，跨 Trainium3 / TPU v7 / Maia 200 的独立同口径对比仍然稀缺。"
        ),
        "impact": 4,
        "sentiment": "positive",
        "source_name": "The Index Today / Crypto Briefing（引述微软官方博客与高管表态）",
        "source_url": "https://www.theindextoday.com/?p=1611/",
    },
    {
        "symbol": "MSFT",
        "occurred_on": "2026-08-15",
        "category": "partnership",
        "title": "Anthropic 与微软洽谈在 Azure 上用 Maia 运行 Claude 推理，微软并已向其推介未发布的 Maia 300",
        "summary": (
            "据 CNBC 报道（始于 2026 年 5 月、至 9 月仍在延续），Anthropic 与微软处于早期洽谈阶段，"
            "拟租用搭载 Maia 200 加速器的 Azure 服务器来跑 Claude 推理；微软随后进一步向其推介尚未发布的 Maia 300。"
            "双方均未证实，亦未签署任何协议、无商业条款与多年承诺。"
            "若成行，将是自研推理硅片首次在前沿模型上实现生产级外部部署，对微软硅片经济学构成关键验证。"
            "但 Anthropic 同时在自建芯片设计团队，且已锁定 AWS Trainium 十年协议与 Google TPU 容量，"
            "Maia 只会是其「多云对冲」策略中的一条线。注：本条为持续状态更新，取 2026-08-15 作为观察日。"
        ),
        "impact": 3,
        "sentiment": "neutral",
        "source_name": "ai|expert / Future Technology（引述 CNBC 原始报道）",
        "source_url": "https://futuretechnologyhq.com/anthropic-claude-microsoft-maia-chip-deal",
    },
    {
        "symbol": "MSFT",
        "occurred_on": "2026-08-29",
        "category": "partnership",
        "title": "挪威 Kvandal「Stargate Norway」数据中心全部容量由微软承接，OpenAI 不再作为锚定客户",
        "summary": (
            "挪威 Aker ASA 在 2026 年一季度股东信中披露，原本以 OpenAI 为意向锚定客户、打着 Stargate Norway 名号的 Kvandal 场址，"
            "其全部容量已由微软承租，并在既有承诺之外追加 3 万颗 NVIDIA Vera Rubin GPU；Aker 将与微软相关的承诺规模标注为 62 亿美元。"
            "该场址一期原规划 230MW、并有意追加 290MW，目标 2026 年底前部署 10 万颗 NVIDIA GPU。"
            "截至 2026-08-29，OpenAI 未发布任何更新公告确认其在 Kvandal 保留容量——因此 OpenAI 早前的目标只能标注为「先前宣布」，"
            "而非当前交付计划。物理场址仍在开发中，但公开披露的全部商业容量已属微软，属典型的算力重分配而非项目取消。"
        ),
        "impact": 3,
        "sentiment": "positive",
        "source_name": "Stargate Project 追踪（stargate.how，援引 Aker ASA 股东信）",
        "source_url": "https://stargate.how/news/what-happened-stargate-norway",
    },
    {
        "symbol": "MSFT",
        "occurred_on": "2026-08-01",
        "category": "other",
        "title": "俄亥俄 Licking County 数据中心群复工：17 栋楼、约 869MW，目标 2029 年前投运",
        "summary": (
            "微软在俄亥俄州 Licking County（Heath / Hebron / New Albany）的数据中心建设在 2025 年暂停后复工，"
            "据卫星影像显示 2026 年 6 月已出现 renewed 场地清理与平整，合计规划 17 栋建筑、约 869MW，目标 2029 年前投运。"
            "该复工说明即便资金充裕的超大规模厂商，也会因容量需求、设计或市场预期变化而调整施工节奏。"
            "同期报道的行业信号：约四分之一在建数据中心容量涉及自备电源方案，覆盖 59 个追踪项目、约 90GW。"
        ),
        "impact": 2,
        "sentiment": "neutral",
        "source_name": "remio.ai（整理自 2026 年 8 月数据中心项目追踪）",
        "source_url": "https://www.remio.ai/post/10-data-center-projects-show-power-is-the-real-constraint-on-ai-growth",
    },

    # ===================== GOOGL =====================
    {
        "symbol": "GOOGL",
        "occurred_on": "2026-08-05",
        "category": "personnel",
        "title": "DeepMind 领导层地震：Hassabis 转任主席，效力 27 年的 Jeff Dean 离职创办 Discovery Loop，股价盘中跌约 5%",
        "summary": (
            "谷歌于 2026 年 8 月 5–6 日宣布 AI 部门重大人事调整：DeepMind 联合创始人兼 CEO Demis Hassabis 卸任日常运营职务，"
            "转任 Google DeepMind 主席兼 Alphabet 首席科学家（继续领导 Isomorphic Labs，聚焦 AI 安全与治理）；"
            "Google DeepMind CTO 兼 Alphabet 首席 AI 架构师 Koray Kavukcuoglu 升任高级副总裁，接管 Gemini 模型研发、前沿研究、"
            "Gemini App 与开发者生态等全部运营核心。与此同时，1999 年加入、参与 MapReduce / BigTable / TensorFlow 的 Jeff Dean 离职，"
            "创办公益公司 Discovery Loop（目标是用自驱动 AI 系统自动化机器学习、科学与工程），"
            "随行的还有 Quoc V. Le、Oriol Vinyals、Sanjay Ghemawat 三位资深研究员；Alphabet 仍是该新公司的创始投资人与云伙伴。"
            "消息公布后 Alphabet 股价盘中一度跌约 5%（FT 报道），市值蒸发数百亿美元。"
            "同期有报道称 Sergey Brin 重返一线亲自过问 Gemini。"
        ),
        "impact": 5,
        "sentiment": "negative",
        "source_name": "The Agent Times / The Index Today（引述谷歌官方博客与 FT）",
        "source_url": "https://theagenttimes.com/agents/article/hassabis-moves-to-chair-at-google-deepmind-as-jeff-dean-exit-82bf778d",
    },
    {
        "symbol": "GOOGL",
        "occurred_on": "2026-06-30",
        "category": "partnership",
        "title": "TPU 从「自用」转向「外售」：6 月首批硬件交付，Anthropic 相关 1GW 由特殊目的实体支付 350 亿美元",
        "summary": (
            "SemiAnalysis 估算 TPU 系统按总额法确认的收入约为每 GW 350 亿美元，2026Q2 谷歌确认约 12 亿美元——这是 TPU 系统首次作为外部销售收入入账。"
            "2026 年 6 月首批 TPU 硬件完成交付：名为 Compute SPV 的特殊目的实体支付 350 亿美元，购入约 1GW 的 AI 硬件（约合 100 万个 TPU）。"
            "4 月谷歌又同意向博通出售 3.5GW 的 TPU 硬件供 Anthropic 部署，博通披露的采购承诺总额约 1280 亿美元。"
            "据英国《金融时报》，谷歌已构建史上规模最大的基础设施融资计划之一，捆绑约 2000 亿美元合同，向 Anthropic 出售超过 1500 亿美元的 AI 芯片。"
            "SemiAnalysis 估计 2026Q3–2027Q4 期间谷歌超过 20% 的 TPU 出货将直接销售给 Anthropic（不含已租给 Anthropic 的数十万颗与承诺租给 Meta 的数十万颗）；"
            "DeepMind 在谷歌整体 AI 算力中的占比已从 2024 年约 40% 降至 2026 年约 33%，预计到 2027 年底进一步降至 17%。"
        ),
        "impact": 4,
        "sentiment": "positive",
        "source_name": "格隆汇（整理 SemiAnalysis Tokenomics Model 与 FT 报道）",
        "source_url": "https://m.gelonghui.com/p/5992826",
    },
    {
        "symbol": "GOOGL",
        "occurred_on": "2026-07-08",
        "category": "product_launch",
        "title": "Waymo 新增圣迭戈、拉斯维加斯、坦帕、丹佛四城无人驾驶，目标年底周订单达 100 万",
        "summary": (
            "Waymo 于 2026-07-08 宣布在圣迭戈、拉斯维加斯、坦帕、丹佛四个新市场启动全无人驾驶（先向员工开放，随后向公众开放，四城均计划年内完成）；"
            "至此其在超过 15 个美国都会区提供全无人驾驶服务。7 月 7 日纳什维尔通过与 Lyft 的合作向全体公众开放。"
            "年内还计划落地华盛顿特区、底特律与首个国际市场伦敦。资金面：2026 年 2 月 Waymo 从 Alphabet 及其他投资人处融资 160 亿美元，"
            "投后估值 1260 亿美元，为自动驾驶史上最大单轮融资；梅萨（亚利桑那）工厂正爬产至年产数万台第六代 Driver。"
            "运营目标：当前付费订单约 50 万单/周，目标年底达到 100 万单/周；累计行程已超 2000 万次。"
            "6 月推出 Waymo Premier 会员（29.99 美元/月）。经济性问题仍待解：McKinsey 估计 Robotaxi 每英里成本需降至 2 美元以下，"
            "当前行业成本约 7–9 美元/英里；Alphabet Other Bets 2026Q1 经营亏损 21 亿美元，Pichai 表示约 2027 年有望盈利。"
        ),
        "impact": 3,
        "sentiment": "positive",
        "source_name": "CNBC / Tech Times",
        "source_url": "https://www.cnbc.com/amp/2026/07/08/waymo-starts-driverless-rides-in-san-diego-las-vegas-tampa-denver.html",
    },
    {
        "symbol": "GOOGL",
        "occurred_on": "2026-08-14",
        "category": "regulatory",
        "title": "加州 CPUC 批准 Waymo 扩展至旧金山湾区、洛杉矶并进入萨克拉门托与圣迭戈；Pichai 淡化分拆可能",
        "summary": (
            "加州公用事业委员会（CPUC）批准 Waymo 在旧金山湾区与洛杉矶扩展全无人驾驶网约车服务，并新进入萨克拉门托与圣迭戈。"
            "Waymo 称本次推进将「循序渐进、以安全框架为指导」，并与地方官员和居民保持沟通。"
            "此前一个月，Alphabet CEO Pichai 在 Q2 财报电话会上回应分析师关于 Waymo 是否分拆的提问时表示："
            "Waymo 留在 Alphabet 的 Other Bets 结构内最合适，公司当前重点是「把业务规模化并执行到那个非凡的潜力上」，未给出分拆标准。"
            "另据 Alphabet 相关动向，其今年将把 GFiber 等其他 Other Bets 分拆出去。"
            "合作方面：Uber CEO Dara Khosrowshahi 在 Q2 电话会称 Waymo 是「非常重要」的伙伴，但 Uber 也在扩大与其他自动驾驶供应商的合作以降低单点依赖。"
        ),
        "impact": 3,
        "sentiment": "positive",
        "source_name": "Asianet Newsable / The Buildout",
        "source_url": "https://newsable.asianetnews.com/markets/waymo-scales-toward-1-million-weekly-rides-after-california-approval-for-expansion-articleshow-x4qvc7c",
    },
    {
        "symbol": "GOOGL",
        "occurred_on": "2026-08-20",
        "category": "model_release",
        "title": "三周内连发 Gemini 3.6 Flash 与 3.7 Flash，单价减半；8 月 Made by Google 配件 Pixel 11 与 Tensor G6 发布",
        "summary": (
            "在新 leadership 结构下，Google 于 8 月在三周内连发 Gemini 3.6 Flash 与 Gemini 3.7 Flash，并宣称单 token 价格较此前降低约一半，"
            "显示 DeepMind 正试图以更快节奏 + 更低成本应战 OpenAI 与 Anthropic。"
            "同期 8 月的 Made by Google 活动把新的 Gemini 能力与 Pixel 11 系列及其 Tensor G6 芯片打包发布，"
            "显示谷歌希望 Gemini 不只落在云端 API，也深度嵌入自家硬件。"
            "注：目前 Gemini App 已拥有 9.5 亿 MAU、Gemma 开源模型累计下载超 9 亿次，"
            "但亦有报道指出 Gemini 在部分全球模型榜单上的名次出现波动。"
        ),
        "impact": 3,
        "sentiment": "positive",
        "source_name": "The Index Today",
        "source_url": "https://www.theindextoday.com/google-deepmind-shake-up-hassabis-steps-back-to-chairman-as-jeff-dean-exits-after-27-years",
    },
    {
        "symbol": "GOOGL",
        "occurred_on": "2026-07-17",
        "category": "regulatory",
        "title": "法国竞争管理局发布 AI 代理竞争报告，建议将 MaaS 平台纳入 DMA「核心平台服务」指定",
        "summary": (
            "法国竞争管理局（AdlC）于 2026-07-17 发布智能体 AI 领域竞争报告（延续其 2026 年 1 月的调查），警告 AI 代理正迅速成为通向更广泛数字经济的网关。"
            "报告指出：尽管进入 AI 代理赛道的门槛低于构建基础生成模型，但开发者在触达用户、数据获取、互操作性与推理成本上仍受限。"
            "识别出的竞争风险包括：大型数字平台与 AI 代理提供商之间的股权投资与合作关系、在代理排序/推荐中的自我优待、"
            "开发者通过 API 依赖第三方基础模型形成的依赖风险、任务自动化带来的数据锁定、以及代理商务风险"
            "（自动重复购买固化在位者地位、潜在算法合谋）。报告还提示 AI 代理的「平台化」可能去中介化出版商与电商站点。"
            "建议：在竞争法、AI 法案与 DMA 现有框架下加强执法，更严格审查大型数字公司与竞争性 AI 代理开发者之间的投资纽带，"
            "推动互操作性与开放标准，并考虑将代理分发渠道（特别是 MaaS 平台）指定为核心平台服务。"
        ),
        "impact": 2,
        "sentiment": "negative",
        "source_name": "Lexology（European Antitrust Bimonthly Bulletin, July/August 2026）",
        "source_url": "https://www.lexology.com/library/detail.aspx?g=4599b7cf-be4e-477f-8991-1d7839e132c8",
    },

    # ===================== AAPL =====================
    {
        "symbol": "AAPL",
        "occurred_on": "2026-07-08",
        "category": "regulatory",
        "title": "欧盟普通法院驳回苹果三项 DMA 挑战，确认 App Store 与 iOS 的「守门人」认定",
        "summary": (
            "2026-07-08，欧盟普通法院驳回苹果就其被认定为《数字市场法》（DMA）「守门人」提起的挑战，"
            "维持欧委会 2023 年关于苹果 App Store 与 iOS 操作系统须遵守 DMA 行为规则的决定。"
            "法院否定了苹果的核心论点——即其为 iPhone、iPad、Apple Watch、Mac、Apple TV 设立的五个应用商店是相互独立的服务、"
            "只有 iOS App Store 跨过 DMA 的指定门槛；法院认定这些商店共同构成单一核心平台服务（CPS），"
            "因为「无论涉及何种设备」，它们的目的一致，都是「把应用开发者与终端用户连接起来」，"
            "而苹果所强调的差异「主要涉及所使用设备的具体特性」。"
            "法院拒绝对 DMA 互操作性义务的合法性作出裁决，理由是指定决定并非以其为法律依据；"
            "同时以不具可受理性为由驳回苹果对 iMessage 被列为核心平台服务的挑战（理由是该分类本身不产生约束性法律效果）。"
        ),
        "impact": 3,
        "sentiment": "negative",
        "source_name": "Lexology（European Antitrust Bimonthly Bulletin, July/August 2026）",
        "source_url": "https://www.lexology.com/library/detail.aspx?g=4599b7cf-be4e-477f-8991-1d7839e132c8",
    },
    {
        "symbol": "AAPL",
        "occurred_on": "2026-08-18",
        "category": "regulatory",
        "title": "苹果向欧盟投降：废除 Core Technology Fee，10 月 1 日起 EU App Store 佣金降至最低 5%",
        "summary": (
            "苹果于 2026-08-18 宣布欧盟 App Store 费率结构的全面重塑（与欧委会密切协作达成），2026-10-01 生效，"
            "宣告结束长达 18 个月的监管对抗：废除争议最大的 Core Technology Fee（每次安装 0.50 欧元），"
            "改为对 App Store 之外分发的 App 收取 5% 的 Core Technology Commission；同时取消初始获客费与商店服务费。"
            "新费率：使用 Apple IAP 的 App Store 应用佣金 26%（小企业计划、小程序伙伴计划、视频伙伴计划成员降至 15%）；"
            "并行接入替代支付处理的降至 20%（符合条件的小开发者 10%）；外链至网站完成购买的 15%（小开发者 10%）；"
            "自动续订订阅第二年降至 15%。另类应用市场分发适用 5% 统一佣金。"
            "背景：2025-04-23 欧委会因反引流违规对苹果罚款 5 亿欧元（同日 Meta 被罚 2 亿欧元、X 被罚 1.2 亿欧元，合计 8.2 亿欧元），"
            "苹果随后在 DMA 守门人认定诉讼中败诉。欧委会欢迎该公告但未宣布结案，将持续监督执行。"
            "结构性影响：付费墙整体抽成率下降会压制服务业务毛利率，但消除了重复违规罚款风险（DMA 重复违规罚款上限约为全球营收的 10%，约 360 亿欧元）。"
        ),
        "impact": 4,
        "sentiment": "neutral",
        "source_name": "Streamline Feed / Lowdown",
        "source_url": "https://streamlinefeed.co.ke/news/apple-overhauls-eu-app-store-fees-under-digital-markets-act-pressure",
    },
    {
        "symbol": "AAPL",
        "occurred_on": "2026-08-13",
        "category": "regulatory",
        "title": "Epic 案：法官拒绝苹果暂缓申请，要求其为外部购买链接佣金提供「真实且合理成本」举证",
        "summary": (
            "加州奥克兰联邦地区法院 Yvonne Gonzalez Rogers 法官于 2026-08-11 拒绝了苹果的暂缓请求。"
            "苹果此前于 2026 年 5 月向最高法院提交调卷申请，最高法院于 6 月 30 日受理，苹果以此为由请求暂缓——被驳回。"
            "法律标准：第九巡回法院认定苹果只能就其「真实且合理地」为协调外链购买而发生的成本收费，属成本补偿标准而非利润最大化/市场费率标准，"
            "更接近公用事业监管模型。若法院采用严格的成本口径、而苹果的实际协调成本被证明很小，"
            "这一判例将影响欧盟、英国、日本、韩国、印度对应用商店佣金主张的评估。"
            "美国自 2025 年 4 月起外链购买佣金为零，任何法院批准的费率都是相对现行基线的上调。"
            "苹果在多线作战：英国上诉法院待审 15 亿英镑集体诉讼（听证窗口 2026-11-02 至 2027-03-24），"
            "另有一项由消费者组织 Which? 提起、覆盖约 3850 万英国 iPhone/iPad 用户的 30 亿英镑集体诉讼已于 2026 年 6 月获准立案；"
            "日本《智能手机软件竞争促进法》2025 年 12 月生效；巴西竞争机构已达成和解；印度竞争委员会正权衡大额罚款。"
        ),
        "impact": 3,
        "sentiment": "negative",
        "source_name": "Tech Times",
        "source_url": "https://techtimes.com/articles/324312/20260813/apple-must-now-justify-app-store-commission-judge-who-called-it-contemptuous.htm",
    },
    {
        "symbol": "AAPL",
        "occurred_on": "2026-09-12",
        "category": "product_launch",
        "title": "iPhone 18 Pro 系列 9/12 预购：首小时销售额为上代两倍，全平台预约破 450 万，官网发货推迟至 9 月底",
        "summary": (
            "iPhone 18 Pro 系列于 2026-09-12 20:00 开启预售，多个热门型号在官网、淘宝、京东等平台开售数分钟内售罄，"
            "天猫 Apple 旗舰店因流量过大出现崩溃页面；首小时销售额为上代 iPhone 17 Pro 的 2 倍，全平台预约总量突破 450 万，"
            "热门版本官网发货时间推迟至 9 月底，第三方渠道（得物、闲鱼）主流机型成交均价较官方价上涨约 3000 元、涨幅达 27%，"
            "「苹果18抢不到」登上微博热搜榜首。9 月 18 日正式上市。"
            "供给侧：真正制约首批发货量的是上游关键零部件产能。据报道苹果向供应链下达了全年 9500 万台的出货目标。"
            "与往年全系齐发不同，今年仅有 iPhone 18 Pro / Pro Max 与折叠屏 iPhone Duo 三款高端机型首发，标准版推迟至 2027 年春季，"
            "意味着代工厂需在更短窗口内完成两款复杂度更高产品的爬坡；富士康郑州工厂自 8 月中旬起大规模紧急招工，"
            "立讯精密拿下 iPhone 18 Pro Max 约 70% 的组装份额。"
            "渠道侧新变量：字节跳动的豆包（Doubao）在 App 内提供首批 iPhone 18 Pro 独立库存，"
            "用户说一句「帮我订一台 iPhone 18 Pro Max」即可通过抖音商城完成下单（48 小时发货、12 期免息），"
            "AI 助手正从信息入口变成交易入口，绕开苹果自有渠道。"
        ),
        "impact": 4,
        "sentiment": "positive",
        "source_name": "证券日报 / 中国经济网 / 东方财富 / Trending on Weibo",
        "source_url": "https://www.ce.cn/xwzx/gnsz/gdxw/202609/t20260915_3213083.shtml",
    },
    {
        "symbol": "AAPL",
        "occurred_on": "2026-09-15",
        "category": "macro",
        "title": "中国高端手机格局生变：Q2 华为份额 23% 反超苹果 18%，Mate XT 2（19999 元）首销秒罄",
        "summary": (
            "据 Counterpoint 等机构统计，2026 年第二季度华为国内市场份额达 23%、苹果以 18% 退居第二；"
            "上半年累计份额华为 20.6%、苹果 17.5%，差距从一季度的 0.8 个百分点扩大到 4.6 个百分点。"
            "华为是前六大主流品牌中唯一实现同比正增长的厂商（涨幅接近 20%），而苹果的份额增长基本靠 618 等大促阶段降价拉动，日常零售自然增速远低于华为。"
            "高端价位段（5000 元以上）双方势均力敌：华为 Mate 80 系列总销量已突破 910 万台，阔屏 Pura X 系列累计发货超 290 万台，"
            "在非 iPhone 发售的常规时段，华为在 5000+ 价位单周销量已反超苹果。"
            "万元以上超高端市场华为已明显领先：9 月 12 日 10:08 全渠道首销的 Mate XT 2 非凡大师（起售价 19999 元）开售瞬间各配色版本全部断货，"
            "现货排队周期已排到 11 月上旬；叠加前两代三折叠机型，华为万元以上折叠屏累计销量已超过苹果同期所有万元以上机型销量总和。"
            "展望：10 月华为 Mate 90 系列即将发售，两者国内份额差距大概率继续拉开。"
            "另一层供给变量：华为被指已签订锁价锁量的长期 DRAM 协议，作为其将 2026 年手机出货目标提升至 6000 万部的底气；"
            "而苹果正面临三家核心内存供应商的涨价压力。"
        ),
        "impact": 3,
        "sentiment": "negative",
        "source_name": "东方财富财富号（引述 Counterpoint 等机构数据）",
        "source_url": "https://caifuhao.eastmoney.com/news/20260915152433705433790",
    },

    # ===================== META =====================
    {
        "symbol": "META",
        "occurred_on": "2026-07-31",
        "category": "partnership",
        "title": "Hyperion 数据中心 IT 容量从 2GW 扩至 5GW，投资超 500 亿美元，成 Meta 机队最大项目",
        "summary": (
            "Meta 于 2026 年 7 月宣布把路易斯安那州 Richland Parish 的 Hyperion 数据中心 IT 容量从此前规划的 2GW 提升至 5GW，"
            "对应投资超过 500 亿美元（约 100 亿美元/GW，相当于其 FY2025 资本开支 697 亿美元的约 72%），成为 Meta 机队中最大的数据中心。"
            "项目占地约 2250 英亩（约 9.1 平方公里，约为纽约中央公园的 3.5 倍），规划 11 栋独立数据中心主楼，总建筑面积超 37 万平方米，"
            "每栋搭载数十万块 GPU，定位为训练下一代 LLM（如 Llama 4 级）的「Titan Cluster」。"
            "高峰期建筑岗位超 7500 个，投运后提供约 1000 个长期岗位；一期预计 2026 年底/2028 年初上线， Societies 天然气机组先在 Holly Ridge 为 1.8GW 负载供电。"
            "融资结构：2025-10-21 与 Blue Owl Capital 达成 270 亿美元合资协议共同开发。"
            "项目已引发当地交通量激增、水质浑浊与间歇性停电等民生争议，Meta 承诺投入超 10 亿美元升级当地道路与水务系统。"
        ),
        "impact": 4,
        "sentiment": "positive",
        "source_name": "Data Center Index / 百度百科「Hyperion数据中心」",
        "source_url": "https://datacenterindex.ai/projects/meta-hyperion",
    },
    {
        "symbol": "META",
        "occurred_on": "2026-09-11",
        "category": "partnership",
        "title": "与 Entergy 达成里程碑协议：新建 7 座天然气电厂（5.2GW），路易斯安那当地燃气装机累计达 10 座、超 7GW",
        "summary": (
            "Entergy 路易斯安那子公司宣布，Meta 将出资新建 7 座天然气发电厂（新增 5.2GW），使其为 Hyperion 供电的天然气电厂总数达 10 座、"
            "发电能力超 7GW（此前已获批的 3 座约 2.3GW）；5GW 直接用于算力负载，其余供园区运营。新建工程需获州监管机构批准。"
            "Meta 还将资助 240 英里输电线路（连接路易斯安那南北部与阿肯色州）、电池储能系统、以及既有 Entergy 设施的核电扩容；"
            "双方另签署谅解备忘录探索未来核电开发。Meta 未披露总成本；Entergy 称结构化安排下 Meta 承担其全额服务成本，"
            "并预计该协议将在 20 年内为客户带来超 20 亿美元节省。"
            "Meta 数据副总裁 Rachel Peterson 称该申请与白宫提出的「纳税人保护计划」一致，并强调路易斯安那「友好的营商环境」。"
            "背景：2026 年 8 月特朗普要求科技企业承诺自行承担电力成本，以免居民电费上涨。"
            "争议：这些燃气电站全生命周期年碳排放估计达 400 万至 1000 万吨，相当于拉脱维亚全国年排放量；作为协议的一部分，Meta 承诺资助最高 2.5GW 新增可再生能源项目。"
        ),
        "impact": 4,
        "sentiment": "neutral",
        "source_name": "TechPathy（引述 Bloomberg 与 Entergy 公告）",
        "source_url": "https://techpathy.com/meta-to-power-massive-louisiana-data-center-with-10-natural-gas-plants-under-landmark-entergy-deal",
    },
    {
        "symbol": "META",
        "occurred_on": "2026-07-15",
        "category": "macro",
        "title": "Meta 退出 RE100 转向「气电+核电」基荷：签 Vistra / Constellation / Oklo / TerraPower 多项长协",
        "summary": (
            "Meta 因 Hyperion 等数据中心的基荷需求，于 2026 年 7 月正式退出已参与十年的 RE100 全球可再生能源倡议，"
            "公司口径转向「可靠电力优先」：承认「纸面上匹配年度用电量」与「任何一毫秒都确实拥有稳定电力」之间存在根本差别。"
            "具体长约包括：与 Vistra 签署 20 年零碳电力采购协议（逾 2600MW，20 年总成本估计约 70–86 亿美元）；"
            "与 Constellation 签署伊利诺伊州 Clinton 核电站 20 年期虚拟 PPA；与 Oklo 达成协议开发 1200MW 核电园区；"
            "与 TerraPower 签署部署最多 8 座 Natrium 反应堆的协议。"
            "海外布局同步推进：公布首个加拿大数据中心——阿尔伯塔省 Sturgeon County 约 1750 英亩、4 栋楼、1GW AI 优化容量，"
            "并配套 932MW 专用天然气设施。"
            "注：微软同期采取类似策略（6 月与 Chevron 签署 20 年协议建设德州 Reeves County 2.7GW 燃气 Project Kilby、"
            "表后直供，目标 2028 年底前向微软数据中心供电；另有 20 年协议重启三里岛核反应堆）。"
            "行业面：当前约四分之一在建数据中心容量涉及自建电源方案，覆盖 59 个追踪项目、约 90GW。"
        ),
        "impact": 3,
        "sentiment": "neutral",
        "source_name": "百度百科「Meta」/ NexFuture / remio.ai",
        "source_url": "https://www.nexfuture.net/2026/09/beyond-renewables-microsoft-and-meta.html",
    },
    {
        "symbol": "META",
        "occurred_on": "2026-09-23",
        "category": "product_launch",
        "title": "Meta Connect 2026 发布七款新品：VR Glasses 1299 美元对标 Vision Pro、无摄像头 Ray-Ban Meta Audio 349 美元、Muse Charm",
        "summary": (
            "Meta Connect 2026（9 月 23–24 日，门洛帕克）以「眼镜而非头显」为主题发布七款新品："
            "① Meta VR Glasses（100 克，约为 Quest 3 的五分之一，5K micro-OLED「Infinite Display」2412×2288/眼、最高 120Hz，"
            "外置「puck」计算单元搭载高通 Snapdragon Reality Elite、128GB + 12GB RAM，2027 年春季上市，1299 美元起，"
            "直接对标 3499 美元的 Apple Vision Pro，支持眼动+手势操控，可作为 Mac/Windows 无线虚拟显示器）；"
            "② Ray-Ban Meta Audio（首款无摄像头 AI 眼镜，43 克，12 小时续航/配充电盒 48 小时，349 美元，10 月 13 日发货）；"
            "③ Ray-Ban Meta Gen 3（12MP 相机 + 3K 空间视频、9 小时续航，新增 Aviator 与 Zena 框型，449 美元，较上一代 379 美元上涨约 19%）；"
            "④ Meta Adventurer（入门价位）；⑤ 扩展的 Meta Ray-Ban Display；"
            "⑥ Muse Charm（钥匙扣大小AI伴侣，2 英寸 LED、指纹传感器、内置 5G，假日季上市）；"
            "⑦ FDA 批准的助听增强功能（149 美元一次性，30 天试用，可用 FSA/HSA 报销）。"
            "扎克伯格称到 2026 年底眼镜款式将超过 100 种，并宣布 Muse 深度整合进眼镜：无需掏手机即可语音调用，"
            "未来几周将实现全情境感知并在后台持续运行。商业化路径：Muse 对多数场景保持免费，"
            "未来计划对 Agent 促成的交易抽取小额佣金。The Verge 指出本次发布会「元宇宙」叙事明显减少。"
        ),
        "impact": 5,
        "sentiment": "positive",
        "source_name": "Deccan Herald / Gadgets Now / 华尔街见闻",
        "source_url": "https://www.deccanherald.com/amp/story/technology%2Fartificial-intelligence%2Fmeta-connect-2026-highlights-new-camera-free-ai-ray-ban-meta-audio-glasses-vr-glasses-and-more-4157800",
    },
    {
        "symbol": "META",
        "occurred_on": "2026-07-29",
        "category": "partnership",
        "title": "Meta 与贝莱德（BlackRock）成立合资在埃尔帕索建设 1GW 数据中心，延续表外融资路线",
        "summary": (
            "Meta 在 2026Q2 财报的高亮点中披露：与贝莱德（BlackRock）达成战略合资，在美国得州埃尔帕索开发一个 1GW 数据中心。"
            "该项目高峰期创造超 4000 个建筑岗位，运营期提供约 300 个长期岗位；Meta 同时向埃尔帕索公立学校捐赠以支持 STEM 教育。"
            "这是 Meta 在数据中心融资结构上持续表外化的延续：路易斯安那 Hyperion 由与 Blue Owl Capital 的 270 亿美元合资持有，"
            "而 Meta 提供建设与物业管理服务；埃尔帕索项目同样采用与资管机构的合资形式。"
            "在本轮资本开支大幅上修（全年指引 1300–1450 亿美元）的背景下，Meta 的数据中心扩张已从"
            "「自有资本开支」转向「资本开支 + 合资 + 项目融资」组合，"
            "这是在营业利润率已从上年同期 43% 降至 31%、自由现金流单季仅剩 7.84 亿美元的背景下做出的结构性选择。"
        ),
        "impact": 3,
        "sentiment": "positive",
        "source_name": "TipRanks（Meta Q2 2026 财报要点）/ 百度百科「Meta」",
        "source_url": "https://www.tipranks.com/stocks/meta/earnings/q2-2026-report?hash=slideDeck",
    },

    # ===================== AMZN =====================
    {
        "symbol": "AMZN",
        "occurred_on": "2026-06-26",
        "category": "macro",
        "title": "Prime Day 2026 美国线上消费 264 亿美元创新高（+9.3%），但户均消费 143.45 美元同比 -8.3%",
        "summary": (
            "2026 年 Prime Day 于 6 月 23–26 日举行（已从 7 月提前至 6 月），四天期间美国全渠道线上零售销售额达 264 亿美元，"
            "同比 +9.3%~9.54%，创历史纪录；首日销售额 83 亿美元（同比 +5.3%），为 2026 年美国最大的单日线上购物。"
            "移动端贡献占比升至 53.2%，首次超过 PC 端；约 63% 的家庭完成两次及以上下单。"
            "但另一组数据呈现完全不同的叙事：Numerator 追踪超 5.9 万户家庭显示，户均消费 143.45 美元（去年同期 156.37 美元，同比 -8.3%），"
            "单件均价 23.23 美元（去年 24.59 美元），仅 59% 的消费者对折扣满意（去年 68%）。"
            "即总盘子扩大靠的是「更多人买」而非「单人买更多」，流量成本上升、订单碎片化、利润空间在约 24% 的折扣力度下被进一步压缩。"
            "品类结构：服装鞋类 30%、家庭日用品 28%、健康保健品 27%；其中最贵价位商品的购买份额同比 +19%、"
            "高端电子产品购买额同比 +51%。"
            "欧洲表现分化：整体接近去年水平，英国 +3%，热浪推动风扇/冰淇淋机/驱虫剂等品类。"
            "AI 侧：Rufus 助手峰值处理能力达每分钟约 300 万 token，AI 相关物流量同比接近翻倍。"
            "支付侧：BNPL 占比提升至 6.5%–6.6%（同比 +7.6%），提示支付周期拉长对现金流的潜在影响。"
            "广告侧：CPC 小幅下降、ROAS 提升至约 4.59 美元。"
        ),
        "impact": 3,
        "sentiment": "neutral",
        "source_name": "AMZ123 / 雨果跨境eccang（引述 Adobe、Numerator）/ eMarketer",
        "source_url": "https://www.amz123.com/kx/WAO1RAb5",
    },
    {
        "symbol": "AMZN",
        "occurred_on": "2026-08-05",
        "category": "partnership",
        "title": "AWS 与 Anthropic 扩表至十年超 1000 亿美元；亚马逊对 Anthropic 累计投资 130 亿、潜在上限 330 亿",
        "summary": (
            "据亚马逊 Q2 2026 SEC 文件：AWS 与 Anthropic 的核心云关系在未来十年扩大超 1000 亿美元（4 月 20 日宣布），"
            "覆盖由亚马逊自研芯片（Graviton 处理器 + Trainium2 至 Trainium4，并可延伸至未来世代）提供的最高 5GW 容量。"
            "同一份披露还显示 OpenAI 既有的 380 亿美元 AWS 承诺追加 1000 亿美元、为期八年。"
            "AWS 长期合约的加权平均剩余期限从 4.0 年延长至 6.4 年；部门积压订单自 2025 年中约 1950 亿、"
            "3 月约 3640 亿增至 6 月底约 4960 亿美元（其中该笔 Anthropic 交易约占五分之一）。"
            "股权侧：亚马逊 4 月 20 日立即投入 50 亿美元，叠加此前持有的 80 亿，累计达 130 亿美元；"
            "若 Anthropic 达成特定绩效里程碑，亚马逊还可能再追加 200 亿，潜在总额达 330 亿美元。"
            "资金安排上，亚马逊在 Q2 分别向 Anthropic 的 Series G 与 Series H 各投入 50 亿美元，"
            "动用了原上限 200 亿美元的定制信贷额度，剩余 150 亿可用；提款严格与 AWS 算力交付里程碑挂钩，"
            "未来提款形式为可转换票据或 IPO/流动性事件后的普通股（受亚马逊的结构性持股上限约束）。"
            "会计侧：亚马逊在 2026Q2 对 Anthropic 优先股确认了 505 亿美元的公允价值上调（非现金），"
            "反映的是可观察的私募定价基准而非 AWS 实际经营现金流。"
        ),
        "impact": 5,
        "sentiment": "positive",
        "source_name": "PivotNews（引述亚马逊 Q2 2026 SEC 文件）/ PChome / TMAStreet",
        "source_url": "https://pivotnews.ai/five/anthropic-s-100-billion-aws-pledge-faces-its-first-audit",
    },
    {
        "symbol": "AMZN",
        "occurred_on": "2026-09-06",
        "category": "other",
        "title": "Anthropic 拟于劳动节后公布 IPO 招股书，其 1000 亿美元 AWS 承诺将首次接受外部审计检验",
        "summary": (
            "Motley Fool 分析师 Daniel Sparks 于 2026-09-06 指出，据 The Information 上月报道，Anthropic 计划在美国劳动节后公布 IPO 招股书，"
            "最早 9 月下旬或 10 月挂牌；其目前唯一的公开记录是 6 月 1 日向 SEC 保密提交的 S-1 草案，Series H 投后估值 9650 亿美元。"
            "这将是投资者第一次从买方账本一侧检验 Anthropic 的履约能力：1000 亿美元摊到十年约合每年 100 亿美元以上。"
            "Anthropic 的数据目前为自报——4 月年化营收超 300 亿美元，据 CNBC 报道公司 8 月中旬向投资人称已超 650 亿美元；"
            "诉讼/合规侧同时存在 FTC 反竞争数据行为调查、与 Sony/Warner Music 的版权诉讼，以及在五角大楼黑名单案中胜诉。"
            "Sparks 的核心观点：积压订单是已签约工作而非收入，亚马逊只能记录自己这一侧的安排；"
            "在 Anthropic 提交招股书之前，投资者只能依据其自行披露的数据来评判 AWS 这超过 2000 亿美元的、"
            "来自两家私营 AI 公司的多年承诺。"
        ),
        "impact": 3,
        "sentiment": "neutral",
        "source_name": "PivotNews（引述 fool.com 与 The Information）",
        "source_url": "https://pivotnews.ai/five/anthropic-s-100-billion-aws-pledge-faces-its-first-audit",
    },
    {
        "symbol": "AMZN",
        "occurred_on": "2026-08-01",
        "category": "other",
        "title": "AWS 印第安纳 Hobart 园区从 6 栋扩至 26 栋（约 2GW）；机器人部门 3 月裁 100+ 岗、Blue Jay 项目被砍",
        "summary": (
            "据 2026 年 8 月的项目追踪，AWS 通过最新备案把印第安纳州 Hobart 园区从规划的 6 栋楼扩展至 26 栋，"
            "整个园区约需 2GW 的设施电力；场地清理早在 2026 年 3 月就已被观察到，因此有别于仅停留在 PPT 或早期规划文档中的项目。"
            "但单个楼宇仍需逐一获得许可、电力设备、网络连接、服务器与客户，因此园区总量对近期可用产能的指示意义有限。"
            "机器人侧据此前报道：亚马逊于 2026 年 1 月关停较新的 Blue Jay 多臂仓储机器人（因制造成本与运营问题），"
            "感知与抓取软件被并入其他项目；2026-03-04 又在机器人部门裁撤 100 多个白领岗位（此前 1 月已裁约 16000 名公司员工，"
            "自 2022 年底以来企业岗位累计削减超 57000 个）；替代方案是名为 Orbital 的新模块化自动化平台（含潜在 Whole Foods 微履约场景）。"
            "截至 2025 年中亚马逊已在全球 300 多个设施部署超 100 万台机器人，DeepFleet 可将机器人行驶时间改善约 10%；"
            "截至 2025 年中亚马逊已在全球 300 多个设施部署超 100 万台机器人，DeepFleet 可将机器人行驶时间改善约 10%；"
            "另有报道引用的内部规划文件称，到 2033 年可少雇最多 60 万人，2025–2027 年节省约 126 亿美元人力成本。"
        ),
        "impact": 2,
        "sentiment": "neutral",
        "source_name": "remio.ai / The Index Today / ai2.work",
        "source_url": "https://www.theindextoday.com/amazon-cuts-robotics-jobs-even-as-it-bets-everything-on-warehouse-automation",
    },

    # ===================== AVGO =====================
    {
        "symbol": "AVGO",
        "occurred_on": "2026-09-02",
        "category": "partnership",
        "title": "与 Apollo、Blackstone 完成 AI 基建融资工具首期 350 亿美元，专项用于 Anthropic 算力需求",
        "summary": (
            "为支撑资本密集型的算力建设，博通宣布已与私募机构 Apollo Global Management 和 Blackstone "
            "完成 AI 基础设施融资工具的首期 350 亿美元，该安排与 Anthropic 的算力需求直接挂钩。"
            "管理层表示此前的融资安排已用于支持超过 20GW 的算力，其余将逐案评估；公司称未宣布新的残值担保或兜底安排。"
            "同期管理层明确了执行瓶颈：土地、电力（ shell/用地许可）、酸碱 advanced 晶圆、基板、HBM 等系统组件都可能影响部署节奏。"
            "融资已从资产负债表考量演变为 AI 硅片的 go-to-market 工具：前瞻 AI 客户缺乏足够信用能力时，"
            "由博通牵头的融资结构是让 GW 级订单落地的前提条件之一。"
        ),
        "impact": 4,
        "sentiment": "positive",
        "source_name": "SmartBrains AI（引述博通 Q3 FY2026 财报电话会）",
        "source_url": "https://smartbrainsai.com/broadcoms-ai-chip-sales-triple-to-16-7-billion-as-hock-tan-charts-a-path-to-230-billion",
    },
    {
        "symbol": "AVGO",
        "occurred_on": "2026-09-02",
        "category": "earnings",
        "title": "毛利率信号转负：Q4 指引隐含 non-GAAP 毛利率降至约 73%，XPU 占比与内存含量上升稀释毛利",
        "summary": (
            "在 +86% 的营收增长之外，博通同时给出了偏负面的质量信号："
            "Q3 non-GAAP 毛利率环比下降 210 个基点至 75%（另一口径为 76.3%，同比降 1.5pct），原因是定制 AI 加速器（XPU）出货占比提升——"
            "这类产品毛利率通常低于网络芯片；Q4 指引隐含 non-GAAP 毛利率进一步降至约 73%。"
            "管理层表示随着 AI 占比继续上升、单位所含内存价值增加，毛利率压力可能持续，"
            "但因经营杠杆足够强，营业利润率可维持在 66% 左右。"
            "其他硬约束：Q4 资本开支指引 14 亿美元；土地、电力、数据中心土建、先进晶圆、基板、HBM 及其他系统组件都可能影响部署节奏；"
            "客户融资安排将逐案评估。管理层同时表示未来两年将向现有定制芯片客户出货合计约 3500 亿美元的 AI 半导体。"
        ),
        "impact": 3,
        "sentiment": "negative",
        "source_name": "MarketBeat（博通 Q3 2026 财报电话会纪要）/ SmartBrains AI",
        "source_url": "https://www.marketbeat.com/earnings/reports/2026-9-2-broadcom-inc-stock/",
    },
    {
        "symbol": "AVGO",
        "occurred_on": "2026-09-07",
        "category": "other",
        "title": "分析师称 1150 亿是「地板」而非天花板，Anthropic 与 OpenAI 将于 2027 年超越谷歌成最大定制芯片客户",
        "summary": (
            "专业半导体分析师 Ben Bajarin 与 Jay Goldberg 在 9 月 7 日的播客中表示，博通给出的 FY2027 约 1150 亿美元 AI 半导体收入"
            "应被视为「地板」而非上限，而市场内部的低语数字约在 1500 亿美元——这正是财报周股价下跌约 4% 的原因（预期差而非基本面转弱）。"
            "更值得注意的结构变化：Anthropic 与 OpenAI 预计将在 2027 年超越谷歌，成为博通最大的两家定制芯片客户，"
            "两家公司在不到一年的时间内从零增长到超过 Google 的体量。"
            "同期的空方叙事也在升级：有宏观分析者构建了实时倒计时追踪超大厂何时跨入自由现金流负值，读数约 50 天甚至更短；"
            "具体拆解为——Alphabet 六个月 1476 亿美元营业利润在扣除 806 亿资本开支后仅剩 533 亿自由现金流，"
            "亚马逊近 7500 亿营收对应的自由现金流为 -76 亿美元。类比是 1840 年代英国铁路狂热：股市顶部比企业真正削减开支早 18 个月。"
        ),
        "impact": 3,
        "sentiment": "neutral",
        "source_name": "Matterfact（The AI Capex Tracker，2026-09-08 期）",
        "source_url": "https://www.matterfact.com/newsletter/2026-09-08-broadcom-names-its-number-bears-name-a-date",
    },
    {
        "symbol": "AVGO",
        "occurred_on": "2026-08-20",
        "category": "regulatory",
        "title": "VMware 后并购定价引发流失风险：部分客户报告涨价 800%–1500%，转向 Nutanix / OpenShift / 公有云",
        "summary": (
            "竞争性情报显示，博通收购后的 VMware 定价策略已成为显著的客户流失风险："
            "部分组织报告在新的订阅捆绑模式下价格上涨 800% 至 1500%，核心许可约为每核每年 190 美元、设 72 核最低门槛（约 1 万美元/年）。"
            "从永久许可转向订阅许可，消除了客户此前持有的期权价值。"
            "这种激进的重定价在近期榨取了装机基数的最大价值，但也加速了对 Nutanix、Red Hat OpenShift 与公有云迁移的评估——"
            "意味着博通软件收入的耐久性更依赖于转换成本的黏性，而非价格竞争力。"
            "对冲动作：与拥有 20 年以上关系的 NEC 围绕部署 VMware Cloud Foundation 深化合作（称已进入十大 Fortune 500 中的九家），"
            "通过 GSI 忠诚度计划保护企业侧;同时在 Kubernetes 生态与 F5、Kong、Tigera 建立合作。"
            "战略判读是：博通预期流失风险最高的集中在中端市场，因此用关系型企业盟友筑牢大型企业防线。"
        ),
        "impact": 3,
        "sentiment": "negative",
        "source_name": "ForesightIQ（Broadcom Competitive Intelligence & Landscape）",
        "source_url": "https://foresightiq.co/competitive-landscape/broadcom",
    },

    # ===================== AMD =====================
    {
        "symbol": "AMD",
        "occurred_on": "2026-08-06",
        "category": "product_launch",
        "title": "Advancing AI 2026 发布 Helios 机架：72 颗 MI455X + UALink over Ethernet，单机架售价约 525 万美元",
        "summary": (
            "AMD 于旧金山 Advancing AI 2026（8 月 6 日）宣布 Helios 机架级 AI 系统进入全面生产，"
            "三季度末开始出货、四季度放量并延续至 2027 年。单机架连接 72 颗 Instinct MI455X GPU"
            "（TSMC 2nm/3nm，3200 亿晶体管，12 个计算与 I/O 芯粒，432GB HBM4、最高 19.6TB/s 带宽），"
            "配第六代 EPYC Venice CPU、Pensando Salina DPU 与 Vulcano 800G AI NIC、液冷；"
            "整机 31TB HBM4、峰值 2.9 EFLOPS FP4（1.4 EFLOPS FP8）、260TB/s scale-up 带宽、43TB/s scale-out 带宽。"
            "网络架构是最大差异化：三层网络全部基于以太网与开放标准——前端为第三代 Pensando Salina DPU（400G），"
            "scale-up 用第一代 UALink over Ethernet（UALoE）连接全部 72 颗 GPU，scale-out 为第二代 Vulcano AI NIC（800G，每 GPU 3 张、共 2.4Tbps）。"
            "AMD 称单机架每美元 token 数较 Nvidia Rubin NVL72 高最多 30%、内存容量高 50%；"
            "据与会分析师，单机架售价约 500–550 万美元（均值约 525 万）。"
            "注：以太网 2025 年已在 AI 后端网络超过 InfiniBand，2026Q1 约占 AI 集群数据中心交换机销量的三分之二。"
        ),
        "impact": 5,
        "sentiment": "positive",
        "source_name": "Fierce Network / Converge Digest",
        "source_url": "https://www.fierce-network.com/cloud/amds-helios-bets-ai-networking-open-ethernet",
    },
    {
        "symbol": "AMD",
        "occurred_on": "2026-08-06",
        "category": "partnership",
        "title": "Oracle 自 Q3 起部署 5 万颗 MI450；OpenAI / Meta 各 6GW + Anthropic 2GW，合计锁定超 12GW 加速器需求",
        "summary": (
            "AMD 在 Advancing AI 2026 上披露的客户版图：OpenAI 的既有协议覆盖最多 6GW AMD GPU（首个 1GW MI450 级部署在 2026 下半年启动），"
            "Meta 另有单独的 6GW 多代际协议（同样以约 1GW MI450 级基础设施在 2026 下半年起步）；"
            "Meta 基础设施负责人 Santosh Janardhan 表示 MI350 系列已在排序与推荐系统中量产使用，MI450 将「全面铺开」。"
            "Anthropic 的投资/供货打包：最高 2GW Helios 容量 + AMD 最多 50 亿美元的股权投资。"
            "此外 Oracle 宣布自 2026Q3 起在 Oracle Cloud Infrastructure 部署 5 万颗 MI450；"
            "微软 Azure 确认作为 Helios 机架的锚定客户，用于前沿模型推理。"
            "OpenAI 协议的特殊结构：AMD 授予其最多 1.6 亿股、行权价 0.01 美元的绩效认股权，"
            "按部署里程碑分批归属直至 2030 年 10 月；全部行权约相当于 AMD 已发行股份的 10%——"
            "这使 AMD 同时成为 OpenAI 的供应商与潜在股东，属于行业内普遍的循环供应商融资模式。"
            "OpenAI 基础设施负责人 Sachin Katti 表示将从今年底开始大规模部署 Helios、2027 年加速；"
            "Anthropic 首席计算官 Tom Brown 披露其评估过程：一名工程师把上一代 MI355X 机架接上 Claude、让 AI 自行bring up后离开过周末，"
            "回来时已得到一份持续爬升的性能曲线图。"
        ),
        "impact": 5,
        "sentiment": "positive",
        "source_name": "Fierce Network / Tech Insider / Converge Digest",
        "source_url": "https://tech-insider.org/amd-advancing-ai-2026/",
    },
    {
        "symbol": "AMD",
        "occurred_on": "2026-08-06",
        "category": "product_launch",
        "title": "推出风冷 MI350P 与 Cerebras 异构推理方案；Venice 新增 256 核/512 线程 agent sandbox 变体",
        "summary": (
            "面向无法围绕液冷 AI 机架重建机房的企业，AMD 发布风冷 Instinct MI350P：可放入既有企业服务器，"
            "单卡支持最高 2600 亿参数模型，公司称每美元每秒 token 数最高为竞品的 4.2 倍。"
            "AMD 自有 IT 组织在 EPYC + MI350P 上运行开放权重模型（本地模型与前沿模型之间智能路由），"
            "称 token 成本降低 43%、本地负载响应速度最高提升 3 倍。"
            "异构推理：与 Cerebras 合作，由 Helios 负责 prompt 处理与大上下文 prefill、Cerebras 晶圆级引擎负责带宽密集的 decode 与低时延 token 生成；"
            "双方联合建模估计在同等交互水平下，每瓦每秒 token 数最高为纯 Cerebras 配置的 5 倍，"
            "Cerebras 计划于 2026 下半年通过 Cerebras Cloud 提供该架构。"
            "CPU 侧：Venice 家族（Zen 6，TSMC 2nm，2030 亿晶体管，最高较上代提升 1.8 倍，为 EPYC 史上最大代际提升之一）"
            "除 96 核 GPU 主机版本与 128 核通用版本外，新增专为「agent sandbox」设计的 256 核/512 线程版本，"
            "用于 agent 执行代码、调用工具与查询数据等 CPU 密集型负载。AMD 预计到 2030 年服务器 CPU 市场规模将超 2000 亿美元。"
        ),
        "impact": 3,
        "sentiment": "positive",
        "source_name": "Fierce Network",
        "source_url": "https://www.fierce-network.com/cloud/amd-launches-full-stack-ai-compute-agentic-era",
    },
    {
        "symbol": "AMD",
        "occurred_on": "2026-08-06",
        "category": "macro",
        "title": "AMD 判断推理已占全球 AI 算力约 60%，月 token 消耗超 35 quadrillion（约两年前的 160 倍）",
        "summary": (
            "Lisa Su 在 Advancing AI 2026 主题演讲中把叙事锚定在一个结构性转变上：推理消耗的全球 AI 算力已超过模型训练。"
            "AMD 估计 2026 年推理将占全球 AI 算力约 60%，月 token 消耗超过 35 quadrillion，约为两年前的 160 倍。"
            "公司相应上调长期市场预测：AI 加速器市场到 2030 年约达 1.4 万亿美元，服务器 CPU 市场从当前约 250 亿美元扩张至超 2000 亿美元。"
            "产品路线也随之为推理而重构：整机交付（机架级而非芯片级）、从不依赖专有互连的全以太网开放标准、"
            "以及专门针对 agent 执行的 CPU 密度优化。Schneider Electric 已发布 246kW 的机架部署参考设计。"
        ),
        "impact": 2,
        "sentiment": "positive",
        "source_name": "Converge Digest / Fierce Network",
        "source_url": "https://convergedigest.com/amd-puts-helios-into-production-as-ai-reshapes-data-centers/",
    },
]


def main() -> None:
    res = post("/events", {"agent": AGENT, "events": EVENTS})
    print("events:", json.dumps(res, ensure_ascii=False))

    res = post("/done", {"agent": AGENT,
                         "note": "第二轮补充：新增 " + str(len(EVENTS)) + " 条事件，覆盖自研芯片、算力基建/电力、"
                                 "监管诉讼（DMA/Epic/ robotic）、核心人事、产品与渠道，均已标注真实来源。"})
    print("done:", json.dumps(res, ensure_ascii=False))


if __name__ == "__main__":
    main()
