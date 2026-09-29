"""打印一个本机可用的访问令牌（供 visual 回归脚本使用）
=====================================================

四个真实浏览器回归脚本都要传 `<url> <token>`：

    cd frontend
    TOKEN=$(cd ../backend && .venv/Scripts/python.exe ../tools/mint_token.py)
    npm run test:visual:intel -- http://127.0.0.1:8787/intel "$TOKEN"

**为什么要单独做个小工具**：`create_access_token` 有两个极易踩的坑，踩了之后
表现是「token 能打印、但登录态静默失效，一路 FAIL」，很难定位：

  1. 它在 `app.security`，**不是** `app.auth`（导入错会 ModuleNotFoundError）；
  2. 签名是 `create_access_token(subject: str, extra: dict)`，**且返回 tuple `(token, expiry)`** ——
     直接把 dict 当第一个参数传，或忘了解包，都会得到坏 token。

本工具按正确姿势调用并只打印 token 本身，方便 `$(...)` 捕获。

用法：
    cd backend && .venv/Scripts/python.exe ../tools/mint_token.py [用户名]

⚠️ 会读本机数据库；输出的是**短期 bearer token**，只在本机用，不要贴进 issue / 提交信息。
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from app.database import init_db, session_scope  # noqa: E402
from app.models import User  # noqa: E402
from app.security import create_access_token  # noqa: E402


def main() -> int:
    username = sys.argv[1] if len(sys.argv) > 1 else ""
    init_db()
    with session_scope() as db:
        q = db.query(User)
        u = q.filter(User.username == username).first() if username else q.first()
        if not u:
            print(f"找不到用户：{username or '(库中无任何用户)'}", file=sys.stderr)
            return 1
        # ⚠️ 必须解包：返回的是 (token, expiry)
        result = create_access_token(u.username, {"uid": u.id})
        token = result[0] if isinstance(result, tuple) else result
    # 只把 token 打到 stdout（日志走 stderr），方便 `$(...)` 干净捕获
    print(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
