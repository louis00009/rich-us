/**
 * 构建前置步骤
 * =============
 * 部分环境（如启用了 safe-delete 保护的主机）会拦截 fs.rmSync，
 * 导致 Vite 的 emptyOutDir 阶段失败。
 *
 * 这里改用「重命名归档」代替删除：把上一次的 dist 移到 dist.old-<时间戳>，
 * 既让 Vite 面对一个干净目录，又不真正销毁任何文件。
 * 归档目录只保留最近 2 个，更早的尝试删除（失败则忽略）。
 */
import { existsSync, mkdirSync, readdirSync, renameSync, rmSync, statSync } from 'node:fs'
import { resolve } from 'node:path'

// 每次构建自动刷新 index.html 的 qd-build 版本标记（用户可据此确认浏览器拿到的是新版）
import { readFileSync, writeFileSync } from 'node:fs'
const INDEX = resolve('index.html')
const d0 = new Date()
  const p2 = (n) => String(n).padStart(2, '0')
  const stamp = `${d0.getFullYear()}-${p2(d0.getMonth() + 1)}-${p2(d0.getDate())} ${p2(d0.getHours())}:${p2(d0.getMinutes())} 本地构建`
try {
  let html = readFileSync(INDEX, 'utf8')
  html = /<meta name="qd-build" content="[^"]*" \/>/.test(html)
    ? html.replace(/<meta name="qd-build" content="[^"]*" \/>/, `<meta name="qd-build" content="${stamp}" />`)
    : html.replace('<title>', `    <meta name="qd-build" content="${stamp}" />\n    <title>`)
  writeFileSync(INDEX, html)
} catch { /* 不阻塞构建 */ }

const DIST = resolve('dist')
const KEEP = 2

function main() {
  if (existsSync(DIST) && readdirSync(DIST).length > 0) {
    const stamp = new Date().toISOString().replace(/[-:T]/g, '').slice(0, 14)
    const target = resolve(`dist.old-${stamp}`)
    try {
      renameSync(DIST, target)
      console.log(`[prebuild] 已归档上一次构建 → ${target.split(/[\\/]/).pop()}`)
    } catch (e) {
      console.log(`[prebuild] 归档失败（忽略，继续构建）: ${e.message}`)
    }
  }

  // 清理过旧的归档（保留最近 KEEP 个）。删除失败不阻塞构建。
  try {
    const archives = readdirSync(resolve('.'))
      .filter((n) => n.startsWith('dist.old-'))
      .map((n) => ({ n, t: statSync(resolve(n)).mtimeMs }))
      .sort((a, b) => b.t - a.t)
    for (const a of archives.slice(KEEP)) {
      try {
        rmSync(resolve(a.n), { recursive: true, force: true })
      } catch {
        /* 环境不允许删除，跳过 */
      }
    }
  } catch {
    /* ignore */
  }

  if (!existsSync(DIST)) mkdirSync(DIST, { recursive: true })
}

main()
