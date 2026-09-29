/**
 * AI 调用层（AI Task Hub 的前端入口）
 * ==================================
 * 全平台所有 AI 接入点都通过 `aiAssist()` 调用同一个后端端点
 * `POST /api/ai/assist`，因此：
 *   · 后端只维护一份「任务注册表」（backend/app/ai_tasks*.py）；
 *   · 前端不需要为每个功能点各写一个请求函数；
 *   · AI 网关配置统一来自「设置 → AI 分析」，改一处全站生效。
 *
 * 与 `api.ts` 的分工：本文件只做**AI 语义**的封装（任务名、超时、状态缓存），
 * 底层 HTTP/鉴权/错误提取仍复用 `api`。
 */
import { api } from './api'

export interface AiTaskResult {
  task: string
  title: string
  /** llm = 大模型生成；local = 未配置 LLM 时的确定性规则化兜底 */
  engine: 'llm' | 'local'
  text: string
  facts?: Record<string, any>
  /**
   * 结构化结果 —— 仅「需要被前端消费」的任务才有（如 `smart_screen` 返回可直接
   * 应用回筛选面板的条件）。后端登记任务时挂了 `parse` 钩子才会出现。
   */
  data?: Record<string, any>
  /** LLM 调用失败的原因（此时 text 是本地兜底结果，不是错误） */
  llm_error?: string
}

export interface AiTaskInfo {
  key: string
  title: string
  desc: string
}

export interface AiStatus {
  llm_configured: boolean
  base_url?: string
  model?: string
  extra_models?: string[]
  note?: string
}

/**
 * 单次 AI 任务的最长等待。
 * 后端每次 LLM 调用 httpx 超时 180s（推理型模型先写思维链，实测单次 40~90s）；
 * 若模型空返回且响应较快，后端还会再补试一次，因此最坏约 360s 理论上限。
 * 这里给到 240s —— 覆盖「单次慢调用」，但不至于让用户对着转圈等太久。
 */
const ASSIST_TIMEOUT = 240_000

export function aiAssist(
  task: string,
  payload: Record<string, any> = {},
  opts: { model?: string; forceLocal?: boolean; timeoutMs?: number } = {},
): Promise<AiTaskResult> {
  return api.post<AiTaskResult>(
    '/ai/assist',
    {
      task,
      payload,
      model: opts.model || '',
      force_local: !!opts.forceLocal,
    },
    opts.timeoutMs ?? ASSIST_TIMEOUT,
  )
}

export function listAiTasks(): Promise<{ items: AiTaskInfo[] }> {
  return api.get<{ items: AiTaskInfo[] }>('/ai/tasks')
}

/* ------------------------------------------------------------------
 * AI 状态（llm_configured / 可选模型）
 * 多个 AIAssist 实例会同时挂载，因此做一次进程内缓存 + 请求合并，
 * 避免一个页面出现十几个 AI 卡片就打十几次 /ai/status。
 * ------------------------------------------------------------------ */
let _statusPromise: Promise<AiStatus> | null = null

export function getAiStatus(force = false): Promise<AiStatus> {
  if (force || !_statusPromise) {
    _statusPromise = api
      .get<AiStatus>('/ai/status')
      .catch(() => ({ llm_configured: false, extra_models: [] }) as AiStatus)
  }
  return _statusPromise
}

/** 配置变更（保存 AI 设置）后调用，让下次读取拿到最新状态。 */
export function invalidateAiStatus() {
  _statusPromise = null
}
