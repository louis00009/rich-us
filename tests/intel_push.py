#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""临时脚本：以 agent=workbuddy 向 QuantDesk Bridge 提交一轮情报抓取成果。"""
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
    # ================= MSFT =================
    {
        "symbol": "MSFT",
        "occurred_on": "2026-07-29",
        "category": "earnings",
        "title": "微软 FY26Q4 营收 900 亿美元同比 +18%，Azure 增速升至 43% 且全年收入首破 1000 亿美元",
        "summary": (
            "截至 2026-06-30 的 FY26Q4：营收 900.07 亿美元（+18%，不变汇率 +17%），营业利润 406 亿（+18%），"
            "GAAP 净利 357.66 亿（+31%），GAAP EPS 4.81 美元，剔除 OpenAI 投资影响后的 non-GAAP EPS 4.74 美元（+23%），"
            "均超市场预期（营收预期约 876 亿、EPS 预期 4.24）。Azure 及其他云服务收入同比 +43%（上季 +40%，预期 39.98%），"
            "为 2022 年初以来最快；微软称 Azure 全年收入首次突破 1000 亿美元。Microsoft Cloud 收入 593 亿（+27%），"
            "商业剩余履约义务（RPO）同比 +84% 至 6780 亿美元；M365 Copilot 付费席位超 3000 万（上季 2000 万，预期 2690 万）。"
            "FY27Q1 指引营收 898.5–909.5 亿美元、Azure 增速 45%（预期 41.4%）。当日盘后股价一度涨超 8%。"
        ),
        "impact": 5,
        "sentiment": "positive",
        "source_name": "Microsoft Investor Relations（FY26 Q4 财报新闻稿）",
        "source_url": "https://www.microsoft.com/en-us/Investor/earnings/FY-2026-Q4/press-release-webcast",
    },
    {
        "symbol": "MSFT",
        "occurred_on": "2026-07-29",
        "category": "earnings",
        "title": "FY26Q4 资本支出 410 亿美元同比 +69%，自由现金流 196.4 亿同比 -23%，全年资本支出指引因会计准则变更调至 1750 亿",
        "summary": (
            "第四财季资本支出 410 亿美元、同比 +69%，主要用于半导体等以支持 Azure；公司维持全年资本支出计划，"
            "但因会计准则变更，指引口径由三个月前宣布的 1900 亿美元变为 1750 亿美元，CFO Amy Hood 预计 FY27 资本支出将进一步增长。"
            "本季自由现金流 196.4 亿美元、同比 -23%。公司另将办公楼与数据中心使用寿命由 15 年延长至 25 年。"
            "本季新增尚未开始执行的数据中心租赁承诺超 1300 亿美元，未执行租约总额增至 3291 亿美元。"
        ),
        "impact": 3,
        "sentiment": "neutral",
        "source_name": "澎湃新闻 / 财联社（引述微软财报与电话会）",
        "source_url": "https://m.thepaper.cn/newsDetail_forward_33684012",
    },
    {
        "symbol": "MSFT",
        "occurred_on": "2026-07-08",
        "category": "model_release",
        "title": "自研 MAI 模型接管 Excel/Outlook 等 Copilot 常规任务，Suleyman 称目标是「削减并最终消除」对 Anthropic 的支出",
        "summary": (
            "微软将收件箱摘要、公式生成、简单图表等常规负载路由到自研 MAI 模型（Build 2026 发布 MAI 系列），"
            "同时把 Copilot 与 Azure AI Foundry 建设为多模型路由平台；AI CEO Mustafa Suleyman 公开表示 Anthropic「极其昂贵」，"
            "目标是削减并最终消除这部分成本。背景：2026-04-27 微软与 OpenAI 再次修订协议，微软 IP 许可至 2032 年但改为非独占，"
            "微软停止向 OpenAI 支付收入分成，OpenAI 向微软的收入分成保留至 2030 年但设总额上限。"
            "风险点在于微软未公开披露 Copilot 请求具体由哪个模型完成。"
        ),
        "impact": 4,
        "sentiment": "neutral",
        "source_name": "Tech Times",
        "source_url": "https://techtimes.com/articles/319878/20260708/microsofts-house-ai-takes-over-excel-outlook-squeezing-openai-anthropic.htm",
    },
    {
        "symbol": "MSFT",
        "occurred_on": "2026-08-05",
        "category": "personnel",
        "title": "微软提交 WARN 文件：雷德蒙德总部 493 个 + 普吉特湾 112 个岗位永久裁撤，9 月 4 日生效",
        "summary": (
            "华盛顿州就业安全部公示的 WARN 通知显示，微软永久裁撤雷德蒙德总部园区 493 个岗位及普吉特湾地区 112 个远程岗位，"
            "合计 605 人，2026-09-04 生效。这是全球约 4800 人裁员计划的一部分（约占 22 万员工的 2.1%），Xbox 与销售团队为重灾区："
            "Xbox 部门一次性裁减约 1600 人，并计划在 FY27 内累计至约 3200 人（约占 Xbox 员工五分之一），同时将拆分四家游戏工作室。"
            "Xbox 负责人 Asha Sharma 在内部备忘录中称「我们目前的业务并不健康」，并称 Xbox 利润率比同业低 3–10 倍。"
            "此前 2026 年 4 月微软向 8750 名美国员工提供自愿买断，约 30% 接受；2025 年已在全球裁员约 15000 人。"
        ),
        "impact": 3,
        "sentiment": "negative",
        "source_name": "新浪财经 / IT之家（引述华盛顿州 WARN 文件）",
        "source_url": "https://finance.sina.com.cn/tech/digi/2026-08-05/doc-inimhawc3593409.shtml",
    },
    {
        "symbol": "MSFT",
        "occurred_on": "2026-08-20",
        "category": "personnel",
        "title": "AI 部门首席营销官 Andrea Mallard 上任约半年卸任，Copilot 营销统一交由 Jared Spataro 接管",
        "summary": (
            "据 Business Insider，微软确认 AI 部门首席营销官 Andrea Mallard（原 Pinterest CMO，2026 年 1 月加入）卸任现有职务，"
            "因将于 8 月举家迁居欧洲照料父亲，将以顾问身份服务至明年初，公司暂不计划直接补缺。"
            "Copilot 相关营销将统一交由 Jared Spataro 负责。报道称此次变动与微软 AI 部门战略调整相关："
            "公司正重新梳理面向个人用户的营销模式，推动消费级与企业级 Copilot 整合为统一产品。"
        ),
        "impact": 2,
        "sentiment": "neutral",
        "source_name": "环球网科技（引述 Business Insider）",
        "source_url": "https://dy.163.com/article/L4PF1QKF0514R9OJ.html",
    },
    {
        "symbol": "MSFT",
        "occurred_on": "2026-09-10",
        "category": "product_launch",
        "title": "Copilot Studio 应用生成进入公开预览，Copilot Cowork 推出 /app 技能与 CSP 激活激励",
        "summary": (
            "微软宣布 Copilot Studio 支持用自然语言描述业务应用、生成可运行预览并通过对话迭代（公开预览，按量计费）；"
            "同时在 Frontier 计划下为 Copilot Cowork 引入 /app 技能。9 月 1 日推出 Copilot Cowork CSP 激活激励，"
            "对推动客户采用与用量的合作伙伴给予奖金。另：GitHub Copilot harness 已在 Copilot Studio 正式可用（8 月 GA），"
            "Microsoft 365 管理中心的跨租户 Agent 管理进入公开预览。"
        ),
        "impact": 2,
        "sentiment": "positive",
        "source_name": "Microsoft Tech Community / Microsoft Learn",
        "source_url": "https://techcommunity.microsoft.com/blog/partnernews/september-update-what%E2%80%99s-new-for-partners-in-ai-business-solutions/4553602",
    },

    # ================= GOOGL =================
    {
        "symbol": "GOOGL",
        "occurred_on": "2026-07-22",
        "category": "earnings",
        "title": "Alphabet Q2 营收 1198 亿美元 +24%，Google Cloud +82% 至 248 亿，云积压订单 5140 亿美元",
        "summary": (
            "2026Q2：合并营收 1197.96 亿美元（+24%，不变汇率 +23%），为连续第 12 个季度双位数增长；"
            "Google Services 945 亿（+15%，其中搜索及其他 +17%、YouTube 广告 +13%、订阅/平台/设备 +15%）；"
            "Google Cloud 248 亿（+82%），云经营利润 88 亿（同比三倍有余），经营利润率由 20.7% 升至 35.6%；"
            "云积压订单环比增超 500 亿至 5140 亿美元，公司预计未来 24 个月确认其中略超 50%。"
            "合并营业利润 407.7 亿（+30%），经营利润率 34%（+2pct）。其他收益净额 980 亿美元（主要为股权证券未实现收益），"
            "推动净利至 1121 亿、EPS 9.11 美元（+294%）。资本支出 448.9 亿美元（上年同期 224 亿），"
            "并完成 496 亿美元股权融资；全年资本支出指引由 1800–1900 亿上调至 1950–2050 亿美元。"
            "本季首次确认向客户数据中心交付 TPU 系统所产生的收入。财报后股价盘后跌约 3.4%。"
        ),
        "impact": 5,
        "sentiment": "positive",
        "source_name": "Alphabet 投资者关系（Q2 2026 财报新闻稿 PDF）",
        "source_url": "https://s206.q4cdn.com/479360582/files/doc_financials/2026/q2/2026q2-alphabet-earnings-release.pdf",
    },
    {
        "symbol": "GOOGL",
        "occurred_on": "2026-07-21",
        "category": "model_release",
        "title": "发布 Gemini 3.6 Flash / 3.5 Flash-Lite / 3.5 Flash Cyber，并已启动 Gemini 4 预训练",
        "summary": (
            "财报前一日发布 Gemini 3.6 Flash 与 Gemini 3.5 Flash-Lite（主打性价比），以及 Gemini 3.5 Flash Cyber"
            "（配合 CodeMender 代理可自动发现并修复漏洞，性能对标体量大得多的安全模型）。Gemini 3.5 Pro 正在测试中。"
            "Pichai 称团队已启动「迄今最大规模的一次预训练」用于 Gemini 4。模型 API 每分钟处理约 220 亿 token"
            "（上季度 160 亿），每月有超 900 万开发者基于其模型开发；Gemma 系列累计下载超 9 亿次，Gemma 4 自 4 月发布以来超 3 亿次。"
            "代理式开发平台 Antigravity 周活超 240 万。"
        ),
        "impact": 4,
        "sentiment": "positive",
        "source_name": "Google 官方博客（Alphabet Q2 2026 财报电话会 CEO 发言整理）",
        "source_url": "https://blog.google/company-news/inside-google/message-ceo/alphabet-earnings-q2-2026/",
    },
    {
        "symbol": "GOOGL",
        "occurred_on": "2026-07-23",
        "category": "regulatory",
        "title": "欧盟委员会依《数字市场法》对谷歌罚款 8.9 亿欧元，要求 60 天内整改搜索自我优待与 Play Store 引导规则",
        "summary": (
            "欧盟委员会认定谷歌在搜索结果中优先展示自家购物、酒店、交通、体育等服务构成「自我优待」，罚款 4.6 亿欧元；"
            "并认定其限制应用开发者告知用户可通过 Google Play 以外渠道以更低价格购买服务、阻碍站外交易，罚款 4.3 亿欧元。"
            "合计 8.9 亿欧元（约 10 亿美元）。谷歌须在 60 天内公平、非歧视地对待搜索结果中的第三方服务，"
            "并允许开发者自由向用户介绍优惠、在 Play 商店外完成交易，否则面临追加罚款。"
            "同月 2 日，欧盟法院驳回谷歌上诉，维持 2018 年安卓垄断案 41.25 亿欧元罚款。"
        ),
        "impact": 3,
        "sentiment": "negative",
        "source_name": "新华社 / 人民网（另见 The Verge）",
        "source_url": "https://world.people.com.cn/n1/2026/0724/c1002-40767228.html",
    },
    {
        "symbol": "GOOGL",
        "occurred_on": "2026-09-02",
        "category": "regulatory",
        "title": "美国法院就广告技术垄断案作出救济裁决：驳回拆分 AdX，改采行为性救济，有效期 6 年",
        "summary": (
            "弗吉尼亚东区联邦地区法院 Brinkema 法官（裁决 9 月 2 日作出、9 月 16 日解封）驳回司法部要求剥离 AdX 广告交易所、"
            "开源 DFP 最终竞价逻辑的结构性救济请求，认定行为性救济足以纠正反竞争行为。法院命令包括：禁止将 DFP 与 AdX 捆绑、"
            "禁止恢复 First Look / Last Look 功能、禁止对间接交易适用统一计价规则；要求谷歌构建接口让开源 header bidding 联盟 Prebid "
            "取得 AdX 实时报价并将 AdX 实时报价提交至竞品发布商广告服务器；向发布商开放 DFP 历史与配置数据、AdX 持续报价数据并允许导出；"
            "禁止 AdWords 直接向 DFP 竞价或偏袒谷歌自有工具。另设监督人与 3 人技术委员会，裁决有效期 6 年，60 天后生效。"
            "此前 2025 年 4 月法院已认定谷歌非法垄断发布商广告服务器与广告交易市场。"
        ),
        "impact": 4,
        "sentiment": "positive",
        "source_name": "Digital Watch Observatory（日内瓦互联网平台）",
        "source_url": "https://dig.watch/updates/court-unsealed-decision-on-remedies-set-on-google",
    },
    {
        "symbol": "GOOGL",
        "occurred_on": "2026-04-25",
        "category": "regulatory",
        "title": "搜索反垄断案救济裁决：禁止谷歌就 Search / Chrome / Gemini 签订独家默认分发协议，改为年度续签",
        "summary": (
            "哥伦比亚特区联邦地区法院 Mehta 法官 2026-04-25 作出救济裁决，未支持拆分，但禁止谷歌就 Google 搜索、Chrome、"
            "Google Assistant 与 Gemini 应用签订独家默认分发合同——相关合同改为每年续签，不再允许多年排他安排。"
            "法院同时要求谷歌向合格竞争者开放部分搜索索引与用户交互数据（广告数据被排除在外）。"
            "2025 年 9 月法院已将该案范围扩展至生成式 AI 产品。谷歌表示将就部分内容上诉，上诉预计延续至 2027 年。"
            "注：本条发生在最近 90 天窗口之外，但对 Gemini 分发格局属关键结构性约束，故一并记录。"
        ),
        "impact": 4,
        "sentiment": "neutral",
        "source_name": "The Index Today（引述法院救济裁决及 Brookings 分析）",
        "source_url": "https://www.theindextoday.com?p=1056/",
    },
    {
        "symbol": "GOOGL",
        "occurred_on": "2026-09-23",
        "category": "model_release",
        "title": "DeepMind 负责人称 Gemini 4 将「大幅提前」到来，GOOGL 前一日录得一个月内最大单日跌幅",
        "summary": (
            "据 2026-09-24 财经快讯，DeepMind 负责人表示 Gemini 4 将比预期「早得多」推出，GOOGL 股价在此前录得近一个月最大单日跌幅后企稳。"
            "同期有分析关注谷歌将个人理财功能引入 Gemini 的潜在收益。另有分析师（Gene Munster）认为 Meta 的 Muse 对谷歌构成竞争压力。"
        ),
        "impact": 3,
        "sentiment": "neutral",
        "source_name": "Yahoo Finance / finnhub 新闻流",
        "source_url": "https://finance.yahoo.com/",
    },

    # ================= AAPL =================
    {
        "symbol": "AAPL",
        "occurred_on": "2026-07-30",
        "category": "earnings",
        "title": "FY26Q3 营收 1094 亿美元 +16%、净利 +27%，但服务与大中华区不及预期、Q4 指引低于华尔街，盘后跌超 8%",
        "summary": (
            "截至 2026-06-27 的 FY26Q3：营收 1094.17 亿美元（+16%），净利 297.89 亿（+27%），摊薄 EPS 2.02 美元（+29%）。"
            "iPhone 542.52 亿（+21.7%，占比约 49.6%）、Mac 103.52 亿（+28.7%）、服务 307.39 亿（+12.1%，低于预期 312.2 亿）、"
            "可穿戴/家居 78.83 亿（+6.5%）、iPad 61.91 亿（-5.9%）。大中华区 188.16 亿（+22%，创历史纪录，但低于预期 195 亿）；"
            "美洲 457.81 亿（+11%）、欧洲 293.95 亿（+22%）。CFO Kevan Parekh 指引 FY26Q4 营收同比 +9%–11%"
            "（区间上限低于华尔街一致预期 12.1%），毛利率 46%–47%；称汇率将拖累约 2.5 个百分点，芯片与内存供应短缺的负面影响将环比显著扩大。"
            "财报后盘后股价一度跌超 8%，市值单夜蒸发逾 3000 亿美元。"
        ),
        "impact": 4,
        "sentiment": "negative",
        "source_name": "新华网 / 中国证券报",
        "source_url": "https://www.news.cn/world/20260731/146004397e8b4a58ac90123857d86e21/c.html",
    },
    {
        "symbol": "AAPL",
        "occurred_on": "2026-07-30",
        "category": "macro",
        "title": "库克：需求未走弱但受先进制程自研芯片产能与 DRAM 供给双重限制，内存成本上升且供应商仅三家",
        "summary": (
            "FY26Q3 电话会上，苹果 CEO 蒂姆·库克表示当前终端订单远超供应链承载能力，受先进制程自研芯片产能与 DRAM 内存供给双重限制；"
            "内存成本正在上升，当前内存市场仅有三家核心供应商，苹果正评估扩充供给渠道的全部可能性以缓解成本与供货双重压力。"
            "机构仍看好下半年：分析师普遍认为 iPhone 18 系列、折叠屏 iPhone 与新一代 AI 终端会持续带动硬件销量，"
            "高端机型定价策略可对冲上游元器件涨价带来的利润压力。"
        ),
        "impact": 3,
        "sentiment": "negative",
        "source_name": "百度百科「2026财年第三财季」词条（整理自苹果财报电话会）",
        "source_url": "https://baike.baidu.com/item/2026%E8%B4%A2%E5%B9%B4%E7%AC%AC%E4%B8%89%E8%B4%A2%E5%AD%A3/68436471",
    },
    {
        "symbol": "AAPL",
        "occurred_on": "2026-09-01",
        "category": "personnel",
        "title": "John Ternus 接任苹果 CEO，Tim Cook 在 9 月 9 日发布会上以告别致辞完成交棒",
        "summary": (
            "苹果硬件工程高级副总裁 John Ternus 于 2026-09-01 出任首席执行官，Tim Cook 卸任。"
            "9 月 9 日的「Surprise and Shine」发布会以 Cook 的致辞作结并引出 Ternus，由 Ternus 主讲 iPhone 产品线。"
            "Ternus 在会上表示：「我们在最重要的几个领域取得了巨大进步：智能、性能、电池与相机。」"
            "需要注意的是，苹果的 AI 资本开支持续被市场质疑偏低——Forbes 估算苹果 2025 年 AI 资本支出约 120 亿美元，"
            "远低于谷歌、亚马逊与 Meta（苹果不单独披露该口径）。"
        ),
        "impact": 5,
        "sentiment": "neutral",
        "source_name": "Abt Electronics 发布会实录 / FinanceTracked（引述苹果与 CNBC）",
        "source_url": "https://financetracked.com/apple-siri-ai-iphone-18",
    },
    {
        "symbol": "AAPL",
        "occurred_on": "2026-09-09",
        "category": "product_launch",
        "title": "iPhone 18 / 18 Pro / Pro Max（A20 Pro 2nm）发布，首款折叠屏 iPhone Duo 1999 美元，Pro 系列涨价 100 美元",
        "summary": (
            "9 月 9 日「Surprise and Shine」发布会：iPhone 18 Pro 起售 1199 美元、Pro Max 1299 美元（较上代均涨 100 美元），"
            "搭载 A20 Pro（苹果首款 2nm iPhone 芯片，6 核 CPU + 7 核 GPU + 第二代神经引擎，内存带宽提升 50%）；"
            "Pro Max 视频播放续航达 45 小时（史上最大提升），15 分钟可充至 50%。"
            "首款折叠屏 iPhone Duo 起售 1999 美元，10 月 16 日预售、10 月 23 日上市。iPhone 18 Pro 系列 9 月 12 日开启预购、9 月 18 日上市。"
            "国行 256GB 起售价分别 9999 / 10999 元，较上代均涨 1000 元。影像方面新增可变光圈 48MP 主摄、Pro 级手动控制与 Apple 参考图像（用于验证照片原真性）。"
        ),
        "impact": 5,
        "sentiment": "positive",
        "source_name": "FinanceTracked（引述苹果官方与 CNBC）/ Abt Electronics",
        "source_url": "https://www.abt.com/blog/apple-event-september-2026",
    },
    {
        "symbol": "AAPL",
        "occurred_on": "2026-09-14",
        "category": "model_release",
        "title": "重构版 Siri AI 随 iOS 27 以 beta 上线：跨 30 万+ App 操作、个人上下文理解，初期仅英文且欧盟不上线",
        "summary": (
            "Siri AI 于 2026-09-14 随 iOS 27 以 beta 形式推出，可跨消息/邮件/照片理解个人上下文、回答屏幕内容相关问题、"
            "抓取实时网络信息、在 App 内执行操作并按收件人语气起草文本；支持 30 万+ 第三方 App，配有独立 Siri App 并通过 iCloud 同步对话历史，"
            "重负载请求路由至 Private Cloud Compute。Apple Intelligence 支持 16 种语言，但 Siri AI 首发仅英文；"
            "欧盟的 iOS/iPadOS/watchOS 初期不可用（仅 Mac 与 Vision Pro 可用），中国大陆正式上线时间取决于监管审批进度。"
            "苹果已于 6 月披露：Apple 基础模型是与 Google 及其 Gemini 模型合作构建的。"
            "Live Rewind 与 Siri Recap 将于 2026 年末以 beta 推出（英文、欧盟初期不上线）。"
            "健康方面：Health App 由 Apple Intelligence 驱动，新增 Longevity 标签与 Health Age；"
            "可通过 Health App 预约购买 Quest Diagnostics 的 50+ 项生物标志物检测包（119 美元，约 2000 个网点）。"
        ),
        "impact": 5,
        "sentiment": "positive",
        "source_name": "FinanceTracked（引述苹果发布会与 CNBC）/ 百度百科 iPhone18Pro 系列",
        "source_url": "https://financetracked.com/apple-siri-ai-iphone-18",
    },

    # ================= META =================
    {
        "symbol": "META",
        "occurred_on": "2026-07-29",
        "category": "earnings",
        "title": "Q2 营收 608 亿 +28% 但 EPS 6.18 大幅低于预期 7.22，自由现金流骤降至 7.84 亿，资本支出下限上调至 1300 亿",
        "summary": (
            "2026Q2：营收 608.01 亿美元（+28%，不变汇率 +27%），广告收入 593.63 亿（+27%），Family of Apps 收入 603.70 亿；"
            "净利 158.5 亿（同比 -14%，去年同期 183.4 亿），摊薄 EPS 6.18 美元（预期约 7.22）。"
            "总费用 420.26 亿（+55%），其中含 24 亿美元法律相关费用与 11.8 亿美元遣散费（源自 5 月启动的裁员）；"
            "研发费用率由 27% 升至 36%，管理费用率由 5% 升至 9%。营业利润率由 43% 降至 31%（GAAP 营业利润 188 亿，-8%）；"
            "剔除法律费用与遣散费后营业利润同比 +9%。Family DAP 36.0 亿（+3%），ARPP 16.86 美元（+23.5%）；"
            "广告展示量 +14%、单条广告均价 +12%。Reality Labs 收入 4.31 亿（+16%），经营亏损 46.19 亿。"
            "资本支出（含融资租赁本金支付）310.78 亿（+82.7%）；全年资本支出指引下限上调 50 亿至 1300–1450 亿美元，"
            "全年总费用指引 1650–1690 亿。自由现金流降至 7.84 亿（去年同期 85.5 亿，-90.8%）。"
            "Q3 指引营收 610–640 亿（预期约 631.5 亿）。期末员工超 7.5 万人（环比 -3%），现金及有价证券 903 亿、债务 837 亿。"
            "财报后股价盘后跌约 10%，此前已连续 10 个交易日下跌。"
        ),
        "impact": 5,
        "sentiment": "negative",
        "source_name": "Quartz（引述 Meta 财报与 CNBC）/ MarketBeat 电话会实录",
        "source_url": "https://qz.com/meta-q2-2026-earnings-miss-legal-charges-ai-costs-073026",
    },
    {
        "symbol": "META",
        "occurred_on": "2026-07-15",
        "category": "model_release",
        "title": "Muse Image / Muse Video 交付：Muse Image 在 Arena 文生图等三项测试位列第二，Muse Video 文生视频榜第三",
        "summary": (
            "Meta 超级智能实验室（MSL）旗下 TBD Lab 继 2026 年 4 月发布首款基础模型 Muse Spark 后，"
            "7 月正式发布 Muse Image 并开启 Muse Video 预览：Muse Image 在 Arena 文生图、单图编辑、多图编辑三项测试中位列第二，"
            "仅次于 OpenAI GPT Image 2、力压谷歌 Nano Banana；Muse Video 在文生视频排行榜位列第三，进入第一梯队。"
            "Muse Spark 1.2 于 8 月初更新，重点转向编程、长程 Agent 任务与多模态能力。此外公司已实现 Instagram 上所有公开的 "
            "Reels 与 Feed 帖子自动经 LLM 处理分析，并开始使用 Muse 系列模型做视频主题分类与摘要；"
            "本季在 Reels 上完成史上最大单次排序模型升级，带动 Instagram 会话时长提升 15 个基点。"
        ),
        "impact": 3,
        "sentiment": "positive",
        "source_name": "钛媒体 / 新浪财经",
        "source_url": "https://finance.sina.com.cn/tech/csj/2026-08-14/doc-ininfvzx9456646.shtml",
    },
    {
        "symbol": "META",
        "occurred_on": "2026-08-14",
        "category": "personnel",
        "title": "MSL 多模态负责人余家辉（Jiahui Yu）离职创业，距其带队发布 Muse Spark 1.2 仅 8 天",
        "summary": (
            "2026-08-14，Meta 超级智能实验室核心研究员余家辉在 X 宣布离职创业。其 2025 年 6 月底自 OpenAI 加入，"
            "为 TBD Lab 创始成员与多模态方向负责人，主导 Muse Spark / Voice Mode / Muse Image / Muse Video 系列。"
            "此前扎克伯格亲自挖角，薪酬包一度被传高达 1 亿美元（后经 Meta CTO 澄清为含股票、奖金与绩效条件的整体包）。"
            "这是 MSL 一系列高调离职中的最新一起：此前已至少 8 人离职，包括在 Meta 任职 10 年的 Chaya Nayak（转投 OpenAI）、"
            "任职 12 年的 Birch Mart（加入 Anthropic），以及从苹果挖来、任职半年即跳槽 OpenAI 的庞若鸣。"
        ),
        "impact": 4,
        "sentiment": "negative",
        "source_name": "钛媒体 / 新浪财经",
        "source_url": "https://www.tmtpost.com/8103821.html",
    },
    {
        "symbol": "META",
        "occurred_on": "2026-09-10",
        "category": "personnel",
        "title": "TBD Lab 核心成员 Andrew Tulloch 离职加盟 Anthropic，负责 Claude Code 推理性能优化",
        "summary": (
            "2026-09-10 前后，由 Alexandr Wang 领导、被视为扎克伯格 AI 战略核心的 TBD Lab 核心成员 Andrew Tulloch 宣布离职，"
            "下一步加盟 Anthropic 负责 Claude Code 推理性能优化。Tulloch 曾在 Meta 工作 11 年，后联合创办 Thinking Machines Lab，"
            "2025 年 10 月底被扎克伯格亲自挖回（据报 6 年总包约 15 亿美元，该数字存在争议），负责 Muse 多模态模型研发，"
            "至离职仅 11 个月。他特意等到 Meta 发布新一代开源模型系列与消费级助手 Muse 之后才离开。"
            "UCSD 助理教授 Hao Zhang 亦于同期结束在 TBD Lab 的任期离职。激进的高薪策略在内部老员工中引发不满，"
            "被认为是团队氛围紧张、人才持续流失的原因之一。"
        ),
        "impact": 4,
        "sentiment": "negative",
        "source_name": "今日头条 / ABAB News（引述社交平台公开声明）",
        "source_url": "https://www.ababnews.com/news/fe6a895e-73e5-485d-8df9-bf985661f857",
    },
    {
        "symbol": "META",
        "occurred_on": "2026-09-24",
        "category": "product_launch",
        "title": "Meta 推出更低价 AI 眼镜，扎克伯格称 Muse 对「海量 token」保持免费，Walmart / Sephora / Best Buy 接入购物场景",
        "summary": (
            "据 2026-09-24 财经快讯：Meta 发布定价更低的 AI 眼镜（SPECS），扎克伯格表示 Muse 将对「数量极大的 token」保持免费，"
            "Walmart、Sephora、Best Buy 等零售商已接入以支撑购物场景。扎克伯格同时承认 AI 的进展速度超过了元宇宙愿景，"
            "推动公司战略转向。另有报道称 Meta 新 VR 眼镜直接对标苹果。"
            "风险提示：Gene Munster 预计 Meta 在 Connect 主题演讲后股价「持平至走低」。"
        ),
        "impact": 4,
        "sentiment": "positive",
        "source_name": "Yahoo Finance / finnhub 新闻流",
        "source_url": "https://finance.yahoo.com/",
    },

    # ================= AMZN =================
    {
        "symbol": "AMZN",
        "occurred_on": "2026-07-30",
        "category": "earnings",
        "title": "Q2 营收 2006 亿 +20%，AWS +36.7% 创 18 个季度最快，积压订单 4960 亿，全年资本开支上调至约 2200 亿",
        "summary": (
            "2026Q2（截至 6/30）：净销售额 2006 亿美元（+20%，剔除汇率后 +20%），超市场预期约 1965 亿；"
            "经营利润 274.61 亿（+43%，预期约 236 亿），经营利润率 13.7%（+2.3pct）。"
            "AWS 收入 422.32 亿（+36.7%，连续第五个季度加速，为 2021 年以来最快、18 个季度最快），年化收入规模约 1690 亿美元，"
            "积压订单 4960 亿美元；AWS 经营利润 166.21 亿，经营利润率约 39.4%（同比 +6.5pct，显著高于预期约 34%），"
            "贡献公司约 61% 的经营利润。北美 1161.77 亿（+16%，OPM 7.9%）、国际 421.97 亿（+15%，OPM 4.1%）、广告 198 亿（+26%）。"
            "净利 626 亿（+245%），其中包含来自 Anthropic 投资的 534 亿美元税前非经营性其他收益，稀释后 EPS 5.75 美元。"
            "Q2 资本支出净额约 531 亿（+69%），二季度资本开支 542 亿；全年现金资本开支指引上调至约 2200 亿美元（此前约 2000 亿）。"
            "TTM 经营现金流 1614 亿（+33%），但 TTM 自由现金流转为净流出 76 亿美元（去年同期为净流入 182 亿）。"
            "Q3 指引：营收 1970–2020 亿（+9%–12%，剔除 Prime Day 分布影响增速高约 400bp），经营利润 225–265 亿。"
            "财报后股价盘后一度涨近 10%，次日收涨 15.32%。"
        ),
        "impact": 5,
        "sentiment": "positive",
        "source_name": "Amazon 向 SEC 提交的 8-K 附件（Q2 2026 财报新闻稿）",
        "source_url": "https://www.sec.gov/Archives/edgar/data/1018724/000101872426000024/amzn-20260630xex991.htm",
    },
    {
        "symbol": "AMZN",
        "occurred_on": "2026-07-30",
        "category": "partnership",
        "title": "Trainium 获 Anthropic 与 OpenAI 多年期多吉瓦级采购承诺，AI 与自研芯片年化收入双双突破 250 亿美元",
        "summary": (
            "AWS 的 AI 业务年化收入运行率已超 250 亿美元（三位数同比增长），自研芯片业务年化收入运行率同样超 250 亿美元（三位数增长）。"
            "Trainium 方面，全球最大的两家 AI 实验室 Anthropic 与 OpenAI 均作出多年、多吉瓦级承诺；"
            "越来越多 AI 初创公司采用 Trainium，包括 NEURA Robotics、Odyssey、TwelveLabs、Decart、Poolside、Karakuri、"
            "Metagenomi Therapeutics、NetoAI、Splash Music，以及 Uber、Pinterest 等较大规模公司。Graviton5 客户收入承诺环比增长近 2 倍。"
            "CEO Andy Jassy 表示即便达到 2200 亿美元支出规模，仍无法满足 2026 年的全部需求，并预计供不应求将延续到 2027 年，"
            "且已看到「十分惊人的 2028 年需求量」；内存价格上涨也推高了资本开支预期。"
        ),
        "impact": 4,
        "sentiment": "positive",
        "source_name": "Amazon 向 SEC 提交的 8-K 附件（Q2 2026 财报新闻稿）",
        "source_url": "https://www.sec.gov/Archives/edgar/data/1018724/000101872426000024/amzn-20260630xex991.htm",
    },
    {
        "symbol": "AMZN",
        "occurred_on": "2026-09-24",
        "category": "other",
        "title": "亚马逊屏蔽 Meta 的 AI 购物代理，而 Shopify 选择开放并按结账抽成",
        "summary": (
            "据 2026-09-24 财经快讯，亚马逊阻止了 Meta 的 AI 购物代理访问其平台，而 Shopify 选择接纳该代理并对每笔结账收取分成。"
            "该事件反映电商入口在 Agent 时代的控制权争夺：亚马逊倾向于把交易闭环留在自有生态内，"
            "这可能限制第三方通用购物代理在亚马逊商品上的可用性，但也降低了被「去中介化」的风险。"
        ),
        "impact": 2,
        "sentiment": "neutral",
        "source_name": "Yahoo Finance / finnhub 新闻流",
        "source_url": "https://finance.yahoo.com/",
    },

    # ================= AVGO =================
    {
        "symbol": "AVGO",
        "occurred_on": "2026-09-02",
        "category": "earnings",
        "title": "FY26Q3 营收 295.9 亿 +86%，AI 半导体 167 亿 +221%，自由现金流率 46%，Q4 指引 348 亿 +93%",
        "summary": (
            "FY26Q3（截至 2026-08-02）：净营收 295.91 亿美元（+86%），半导体解决方案 208.39 亿（+127%，占总营收 70%）、"
            "基础设施软件 87.52 亿（+29%）。GAAP 营业利润 159.55 亿（+171%），non-GAAP 营业利润 200.95 亿（+92%），"
            "non-GAAP 营业利润率 67.9%；GAAP 稀释 EPS 2.68（+215%），non-GAAP EPS 3.32（+96%）。"
            "经营现金流 141.97 亿，扣除 5 亿资本支出后自由现金流 136.65 亿，占营收 46%。期末现金 240 亿（环比 +43 亿），"
            "本季偿还 56 亿长期债务，季后又偿还 15 亿优先票据。季度股息 0.65 美元/股（本季派发 31 亿）。"
            "AI 半导体收入 167 亿美元，同比 +221%、环比 +54%，占公司总营收 56%（上季 49%）；XPU 出货量同比增长超 3.5 倍，占 AI 收入 73%；"
            "AI 网络收入同比增长超 2.5 倍。Q4 指引：合并营收约 348 亿（+93%），其中 AI 半导体 217 亿（+236%），半导体约 261 亿，"
            "基础设施软件约 87 亿（+25%），non-GAAP 营业利润率约 66%。注：Q4 指引略低于华尔街一致预期 350.5 亿。"
        ),
        "impact": 5,
        "sentiment": "positive",
        "source_name": "Broadcom 官方新闻稿（2026-09-02）",
        "source_url": "https://jp.broadcom.com/company/news/apj/financial-releases/64671",
    },
    {
        "symbol": "AVGO",
        "occurred_on": "2026-09-02",
        "category": "partnership",
        "title": "与 Google 签署长期 TPU 协议（未来数年每年数百亿美元），并量产交付 Ironwood TPU v7 / TPU v8i 与 OpenAI 首代 Jalapeño",
        "summary": (
            "本季向 Anthropic 与 Google 大批量交付 Ironwood TPU v7，开始量产 Google 下一代 TPU v8i（面向推理优化，"
            "管理层称性能可比甚至优于 Vera Rubin GPU），并出货 OpenAI 首代定制加速器 Jalapeño（管理层称在部分推理负载上优于 Grace Blackwell GPU）。"
            "与 Google 达成长期协议，共同开发并供应未来数代 TPU 与 AI 网络，未来数年每年交付规模达「数百亿美元」级别。"
            "客户部署路线图：Anthropic 2026 年部署 1GW Ironwood，2027 年再部署 5GW TPU v8i，2028 年再增 10GW；"
            "OpenAI 的 Jalapeño 计划 2027 年部署 1.3GW，2028 年有超过 5GW 的可见度；Meta 方面将于 2027 年底前交付三代 MTIA 加速器，"
            "并有到 2028 年部署 3GW 的可见度。Q4 预计开始量产交付 Meta 的定制 MTIA。"
        ),
        "impact": 5,
        "sentiment": "positive",
        "source_name": "Nasdaq（Broadcom Q3 财报电话会要点）/ TipRanks",
        "source_url": "https://www.nasdaq.com/articles/broadcom-q3-earnings-call-highlights",
    },
    {
        "symbol": "AVGO",
        "occurred_on": "2026-09-02",
        "category": "earnings",
        "title": "给出罕见多年 AI 指引：FY26 AI 收入 580 亿、FY27 约 1150 亿、FY28 约 2300 亿，FY28 EPS 目标超 30 美元",
        "summary": (
            "公司将 FY2026 AI 收入指引由 560 亿上调至 580 亿美元（+186%），并首次给出多年可见度："
            "FY2027 AI 半导体收入约 1150 亿美元、FY2028 约 2300 亿美元，称已锁定支撑 FY27 的供应并对 FY28 所需供应有可见度，"
            "且 FY2028 EPS 目标超过 30 美元。Hock Tan 强调「这是真实需求」，但公司已按客户数据中心的实际部署节奏（土地/电力/机壳可得性）"
            "做了折算，当前需求其实高于 FY27 展望。产能侧：计划两年内将磷化铟与激光器产能提升三倍，并在新加坡建设基板产能。"
            "融资侧：已通过 Apollo Global Management 与 Blackstone 的融资工具支持 Anthropic 相关的 Google 芯片部署，"
            "目标是支撑 20GW 以上算力；公司称未宣布新的残值担保或兜底，未来结构将逐案评估。"
        ),
        "impact": 5,
        "sentiment": "positive",
        "source_name": "Nasdaq（Broadcom Q3 财报电话会要点）/ Futurum Group",
        "source_url": "https://futurumgroup.com/insights/broadcom-q3-fy-2026-can-custom-silicon-sustain-ai-growth",
    },
    {
        "symbol": "AVGO",
        "occurred_on": "2026-09-02",
        "category": "product_launch",
        "title": "Tomahawk 6（100T）全面铺开，Tomahawk 7 流片成业界首款 200T 以太网交换芯片，Tomahawk Ultra 开始部署",
        "summary": (
            "AI 网络收入同比增长超 2.5 倍。Broadcom 率先推出 100T Tomahawk 6，并称其已部署在几乎所有与其合作构建 XPU 的 AI 超大规模客户、"
            "以及不使用 Broadcom XPU 的客户中；面向 scale-up 低时延以太网的 Tomahawk Ultra 采用情况超预期，本季开始部署并将延续至 FY27；"
            "Tomahawk 7 已完成流片，为业界首款 200Tbps 以太网交换芯片。公司同时保持在 PCIe 交换与光 DSP 上的领先。"
            "基础设施软件方面：Q3 收入 87.52 亿（+29%），ARR 增长 15%，软件经营利润率约 84%（同比 +6.5pct），毛利率 94%；"
            "发布 VMware Private AI Cloud，并推动客户将负载从公有云回迁至私有云。"
        ),
        "impact": 3,
        "sentiment": "positive",
        "source_name": "Nasdaq（Broadcom Q3 财报电话会要点）/ TipRanks",
        "source_url": "https://www.nasdaq.com/articles/broadcom-q3-earnings-call-highlights",
    },

    # ================= AMD =================
    {
        "symbol": "AMD",
        "occurred_on": "2026-08-05",
        "category": "earnings",
        "title": "Q2 营收 115 亿美元 +50% 创纪录，数据中心 67 亿 +107%（占比 58%），Q3 指引约 130 亿 +41%",
        "summary": (
            "2026Q2：营收 115 亿美元（+50%，环比 +13%），创单季纪录；GAAP 毛利率 54%，GAAP 营业利润 20 亿，净利 23 亿，稀释 EPS 1.38 美元；"
            "non-GAAP 毛利率 56%（同比 +200bp 以上、环比 +80bp），non-GAAP 营业利润 31 亿（OPM 27%，同比 +15pct），non-GAAP 净利 28 亿，EPS 1.66 美元（+82%）。"
            "数据中心 67 亿（+107%），占营收 58%（去年同期 42%），分部营业利润 21 亿（31% 分部利润率）；服务器 CPU 连续第五个季度创纪录，"
            "云与企业销售各同比 +70% 以上。客户端与游戏 38 亿（+6%）：客户端 31 亿（+23%，移动处理器创纪录、Ryzen PRO +50%），"
            "游戏 7.79 亿（-31%，因半定制 SoC 出货减少）。嵌入式 9.77 亿（+19%），分部营业利润 3.86 亿（40% 利润率）。"
            "资本支出 8.08 亿（同比近三倍），经营现金流 24 亿，自由现金流 16 亿，期末现金及短期投资 131 亿。"
            "Q3 指引：营收约 130 亿 ±3 亿（中点同比 +41%），non-GAAP 毛利率约 56%，non-GAAP 营业费用约 36.5 亿。"
            "注：去年同期含 8 亿美元 MI308 出口管制相关存货减值，基数偏低。"
        ),
        "impact": 5,
        "sentiment": "positive",
        "source_name": "AMD 官方新闻稿（2026 年第二季度财报）",
        "source_url": "https://amd.com/zh-cn/newsroom/press-releases/amd-2q-2026-earnings.html",
    },
    {
        "symbol": "AMD",
        "occurred_on": "2026-08-05",
        "category": "partnership",
        "title": "与 Anthropic 达成战略合作：最多部署 2GW MI450（Helios），首个 GW 于 2027 上半年落地",
        "summary": (
            "AMD 宣布与 Anthropic 建立战略合作，将在 Helios 机架配置中部署最多 2GW 的 MI450 系列 GPU，"
            "首个 GW 计划于 2027 上半年开始部署，并展开多年合作以用 Claude 模型优化底层 ROCm 软件栈。"
            "Helios 机架级 AI 平台（EPYC Venice + MI450 系列 GPU + Pensando 网络 + ROCm）已投产，"
            "公司称同机架功耗下吞吐最高提升 15%、每美元 token 数最高提升 30%；初期出货于 Q3 晚些时候开始，Q4 至 2027 年放量。"
            "Helios 已被 Anthropic、Meta、Microsoft、OpenAI、Oracle 等采用；与微软的合作扩展至在 Azure 上大规模部署 Helios 机架用于前沿模型推理，"
            "并新增两个 EPYC 驱动的 VM 系列。另有与 OpenAI、Meta 的多代际部署承诺。Lisa Su 称 Helios 的需求量超出公司最初预测。"
        ),
        "impact": 5,
        "sentiment": "positive",
        "source_name": "The Markets Daily（AMD Q2 2026 财报电话会要点）/ TipRanks",
        "source_url": "https://www.themarketsdaily.com/2026/08/04/advanced-micro-devices-q2-earnings-call-highlights.html",
    },
    {
        "symbol": "AMD",
        "occurred_on": "2026-08-05",
        "category": "product_launch",
        "title": "第六代 EPYC Venice（Zen 6 / 2nm）投产，发布 ROCm.ai 并上调长期 TAM 与财务目标",
        "summary": (
            "第六代 EPYC Venice（Zen 6 架构、2nm 制程，30+ SKU）已投产，OEM 与主要云厂商计划于年内推出平台/开始部署；"
            "公司称其每瓦性能为领先 x86 的 2 倍以上、为领先 ARM CPU 的最多 3.3 倍。软件侧发布 ROCm.ai，"
            "称对多数模型较 ROCm 7 提供 2 倍以上训练性能与 3 倍推理性能；超 300 万个模型可在 AMD 上开箱即跑，开源 ROCm 贡献同比增超 10 倍。"
            "公司上调长期市场假设：数据中心 AI 加速器 TAM 年均增长 >45% 至 2030 年约 1.4 万亿美元；"
            "服务器 CPU 市场年均增长 >50% 至 2030 年约 2200 亿美元；高性能与 AI 计算整体约 40% CAGR、2030 年接近 2 万亿美元。"
            "公司称整体营收增速将「大幅高于」此前 >35% 的目标，并在战略期内「显著超过」20 美元的年度 EPS 目标。"
            "Lisa Su 预计下半年服务器 CPU 业务同比 +80% 以上、2027 年 +70% 以上，2027 年数据中心分部营收将翻倍以上；"
            "但 2026 年服务器 CPU 供应偏紧，2027 年才有望改善。"
        ),
        "impact": 4,
        "sentiment": "positive",
        "source_name": "AMD 官方新闻稿 / The Markets Daily（财报电话会要点）",
        "source_url": "https://www.themarketsdaily.com/2026/08/04/advanced-micro-devices-q2-earnings-call-highlights.html",
    },
    {
        "symbol": "AMD",
        "occurred_on": "2026-08-05",
        "category": "regulatory",
        "title": "出口管制仍是活风险：美国 BIS 持续收紧先进 AI 芯片出口，公司风险披露点名国家安全法规与许可要求",
        "summary": (
            "AMD 的谨慎性披露明确将国家安全法规与许可要求列为可能影响未来业绩的重大因素。"
            "去年 Q2 曾因美国政府对 Instinct MI308 GPU 的出口管制计提 8 亿美元存货减值，压低了基数；"
            "随着美国工业与安全局（BIS）持续收紧对特定司法管辖区的先进 AI 芯片出口限制，"
            "AMD 向非盟友市场销售 Instinct GPU 的能力将在 2026 下半年持续成为投资者关注变量。"
            "此外，财报后市场讨论集中在两点：股价突破 600 美元后是否拆股，以及 AMD 年内 +187%（对比英伟达 +22%）后的估值透支风险。"
        ),
        "impact": 3,
        "sentiment": "negative",
        "source_name": "The Datatech Times / Yahoo Finance 新闻流",
        "source_url": "https://datatech.disruptsmedia.com/semiconductors/amd-posts-record-115bn-q2-revenue-data-centre-sales-double",
    },
]

