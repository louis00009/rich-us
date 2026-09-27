"""API 路由聚合。"""
from fastapi import APIRouter

from . import ai, alerts, auth, backtest, intel, market, news, ops, optimize, rankings, risk, strategies, system, trading, watchlist, ws

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(system.router)
api_router.include_router(ops.router)
api_router.include_router(market.router)
api_router.include_router(news.router)
api_router.include_router(rankings.router)
api_router.include_router(watchlist.router)
api_router.include_router(alerts.router)
api_router.include_router(strategies.router)
api_router.include_router(backtest.router)
api_router.include_router(optimize.router)
api_router.include_router(trading.router)
api_router.include_router(risk.router)
api_router.include_router(ai.router)
api_router.include_router(intel.router)
api_router.include_router(ws.router)

__all__ = ["api_router"]
