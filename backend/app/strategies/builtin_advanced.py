"""
内置策略 —— 进阶/前沿族（对应 2026 年机构与卖方研究主流做法）
================================================================
注册表 barrel：策略类本体已按族拆到 `advanced/` 包
（FILE_SIZE_DEBT Batch E-2），import 本模块即触发全部注册，
`builtin_advanced.XXX` 的旧类引用路径经 re-export 保持不变。

- 多因子机器学习 Alpha（walk-forward 滚动训练，杜绝前视偏差）
- 波动率管理动量（Moreira & Muir）—— 用上一期已实现方差缩放动量仓位
- 状态自适应（趋势 / 均值回归随波动率与效率比切换）
- Dual Thrust 区间突破
- VCP 波动收缩突破（Minervini 形态量化）
- 网格交易
- 风险平价配置（inverse-vol）
- 多策略集成投票
- 多因子打分选股（透明量价因子）
"""
from __future__ import annotations

# 导入即注册（@register 在类定义时执行）
from .advanced.alloc import RiskParityAlloc  # noqa: F401
from .advanced.breakout import DualThrust, VcpBreakout  # noqa: F401
from .advanced.ensemble import EnsembleVote  # noqa: F401
from .advanced.factor import MultiFactorScore  # noqa: F401
from .advanced.grid import GridTrading  # noqa: F401
from .advanced.ml import MlAlphaRidge  # noqa: F401
from .advanced.regime import RegimeAdaptive  # noqa: F401
from .advanced.trend import VolManagedMomentum  # noqa: F401

__all__ = [
    "MlAlphaRidge", "VolManagedMomentum", "RegimeAdaptive", "DualThrust",
    "VcpBreakout", "GridTrading", "RiskParityAlloc", "EnsembleVote",
    "MultiFactorScore",
]
