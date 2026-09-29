/**
 * 挑一个**真的能 bind** 的 CDP 调试端口
 * =====================================
 * ⚠️ 为什么不能写死端口：Windows 上有一批端口段被系统保留（Hyper-V / WSL 的动态排除段），
 * 落在里面的端口 bind() 会直接失败：
 *     bind() returned an error: 以一种访问权限不允许的方式做了一个访问套接字的尝试。 (0x271D)
 * 表现为：Chrome 进程活着，但 devtools HTTP server 起不来 → CDP 端口永远连不上，
 * 脚本只报一句含糊的「Chrome 调试端口未就绪」。
 *
 * 本机实测保留段包含 **9320–9419**（`netsh interface ipv4 show excludedportrange protocol=tcp`），
 * 而原来的脚本把端口写死成 9333 / 9334 / 9337 —— 全部踩中，四个 visual 脚本一起静默失效。
 *
 * 所以：不猜端口，启动前先探测。可用 `QD_CDP_PORT=<n>` 显式指定。
 */
import net from 'node:net'

/** 候选端口：9222 是 CDP 惯例端口，且本机不在任何保留段内。 */
export const CANDIDATE_PORTS = [9222, 9223, 9224, 9225, 9226, 9227, 9228, 9229]

/** 端口能否在本机 bind（127.0.0.1）。 */
export function canBind(port) {
  return new Promise((resolve) => {
    const srv = net.createServer()
    srv.once('error', () => resolve(false))
    srv.once('listening', () => srv.close(() => resolve(true)))
    srv.listen(port, '127.0.0.1')
  })
}

/**
 * 返回第一个可 bind 的端口。
 * @param {number} [explicit] 显式指定（来自 QD_CDP_PORT）；给了就直接用，不探测。
 */
export async function pickPort(explicit) {
  if (explicit) return explicit
  for (const p of CANDIDATE_PORTS) {
    if (await canBind(p)) return p
  }
  throw new Error(
    `找不到可用的调试端口（候选 ${CANDIDATE_PORTS.join(' / ')} 全部被占用或在系统保留段内）。` +
      '可先用 netsh interface ipv4 show excludedportrange protocol=tcp 查保留段，再用 QD_CDP_PORT=<n> 指定。',
  )
}

/** 便捷入口：读环境变量 + 探测。 */
export async function resolveDebugPort() {
  const n = Number(process.env.QD_CDP_PORT || 0)
  return pickPort(Number.isFinite(n) && n > 0 ? n : undefined)
}
