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


def _auth_ws(ws: WebSocket) -> str | None:
    token = ws.query_params.get("token") or ""
    if not token:
        header = ws.headers.get("authorization", "")
        if header.lower().startswith("bearer "):
            token = header[7:]
    payload = decode_access_token(token)
    return payload.get("sub") if payload else None


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
      → {"action": "sub"|"unsub", "topics": ["quotes:AAPL,SPY", "intraday:AAPL", "alerts"]}
      ← {"topic": "quotes", "ts": ..., "data": [...]}   2 秒一拍
      ← {"topic": "alerts", "ts": ..., "data": [...]}   新事件即时
      ← {"topic": "ack", "data": {"subscribed": [...]}}
    """
    if not _auth_ws(ws):
        await ws.close(code=4401)
        return
    await ws.accept()
    loop = asyncio.get_running_loop()
    conn = realtime.register(loop)

    async def _sender() -> None:
        try:
            while True:
                msg = await conn.queue.get()
                await ws.send_text(json.dumps(msg, ensure_ascii=False, default=str))
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            return

    sender = asyncio.create_task(_sender())
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except (ValueError, TypeError):
                continue
            action = str(msg.get("action", ""))
            topics = [str(t) for t in (msg.get("topics") or [])][:20]
            if action == "sub":
                realtime.subscribe(conn, topics)
            elif action == "unsub":
                realtime.unsubscribe(conn, topics)
            conn.push({"topic": "ack", "data": {"subscribed": sorted(conn.topics)}})
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
