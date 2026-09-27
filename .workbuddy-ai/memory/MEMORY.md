# QuantDesk for IBKR — 项目长期备忘

## 仓库与版本控制
- **远端**：`git@github.com:louis00009/rich-us.git`（**SSH**）
  - ⚠️ 本机 **HTTPS 到 github.com 有 TLS 问题**（`schannel: server closed abruptly`），
    不要改用 HTTPS 远端。
  - 认证方式：`~/.ssh/id_rsa`（公钥已注册到 GitHub 账号 louis00009）。
- **分支**：`main`，已设 upstream → 日常 `git push` 即可。
- 非交互环境推送用：
  `GIT_SSH_COMMAND="ssh -o BatchMode=yes" git push`
  （否则凭据提示会挂死）。
- 首次提交：`b88b8d8`（2026-09-27，167 文件）。

## 密钥与忽略规则（重要）
- `backend/runtime/` 内有 **`.secret`（Fernet key + JWT secret）**、
  **`.env`（FINNHUB_API_KEY、QD_ALLOW_LIVE_TRADING）**、`quantdesk.db` —— 全部已在
  `.gitignore` 中排除。
- **已忽略**：`backend/runtime/*`、`.backup-*/`、`frontend/.cdp-profile/`、
  `backend/_checks_out.txt`、`*_checks_out.txt`、`node_modules/`、`dist/`、`.venv/`。
- **教训**：`backend/_checks_out.txt`（自检输出日志）曾含真实 FINNHUB key 且不在任何
  ignore 规则内 —— **提交前必须做内容级密钥扫描**，不能只依赖 `.gitignore`。
- 可复用流程见用户级 skill：`git-safe-publish`。

## 开发约定（来自 TODO.md 铁律 + 本轮验证）
- 后端只监听 `127.0.0.1`；涨红跌绿（`format.ts`）。
- **无未来函数**：第 t 根收盘信号在第 t+1 根开盘成交（`backtest.py`）；
  实盘引擎已按此对齐（取已完成的 bar）。
- 回测 / 实盘共用同一套 `StopTracker`（`risk/stops.py`）。
- **`async def` 端点内不得直接做同步 DB I/O** —— SQLite 写锁 + commit 会冻结整个
  事件循环。一律 `await run_in_threadpool(...)`，或把端点写成同步 `def`。
  ⚠️ 例外：`engine_start` 等**不能**改同步 `def` —— `task.start()` 内部调
  `asyncio.create_task()`，在线程池里没有运行中的事件循环会抛 `RuntimeError`。
- **`create_all` 不会给已存在的表补索引/列** —— 老库要显式
  `CREATE INDEX IF NOT EXISTS`（见 `database.py` 的 `_MIGRATE_INDEXES`）与 `ALTER TABLE`。
- 前端 hooks 必须在 early return 之前（React #300 白屏教训），构建链已固化
  `npm run lint:hooks`。

## 测试与验证
- 后端：`cd backend && .venv/Scripts/python.exe ../tests/run_checks.py [data|strategies|optimize|api]`
  - 用 `TestClient(app)` **进程内**运行，无需启动服务。
  - ⚠️ 网络受限时 `data`/`all` 子集极慢（yfinance 每标的 20s 超时），**建议按子集跑**。
- 前端：`npm run typecheck` / `npm run lint:hooks` / `npm run build` /
  `npm run test:topics`（WS 主题契约回归，10 项）/
  `npm run smoke`（需后端已启动）。
- **本环境 FastAPI 用惰性 `_IncludedRouter`，`app.routes` 不展开子路由** ——
  遍历它只能看到 8 条，会误判"端点不存在"。要做路由级检查需递归展开，
  或改用 `inspect.iscoroutinefunction` + `getsource` 静态扫描 `app/api/*`。
