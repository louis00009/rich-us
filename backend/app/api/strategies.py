"""策略接口：内置策略库、自定义策略 CRUD、规则/代码校验。"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from .. import state as appstate
from ..schemas import StrategyConfigIn, StrategyConfigOut, ValidateCodeRequest
from ..strategies import categories, list_strategies
from ..strategies.indicators import INDICATOR_CATALOG
from ..strategies.custom import (
    ALLOWED_RULE_INDICATORS,
    OPS,
    CodeSecurityError,
    RuleError,
    validate_code,
    validate_rule,
)
from ..models import StrategyConfig
from .deps import CurrentUser, DbSession

router = APIRouter(prefix="/strategies", tags=["策略"])


def _row_out(r: StrategyConfig) -> StrategyConfigOut:
    def _j(s: str, default):  # noqa: ANN001
        try:
            return json.loads(s) if s else default
        except json.JSONDecodeError:
            return default

    return StrategyConfigOut(
        id=r.id, name=r.name, kind=r.kind, strategy_key=r.strategy_key,
        params=_j(r.params_json, {}), rule=_j(r.rule_json, None) or None,
        code=r.code or "", symbols=_j(r.symbols_json, []), risk=_j(r.risk_json, {}),
        notes=r.notes or "", tags=_j(r.tags_json, []), is_active=bool(r.is_active),
        created_at=r.created_at.isoformat() if r.created_at else "",
        updated_at=r.updated_at.isoformat() if r.updated_at else "",
    )


@router.get("")
def list_all(user: CurrentUser = None) -> dict:  # noqa: ARG001
    return {
        "builtin": list_strategies(),
        "categories": categories(),
        "count": len(list_strategies()),
    }


@router.get("/dsl")
def dsl_meta(user: CurrentUser = None) -> dict:  # noqa: ARG001
    """规则 DSL 与代码沙箱的元信息，前端据此渲染可视化编辑器。"""
    return {
        "operators": [
            {"key": ">", "label": "大于"}, {"key": "<", "label": "小于"},
            {"key": ">=", "label": "大于等于"}, {"key": "<=", "label": "小于等于"},
            {"key": "cross_above", "label": "上穿"}, {"key": "cross_below", "label": "下穿"},
        ],
        "indicator_groups": INDICATOR_CATALOG,
        "allowed_indicators": ALLOWED_RULE_INDICATORS,
        "ops": OPS,
        "code_template": (
            "# ctx.closes -> DataFrame(index=日期, columns=标的)\n"
            "# ctx.data[sym] -> DataFrame(open/high/low/close/volume)\n"
            "# 返回: DataFrame(index=日期, columns=标的, values=目标权重 ∈ [-1, 1])\n"
            "# 仅可使用 pd / np / math / statistics；禁止 eval、exec、open、__import__\n\n"
            "import pandas as pd\n"
            "import numpy as np\n\n"
            "def generate(ctx):\n"
            "    c = ctx.closes\n"
            "    fast = c.ewm(span=20, adjust=False).mean()\n"
            "    slow = c.ewm(span=100, adjust=False).mean()\n"
            "    w = pd.DataFrame(0.0, index=c.index, columns=c.columns)\n"
            "    w[fast > slow] = 1.0\n"
            "    return w\n"
        ),
        "code_limits": {"max_chars": 8000, "allowed_imports": ["pandas", "numpy", "math", "statistics", "datetime"]},
        "sandbox_note": "代码策略经 AST 白名单校验后在受限命名空间中执行，仅建议在本地单用户环境使用。",
    }


@router.get("/custom")
def list_custom(db: DbSession, user: CurrentUser) -> dict:  # noqa: ARG001
    rows = db.execute(select(StrategyConfig).order_by(StrategyConfig.updated_at.desc())).scalars().all()
    return {"items": [_row_out(r) for r in rows]}


@router.post("/custom", response_model=StrategyConfigOut)
def create_custom(payload: StrategyConfigIn, db: DbSession, user: CurrentUser) -> StrategyConfigOut:
    exists = db.execute(select(StrategyConfig).where(StrategyConfig.name == payload.name)).scalars().first()
    if exists:
        raise HTTPException(409, f"策略名称「{payload.name}」已存在")

    if payload.kind == "builtin" and not payload.strategy_key:
        raise HTTPException(400, "内置策略必须指定 strategy_key")
    if payload.kind == "rule":
        try:
            validate_rule(payload.rule or {})
        except RuleError as exc:
            raise HTTPException(400, f"规则校验失败：{exc}") from exc
    if payload.kind == "code":
        try:
            validate_code(payload.code)
        except CodeSecurityError as exc:
            raise HTTPException(400, f"代码安全校验失败：{exc}") from exc

    row = StrategyConfig(
        name=payload.name, kind=payload.kind,
        strategy_key=payload.strategy_key or ("custom_rule" if payload.kind == "rule" else "custom_code"),
        params_json=json.dumps(payload.params, ensure_ascii=False),
        rule_json=json.dumps(payload.rule, ensure_ascii=False) if payload.rule else "",
        code=payload.code, symbols_json=json.dumps(payload.symbols),
        risk_json=json.dumps(payload.risk, ensure_ascii=False),
        notes=payload.notes, tags_json=json.dumps(payload.tags, ensure_ascii=False),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    appstate.log("strategy_create", "INFO", f"创建策略 {row.name}（{row.kind}）", actor=user.username)
    return _row_out(row)


@router.put("/custom/{sid}", response_model=StrategyConfigOut)
def update_custom(sid: int, payload: StrategyConfigIn, db: DbSession, user: CurrentUser) -> StrategyConfigOut:
    row = db.get(StrategyConfig, sid)
    if not row:
        raise HTTPException(404, "策略不存在")
    dup = db.execute(
        select(StrategyConfig).where(StrategyConfig.name == payload.name, StrategyConfig.id != sid)
    ).scalars().first()
    if dup:
        raise HTTPException(409, f"策略名称「{payload.name}」已被占用")
    if payload.kind == "rule":
        try:
            validate_rule(payload.rule or {})
        except RuleError as exc:
            raise HTTPException(400, f"规则校验失败：{exc}") from exc
    if payload.kind == "code":
        try:
            validate_code(payload.code)
        except CodeSecurityError as exc:
            raise HTTPException(400, f"代码安全校验失败：{exc}") from exc

    row.name = payload.name
    row.kind = payload.kind
    row.strategy_key = payload.strategy_key or ("custom_rule" if payload.kind == "rule" else "custom_code")
    row.params_json = json.dumps(payload.params, ensure_ascii=False)
    row.rule_json = json.dumps(payload.rule, ensure_ascii=False) if payload.rule else ""
    row.code = payload.code
    row.symbols_json = json.dumps(payload.symbols)
    row.risk_json = json.dumps(payload.risk, ensure_ascii=False)
    row.notes = payload.notes
    row.tags_json = json.dumps(payload.tags, ensure_ascii=False)
    db.commit()
    db.refresh(row)
    appstate.log("strategy_update", "INFO", f"更新策略 {row.name}", actor=user.username)
    return _row_out(row)


@router.delete("/custom/{sid}")
def delete_custom(sid: int, db: DbSession, user: CurrentUser) -> dict:
    row = db.get(StrategyConfig, sid)
    if not row:
        raise HTTPException(404, "策略不存在")
    name = row.name
    db.delete(row)
    db.commit()
    appstate.log("strategy_delete", "WARN", f"删除策略 {name}", actor=user.username)
    return {"ok": True, "message": f"已删除策略「{name}」"}


@router.post("/validate-rule")
def check_rule(payload: dict, user: CurrentUser) -> dict:  # noqa: ARG001
    try:
        norm = validate_rule(payload)
        return {"ok": True, "normalized": norm}
    except RuleError as exc:
        return {"ok": False, "error": str(exc)}


@router.post("/validate-code")
def check_code(payload: ValidateCodeRequest, user: CurrentUser) -> dict:  # noqa: ARG001
    try:
        validate_code(payload.code)
        return {"ok": True, "message": "代码通过 AST 白名单校验"}
    except CodeSecurityError as exc:
        return {"ok": False, "error": str(exc)}
