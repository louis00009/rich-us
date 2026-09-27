# Auto News Fetch — 执行记录

- 任务：每 5 分钟触发的自动新闻抓取，脚本内置 14 分钟节流（--throttle-minutes 14 --days 7）。
- 命令：`cd backend && .venv/Scripts/python.exe ../tools/auto_fetch.py --throttle-minutes 14 --days 7`

## 2026-09-26 18:55
- 正常执行（未触发节流跳过）。观察列表 33 家。
- 提交 16 条事件，重复 1 条。有产出的标的：META(3)、V(3)、AMD(2)、CRM(2)、COST(2)、NVDA(1, 重复1)、ASML(1)、IBM(1)。
- 退出码 0，无报错。
