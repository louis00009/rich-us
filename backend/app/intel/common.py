"""intel 共享原语（FILE_SIZE_DEBT Batch F-1 从 intel.py 拆出）。

常量（事件类别/阶段/情绪/建议/周期）+ log + REPORT_DIR + ORM 模型 re-export。
"""
from __future__ import annotations

import logging

from ..config import RUNTIME_DIR
from ..models import (  # noqa: F401 —— 供各域文件 from .common import
    IntelAnalysis,
    IntelBridgeLog,
    IntelCompany,
    IntelEvent,
    IntelRun,
    IntelSetting,
)

log = logging.getLogger("quantdesk.intel")  # noqa: F401

REPORT_DIR = RUNTIME_DIR / "intel" / "reports"  # noqa: F401


EVENT_CATEGORIES = {
    "model_release": "模型发布",
    "product_launch": "产品发布",
    "partnership": "合作/联盟",
    "earnings": "财报/业绩",
    "regulatory": "监管/政策",
    "personnel": "人事变动",
    "macro": "宏观/行业",
    "other": "其他",
}
# 前瞻管道阶段：财报滞后，用合同/订单管道前瞻未来 3-6 个月经营可见性
EVENT_STAGES = {
    "confirmed": "已敲定",
    "negotiating": "在谈",
    "rumor": "传闻",
}
SENTIMENTS = {"positive", "neutral", "negative"}
RECOMMENDATIONS = {"strong_buy", "buy", "hold", "reduce", "avoid"}
HORIZONS = {"intraday", "swing", "position"}
REC_CN = {
    "strong_buy": "强烈买入",
    "buy": "买入",
    "hold": "持有",
    "reduce": "减持",
    "avoid": "回避",
}

