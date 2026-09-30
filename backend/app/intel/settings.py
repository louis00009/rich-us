"""intel 设置与初始化（FILE_SIZE_DEBT Batch F-1 从 intel.py 拆出）。

_gen_token 放本文件（而非文档配方的 bridge.py）：ensure_settings 与 reset_bridge_token
都用它，放这里可断开 settings ↔ bridge 的 import 环。
"""
from __future__ import annotations

import json

from ..database import session_scope
from .common import IntelCompany, IntelSetting


# 默认观察标的：美股核心公司（可增删，存 intel_companies）
DEFAULT_COMPANIES: list[dict[str, str]] = [
    {"symbol": "NVDA", "name": "NVIDIA", "theme": "AI 算力", "focus": "数据中心 GPU/Blackwell/Rubin 节奏、大厂资本开支、出口管制"},
    {"symbol": "MSFT", "name": "Microsoft", "theme": "AI 应用 + 云", "focus": "Azure 增速、Copilot 商业化、OpenAI 关系"},
    {"symbol": "GOOGL", "name": "Alphabet", "theme": "AI + 搜索 + 广告", "focus": "Gemini 迭代、TPU 自研、搜索份额、反垄断"},
    {"symbol": "AAPL", "name": "Apple", "theme": "消费电子 + AI", "focus": "iPhone 周期、Apple Intelligence、中国区销售"},
    {"symbol": "META", "name": "Meta Platforms", "theme": "AI + 社交广告", "focus": "Llama 开源策略、广告推荐效率、 Reality Labs 亏损"},
    {"symbol": "AMZN", "name": "Amazon", "theme": "云 + 电商 + 机器人", "focus": "AWS 增速与利润率、自研 Trainium、物流自动化"},
    {"symbol": "TSLA", "name": "Tesla", "theme": "自动驾驶 + 机器人", "focus": "FSD 进展、Robotaxi/Optimus 里程碑、交付量"},
    {"symbol": "AVGO", "name": "Broadcom", "theme": "AI ASIC + 网络", "focus": "定制 ASIC 客户、VMware 整合、网络芯片"},
    {"symbol": "AMD", "name": "AMD", "theme": "AI 芯片挑战者", "focus": "MI 系列放量、数据中心份额、CPU 竞争"},
    {"symbol": "NFLX", "name": "Netflix", "theme": "流媒体 + 广告", "focus": "订阅/广告层增长、内容投入、涨价节奏"},
    {"symbol": "ORCL", "name": "Oracle", "theme": "云数据库 + OCI", "focus": "OCI 增速、AI 合同积压、Stargate 进展"},
    {"symbol": "CRM", "name": "Salesforce", "theme": "企业软件 + Agent", "focus": "Agentforce 商业化、利润率改善"},
    {"symbol": "JPM", "name": "JPMorgan", "theme": "银行龙头", "focus": "净利息收入、资本市场回暖、信贷质量"},
    {"symbol": "V", "name": "Visa", "theme": "支付网络", "focus": "跨境交易量、稳定币威胁与机会"},
    {"symbol": "WMT", "name": "Walmart", "theme": "零售 + 广告", "focus": "电商增速、会员收入、自动化降本"},
    {"symbol": "COST", "name": "Costco", "theme": "会员制零售", "focus": "会员费提价、电商增长、同店销售"},
    {"symbol": "UNH", "name": "UnitedHealth", "theme": "医疗健康", "focus": "医保赔付率、Optum 增长、监管"},
    {"symbol": "LLY", "name": "Eli Lilly", "theme": "减肥药 + 创新药", "focus": "Zepbound/Mounjaro 放量、产能扩张、管线数据"},
    {"symbol": "XOM", "name": "ExxonMobil", "theme": "能源 + LNG", "focus": "产量指引、炼化利润率、资本回报"},
    {"symbol": "ASML", "name": "ASML", "theme": "光刻机垄断", "focus": "EUV 订单、High-NA 出货、中国区占比"},
]



def ensure_settings() -> IntelSetting:
    """读取（并按需创建）单行设置；bridge_token 为空则生成。"""
    with session_scope() as db:
        row = db.get(IntelSetting, 1)
        if row is None:
            row = IntelSetting(id=1, bridge_token=_gen_token())
            db.add(row)
            db.flush()
        elif not row.bridge_token:
            row.bridge_token = _gen_token()
        if db.dirty:
            db.flush()  # autoflush=False：expunge 前必须先落库，否则修改被静默丢弃
        db.expunge(row)
        return row



def _gen_token() -> str:
    import secrets

    return "qdintel_" + secrets.token_hex(16)



def save_settings(*, interval_minutes: int | None = None, auto_analyze: bool | None = None,
                  ai_scrape: bool | None = None, pinned_symbols: list[str] | None = None,
                  surge_pct: float | None = None,
                  llm_fallback_chain: str | None = None) -> IntelSetting:
    with session_scope() as db:
        row = db.get(IntelSetting, 1)
        if interval_minutes is not None:
            row.interval_minutes = max(5, min(720, int(interval_minutes)))
        if auto_analyze is not None:
            row.auto_analyze = bool(auto_analyze)
        if ai_scrape is not None:
            row.ai_scrape = bool(ai_scrape)
        if pinned_symbols is not None:
            row.pinned_symbols = json.dumps(_norm_pinned(pinned_symbols))
        if surge_pct is not None:
            try:
                row.surge_pct = max(1.0, min(20.0, float(surge_pct)))
            except (TypeError, ValueError):
                pass
        if llm_fallback_chain is not None:
            # 规范化：去空 / 去重保序 / 上限 5 档 / 单档上限 64 字符
            parts, seen = [], set()
            for p in (llm_fallback_chain or "").split(","):
                m = p.strip()[:64]
                if m and m not in seen:
                    seen.add(m)
                    parts.append(m)
                if len(parts) >= 5:
                    break
            row.llm_fallback_chain = ",".join(parts)
        if db.dirty:
            db.flush()  # autoflush=False：expunge 前必须先落库，否则修改被静默丢弃
        db.expunge(row)
        return row


def _norm_chain(raw: str) -> list[str]:
    """模型 fallback 链规范化：去空 / 去重保序 / 上限 5 档。"""
    out: list[str] = []
    for p in (raw or "").split(","):
        m = p.strip()[:64]
        if m and m not in out:
            out.append(m)
    return out[:5]


def chain_list(st: IntelSetting) -> list[str]:
    """读取模型 fallback 链（逗号分隔 → list[str]；损坏按空处理）。"""
    return _norm_chain(st.llm_fallback_chain or "")


def _norm_pinned(raw: list[str]) -> list[str]:
    """重点标的规范化：大写 / 去空格 / 去重保序 / 丢非法项，上限 8 家。"""
    out: list[str] = []
    for x in raw or []:
        sym = str(x or "").strip().upper()[:16]
        if sym and sym not in out:
            out.append(sym)
    return out[:8]


def pinned_list(st: IntelSetting) -> list[str]:
    """读取重点标的清单（JSON 数组字符串 → list[str]；损坏按空处理）。"""
    try:
        data = json.loads(st.pinned_symbols or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return _norm_pinned(data) if isinstance(data, list) else []



def ensure_default_companies() -> None:
    """首次使用时灌入默认美股核心公司（已存在则跳过）。"""
    with session_scope() as db:
        existing = {c.symbol for c in db.query(IntelCompany).all()}
        for item in DEFAULT_COMPANIES:
            if item["symbol"] not in existing:
                db.add(IntelCompany(**item))

