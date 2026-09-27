#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""第三轮补充（A 组：MSFT / GOOGL / AAPL）——财务质量、监管罚则、安全事件、产品线。"""
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
        "occurred_on": "2026-09-15",
        "category": "earnings",
        "title": "季度股息上调 8% 至 0.98 美元/股，连续第 24 年提高；单季股息加回购返还 102 亿美元",
        "summary": (
            "微软 2026-09-15 将季度股息由 0.91 美元上调至 0.98 美元（约 +8%），年化派息 3.92 美元，"
            "按约 500 美元股价计收益率约 0.80%，仍低于科技板块平均 1.37%。12 月 10 日派发，11 月 19 日为除息日兼登记日。"
            "这是连续第 24 年提高股息，再提一次即达「股息贵族」25 年门槛；派息率仅 20.53%，"
            "即便股息翻倍仍可留存近六成盈利。单季通过股息与回购合计返还股东 102 亿美元，"
            "而同期 2026 日历年 AI 基础设施资本开支计划约 1750 亿美元——即在激进投入的同时仍在提高派息。"
            "分部：FY26Q4 Intelligent Cloud 393 亿（+32%，最大分部）、生产力与业务流程 378 亿（+14%）、"
            "更多个人计算 129 亿（-4%）；Copilot 付费席位超 3000 万且净增环比翻倍以上。"
            "全年 FY26 EPS 17.28 美元，分析师对 FY27 预期 19.61 美元（约 +13.5%）。"
            "下次财报 2026-11-04，将是重组分部报告后的首个完整季度读数（分析师预期每股 4.69 美元，上年同期 4.13 美元）。"
        ),
        "impact": 3,
        "sentiment": "positive",
        "source_name": "Yahoo Finance / AOL（引述微软 SEC 文件与 Barchart）",
        "source_url": "https://finance.yahoo.com/markets/stocks/articles/microsoft-just-hiked-dividend-8-233002125.html",
    },
    {
        "symbol": "MSFT",
        "occurred_on": "2026-09-10",
        "category": "partnership",
        "title": "与诺基亚深化合作：整合 Nokia Data Suite 与 Microsoft Fabric，助电信运营商自动化网络运维",
        "summary": (
            "微软与诺基亚（NOK）深化合作，帮助电信运营商自动化更多网络运维工作。双方正构建共享数据平台，"
            "把 Nokia Data Suite 与 Microsoft Fabric 打通，让运营商在同一环境中同时获得即用型网络数据"
            "与微软的数据、治理及 AI 工具，目标是把获取可靠洞察的时间从数周压缩到数分钟，"
            "并消除大量拼接异构系统的手工工作。这是微软把 Azure/Fabric 推向电信等垂直行业数据层的典型动作。"
        ),
        "impact": 2,
        "sentiment": "positive",
        "source_name": "Yahoo Finance / Kobaran",
        "source_url": "https://www.kobaran.com/microsoft-stock-gets-an-8-dividend-boost-but-the-real-story-is-ai",
    },
    {
        "symbol": "MSFT",
        "occurred_on": "2026-07-14",
        "category": "other",
        "title": "7 月补丁日创纪录修复 622 个 CVE，含两个在野利用零日与 Hyper-V 9.9 分虚拟机逃逸漏洞",
        "summary": (
            "微软 2026 年 7 月补丁日（7 月 14 日）共修复 622 个漏洞，覆盖 Windows、Office、SharePoint Server、"
            "AD FS、Exchange Server、Azure 组件与 SQL Server。两个已被确认在野利用："
            "CVE-2026-56164（SharePoint 权限提升，可远程利用且无需认证）、CVE-2026-56155（AD FS 权限提升，"
            "授权攻击者可提权至管理员）。其他高危项：CVE-2026-57092（Hyper-V VMSwitch，CVSS 9.9，"
            "use-after-free 可致虚拟机逃逸到宿主机，对多租户隔离构成严重威胁）；"
            "CVE-2026-50518 与 CVE-2026-56159（DHCP Server，9.8）；CVE-2026-56188（Windows Server 网络驱动，9.8，"
            "未认证 RCE）；CVE-2026-55944（Dynamics 365 Business Central，9.8，反序列化未认证 RCE）；"
            "CVE-2026-55008（Exchange/OWA，9.6）。Office 单独获 164 个修复，含 9 个可通过预览窗格触发的严重 RCE"
            "（无需打开文档）。此外本次更新移除了 1 月引入的 Kerberos RC4 回退开关，"
            "缺少 AES 密钥的服务账号在打补丁后可能认证失败，需提前排查。"
        ),
        "impact": 3,
        "sentiment": "negative",
        "source_name": "Orca Security / Field Effect",
        "source_url": "https://orca.security/resources/blog/microsoft-july-2026-patch-tuesday-sharepoint-zero-day/",
    },
    {
        "symbol": "MSFT",
        "occurred_on": "2026-08-18",
        "category": "regulatory",
        "title": "CISA 将 6 个 SharePoint 漏洞列入 KEV 目录并多次升级告警，要求联邦机构 3 天内修补",
        "summary": (
            "美国 CISA 就 SharePoint 本地部署遭持续攻击多次更新告警，确认以下漏洞在野被利用并纳入 KEV 目录："
            "CVE-2026-32201（4 月作为零日被利用，4/14 入 KEV）、CVE-2026-45659（5 月带外更新修复，7/1 入 KEV）、"
            "CVE-2026-56164（7/14 入 KEV）、CVE-2026-58644（CVSS 9.8 反序列化 RCE，7/16 入 KEV）、"
            "CVE-2026-50522（7/22 入 KEV）、CVE-2026-55040（CVSS 9.1 认证绕过，可冒充含管理员在内的用户，8/18 入 KEV）。"
            "受影响版本含 SharePoint Server 订阅版、2019 与 2016；攻击者通过 RCE 与后渗透活动"
            "（窃取 IIS 机器密钥、反序列化植入）获取持久化并部署恶意软件。CISA 要求联邦机构 3 天内修补（BOD 26-04），"
            "并建议避免 SharePoint 直接暴露公网、如需暴露则部署七层反向代理、启用 AMSI 集成并选用完整模式请求体扫描、"
            "轮换 IIS 机器密钥、阻断对管理中心的外网访问。随后 8 月补丁日又修复 415 个 CVE，含 1 个已利用零日与 62 个严重漏洞。"
        ),
        "impact": 3,
        "sentiment": "negative",
        "source_name": "CISA 官方告警 / SecurityWeek / CrowdStrike",
        "source_url": "https://www.cisa.gov/news-events/alerts/2026/07/14/cisa-urges-sharepoint-hardening-after-new-exploitations",
    },
    {
        "symbol": "MSFT",
        "occurred_on": "2026-09-11",
        "category": "regulatory",
        "title": "欧盟接受微软把 Teams 从 Office 解绑的承诺，具法律约束力至少 7 年，避免重额反垄断罚款",
        "summary": (
            "欧盟委员会确认接受微软的承诺，使其在欧盟竞争法下具法律约束力至少 7 年，从而避免潜在的重额罚款。"
            "委员会曾指控微软把 Teams 与 Office 打包属「滥用性搭售」，阻碍 Slack、Zoom 等竞品竞争。"
            "承诺包括：以更低价格提供不含 Teams 的 Office 365 与 Microsoft 365 套件；允许长期许可持有者切换至不含 Teams 版本；"
            "改善 Teams 与竞品的互操作性；支持把数据从 Teams 迁移到竞争服务。经市场测试后，"
            "微软还同意把含 Teams 与不含 Teams 版本之间的价差再拉大 50%，并在网站上更清晰展示不含 Teams 的替代方案。"
            "案件源于 Slack（2021 年被 Salesforce 以 277 亿美元收购）的投诉。微软已在全球自愿适用这些承诺，"
            "但在英国不具法律强制力——英国 CMA 另就微软商业软件生态系统启动了战略市场地位（SMS）调查，"
            "并在其征求意见文件中明确表示会参考欧盟的 Teams 救济与 DMA 约束。"
            "行业关注点已转向下一个战场：把 Copilot 与 M365 订阅捆绑是否构成同类反竞争行为。"
        ),
        "impact": 3,
        "sentiment": "negative",
        "source_name": "EasternEye / Tech Research Online（引述欧盟委员会声明与 CNBC）",
        "source_url": "https://www.easterneye.biz/microsoft-antitrust-teams-offer-eu/",
    },

    # ===================== GOOGL =====================
    {
        "symbol": "GOOGL",
        "occurred_on": "2026-07-22",
        "category": "earnings",
        "title": "Q2 广告总收入 816 亿美元 +14.4%；Other Bets 收入仅 3.82 亿、经营亏损 18 亿",
        "summary": (
            "广告口径拆解：Q2 总广告收入约 816 亿美元（+14.4%），其中 Google 搜索 633 亿（+17%）为增长主力，"
            "YouTube 广告 111 亿（+13%），订阅/平台/设备 129 亿（+15%）。"
            "云业务 82% 的增速不应被简单视为纯有机或可持续——该季度包含了 TPU 系统销售收入的首次确认，"
            "以及 Wiz 收购并表的贡献；云积压订单约 5139 亿美元，略超一半预计在未来 24 个月确认，"
            "但积压是已签约需求而非有保障的收入，仍取决于服务交付、容量、合同条款与客户实际用量。"
            "其他业务：Other Bets 收入仅 3.82 亿美元、经营亏损 18 亿美元；"
            "Alphabet 层面另产生 58 亿美元经营亏损，主要反映共享的 AI 研发投入。"
            "Waymo 等项目可能创造可观期权价值，但在资本需求与长期单位经济性清晰之前应谨慎估值。"
        ),
        "impact": 3,
        "sentiment": "neutral",
        "source_name": "StockMetricLab / PivotNews",
        "source_url": "https://stockmetriclab.com/alphabet-stock-analysis",
    },
    {
        "symbol": "GOOGL",
        "occurred_on": "2026-07-22",
        "category": "earnings",
        "title": "Q2 自由现金流转负：资本开支 448.9 亿超过经营现金流 391 亿，未投用资产已达 1228 亿",
        "summary": (
            "Q2 购置物业与设备支出 448.9 亿美元，超过 391 亿美元的经营现金流，公司口径自由现金流为 -59 亿美元。"
            "2026 年上半年资本开支累计 806 亿美元，为上年同期 396 亿美元的两倍以上。"
            "更关键的是会计费用将滞后于现金承诺：季末「尚未投入使用」的资产达 1228 亿美元，"
            "尚未启动的数据中心租赁项下未来付款达 852 亿美元——折旧在资产达到可使用状态时才开始计提，"
            "意味着即便建设阶段结束，利润率仍可能面临持续上行压力。"
            "TTM 口径：经营现金流 1857 亿、购建固定资产 1324 亿、公司口径自由现金流 533 亿。"
            "即 Alphabet 六个月 1476 亿美元营业利润在扣除 806 亿资本开支后仅剩 533 亿自由现金流。"
        ),
        "impact": 3,
        "sentiment": "negative",
        "source_name": "StockMetricLab",
        "source_url": "https://stockmetriclab.com/alphabet-stock-analysis",
    },
    {
        "symbol": "GOOGL",
        "occurred_on": "2026-07-22",
        "category": "other",
        "title": "融资结构变化：Q2 融资 699 亿美元，短期有价证券含约 800 亿受限 SpaceX 股份，上半年回购为零",
        "summary": (
            "2026 年 6 月底 Alphabet 持有现金、现金等价物与短期有价证券 2425 亿美元，长期债务 982 亿美元。"
            "但流动性数字需打折：短期有价证券中约 800 亿美元为受限的 SpaceX 股份，"
            "不应视为可立即用于运营或股东分配的普通现金。Q2 期间通过普通股与强制可转换优先股融资 496 亿美元，"
            "并发行优先无担保票据净得 203 亿美元；另设立最多 400 亿美元的市价发行（ATM）计划，季末尚未出售任何股份。"
            "值得注意的是，上半年普通股回购为零，尽管授权余额仍有 695 亿美元。"
            "新增融资为 AI 基础设施与并购（含已完成的 Wiz 交易）提供灵活性，但也改变了资本结构——"
            "需持续跟踪完全稀释后股数、优先股转换、股权激励、债务偿付，以及新资本是否产生增量经营现金流。"
        ),
        "impact": 3,
        "sentiment": "neutral",
        "source_name": "StockMetricLab",
        "source_url": "https://stockmetriclab.com/alphabet-stock-analysis",
    },
    {
        "symbol": "GOOGL",
        "occurred_on": "2026-08-01",
        "category": "other",
        "title": "YouTube 年化体量接近 930 亿美元，Nielsen 6 月数据显示其占流媒体观看时长 13.8% 居首",
        "summary": (
            "2026 年上半年 YouTube 广告收入接近 210 亿美元；订阅、平台与设备（含 YouTube TV、YouTube Music/Premium、"
            "NFL Sunday Ticket）接近 253 亿美元，两者合计年化接近 930 亿美元。YouTube 广告上半年同比 +12%，"
            "订阅/平台/设备 +17%，两条线仍在扩张。Google 首席商务官 Philipp Schindler 表示「客厅端持续看到很强的动能」。"
            "Nielsen 6 月数据显示 YouTube 占流媒体观看时长的 13.8%，为行业第一，第二名 Netflix 为 7.9%。"
            "参考：Alphabet 2006 年以 16.5 亿美元股票收购 YouTube，当时谷歌自身市值仅 1300 亿美元。"
        ),
        "impact": 3,
        "sentiment": "positive",
        "source_name": "PrimeXBT（引述 The Motley Fool 与 Nielsen）",
        "source_url": "https://primexbt.ch/news/google-bought-youtube-for-1-65-billion-in-2006-its-now-a-93-billion-business-at",
    },
    {
        "symbol": "GOOGL",
        "occurred_on": "2026-08-15",
        "category": "product_launch",
        "title": "搜索体验重构：5 月起以 AI Overviews / AI Mode 取代「十条蓝链」，AI Mode 零点击率高达 93%",
        "summary": (
            "谷歌于 5 月改造传统搜索体验，放弃延续数十年的「十条蓝链」，转而扩大 AI Overviews 与 AI Mode，"
            "该决定已导致发布商点击率下降，是搜索生态运作方式的重大转变。随搜索体验变化，"
            "面向对话式搜索结果的新广告形式正在出现，如 Highlighted Answers 与 Conversational Discovery Ads。"
            "零点击数据：无 AI Overview 的 Google 搜索为 34%，有 AI Overview 的升至 43%，AI Mode 高达 93%。"
            "AI Overviews 覆盖度：2025 年 2 月约 31% 的追踪查询，至 2026 年 3–4 月升至约 48–60%，"
            "全球月触达用户超 20 亿；8 词以上长查询触发 AI Overview 的概率达 57%。"
            "商业含义：谷歌用 AI 答案守住了九成以上的搜索份额，但把点击让渡给了摘要——"
            "这既是防御 AI 聊天机器人的必要代价，也改变了其与发布商、广告主之间的价值分配。"
        ),
        "impact": 3,
        "sentiment": "neutral",
        "source_name": "PivotNews / Exposure Ninja / ValueAdd VC",
        "source_url": "https://pivotnews.ai/five/big-tech-s-ai-costs-have-surged-can-ad-revenues-keep-up",
    },
    {
        "symbol": "GOOGL",
        "occurred_on": "2026-07-15",
        "category": "macro",
        "title": "谷歌全球搜索份额首次跌破 90%；AI 搜索流量两年增长 16 倍，Gemini 升至聊天机器人份额第二",
        "summary": (
            "StatCounter 2026 年数据显示谷歌全球搜索份额首次跌破 90%（另有口径为 90.46%／91.4%），"
            "这是 AI Overviews 推出一年多之后出现的首次松动。AI 搜索侧：2024–2026 年 AI 搜索流量增长 16 倍"
            "（SE Ranking 对 101,574 个网站的研究）；AI 搜索已占约每 312 次网站访问中的 1 次（2024 年约为每 5000 次中的 1 次）。"
            "份额格局：ChatGPT 占 AI 引荐流量 74.78%（2026 年 6 月约 12 亿 MAU、9000 万+ WAU）；"
            "Gemini 以 11.56% 的引荐份额位居第二，聊天机器人份额 18%–21.5%，并于 2026 年 1 月超越 Perplexity（第三，7.23%）；"
            "Claude 增速最快（同比 +320%，份额 2.62%）；Microsoft Copilot 占 3.51%。"
            "另有数据显示 ChatGPT 的助手市场份额已跌破 50%（2026 年 5 月 46.4%，Sensor Tower），市场呈三分格局。"
            "监管侧：英国 CMA 最终决定中认定谷歌占一般搜索查询超 90%；欧盟委员会的市场调查则认定"
            "Bing 并非终端用户触达商业用户的重要入口。"
        ),
        "impact": 3,
        "sentiment": "neutral",
        "source_name": "GeoAura / Colorlib / SQ Magazine（引述 StatCounter、SE Ranking、Similarweb、CMA）",
        "source_url": "https://geoaura.world/blog/ai-search-market-share-growth",
    },

    # ===================== AAPL =====================
    {
        "symbol": "AAPL",
        "occurred_on": "2026-07-30",
        "category": "earnings",
        "title": "关税退款贡献约 2 个百分点毛利率与每股 0.11 美元；当季回购 259.49 亿美元、派息 39.98 亿",
        "summary": (
            "FY26Q3 毛利率 50.1%（上年同期 46.5%），其中关税退款带来约 2 个百分点的正向影响；"
            "产品毛利率 40.1%（上年同期 34.5%），服务毛利率 75.6%（持平）。产品毛利额与毛利率上升主要受"
            "产品组合变化与关税退款影响，部分被存储器等成本上升抵消。摊薄 EPS 2.02 美元（+29%），"
            "其中关税退款贡献每股 0.11 美元。资本回报：当季回购 259.49 亿美元普通股，支付 39.98 亿股息及等价物；"
            "董事会宣告每股 0.27 美元股息，2026-08-13 派发、08-10 登记。"
            "结构性提示：产品毛利率的同比大幅改善中有相当比例来自一次性的关税退款而非经营改善，"
            "而管理层已明确 Q4 将面临内存与先进制程供给的更大压力，毛利率指引回落至 46%–47%。"
        ),
        "impact": 3,
        "sentiment": "positive",
        "source_name": "华鑫证券研究报告（同花顺转载）/ News9 LIVE",
        "source_url": "https://field.10jqka.com.cn/20260813/c678940096.shtml",
    },
    {
        "symbol": "AAPL",
        "occurred_on": "2026-07-30",
        "category": "earnings",
        "title": "印度年销售额首破 100 亿美元，Mac 收入 +29% 创最佳新客季，活跃设备装机超 25 亿台",
        "summary": (
            "苹果在印度的年销售额首次突破 100 亿美元（截至 2026 年 3 月的财年约 100 亿，上一财年约 90 亿），"
            "巩固其作为 iPhone 增长引擎的地位并降低对中国单一市场的依赖。"
            "FY26Q3 为公司史上最强 6 月季度：美洲、拉美、西欧、印度、中国大陆、日本与东南亚均创 6 月季度收入纪录；"
            "发达市场与新兴市场双创纪录，多数新兴市场实现双位数增长。"
            "Mac 收入 103.52 亿美元（+29%），CFO Kevan Parekh 归功于 MacBook Neo 与 MacBook Pro 的需求，"
            "并称 Mac 在印度、美国与中国大陆均录得有史以来最好的新客与升级季。"
            "服务业务在 FY26Q2 已达创纪录的约 310 亿美元。活跃设备装机量已超 25 亿台。"
            "风险：印度本土制造（富士康、塔塔、纬创）与零售扩张仍在爬坡，且苹果在印度面临反垄断诉讼与潜在巨额罚则。"
        ),
        "impact": 4,
        "sentiment": "positive",
        "source_name": "Edgen（引述 Zacks Equity Research）/ News9 LIVE",
        "source_url": "https://news9live.com/technology/tech-news/apple-india-sales-record-high-mac-revenue-jumps-29-percent-2995183",
    },
    {
        "symbol": "AAPL",
        "occurred_on": "2026-09-01",
        "category": "personnel",
        "title": "App Store 与 Apple Events 换帅：Phil Schiller 在发布会前 9 天卸下活动职责，Nola Weinstein 接管",
        "summary": (
            "Phil Schiller 在 9 月 9 日发布会前 9 天不再负责 Apple Events，使这成为十余年来首个由他人主导的 9 月发布会；"
            "Nola Weinstein 接管该职能并向传播部门汇报。App Store 亦进入新领导班子时代——"
            "新团队希望从规模约 300 亿美元的 App Store 中获取更多价值。"
            "背景：Schiller 自 2011 年起主导苹果发布节奏，其当年的主张是「在业务强劲时主动降费率，看起来是慷慨；"
            "在法院命令下降费率，看起来是失败」。过去十六个月苹果在司法与监管压力下已多次公布新费率表，"
            "每一次都比挑战者期望的保留了更多原有经济利益。Ternus 与 Eddy Cue 继承的是一张「存活下来」的费率表、"
            "一个监管尚未触及的广告业务，以及一个由长期掌舵者决定交棒的应用商店。"
        ),
        "impact": 3,
        "sentiment": "neutral",
        "source_name": "Gadgets Now",
        "source_url": "https://gadgetsnow.indiatimes.com/tech-news/apples-new-leaders-want-more-from-its-30-billion-app-store/articleshow/133865911.cms",
    },
    {
        "symbol": "AAPL",
        "occurred_on": "2026-09-14",
        "category": "regulatory",
        "title": "印度反垄断风险：修订后的竞争法按全球营业额计罚，苹果称面临最高 380 亿美元罚则",
        "summary": (
            "苹果表示，印度修订后的竞争法允许按全球营业额计算罚则，使其面临最高 380 亿美元的罚款风险。"
            "2026 年 5 月，德里高等法院要求监管机构继续推进该案，但在 2026 年 7 月 15 日之前不得作出最终命令；"
            "6 月，苹果同意提交印度专属的财务数据。此后公开记录暂未见更新。"
            "商业背景：Counterpoint Research 数据显示 iPhone 在印度的份额约 9%，较两年前翻倍以上；"
            "苹果在整个诉讼期间持续扩张印度的零售与制造。印度开发者与其他地区开发者支付同样的佣金，"
            "而其监管机构正在争论苹果是否有权向他们收费——这一落差使 App Store 的下一轮费率调整"
            "在德里与在华盛顿一样成为现实问题。"
        ),
        "impact": 4,
        "sentiment": "negative",
        "source_name": "Gadgets Now",
        "source_url": "https://gadgetsnow.indiatimes.com/tech-news/apples-new-leaders-want-more-from-its-30-billion-app-store/articleshow/133865911.cms",
    },
    {
        "symbol": "AAPL",
        "occurred_on": "2026-08-20",
        "category": "macro",
        "title": "供应链去中国化：Counterpoint 估计 2026 年印度可占全球 iPhone 产量约 26%（四年前约 6%）",
        "summary": (
            "路透 8 月报道称印度正在提案延长惠及合同制造商的税收豁免；"
            "Counterpoint 估计 2026 年印度可占全球 iPhone 产量的约 26%，而四年前这一比例仅约 6%。"
            "这种地理多元化在中美贸易紧张持续的背景下具有战略价值，但并不能消除苹果的关税敞口——"
            "公司仍运营着极其复杂的国际供应链。更宏观的含义是：关税正在加速一个已经在发生的结构性转变，"
            "即从「最低成本的全球供应链」转向「更昂贵但地理多元的供应链」。"
            "关键区分在于「卖基础设施的公司」与「买基础设施的公司」："
            "半导体设计商、代工厂、先进封装与本土制造供应商可能从回流中受益；"
            "而云厂商、设备制造商等重型硬件买家即便长期需求强劲，也可能面临更高成本。"
            "苹果的成本压力是双重的：一方面是关税与制造转移的资本开支，另一方面是仅三家核心供应商的内存涨价。"
        ),
        "impact": 3,
        "sentiment": "neutral",
        "source_name": "USnewsSphere（引述 Reuters 与 Counterpoint）",
        "source_url": "https://usnewssphere.com/u-s-tariffs-and-the-ai-supply-chain-which-ame",
    },
]


def main() -> None:
    print("events:", json.dumps(post("/events", {"agent": AGENT, "events": EVENTS}), ensure_ascii=False))


if __name__ == "__main__":
    main()