ANALYSES: list[dict] = [
    {
        "symbol": "MSFT",
        "recommendation": "buy",
        "confidence": 72.0,
        "horizon": "position",
        "thesis": (
            "Azure 是本轮最硬的证据：FY26Q4 增速升至 43% 且公司指引 FY27Q1 进一步到 45%，全年 Azure 收入首破 1000 亿美元，"
            "商业 RPO 同比 +84% 至 6780 亿美元（约为全年营收的两倍），意味着未来数个季度的收入可见度极高。"
            "M365 Copilot 付费席位一个季度从 2000 万增至 3000 万，说明企业级 AI 需求正在转化为可计量的席位收入，"
            "而非停留在概念验证。差异化护城河在于：微软 IP 许可至 2032 年虽改为非独占，但期限已成为固定日历日（不再挂钩 AGI 认定），"
            "同时自研 MAI 系列把常规推理负载内部化，长期压低单位 token 成本——这是 Copilot 毛利率的关键杠杆。"
            "估值与图形：现价 500.59，距 52 周高点 -8.85%，站上 SMA200 约 16.3%，RSI 56.3、ADX 31.7 处于健康上升趋势而非超买，"
            "1 年回报仅 -1.89%（相对本轮 AI 行情明显落后），是七家里「基本面加速 + 图形未透支」组合最干净的一个。"
        ),
        "catalysts": (
            "1) FY27Q1（10 月底）财报验证 Azure 45% 指引；2) Copilot 席位从 3000 万向 4000–5000 万爬坡；"
            "3) MAI 模型替代第三方推理带来的 Copilot 毛利改善；4) 6780 亿美元 RPO 逐步转化为收入；"
            "5) 数据中心折旧年限由 15 年延至 25 年，会计上抬升后续利润率。"
        ),
        "risks": (
            "1) 资本支出 410 亿/季且 FY27 继续增长，自由现金流已同比 -23%；2) Xbox 减值 + 全球 4800 人裁员、Xbox 累计裁至 3200 人，"
            "管理层自认该业务「不健康」；3) Copilot 多模型路由未公开透明，存在「同等价格、更弱模型」的口碑反噬风险；"
            "4) OpenAI 关系非独占化后，长期来看微软对前沿模型的议价力下降；5) AI 部门高管流动（CMO 半年卸任）。"
        ),
        "position_pct": 7.0,
        "invalidation": (
            "Azure 同比增速跌破 35%，或商业 RPO 环比首次出现不增/转负，或 Copilot 付费席位连续两季低于 500 万净增——"
            "任一触发即下调至 hold。技术面跌破 SMA50（约 471）且伴随 Azure 指引下修则直接离场。"
        ),
    },
    {
        "symbol": "GOOGL",
        "recommendation": "buy",
        "confidence": 68.0,
        "horizon": "position",
        "thesis": (
            "云是本轮最大亮点：Q2 Google Cloud +82% 至 248 亿、经营利润率从 20.7% 拉到 35.6%、积压订单环比增超 500 亿至 5140 亿美元，"
            "且公司明确未来 24 个月将确认其中略超 50%——这是极罕见的中期收入可见度。本季首次确认 TPU 系统交付客户数据中心产生的收入，"
            "说明自研芯片从内部成本项转为外部收入项，是估值重估的潜在触发点。"
            "反垄断尾部风险显著收敛：搜索案救济未拆分、仅限制独家默认分发（改年度续签）；广告技术案 9 月 2 日明确驳回 AdX 剥离，"
            "改行为性救济 6 年——两个最大的结构性风险都被排除。Gemini 侧：API 每分钟 220 亿 token（环比 160 亿）、"
            "Gemini App 9.5 亿 MAU、AI Mode 破 10 亿 MAU、Gemini 4 预训练已启动。"
            "图形上现价 337.83 几乎正好压在 SMA200（+0.08%），ADX 13.8 无趋势、RSI 45.1 中性，3 个月 -2.1% 明显跑输同业，"
            "属于「基本面在加速、股价在横盘消化」的蓄势形态。"
        ),
        "catalysts": (
            "1) 5140 亿美元云积压订单在未来 24 个月确认过半；2) Gemini 4 提前发布（DeepMind 负责人已公开暗示）；"
            "3) TPU 外销放量带来新的收入与毛利结构；4) 广告技术案行为性救济落地、不确定性出清；"
            "5) 与苹果的合作（Apple 基础模型基于 Gemini 构建）随 Siri AI 铺开而放大。"
        ),
        "risks": (
            "1) 全年资本支出上调至 1950–2050 亿美元并完成 496 亿股权融资，稀释与折旧压力实实在在；"
            "2) Q2 净利 1121 亿中约 980 亿来自股权证券未实现收益，不可持续，未来季度可能造成难看的同比基数；"
            "3) 欧盟 DMA 8.9 亿欧元罚款 + 60 天整改，搜索自我优待规则改变可能侵蚀购物/旅游类变现效率；"
            "4) 广告技术行为性救济（开放 Prebid 接口、数据可移植）长期削弱 AdX 的定价权；"
            "5) 搜索入口面临 Gemini/AI 助手的自我蚕食与 Meta Muse 等竞品分流。"
        ),
        "position_pct": 8.0,
        "invalidation": (
            "云增速回落至 60% 以下，或云积压订单连续两季环比不增，或搜索广告收入同比增速跌破 10%——任一触发即下调至 hold。"
            "股价有效跌破 SMA200（约 338）并收在 320 下方则先减半仓。"
        ),
    },
    {
        "symbol": "AAPL",
        "recommendation": "hold",
        "confidence": 64.0,
        "horizon": "swing",
        "thesis": (
            "基本面不差但价格已经先走完：现价 337.02 距 52 周高点仅 -2.41%，今年以来 +24.7%、近 1 个月 +8.6%，"
            "RSI 62.9 偏热，估值层面已有第三方测算认为存在约 32% 的高估。FY26Q3 虽然营收 +16%、净利 +27%、大中华区 +22% 创纪录，"
            "但服务收入 307.39 亿低于预期 312.2 亿、大中华区 188 亿低于预期 195 亿，FY26Q4 指引 +9%–11% 的上限低于华尔街 12.1%，"
            "财报后盘后一度跌超 8%——说明市场定价的是「低于预期的边际变化」而非绝对增速。"
            "最关键的是供给端约束：库克明确终端订单超过供应链承载能力，先进制程自研芯片产能与 DRAM 双重受限，"
            "内存只有三家核心供应商且成本上升，iPhone/Mac/iPad 三条线都会受产能约束。这意味着即便 iPhone 18 / 折叠屏 iPhone Duo 需求强劲，"
            "短期也兑现不成收入。CEO 由 Tim Cook 换为 John Ternus 是十年来最大治理变化，方向尚待验证。"
            "结论：不追高，等回踩 SMA50（约 321）或 Q4 指引上修再介入。"
        ),
        "catalysts": (
            "1) iPhone 18 Pro（A20 Pro 2nm，续航 45 小时）9 月 18 日上市 + 折叠屏 iPhone Duo 10 月 23 日上市，10 月季度与 12 月季度备货；"
            "2) Siri AI 从 beta 转正、支持语言从英文扩展到 16 种（含简繁体中文），以及中国大陆监管审批落地；"
            "3) 大中华区在 iPhone 17 周期已见 IDC 出货 +24.4% 的份额回升；4) 服务业务增速若重回 15% 以上；"
            "5) 内存/先进制程供给缓解后 Q4 指引上修。"
        ),
        "risks": (
            "1) 内存与先进制程供给约束环比扩大，直接压制 Q4 与明年 Q1 出货；2) 汇率预计拖累增速约 2.5 个百分点，毛利率指引仅 46%–47%；"
            "3) Siri AI 欧盟初期不上线、中国大陆取决于监管审批，AI 卖点在两个重要市场缺位；"
            "4) Apple 基础模型依赖 Google Gemini 构建，AI 自主性与议价力受限，且 AI 资本开支（Forbes 估算约 120 亿/年）远低于同业；"
            "5) CEO 更替带来的执行不确定性；6) Meta 新 VR/AI 眼镜直接对标苹果硬件生态。"
        ),
        "position_pct": 4.0,
        "invalidation": (
            "升级为 buy 的条件：FY26Q4 指引上修至 +12% 以上，或大中华区同比重回 20%+ 且服务增速回到 15%+。"
            "降级为 reduce 的条件：iPhone 出货受供给约束导致 Q4 营收同比跌破 8%，或 Siri AI 中国大陆审批被长期搁置。"
        ),
    },
    {
        "symbol": "META",
        "recommendation": "hold",
        "confidence": 60.0,
        "horizon": "swing",
        "thesis": (
            "广告引擎依然是全行业最强之一：Q2 营收 +28%、ARPP +23.5%、展示量 +14%、均价 +12%，"
            "Instagram 全球使用时长双位数增长，Reels 完成史上最大单次排序模型升级带来 15bp 会话提升，"
            "FoA 其他收入首破 10 亿（+73%，WhatsApp 付费消息与订阅驱动）。但财报暴露了三个真问题："
            "一是 EPS 6.18 大幅低于预期 7.22，费用 +55%（含 24 亿法律费用与 11.8 亿遣散费），营业利润率从 43% 掉到 31%；"
            "二是自由现金流从 85.5 亿塌到 7.84 亿（-90.8%），全年资本支出下限上调至 1300 亿、上限 1450 亿；"
            "三是超级智能实验室人才持续失血——余家辉（Muse 多模态主导者）8 月离职创业，Andrew Tulloch 9 月离职加盟 Anthropic，"
            "此前已有 Chaya Nayak 等至少 8 人出走。花 6 年 15 亿美元买来的核心研究员 11 个月就走，"
            "说明 MSL 的组织与路线博弈（商业化落地 vs 前沿 AGI 探索）尚未理顺。"
            "图形上极度拉伸：现价 744.10 高于 SMA20 达 16.02%、高于 SMA50 达 21.66%，RSI 77.0 明确超买，"
            "近 1 个月 +33.21%、近 3 个月 +33.54%，距 52 周高点仅 -3.11%。在这种位置上叠加 EPS 不及预期与核心人才流失，"
            "风险收益比很差。持仓可以拿，此价位不新增。"
        ),
        "catalysts": (
            "1) 更低价 AI 眼镜（SPECS）放量 + Muse 对「海量 token」免费，Walmart / Sephora / Best Buy 接入购物场景；"
            "2) Muse Image / Muse Video 已进入第一梯队（Arena 文生图第二、文生视频第三）；"
            "3) LLM 驱动的排序与推荐持续提升 ARPP；4) Reality Labs 收入 +16%（AI 眼镜对冲 Quest 下滑）；"
            "5) 与 BlackRock 合资建设埃尔帕索 1GW 数据中心。"
        ),
        "risks": (
            "1) 资本支出 1300–1450 亿 + 全年费用 1650–1690 亿，自由现金流几近归零；2) 青少年相关社交媒体诉讼年内开庭，"
            "公司已提示可能产生重大损失（本季已计提 24 亿法律费用）；3) MSL 核心人才持续流向 OpenAI / Anthropic 或自行创业；"
            "4) Reality Labs 单季经营亏损 46.19 亿且在扩大；5) 技术面严重超买，回踩 SMA20（约 641）的空间超过 -14%；"
            "6) 亚马逊已屏蔽 Meta 的 AI 购物代理，Agent 电商闭环受阻。"
        ),
        "position_pct": 3.0,
        "invalidation": (
            "升级为 buy 的条件：回踩 SMA20（约 641）且不破，同时 Q3 财报 EPS 回到同比正增长、自由现金流环比转正。"
            "降级为 reduce 的条件：跌破 SMA20 后连续三日收在下方，或再有一名 MSL 核心研究员离职，或法律计提超 30 亿。"
        ),
    },
    {
        "symbol": "AMZN",
        "recommendation": "buy",
        "confidence": 70.0,
        "horizon": "position",
        "thesis": (
            "AWS 增速 36.7% 是 18 个季度以来最快，且已连续五个季度加速——这与「云竞争加剧、份额被抢」的流行叙事相反。"
            "更关键的是质量：AWS 经营利润率 39.4%（同比 +6.5pct，远超市场预期的约 34%），以约 21% 的营收贡献了约 61% 的经营利润，"
            "说明加速不是靠降价换量。积压订单 4960 亿美元提供中期可见度，AI 业务与自研芯片业务年化收入双双突破 250 亿美元且三位数增长，"
            "Trainium 拿到 Anthropic 与 OpenAI 的多年期多吉瓦级承诺——自研芯片是 AWS 毛利结构的长期杠杆。"
            "零售侧也稳：北美 +16%、国际 +15%、广告 +26%，Prime 当日/次日达商品数同比 +40% 以上。"
            "图形上现价 249.27 低于 SMA20/SMA50 约 2.3%/2.7%，RSI 44.1 中性偏弱，ADX 10.9 无趋势，距 52 周高点 -13.21%，"
            "但仍在 SMA200 上方 3.59%——即财报后的跳涨（当日收涨 15.32%）已被完全回吐，属于「好财报后的回调买入窗口」。"
            "主要代价是资本开支：全年上调至约 2200 亿美元，TTM 自由现金流转为 -76 亿。"
        ),
        "catalysts": (
            "1) AWS 连续加速的第五个季度若延续到 Q3（10 月底财报）；2) 4960 亿美元积压订单转化；"
            "3) Trainium 在 Anthropic / OpenAI 的多吉瓦承诺进入交付期；4) Graviton5 客户承诺环比近 2 倍增长；"
            "5) 广告业务 +26% 且基数扩大；6) 管理层称 2027 年仍供不应求、2028 年需求「十分惊人」。"
        ),
        "risks": (
            "1) 全年资本开支约 2200 亿美元，TTM 自由现金流已转为 -76 亿，若 AI 需求证伪则折旧压力巨大；"
            "2) Q2 净利 626 亿中约 534 亿来自 Anthropic 投资的非经营性收益，剔除后核心盈利需重新审视，且造成极高同比基数；"
            "3) 内存价格上涨推高资本开支，Jassy 称短期不太可能放缓；4) Q3 指引 +9%–12% 看似降速（含 Prime Day 分布影响与 80bp 汇率逆风）；"
            "5) Agent 电商入口争夺带来新变量（已屏蔽 Meta 购物代理，但也可能被去中介化）。"
        ),
        "position_pct": 7.0,
        "invalidation": (
            "AWS 同比增速回落至 25% 以下，或 AWS 经营利润率跌破 35%（说明加速是靠降价/低毛利负载换来），"
            "或积压订单环比连续两季不增——任一触发即下调至 hold。股价有效跌破 SMA200（约 241）则先减半仓。"
        ),
    },
    {
        "symbol": "AVGO",
        "recommendation": "strong_buy",
        "confidence": 74.0,
        "horizon": "position",
        "thesis": (
            "这是本次七家里基本面与股价背离最大的一个。基本面：FY26Q3 营收 +86%、AI 半导体 +221%（环比 +54%）、"
            "non-GAAP EPS +96%、自由现金流率 46%（单季 136.65 亿），Q4 指引 AI 半导体 217 亿（+236%）；"
            "更重要的是公司给出了罕见的多年可见度——FY26 AI 收入 580 亿、FY27 约 1150 亿、FY28 约 2300 亿，FY28 EPS 目标超 30 美元，"
            "且明确已锁定 FY27 供应、对 FY28 供应有可见度。客户侧不是单点依赖而是平台化：Google（长期协议，未来数年每年数百亿美元 TPU）、"
            "Anthropic（2026 年 1GW Ironwood + 2027 年 5GW + 2028 年 10GW）、OpenAI（Jalapeño，2027 年 1.3GW、2028 年 >5GW）、"
            "Meta（2027 年底前三代 MTIA、2028 年 3GW 可见度）。网络侧 Tomahawk 6 已铺开、Tomahawk 7（业界首款 200T）流片，"
            "AI 网络收入同比 +2.5 倍以上——即使客户的加速器架构变化，网络仍是第二增长曲线。"
            "股价则完全没反映：现价 354.99 距 52 周高点 -28.04%，低于 SMA50 5.91%、低于 SMA200 3.39%，"
            "近 3 个月 -6.92%、近 1 年仅 +5.56%，RSI 44.7 中性。这种「业绩 +86% 而股价 -7%（3 个月）」的剪刀差，"
            "通常源于市场对客户集中度与融资结构的担忧——但 Q4 指引仅略低于一致预期（348 亿 vs 350.5 亿），并不足以解释 28% 的回撤。"
        ),
        "catalysts": (
            "1) Q4 AI 半导体 217 亿（+236%）兑现；2) Meta MTIA 于 Q4 开始量产交付，客户数从 6 个 XPU 客户进一步扩面；"
            "3) Tomahawk 7 / Tomahawk Ultra 在 scale-up 场景放量；4) FY27 AI 收入指引 1150 亿的落地路径在后续财报逐步确认；"
            "5) 单季偿还 56 亿长期债务 + 季后再还 15 亿，资产负债表改善；6) VMware Private AI Cloud 打开私有云 AI 增量。"
        ),
        "risks": (
            "1) 客户高度集中：AI 半导体收入来自 6 个 XPU 客户，任一超大客户削减 GW 级承诺都是重击；"
            "2) 依赖 Apollo / Blackstone 等融资工具支撑 20GW+ 算力部署，结构复杂且逐案评估；"
            "3) 土地/电力/机壳可得性决定部署节奏，公司已按此折算展望——若基建延期，收入确认会顺延；"
            "4) 磷化铟、激光器、基板（新加坡）产能爬坡不及预期；5) AI 占比提升会稀释毛利率（Q3 已降至 76.3%），"
            "靠经营杠杆维持 OPM；6) 技术面仍在 SMA200 下方，趋势尚未反转，若跌破 335（Donchian 下轨）需尊重价格。"
        ),
        "position_pct": 9.0,
        "invalidation": (
            "降级条件：任一超大客户（Google / OpenAI / Anthropic / Meta）公开削减或延期 GW 级部署承诺，"
            "或 AI 半导体收入首次出现环比负增长，或 FY27 AI 指引被下调至 1000 亿以下——任一触发即降至 hold 并减仓一半。"
            "技术面跌破 335（近 20 日 Donchian 下轨）且无基本面支撑则先止损。"
        ),
    },
    {
        "symbol": "AMD",
        "recommendation": "hold",
        "confidence": 62.0,
        "horizon": "swing",
        "thesis": (
            "基本面确实是历史最强：Q2 营收 +50% 创纪录，数据中心 +107% 至 67 亿（占比从 42% 升到 58%），"
            "non-GAAP 毛利率 56%、OPM 27%（同比 +15pct）、EPS +82%；Helios 机架平台已投产并被 Anthropic、Meta、Microsoft、OpenAI、Oracle 采用，"
            "与 Anthropic 达成最多 2GW MI450 的战略合作（首个 GW 2027 上半年），与微软扩展到 Azure 大规模部署；"
            "EPYC Venice（Zen 6 / 2nm）投产，ROCm.ai 发布，长期 TAM 与财务目标全面上调（FY2030 AI 加速器 TAM 约 1.4 万亿美元）。"
            "问题完全在价格：现价 614.61，年初至今 +175.03%、近 6 个月 +199.27%、近 1 年 +284.64%，"
            "高于 SMA200 达 70.42%、高于 SMA20 达 19.81%，距 52 周高点仅 -1.61%，RSI 71.0 超买。"
            "市场已经在讨论「600 美元以上是否拆股」和「年内 +187% 是否该获利了结」——这类讨论本身就是筹码结构变脆的信号。"
            "此外游戏业务 -31%、2026 年服务器 CPU 供应偏紧、出口管制仍是活风险。"
            "结论：中期逻辑成立，但此刻的预期已经打满（2027 年数据中心翻倍以上是共识预期而非超预期），"
            "此位置不建新仓，等回踩 SMA20（约 513）或 Q3 财报确认 Helios 出货节奏。"
        ),
        "catalysts": (
            "1) Q3 指引营收约 130 亿（+41%）兑现；2) Helios 机架 Q3 晚些时候开始出货、Q4 至 2027 放量（Lisa Su 称需求超最初预测）；"
            "3) Anthropic 首个 GW 的 MI450 于 2027 上半年部署；4) EPYC Venice 在 OEM 与云厂商落地，"
            "管理层预计下半年服务器 CPU +80% 以上、2027 年 +70% 以上；5) ROCm.ai 带来生态迁移（超 300 万模型开箱即跑）；"
            "6) 2027 年数据中心分部营收翻倍以上。"
        ),
        "risks": (
            "1) 估值极度拉伸：高于 SMA200 70%、YTD +175%，任何不及预期都会被放大；2) 游戏业务 -31%（半定制 SoC 出货减少）；"
            "3) 2026 年服务器 CPU 供应偏紧，供应到 2027 年才改善；4) 美国 BIS 持续收紧先进 AI 芯片出口管制，"
            "去年曾因 MI308 计提 8 亿美元存货减值；5) ROCm 相对 CUDA 的生态差距仍是长期摩擦；"
            "6) 数据中心 AI 产品毛利率低于公司平均，放量可能稀释整体毛利；7) 与英伟达的直接竞争（未来 12 个月谁跑赢存在分歧）。"
        ),
        "position_pct": 3.0,
        "invalidation": (
            "升级为 buy 的条件：回踩 SMA20（约 513）后企稳，且 Q3 财报确认 Helios 出货与数据中心环比增速 >15%。"
            "降级为 reduce 的条件：Helios 出货延期至 2027 年之后，或数据中心收入环比增速低于 10%，或新增重大出口管制限制——"
            "任一触发即降至 reduce 并减仓一半。"
        ),
    },
]


def main() -> None:
    res = post("/events", {"agent": AGENT, "events": EVENTS})
    print("events:", json.dumps(res, ensure_ascii=False))

    res = post("/analysis", {"agent": AGENT, "analyses": ANALYSES})
    print("analysis:", json.dumps(res, ensure_ascii=False))

    res = post("/done", {"agent": AGENT,
                         "note": "完成 7 家（MSFT/GOOGL/AAPL/META/AMZN/AVGO/AMD）近 90 天情报抓取："
                                 "32 条事件 + 7 条建议，全部带真实来源链接。"})
    print("done:", json.dumps(res, ensure_ascii=False))


if __name__ == "__main__":
    main()
