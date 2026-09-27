"""WebSocket 实时推送：行情 / 账户心跳 / 主题订阅 hub（秒级）。"""
from __future__ import annotations

import asyncio
import datetime as dt
import json

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool

from .. import realtime, state as appstate
from ..brokers import get_broker
from ..data_provider import get_quotes
from ..security import decode_access_token

router = APIRouter(tags=["实时推送"])

MAX_SYMBOLS = 30
AUTH_TIMEOUT_SEC = 10.0   # 首帧鉴权的等待上限


def _subject_from_token(token: str) -> str | None:
    payload = decode_access_token(token) if token else None
    return payload.get("sub") if payload else None


def _auth_from_header_or_query(ws: WebSocket) -> str | None:
    """非首帧来源的鉴权：Authorization 头 > `?token=` 查询串。

    P1-11：查询串会把 JWT 写进浏览器历史 / 反向代理访问日志 / Referer，
    因此**不再是首选**；这里仅作为向后兼容（旧客户端、测试脚本）保留。
    """
    header = ws.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        sub = _subject_from_token(header[7:])
        if sub:
            return sub
    return _subject_from_token(ws.query_params.get("token") or "")


def _auth_ws(ws: WebSocket) -> str | None:
    """旧签名（`/ws/stream` 沿用）：仅 Authorization 头 + 查询串。"""
    return _auth_from_header_or_query(ws)


def _quotes_preferring_broker(symbols: list[str]) -> list[dict]:
    """实盘场景下必须用券商的行情，否则会出现「看到的价格 ≠ 成交的价格」。"""
    try:
        cfg = appstate.get_broker_settings()
        if str(cfg.get("provider")) == "ibkr":
            broker, _ = get_broker(cfg)
            rows = broker.quotes(symbols)
            if rows and any(r.get("price", 0) > 0 for r in rows):
                return rows
    except Exception:  # noqa: BLE001
        pass
    return get_quotes(symbols)


@router.websocket("/ws")
async def hub(ws: WebSocket) -> None:
    """主题订阅式实时推送（T-106，秒级）。

    协议：
      → {"action": "auth", "token": "<JWT>"}            ← 首帧鉴权（推荐，P1-11）
      → {"action": "sub"|"unsub", "topics": ["quotes:AAPL,SPY", "intraday:AAPL", "alerts"]}
      ← {"topic": "quotes", "ts": ..., "data": [...]}   2 秒一拍
      ← {"topic": "alerts", "ts": ..., "data": [...]}   新事件即时
      ← {"topic": "ack", "data": {"subscribed": [...]}}

    鉴权来源优先级：首帧 auth > Authorization 头 > `?token=` 查询串（后两者向后兼容）。
    """
    await ws.accept()
    # P1-11：token 优先从**首帧**取 —— 不再要求把 JWT 放进 URL 查询串
    # （那会写进浏览器历史 / 反向代理访问日志 / Referer）。
    user = _auth_from_header_or_query(ws)
    first_msg: dict | None = None
    if not user:
        try:
            raw = await asyncio.wait_for(ws.receive_text(), timeout=AUTH_TIMEOUT_SEC)
            parsed = json.loads(raw)
            first_msg = parsed if isinstance(parsed, dict) else None
        except Exception:  # noqa: BLE001 —— 超时 / 非法帧 / 客户端直接断开
            await ws.close(code=4401)
            return
        if first_msg and str(first_msg.get("action", "")) == "auth":
            user = _subject_from_token(str(first_msg.get("token") or ""))
        if not user:
            await ws.close(code=4401)
            return

    loop = asyncio.get_running_loop()
    conn = realtime.register(loop)

    def _apply(msg: dict) -> None:
        action = str(msg.get("action", ""))
        topics = [str(t) for t in (msg.get("topics") or [])][:20]
        if action == "sub":
            realtime.subscribe(conn, topics)
        elif action == "unsub":
            realtime.unsubscribe(conn, topics)
        # P1-6 配套：用 snapshot() 而不是直接迭代 conn.topics（跨线程安全）
        conn.push({"topic": "ack", "data": {"subscribed": sorted(conn.snapshot())}})

    async def _sender() -> None:
        try:
            while True:
                msg = await conn.queue.get()
                await ws.send_text(json.dumps(msg, ensure_ascii=False, default=str))
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            return

    sender = asyncio.create_task(_sender())
    try:
        # 首帧若不是 auth（例如直接发了 sub），也要照常处理，避免丢掉订阅
        if first_msg is not None:
            _apply(first_msg)
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except (ValueError, TypeError):
                continue
            _apply(msg)
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        pass
    finally:
        sender.cancel()
        realtime.unregister(conn)


@router.websocket("/ws/stream")
async def stream(
    ws: WebSocket,
    symbols: str = Query("SPY,QQQ"),
    interval: int = Query(10, ge=3, le=300),
    include_account: bool = Query(True),
) -> None:
    if not _auth_ws(ws):
        await ws.close(code=4401)
        return
    await ws.accept()

    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()][:MAX_SYMBOLS]
    mode = await run_in_threadpool(appstate.effective_mode)   # P1-9：与下单通道同源（UI 开关 ∧ 端口）
    await ws.send_text(json.dumps({"type": "hello", "symbols": syms, "interval": interval, "mode": mode}))

    try:
        while True:
            try:
                quotes = await run_in_threadpool(_quotes_preferring_broker, syms)
            except Exception as exc:  # noqa: BLE001
                quotes = []
                await ws.send_text(json.dumps({"type": "error", "message": str(exc)}))
            payload: dict = {
                "type": "tick",
                "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
                "quotes": quotes,
            }
            if include_account:
                try:
                    cfg = await run_in_threadpool(appstate.get_broker_settings)
                    broker, broker_mode = get_broker(cfg)
                    acc = await run_in_threadpool(broker.account)
                    payload["account"] = acc.dict()
                    payload["broker_mode"] = broker_mode
                except Exception as exc:  # noqa: BLE001
                    payload["account"] = {"connected": False, "message": str(exc)}
            await ws.send_text(json.dumps(payload, ensure_ascii=False, default=str))
            await asyncio.sleep(interval)
    except WebSocketDisconnect:
        return
    except Exception:  # noqa: BLE001
        try:
            await ws.close()
        except Exception:  # noqa: BLE001
            pass
